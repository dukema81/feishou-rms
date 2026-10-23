# -*- coding: utf-8 -*-
"""飞售 RMS API 集成测试"""
import json

# ---------- 认证 ----------

def test_health(jreq_fn):
    j = jreq_fn("GET", "/api/health")
    assert j["code"] == 200 and j["data"]["ok"]


def test_login_fail(jreq_fn):
    j = jreq_fn("POST", "/api/login", {"username": "admin", "password": "wrong"})
    assert j["code"] == 401


def test_me(jreq_fn, tok):
    j = jreq_fn("GET", "/api/me", token=tok)
    assert j["code"] == 200 and j["data"]["user"]["role"] == "admin"


def test_unauthorized(jreq_fn):
    j = jreq_fn("GET", "/api/commodities")
    assert j["code"] == 401


# ---------- 主数据 ----------

def test_store_crud(jreq_fn, tok):
    j = jreq_fn("POST", "/api/stores", {"code": "STEST", "name": "测试门店", "address": "测试路"}, token=tok)
    assert j["code"] == 200, j
    sid = j["data"]["id"]
    j = jreq_fn("GET", "/api/stores/%d" % sid, token=tok)
    assert j["data"]["name"] == "测试门店"
    j = jreq_fn("POST", "/api/stores", {"code": "STEST", "name": "重复"}, token=tok)
    assert j["code"] == 409


def test_commodity_barcode(jreq_fn, tok):
    j = jreq_fn("GET", "/api/commodities/barcode/6901234500011", token=tok)
    assert j["code"] == 200 and j["data"]["name"] == "可口可乐330ml"
    j = jreq_fn("GET", "/api/commodities/barcode/9999999999999", token=tok)
    assert j["code"] == 404


def test_commodity_dup_barcode(jreq_fn, tok):
    j = jreq_fn("POST", "/api/commodities", {"name": "撞码商品", "barcode": "6901234500011",
                                             "price": 1, "cost": 0.5}, token=tok)
    assert j["code"] == 409


def test_member_create_and_level(jreq_fn, tok):
    j = jreq_fn("POST", "/api/members", {"name": "测试会员", "phone": "13999990000",
                                         "level": "gold", "balance": 100}, token=tok)
    assert j["code"] == 200, j
    code = j["data"]["code"]
    assert code.startswith("M")
    mid = j["data"]["id"]
    j = jreq_fn("GET", "/api/members/%d" % mid, token=tok)
    assert j["data"]["discount_rate"] == 0.9
    # 重复手机号
    j = jreq_fn("POST", "/api/members", {"name": "重复", "phone": "13999990000"}, token=tok)
    assert j["code"] == 409


def test_member_recharge(jreq_fn, tok):
    j = jreq_fn("POST", "/api/members/3/recharge", {"amount_cents": 5000}, token=tok)
    assert j["code"] == 200
    assert j["data"]["balance_cents"] == 5000
    j = jreq_fn("GET", "/api/members/3/txns", token=tok)
    assert j["code"] == 200 and j["data"]["total"] >= 1


def test_promotion_create_overlap(jreq_fn, tok):
    j = jreq_fn("POST", "/api/promotions", {"name": "重叠促销", "ptype": "full_off",
                                            "threshold_cents": 100, "off_cents": 10,
                                            "start_date": "2026-06-01", "end_date": "2027-06-01"}, token=tok)
    assert j["code"] == 422  # 与满30减5重叠


def test_promotion_calc(jreq_fn, tok):
    j = jreq_fn("POST", "/api/promotions/calc", {"subtotal_cents": 1350, "member_level": "gold"}, token=tok)
    assert j["code"] == 200
    d = j["data"]
    # 88折优惠 162 → 余 1188 → gold 0.9 = 1069.2 → 1069
    assert d["promo_off_cents"] == 162
    assert d["paid_cents"] == 1069
    assert d["member_off_cents"] == 119


# ---------- POS 销售 ----------

def _sale(jreq_fn, tok, **over):
    body = {"store_id": 1, "pay_method": "cash",
            "items": [{"commodity_id": 1, "qty": 1}, {"commodity_id": 2, "qty": 1}]}
    body.update(over)
    return jreq_fn("POST", "/api/sales", body, token=tok)


