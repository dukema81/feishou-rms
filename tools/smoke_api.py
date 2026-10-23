# -*- coding: utf-8 -*-
"""飞售 RMS 冒烟测试：核心业务链路 + API 全量检查（57 项）
用法: python smoke_api.py [base_url]   默认 http://127.0.0.1:8029
幂等化：使用时间戳后缀命名动态资源，可重复执行。
"""
import sys, time, json, urllib.request, urllib.error, urllib.parse
from decimal import Decimal, ROUND_HALF_UP

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8029"
SUF = str(int(time.time()))[-6:]
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PASS, FAIL = [], []

def req(method, path, body=None, tok=None, headers=None):
    path = urllib.parse.quote(path, safe="/?&=.%_")
    h = dict(headers or {})
    if tok:
        h["Authorization"] = "Bearer " + tok
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with OP.open(r, timeout=15) as f:
            raw = f.read().decode("utf-8-sig")
            try:
                return f.status, json.loads(raw)
            except ValueError:
                return f.status, {"_raw": raw}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8-sig"))
        except Exception:
            return e.code, {}

def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("OK  " if cond else "FAIL") + " " + name + ("" if cond else "  <<< " + str(detail)[:200]))

# ============ 1. 健康与认证 ============
s, j = req("GET", "/api/health")
chk("health 200", s == 200 and j["data"]["ok"], j)
s, j = req("POST", "/api/login", {"username": "admin", "password": "123456"})
chk("login admin", s == 200 and j["data"]["token"], j)
TOK = j["data"]["token"]
s, j = req("GET", "/api/me", tok=TOK)
chk("me perms", s == 200 and j["data"]["perms"], j)
s, j = req("POST", "/api/login", {"username": "nobody", "password": "x"})
chk("login bad 401", s == 401, j)
s, j = req("GET", "/api/commodities")
chk("no-auth 401", s == 401, j)
s, j = req("POST", "/api/login", {"username": "reader01", "password": "123456"})
RTOK = j["data"]["token"]
s, j = req("POST", "/api/commodities", {"name": "x"}, tok=RTOK)
chk("reader write 403", s == 403, j)
s, j = req("GET", "/api/dashboard", tok=TOK)
chk("dashboard", s == 200 and "sales_today" in j["data"], j)

# ============ 2. 主数据 ============
s, j = req("POST", "/api/stores", {"code": "SMK" + SUF, "name": "冒烟门店" + SUF, "address": "测试路1号"}, tok=TOK)
chk("store create", s == 200, j)
SID = j["data"]["id"]
s, j = req("GET", "/api/stores", tok=TOK)
chk("store list", s == 200 and j["data"]["total"] >= 4, j)
s, j = req("PUT", "/api/stores/%d" % SID, {"phone": "0571-00000000"}, tok=TOK)
chk("store update", s == 200, j)
s, j = req("POST", "/api/stores", {"code": "SMK" + SUF, "name": "重复"}, tok=TOK)
chk("store dup code 409", s == 409, j)
s, j = req("GET", "/api/commodities", tok=TOK)
chk("commodity list", s == 200 and j["data"]["total"] >= 8, j)
s, j = req("GET", "/api/commodities/barcode/6901234500028", tok=TOK)
chk("commodity barcode", s == 200 and j["data"]["name"] == "农夫山泉550ml", j)
s, j = req("POST", "/api/commodities", {"name": "冒烟商品" + SUF, "barcode": "690" + SUF + "000001"[:9],
                                        "price": 9.9, "cost": 5.5, "safe_stock": 5}, tok=TOK)
chk("commodity create", s == 200 and j["data"]["sku"].startswith("SP"), j)
CID = j["data"]["id"]
s, j = req("POST", "/api/commodities", {"name": "撞码", "barcode": "6901234500011"}, tok=TOK)
chk("commodity dup barcode 409", s == 409, j)
s, j = req("GET", "/api/members", tok=TOK)
chk("member list", s == 200 and j["data"]["total"] >= 4, j)
s, j = req("POST", "/api/members", {"name": "冒烟会员" + SUF, "phone": "138" + SUF, "level": "silver",
                                    "balance": 50}, tok=TOK)
