# -*- coding: utf-8 -*-
"""飞售 RMS 服务端：零依赖 HTTP API（端口 8029，前缀可配）"""
import os, re, json, time, hashlib, traceback, urllib.parse, datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http import cookies as http_cookies

import db as D
from db import q, q1, execute, next_seq, make_no, bump_sync, get_sync
import ret as K
import seed as S

PORT = int(os.environ.get("RET_PORT", "8029"))
PREFIX = os.environ.get("RET_PREFIX", "")
TOKEN_TTL = 7 * 86400

def now_s():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def jdump(o):
    return json.dumps(o, ensure_ascii=False, default=str)

class ApiError(Exception):
    def __init__(self, code, message):
        self.code = code; self.message = message

def page_args(qs):
    p = max(int(qs.get("page", ["1"])[0] or 1), 1)
    s = min(max(int(qs.get("size", ["20"])[0] or 20), 1), 200)
    return p, s, (p - 1) * s

def listwrap(sql, params, qs, extra=None):
    p, s, off = page_args(qs)
    total = q1("SELECT COUNT(*) AS c FROM (" + sql + ")", params)["c"]
    rows = q(sql + " LIMIT %d OFFSET %d" % (s, off), params)
    items = [dict(r) for r in rows]
    if extra:
        for it in items:
            extra(it)
    return {"items": items, "total": total, "page": p, "size": s}

def csv_export(rows, cols):
    import io, csv as _csv
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] if c in r.keys() else "" for c in cols])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")

def log_act(user_id, action, detail=""):
    D.execute("INSERT INTO logs(ts,user_id,action,detail) VALUES(?,?,?,?)", (now_s(), user_id, action, detail))

# ---------- 认证 ----------

def auth_token(tok):
    if not tok:
        return None
    row = q1("SELECT t.*, u.username, u.name, u.role FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?", (tok,))
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] < now_s():
        execute("DELETE FROM tokens WHERE token=?", (tok,))
        return None
    return row

def auth_key(key):
    if not key:
        return None
    row = q1("SELECT * FROM api_keys WHERE key_hash=? AND status=1", (sha(key),))
    if not row:
        return None
    execute("UPDATE api_keys SET last_used=? WHERE id=?", (now_s(), row["id"]))
    return {"username": "apikey:" + (row["prefix"] or "k"), "name": row["name"], "role": "apikey", "perms": (row["perms"] or "retail.read").split(",")}

