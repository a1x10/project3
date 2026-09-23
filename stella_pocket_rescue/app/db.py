"""SQLite-хранилище: переживает перезагрузку и отключение питания (WAL)."""
import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT UNIQUE NOT NULL,
    created       REAL NOT NULL,
    updated       REAL NOT NULL,
    priority      TEXT NOT NULL DEFAULT 'unknown',
    score         INTEGER NOT NULL DEFAULT 0,
    tags          TEXT NOT NULL DEFAULT '[]',
    people        INTEGER,
    lat           REAL,
    lon           REAL,
    accuracy      REAL,
    location_text TEXT,
    panic         INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'new',
    note          TEXT,
    client_ip     TEXT,
    mac           TEXT,
    device        TEXT,
    device_info   TEXT NOT NULL DEFAULT '{}',
    battery       REAL,
    charging      INTEGER,
    last_seen     REAL
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    text       TEXT NOT NULL,
    ts         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS broadcasts (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    ts   REAL NOT NULL
);
"""

INCIDENT_FIELDS = (
    "priority", "score", "tags", "people", "lat", "lon", "accuracy",
    "location_text", "panic", "status", "note",
    "client_ip", "mac", "device", "device_info", "battery", "charging", "last_seen",
)
JSON_FIELDS = {"tags", "device_info"}


class Database:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # --- messages ---
    def add_message(self, session_id: str, role: str, text: str) -> int:
        return self._exec(
            "INSERT INTO messages(session_id, role, text, ts) VALUES (?, ?, ?, ?)",
            (session_id, role, text, time.time()),
        ).lastrowid

    def messages(self, session_id: str, after_id: int = 0) -> list[dict]:
        return self._all(
            "SELECT id, role, text, ts FROM messages WHERE session_id = ? AND id > ? ORDER BY id",
            (session_id, after_id),
        )

    def last_message(self, session_id: str, role: str) -> dict | None:
        rows = self._all(
            "SELECT id, role, text, ts FROM messages WHERE session_id = ? AND role = ? "
            "ORDER BY id DESC LIMIT 1",
            (session_id, role),
        )
        return rows[0] if rows else None

    # --- incidents ---
    def get_incident(self, session_id: str) -> dict | None:
        rows = self._all("SELECT * FROM incidents WHERE session_id = ?", (session_id,))
        return _decode(rows[0]) if rows else None

    def get_incident_by_id(self, incident_id: int) -> dict | None:
        rows = self._all("SELECT * FROM incidents WHERE id = ?", (incident_id,))
        return _decode(rows[0]) if rows else None

    def upsert_incident(self, session_id: str, **fields) -> dict:
        unknown = set(fields) - set(INCIDENT_FIELDS)
        if unknown:
            raise ValueError(f"unknown fields: {unknown}")
        for jf in JSON_FIELDS & set(fields):
            fields[jf] = json.dumps(fields[jf], ensure_ascii=False)
        now = time.time()
        self._exec(
            "INSERT OR IGNORE INTO incidents(session_id, created, updated) VALUES (?, ?, ?)",
            (session_id, now, now),
        )
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            self._exec(
                f"UPDATE incidents SET {cols}, updated = ? WHERE session_id = ?",
                (*fields.values(), now, session_id),
            )
        return self.get_incident(session_id)

    def incidents(self) -> list[dict]:
        rows = self._all(
            "SELECT i.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = i.session_id "
            "AND m.role = 'user') AS user_messages FROM incidents i"
        )
        return [_decode(r) for r in rows]

    # --- broadcasts ---
    def add_broadcast(self, text: str) -> int:
        return self._exec(
            "INSERT INTO broadcasts(text, ts) VALUES (?, ?)", (text, time.time())
        ).lastrowid

    def broadcasts(self, after_id: int = 0) -> list[dict]:
        return self._all(
            "SELECT id, text, ts FROM broadcasts WHERE id > ? ORDER BY id", (after_id,)
        )


    def touch(self, session_id: str, **fields) -> None:
        """Отметить, что сессия жива (опрос сообщений), и обновить лёгкие поля."""
        fields["last_seen"] = time.time()
        self.upsert_incident(session_id, **fields)


def _decode(row: dict) -> dict:
    row["tags"] = json.loads(row["tags"])
    row["device_info"] = json.loads(row["device_info"] or "{}")
    row["panic"] = bool(row["panic"])
    row["charging"] = None if row["charging"] is None else bool(row["charging"])
    return row