chk("member create", s == 200 and j["data"]["code"].startswith("M"), j)
MID = j["data"]["id"]
s, j = req("GET", "/api/members/%d" % MID, tok=TOK)
chk("member gold rate", j["data"]["discount_rate"] == 0.95, j)
s, j = req("POST", "/api/members/%d/recharge" % MID, {"amount_cents": 1000}, tok=TOK)
chk("member recharge", s == 200 and j["data"]["balance_cents"] == 6000, j)
s, j = req("GET", "/api/suppliers", tok=TOK)
chk("supplier list", s == 200 and j["data"]["total"] >= 2, j)

# ============ 3. 促销 ============
s, j = req("GET", "/api/promotions", tok=TOK)
chk("promo list", s == 200 and j["data"]["total"] >= 2, j)
s, j = req("POST", "/api/promotions", {"name": "冒烟满减" + SUF, "ptype": "full_off",
                                       "threshold_cents": 2000, "off_cents": 300,
                                       "start_date": "2026-01-01", "end_date": "2027-12-31",
                                       "store_id": SID}, tok=TOK)
chk("promo create full_off", s == 200, j)
s, j = req("POST", "/api/promotions", {"name": "冒烟重叠" + SUF, "ptype": "full_off",
                                       "threshold_cents": 100, "off_cents": 10,
                                       "start_date": "2026-06-01", "end_date": "2027-06-01"}, tok=TOK)
chk("promo overlap 422", s == 422, j)
s, j = req("POST", "/api/promotions", {"name": "坏折扣", "ptype": "discount", "rate": 100,
                                       "start_date": "2026-01-01", "end_date": "2027-12-31"}, tok=TOK)
chk("promo bad rate 422", s == 422, j)
s, j = req("POST", "/api/promotions/calc", {"subtotal_cents": 2500, "member_level": "gold"}, tok=TOK)
chk("promo calc", s == 200, j)

# ============ 4. POS 销售 ============
s, j = req("POST", "/api/sales", {"store_id": 1, "member_id": MID, "pay_method": "cash",
                                  "items": [{"commodity_id": 1, "qty": 5}, {"commodity_id": 2, "qty": 5}]}, tok=TOK)
# 小计 5*350+5*200=2750；促销取最优：满减(满2000减300=300) vs 88折(330) → 330；余 2420×0.95=2299
chk("sale silver calc", s == 200 and j["data"]["subtotal_cents"] == 2750
    and j["data"]["promo_off_cents"] == 330 and j["data"]["paid_cents"] == 2299, j)
SALE_ID = j["data"]["id"]
s, j = req("GET", "/api/sales/%d" % SALE_ID, tok=TOK)
chk("sale detail items", s == 200 and len(j["data"]["items"]) == 2, j)
s, j = req("POST", "/api/sales", {"store_id": 1, "member_id": MID, "pay_method": "balance",
                                  "items": [{"commodity_id": 8, "qty": 20}]}, tok=TOK)
chk("sale balance insufficient 422", s == 422, j)
s, j = req("POST", "/api/sales", {"store_id": 1, "items": [{"commodity_id": 1, "qty": 999999}]}, tok=TOK)
chk("sale stock 422", s == 422 and "库存不足" in j["message"], j)
s, j = req("GET", "/api/inventory/summary?store_id=1&commodity_id=1", tok=TOK)
chk("inventory summary", s == 200 and j["data"]["total"] >= 0, j)
s, j = req("POST", "/api/sales/%d/refund" % SALE_ID, {"reason": "冒烟退货"}, tok=TOK)
chk("sale refund", s == 200 and j["data"]["refund_no"].startswith("TH"), j)
s, j = req("POST", "/api/sales/%d/refund" % SALE_ID, {}, tok=TOK)
chk("refund twice 422", s == 422, j)

# ============ 5. 采购 ============
s, j = req("POST", "/api/purchases", {"supplier_id": 1, "store_id": SID,
                                      "items": [{"commodity_id": CID, "qty": 100, "cost_cents": 550,
                                                 "batch_no": "SMK" + SUF, "expiry": "2027-06-01"}]}, tok=TOK)
