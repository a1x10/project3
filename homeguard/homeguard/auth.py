"""Пользователи и сессии. Вход — только через Telegram-бота:

1. Панель (или приложение) просит nonce и открывает ссылку t.me/<бот>?start=<nonce>.
2. Человек жмёт «Start» — бот получает nonce и его Telegram-ID.
3. Первый вошедший становится владельцем. Остальных владелец подтверждает кнопкой в боте.
4. Панель опрашивает статус и получает токен сессии (один раз).
"""
import hashlib
import secrets
import time

from . import config, db

LOGIN_TTL = 600


class AuthError(Exception):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def owner() -> dict | None:
    rows = db.query("SELECT * FROM users WHERE role = 'owner' LIMIT 1")
    return rows[0] if rows else None


def get_user(tg_id: int) -> dict | None:
    rows = db.query("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
    return rows[0] if rows else None


def list_users() -> list[dict]:
    return db.query("SELECT tg_id, name, username, role, created FROM users ORDER BY created")


def set_role(tg_id: int, role: str) -> None:
    if role not in ("member", "pending"):
        raise AuthError("Недопустимая роль")
    u = get_user(tg_id)
    if not u or u["role"] == "owner":
        raise AuthError("Нельзя изменить этого пользователя")
    db.execute("UPDATE users SET role = ? WHERE tg_id = ?", (role, tg_id))
    if role == "pending":
        db.execute("DELETE FROM sessions WHERE tg_id = ?", (tg_id,))


def remove_user(tg_id: int) -> None:
    u = get_user(tg_id)
    if not u or u["role"] == "owner":
        raise AuthError("Нельзя удалить владельца")
    db.execute("DELETE FROM sessions WHERE tg_id = ?", (tg_id,))
    db.execute("DELETE FROM users WHERE tg_id = ?", (tg_id,))


# ---- вход ----

def start_login(kind: str = "web") -> str:
    if kind not in ("web", "app"):
        raise AuthError("Неизвестный тип входа")
    db.execute("DELETE FROM login_requests WHERE created < ?", (time.time() - LOGIN_TTL,))
    nonce = secrets.token_urlsafe(18)  # символы A-Z a-z 0-9 _ - — допустимы в параметре /start
    db.execute("INSERT INTO login_requests (nonce, kind, created, status) VALUES (?,?,?,'waiting')",
               (nonce, kind, time.time()))
    return nonce


def _request(nonce: str) -> dict | None:
    rows = db.query("SELECT * FROM login_requests WHERE nonce = ? AND created > ?",
                    (nonce, time.time() - LOGIN_TTL))
    return rows[0] if rows else None


def _new_session(tg_id: int, kind: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (_hash(token), tg_id, kind, now, now))
    return token


def bot_start(nonce: str, tg_id: int, name: str, username: str | None) -> str:
    """Вызывается ботом на /start <nonce>. Возвращает: approved | pending_owner | expired | denied."""
    req = _request(nonce)
    if not req or req["status"] != "waiting":
        return "expired"
    user = get_user(tg_id)
    if user is None:
        role = "owner" if owner() is None else "pending"
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (tg_id, name[:64], username, role, time.time()))
        user = get_user(tg_id)
    else:
        db.execute("UPDATE users SET name = ?, username = ? WHERE tg_id = ?", (name[:64], username, tg_id))
    db.execute("UPDATE login_requests SET tg_id = ? WHERE nonce = ?", (tg_id, nonce))
    if user["role"] in ("owner", "member"):
        approve(nonce)
        return "approved"
    db.execute("UPDATE login_requests SET status = 'pending_owner' WHERE nonce = ?", (nonce,))
    return "pending_owner"


def approve(nonce: str) -> None:
    req = _request(nonce)
    if not req or req["tg_id"] is None or req["status"] not in ("waiting", "pending_owner"):
        raise AuthError("Запрос на вход устарел")
    if get_user(req["tg_id"])["role"] == "pending":
        db.execute("UPDATE users SET role = 'member' WHERE tg_id = ?", (req["tg_id"],))
    token = _new_session(req["tg_id"], req["kind"])
    db.execute("UPDATE login_requests SET status = 'approved', token = ? WHERE nonce = ?", (token, nonce))


def deny(nonce: str) -> None:
    db.execute("UPDATE login_requests SET status = 'denied' WHERE nonce = ?", (nonce,))


def poll(nonce: str) -> tuple[str, str | None]:
    """(статус, токен). Токен отдаётся один раз."""
    req = _request(nonce)
    if not req:
        return "expired", None
    if req["status"] == "approved":
        db.execute("UPDATE login_requests SET status = 'taken', token = NULL WHERE nonce = ?", (nonce,))
        return "approved", req["token"]
    return req["status"], None


# ---- сессии ----

def user_by_token(token: str | None) -> dict | None:
    if not token:
        return None
    rows = db.query("SELECT s.tg_id, s.kind, s.created, u.name, u.username, u.role FROM sessions s "
                    "JOIN users u ON u.tg_id = s.tg_id WHERE s.token_hash = ?", (_hash(token),))
    if not rows:
        return None
    s = rows[0]
    if s["role"] == "pending" or time.time() - s["created"] > config.SESSION_DAYS * 86400:
        return None
    db.execute("UPDATE sessions SET last_used = ? WHERE token_hash = ?", (time.time(), _hash(token)))
    return {"tg_id": s["tg_id"], "name": s["name"], "username": s["username"], "role": s["role"], "kind": s["kind"]}


def logout(token: str) -> None:
    db.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))