def do_login(body):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    u = q1("SELECT * FROM users WHERE username=? AND status=1", (username,))
    if not u or u["password"] != sha(password):
        log_act(None, "login_fail", username)
        raise ApiError(401, "用户名或密码错误")
    tok = sha(username + str(time.time()) + os.urandom(8).hex())[:40]
    exp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + TOKEN_TTL))
    execute("INSERT INTO tokens(token, user_id, created_at, expires_at) VALUES(?,?,?,?)", (tok, u["id"], now_s(), exp))
    log_act(u["id"], "login", username)
    perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"])
    return {"token": tok, "expires_at": exp, "user": {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"]}, "perms": perms}

def h_login(ctx, m, qs, body):
    return do_login(body)

def h_logout(ctx, m, qs, body):
    execute("DELETE FROM tokens WHERE token=?", (ctx["token"],))
    return {"ok": True}

def h_me(ctx, m, qs, body):
    u = ctx["user"]
    perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"]) if u.get("role") != "apikey" else u["perms"]
    return {"user": {"id": u.get("id"), "username": u["username"], "name": u["name"], "role": u["role"]}, "perms": perms}

def h_health(ctx, m, qs, body):
    return {"ok": True, "service": "feishou-rms", "ts": now_s()}

# ---------- 用户 / Key ----------

def h_users(ctx, m, qs, body):
    return listwrap("SELECT id,username,name,role,phone,status,created_at FROM users ORDER BY id", (), qs)

def h_users_create(ctx, m, qs, body):
    if not body.get("username") or not body.get("password"):
        raise ApiError(422, "username/password 必填")
    if q1("SELECT id FROM users WHERE username=?", (body["username"],)):
        raise ApiError(409, "用户名已存在")
    role = body.get("role", "reader")
    if role not in K.ROLE_PERMS:
        raise ApiError(422, "角色非法")
    c = execute("INSERT INTO users(username,password,name,role,phone) VALUES(?,?,?,?,?)",
                (body["username"], sha(body["password"]), body.get("name", body["username"]), role, body.get("phone")))
    return {"id": c.lastrowid}

def h_users_update(ctx, m, qs, body):
    uid = int(m.group(1))
    if not q1("SELECT id FROM users WHERE id=?", (uid,)):
        raise ApiError(404, "用户不存在")
    sets, params = [], []
    for f in ("name", "role", "phone"):
        if f in body:
            if f == "role" and body[f] not in K.ROLE_PERMS:
                raise ApiError(422, "角色非法")
            sets.append(f + "=?"); params.append(body[f])
    if body.get("password"):
        sets.append("password=?"); params.append(sha(body["password"]))
    if "status" in body:
        sets.append("status=?"); params.append(1 if body["status"] else 0)
    if sets:
        params.append(uid)
        execute("UPDATE users SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_users_delete(ctx, m, qs, body):
    uid = int(m.group(1))
    if uid == (ctx["user"].get("id") or 0):
        raise ApiError(422, "不能删除自己")
    row = q1("SELECT id FROM users WHERE id=?", (uid,))
    if not row:
        raise ApiError(404, "用户不存在")
    execute("DELETE FROM tokens WHERE user_id=?", (uid,))
    execute("DELETE FROM users WHERE id=?", (uid,))
    return {"ok": True}

def h_keys(ctx, m, qs, body):
    return listwrap("SELECT id,name,prefix,perms,status,last_used,created_at FROM api_keys ORDER BY id", (), qs)

def h_keys_create(ctx, m, qs, body):
    name = body.get("name") or "default"
    raw = "fsh_" + sha(name + str(time.time()) + os.urandom(8).hex())[:32]
    c = execute("INSERT INTO api_keys(name, key_hash, prefix, perms) VALUES(?,?,?,?)",
                (name, sha(raw), raw[:12], body.get("perms", "retail.*")))
    return {"id": c.lastrowid, "key": raw, "note": "仅此一次返回明文，请妥善保存"}

def h_keys_delete(ctx, m, qs, body):
    execute("DELETE FROM api_keys WHERE id=?", (int(m.group(1)),))
    return {"ok": True}

# ---------- 门店 ----------

def h_store_list(ctx, m, qs, body):
    kw = qs.get("keyword", [""])[0]
    cond, params = "1=1", []
    if kw:
        cond = "(name LIKE ? OR code LIKE ? OR address LIKE ?)"; params = ["%" + kw + "%"] * 3
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    return listwrap("SELECT * FROM stores WHERE " + cond + " ORDER BY id", params, qs)

def h_store_create(ctx, m, qs, body):
    if not body.get("name"):
        raise ApiError(422, "name 必填")
    if q1("SELECT id FROM stores WHERE code=?", (body.get("code") or "",)):
        raise ApiError(409, "门店编码已存在")
    c = execute("INSERT INTO stores(code,name,address,phone) VALUES(?,?,?,?)",
                (body.get("code"), body["name"], body.get("address"), body.get("phone")))
    bump_sync("stores")
    return {"id": c.lastrowid}

def _store_or_404(sid):
    r = q1("SELECT * FROM stores WHERE id=?", (sid,))
    if not r:
        raise ApiError(404, "门店不存在")
    return r

def h_store_get(ctx, m, qs, body):
    return dict(_store_or_404(int(m.group(1))))

def h_store_update(ctx, m, qs, body):
    sid = int(m.group(1)); _store_or_404(sid)
    sets, params = [], []
    for f in ("code", "name", "address", "phone", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(sid)
        execute("UPDATE stores SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("stores")
    return {"ok": True}

def h_store_delete(ctx, m, qs, body):
    sid = int(m.group(1)); _store_or_404(sid)
    if q1("SELECT id FROM sales WHERE store_id=? LIMIT 1", (sid,)):
        raise ApiError(409, "门店有销售记录，禁止删除")
    if q1("SELECT id FROM inventory WHERE store_id=? LIMIT 1", (sid,)):
        raise ApiError(409, "门店有库存记录，禁止删除")
    execute("DELETE FROM stores WHERE id=?", (sid,))
    bump_sync("stores")
    return {"ok": True}

# ---------- 商品 ----------

def h_comm_list(ctx, m, qs, body):
    cond, params = "1=1", []
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (name LIKE ? OR sku LIKE ?)"; params += ["%" + kw + "%"] * 2
    if qs.get("barcode", [""])[0]:
        cond += " AND barcode=?"; params.append(qs["barcode"][0])
    if qs.get("category", [""])[0]:
        cond += " AND category=?"; params.append(qs["category"][0])
    if qs.get("store_id", [""])[0]:
        cond += " AND id IN (SELECT commodity_id FROM inventory WHERE store_id=?)"
        params.append(int(qs["store_id"][0]))
    def ex(it):
        rows = q("SELECT COALESCE(SUM(qty),0) s FROM inventory WHERE commodity_id=?", (it["id"],))
        it["stock"] = int(rows[0]["s"] or 0)
        return it
    return listwrap("SELECT * FROM commodities WHERE " + cond + " ORDER BY id", params, qs, ex)

def h_comm_create(ctx, m, qs, body):
    if not body.get("name"):
        raise ApiError(422, "name 必填")
    if body.get("barcode") and q1("SELECT id FROM commodities WHERE barcode=?", (body["barcode"],)):
        raise ApiError(409, "条码已存在")
    sku = body.get("sku") or "SP%04d" % next_seq("commodity_sku")
    c = execute("INSERT INTO commodities(sku,barcode,name,unit,category,price_cents,cost_cents,shelf_life_days,safe_stock) VALUES(?,?,?,?,?,?,?,?,?)",
                (sku, body.get("barcode"), body["name"], body.get("unit", "件"), body.get("category"),
                 K.money_to_cents(body.get("price", 0)), K.money_to_cents(body.get("cost", 0)),
                 int(body.get("shelf_life_days", 365) or 365), int(body.get("safe_stock", 10) or 10)))
    bump_sync("commodities")
    return {"id": c.lastrowid, "sku": sku}

def _comm_or_404(cid):
    r = q1("SELECT * FROM commodities WHERE id=?", (cid,))
    if not r:
        raise ApiError(404, "商品不存在")
    return r

def h_comm_get(ctx, m, qs, body):
    d = dict(_comm_or_404(int(m.group(1))))
    d["batches"] = [dict(r) for r in q("SELECT * FROM inventory WHERE commodity_id=? ORDER BY expire_at", (d["id"],))]
    return d

def h_comm_update(ctx, m, qs, body):
    cid = int(m.group(1)); _comm_or_404(cid)
    sets, params = [], []
    for f in ("name", "unit", "category", "shelf_life_days", "safe_stock", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if "price" in body:
        sets.append("price_cents=?"); params.append(K.money_to_cents(body["price"]))
    if "cost" in body:
        sets.append("cost_cents=?"); params.append(K.money_to_cents(body["cost"]))
    if "barcode" in body:
        dup = q1("SELECT id FROM commodities WHERE barcode=? AND id<>?", (body["barcode"] or "", cid))
        if dup:
            raise ApiError(409, "条码已存在")
        sets.append("barcode=?"); params.append(body["barcode"] or None)
    if sets:
        params.append(cid)
        execute("UPDATE commodities SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("commodities")
    return {"ok": True}

def h_comm_delete(ctx, m, qs, body):
    cid = int(m.group(1))
    if q1("SELECT id FROM sale_items WHERE commodity_id=? LIMIT 1", (cid,)):
        raise ApiError(409, "商品已有销售记录，禁止删除")
    execute("DELETE FROM inventory WHERE commodity_id=?", (cid,))
    execute("DELETE FROM commodities WHERE id=?", (cid,))
    bump_sync("commodities")
    return {"ok": True}

def h_comm_barcode(ctx, m, qs, body):
    code = m.group(1)
    r = q1("SELECT * FROM commodities WHERE barcode=?", (code,))
    if not r:
        raise ApiError(404, "条码不存在: " + code)
    d = dict(r)
    d["stock"] = int(q1("SELECT COALESCE(SUM(qty),0) s FROM inventory WHERE commodity_id=?", (d["id"],))["s"] or 0)
    return d

# ---------- 会员 ----------

def h_member_list(ctx, m, qs, body):
    cond, params = "1=1", []
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (name LIKE ? OR code LIKE ? OR phone LIKE ?)"; params += ["%" + kw + "%"] * 3
    if qs.get("level", [""])[0]:
        cond += " AND level=?"; params.append(qs["level"][0])
    if qs.get("phone", [""])[0]:
        cond += " AND phone LIKE ?"; params.append("%" + qs["phone"][0] + "%")
    return listwrap("SELECT * FROM members WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_member_create(ctx, m, qs, body):
    if not body.get("name"):
        raise ApiError(422, "name 必填")
    if body.get("phone") and q1("SELECT id FROM members WHERE phone=?", (body["phone"],)):
        raise ApiError(409, "手机号已注册")
    level = body.get("level", "normal")
    if level not in K.MEMBER_RATES:
        raise ApiError(422, "level 须为 normal/silver/gold/platinum")
    code = body.get("code") or "M%04d" % next_seq("member_code")
    c = execute("INSERT INTO members(code,name,phone,level,balance_cents) VALUES(?,?,?,?,?)",
                (code, body["name"], body.get("phone"), level, K.money_to_cents(body.get("balance", 0))))
    bump_sync("members")
    return {"id": c.lastrowid, "code": code}

def _member_or_404(mid):
    r = q1("SELECT * FROM members WHERE id=?", (mid,))
    if not r:
        raise ApiError(404, "会员不存在")
    return r

def h_member_get(ctx, m, qs, body):
    d = dict(_member_or_404(int(m.group(1))))
    d["discount_rate"] = K.member_rate(d["level"])
    return d

def h_member_update(ctx, m, qs, body):
    mid = int(m.group(1)); _member_or_404(mid)
    sets, params = [], []
    for f in ("name", "phone", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if "level" in body:
        if body["level"] not in K.MEMBER_RATES:
            raise ApiError(422, "level 非法")
        sets.append("level=?"); params.append(body["level"])
    if sets:
        params.append(mid)
        execute("UPDATE members SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("members")
    return {"ok": True}

def h_member_delete(ctx, m, qs, body):
    mid = int(m.group(1))
    if q1("SELECT id FROM sales WHERE member_id=? LIMIT 1", (mid,)):
        raise ApiError(409, "会员有消费记录，禁止删除")
    execute("DELETE FROM member_txns WHERE member_id=?", (mid,))
    execute("DELETE FROM members WHERE id=?", (mid,))
    bump_sync("members")
    return {"ok": True}

def h_member_txns(ctx, m, qs, body):
    mid = int(m.group(1)); _member_or_404(mid)
    return listwrap("SELECT * FROM member_txns WHERE member_id=? ORDER BY id DESC", (mid,), qs)

def h_member_recharge(ctx, m, qs, body):
    mid = int(m.group(1)); mem = _member_or_404(mid)
    amt = body.get("amount_cents")
    if not amt or int(amt) <= 0:
        raise ApiError(422, "amount_cents 必须为正数")
    amt = int(amt)
    execute("UPDATE members SET balance_cents=balance_cents+? WHERE id=?", (amt, mid))
    c = execute("INSERT INTO member_txns(member_id,ttype,points_delta,amount_cents,note) VALUES(?,?,?,?,?)",
                (mid, "recharge", 0, amt, body.get("note", "储值充值")))
    execute("INSERT INTO transactions(ttype,amount_cents,ref_type,ref_id,note) VALUES(?,?,?,?,?)",
            ("income", amt, "member_recharge", c.lastrowid, "会员充值 " + mem["code"]))
    bump_sync("members")
    return {"ok": True, "balance_cents": q1("SELECT balance_cents FROM members WHERE id=?", (mid,))["balance_cents"]}

def h_member_sales(ctx, m, qs, body):
    mid = int(m.group(1)); _member_or_404(mid)
    return listwrap("SELECT * FROM sales WHERE member_id=? ORDER BY id DESC", (mid,), qs)

# ---------- 供应商 ----------

def h_supplier_list(ctx, m, qs, body):
    kw = qs.get("keyword", [""])[0]
    cond, params = "1=1", []
    if kw:
        cond = "(name LIKE ? OR contact LIKE ?)"; params = ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM suppliers WHERE " + cond + " ORDER BY id", params, qs)

def h_supplier_create(ctx, m, qs, body):
    if not body.get("name"):
        raise ApiError(422, "name 必填")
    c = execute("INSERT INTO suppliers(name,contact,phone,credit_days,debt_limit_cents) VALUES(?,?,?,?,?)",
                (body["name"], body.get("contact"), body.get("phone"), int(body.get("credit_days", 30) or 30),
                 int(body.get("debt_limit_cents", 5000000) or 5000000)))
    return {"id": c.lastrowid}

def h_supplier_update(ctx, m, qs, body):
    sid = int(m.group(1))
    if not q1("SELECT id FROM suppliers WHERE id=?", (sid,)):
        raise ApiError(404, "供应商不存在")
    sets, params = [], []
    for f in ("name", "contact", "phone", "credit_days", "debt_limit_cents"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(sid)
        execute("UPDATE suppliers SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_supplier_delete(ctx, m, qs, body):
    sid = int(m.group(1))
    if q1("SELECT id FROM purchases WHERE supplier_id=? LIMIT 1", (sid,)):
        raise ApiError(409, "供应商有采购记录，禁止删除")
    execute("DELETE FROM suppliers WHERE id=?", (sid,))
    return {"ok": True}

# ---------- 促销 ----------

def h_promo_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    if qs.get("ptype", [""])[0]:
        cond += " AND ptype=?"; params.append(qs["ptype"][0])
    if qs.get("store_id", [""])[0]:
        cond += " AND (store_id=? OR store_id IS NULL)"; params.append(int(qs["store_id"][0]))
    if qs.get("date", [""])[0]:
        d = qs["date"][0]
        cond += " AND start_date<=? AND end_date>=?"; params += [d, d]
    return listwrap("SELECT * FROM promotions WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_promo_create(ctx, m, qs, body):
    if not body.get("name") or not body.get("ptype"):
        raise ApiError(422, "name/ptype 必填")
    ptype = body["ptype"]
    if ptype not in ("full_off", "discount"):
        raise ApiError(422, "ptype 须为 full_off/discount")
    rate = int(body.get("rate", 100) or 100)
    if ptype == "full_off" and (not body.get("threshold_cents") or not body.get("off_cents")):
        raise ApiError(422, "full_off 需 threshold_cents/off_cents")
    if ptype == "discount" and not (0 < rate < 100):
        raise ApiError(422, "discount 需 0 < rate < 100（如 88 表示 88 折）")
    start = body.get("start_date"); end = body.get("end_date")
    if not start or not end:
        raise ApiError(422, "start_date/end_date 必填")
    # 同门店同类型时间窗重叠检测
    rows = q("SELECT * FROM promotions WHERE ptype=? AND status='active'", (ptype,))
    for r in rows:
        if body.get("store_id") != r["store_id"]:
            continue
        if K.date_overlap(start[:10], end[:10], r["start_date"][:10], r["end_date"][:10]):
            raise ApiError(422, "与促销「%s」时间窗重叠" % r["name"])
    c = execute("INSERT INTO promotions(name,ptype,threshold_cents,off_cents,rate,start_date,end_date,store_id,status) VALUES(?,?,?,?,?,?,?,?,?)",
                (body["name"], ptype, int(body.get("threshold_cents", 0) or 0), int(body.get("off_cents", 0) or 0),
                 rate, start, end, body.get("store_id"), body.get("status", "active")))
    bump_sync("promotions")
    return {"id": c.lastrowid}

def _promo_or_404(pid):
    r = q1("SELECT * FROM promotions WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "促销不存在")
    return r

def h_promo_get(ctx, m, qs, body):
    return dict(_promo_or_404(int(m.group(1))))

def h_promo_update(ctx, m, qs, body):
    pid = int(m.group(1)); _promo_or_404(pid)
    sets, params = [], []
    for f in ("name", "threshold_cents", "off_cents", "rate", "start_date", "end_date", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(pid)
        execute("UPDATE promotions SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("promotions")
    return {"ok": True}

def h_promo_delete(ctx, m, qs, body):
    execute("DELETE FROM promotions WHERE id=?", (int(m.group(1)),))
    bump_sync("promotions")
    return {"ok": True}

def h_promo_calc(ctx, m, qs, body):
    """试算：{subtotal_cents, member_level?, store_id?} → 优惠分解"""
    sub = int(body.get("subtotal_cents", 0) or 0)
    promos = q("SELECT * FROM promotions WHERE status='active'", ())
    avail = [r for r in promos if K.promo_active(r, store_id=body.get("store_id"))]
    promo, off = K.best_promotion(avail, sub)
    rate = K.member_rate(body.get("member_level") or "")
    remainder = sub - off
    paid = K.payable_cents(remainder, rate)
    return {"subtotal_cents": sub, "promotion": dict(promo) if promo else None,
            "promo_off_cents": off, "member_rate": rate,
            "member_off_cents": remainder - paid, "paid_cents": paid}

# ---------- POS 销售 ----------

def _sale_full(sid):
    r = q1("SELECT * FROM sales WHERE id=?", (sid,))
    if not r:
        raise ApiError(404, "销售单不存在")
    d = dict(r)
    d["items"] = [dict(x) for x in q("SELECT * FROM sale_items WHERE sale_id=? ORDER BY id", (sid,))]
    d["store"] = dict(q1("SELECT id,code,name FROM stores WHERE id=?", (r["store_id"],)) or {}) if r["store_id"] else None
    if r["member_id"]:
        mem = q1("SELECT id,code,name,level FROM members WHERE id=?", (r["member_id"],))
        d["member"] = dict(mem) if mem else None
    return d

def h_sale_list(ctx, m, qs, body):
    cond, params = "1=1", []
    for f in ("store_id", "member_id", "status", "pay_method"):
        if qs.get(f, [""])[0]:
            cond += " AND %s=?" % f; params.append(int(qs[f][0]) if f.endswith("_id") else qs[f][0])
    if qs.get("date", [""])[0]:
        cond += " AND date(created_at)=?"; params.append(qs["date"][0])
    if qs.get("date_from", [""])[0]:
        cond += " AND date(created_at)>=?"; params.append(qs["date_from"][0])
    if qs.get("date_to", [""])[0]:
        cond += " AND date(created_at)<=?"; params.append(qs["date_to"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND no LIKE ?"; params.append("%" + kw + "%")
    return listwrap("SELECT * FROM sales WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_sale_get(ctx, m, qs, body):
    return _sale_full(int(m.group(1)))

def h_sale_create(ctx, m, qs, body):
    if not body.get("store_id"):
        raise ApiError(422, "store_id 必填")
    _store_or_404(body["store_id"])
    items = body.get("items") or []
    if not items:
        raise ApiError(422, "items 不能为空")
    pay_method = body.get("pay_method", "cash")
    if pay_method not in ("cash", "wechat", "alipay", "balance"):
        raise ApiError(422, "pay_method 非法")
    member = None
    if body.get("member_id"):
        member = _member_or_404(body["member_id"])
    # 明细与小计
    prepared, totals = [], []
    for it in items:
        if not it.get("commodity_id"):
            raise ApiError(422, "items[].commodity_id 必填")
        c = _comm_or_404(it["commodity_id"])
        qty = int(it.get("qty", 1) or 1)
        if qty <= 0:
            raise ApiError(422, "qty 须为正数")
        unit_price = int(it.get("unit_price_cents") or c["price_cents"])
        amt = K.line_amount_cents(qty, unit_price)
        totals.append(amt)
        prepared.append((c, qty, unit_price, amt))
    subtotal = sum(totals)
    # 促销（自动匹配最优）
    promo_off = 0
    promo = None
    if body.get("promotion_id"):
        promo = _promo_or_404(body["promotion_id"])
        promo_off = K.promo_off_cents(promo, subtotal)
    else:
        rows = q("SELECT * FROM promotions WHERE status='active'", ())
        avail = [r for r in rows if K.promo_active(r, store_id=body["store_id"])]
        promo, promo_off = K.best_promotion(avail, subtotal)
    remainder = subtotal - promo_off
    # 会员折扣
    rate = K.member_rate(member["level"]) if member else 1.00
    paid = K.payable_cents(remainder, rate)
    member_off = remainder - paid
    # 余额支付
    if pay_method == "balance":
        if not member:
            raise ApiError(422, "余额支付需指定会员")
        if int(member["balance_cents"]) < paid:
            raise ApiError(422, "储值余额不足")
    # 库存 FEFO 预检（先校验后扣减，避免半扣）
    for c, qty, unit_price, amt in prepared:
        rows = q("SELECT * FROM inventory WHERE store_id=? AND commodity_id=?",
                 (body["store_id"], c["id"]))
        allocs, shortfall = K.fefe_batches(rows, qty)
        if shortfall > 0:
            raise ApiError(422, "库存不足: %s（需 %d，缺 %d）" % (c["name"], qty, shortfall))
    # 落库
    no = make_no("XS", "sale_no")
    c = execute("INSERT INTO sales(no,store_id,member_id,subtotal_cents,promo_off_cents,member_off_cents,paid_cents,pay_method,received_cents,points,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (no, body["store_id"], member["id"] if member else None, subtotal, promo_off, member_off,
                 paid, pay_method, int(body.get("received_cents", paid) or paid), 0, "paid"))
    sid = c.lastrowid
    margin_warns = []
    for c2, qty, unit_price, amt in prepared:
        rows = q("SELECT * FROM inventory WHERE store_id=? AND commodity_id=?", (body["store_id"], c2["id"]))
        allocs, _ = K.fefe_batches(rows, qty)
        for inv_id, batch_no, take in allocs:
            execute("UPDATE inventory SET qty=qty-?, version=version+1 WHERE id=?", (take, inv_id))
        execute("INSERT INTO sale_items(sale_id,commodity_id,commodity_name,qty,unit_price_cents,cost_cents,amount_cents) VALUES(?,?,?,?,?,?,?)",
                (sid, c2["id"], c2["name"], qty, unit_price, c2["cost_cents"], amt))
        if K.negative_margin(unit_price, c2["cost_cents"]):
            margin_warns.append(c2["name"])
    for name in margin_warns:
        execute("INSERT INTO risks(rtype,ref_id,title,detail,score,grade) VALUES('negative_margin',?,?,?,35,'warn')",
                (sid, "负毛利销售", "销售 %s 中「%s」折后售价低于进价" % (no, name)))
    # 支付流水
    execute("INSERT INTO transactions(ttype,amount_cents,ref_type,ref_id,pay_method,note) VALUES('income',?,?,?,?,?)",
            (paid, "sale", sid, pay_method, "销售收款 " + no))
    # 会员积分与余额
    pts = 0
    if member:
        pts = K.points_earned(paid)
        execute("UPDATE members SET points=points+? WHERE id=?", (pts, member["id"]))
        execute("INSERT INTO member_txns(member_id,ttype,points_delta,amount_cents,note,ref_id) VALUES(?,?,?,?,?,?)",
                (member["id"], "earn", pts, paid, "消费积分 " + no, sid))
        if pay_method == "balance":
            execute("UPDATE members SET balance_cents=balance_cents-? WHERE id=?", (paid, member["id"]))
            execute("INSERT INTO member_txns(member_id,ttype,points_delta,amount_cents,note,ref_id) VALUES(?,?,?,?,?,?)",
                    (member["id"], "spend", 0, -paid, "余额消费 " + no, sid))
        # 升级检查
        cur_pts = q1("SELECT points FROM members WHERE id=?", (member["id"],))["points"]
        new_lv = K.points_to_level(cur_pts)
        if new_lv != member["level"]:
            execute("UPDATE members SET level=? WHERE id=?", (new_lv, member["id"]))
    bump_sync("sales"); bump_sync("inventory"); bump_sync("transactions")
    d = _sale_full(sid)
    d["points_earned"] = pts
    d["change_cents"] = max(0, int(body.get("received_cents", paid) or paid) - paid) if pay_method == "cash" else 0
    d["level_upgraded"] = (member and K.points_to_level(q1("SELECT points FROM members WHERE id=?", (member["id"],))["points"]) != member["level"])
    d["margin_warnings"] = margin_warns
    return d

def h_sale_refund(ctx, m, qs, body):
    sid = int(m.group(1))
    r = q1("SELECT * FROM sales WHERE id=?", (sid,))
    if not r:
        raise ApiError(404, "销售单不存在")
    if r["status"] != "paid":
        raise ApiError(422, "仅已支付销售单可退货")
    items = q("SELECT * FROM sale_items WHERE sale_id=?", (sid,))
    # 回补库存
    for it in items:
        # 找到该商品门店批次，回补到最早批次（简化：任选有记录批次或建 RMA 批次）
        inv = q1("SELECT id FROM inventory WHERE store_id=? AND commodity_id=? LIMIT 1",
                 (r["store_id"], it["commodity_id"]))
        if inv:
            execute("UPDATE inventory SET qty=qty+?, version=version+1 WHERE id=?", (it["qty"], inv["id"]))
        else:
            execute("INSERT INTO inventory(store_id,commodity_id,batch_no,qty) VALUES(?,?,?,?)",
                    (r["store_id"], it["commodity_id"], "RMA-%s" % r["no"], it["qty"]))
    refund_no = make_no("TH", "refund_no")
    execute("UPDATE sales SET status='refunded' WHERE id=?", (sid,))
    execute("INSERT INTO transactions(ttype,amount_cents,ref_type,ref_id,note) VALUES('refund',?, 'sale', ?, ?)",
            (-r["paid_cents"], sid, "退货 " + refund_no + "（原单 " + r["no"] + "）"))
    if r["member_id"]:
        execute("UPDATE members SET points=MAX(0, points-?) WHERE id=?", (r["points"] or 0, r["member_id"]))
        execute("INSERT INTO member_txns(member_id,ttype,points_delta,amount_cents,note,ref_id) VALUES(?,?,?,?,?,?)",
                (r["member_id"], "refund_earn", -(r["points"] or 0), -r["paid_cents"], "退货冲减 " + refund_no, sid))
    bump_sync("sales"); bump_sync("inventory"); bump_sync("transactions")
    return {"ok": True, "refund_no": refund_no, "refund_cents": r["paid_cents"]}

# ---------- 库存 ----------

def h_inv_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("store_id", [""])[0]:
        cond += " AND i.store_id=?"; params.append(int(qs["store_id"][0]))
    if qs.get("commodity_id", [""])[0]:
        cond += " AND i.commodity_id=?"; params.append(int(qs["commodity_id"][0]))
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND d.name LIKE ?"; params.append("%" + kw + "%")
    if qs.get("near_expiry_days", [""])[0]:
        days = int(qs["near_expiry_days"][0])
        limit = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
        cond += " AND i.expire_at<=?"; params.append(limit)
    return listwrap("SELECT i.*, d.name AS commodity_name, d.sku, d.safe_stock FROM inventory i JOIN commodities d ON d.id=i.commodity_id WHERE " + cond + " ORDER BY i.expire_at, i.id", params, qs)

def h_inv_summary(ctx, m, qs, body):
    sid = qs.get("store_id", [""])[0]
    cid = qs.get("commodity_id", [""])[0]
    if not cid:
        raise ApiError(422, "commodity_id 必填")
    cond = "commodity_id=?"
    params = [int(cid)]
    if sid:
        cond += " AND store_id=?"; params.append(int(sid))
    rows = q("SELECT batch_no,qty,expire_at,store_id FROM inventory WHERE " + cond + " ORDER BY expire_at", params)
    return {"commodity_id": int(cid), "store_id": int(sid) if sid else None,
            "total": sum(int(r["qty"] or 0) for r in rows), "batches": [dict(r) for r in rows]}

# ---------- 采购 ----------

PURCHASE_ACTIONS = {"to_submitted": "submitted", "to_received": "received", "to_cancelled": "cancelled"}

def _purchase_full(pid):
    r = q1("SELECT * FROM purchases WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "采购单不存在")
    d = dict(r)
    d["items"] = [dict(x) for x in q("SELECT pi.*, cm.name AS commodity_name FROM purchase_items pi JOIN commodities cm ON cm.id=pi.commodity_id WHERE pi.purchase_id=? ORDER BY pi.id", (pid,))]
    s = q1("SELECT name,phone FROM suppliers WHERE id=?", (r["supplier_id"],))
    d["supplier"] = dict(s) if s else None
    return d

def h_purchase_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    if qs.get("supplier_id", [""])[0]:
        cond += " AND supplier_id=?"; params.append(int(qs["supplier_id"][0]))
    if qs.get("store_id", [""])[0]:
        cond += " AND store_id=?"; params.append(int(qs["store_id"][0]))
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND no LIKE ?"; params.append("%" + kw + "%")
    return listwrap("SELECT * FROM purchases WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_purchase_get(ctx, m, qs, body):
    return _purchase_full(int(m.group(1)))

def h_purchase_create(ctx, m, qs, body):
    if not body.get("supplier_id"):
        raise ApiError(422, "supplier_id 必填")
    if not q1("SELECT id FROM suppliers WHERE id=?", (body["supplier_id"],)):
        raise ApiError(404, "供应商不存在")
    items = body.get("items") or []
    if not items:
        raise ApiError(422, "items 不能为空")
    no = make_no("CG", "purchase_no")
    total = K.purchase_total_cents(items)
    c = execute("INSERT INTO purchases(no,supplier_id,store_id,status,total_cents) VALUES(?,?,?,?,?)",
                (no, body["supplier_id"], body.get("store_id"), "draft", total))
    pid = c.lastrowid
    for it in items:
        if not it.get("commodity_id"):
            raise ApiError(422, "items[].commodity_id 必填")
        _comm_or_404(it["commodity_id"])
        qty = int(it.get("qty", 0) or 0)
        cost = int(it.get("cost_cents", 0) or 0)
        execute("INSERT INTO purchase_items(purchase_id,commodity_id,qty,cost_cents,amount_cents,batch_no,expiry) VALUES(?,?,?,?,?,?,?)",
                (pid, it["commodity_id"], qty, cost, qty * cost, it.get("batch_no"), it.get("expiry")))
    return _purchase_full(pid)

def h_purchase_item_add(ctx, m, qs, body):
    pid = int(m.group(1))
    r = q1("SELECT * FROM purchases WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "采购单不存在")
    if r["status"] != "draft":
        raise ApiError(422, "仅草稿采购单可加明细")
    if not body.get("commodity_id"):
        raise ApiError(422, "commodity_id 必填")
    _comm_or_404(body["commodity_id"])
    qty = int(body.get("qty", 0) or 0)
    cost = int(body.get("cost_cents", 0) or 0)
    execute("INSERT INTO purchase_items(purchase_id,commodity_id,qty,cost_cents,amount_cents,batch_no,expiry) VALUES(?,?,?,?,?,?,?)",
            (pid, body["commodity_id"], qty, cost, qty * cost, body.get("batch_no"), body.get("expiry")))
    total = q1("SELECT SUM(amount_cents) s FROM purchase_items WHERE purchase_id=?", (pid,))["s"] or 0
    execute("UPDATE purchases SET total_cents=? WHERE id=?", (total, pid))
    return _purchase_full(pid)

def h_purchase_transition(ctx, m, qs, body):
    pid = int(m.group(1))
    r = q1("SELECT * FROM purchases WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "采购单不存在")
    action = body.get("action") or ""
    if action not in PURCHASE_ACTIONS:
        raise ApiError(422, "action 须为 " + "/".join(PURCHASE_ACTIONS))
    nxt = PURCHASE_ACTIONS[action]
    if not K.can_transition(K.PURCHASE_TRANS, r["status"], nxt):
        raise ApiError(422, "采购单 %s 不允许 %s → %s" % (r["no"], r["status"], nxt))
    if nxt == "received":
        items = q("SELECT * FROM purchase_items WHERE purchase_id=?", (pid,))
        if not items:
            raise ApiError(422, "采购单无明细，不可入库")
        store_id = r["store_id"] or 1
        for it in items:
            batch = it["batch_no"] or ("%s-B%d" % (r["no"], it["id"]))
            exist = q1("SELECT id FROM inventory WHERE store_id=? AND commodity_id=? AND batch_no=?",
                       (store_id, it["commodity_id"], batch))
            if exist:
                execute("UPDATE inventory SET qty=qty+?, expire_at=COALESCE(?, expire_at), version=version+1 WHERE id=?",
                        (it["qty"], it["expiry"], exist["id"]))
            else:
                execute("INSERT INTO inventory(store_id,commodity_id,batch_no,qty,expire_at) VALUES(?,?,?,?,?)",
                        (store_id, it["commodity_id"], batch, it["qty"], it["expiry"]))
        sup = q1("SELECT * FROM suppliers WHERE id=?", (r["supplier_id"],))
        execute("UPDATE suppliers SET payable_cents=payable_cents+? WHERE id=?", (r["total_cents"], r["supplier_id"]))
        if K.supplier_over_debt(int(sup["payable_cents"] or 0) + r["total_cents"], sup["debt_limit_cents"]):
            execute("INSERT INTO risks(rtype,ref_id,title,detail,score,grade) VALUES('supplier_overdue',?,?,?,20,'risk')",
                    (sup["id"], "供应商欠款超限", "%s 应付将超过欠款上限" % sup["name"]))
        execute("INSERT INTO transactions(ttype,amount_cents,ref_type,ref_id,note) VALUES('expense',?, 'purchase', ?, '采购入库 ' || ?)",
                (-r["total_cents"], pid, r["no"]))
        bump_sync("inventory")
        bump_sync("transactions")
    execute("UPDATE purchases SET status=? WHERE id=?", (nxt, pid))
    bump_sync("purchases")
    return {"ok": True, "status": nxt}

def h_purchase_delete(ctx, m, qs, body):
    pid = int(m.group(1))
    r = q1("SELECT * FROM purchases WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "采购单不存在")
    if r["status"] not in ("draft", "cancelled"):
        raise ApiError(422, "仅草稿/已取消采购单可删除")
    execute("DELETE FROM purchase_items WHERE purchase_id=?", (pid,))
    execute("DELETE FROM purchases WHERE id=?", (pid,))
    return {"ok": True}

# ---------- 财务 ----------

def h_tx_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("ttype", [""])[0]:
        cond += " AND ttype=?"; params.append(qs["ttype"][0])
    if qs.get("date_from", [""])[0]:
        cond += " AND date(created_at)>=?"; params.append(qs["date_from"][0])
    if qs.get("date_to", [""])[0]:
        cond += " AND date(created_at)<=?"; params.append(qs["date_to"][0])
    return listwrap("SELECT * FROM transactions WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_finance_summary(ctx, m, qs, body):
    d = qs.get("date", [""])[0] or time.strftime("%Y-%m-%d")
    income = q1("SELECT COALESCE(SUM(amount_cents),0) s FROM transactions WHERE ttype='income' AND date(created_at)=?", (d,))["s"]
    refund = q1("SELECT COALESCE(SUM(amount_cents),0) s FROM transactions WHERE ttype='refund' AND date(created_at)=?", (d,))["s"]
    expense = q1("SELECT COALESCE(SUM(amount_cents),0) s FROM transactions WHERE ttype='expense' AND date(created_at)=?", (d,))["s"]
    by_method = {}
    for r in q("SELECT pay_method m, SUM(amount_cents) s FROM transactions WHERE ttype='income' AND date(created_at)=? GROUP BY pay_method", (d,)):
        by_method[r["m"] or "cash"] = int(r["s"] or 0)
    sale_count = q1("SELECT COUNT(*) c FROM sales WHERE date(created_at)=?", (d,))["c"]
    member_new = q1("SELECT COUNT(*) c FROM members WHERE date(created_at)=?", (d,))["c"]
    return {"date": d, "income_cents": int(income), "refund_cents": int(refund), "expense_cents": int(expense),
            "by_method": by_method, "sale_count": sale_count, "member_new": member_new}

# ---------- 风险 ----------

def h_risk_list(ctx, m, qs, body):
    cond, params = "1=1", []
    for f in ("status", "grade", "rtype"):
        if qs.get(f, [""])[0]:
            cond += " AND %s=?" % f; params.append(qs[f][0])
    return listwrap("SELECT * FROM risks WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_risk_scan(ctx, m, qs, body):
    created = 0
    by_type = {}
    today = datetime.date.today()
    def _exists(rtype, ref_id):
        return q1("SELECT id FROM risks WHERE rtype=? AND ref_id=? AND status='open'", (rtype, ref_id))
    # 1 商品低库存（按门店×商品）
    for r in q("SELECT s.id AS store_id, s.name AS store_name, c.id, c.name, c.safe_stock, COALESCE(SUM(i.qty),0) total FROM stores s CROSS JOIN commodities c LEFT JOIN inventory i ON i.store_id=s.id AND i.commodity_id=c.id WHERE c.safe_stock>0 GROUP BY s.id, c.id"):
        if int(r["total"]) <= r["safe_stock"]:
            if not _exists("stock_low", r["store_id"] * 100000 + r["id"]):
                execute("INSERT INTO risks(rtype,ref_id,title,detail,score,grade) VALUES('stock_low',?,?,?,30,'warn')",
                        (r["store_id"] * 100000 + r["id"], "商品低库存",
                         "[%s] %s 当前库存 %d ≤ 安全库存 %d" % (r["store_name"], r["name"], r["total"], r["safe_stock"])))
                created += 1; by_type["stock_low"] = by_type.get("stock_low", 0) + 1
    # 2 效期临期
    for r in q("SELECT i.id, c.name, i.store_id, i.batch_no, i.expire_at FROM inventory i JOIN commodities c ON c.id=i.commodity_id WHERE i.qty>0"):
        chk = K.expiry_check(r["expire_at"], 90, today)
        if chk and not _exists("expiry_near", r["id"]):
            execute("INSERT INTO risks(rtype,ref_id,title,detail,score,grade) VALUES('expiry_near',?,?,?,25,'warn')",
                    (r["id"], "商品效期预警", "门店 %d %s 批次 %s 效期 %s，剩余不足 90 天" % (r["store_id"], r["name"], r["batch_no"], r["expire_at"])))
            created += 1; by_type["expiry_near"] = by_type.get("expiry_near", 0) + 1
    # 3 供应商欠款超限
    for r in q("SELECT id, name, payable_cents, debt_limit_cents FROM suppliers WHERE debt_limit_cents>0 AND payable_cents>debt_limit_cents"):
        if not _exists("supplier_overdue", r["id"]):
            execute("INSERT INTO risks(rtype,ref_id,title,detail,score,grade) VALUES('supplier_overdue',?,?,?,20,'risk')",
                    (r["id"], "供应商欠款超限", "%s 应付 %d 超过上限 %d" % (r["name"], r["payable_cents"], r["debt_limit_cents"])))
            created += 1; by_type["supplier_overdue"] = by_type.get("supplier_overdue", 0) + 1
    return {"created": created, "by_type": by_type}

def h_risk_resolve(ctx, m, qs, body):
    rid = int(m.group(1))
    r = q1("SELECT * FROM risks WHERE id=?", (rid,))
    if not r:
        raise ApiError(404, "风险不存在")
    if r["status"] != "open":
        raise ApiError(422, "风险已处理")
    execute("UPDATE risks SET status='resolved', resolved_by=?, note=? WHERE id=?",
            (ctx["user"].get("name") or "", body.get("note"), rid))
    return {"ok": True}

# ---------- 仪表盘 ----------

def h_dashboard(ctx, m, qs, body):
    d = qs.get("date", [""])[0] or time.strftime("%Y-%m-%d")
    sale_today = q1("SELECT COUNT(*) c FROM sales WHERE date(created_at)=? AND status='paid'", (d,))["c"]
    income = q1("SELECT COALESCE(SUM(amount_cents),0) s FROM transactions WHERE ttype='income' AND date(created_at)=?", (d,))["s"]
    members = q1("SELECT COUNT(*) c FROM members WHERE status='active'", ())["c"]
    pending_po = q1("SELECT COUNT(*) c FROM purchases WHERE status='submitted'", ())["c"]
    low_stock = q1("SELECT COUNT(*) c FROM risks WHERE rtype='stock_low' AND status='open'", ())["c"]
    near_expiry = q1("SELECT COUNT(*) c FROM risks WHERE rtype='expiry_near' AND status='open'", ())["c"]
    active_promos = q1("SELECT COUNT(*) c FROM promotions WHERE status='active' AND end_date>=?", (d,))["c"]
    open_risks = q1("SELECT COUNT(*) c FROM risks WHERE status='open'", ())["c"]
    return {"date": d, "sales_today": sale_today, "income_cents": int(income),
            "members": members, "pending_purchase": pending_po,
            "low_stock": low_stock, "near_expiry": near_expiry,
            "active_promotions": active_promos, "open_risks": open_risks}

# ---------- 平台域 ----------

def h_notices(ctx, m, qs, body):
    return listwrap("SELECT * FROM notices ORDER BY id DESC", (), qs)

def h_notices_create(ctx, m, qs, body):
    if not body.get("title"):
        raise ApiError(422, "title 必填")
    c = execute("INSERT INTO notices(title,content,level) VALUES(?,?,?)",
                (body["title"], body.get("content", ""), body.get("level", "info")))
    return {"id": c.lastrowid}

def h_notices_delete(ctx, m, qs, body):
    execute("DELETE FROM notices WHERE id=?", (int(m.group(1)),))
    return {"ok": True}

def h_logs(ctx, m, qs, body):
    return listwrap("SELECT * FROM logs ORDER BY id DESC", (), qs)

def h_rules(ctx, m, qs, body):
    return {"items": [dict(r) for r in q("SELECT * FROM ret_rules ORDER BY id")]}

def h_rules_update(ctx, m, qs, body):
    name = body.get("name")
    if not name:
        raise ApiError(422, "name 必填")
    if not q1("SELECT id FROM ret_rules WHERE name=?", (name,)):
        execute("INSERT INTO ret_rules(name,value,updated_at) VALUES(?,?,?)", (name, body.get("value", ""), now_s()))
    else:
        execute("UPDATE ret_rules SET value=?, updated_at=? WHERE name=?", (body.get("value", ""), now_s(), name))
    return {"ok": True}

# ---------- 增量同步 / 导出 ----------

SYNC_ENTITIES = {
    "stores": "SELECT * FROM stores ORDER BY id",
    "commodities": "SELECT * FROM commodities ORDER BY id",
    "members": "SELECT * FROM members ORDER BY id",
    "promotions": "SELECT * FROM promotions ORDER BY id",
    "sales": "SELECT * FROM sales ORDER BY id",
    "inventory": "SELECT * FROM inventory ORDER BY id",
    "purchases": "SELECT * FROM purchases ORDER BY id",
    "risks": "SELECT * FROM risks ORDER BY id",
}

def h_sync(ctx, m, qs, body):
    since = int(qs.get("since", ["0"])[0] or 0)
    ents = [e for e in (qs.get("entities", [""])[0] or "").split(",") if e]
    if not ents:
        ents = list(SYNC_ENTITIES.keys())
    changes, maxver = [], 0
    for e in ents:
        if e not in SYNC_ENTITIES:
            raise ApiError(422, "未知同步实体: %s" % e)
        v = get_sync(e)
        maxver = max(maxver, v)
        if v > since:
            rows = [dict(r) for r in q(SYNC_ENTITIES[e])]
            for r in rows:
                changes.append({"entity": e, "op": "upsert", "row": r})
    return {"version": maxver, "since": since, "changes": changes}

EXPORTS = {
    "commodities": ("SELECT * FROM commodities ORDER BY id", ["sku", "barcode", "name", "unit", "category", "price_cents", "cost_cents"]),
    "members": ("SELECT * FROM members ORDER BY id", ["code", "name", "phone", "level", "points", "balance_cents"]),
    "sales": ("SELECT * FROM sales ORDER BY id", ["no", "store_id", "member_id", "subtotal_cents", "promo_off_cents", "member_off_cents", "paid_cents", "pay_method", "status", "created_at"]),
    "inventory": ("SELECT i.*, c.name FROM inventory i JOIN commodities c ON c.id=i.commodity_id ORDER BY i.id", ["name", "store_id", "batch_no", "qty", "expire_at"]),
    "transactions": ("SELECT * FROM transactions ORDER BY id", ["ttype", "amount_cents", "ref_type", "pay_method", "note", "created_at"]),
}

def h_export(ctx, m, qs, body):
    ent = m.group(1)
    if ent not in EXPORTS:
        raise ApiError(404, "未知导出实体")
    sql, cols = EXPORTS[ent]
    return ("csv", csv_export(q(sql), cols))

# ---------- 路由表 ----------

ROUTES = [
    ("GET",  r"^/api/health$", h_health, None),
    ("POST", r"^/api/login$", h_login, None),
    ("POST", r"^/api/logout$", h_logout, "auth"),
    ("GET",  r"^/api/me$", h_me, "auth"),
    ("GET",  r"^/api/users$", h_users, "admin"),
    ("POST", r"^/api/users$", h_users_create, "admin"),
    ("PUT",  r"^/api/users/(\d+)$", h_users_update, "admin"),
    ("DELETE", r"^/api/users/(\d+)$", h_users_delete, "admin"),
    ("GET",  r"^/api/api-keys$", h_keys, "admin"),
    ("POST", r"^/api/api-keys$", h_keys_create, "admin"),
    ("DELETE", r"^/api/api-keys/(\d+)$", h_keys_delete, "admin"),
    ("GET",  r"^/api/stores$", h_store_list, "retail.stores.read"),
    ("POST", r"^/api/stores$", h_store_create, "retail.stores.write"),
    ("GET",  r"^/api/stores/(\d+)$", h_store_get, "retail.stores.read"),
    ("PUT",  r"^/api/stores/(\d+)$", h_store_update, "retail.stores.write"),
    ("DELETE", r"^/api/stores/(\d+)$", h_store_delete, "retail.stores.write"),
    ("GET",  r"^/api/commodities$", h_comm_list, "retail.commodities.read"),
    ("POST", r"^/api/commodities$", h_comm_create, "retail.commodities.write"),
    ("GET",  r"^/api/commodities/barcode/([0-9Xx]+)$", h_comm_barcode, "retail.commodities.read"),
    ("GET",  r"^/api/commodities/(\d+)$", h_comm_get, "retail.commodities.read"),
    ("PUT",  r"^/api/commodities/(\d+)$", h_comm_update, "retail.commodities.write"),
    ("DELETE", r"^/api/commodities/(\d+)$", h_comm_delete, "retail.commodities.write"),
    ("GET",  r"^/api/members$", h_member_list, "retail.members.read"),
    ("POST", r"^/api/members$", h_member_create, "retail.members.write"),
    ("GET",  r"^/api/members/(\d+)$", h_member_get, "retail.members.read"),
    ("PUT",  r"^/api/members/(\d+)$", h_member_update, "retail.members.write"),
    ("DELETE", r"^/api/members/(\d+)$", h_member_delete, "retail.members.write"),
    ("GET",  r"^/api/members/(\d+)/txns$", h_member_txns, "retail.members.read"),
    ("POST", r"^/api/members/(\d+)/recharge$", h_member_recharge, "retail.members.write"),
    ("GET",  r"^/api/members/(\d+)/sales$", h_member_sales, "retail.members.read"),
    ("GET",  r"^/api/suppliers$", h_supplier_list, "retail.suppliers.read"),
    ("POST", r"^/api/suppliers$", h_supplier_create, "retail.suppliers.write"),
    ("PUT",  r"^/api/suppliers/(\d+)$", h_supplier_update, "retail.suppliers.write"),
    ("DELETE", r"^/api/suppliers/(\d+)$", h_supplier_delete, "retail.suppliers.write"),
    ("GET",  r"^/api/promotions$", h_promo_list, "retail.promotions.read"),
    ("POST", r"^/api/promotions$", h_promo_create, "retail.promotions.write"),
    ("GET",  r"^/api/promotions/(\d+)$", h_promo_get, "retail.promotions.read"),
    ("PUT",  r"^/api/promotions/(\d+)$", h_promo_update, "retail.promotions.write"),
    ("DELETE", r"^/api/promotions/(\d+)$", h_promo_delete, "retail.promotions.write"),
    ("POST", r"^/api/promotions/calc$", h_promo_calc, "retail.promotions.read"),
    ("GET",  r"^/api/sales$", h_sale_list, "retail.sales.read"),
    ("POST", r"^/api/sales$", h_sale_create, "retail.sales.write"),
    ("GET",  r"^/api/sales/(\d+)$", h_sale_get, "retail.sales.read"),
    ("POST", r"^/api/sales/(\d+)/refund$", h_sale_refund, "retail.sales.write"),
    ("GET",  r"^/api/inventory$", h_inv_list, "retail.inventory.read"),
    ("GET",  r"^/api/inventory/summary$", h_inv_summary, "retail.inventory.read"),
    ("GET",  r"^/api/purchases$", h_purchase_list, "retail.purchases.read"),
    ("POST", r"^/api/purchases$", h_purchase_create, "retail.purchases.write"),
    ("GET",  r"^/api/purchases/(\d+)$", h_purchase_get, "retail.purchases.read"),
    ("DELETE", r"^/api/purchases/(\d+)$", h_purchase_delete, "retail.purchases.write"),
    ("POST", r"^/api/purchases/(\d+)/items$", h_purchase_item_add, "retail.purchases.write"),
    ("POST", r"^/api/purchases/(\d+)/transition$", h_purchase_transition, "retail.purchases.write"),
    ("GET",  r"^/api/transactions$", h_tx_list, "retail.sales.read"),
    ("GET",  r"^/api/finance/summary$", h_finance_summary, "retail.sales.read"),
    ("GET",  r"^/api/risks$", h_risk_list, "retail.risk.read"),
    ("POST", r"^/api/risks/scan$", h_risk_scan, "retail.risk.write"),
    ("PUT",  r"^/api/risks/(\d+)/resolve$", h_risk_resolve, "retail.risk.write"),
    ("GET",  r"^/api/dashboard$", h_dashboard, "auth"),
    ("GET",  r"^/api/notices$", h_notices, "auth"),
    ("POST", r"^/api/notices$", h_notices_create, "admin"),
    ("DELETE", r"^/api/notices/(\d+)$", h_notices_delete, "admin"),
    ("GET",  r"^/api/logs$", h_logs, "admin"),
    ("GET",  r"^/api/rules$", h_rules, "auth"),
    ("PUT",  r"^/api/rules$", h_rules_update, "admin"),
    ("GET",  r"^/api/sync$", h_sync, "auth"),
    ("GET",  r"^/api/export/([a-z]+)$", h_export, "auth"),
]

_COMPILED = [(mt, re.compile(rx), fn, perm) for mt, rx, fn, perm in ROUTES]

# ---------- HTTP Handler ----------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FeiShouRMS/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, data, ctype="application/json; charset=utf-8", extra=None):
        body = data if isinstance(data, bytes) else data.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Token, X-Api-Key, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, code, data):
        if isinstance(data, str):
            self._send(code, jdump({"code": code, "message": data, "data": None}))
        else:
            self._send(code, jdump({"code": code, "message": "ok" if code < 400 else "error", "data": data}))

    def _body(self):
        ln = int(self.headers.get("Content-Length") or 0)
        if ln <= 0:
            return {}
        raw = self.rfile.read(ln)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _token_from_req(self):
        h = self.headers
        auth = h.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        if h.get("X-Token"):
            return h["X-Token"].strip()
        ck = h.get("Cookie")
        if ck:
            try:
                c = http_cookies.SimpleCookie(ck)
                if "retail_token" in c:
                    return c["retail_token"].value
                if "token" in c:
                    return c["token"].value
            except Exception:
                pass
        if h.get("X-Api-Key"):
            return "key:" + h["X-Api-Key"].strip()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "token" in qs:
            return qs["token"][0]
        return None

    def _authenticate(self):
        tok = self._token_from_req()
        if not tok:
            return None, None
        if tok.startswith("key:"):
            u = auth_key(tok[4:])
            return ({"id": None, **u} if u else None), tok
        u = auth_token(tok)
        if u:
            perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"])
            return {"id": u["user_id"], "username": u["username"], "name": u["name"], "role": u["role"], "perms": perms}, tok
        return None, tok

    def _match_route(self, method, path):
        for mt, rx, fn, perm in _COMPILED:
            if mt != method:
                continue
            m = rx.match(path)
            if m:
                return fn, perm, m
        return None, None, None

    def _handle(self, method):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if PREFIX and path.startswith(PREFIX):
                path = path[len(PREFIX):] or "/"
            if method == "OPTIONS":
                return self._send(200, "{}")
            if not path.startswith("/api/"):
                return self._static(path)
            qs = urllib.parse.parse_qs(parsed.query)
            fn, perm, m = self._match_route(method, path)
            if not fn:
                return self._send_json(404, "接口不存在: %s" % path)
            user, tok = self._authenticate()
            ctx = {"user": user or {}, "token": (tok or "").replace("key:", "")}
            if perm is not None and not user:
                return self._send_json(401, "未认证")
            if perm == "admin":
                if not user or user.get("role") != "admin":
                    return self._send_json(403, "需要管理员权限")
            elif perm == "auth":
                if not user:
                    return self._send_json(401, "未认证")
            elif perm:
                perms = user.get("perms") if user else None
                if not user or not K.has_perm(perms or [], perm):
                    return self._send_json(403, "无权限: " + perm)
            body = self._body() if method in ("POST", "PUT", "DELETE") else {}
            idem = self.headers.get("Idempotency-Key")
            if idem and method == "POST":
                row = q1("SELECT response FROM idem_keys WHERE key=?", (idem,))
                if row:
                    return self._send(200, row["response"])
            result = fn(ctx, m, qs, body)
            if isinstance(result, tuple) and result[0] == "csv":
                return self._send(200, result[1], ctype="text/csv; charset=utf-8",
                                  extra={"Content-Disposition": "attachment; filename=export.csv"})
            payload = jdump({"code": 200, "message": "ok", "data": result})
            if idem and method == "POST":
                execute("INSERT OR REPLACE INTO idem_keys(key, user_id, response, created_at) VALUES(?,?,?,?)",
                        (idem, user.get("id") if user else None, payload, now_s()))
            return self._send(200, payload)
        except ApiError as e:
            return self._send_json(e.code, e.message)
        except Exception as e:
            traceback.print_exc()
            return self._send_json(500, "内部错误: %s" % e)

    def _static(self, path):
        if path in ("/", "/index.html", ""):
            path = "/index.html"
        fp = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend"), path.lstrip("/"))
        fp = os.path.normpath(fp)
        if not fp.startswith(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))):
            return self._send(403, "forbidden", ctype="text/plain")
        if not os.path.isfile(fp):
            return self._send(404, "not found", ctype="text/plain")
        ctype = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8", "svg": "image/svg+xml", "png": "image/png", "ico": "image/x-icon"}.get(fp.rsplit(".", 1)[-1], "application/octet-stream")
        with open(fp, "rb") as f:
            return self._send(200, f.read(), ctype=ctype)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self._handle("OPTIONS")

def main():
    D.init_db()
    S.run()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("FeiShou RMS listening on :%d prefix=%r db=%s" % (PORT, PREFIX, D.DB_PATH))
    srv.serve_forever()

if __name__ == "__main__":
    main()
