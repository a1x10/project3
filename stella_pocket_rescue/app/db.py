import json
import logging
import os
import sqlite3
import threading
import time
import urllib.parse

log = logging.getLogger("stella.db")

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
    ts         REAL NOT NULL,
    engine     TEXT
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS broadcasts (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    ts   REAL NOT NULL
);
"""

MIGRATIONS = (
    ("messages", "engine", "TEXT"),
)

INCIDENT_FIELDS = (
    "priority", "score", "tags", "people", "lat", "lon", "accuracy",
    "location_text", "panic", "status", "note",
    "client_ip", "mac", "device", "device_info", "battery", "charging", "last_seen",
)
JSON_FIELDS = {"tags", "device_info"}
MESSAGE_COLUMNS = "id, role, text, ts, engine"
CORRUPT_MARKERS = ("not a database", "malformed", "corrupt")


class Database:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._conn = self._open(path)

    def _open(self, path: str) -> sqlite3.Connection:
        try:
            return self._connect(path)
        except sqlite3.DatabaseError as exc:
            if path == ":memory:" or not any(m in str(exc).lower() for m in CORRUPT_MARKERS):
                raise
            log.error("база %s повреждена (%s), откладываю её в сторону и создаю новую", path, exc)
            _quarantine(path)
            return self._connect(path)

    def _connect(self, path: str) -> sqlite3.Connection:
        if path != ":memory:":
            folder = os.path.dirname(os.path.abspath(path))
            os.makedirs(folder, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            if path != ":memory:":
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                except sqlite3.OperationalError as exc:
                    log.warning("WAL недоступен: %s", exc)
            conn.executescript(SCHEMA)
            _migrate(conn)
            conn.commit()
        except Exception:
            conn.close()
            raise
        return conn

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def add_message(self, session_id: str, role: str, text: str, engine: str | None = None) -> int:
        engine = str(engine)[:32] if engine else None
        return self._exec(
            "INSERT INTO messages(session_id, role, text, ts, engine) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, text, time.time(), engine),
        ).lastrowid

    def messages(self, session_id: str, after_id: int = 0) -> list[dict]:
        return self._all(
            f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE session_id = ? AND id > ? ORDER BY id",
            (session_id, after_id),
        )

    def last_message(self, session_id: str, role: str) -> dict | None:
        rows = self._all(
            f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE session_id = ? AND role = ? "
            "ORDER BY id DESC LIMIT 1",
            (session_id, role),
        )
        return rows[0] if rows else None

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

    def add_broadcast(self, text: str) -> int:
        return self._exec(
            "INSERT INTO broadcasts(text, ts) VALUES (?, ?)", (text, time.time())
        ).lastrowid

    def broadcasts(self, after_id: int = 0) -> list[dict]:
        return self._all(
            "SELECT id, text, ts FROM broadcasts WHERE id > ? ORDER BY id", (after_id,)
        )

    def touch(self, session_id: str, **fields) -> None:
        fields["last_seen"] = time.time()
        self.upsert_incident(session_id, **fields)

    def health(self) -> dict:
        with self._lock:
            stats = _stats(self._conn)
        stats.update(size_bytes=_size(self.path), memory=self.path == ":memory:")
        return stats


def inspect(path: str) -> dict | None:
    if path == ":memory:" or not os.path.isfile(path):
        return None
    uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        stats = _stats(conn)
    finally:
        conn.close()
    stats.update(size_bytes=_size(path), memory=False)
    return stats


def _stats(conn: sqlite3.Connection) -> dict:
    check = conn.execute("PRAGMA quick_check").fetchone()[0]
    incidents = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM incidents WHERE status != 'resolved'").fetchone()[0]
    return {"quick_check": str(check), "incidents": incidents, "messages": messages, "active": active}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, kind in MIGRATIONS:
        if column in _columns(conn, table):
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            log.info("миграция базы: %s.%s добавлена", table, column)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise


def _quarantine(path: str) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm", "-journal"):
        src = path + suffix
        if os.path.exists(src):
            try:
                os.replace(src, f"{path}.corrupt-{stamp}{suffix}")
            except OSError as exc:
                log.error("не удалось отложить %s: %s", src, exc)


def _size(path: str) -> int | None:
    if path == ":memory:":
        return None
    try:
        return sum(os.path.getsize(path + s) for s in ("", "-wal") if os.path.exists(path + s))
    except OSError:
        return None


def _decode(row: dict) -> dict:
    row["tags"] = _loads(row.get("tags"), [])
    row["device_info"] = _loads(row.get("device_info"), {})
    row["panic"] = bool(row["panic"])
    row["charging"] = None if row["charging"] is None else bool(row["charging"])
    return row


def _loads(raw, default):
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default
