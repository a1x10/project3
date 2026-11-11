"""Откуда пришел запрос и кто его прислал: вход администратора, cookie, защита от подделки запросов.

Каналы:
  cli     команда stella на самой плате (напрямую на 127.0.0.1:8000, без nginx);
  field   телефон в сети SOS;
  lan     кабель, USB или домашняя сеть (частные адреса);
  remote  все остальное: интернет через туннель и любые непонятные запросы.
nginx на каждом входе ставит X-Stella-Via, поэтому подделать «field» из интернета нельзя:
туннель всегда приходит с Via=tunnel.
"""
import hashlib
import hmac
import ipaddress
import logging
import secrets
import time
from collections import OrderedDict
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from . import config

log = logging.getLogger("stella.access")

CLI, FIELD, LAN, REMOTE = "cli", "field", "lan", "remote"
COOKIE = "stella_admin"
LOOPBACK_PEERS = {"127.0.0.1", "::1", "testclient"}
TLS_IP = "10.42.0.2"
MIN_ITERATIONS, MAX_ITERATIONS = 10_000, 2_000_000

_ephemeral_secret = secrets.token_hex(32)
if not config.SESSION_SECRET:
    log.warning("STELLA_SESSION_SECRET не задан: входы на сайт настроек сбросятся при перезапуске")


class Limiter:
    """Счетчик неудачных попыток с ограниченной памятью: старые ключи вытесняются."""

    def __init__(self, limit: int, window: float, max_keys: int = 2048):
        self.limit, self.window, self.max_keys = limit, window, max_keys
        self._hits: OrderedDict[str, list[float]] = OrderedDict()

    def _recent(self, key: str, now: float) -> list[float]:
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        if hits:
            self._hits[key] = hits
            self._hits.move_to_end(key)
        else:
            self._hits.pop(key, None)
        return hits

    def blocked(self, key: str, now: float | None = None) -> bool:
        return len(self._recent(key, now or time.time())) >= self.limit

    def fail(self, key: str, now: float | None = None) -> None:
        now = now or time.time()
        self._hits[key] = self._recent(key, now) + [now]
        self._hits.move_to_end(key)
        while len(self._hits) > self.max_keys:
            self._hits.popitem(last=False)

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)


login_failures = Limiter(5, 900)
remote_login_failures = Limiter(30, 900, max_keys=1)


def _sos_network():
    try:
        return ipaddress.ip_network(f"{config.PORTAL_HOST}/24", strict=False)
    except ValueError:
        return ipaddress.ip_network("10.42.0.0/24")


def client_ip(request: Request) -> str | None:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


def channel(request: Request) -> str:
    via = request.headers.get("x-stella-via")
    peer = request.client.host if request.client else ""
    if via is None:
        if request.headers.get("x-real-ip") is None and peer in LOOPBACK_PEERS:
            return CLI
        return REMOTE
    if via not in ("portal", "portal-tls"):
        return REMOTE
    try:
        ip = ipaddress.ip_address(request.headers.get("x-real-ip", "").strip())
    except ValueError:
        return REMOTE
    if ip in _sos_network() or str(ip) == TLS_IP:
        return FIELD
    if ip.is_private or ip.is_link_local or ip.is_loopback:
        return LAN
    return REMOTE


def is_https(request: Request) -> bool:
    return (request.headers.get("x-stella-via") in ("tunnel", "portal-tls")
            and request.headers.get("x-forwarded-proto") == "https")


def login_policy(request: Request) -> tuple[bool, str]:
    ch = channel(request)
    if is_https(request) or ch in (CLI, LAN):
        return True, ""
    if ch == FIELD and config.ADMIN_HTTP_WIFI:
        return True, ""
    if ch == FIELD:
        where = f"https://{config.BOX_DOMAIN}/admin" if config.BOX_DOMAIN else "по HTTPS через домен коробки"
        return False, ("Сеть SOS открытая, пароль в ней могут подслушать. Войдите " + where +
                       ", по кабелю или USB, либо разрешите вход командой на плате: sudo stella admin wifi on")
    return False, "Из интернета вход только по HTTPS"


