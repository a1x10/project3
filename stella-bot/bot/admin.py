"""Панель управления: API под /admin/api.

Защита:
- вход только по двум паролям из .env (PANEL_PASSWORD_1 и PANEL_PASSWORD_2); в коде и в репозитории их нет;
  пока хоть один не задан — панель выключена;
- оба пароля проверяются одним запросом и никогда не сообщается, какой из них неверный,
  поэтому подбирать их по отдельности нельзя;
- защита от подбора: после 5 ошибок с одного адреса — блок на 15 минут (и каждый следующий вдвое дольше),
  после 20 ошибок за час со всех адресов — вход закрыт для всех на час; каждая попытка занимает ~1 секунду;
- о каждом входе и о блокировках владелец получает сообщение в WhatsApp;
- сессия — случайный токен (256 бит), хранится только в памяти сервера в виде хэша,
  живёт PANEL_SESSION_HOURS и обрывается после PANEL_IDLE_MINUTES без действий;
- запросы только с разрешённых сайтов (PANEL_ORIGINS), токен — в заголовке, без cookies.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import Settings
from .db import OWNER_SENDER, Person, chat_paused
from .plans import get_plan, set_plan, used_today
from .util import mask_phone, phone_of, utcnow

if TYPE_CHECKING:
    from .brain import Brain

log = logging.getLogger("stella.admin")

IP_MAX_FAILS = 5
IP_WINDOW = 15 * 60
IP_LOCK = 15 * 60
IP_LOCK_MAX = 24 * 3600
GLOBAL_MAX_FAILS = 20
GLOBAL_WINDOW = 3600
GLOBAL_LOCK = 3600
LOGIN_DELAY = 0.8  # каждая попытка входа — не быстрее
MAX_SESSIONS = 10


@dataclass
class Session:
    created: float
    last_seen: float
    ip: str


class LoginLocked(Exception):
    def __init__(self, retry_after: float, scope: str):
        super().__init__(scope)
        self.retry_after = int(retry_after) + 1
        self.scope = scope


class AdminAuth:
    def __init__(self, settings: Settings, clock: Callable[[], float] = time.time):
        self.s = settings
        self.clock = clock  # обычное время (не monotonic): блокировки сохраняются и переживают перезапуск
        # попытки входа идут строго по одной: иначе пачка параллельных запросов успела бы проскочить
        # проверку блокировки, пока каждая «ждёт свою секунду»
        self.login_lock = asyncio.Lock()
        self.sessions: dict[str, Session] = {}  # sha256(token) -> сессия
        self._fails: dict[str, deque[float]] = {}
        self._locks: dict[str, float] = {}  # ip -> до какого момента заблокирован
        self._lock_count: dict[str, int] = {}
        self._global_fails: deque[float] = deque()
        self._global_lock_until = 0.0

    def enabled(self) -> bool:
        return bool(self.s.panel_password_1 and self.s.panel_password_2)

    def weak(self) -> bool:
        """Короткие или только из цифр — подбираются легко (держится на блокировках)."""
        pw = self.s.panel_password_1 + self.s.panel_password_2
        return len(pw) < 16 or pw.isdigit()

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def locked(self, ip: str, local: bool = False) -> LoginLocked | None:
        """local — вход с самого сервера (SSH-туннель): общий замок на него не действует, иначе
        любой знающий адрес туннеля мог бы навсегда запереть владельца."""
        now = self.clock()
        if now < self._global_lock_until and not local:
            return LoginLocked(self._global_lock_until - now, "global")
        until = self._locks.get(ip, 0.0)
        if now < until:
            return LoginLocked(until - now, "ip")
        return None

    def check_passwords(self, p1: str, p2: str) -> bool:
        # оба сравнения выполняются всегда и за одинаковое время (хэши одной длины — длина пароля не видна)
        ok1 = hmac.compare_digest(self._hash(p1), self._hash(self.s.panel_password_1))
        ok2 = hmac.compare_digest(self._hash(p2), self._hash(self.s.panel_password_2))
        return ok1 and ok2

    def register_failure(self, ip: str) -> str | None:
        """Возвращает 'ip' / 'global', если из-за этой ошибки включилась блокировка."""
        now = self.clock()
        self._prune(now)
        q = self._fails.setdefault(ip, deque())
        q.append(now)
        while q and now - q[0] > IP_WINDOW:
            q.popleft()
        self._global_fails.append(now)
        while self._global_fails and now - self._global_fails[0] > GLOBAL_WINDOW:
            self._global_fails.popleft()
        if len(self._global_fails) >= GLOBAL_MAX_FAILS:
            self._global_lock_until = now + GLOBAL_LOCK
            self._global_fails.clear()
            return "global"
        if len(q) >= IP_MAX_FAILS:
            n = self._lock_count.get(ip, 0) + 1
            self._lock_count[ip] = n
            self._locks[ip] = now + min(IP_LOCK * 2 ** (n - 1), IP_LOCK_MAX)
            q.clear()
            return "ip"
        return None

    def _prune(self, now: float) -> None:
        """Не копим память на каждый адрес, с которого когда-то ошиблись."""
        if len(self._fails) + len(self._locks) < 2000:
            return
        for ip in list(self._fails):
            q = self._fails[ip]
            if not q or now - q[-1] > IP_WINDOW:
                del self._fails[ip]
        for ip in list(self._locks):
            if self._locks[ip] < now - IP_LOCK_MAX:
                self._locks.pop(ip, None)
                self._lock_count.pop(ip, None)

    def reset_locks(self) -> None:
        """Снять все блокировки входа (команда владельца «стелла разблокируй панель»)."""
        self._fails.clear()
        self._locks.clear()
        self._lock_count.clear()
        self._global_fails.clear()
        self._global_lock_until = 0.0

    def export_locks(self) -> dict[str, Any]:
        now = self.clock()
        return {"global_until": self._global_lock_until if self._global_lock_until > now else 0,
                "ip": {ip: [until, self._lock_count.get(ip, 1)] for ip, until in self._locks.items() if until > now}}

    def import_locks(self, data: dict[str, Any]) -> None:
        try:
            self._global_lock_until = float(data.get("global_until") or 0)
            for ip, (until, count) in (data.get("ip") or {}).items():
                self._locks[str(ip)] = float(until)
                self._lock_count[str(ip)] = int(count)
        except (TypeError, ValueError, AttributeError):
            pass

    def new_session(self, ip: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        self._fails.pop(ip, None)
        if len(self.sessions) >= MAX_SESSIONS:
            oldest = min(self.sessions, key=lambda k: self.sessions[k].last_seen)
            self.sessions.pop(oldest)
        self.sessions[self._hash(token)] = Session(created=now, last_seen=now, ip=ip)
        return token

    def verify(self, token: str) -> Session | None:
        if not token:
            return None
        key = self._hash(token)
        sess = self.sessions.get(key)
        if sess is None:
            return None
        now = self.clock()
        if (now - sess.created > self.s.panel_session_hours * 3600
                or now - sess.last_seen > self.s.panel_idle_minutes * 60):
            self.sessions.pop(key, None)
            return None
        sess.last_seen = now
        return sess

    def logout(self, token: str) -> None:
        self.sessions.pop(self._hash(token), None)

    def logout_all(self) -> None:
        self.sessions.clear()


# ---------- журнал для панели ----------
class RingLog(logging.Handler):
    """Последние строки лога бота — для вкладки «Журнал»."""

    def __init__(self, size: int = 500):
        super().__init__(level=logging.INFO)
        self.lines: deque[dict[str, str]] = deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
        except Exception:
            text = str(record.msg)
        at = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        self.lines.append({"at": at, "level": record.levelname, "text": f"{record.name}: {text}"[:1000]})


RING = RingLog()


def install_ring_log() -> None:
    logger = logging.getLogger("stella")
    if RING not in logger.handlers:
        logger.addHandler(RING)


# ---------- настройки, которые можно менять из панели ----------
MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
EDITABLE: list[dict[str, Any]] = [
    {"key": "llm_model", "label": "Модель", "type": "select", "options": MODELS,
     "hint": "Opus — самая умная (дороже Sonnet в 2 раза), Haiku — самая дешёвая"},
    {"key": "llm_effort", "label": "Сколько думать перед ответом", "type": "select",
     "options": ["low", "medium", "high"], "hint": "low — быстро и коротко; high — дольше и дороже"},
    {"key": "llm_model_after", "label": "Модель после окончания бонусных кредитов", "type": "select",
     "options": MODELS, "hint": "работает за твои деньги на API — Opus быстро съест баланс"},
    {"key": "daily_budget_usd", "label": "Лимит расходов в день, $", "type": "number", "min": 0, "max": 200,
     "hint": "после лимита отвечает только на прямые обращения"},
    {"key": "llm_web_search", "label": "Поиск в интернете", "type": "bool"},
    {"key": "media_enabled", "label": "Стикеры, картинки, документы, презентации, видео", "type": "bool"},
    {"key": "media_per_day", "label": "Файлов в один чат за день", "type": "number", "min": 0, "max": 500},
    {"key": "vision_enabled", "label": "Видит фото и стикеры", "type": "bool"},
    {"key": "video_dl_enabled", "label": "Скачивает видео по ссылкам TikTok и YouTube", "type": "bool"},
    {"key": "video_dl_per_day", "label": "Скачанных видео в один чат за день", "type": "number", "min": 0, "max": 500},
    {"key": "documents_enabled", "label": "Читает присланные файлы (PDF, Word, Excel…)", "type": "bool"},
    {"key": "voice_enabled", "label": "Голосовые: понимает и может ответить голосом", "type": "bool"},
    {"key": "voice_stt_model", "label": "Распознавание голоса", "type": "select", "options": ["base", "small"],
     "hint": "base — легче (~0.3 ГБ памяти), small — точнее (~0.6 ГБ)"},
    {"key": "sandbox_enabled", "label": "Запуск кода по твоей просьбе (песочница Anthropic)", "type": "bool",
     "hint": "только для владельца (OWNER_PHONE); код выполняется не на сервере"},
    {"key": "chime_default", "label": "Как часто сама встревает в разговор", "type": "select",
     "options": ["off", "rare", "normal", "chatty"], "hint": "для чатов, где режим не задан отдельно"},
    {"key": "initiative_per_week", "label": "Сама пишет в группу, раз в неделю", "type": "number",
     "min": 0, "max": 14},
    {"key": "allow_dms", "label": "Отвечать в личке", "type": "bool"},
    {"key": "prompt_style", "label": "Стиль", "type": "select", "options": ["minimal", "full"],
     "hint": "minimal — просто общается как человек; full — подробный характер (настроения, обиды)"},
    {"key": "max_bubbles", "label": "Максимум сообщений в одном ответе", "type": "number", "min": 1, "max": 10},
    {"key": "reply_each_max", "label": "Скольким людям отвечать по отдельности за раз", "type": "number",
     "min": 1, "max": 10},
    {"key": "owner_takeover_minutes", "label": "Молчать, когда ты пишешь сам с её телефона, мин",
     "type": "number", "min": 0, "max": 1440},
    {"key": "free_replies_per_day", "label": "Подписки: бесплатных ответов человеку в день", "type": "number",
     "min": 0, "max": 10000, "hint": "0 — без лимита. Подписку или свой лимит человеку выдаёшь во вкладке «Люди»; "
     "тебе и админам — всегда без лимита"},
    {"key": "limit_message", "label": "Подписки: что писать, когда лимит кончился", "type": "text", "max_len": 600,
     "hint": "{support} — подставится контакт техподдержки, {limit} — сколько сообщений было можно"},
    {"key": "support_contact", "label": "Подписки: контакт техподдержки", "type": "text", "max_len": 200,
     "hint": "@username, ссылка или номер — его Стелла даст тем, у кого кончился лимит"},
]
EDITABLE_KEYS = {e["key"]: e for e in EDITABLE}
OVERRIDES_KV = "settings_override"


def coerce(desc: dict[str, Any], value: Any) -> Any:
    kind = desc["type"]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError("нужно да/нет")
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("нужно число")
        if not (desc.get("min", float("-inf")) <= value <= desc.get("max", float("inf"))):
            raise ValueError(f"от {desc.get('min')} до {desc.get('max')}")
        return value
    if kind == "select":
        if value not in desc["options"]:
            raise ValueError("нет такого варианта")
        return value
    return str(value)[:desc.get("max_len", 200)]


async def load_overrides(brain: "Brain") -> dict[str, Any]:
    row = await brain.db.kv_get(OVERRIDES_KV)
    try:
        data = json.loads(row[0]) if row and row[0] else {}
    except ValueError:
        data = {}
    applied = {}
    for key, value in (data or {}).items():
        desc = EDITABLE_KEYS.get(key)
        if not desc:
            continue
        try:
            value = coerce(desc, value)
        except ValueError:
            continue
        cur = getattr(brain.s, key)
        setattr(brain.s, key, int(value) if isinstance(cur, int) and not isinstance(cur, bool) else value)
        applied[key] = value
    if applied:
        brain.on_settings_changed()
    return applied


def describe(s: Settings) -> list[dict[str, Any]]:
    out = []
    for e in EDITABLE:
        out.append({"key": e["key"], "label": e["label"], "type": e["type"], "options": e.get("options"),
                    "value": getattr(s, e["key"]), "min": e.get("min"), "max": e.get("max"), "hint": e.get("hint")})
    return out


# ---------- API ----------
class LoginBody(BaseModel):
    p1: str = Field(max_length=128)
    p2: str = Field(max_length=128)


class TextBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class PauseBody(BaseModel):
    minutes: int = Field(ge=1, le=7 * 24 * 60)


class ChimeBody(BaseModel):
    level: str = Field(pattern="^(off|rare|normal|chatty)$")


class AboutBody(BaseModel):
    about: str = Field(max_length=4000)


class ProfileBody(BaseModel):
    fields: dict[str, str]


class PlanBody(BaseModel):
    kind: str = Field(pattern="^(free|unlimited|limit)$")  # бесплатно / подписка без лимита / свой лимит
    days: int = Field(default=0, ge=0, le=3650)  # 0 — навсегда
    limit: int = Field(default=0, ge=0, le=10000)  # ответов в сутки (для kind=limit)


async def plan_info(brain: "Brain", p: Person) -> dict[str, Any]:
    """Подписка человека для панели: что выдано, до когда, сколько можно и сколько уже сегодня."""
    plan = await get_plan(brain.db, p.id, expired=True)
    until = plan.get("until") if plan else None
    ended = bool(until and time.time() >= float(until))
    return {"kind": plan["kind"] if plan and not ended else "free", "until": until,
            "ended": ended, "limit": plan.get("limit") if plan else None,
            "daily": await brain.reply_limit(p), "used_today": await used_today(brain.db, p.id),
            "admin": brain.s.is_admin(phone_of(p.jid) or p.phone)}


LOCKS_KV = "panel_locks"


def is_local_request(request: Request) -> bool:
    """Запрос с самого сервера (docker-сеть / localhost / SSH-туннель), а не через Cloudflare или nginx."""
    if request.headers.get("cf-connecting-ip") or request.headers.get("x-real-ip") \
            or request.headers.get("x-forwarded-for"):
        return False
    host = request.client.host if request.client else ""
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback
    except ValueError:
        return host in ("testclient", "localhost")


def client_ip(request: Request) -> str:
    """Через Cloudflare — CF-Connecting-IP (его ставит Cloudflare), через nginx — X-Real-IP."""
    for header in ("cf-connecting-ip", "x-real-ip"):
        value = request.headers.get(header, "").strip()
        if value:
            return value[:64]
    return request.client.host if request.client else "?"


def _iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


def build_router(get_brain: Callable[[Request], "Brain"]) -> APIRouter:
    router = APIRouter(prefix="/admin/api")

    def auth_of(request: Request) -> AdminAuth:
        return get_brain(request).admin

    async def require_session(request: Request) -> str:
        auth = auth_of(request)
        if not auth.enabled():
            raise HTTPException(503, detail="disabled")
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not auth.verify(token):
            raise HTTPException(401, detail="unauthorized")
        return token

    async def chat_or_404(request: Request, chat_id: int) -> dict[str, Any]:
        brain = get_brain(request)
        chats = await brain.db.all_chats(brain.s.evolution_instance)
        chat = next((c for c in chats if c["id"] == chat_id), None)
        if chat is None:
            raise HTTPException(404, detail="нет такого чата")
        return chat

    @router.post("/login")
    async def login(body: LoginBody, request: Request) -> JSONResponse:
        brain = get_brain(request)
        auth = brain.admin
        if not auth.enabled():
            return JSONResponse({"error": "disabled"}, status_code=503)
        ip = client_ip(request)
        local = is_local_request(request)
        async with auth.login_lock:  # по одной попытке за раз — параллельными запросами замок не обойти
            lock = auth.locked(ip, local)
            if lock:
                return JSONResponse({"error": "locked", "retry_after": lock.retry_after}, status_code=429,
                                    headers={"Retry-After": str(lock.retry_after)})
            await asyncio.sleep(LOGIN_DELAY)
            ok = auth.check_passwords(body.p1.strip(), body.p2.strip())
            locked = None if ok else auth.register_failure(ip)
        if ok:
            token = auth.new_session(ip)
            log.warning("вход в панель (%s)", ip)
            # о каждом входе — отдельно (без «не чаще раза в 10 минут»), при обрыве WhatsApp — позже
            brain.spawn(brain.tell_owner(f"🔐 Вход в панель Стеллы (адрес {ip}). Если это не ты — смени "
                                         "PANEL_PASSWORD_1/2 в .env и перезапусти бота: все входы сбросятся."))
            return JSONResponse({"token": token, "expires_in": int(brain.s.panel_session_hours * 3600)})
        log.warning("неверный вход в панель (%s)%s", ip, f", блокировка: {locked}" if locked else "")
        if locked:
            await brain.db.kv_set(LOCKS_KV, json.dumps(auth.export_locks()))
            what = "для всех на час" if locked == "global" else f"для адреса {ip}"
            brain.spawn(brain.tell_owner(f"⚠️ Кто-то подбирает пароли к панели Стеллы — вход заблокирован {what}. "
                                         "Снять блокировку: напиши Стелле «стелла разблокируй панель»."))
        return JSONResponse({"error": "wrong"}, status_code=401)

    @router.post("/logout")
    async def logout(request: Request, token: str = Depends(require_session)) -> dict[str, Any]:
        auth_of(request).logout(token)
        return {"ok": True}

    @router.post("/logout_all")
    async def logout_all(request: Request, token: str = Depends(require_session)) -> dict[str, Any]:
        auth_of(request).logout_all()
        return {"ok": True}

    @router.get("/status")
    async def status(request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        s = brain.s
        kind, model = s.backend_for(date.today())
        chats = await brain.db.all_chats(s.evolution_instance)
        return {
            "whatsapp": brain.connection_state,
            "llm_backend": kind,
            "llm_model": model,
            "llm_effort": s.llm_effort,
            "spend_today_usd": round(await brain.refresh_spend(), 4),
            "daily_budget_usd": s.daily_budget_usd,
            "over_budget": brain.over_budget(),
            "chats": len(chats),
            "groups": sum(1 for c in chats if c["is_group"]),
            "dms": sum(1 for c in chats if not c["is_group"]),
            "own_lid_known": any(j.endswith("@lid") for j in brain.bot.jids),
            "weak_passwords": auth_of(request).weak(),
            "tunnel_url": brain.tunnel_url,
            "uptime_s": int(time.monotonic() - brain.started_at),
            "switch_at": s.llm_switch_at.isoformat() if s.llm_switch_at else None,
        }

    @router.get("/chats")
    async def chats(request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        out = []
        for c in await brain.db.all_chats(brain.s.evolution_instance):
            paused = chat_paused(c)
            out.append({
                "id": c["id"],
                "title": c.get("title") or ("группа" if c["is_group"] else f"личка {mask_phone(c['jid'])}"),
                "is_group": bool(c["is_group"]),
                "jid_masked": mask_phone(c["jid"]),
                "paused_until": _iso(c["paused_until"]) if paused else None,
                "paused_by_owner": paused and await brain._owner_takeover_active(c),
                "chime_level": c.get("chime_level"),
                "last_bot_at": _iso(c.get("last_bot_at")),
                "last_message_at": _iso(await brain.db.last_message_at(c["id"])),
                "members": await brain.db.count_members(c["id"]),
                "grudges": len(await brain.db.active_grudges(c["id"])),
            })
        out.sort(key=lambda x: (not x["is_group"], -(datetime.fromisoformat(x["last_message_at"]).timestamp()
                                                     if x["last_message_at"] else 0)))
        return {"chats": out}

    @router.get("/chats/{chat_id}/messages")
    async def messages(chat_id: int, request: Request, limit: int = 60,
                       _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        await chat_or_404(request, chat_id)
        rows = await brain.db.recent_messages(chat_id, max(1, min(limit, 300)))
        out = []
        for r in rows:
            if r["role"] == "assistant":
                sender = "ты (с её телефона)" if r.get("sender_name") == OWNER_SENDER else brain.s.bot_name
            else:
                sender = r.get("sender_name") or "кто-то"
            out.append({"id": r["id"], "role": r["role"], "sender": sender, "text": r.get("text") or "",
                        "kind": r.get("kind") or "text", "at": _iso(r.get("created_at"))})
        return {"messages": out}

    @router.post("/chats/{chat_id}/send")
    async def send(chat_id: int, body: TextBody, request: Request,
                   _: str = Depends(require_session)) -> dict[str, Any]:
        from .casino import CasinoResult

        brain = get_brain(request)
        chat = await chat_or_404(request, chat_id)
        lines = [ln.strip() for ln in body.text.split("\n") if ln.strip()]
        if len(lines) > 10:  # не больше 10 сообщений подряд — остальное одним сообщением
            lines = lines[:9] + ["\n".join(lines[9:])]
        # «печатает…» занимает время — отправляем в фоне, панель не ждёт
        brain.spawn(brain.outbox.send_result(chat, CasinoResult(lines)))
        log.info("панель: отправляется от Стеллы в %s", mask_phone(chat["jid"]))
        return {"ok": True, "queued": True}

    @router.post("/chats/{chat_id}/pause")
    async def pause(chat_id: int, body: PauseBody, request: Request,
                    _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        await chat_or_404(request, chat_id)
        until = utcnow() + timedelta(minutes=body.minutes)
        await brain.db.update_chat(chat_id, paused_until=until)
        await brain.db.kv_set(f"takeover:{chat_id}", "")
        return {"ok": True, "paused_until": _iso(until)}

    @router.post("/chats/{chat_id}/unpause")
    async def unpause(chat_id: int, request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        await chat_or_404(request, chat_id)
        await brain.db.update_chat(chat_id, paused_until=None)
        return {"ok": True}

    @router.post("/chats/{chat_id}/chime")
    async def chime(chat_id: int, body: ChimeBody, request: Request,
                    _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        await chat_or_404(request, chat_id)
        await brain.db.update_chat(chat_id, chime_level=body.level)
        return {"ok": True}

    @router.post("/chats/{chat_id}/poke")
    async def poke(chat_id: int, request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        chat = await chat_or_404(request, chat_id)
        if chat_paused(chat):
            return {"ok": True, "sent": False, "queued": False}
        brain.spawn(brain.initiate(chat["jid"]))  # модель думает до пары минут — в фоне
        return {"ok": True, "sent": None, "queued": True}

    @router.get("/chats/{chat_id}/about")
    async def about(chat_id: int, request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
        chat = await chat_or_404(request, chat_id)
        return {"about": chat.get("about") or "", "notes": chat.get("notes") or ""}

    @router.put("/chats/{chat_id}/about")
    async def set_about(chat_id: int, body: AboutBody, request: Request,
                        _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        await chat_or_404(request, chat_id)
        await brain.db.update_chat(chat_id, about=body.about.strip() or None)
        return {"ok": True}

    @router.get("/chats/{chat_id}/people")
    async def people(chat_id: int, request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        await chat_or_404(request, chat_id)
        out = []
        for p, msg_count in await brain.db.members_with_counts(chat_id):
            out.append({
                "id": p.id, "ref": p.ref, "name": p.name, "push_name": p.push_name, "nickname": p.nickname,
                "phone_masked": mask_phone(p.phone) if p.phone else mask_phone(p.jid),
                "msg_count": msg_count, "plan": await plan_info(brain, p),
                "profile": await brain.db.get_profile(p.id, chat_id),
                "facts": await brain.db.get_facts(p.id, chat_id, 200),
            })
        return {"people": out}

    async def member_or_404(request: Request, chat_id: int, person_id: int) -> None:
        brain = get_brain(request)
        await chat_or_404(request, chat_id)
        if person_id not in {p.id for p, _ in await brain.db.members_with_counts(chat_id)}:
            raise HTTPException(404, detail="нет такого человека в этом чате")

    @router.put("/chats/{chat_id}/people/{person_id}/plan")
    async def put_plan(chat_id: int, person_id: int, body: PlanBody, request: Request,
                       _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        await member_or_404(request, chat_id, person_id)
        person = await brain.db.get_person(person_id)
        if person is None:
            raise HTTPException(404, detail="нет такого человека")
        if body.kind == "limit" and body.limit < 1:
            raise HTTPException(400, detail="свой лимит — хотя бы 1 сообщение в день")
        await set_plan(brain.db, person_id, body.kind, days=body.days, limit=body.limit)
        brain._limit_told.pop(person_id, None)
        log.warning("панель: подписка %s — %s%s", person.ref, body.kind, f" на {body.days} дн." if body.days else "")
        return {"ok": True, "plan": await plan_info(brain, person)}

    @router.put("/chats/{chat_id}/people/{person_id}/profile")
    async def set_profile(chat_id: int, person_id: int, body: ProfileBody, request: Request,
                          _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        await member_or_404(request, chat_id, person_id)
        fields = {str(k)[:60]: str(v)[:500] for k, v in list(body.fields.items())[:30]}
        profile = await brain.db.update_profile(person_id, chat_id, fields)
        return {"ok": True, "profile": profile}

    @router.delete("/chats/{chat_id}/people/{person_id}/facts")
    async def forget(chat_id: int, person_id: int, request: Request,
                     _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        await member_or_404(request, chat_id, person_id)
        n = await brain.db.forget_facts(person_id, chat_id, None)
        return {"ok": True, "deleted": n}

    @router.get("/settings")
    async def get_settings(request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
        return {"settings": describe(get_brain(request).s)}

    @router.put("/settings")
    async def put_settings(body: dict[str, Any], request: Request,
                           _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        changes = {}
        for key, value in body.items():
            desc = EDITABLE_KEYS.get(key)
            if not desc:
                raise HTTPException(400, detail=f"эту настройку менять нельзя: {key}")
            try:
                changes[key] = coerce(desc, value)
            except ValueError as exc:
                raise HTTPException(400, detail=f"{desc['label']}: {exc}") from exc
        row = await brain.db.kv_get(OVERRIDES_KV)
        try:
            saved = json.loads(row[0]) if row and row[0] else {}
        except ValueError:
            saved = {}
        saved.update(changes)
        await brain.db.kv_set(OVERRIDES_KV, json.dumps(saved, ensure_ascii=False))
        await load_overrides(brain)
        log.warning("панель: изменены настройки %s", ", ".join(sorted(changes)))
        return {"ok": True, "settings": describe(brain.s)}

    @router.get("/log")
    async def get_log(limit: int = 200, _: str = Depends(require_session)) -> dict[str, Any]:
        lines = list(RING.lines)[-max(1, min(limit, 500)):]
        return {"lines": lines}

    @router.post("/actions/unpause_all")
    async def unpause_all(request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        return {"ok": True, "count": await brain.db.unpause_all(brain.s.evolution_instance)}

    @router.post("/actions/forgive_all")
    async def forgive_all(request: Request, _: str = Depends(require_session)) -> dict[str, Any]:
        brain = get_brain(request)
        return {"ok": True, "count": await brain.db.clear_all_grudges()}

    return router