def test_sale_no_member(jreq_fn, tok):
    # 可乐350 + 农夫山泉200 = 550 分；88折优惠 66 → 484
    j = _sale(jreq_fn, tok)
    assert j["code"] == 200, j
    d = j["data"]
    assert d["subtotal_cents"] == 550
    assert d["promo_off_cents"] == 66
    assert d["paid_cents"] == 484
    assert d["no"].startswith("XS")


def test_sale_member_gold(jreq_fn, tok):
    # member 1 = gold: 550 - 66 = 484 × 0.9 = 435.6 → 436
    j = _sale(jreq_fn, tok, member_id=1)
    assert j["code"] == 200, j
    d = j["data"]
    assert d["member_off_cents"] == 48  # 484 - 436
    assert d["paid_cents"] == 436
    assert d["points_earned"] == 43


def test_sale_balance_pay(jreq_fn, tok):
    # member 4 = platinum 余额 500 元 = 50000 分，买 550 分
    j = _sale(jreq_fn, tok, member_id=4, pay_method="balance")
    assert j["code"] == 200, j
    # 余额不足：member 3（normal，余额 0 + 充值 5000 分=50 元），买 4990+ 分
    j = _sale(jreq_fn, tok, member_id=3, pay_method="balance",
              items=[{"commodity_id": 8, "qty": 2}])  # 59.8×2=119.6 元 = 11960 分 > 5000
    assert j["code"] == 422 and "余额" in j["message"]


def test_sale_insufficient_stock(jreq_fn, tok):
    j = _sale(jreq_fn, tok, items=[{"commodity_id": 1, "qty": 99999}])
    assert j["code"] == 422 and "库存不足" in j["message"]


def test_sale_stock_deducted_fefo(jreq_fn, tok):
    # 商品3 薯片：批次 A03(2026-12-22, 60只) 先扣；扣完正好验证 FEFO
    j = jreq_fn("GET", "/api/inventory/summary?store_id=1&commodity_id=3", token=tok)
    before = j["data"]["total"]
    j = _sale(jreq_fn, tok, items=[{"commodity_id": 3, "qty": 5}])
    assert j["code"] == 200, j
    j = jreq_fn("GET", "/api/inventory/summary?store_id=1&commodity_id=3", token=tok)
    assert j["data"]["total"] == before - 5


def test_sale_idempotency(jreq_fn, tok):
    import json as J
    body = {"store_id": 1, "pay_method": "cash", "items": [{"commodity_id": 2, "qty": 1}]}
    from conftest import jreq
    base = jreq_fn.__closure__[0].cell_contents
    h = {"Idempotency-Key": "pytest-idem-001"}
    r1 = jreq(base, "POST", "/api/sales", body, tok, h)
    r2 = jreq(base, "POST", "/api/sales", body, tok, h)
    assert r1["code"] == 200 and r2["code"] == 200
    assert r1["data"]["no"] == r2["data"]["no"]  # 幂等返回同一单


def test_sale_refund(jreq_fn, tok):
    j = _sale(jreq_fn, tok, items=[{"commodity_id": 6, "qty": 2}])
    assert j["code"] == 200, j
    sid = j["data"]["id"]
    inv_before = jreq_fn("GET", "/api/inventory/summary?store_id=1&commodity_id=6", token=tok)["data"]["total"]
    j = jreq_fn("POST", "/api/sales/%d/refund" % sid, {"reason": "pytest"}, token=tok)
    assert j["code"] == 200 and j["data"]["refund_no"].startswith("TH")
    inv_after = jreq_fn("GET", "/api/inventory/summary?store_id=1&commodity_id=6", token=tok)["data"]["total"]
    assert inv_after == inv_before + 2
    # 二次退货拒绝
    j = jreq_fn("POST", "/api/sales/%d/refund" % sid, {}, token=tok)
    assert j["code"] == 422


# ---------- 采购 ----------

def test_purchase_flow(jreq_fn, tok):
    j = jreq_fn("POST", "/api/purchases", {"supplier_id": 2, "store_id": 3,
                                           "items": [{"commodity_id": 5, "qty": 30, "cost_cents": 200,
                                                      "batch_no": "BTEST01", "expiry": "2027-03-01"}]}, token=tok)
    assert j["code"] == 200, j
    pid = j["data"]["id"]
    assert j["data"]["total_cents"] == 6000
    j = jreq_fn("POST", "/api/purchases/%d/transition" % pid, {"action": "to_submitted"}, token=tok)
    assert j["code"] == 200
    j = jreq_fn("POST", "/api/purchases/%d/transition" % pid, {"action": "to_received"}, token=tok)
    assert j["code"] == 200
    inv = jreq_fn("GET", "/api/inventory/summary?store_id=3&commodity_id=5", token=tok)["data"]
    assert inv["total"] == 30
    sup = jreq_fn("GET", "/api/suppliers", token=tok)
    row = [x for x in sup["data"]["items"] if x["id"] == 2][0]
    assert row["payable_cents"] >= 6000
    # 非法流转
    j = jreq_fn("POST", "/api/purchases/%d/transition" % pid, {"action": "to_submitted"}, token=tok)
    assert j["code"] == 422