def _parse_hash(stored: str) -> tuple[int, bytes, bytes] | None:
    parts = stored.split(":")
    if len(parts) != 4 or parts[0] != "pbkdf2":
        return None
    try:
        iterations = int(parts[1])
        salt, digest = bytes.fromhex(parts[2]), bytes.fromhex(parts[3])
    except ValueError:
        return None
    if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS or len(salt) < 8 or len(digest) != 32:
        return None
    return iterations, salt, digest


def password_configured() -> bool:
    return _parse_hash(config.ADMIN_HASH) is not None


def verify_password(password: str) -> bool:
    parsed = _parse_hash(config.ADMIN_HASH)
    if not parsed or not isinstance(password, str):
        return False
    iterations, salt, digest = parsed
    given = hashlib.pbkdf2_hmac("sha256", password.strip().lower().encode("utf-8"), salt, iterations)
    return hmac.compare_digest(given, digest)


def _key() -> bytes:
    # Смена пароля сразу делает недействительными все выданные cookie
    return hashlib.sha256(((config.SESSION_SECRET or _ephemeral_secret) + "|" + config.ADMIN_HASH).encode()).digest()


def _sign(text: str) -> str:
    return hmac.new(_key(), text.encode(), hashlib.sha256).hexdigest()


def issue_cookie(request: Request, now: float | None = None) -> tuple[str, int, str]:
    ttl = int(config.ADMIN_SESSION_HOURS * 3600)
    exp = int((now or time.time()) + ttl)
    scope = "s" if is_https(request) else "h"
    nonce = secrets.token_hex(12)
    body = f"v1.{exp}.{scope}.{nonce}"
    return f"{body}.{_sign(body)}", ttl, csrf_token({"nonce": nonce})


def read_session(request: Request, now: float | None = None) -> dict | None:
    raw = request.cookies.get(COOKIE, "")
    parts = raw.split(".")
    if len(parts) != 5 or parts[0] != "v1" or not password_configured():
        return None
    body = ".".join(parts[:4])
    if not hmac.compare_digest(_sign(body), parts[4]):
        return None
    try:
        exp = int(parts[1])
    except ValueError:
        return None
    if exp < (now or time.time()):
        return None
    if parts[2] != ("s" if is_https(request) else "h"):
        return None  # cookie с простого HTTP не годится для HTTPS и наоборот
    return {"exp": exp, "scope": parts[2], "nonce": parts[3]}


def csrf_token(session: dict) -> str:
    return _sign("csrf|" + session["nonce"])[:40]


def _same_origin(request: Request) -> bool:
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        return False
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return True
    try:
        netloc = urlsplit(origin).netloc.lower()
    except ValueError:
        return False
    return bool(netloc) and netloc == (request.headers.get("host") or "").lower()


def check_origin(request: Request) -> None:
    if not _same_origin(request):
        raise HTTPException(403, "Запрос пришел с чужого сайта")


def _need_login() -> HTTPException:
    return HTTPException(401, {"error": "Нужен вход администратора", "admin": True})


def require_admin(request: Request) -> dict:
    session = read_session(request)
    if not session:
        raise _need_login()
    return session


def require_admin_write(request: Request) -> dict:
    session = require_admin(request)
    check_origin(request)
    token = request.headers.get("x-stella-csrf", "")
    if not hmac.compare_digest(token.encode(), csrf_token(session).encode()):
        raise HTTPException(403, "Устаревшая страница: обновите ее и повторите")
    return session


def check_rescuer(request: Request, pin: str, expected: str, failures: Limiter) -> None:
    """Консоль спасателя: из интернета сначала вход администратора, потом PIN."""
    ch = channel(request)
    # в тестовой версии на сервере вызовы учебные, жюри входит в консоль сразу по PIN
    if ch == REMOTE and not config.DEMO and not read_session(request):
        raise HTTPException(403, {"error": "Из интернета консоль открывается после входа администратора",
                                  "admin": True})
    key = f"{ch}:{client_ip(request) or '?'}"
    if failures.blocked(key):
        raise HTTPException(429, "Слишком много попыток, подождите 5 минут")
    if not hmac.compare_digest(pin.encode(), expected.encode()):
        failures.fail(key)
        raise HTTPException(401, "Неверный PIN")
    failures.clear(key)
