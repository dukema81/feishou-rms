# -*- coding: utf-8 -*-
"""飞售 RMS 业务内核单测（纯函数，手算验证）"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import ret as K


# ---------- 金额 ----------
def test_money_to_cents():
    assert K.money_to_cents(3.5) == 350
    assert K.money_to_cents("12.345") == 1235  # HALF_UP
    assert K.money_to_cents(0) == 0
    assert K.money_to_cents(29.9) == 2990


def test_line_amount():
    assert K.line_amount_cents(2, 350) == 700
    assert K.line_amount_cents(3, 333) == 999
    assert K.line_amount_cents(1, 0) == 0


def test_payable_half_up():
    assert K.payable_cents(1188, 0.9) == 1069   # 1069.2 → 1069
    assert K.payable_cents(1000, 0.95) == 950
    assert K.payable_cents(999, 0.85) == 849    # 849.15 → 849
    assert K.payable_cents(100, 1.0) == 100


def test_points_earned():
    assert K.points_earned(1215) == 121
    assert K.points_earned(1069) == 106
    assert K.points_earned(99) == 9


# ---------- 会员 ----------
def test_member_rate():
    assert K.member_rate("normal") == 1.00
    assert K.member_rate("silver") == 0.95
    assert K.member_rate("gold") == 0.90
    assert K.member_rate("platinum") == 0.85
    assert K.member_rate("vip") == 1.00  # 未知等级兜底


def test_points_to_level():
    assert K.points_to_level(0) == "normal"
    assert K.points_to_level(3000) == "silver"
    assert K.points_to_level(9999) == "silver"
    assert K.points_to_level(10000) == "gold"
    assert K.points_to_level(20000) == "platinum"


# ---------- 促销 ----------
def test_promo_full_off():
    promo = {"ptype": "full_off", "threshold_cents": 3000, "off_cents": 500}
    assert K.promo_off_cents(promo, 2999) == 0
    assert K.promo_off_cents(promo, 3000) == 500
    assert K.promo_off_cents(promo, 999999) == 500  # 优惠不超过门槛即可（不减超小计）


def test_promo_discount():
    promo = {"ptype": "discount", "rate": 88}
    assert K.promo_off_cents(promo, 1350) == 162   # 1350 × 0.12 = 162
    assert K.promo_off_cents(promo, 5000) == 600   # 5000 × 0.12 = 600
    assert K.promo_off_cents({"ptype": "discount", "rate": 100}, 1000) == 0  # 无效折扣
    assert K.promo_off_cents({"ptype": "discount", "rate": 0}, 1000) == 0


def test_best_promotion():
    promos = [
        {"id": 1, "ptype": "full_off", "threshold_cents": 3000, "off_cents": 500},
        {"id": 2, "ptype": "discount", "rate": 88},
    ]
    p, off = K.best_promotion(promos, 5000)  # 满减 500 vs 88折 600 → 选折扣
    assert p["id"] == 2 and off == 600
    p, off = K.best_promotion(promos, 3000)  # 满减 500 vs 360 → 选满减
    assert p["id"] == 1 and off == 500
    p, off = K.best_promotion(promos, 1000)  # 满减不满足，仅 88 折 120
    assert p["id"] == 2 and off == 120


def test_promo_active_window_and_store():
    promo = {"status": "active", "store_id": None, "start_date": "2026-01-01", "end_date": "2027-12-31"}
    assert K.promo_active(promo, today=__import__("datetime").date(2026, 6, 1))
    assert K.promo_active(promo, today=__import__("datetime").date(2026, 6, 1), store_id=3)
    assert not K.promo_active({"status": "inactive", "store_id": None,
                               "start_date": "2026-01-01", "end_date": "2027-12-31"})
    locked = dict(promo, store_id=2)
    assert not K.promo_active(locked, today=__import__("datetime").date(2026, 6, 1), store_id=1)


def test_date_overlap():
    assert K.date_overlap("2026-01-01", "2026-06-30", "2026-06-01", "2026-12-31")
    assert not K.date_overlap("2026-01-01", "2026-06-30", "2026-07-01", "2026-12-31")


# ---------- 状态机 ----------
def test_sale_transition():
    assert K.can_transition(K.SALE_TRANS, "cart", "paid")
    assert K.can_transition(K.SALE_TRANS, "cart", "cancelled")
    assert not K.can_transition(K.SALE_TRANS, "paid", "refunded")
    assert not K.can_transition(K.SALE_TRANS, "cancelled", "paid")


def test_purchase_transition():
    assert K.can_transition(K.PURCHASE_TRANS, "draft", "submitted")
    assert K.can_transition(K.PURCHASE_TRANS, "submitted", "received")
    assert not K.can_transition(K.PURCHASE_TRANS, "draft", "received")


# ---------- 库存 FEFO ----------
def test_fefe_exact():
    rows = [{"id": 1, "batch_no": "B1", "qty": 3, "expire_at": "2026-06-01"},
            {"id": 2, "batch_no": "B2", "qty": 5, "expire_at": "2026-09-01"}]
    allocs, short = K.fefe_batches(rows, 8)
    assert short == 0
    assert allocs[0][0] == 1 and allocs[0][2] == 3   # 先扣近效期
    assert allocs[1][0] == 2 and allocs[1][2] == 5


def test_fefe_shortfall():
    rows = [{"id": 1, "batch_no": "B1", "qty": 3, "expire_at": "2026-06-01"},
            {"id": 2, "batch_no": "B2", "qty": 5, "expire_at": "2026-09-01"}]
    allocs, short = K.fefe_batches(rows, 9)
    assert short == 1  # 需 9 有 8 缺 1
    assert len(allocs) == 2


def test_stock_available():
    rows = [{"id": 1, "batch_no": "B1", "qty": 10, "expire_at": None}]
    assert K.stock_available(rows, 10)
    assert not K.stock_available(rows, 11)


# ---------- 风险 ----------
def test_low_stock():
    assert K.low_stock_check(8, 10) == (30, "warn")
    assert K.low_stock_check(10, 10) == (30, "warn")
    assert K.low_stock_check(11, 10) is None


def test_expiry_check():
    from datetime import date
    today = date(2026, 1, 1)
    assert K.expiry_check("2026-03-01", 90, today) == (25, "warn")   # 59 天
    assert K.expiry_check("2026-12-01", 90, today) is None           # 334 天
    assert K.expiry_check("2025-12-01", 90, today) == (40, "risk")   # 已过期
    assert K.expiry_check(None, 90, today) is None


def test_negative_margin():
    assert K.negative_margin(199, 220)
    assert not K.negative_margin(350, 220)
    assert not K.negative_margin(100, 0)  # 无成本不判


def test_supplier_over_debt():
    assert K.supplier_over_debt(6000, 5000)
    assert not K.supplier_over_debt(5000, 5000)
    assert not K.supplier_over_debt(99999, 0)  # 上限 0 不启用


def test_purchase_total():
    assert K.purchase_total_cents([{"qty": 10, "cost_cents": 220}, {"qty": 5, "cost_cents": 400}]) == 4200


# ---------- 权限 ----------
def test_has_perm_wildcard():
    assert K.has_perm("*", "retail.anything.read")
    assert K.has_perm(["retail.*"], "retail.sales.write")
    assert not K.has_perm(["retail.sales.*"], "retail.risk.write")


def test_has_perm_write_contains_read():
    assert K.has_perm(["retail.sales.*"], "retail.sales.read")
    # 通配列表写含读；单一 write 不含 read（实现口径与 HIS 一致）
    assert not K.has_perm("retail.members.write", "retail.members.read")
    assert K.has_perm(["retail.members.write", "retail.members.read"], "retail.members.read")


def test_has_perm_compat():
    assert K.has_perm(["retail.sales.read"], "retail.sales.read")
    assert K.has_perm("retail.sales.read,retail.members.read", "retail.members.read")
    assert not K.has_perm([], "retail.sales.read")


# ---------- 统计 ----------
def test_daily_stats():
    sales = [{"status": "paid", "paid_cents": 1000}, {"status": "refunded", "paid_cents": 500}]
    txs = [{"pay_method": "cash", "amount_cents": 600}, {"pay_method": "wechat", "amount_cents": 400}]
    s = K.daily_stats(sales, txs)
    assert s["sales_count"] == 2 and s["income_cents"] == 1000 and s["refund_cents"] == 500
    assert s["by_method"] == {"cash": 600, "wechat": 400}
