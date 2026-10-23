# -*- coding: utf-8 -*-
"""飞售 RMS 演示数据初始化"""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
from ret import money_to_cents

def run():
    db.init_db()
    conn = db.get_db()
    if db.q1("SELECT COUNT(*) c FROM users")["c"] > 0:
        print("seed: already done")
        return

    import hashlib
    def h(p): return hashlib.sha256(p.encode()).hexdigest()

    # seq 显式初始化（全部）
    for name, val in [("sale_no", 1), ("refund_no", 0), ("purchase_no", 0), ("member_code", 4), ("commodity_sku", 8)]:
        db.execute("INSERT OR REPLACE INTO seq(name, val) VALUES(?, ?)", (name, val))

    # 用户 6
    users = [("admin", "系统管理员", "admin"), ("lim", "李明", "manager"),
             ("wangn", "王妮", "cashier"), ("chenyf", "陈永发", "warehouse"),
             ("liug", "刘光", "member_admin"), ("reader01", "只读账号", "reader")]
    for u, n, r in users:
        db.execute("INSERT INTO users(username, password, name, role) VALUES(?,?,?,?)", (u, h("123456"), n, r))

    # 门店 3
    stores = [("S001", "旗舰店（中心广场）", "幸福路1号中心广场", "0571-88880001"),
              ("S002", "城东店", "城东大道88号", "0571-88880002"),
              ("S003", "大学城店", "文华路学府街口", "0571-88880003")]
    for c, n, a, p in stores:
        db.execute("INSERT INTO stores(code, name, address, phone) VALUES(?,?,?,?)", (c, n, a, p))

    # 商品 8（含临期/低库存样例）
    comms = [
        ("SP0001", "6901234500011", "可口可乐330ml", "罐", "饮料", money_to_cents(3.5), money_to_cents(2.2), 270, 50),
        ("SP0002", "6901234500028", "农夫山泉550ml", "瓶", "饮料", money_to_cents(2.0), money_to_cents(1.2), 270, 60),
        ("SP0003", "6901234500035", "乐事薯片原味", "袋", "零食", money_to_cents(6.5), money_to_cents(4.0), 180, 30),
        ("SP0004", "6901234500042", "康师傅红烧牛肉面", "桶", "食品", money_to_cents(4.5), money_to_cents(2.8), 180, 40),
        ("SP0005", "6901234500059", "蒙牛纯牛奶250ml", "盒", "乳品", money_to_cents(3.0), money_to_cents(2.0), 90, 30),
        ("SP0006", "6901234500066", "飞售纸巾抽装", "包", "日化", money_to_cents(2.5), money_to_cents(1.4), 720, 40),
        ("SP0007", "6901234500073", "士力架花生夹心", "支", "零食", money_to_cents(5.0), money_to_cents(3.2), 240, 25),
        ("SP0008", "6901234500080", "海飞丝洗发水", "瓶", "日化", money_to_cents(29.9), money_to_cents(19.0), 720, 10),
    ]
    for sku, bc, n, u, cat, pr, co, shelf, safe in comms:
        db.execute("INSERT INTO commodities(sku, barcode, name, unit, category, price_cents, cost_cents, shelf_life_days, safe_stock) VALUES(?,?,?,?,?,?,?,?,?)",
                   (sku, bc, n, u, cat, pr, co, shelf, safe))

    # 会员 4
    mems = [("M0001", "张伟", "13800000001", "gold", 12800, money_to_cents(200.00)),
            ("M0002", "李娜", "13800000002", "silver", 4200, money_to_cents(50.00)),
            ("M0003", "王强", "13800000003", "normal", 800, money_to_cents(0)),
            ("M0004", "赵六", "13800000004", "platinum", 25600, money_to_cents(500.00))]
    for c, n, p, lv, pts, bal in mems:
        db.execute("INSERT INTO members(code, name, phone, level, points, balance_cents) VALUES(?,?,?,?,?,?)", (c, n, p, lv, pts, bal))

    # 供应商 2
    db.execute("INSERT INTO suppliers(name, contact, phone, credit_days, debt_limit_cents) VALUES(?,?,?,?,?)",
               ("华东饮品供应链", "周经理", "13900000001", 30, money_to_cents(50000)))
    db.execute("INSERT INTO suppliers(name, contact, phone, credit_days, debt_limit_cents) VALUES(?,?,?,?,?)",
               ("鑫达日用百货", "孙经理", "13900000002", 15, money_to_cents(20000)))

    # 促销 2
    db.execute("INSERT INTO promotions(name, ptype, threshold_cents, off_cents, rate, start_date, end_date, store_id, status) VALUES(?,?,?,?,?,?,?,?,?)",
               ("全场满30减5", "full_off", money_to_cents(30), money_to_cents(5), 100, "2026-01-01", "2027-12-31", None, "active"))
    db.execute("INSERT INTO promotions(name, ptype, threshold_cents, off_cents, rate, start_date, end_date, store_id, status) VALUES(?,?,?,?,?,?,?,?,?)",
               ("饮料类88折", "discount", 0, 0, 88, "2026-01-01", "2027-12-31", None, "active"))

    # 库存批次 8（含低库存 8≤10、临期 60≤90 样例；门店1）
    from datetime import date, timedelta
    today = date.today()
    batches = [
        (1, 1, "B2026A01", 200, (today + timedelta(days=120)).isoformat()),
        (1, 2, "B2026A02", 150, (today + timedelta(days=200)).isoformat()),
        (1, 3, "B2026A03", 60, (today + timedelta(days=60)).isoformat()),   # 临期
        (1, 4, "B2026A04", 100, (today + timedelta(days=150)).isoformat()),
        (1, 5, "B2026A05", 40, (today + timedelta(days=45)).isoformat()),   # 临期
        (1, 6, "B2026A06", 80, (today + timedelta(days=400)).isoformat()),
        (1, 7, "B2026A07", 8, (today + timedelta(days=250)).isoformat()),   # 低库存 8≤25
        (1, 8, "B2026A08", 6, (today + timedelta(days=500)).isoformat()),   # 低库存 6≤10
    ]
    for sid, cid, bn, qty, exp in batches:
        db.execute("INSERT INTO inventory(store_id, commodity_id, batch_no, qty, expire_at) VALUES(?,?,?,?,?)", (sid, cid, bn, qty, exp))
    # 门店2 少量库存
    db.execute("INSERT INTO inventory(store_id, commodity_id, batch_no, qty, expire_at) VALUES(?,?,?,?,?)",
               (2, 1, "B2026B01", 100, (today + timedelta(days=180)).isoformat()))
    db.execute("INSERT INTO inventory(store_id, commodity_id, batch_no, qty, expire_at) VALUES(?,?,?,?,?)",
               (2, 2, "B2026B02", 120, (today + timedelta(days=220)).isoformat()))

    # 一笔已完成演示销售（门店1，会员张伟 gold，2 可乐 + 1 薯片）
    # 小计 = 2×350 + 650 = 1350 分；无促销(满30减5不满足)；gold 0.90 → 1215 分；积分 121
    cur = db.execute("INSERT INTO sales(no, store_id, member_id, subtotal_cents, promo_off_cents, member_off_cents, paid_cents, pay_method, received_cents, points, status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     ("XS20260101-001", 1, 1, 1350, 0, 135, 1215, "wechat", 1215, 121, "paid"))
    sale_id = cur.lastrowid
    db.execute("INSERT INTO sale_items(sale_id, commodity_id, commodity_name, qty, unit_price_cents, cost_cents, amount_cents) VALUES(?,?,?,?,?,?,?)",
               (sale_id, 1, "可口可乐330ml", 2, 350, 220, 700))
    db.execute("INSERT INTO sale_items(sale_id, commodity_id, commodity_name, qty, unit_price_cents, cost_cents, amount_cents) VALUES(?,?,?,?,?,?,?)",
               (sale_id, 3, "乐事薯片原味", 1, 650, 400, 650))
    db.execute("INSERT INTO transactions(ttype, amount_cents, ref_type, ref_id, pay_method, note) VALUES(?,?,?,?,?,?)",
               ("income", 1215, "sale", sale_id, "wechat", "销售收款 XS20260101-001"))
    db.execute("INSERT INTO member_txns(member_id, ttype, points_delta, amount_cents, note, ref_id) VALUES(?,?,?,?,?,?)",
               (1, "earn", 121, 1215, "消费积分 XS20260101-001", sale_id))
    # 演示销售扣库存：可乐 2 罐（B2026A01）、薯片 1 袋（B2026A03）
    db.execute("UPDATE inventory SET qty=qty-2 WHERE store_id=1 AND commodity_id=1 AND batch_no='B2026A01'")
    db.execute("UPDATE inventory SET qty=qty-1 WHERE store_id=1 AND commodity_id=3 AND batch_no='B2026A03'")

    # 一张已收货演示采购单（供应商1 → 门店1，可乐 100 罐 @2.2）
    cur = db.execute("INSERT INTO purchases(no, supplier_id, store_id, status, total_cents) VALUES(?,?,?,?,?)",
                     ("CG20260101-001", 1, 1, "received", 22000))
    po_id = cur.lastrowid
    db.execute("INSERT INTO purchase_items(purchase_id, commodity_id, qty, cost_cents, amount_cents, batch_no, expiry) VALUES(?,?,?,?,?,?,?)",
               (po_id, 1, 100, 220, 22000, "B2026A01", (today + timedelta(days=120)).isoformat()))
    db.execute("UPDATE suppliers SET payable_cents=payable_cents+22000 WHERE id=1")

    db.execute("INSERT INTO notices(title, content, level) VALUES(?,?,?)",
               ("欢迎使用飞售零售管理系统", "系统已上线演示环境，请使用 admin/123456 登录体验。", "info"))

    print("seed: done (6 users, 3 stores, 8 commodities, 4 members, 2 suppliers, 2 promotions, 10 batches, 1 demo sale, 1 demo purchase)")

if __name__ == "__main__":
    run()
