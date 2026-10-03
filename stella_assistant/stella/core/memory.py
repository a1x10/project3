"""Долговременная память Стеллы (SQLite): диалог, факты о пользователе, списки,
заметки, будильники/таймеры/напоминания, события календаря, настройки."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from ..nlp.text import best_match

SCHEMA = """
CREATE TABLE IF NOT EXISTS dialog (id INTEGER PRIMARY KEY, ts REAL, role TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS facts (key TEXT PRIMARY KEY, value TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, list TEXT, text TEXT, done INTEGER DEFAULT 0, ts REAL);
CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, ts REAL, text TEXT);
CREATE TABLE IF NOT EXISTS alarms (id INTEGER PRIMARY KEY, kind TEXT, due REAL, label TEXT,
    repeat TEXT, enabled INTEGER DEFAULT 1, created REAL, extra TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, start REAL, end REAL, title TEXT,
    uid TEXT, synced INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS likes (key TEXT PRIMARY KEY, title TEXT, value INTEGER, ts REAL);
"""


class Memory:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    def _q(self, sql: str, args=(), commit: bool = False):
        with self._lock:
            cur = self.db.execute(sql, args)
            if commit:
                self.db.commit()
            return cur

    # ------------------------------------------------------------- диалог --
    def add_dialog(self, role: str, text: str):
        self._q("INSERT INTO dialog(ts, role, text) VALUES (?,?,?)", (time.time(), role, text), True)
        self._q("DELETE FROM dialog WHERE id NOT IN (SELECT id FROM dialog ORDER BY id DESC LIMIT 400)", (), True)

    def recent_dialog(self, n: int = 12, max_age: float = 6 * 3600) -> list[tuple[str, str]]:
        rows = self._q("SELECT role, text FROM dialog WHERE ts > ? ORDER BY id DESC LIMIT ?",
                       (time.time() - max_age, n)).fetchall()
        return [(r["role"], r["text"]) for r in reversed(rows)]

    def clear_dialog(self):
        self._q("DELETE FROM dialog", (), True)

    # -------------------------------------------------------------- факты --
    def set_fact(self, key: str, value: str):
        self._q("INSERT OR REPLACE INTO facts(key, value, ts) VALUES (?,?,?)", (key, value, time.time()), True)

    def get_fact(self, key: str, default=None):
        row = self._q("SELECT value FROM facts WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def facts(self) -> dict:
        return {r["key"]: r["value"] for r in self._q("SELECT key, value FROM facts ORDER BY ts").fetchall()}

    def forget_fact(self, query: str) -> str | None:
        facts = self.facts()
        best, _ = best_match(query, list(facts.items()), key=lambda kv: f"{kv[0]} {kv[1]}", threshold=0.45)
        if best:
            self._q("DELETE FROM facts WHERE key=?", (best[0],), True)
            return best[0]
        return None

    def clear_facts(self):
        self._q("DELETE FROM facts", (), True)

    # ----------------------------------------------------------------- kv --
    def kv_get(self, key: str, default=None):
        row = self._q("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def kv_set(self, key: str, value):
        self._q("INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)), True)

    # ------------------------------------------------------------- списки --
    def list_add(self, list_name: str, text: str) -> int:
        cur = self._q("INSERT INTO items(list, text, done, ts) VALUES (?,?,0,?)", (list_name, text.strip(), time.time()), True)
        return cur.lastrowid

    def list_items(self, list_name: str, include_done: bool = False) -> list[dict]:
        sql = "SELECT * FROM items WHERE list=?" + ("" if include_done else " AND done=0") + " ORDER BY id"
        return [dict(r) for r in self._q(sql, (list_name,)).fetchall()]

    def list_names(self) -> list[str]:
        return [r["list"] for r in self._q("SELECT DISTINCT list FROM items ORDER BY list").fetchall()]

    def _find_item(self, list_name: str, text: str):
        items = self.list_items(list_name, include_done=True)
        best, _ = best_match(text, items, key=lambda it: it["text"], threshold=0.55)
        return best

    def list_remove(self, list_name: str, text: str):
        it = self._find_item(list_name, text)
        if it:
            self._q("DELETE FROM items WHERE id=?", (it["id"],), True)
        return it

    def list_done(self, list_name: str, text: str, done: bool = True):
        it = self._find_item(list_name, text)
        if it:
            self._q("UPDATE items SET done=? WHERE id=?", (1 if done else 0, it["id"]), True)
        return it

    def item_set(self, item_id: int, **fields):
        for k, v in fields.items():
            if k in ("text", "done", "list"):
                self._q(f"UPDATE items SET {k}=? WHERE id=?", (v, item_id), True)

    def item_delete(self, item_id: int):
        self._q("DELETE FROM items WHERE id=?", (item_id,), True)

    def list_clear(self, list_name: str) -> int:
        return self._q("DELETE FROM items WHERE list=?", (list_name,), True).rowcount

    # ------------------------------------------------------------ заметки --
    def note_add(self, text: str) -> int:
        return self._q("INSERT INTO notes(ts, text) VALUES (?,?)", (time.time(), text.strip()), True).lastrowid

    def notes(self, n: int = 50) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (n,)).fetchall()]

    def note_delete(self, note_id: int):
        self._q("DELETE FROM notes WHERE id=?", (note_id,), True)

    def note_find_delete(self, text: str):
        best, _ = best_match(text, self.notes(500), key=lambda n: n["text"], threshold=0.5)
        if best:
            self.note_delete(best["id"])
        return best

    def notes_clear(self):
        self._q("DELETE FROM notes", (), True)

    # ------------------------------------- будильники, таймеры, напоминания --
    def alarm_add(self, kind: str, due: float, label: str = "", repeat=None, extra=None) -> int:
        cur = self._q(
            "INSERT INTO alarms(kind, due, label, repeat, enabled, created, extra) VALUES (?,?,?,?,1,?,?)",
            (kind, due, label, json.dumps(repeat) if repeat else None, time.time(),
             json.dumps(extra, ensure_ascii=False) if extra else None), True)
        return cur.lastrowid

    def alarms(self, kind: str | None = None, enabled_only: bool = True) -> list[dict]:
        sql, args = "SELECT * FROM alarms WHERE 1=1", []
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        if enabled_only:
            sql += " AND enabled=1"
        rows = self._q(sql + " ORDER BY due", args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["repeat"] = json.loads(d["repeat"]) if d["repeat"] else None
            d["extra"] = json.loads(d["extra"]) if d["extra"] else {}
            out.append(d)
        return out

    def alarm_update(self, alarm_id: int, **fields):
        for k, v in fields.items():
            if k in ("repeat", "extra"):
                v = json.dumps(v, ensure_ascii=False) if v else None
            if k in ("due", "label", "enabled", "repeat", "extra", "kind"):
                self._q(f"UPDATE alarms SET {k}=? WHERE id=?", (v, alarm_id), True)

    def alarm_delete(self, alarm_id: int):
        self._q("DELETE FROM alarms WHERE id=?", (alarm_id,), True)

    # ------------------------------------------------------------ события --
    def event_add(self, start: float, end: float, title: str, uid: str | None = None, synced: bool = False) -> int:
        return self._q("INSERT INTO events(start, end, title, uid, synced) VALUES (?,?,?,?,?)",
                       (start, end, title, uid, int(synced)), True).lastrowid

    def events_between(self, a: float, b: float) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM events WHERE start < ? AND end > ? ORDER BY start",
                                         (b, a)).fetchall()]

    def event_delete(self, event_id: int):
        self._q("DELETE FROM events WHERE id=?", (event_id,), True)

    # -------------------------------------------------------------- лайки --
    def like_set(self, key: str, title: str, value: int):
        self._q("INSERT OR REPLACE INTO likes(key, title, value, ts) VALUES (?,?,?,?)", (key, title, value, time.time()), True)

    def likes(self, value: int = 1) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM likes WHERE value=? ORDER BY ts DESC", (value,)).fetchall()]
