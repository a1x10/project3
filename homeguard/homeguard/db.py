import sqlite3
import threading
import time

from . import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    mac TEXT PRIMARY KEY,
    ip TEXT,
    hostname TEXT,
    vendor TEXT,
    type TEXT NOT NULL DEFAULT 'unknown',
    name TEXT,
    is_self INTEGER NOT NULL DEFAULT 0,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    client_ip TEXT NOT NULL,
    domain TEXT NOT NULL,
    qtype TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_queries_ts ON queries(ts);
CREATE INDEX IF NOT EXISTS idx_queries_client ON queries(client_ip);
CREATE TABLE IF NOT EXISTS vpn_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    kind TEXT NOT NULL,
    endpoint TEXT,
    has_auth INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""

DEFAULT_SETTINGS = {"level": "medium", "vpn_active": "", "vpn_kill_switch": "0"}


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            for k, v in DEFAULT_SETTINGS.items():
                _conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (k, v))
            _conn.commit()
        return _conn


def reset_for_tests():
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None


def execute(sql: str, args: tuple = ()) -> None:
    with _lock:
        c = connect()
        c.execute(sql, args)
        c.commit()


def query(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in connect().execute(sql, args).fetchall()]


def get_setting(key: str) -> str:
    rows = query("SELECT v FROM settings WHERE k = ?", (key,))
    return rows[0]["v"] if rows else DEFAULT_SETTINGS[key]


def set_setting(key: str, value: str) -> None:
    execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))


def log_query(client_ip: str, domain: str, qtype: str, action: str, reason: str | None) -> None:
    execute(
        "INSERT INTO queries (ts, client_ip, domain, qtype, action, reason) VALUES (?,?,?,?,?,?)",
        (time.time(), client_ip, domain, qtype, action, reason),
    )


def upsert_device(mac: str, ip: str, hostname: str | None, vendor: str | None,
                  dtype: str, is_self: bool = False, seen: float | None = None) -> None:
    """Обновляет устройство. Имя и тип, заданные пользователем вручную, не затираются."""
    now = seen or time.time()
    with _lock:
        c = connect()
        row = c.execute("SELECT mac FROM devices WHERE mac = ?", (mac,)).fetchone()
        if row:
            c.execute(
                """UPDATE devices SET ip = ?, last_seen = ?,
                   hostname = COALESCE(?, hostname), vendor = COALESCE(?, vendor),
                   is_self = MAX(is_self, ?) WHERE mac = ?""",
                (ip, now, hostname, vendor, int(is_self), mac),
            )
        else:
            c.execute(
                "INSERT INTO devices (mac, ip, hostname, vendor, type, is_self, first_seen, last_seen)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (mac, ip, hostname, vendor, dtype, int(is_self), now, now),
            )
        c.commit()
