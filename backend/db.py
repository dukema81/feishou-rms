# -*- coding: utf-8 -*-
"""飞售 RMS 数据层：建表 + 连接管理（零依赖，SQLite WAL）"""
import os, sqlite3, threading

DB_PATH = os.environ.get("RET_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "feishou.db"))
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL, address TEXT, phone TEXT,
  status TEXT DEFAULT 'active', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS commodities(
  id INTEGER PRIMARY KEY, sku TEXT UNIQUE, barcode TEXT UNIQUE, name TEXT NOT NULL,
  unit TEXT DEFAULT '件', category TEXT, price_cents INTEGER DEFAULT 0, cost_cents INTEGER DEFAULT 0,
  shelf_life_days INTEGER DEFAULT 365, safe_stock INTEGER DEFAULT 10, status TEXT DEFAULT 'active',
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS members(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL, phone TEXT,
  level TEXT DEFAULT 'normal', points INTEGER DEFAULT 0, balance_cents INTEGER DEFAULT 0,
  status TEXT DEFAULT 'active', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS member_txns(
  id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL, ttype TEXT NOT NULL,
  points_delta INTEGER DEFAULT 0, amount_cents INTEGER DEFAULT 0, note TEXT, ref_id INTEGER,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS promotions(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, ptype TEXT NOT NULL,
  threshold_cents INTEGER DEFAULT 0, off_cents INTEGER DEFAULT 0, rate INTEGER DEFAULT 100,
  start_date TEXT, end_date TEXT, store_id INTEGER, status TEXT DEFAULT 'active',
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS sales(
  id INTEGER PRIMARY KEY, no TEXT UNIQUE, store_id INTEGER NOT NULL, member_id INTEGER,
  subtotal_cents INTEGER DEFAULT 0, promo_off_cents INTEGER DEFAULT 0, member_off_cents INTEGER DEFAULT 0,
  paid_cents INTEGER DEFAULT 0, pay_method TEXT DEFAULT 'cash', received_cents INTEGER DEFAULT 0,
  points INTEGER DEFAULT 0, status TEXT DEFAULT 'paid', version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS sale_items(
  id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL, commodity_id INTEGER NOT NULL,
  commodity_name TEXT, qty INTEGER DEFAULT 1, unit_price_cents INTEGER DEFAULT 0,
  cost_cents INTEGER DEFAULT 0, amount_cents INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS inventory(
  id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, commodity_id INTEGER NOT NULL,
  batch_no TEXT NOT NULL, qty INTEGER DEFAULT 0, expire_at TEXT, version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(store_id, commodity_id, batch_no));
CREATE TABLE IF NOT EXISTS purchases(
  id INTEGER PRIMARY KEY, no TEXT UNIQUE, supplier_id INTEGER NOT NULL, store_id INTEGER,
  status TEXT DEFAULT 'draft', total_cents INTEGER DEFAULT 0, version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS purchase_items(
  id INTEGER PRIMARY KEY, purchase_id INTEGER NOT NULL, commodity_id INTEGER NOT NULL,
  qty INTEGER DEFAULT 0, cost_cents INTEGER DEFAULT 0, amount_cents INTEGER DEFAULT 0,
  batch_no TEXT, expiry TEXT);
CREATE TABLE IF NOT EXISTS suppliers(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, contact TEXT, phone TEXT,
  credit_days INTEGER DEFAULT 30, debt_limit_cents INTEGER DEFAULT 5000000,
  payable_cents INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY, ttype TEXT NOT NULL, amount_cents INTEGER DEFAULT 0,
  ref_type TEXT, ref_id INTEGER, pay_method TEXT, note TEXT, version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS risks(
  id INTEGER PRIMARY KEY, rtype TEXT, ref_id INTEGER, title TEXT, detail TEXT,
  score INTEGER DEFAULT 0, grade TEXT DEFAULT 'info', status TEXT DEFAULT 'open',
  resolved_by TEXT, note TEXT, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT NOT NULL, name TEXT,
  role TEXT DEFAULT 'reader', phone TEXT, status INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT, expires_at TEXT);
CREATE TABLE IF NOT EXISTS api_keys(
  id INTEGER PRIMARY KEY, name TEXT, key_hash TEXT UNIQUE, prefix TEXT, perms TEXT DEFAULT 'retail.*',
  created_at TEXT DEFAULT (datetime('now','localtime')), last_used TEXT, status INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY, title TEXT, content TEXT, level TEXT DEFAULT 'info', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, action TEXT, detail TEXT, ip TEXT);
CREATE TABLE IF NOT EXISTS idem_keys(key TEXT PRIMARY KEY, user_id INTEGER, response TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS sync_state(entity TEXT PRIMARY KEY, version INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ret_rules(id INTEGER PRIMARY KEY, name TEXT, value TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS seq(name TEXT PRIMARY KEY, val INTEGER DEFAULT 0);

CREATE INDEX IF NOT EXISTS idx_sales_status ON sales(status);
CREATE INDEX IF NOT EXISTS idx_sales_created ON sales(created_at);
CREATE INDEX IF NOT EXISTS idx_si_sale ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_inv_store ON inventory(store_id, commodity_id, expire_at);
CREATE INDEX IF NOT EXISTS idx_tx_type_date ON transactions(ttype, created_at);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
"""

def get_db():
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return conn

def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()

def q(sql, params=()):
    return get_db().execute(sql, params).fetchall()

def q1(sql, params=()):
    return get_db().execute(sql, params).fetchone()

def execute(sql, params=()):
    conn = get_db()
    import time as _t
    for attempt in range(30):
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as e:
            try:
                conn.rollback()
            except Exception:
                pass
            if "locked" in str(e).lower() and attempt < 29:
                _t.sleep(0.1)
                continue
            raise

def next_seq(name):
    row = q1("SELECT val FROM seq WHERE name=?", (name,))
    if row:
        execute("UPDATE seq SET val=val+1 WHERE name=?", (name,))
        return row["val"] + 1
    execute("INSERT INTO seq(name, val) VALUES(?, 1)", (name,))
    return 1

def make_no(prefix, seq_name):
    from datetime import datetime
    return "%s%s-%03d" % (prefix, datetime.now().strftime("%Y%m%d"), next_seq(seq_name))

def bump_sync(entity, conn=None):
    c = conn or get_db()
    c.execute("INSERT INTO sync_state(entity, version) VALUES(?,1) ON CONFLICT(entity) DO UPDATE SET version=version+1", (entity,))
    c.commit()
    row = c.execute("SELECT version FROM sync_state WHERE entity=?", (entity,)).fetchone()
    return row["version"] if row else 0

def get_sync(entity):
    row = q1("SELECT version FROM sync_state WHERE entity=?", (entity,))
    return row["version"] if row else 0