chk("purchase create", s == 200 and j["data"]["total_cents"] == 55000, j)
POID = j["data"]["id"]
s, j = req("POST", "/api/purchases/%d/transition" % POID, {"action": "to_submitted"}, tok=TOK)
chk("purchase submit", s == 200, j)
s, j = req("POST", "/api/purchases/%d/transition" % POID, {"action": "to_received"}, tok=TOK)
chk("purchase receive", s == 200, j)
s, j = req("GET", "/api/inventory/summary?store_id=%d&commodity_id=%d" % (SID, CID), tok=TOK)
chk("purchase into inventory", s == 200 and j["data"]["total"] == 100, j)
s, j = req("POST", "/api/purchases/%d/transition" % POID, {"action": "to_submitted"}, tok=TOK)
chk("purchase illegal transition 422", s == 422, j)

# ============ 6. 风险 / 财务 ============
s, j = req("POST", "/api/risks/scan", {}, tok=TOK)
chk("risk scan", s == 200 and j["data"]["created"] >= 1, j)
s, j = req("GET", "/api/risks?status=open", tok=TOK)
chk("risk list open", s == 200 and j["data"]["total"] >= 1, j)
RID = j["data"]["items"][0]["id"]
s, j = req("PUT", "/api/risks/%d/resolve" % RID, {"note": "冒烟处理"}, tok=TOK)
chk("risk resolve", s == 200, j)
s, j = req("GET", "/api/finance/summary", tok=TOK)
chk("finance summary", s == 200 and "by_method" in j["data"], j)
s, j = req("GET", "/api/transactions", tok=TOK)
chk("tx list", s == 200 and j["data"]["total"] >= 3, j)

# ============ 7. 系统 ============
s, j = req("GET", "/api/notices", tok=TOK)
chk("notices", s == 200, j)
s, j = req("GET", "/api/logs", tok=TOK)
chk("logs admin", s == 200 and j["data"]["total"] >= 1, j)
s, j = req("GET", "/api/rules", tok=TOK)
chk("rules", s == 200, j)
s, j = req("GET", "/api/sync?since=0&entities=commodities,sales", tok=TOK)
chk("sync", s == 200 and len(j["data"]["changes"]) >= 1, j)
s, j = req("GET", "/api/sync?since=0&entities=notexist", tok=TOK)
chk("sync bad entity 422", s == 422, j)
s, j = req("GET", "/api/export/sales?format=csv", tok=TOK)
chk("export sales csv", s == 200 and "XS" in j.get("_raw", ""), j)
s, j = req("GET", "/api/export/nope", tok=TOK)
chk("export unknown 404", s == 404, j)
s, j = req("POST", "/api/api-keys", {"name": "smoke-" + SUF}, tok=TOK)
chk("api-key create", s == 200 and j["data"]["key"].startswith("fsh_"), j)
AKEY = j["data"]["key"]
s, j = req("GET", "/api/commodities", headers={"X-Api-Key": AKEY})
chk("api-key auth", s == 200, j)
s, j = req("GET", "/api/commodities", headers={"X-Api-Key": "bad-key"})
chk("api-key bad 401", s == 401, j)
s, j = req("GET", "/api/users", tok=TOK)
chk("users list", s == 200 and j["data"]["total"] >= 6, j)
s, j = req("POST", "/api/users", {"username": "smk" + SUF, "password": "123456", "role": "cashier"}, tok=TOK)
chk("user create", s == 200, j)
UID = j["data"]["id"]
s, j = req("PUT", "/api/users/%d" % UID, {"name": "冒烟收银"}, tok=TOK)
chk("user update", s == 200, j)
s, j = req("DELETE", "/api/users/%d" % UID, tok=TOK)
chk("user delete", s == 200, j)
s, j = req("GET", "/api/dashboard", tok=RTOK)
chk("reader dashboard", s == 200, j)

print("==== SMOKE PASS=%d FAIL=%d ====" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
