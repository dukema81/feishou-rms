# -*- coding: utf-8 -*-
"""飞售 RMS 业务内核（纯函数，无 IO 无 DB，可独立单测）"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timedelta

# ---------------- 金额 ----------------
def money_to_cents(yuan) -> int:
    """元（可 float/str）→ 分，HALF_UP"""
    return int((Decimal(str(yuan)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def line_amount_cents(qty, price_cents) -> int:
    """明细金额 = 数量 × 单价（分），HALF_UP"""
    return int((Decimal(str(qty)) * Decimal(str(price_cents))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def payable_cents(total_cents, discount_rate) -> int:
    """应收 = 总额 × 折扣率，对分取整 HALF_UP（只做一次量纲转换）"""
    amt = Decimal(str(total_cents)) * Decimal(str(discount_rate))
    return int(amt.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def points_earned(paid_cents, ratio=10) -> int:
    """积分 = 实付/比例 取整"""
    return int(Decimal(str(paid_cents)) // Decimal(str(ratio)))

# ---------------- 会员折扣 ----------------
MEMBER_RATES = {"normal": 1.00, "silver": 0.95, "gold": 0.90, "platinum": 0.85}

def member_rate(level: str) -> float:
    return MEMBER_RATES.get(level, 1.00)

def points_to_level(points) -> str:
    p = int(points or 0)
    if p >= 20000: return "platinum"
    if p >= 10000: return "gold"
    if p >= 3000: return "silver"
    return "normal"

# ---------------- 促销 ----------------
def promo_off_cents(promo, subtotal_cents) -> int:
    """促销优惠（分）。full_off: 满 threshold 减 off；discount: rate(88→×0.88)。
    不满足条件返回 0"""
    if not promo:
        return 0
    ptype = promo["ptype"]
    if ptype == "full_off":
        if subtotal_cents >= int(promo["threshold_cents"] or 0):
            return min(int(promo["off_cents"] or 0), subtotal_cents)
        return 0
    if ptype == "discount":
        rate = int(promo["rate"] or 100)
        if rate <= 0 or rate >= 100:
            return 0
        off = Decimal(str(subtotal_cents)) * (Decimal(100 - rate) / Decimal(100))
        return int(off.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return 0

def best_promotion(promos, subtotal_cents):
    """从可用促销中取优惠最大者，返回 (promo_or_None, off_cents)"""
    best, best_off = None, 0
    for p in promos:
        off = promo_off_cents(p, subtotal_cents)
        if off > best_off:
            best, best_off = p, off
    return best, best_off

def promo_active(promo, today=None, store_id=None) -> bool:
    """促销在今日/门店可用"""
    if promo["status"] != "active":
        return False
    sid = promo["store_id"]
    if sid is not None and store_id is not None and int(sid) != int(store_id):
        return False
    today = today or date.today()
    try:
        s = datetime.strptime(promo["start_date"][:10], "%Y-%m-%d").date()
        e = datetime.strptime(promo["end_date"][:10], "%Y-%m-%d").date()
    except Exception:
        return False
    return s <= today <= e

def date_overlap(a_s, a_e, b_s, b_e) -> bool:
    """日期区间重叠"""
    return a_s <= b_e and b_s <= a_e

# ---------------- 状态机 ----------------
SALE_TRANS = {
    "cart": {"paid", "cancelled"},
    "paid": set(),
    "cancelled": set(),
}

PURCHASE_TRANS = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"received"},
    "received": set(),
    "cancelled": set(),
}

def can_transition(trans: dict, cur: str, to: str) -> bool:
    return to in trans.get(cur, set())

# ---------------- 库存 ----------------
def fefe_batches(rows, need):
    """FEFO 分配：按效期近先出。返回 (allocations[(id, batch_no, take)], shortfall)
    rows 须含 id/batch_no/qty/expire_at"""
    batches = sorted([dict(r) for r in rows], key=lambda r: (r["expire_at"] or "9999-12-31", r["id"]))
    remain = int(need)
    allocs = []
    for b in batches:
        if remain <= 0:
            break
        have = int(b["qty"] or 0)
        if have <= 0:
            continue
        take = min(have, remain)
        allocs.append((b["id"], b["batch_no"], take))
        remain -= take
    return allocs, remain

def stock_available(rows, need) -> bool:
    _, shortfall = fefe_batches(rows, need)
    return shortfall <= 0

def low_stock_check(qty, safe_stock):
    """≤safe → (30,'warn')"""
    return (30, "warn") if qty <= safe_stock else None

def expiry_check(expire_at, days=90, today=None):
    """效期 ≤ days 天 → (25,'warn')；已过期 → (40,'risk')"""
    if not expire_at:
        return None
    today = today or date.today()
    try:
        exp = datetime.strptime(expire_at[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    left = (exp - today).days
    if left < 0:
        return (40, "risk")
    if left <= days:
        return (25, "warn")
    return None

# ---------------- 毛利/欠款 ----------------
def negative_margin(sale_price_cents, cost_cents) -> bool:
    return cost_cents > 0 and sale_price_cents < cost_cents

def supplier_over_debt(payable_cents, debt_limit_cents) -> bool:
    return debt_limit_cents > 0 and payable_cents > debt_limit_cents

def purchase_total_cents(items) -> int:
    return sum(int(i.get("qty", 0)) * int(i.get("cost_cents", 0)) for i in items)

# ---------------- 权限 ----------------
ROLE_PERMS = {
    "admin": "*",
    "manager": ["retail.sales.*", "retail.commodities.*", "retail.members.*", "retail.promotions.*", "retail.inventory.read", "retail.purchases.read", "retail.stores.read", "retail.risk.read"],
    "cashier": ["retail.sales.*", "retail.commodities.read", "retail.members.read", "retail.members.recharge", "retail.promotions.read"],
    "warehouse": ["retail.purchases.*", "retail.inventory.*", "retail.suppliers.*", "retail.commodities.read"],
    "member_admin": ["retail.members.*", "retail.members.read"],
    "reader": ["retail.sales.read", "retail.commodities.read", "retail.members.read", "retail.inventory.read", "retail.purchases.read", "retail.promotions.read"],
}

def has_perm(perms, perm: str) -> bool:
    """perms: '*' 或逗号分隔字符串或列表；写权限含读权限"""
    if perms == "*":
        return True
    if isinstance(perms, (list, tuple)):
        parts = [str(p) for p in perms if p]
    else:
        parts = [p for p in (perms or "").split(",") if p]
    for p in parts:
        if p == perm:
            return True
        if p.endswith(".*") and perm.startswith(p[:-1]):
            return True
        if perm.endswith(".read") and (perm[:-5] + ".*") in parts:
            return True
    return False

# ---------------- 统计 ----------------
def daily_stats(sales_rows, tx_rows):
    paid = sum(int(s["paid_cents"] or 0) for s in sales_rows if s["status"] == "paid")
    refund = sum(int(s["paid_cents"] or 0) for s in sales_rows if s["status"] == "refunded")
    return {"sales_count": len(sales_rows), "income_cents": paid, "refund_cents": refund,
            "by_method": _by_method(tx_rows)}

def _by_method(tx_rows):
    d = {}
    for t in tx_rows:
        m = t["pay_method"] or "cash"
        d[m] = d.get(m, 0) + int(t["amount_cents"] or 0)
    return d
