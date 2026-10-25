import os
import sqlite3
import threading

from . import config

_lock = threading.Lock()
_conn = sqlite3.connect(os.path.join(config.DATA_DIR, "stella.db"), check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS memory   (id INTEGER PRIMARY KEY, fact TEXT UNIQUE, ts REAL);
    CREATE TABLE IF NOT EXISTS history  (id INTEGER PRIMARY KEY, role TEXT, content TEXT, ts REAL);
    CREATE TABLE IF NOT EXISTS notifs   (id INTEGER PRIMARY KEY, app TEXT, sender TEXT, text TEXT,
                                         key TEXT, importance TEXT, ts REAL);
    CREATE TABLE IF NOT EXISTS photos   (id INTEGER PRIMARY KEY, ts REAL, description TEXT, path TEXT);
    CREATE TABLE IF NOT EXISTS faces    (id INTEGER PRIMARY KEY, name TEXT, note TEXT,
                                         embedding BLOB, photo TEXT, ts REAL);
    CREATE TABLE IF NOT EXISTS homelog  (id INTEGER PRIMARY KEY, ts REAL, day TEXT, minute INTEGER,
                                         entity TEXT, state TEXT);
    CREATE TABLE IF NOT EXISTS reminded (key TEXT PRIMARY KEY, ts REAL);
    """
)


def q(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return _conn.execute(sql, args).fetchall()


def x(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid
