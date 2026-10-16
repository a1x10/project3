"""Напоминания: «стелла напомни завтра в 8 про контрольную», «каждый понедельник в 7:30 напоминай про физру».

Время в базе — UTC без часового пояса (как везде в боте). Люди и модель видят местное время (settings.timezone).
Повторы считаются по местному времени: «в 07:30» остаётся 07:30 и после перевода часов.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    and_,
    func,
    insert,
    select,
    update,
)

from .db import DB, Person, metadata
from .humanize import Segment
from .llm.base import ToolSpec
from .outbox import EVERYONE_RE
from .util import mask_phone, norm, utcnow

if TYPE_CHECKING:
    from .tools import ToolContext

log = logging.getLogger("stella.reminders")

MAX_ACTIVE_PER_CHAT = 50
MAX_TEXT = 500
MAX_AHEAD = timedelta(days=366)
SKEW = timedelta(minutes=1)  # «на сейчас» — не ошибка: часы модели и бота могут чуть расходиться
REPEAT_CATCH_UP = timedelta(days=8)  # повтор с прошедшим временем — переносим на ближайший раз
LATE_NOTE_AFTER = timedelta(minutes=10)  # опоздали (бот был офлайн) — честно говорим
GIVE_UP_AFTER = timedelta(hours=6)  # совсем старое уже не шлём

reminders = Table(
    "reminders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("chat_id", Integer, ForeignKey("chats.id"), nullable=False),
    Column("person_id", Integer),  # кого отметить; пусто — напоминание всему чату
    Column("created_by", Integer),  # кто попросил; пусто — Стелла сама
    Column("text", String(MAX_TEXT), nullable=False),
    Column("due_at", DateTime, nullable=False),  # UTC
    Column("repeat", String(16)),  # daily | weekly | weekdays | пусто — один раз
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("done", Boolean, nullable=False, default=False),
    Index("ix_reminders_due", "done", "due_at"),
)

REPEATS = ("daily", "weekly", "weekdays")
_REPEAT_ALIASES = {
    "daily": "daily", "day": "daily", "every day": "daily", "ежедневно": "daily", "каждый день": "daily",
    "weekly": "weekly", "week": "weekly", "every week": "weekly", "еженедельно": "weekly",
    "каждую неделю": "weekly",
    "weekdays": "weekdays", "weekday": "weekdays", "workdays": "weekdays", "будни": "weekdays",
    "по будням": "weekdays",
    "": None, "none": None, "no": None, "once": None, "нет": None, "один раз": None,
}
EVERY_WEEKDAY = ["каждый понедельник", "каждый вторник", "каждую среду", "каждый четверг", "каждую пятницу",
                 "каждую субботу", "каждое воскресенье"]
_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M")
_EVERYONE_WORDS = {"все", "всем", "всех", "чат", "чату", "all", "everyone"}


def _normalize_repeat(repeat: Any) -> str | None:
    key = norm(str(repeat or ""))
    if key not in _REPEAT_ALIASES:
        raise ValueError("repeat: daily (каждый день), weekly (каждую неделю) или weekdays (по будням)")
    return _REPEAT_ALIASES[key]


def _step(local: datetime, repeat: str) -> datetime:
    """Следующий раз по местному времени."""
    if repeat == "daily":
        return local + timedelta(days=1)
    if repeat == "weekly":
        return local + timedelta(days=7)
    nxt = local + timedelta(days=1)
    while nxt.weekday() >= 5:  # суббота, воскресенье
        nxt += timedelta(days=1)
    return nxt


class Reminders:
    def __init__(self, db: DB, settings: Any):
        self.db = db
        self.s = settings

    # ---------- время ----------
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.s.timezone)  # не кешируем: часовой пояс могут поменять в панели

    def to_utc(self, local: datetime) -> datetime:
        """Местное время (без пояса) -> UTC без пояса."""
        return local.replace(tzinfo=self.tz).astimezone(timezone.utc).replace(tzinfo=None)

    def to_local(self, utc: datetime) -> datetime:
        return utc.replace(tzinfo=timezone.utc).astimezone(self.tz).replace(tzinfo=None)

    def parse_local(self, value: datetime | str) -> datetime:
        """«2026-10-17 08:00» (местное) -> UTC без пояса."""
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc).replace(tzinfo=None)
            return self.to_utc(value)
        raw = re.sub(r"\s+", " ", str(value or "")).strip()
        for fmt in _FORMATS:
            try:
                return self.to_utc(datetime.strptime(raw, fmt))
            except ValueError:
                continue
        raise ValueError("время нужно в формате ГГГГ-ММ-ДД ЧЧ:ММ (местное), например 2026-10-17 08:00")

    def fmt_at(self, due_utc: datetime, now: datetime | None = None) -> str:
        """«17.10 в 08:00» (год — только если не текущий)."""
        local = self.to_local(due_utc)
        this_year = self.to_local(now or utcnow()).year
        day = f"{local:%d.%m}" if local.year == this_year else f"{local:%d.%m.%Y}"
        return f"{day} в {local:%H:%M}"

    def fmt_when(self, row: dict[str, Any], now: datetime | None = None) -> str:
        """Человеческое «когда»: «17.10 в 08:00», «каждый понедельник в 07:30 (ближайший — 19.10)»."""
        local = self.to_local(row["due_at"])
        repeat = row.get("repeat")
        if not repeat:
            return self.fmt_at(row["due_at"], now)
        every = {"daily": "каждый день", "weekdays": "по будням"}.get(repeat) or EVERY_WEEKDAY[local.weekday()]
        return f"{every} в {local:%H:%M} (ближайший — {self.fmt_at(row['due_at'], now).split(' в ')[0]})"

    # ---------- база ----------
    async def add(self, chat_id: int, person_id: int | None, created_by: int | None, text: str,
                  due_local: datetime | str, repeat: str | None = None, *, now: datetime | None = None) -> int:
        """Поставить напоминание. Ошибки (прошлое время, слишком далеко, лимит) — ValueError с понятным текстом."""
        now = now or utcnow()
        text = re.sub(r"\s+", " ", str(text or "")).strip()[:MAX_TEXT]
        if not text:
            raise ValueError("о чём напомнить? text пустой")
        due = self.parse_local(due_local)
        repeat = _normalize_repeat(repeat)
        if repeat == "weekdays":
            local = self.to_local(due)
            while local.weekday() >= 5:  # «по будням» с субботы — начинаем с понедельника
                local += timedelta(days=1)
            due = self.to_utc(local)
        if due < now - SKEW:
            if repeat and now - due <= REPEAT_CATCH_UP:
                local = self.to_local(due)
                while self.to_utc(local) <= now:  # «каждый день в 7:30», а уже 9 утра — начнём завтра
                    local = _step(local, repeat)
                due = self.to_utc(local)
            else:
                raise ValueError(f"это время уже прошло (сейчас {self.fmt_at(now, now)}) — укажи будущее")
        if due > now + MAX_AHEAD:
            raise ValueError("слишком далеко: напоминания ставлю максимум на год вперёд")
        async with self.db.engine.begin() as conn:
            same = (await conn.execute(
                select(reminders.c.id).where(
                    reminders.c.chat_id == chat_id, reminders.c.done.is_(False), reminders.c.due_at == due,
                    reminders.c.text == text,
                    reminders.c.person_id.is_(None) if person_id is None else reminders.c.person_id == person_id,
                ).limit(1)
            )).scalar()
            if same is not None:
                return same  # то же самое уже стоит (модель вызвала дважды) — не дублируем
            active = (await conn.execute(
                select(func.count()).select_from(reminders)
                .where(reminders.c.chat_id == chat_id, reminders.c.done.is_(False))
            )).scalar_one()
            if active >= MAX_ACTIVE_PER_CHAT:
                raise ValueError(f"в этом чате уже {MAX_ACTIVE_PER_CHAT} напоминаний — сначала отмени ненужные")
            res = await conn.execute(insert(reminders).values(
                chat_id=chat_id, person_id=person_id, created_by=created_by, text=text, due_at=due,
                repeat=repeat, created_at=now, done=False,
            ))
            return int(res.inserted_primary_key[0])

    async def get(self, chat_id: int, reminder_id: int) -> dict[str, Any] | None:
        async with self.db.engine.connect() as conn:
            row = (await conn.execute(
                select(reminders).where(reminders.c.id == reminder_id, reminders.c.chat_id == chat_id)
            )).mappings().first()
            return dict(row) if row else None

    async def list_active(self, chat_id: int, now: datetime | None = None) -> list[dict[str, Any]]:
        """Активные напоминания чата по порядку; at/when — уже местным временем."""
        async with self.db.engine.connect() as conn:
            rows = (await conn.execute(
                select(reminders).where(reminders.c.chat_id == chat_id, reminders.c.done.is_(False))
                .order_by(reminders.c.due_at, reminders.c.id)
            )).mappings().all()
        result = []
        for r in rows:
            item = dict(r)
            item["at"] = self.fmt_at(r["due_at"], now)
            item["local"] = f"{self.to_local(r['due_at']):%Y-%m-%d %H:%M}"
            item["when"] = self.fmt_when(item, now)
            result.append(item)
        return result

    async def cancel(self, chat_id: int, reminder_id: int) -> bool:
        async with self.db.engine.begin() as conn:
            res = await conn.execute(
                update(reminders)
                .where(reminders.c.id == reminder_id, reminders.c.chat_id == chat_id, reminders.c.done.is_(False))
                .values(done=True)
            )
            return res.rowcount > 0

    async def due(self, now_utc: datetime | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Напоминания, которым пора (самые старые первыми)."""
        now_utc = now_utc or utcnow()
        async with self.db.engine.connect() as conn:
            rows = (await conn.execute(
                select(reminders).where(reminders.c.done.is_(False), reminders.c.due_at <= now_utc)
                .order_by(reminders.c.due_at, reminders.c.id).limit(limit)
            )).mappings().all()
            return [dict(r) for r in rows]

    def next_due(self, row: dict[str, Any], now: datetime) -> datetime | None:
        """Когда сработать в следующий раз (UTC) или None, если повтора нет."""
        repeat = row.get("repeat")
        if repeat not in REPEATS:
            return None
        local = self.to_local(row["due_at"])
        for _ in range(5000):  # пропущенные разы (бот был выключен) не догоняем — сразу к будущему
            local = _step(local, repeat)
            nxt = self.to_utc(local)
            if nxt > now:
                return nxt
        return None

    async def mark_sent(self, row: dict[str, Any], now: datetime | None = None) -> datetime | None:
        """Отправлено: разовое — закрыть, повтор — перенести на следующий раз. Возвращает новое время или None."""
        now = now or utcnow()
        nxt = self.next_due(row, now)
        values: dict[str, Any] = {"due_at": nxt} if nxt else {"done": True}
        async with self.db.engine.begin() as conn:
            await conn.execute(
                update(reminders)
                .where(and_(reminders.c.id == row["id"], reminders.c.done.is_(False)))
                .values(**values)
            )
        return nxt


# ---------- отправка ----------
def _mentionable(person: Person) -> bool:
    return bool(person.phone) or any(j and j.endswith("@lid") for j in (person.jid, person.alt_jid))


def reminder_text(text: str, person: Person | None, late: timedelta = timedelta(0)) -> str:
    """«⏰ @Вася, напоминаю: скинуть дз». «@все» из текста убираем, чтобы напоминание не тегало весь чат."""
    body = EVERYONE_RE.sub(lambda m: m.group(0)[1:], text.strip())
    if person is None:
        msg = f"⏰ напоминаю: {body}"
    else:
        who = f"@{person.name}" if _mentionable(person) else person.name
        msg = f"⏰ {who}, напоминаю: {body}"
    if late > LATE_NOTE_AFTER:
        msg += " (сорян, с опозданием)"
    return msg


async def _deliver(brain: Any, rem: Reminders, row: dict[str, Any], now: datetime) -> bool:
    late = now - row["due_at"]
    if late > GIVE_UP_AFTER:
        log.info("напоминание №%s опоздало на %s — не шлю", row["id"], late)
        await rem.mark_sent(row, now)
        return False
    chat = await brain.db.get_chat(row["chat_id"])
    person = await brain.db.get_person(row["person_id"]) if row.get("person_id") else None
    text = reminder_text(row["text"], person, late)
    # в чате на паузе тоже шлём: напоминание просили явно
    sent = await brain.outbox.send_segments(
        chat, [Segment("text", text)], reply_to=None, quote_first=False,
        people=[person] if person else [], humanize=False,
        prefer_lid=chat["jid"] in getattr(brain, "lid_chats", ()),
    )
    if not sent:
        log.warning("напоминание №%s не ушло в %s — попробую позже", row["id"], mask_phone(chat["jid"]))
        return False
    await rem.mark_sent(row, now)
    log.info("%s: напоминание №%s отправлено", mask_phone(chat["jid"]), row["id"])
    return True


async def run_due(brain: Any, now: datetime | None = None) -> int:
    """Один проход: отправить всё, чему пора. Возвращает, сколько ушло."""
    if getattr(brain, "connection_state", "open") in ("close", "connecting"):
        return 0  # WhatsApp не на связи — подождём, напоминания никуда не денутся
    now = now or utcnow()
    rem = getattr(brain, "reminders", None) or Reminders(brain.db, brain.s)
    sent = 0
    for row in await rem.due(now):
        try:
            if await _deliver(brain, rem, row, now):
                sent += 1
        except Exception:
            log.exception("напоминание №%s: ошибка", row.get("id"))
    return sent


async def reminder_loop(brain: Any, every: float = 30) -> None:
    """Фоновая задача: раз в every секунд отправляет напоминания, которым пора. Никогда не падает."""
    while True:
        await asyncio.sleep(every)
        try:
            await run_due(brain)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ошибка в цикле напоминаний")


# ---------- инструменты модели ----------
def build_reminder_tools(db: DB, settings: Any, ctx: "ToolContext") -> list[ToolSpec]:
    from .tools import ToolError, resolve_person

    rem = Reminders(db, settings)

    async def name_of(person_id: int | None) -> str:
        if person_id is None:
            return "всем"
        p = ctx.people_refs.get(f"p{person_id}") or await db.get_person(person_id)
        return p.name if p else f"p{person_id}"

    async def set_reminder(args: dict[str, Any]) -> str:
        who = str(args.get("person") or "").strip()
        person: Person | None
        if norm(who).lstrip("@") in _EVERYONE_WORDS or (not who and ctx.sender is None):
            person = None  # всему чату, без отметки
        else:
            person = await resolve_person(db, ctx, who)
        try:
            rid = await rem.add(ctx.chat_id, person.id if person else None, ctx.sender.id if ctx.sender else None,
                                str(args.get("text") or ""), str(args.get("at") or ""), args.get("repeat"))
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        row = await rem.get(ctx.chat_id, rid)
        if person is None:
            whom = ", всему чату"
        elif ctx.sender is not None and person.id == ctx.sender.id:
            whom = ""
        else:
            whom = f", отмечу {person.name}"
        if row and row.get("repeat"):
            return f"ок, буду напоминать {rem.fmt_when(row)}{whom} (№{rid})"
        return f"ок, напомню {rem.fmt_at(row['due_at']) if row else ''}{whom} (№{rid})"

    async def list_reminders(args: dict[str, Any]) -> str:
        rows = await rem.list_active(ctx.chat_id)
        if not rows:
            return "активных напоминаний в этом чате нет"
        lines = [f"№{r['id']} — {r['when']} — {await name_of(r['person_id'])}: {r['text']}" for r in rows]
        return "\n".join(lines)

    async def cancel_reminder(args: dict[str, Any]) -> str:
        m = re.search(r"\d+", str(args.get("id") or ""))
        if not m:
            raise ToolError("id: номер напоминания (из list_reminders)")
        rid = int(m.group(0))
        row = await rem.get(ctx.chat_id, rid)
        if row is None or row["done"]:
            raise ToolError(f"напоминания №{rid} нет (или оно уже сработало)")
        me = ctx.sender.id if ctx.sender else None
        if not ctx.is_admin and (me is None or me not in (row["created_by"], row["person_id"])):
            raise ToolError("отменить может только тот, кто поставил, тот, кому напоминают, или админ")
        if not await rem.cancel(ctx.chat_id, rid):
            raise ToolError(f"напоминания №{rid} уже нет")
        return f"отменила №{rid}: «{row['text'][:80]}»"

    return [
        ToolSpec(
            "set_reminder",
            "Поставить напоминание: в нужное время ты сама напишешь в этот чат «⏰ @Имя, напоминаю: …» с отметкой "
            "человека. Можно себе или другому участнику чата, можно с повтором. Время at — местное, в формате "
            "«ГГГГ-ММ-ДД ЧЧ:ММ»: посчитай его от строки «Сейчас:» в начале контекста («завтра в 8» — завтрашняя "
            "дата и 08:00, «через 2 часа» — сейчас + 2 ч). Для повтора at — ближайший раз. Вернёт подтверждение и "
            "номер напоминания.",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "о чём напомнить, коротко: «контрольная по алгебре», «скинуть дз»"},
                    "at": {"type": "string", "description": "местное время «ГГГГ-ММ-ДД ЧЧ:ММ», например 2026-10-17 08:00"},
                    "person": {"type": "string",
                               "description": "кому: p12 из контекста, имя/ник, «я» (автор сообщения, по умолчанию) "
                                              "или «все» (всему чату, без отметки)"},
                    "repeat": {"type": "string", "enum": list(REPEATS),
                               "description": "повтор: daily — каждый день, weekly — каждую неделю в тот же день, "
                                              "weekdays — по будням (пн–пт); не указывай, если один раз"},
                },
                "required": ["text", "at"],
            },
            set_reminder,
        ),
        ToolSpec(
            "list_reminders",
            "Показать активные напоминания этого чата: номер, когда, кому и о чём.",
            {"type": "object", "properties": {}},
            list_reminders,
        ),
        ToolSpec(
            "cancel_reminder",
            "Отменить напоминание по номеру (номер — из set_reminder или list_reminders). Отменить может тот, "
            "кто поставил, тот, кому напоминают, или админ.",
            {"type": "object", "properties": {"id": {"type": "integer", "description": "номер напоминания"}},
             "required": ["id"]},
            cancel_reminder,
        ),
    ]