# ---------- 风险 / 财务 / 仪表盘 ----------

def test_risk_scan_and_resolve(jreq_fn, tok):
    j = jreq_fn("POST", "/api/risks/scan", {}, token=tok)
    assert j["code"] == 200 and j["data"]["created"] >= 1
    assert "expiry_near" in j["data"]["by_type"] or "stock_low" in j["data"]["by_type"]
    j = jreq_fn("GET", "/api/risks?status=open", token=tok)
    rid = j["data"]["items"][0]["id"]
    j = jreq_fn("PUT", "/api/risks/%d/resolve" % rid, {"note": "pytest"}, token=tok)
    assert j["code"] == 200


def test_finance_summary(jreq_fn, tok):
    j = jreq_fn("GET", "/api/finance/summary", token=tok)
    assert j["code"] == 200
    assert j["data"]["income_cents"] > 0
    assert "by_method" in j["data"]


def test_dashboard(jreq_fn, tok):
    j = jreq_fn("GET", "/api/dashboard", token=tok)
    assert j["code"] == 200
    assert j["data"]["sales_today"] >= 1


# ---------- 权限 ----------

def test_cashier_cannot_manage_risk(jreq_fn):
    j = jreq_fn("POST", "/api/login", {"username": "wangn", "password": "123456"})
    ctok = j["data"]["token"]
    assert jreq_fn("GET", "/api/sales", token=ctok)["code"] == 200
    assert jreq_fn("POST", "/api/risks/scan", {}, token=ctok)["code"] == 403


def test_reader_read_only(jreq_fn):
    j = jreq_fn("POST", "/api/login", {"username": "reader01", "password": "123456"})
    rtok = j["data"]["token"]
    assert jreq_fn("GET", "/api/commodities", token=rtok)["code"] == 200
    assert jreq_fn("POST", "/api/sales", {"store_id": 1, "items": [{"commodity_id": 1, "qty": 1}]},
                   token=rtok)["code"] == 403


def test_api_key_auth(jreq_fn, tok):
    j = jreq_fn("POST", "/api/api-keys", {"name": "pytest-key"}, token=tok)
    assert j["code"] == 200
    key = j["data"]["key"]
    r = jreq_fn("GET", "/api/commodities", headers={"X-Api-Key": key})
    assert r["code"] == 200
    # 查询通道
    r = jreq_fn("GET", "/api/dashboard?token=" + key)
    assert r["code"] == 401  # api key 不走 token 通道
    r = jreq_fn("GET", "/api/commodities", headers={"X-Api-Key": "bad"})
    assert r["code"] == 401


# ---------- 同步与导出 ----------

def test_sync(jreq_fn, tok):
    j = jreq_fn("GET", "/api/sync?since=0&entities=sales", token=tok)
    assert j["code"] == 200 and j["data"]["changes"]
    assert j["data"]["changes"][0]["entity"] == "sales"
    j = jreq_fn("GET", "/api/sync?since=0&entities=nope", token=tok)
    assert j["code"] == 422


def test_export_csv(jreq_fn, tok):
    r = jreq_fn("GET", "/api/export/sales?format=csv", token=tok)
    assert r[0] == "raw" and r[1].startswith("﻿no,") or "no," in r[1]
    j = jreq_fn("GET", "/api/export/nope", token=tok)
    assert j["code"] == 404


def test_negative_margin_risk(jreq_fn, tok):
    # 以低于进价卖（可乐进价 220，卖 100）→ 负毛利风险
    j = _sale(jreq_fn, tok, items=[{"commodity_id": 1, "qty": 1, "unit_price_cents": 100}])
    assert j["code"] == 200, j
    assert j["data"]["margin_warnings"]
    j = jreq_fn("GET", "/api/risks?rtype=negative_margin&status=open", token=tok)
    assert j["data"]["total"] >= 1
