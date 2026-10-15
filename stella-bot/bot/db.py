"""База бота: SQLite на старте, PostgreSQL — сменой DATABASE_URL (SQLAlchemy Core, async)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    delete,
    func,
    insert,
    inspect,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .util import norm, utcnow

metadata = MetaData()

OWNER_SENDER = "__owner__"  # sender_name для сообщений, которые владелец набрал руками с телефона Стеллы

chats = Table(
    "chats",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("instance", String(64), nullable=False),
    Column("jid", String(128), nullable=False),
    Column("is_group", Boolean, nullable=False, default=False),
    Column("title", String(256)),
    Column("paused_until", DateTime),
    Column("chime_level", String(16)),
    Column("notes", Text, default=""),  # что Стелла знает о самом чате: вайб, мемы
    Column("msgs_since_extract", Integer, nullable=False, default=0),
    Column("last_bot_at", DateTime),
    Column("last_eval_at", DateTime),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("updated_at", DateTime, nullable=False, default=utcnow),
    Column("mood", String(200)),  # настроение, которое Стелла сама себе поставила
    Column("mood_until", DateTime),
    Column("last_initiative_at", DateTime),  # когда сама последний раз завела разговор
    Column("about", Text),  # что владелец рассказал про этот чат (python -m bot.notes), не вытесняется
    UniqueConstraint("instance", "jid", name="uq_chat"),
)

profiles = Table(  # анкета человека в чате, которую Стелла заполняет сама
    "profiles",
    metadata,
    Column("person_id", Integer, ForeignKey("people.id"), primary_key=True),
    Column("chat_id", Integer, ForeignKey("chats.id"), primary_key=True),
    Column("data", Text, nullable=False, default="{}"),  # JSON: поле анкеты -> значение
    Column("updated_at", DateTime, nullable=False, default=utcnow),
)

PROFILE_FIELDS = [
    "имя", "как называют", "возраст/класс", "учёба", "увлечения", "игры", "любимое", "характер",
    "как общается", "дружит с", "спорит с", "о себе", "важное",
]
PROFILE_MAX_FIELDS = 20
PROFILE_MAX_VALUE = 200

grudges = Table(  # на кого Стелла обижена
    "grudges",
    metadata,
    Column("chat_id", Integer, ForeignKey("chats.id"), primary_key=True),
    Column("person_id", Integer, ForeignKey("people.id"), primary_key=True),
    Column("until", DateTime, nullable=False),
    Column("reason", String(300), default=""),
)

people = Table(
    "people",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("jid", String(128), nullable=False, unique=True),
    Column("alt_jid", String(128)),
    Column("phone", String(32)),
    Column("push_name", String(128), default=""),
    Column("nickname", String(128)),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("last_seen_at", DateTime, nullable=False, default=utcnow),
)

members = Table(  # кто в каком чате появлялся
    "members",
    metadata,
    Column("chat_id", Integer, ForeignKey("chats.id"), primary_key=True),
    Column("person_id", Integer, ForeignKey("people.id"), primary_key=True),
    Column("msg_count", Integer, nullable=False, default=0),
    Column("last_seen_at", DateTime, nullable=False, default=utcnow),
)

facts = Table(
    "facts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("person_id", Integer, ForeignKey("people.id"), nullable=False),
    Column("chat_id", Integer, ForeignKey("chats.id")),
    Column("fact", Text, nullable=False),
    Column("source", String(16), nullable=False, default="tool"),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Index("ix_facts_person_chat", "person_id", "chat_id"),
)

messages = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("chat_id", Integer, ForeignKey("chats.id"), nullable=False),
    Column("wa_message_id", String(128)),
    Column("person_id", Integer, ForeignKey("people.id")),
    Column("sender_name", String(128), default=""),
    Column("role", String(16), nullable=False),  # user | assistant
    Column("kind", String(16), nullable=False, default="text"),
    Column("text", Text, nullable=False, default=""),
    Column("quoted_wa_id", String(128)),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    UniqueConstraint("chat_id", "wa_message_id", name="uq_msg"),
    Index("ix_messages_chat_id", "chat_id", "id"),
)

wallets = Table(
    "wallets",
    metadata,
    Column("chat_id", Integer, ForeignKey("chats.id"), primary_key=True),
    Column("person_id", Integer, ForeignKey("people.id"), primary_key=True),
    Column("balance", Integer, nullable=False, default=0),
    Column("last_bonus_at", DateTime),
    Column("won", Integer, nullable=False, default=0),
    Column("lost", Integer, nullable=False, default=0),
    Column("games", Integer, nullable=False, default=0),
)

stickers = Table(
    "stickers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("sha256", String(64), nullable=False, unique=True),
    Column("mood", String(64)),
    Column("path", String(512), nullable=False),
    Column("source", String(16), nullable=False, default="pack"),  # pack | learned | collected
    Column("wa_message_id", String(128)),
    Column("uses", Integer, nullable=False, default=0),
    Column("created_at", DateTime, nullable=False, default=utcnow),
)

kv = Table(
    "kv",
    metadata,
    Column("key", String(128), primary_key=True),
    Column("value", Text, nullable=False, default=""),
    Column("num", Float, nullable=False, default=0.0),
)


def _add_missing_columns(sync_conn: Any) -> None:
    """Простая миграция: новые nullable-колонки добавляются в уже существующие таблицы."""
    insp = inspect(sync_conn)
    for table in metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in existing and col.nullable:
                coltype = col.type.compile(dialect=sync_conn.dialect)
                sync_conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}'))


def to_async_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    return url


@dataclass
class Person:
    id: int
    jid: str
    phone: str | None
    push_name: str
    nickname: str | None
    alt_jid: str | None = None

    @property
    def name(self) -> str:
        return self.nickname or self.push_name or (f"+{self.phone}" if self.phone else "кто-то")

    @property
    def ref(self) -> str:
        return f"p{self.id}"


def _person(row: Any) -> Person:
    return Person(
        id=row.id,
        jid=row.jid,
        phone=row.phone,
        push_name=row.push_name or "",
        nickname=row.nickname,
        alt_jid=row.alt_jid,
    )


class DB:
    def __init__(self, url: str):
        async_url = to_async_url(url)
        if async_url.startswith("sqlite+aiosqlite:///"):
            path = async_url.split(":///", 1)[1]
            if path and path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.engine: AsyncEngine = create_async_engine(async_url, future=True)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
            await conn.run_sync(_add_missing_columns)

    async def close(self) -> None:
        await self.engine.dispose()

    # ---------- chats ----------
    async def get_or_create_chat(self, instance: str, jid: str, is_group: bool) -> dict[str, Any]:
        async with self.engine.begin() as conn:
            row = (
                await conn.execute(select(chats).where(chats.c.instance == instance, chats.c.jid == jid))
            ).mappings().first()
            if row:
                return dict(row)
            try:
                await conn.execute(insert(chats).values(instance=instance, jid=jid, is_group=is_group))
            except IntegrityError:
                pass
        return await self.get_chat_by_jid(instance, jid)  # type: ignore[return-value]

    async def get_chat_by_jid(self, instance: str, jid: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(select(chats).where(chats.c.instance == instance, chats.c.jid == jid))
            ).mappings().first()
            return dict(row) if row else None

    async def get_chat(self, chat_id: int) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(chats).where(chats.c.id == chat_id))).mappings().one()
            return dict(row)

    async def update_chat(self, chat_id: int, **values: Any) -> None:
        values["updated_at"] = utcnow()
        async with self.engine.begin() as conn:
            await conn.execute(update(chats).where(chats.c.id == chat_id).values(**values))

    async def group_chats(self, instance: str) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(select(chats).where(chats.c.instance == instance, chats.c.is_group.is_(True)))
            ).mappings().all()
            return [dict(r) for r in rows]

    async def all_chats(self, instance: str) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(select(chats).where(chats.c.instance == instance))).mappings().all()
            return [dict(r) for r in rows]

    async def unpause_all(self, instance: str) -> int:
        """Снять паузу во всех чатах. Возвращает, сколько чатов было на паузе."""
        async with self.engine.begin() as conn:
            res = await conn.execute(
                update(chats)
                .where(chats.c.instance == instance, chats.c.paused_until.is_not(None), chats.c.paused_until > utcnow())
                .values(paused_until=None)
            )
            return res.rowcount or 0

    async def count_user_messages(self, chat_id: int) -> int:
        async with self.engine.connect() as conn:
            return (
                await conn.execute(
                    select(func.count()).select_from(messages)
                    .where(messages.c.chat_id == chat_id, messages.c.role == "user")
                )
            ).scalar_one()

    # ---------- анкеты ----------
    async def get_profile(self, person_id: int, chat_id: int) -> dict[str, str]:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(profiles.c.data).where(profiles.c.person_id == person_id, profiles.c.chat_id == chat_id)
                )
            ).first()
        if not row:
            return {}
        try:
            data = json.loads(row.data or "{}")
        except ValueError:
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    async def update_profile(self, person_id: int, chat_id: int, updates: dict[str, Any]) -> dict[str, str]:
        """Обновить поля анкеты (пустое значение — удалить поле). Возвращает анкету целиком."""
        profile = await self.get_profile(person_id, chat_id)
        for key, value in updates.items():
            key = str(key).strip().lower()[:40]
            if not key:
                continue
            value = "" if value is None else str(value).strip()[:PROFILE_MAX_VALUE]
            if value:
                if key not in profile and len(profile) >= PROFILE_MAX_FIELDS:
                    continue
                profile[key] = value
            else:
                profile.pop(key, None)
        raw = json.dumps(profile, ensure_ascii=False)
        async with self.engine.begin() as conn:
            res = await conn.execute(
                update(profiles)
                .where(profiles.c.person_id == person_id, profiles.c.chat_id == chat_id)
                .values(data=raw, updated_at=utcnow())
            )
            if res.rowcount == 0:
                try:
                    await conn.execute(insert(profiles).values(person_id=person_id, chat_id=chat_id, data=raw))
                except IntegrityError:
                    await conn.execute(
                        update(profiles)
                        .where(profiles.c.person_id == person_id, profiles.c.chat_id == chat_id)
                        .values(data=raw, updated_at=utcnow())
                    )
        return profile

    # ---------- обиды ----------
    async def set_grudge(self, chat_id: int, person_id: int, until: datetime, reason: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(delete(grudges).where(grudges.c.chat_id == chat_id, grudges.c.person_id == person_id))
            await conn.execute(insert(grudges).values(chat_id=chat_id, person_id=person_id, until=until,
                                                      reason=reason[:300]))

    async def clear_grudge(self, chat_id: int, person_id: int) -> bool:
        async with self.engine.begin() as conn:
            res = await conn.execute(
                delete(grudges).where(grudges.c.chat_id == chat_id, grudges.c.person_id == person_id)
            )
            return bool(res.rowcount)

    async def clear_all_grudges(self) -> int:
        async with self.engine.begin() as conn:
            res = await conn.execute(delete(grudges).where(grudges.c.until > utcnow()))
            return res.rowcount or 0

    async def active_grudges(self, chat_id: int, now: datetime | None = None) -> dict[int, str]:
        """person_id -> причина, для обид, которые ещё не прошли."""
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(grudges.c.person_id, grudges.c.reason)
                    .where(grudges.c.chat_id == chat_id, grudges.c.until > (now or utcnow()))
                )
            ).all()
        return {r.person_id: r.reason or "" for r in rows}

    async def bump_extract_counter(self, chat_id: int) -> int:
        async with self.engine.begin() as conn:
            await conn.execute(
                update(chats)
                .where(chats.c.id == chat_id)
                .values(msgs_since_extract=chats.c.msgs_since_extract + 1)
            )
            return (
                await conn.execute(select(chats.c.msgs_since_extract).where(chats.c.id == chat_id))
            ).scalar_one()

    # ---------- people ----------
    async def upsert_person(
        self, jid: str, push_name: str = "", phone: str = "", alt_jid: str | None = None
    ) -> Person:
        now = utcnow()
        async with self.engine.begin() as conn:
            cond = people.c.jid == jid
            if alt_jid:
                cond = or_(cond, people.c.jid == alt_jid, people.c.alt_jid == jid)
            row = (await conn.execute(select(people).where(cond))).first()
            if row:
                values: dict[str, Any] = {"last_seen_at": now}
                if push_name and push_name != row.push_name:
                    values["push_name"] = push_name
                if phone and not row.phone:
                    values["phone"] = phone
                if alt_jid and not row.alt_jid and alt_jid != row.jid:
                    values["alt_jid"] = alt_jid
                await conn.execute(update(people).where(people.c.id == row.id).values(**values))
                row = (await conn.execute(select(people).where(people.c.id == row.id))).first()
                return _person(row)
            try:
                res = await conn.execute(
                    insert(people).values(
                        jid=jid, push_name=push_name, phone=phone or None, alt_jid=alt_jid, last_seen_at=now
                    )
                )
                pid = res.inserted_primary_key[0]
            except IntegrityError:
                pid = (await conn.execute(select(people.c.id).where(people.c.jid == jid))).scalar_one()
            row = (await conn.execute(select(people).where(people.c.id == pid))).first()
            return _person(row)

    async def get_person(self, person_id: int) -> Person | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(people).where(people.c.id == person_id))).first()
            return _person(row) if row else None

    async def find_person_by_jid(self, jid: str) -> Person | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(select(people).where(or_(people.c.jid == jid, people.c.alt_jid == jid)))
            ).first()
            return _person(row) if row else None

    async def set_nickname(self, person_id: int, nickname: str | None) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(update(people).where(people.c.id == person_id).values(nickname=nickname))

    async def touch_member(self, chat_id: int, person_id: int) -> None:
        now = utcnow()
        async with self.engine.begin() as conn:
            res = await conn.execute(
                update(members)
                .where(members.c.chat_id == chat_id, members.c.person_id == person_id)
                .values(msg_count=members.c.msg_count + 1, last_seen_at=now)
            )
            if res.rowcount == 0:
                try:
                    await conn.execute(
                        insert(members).values(chat_id=chat_id, person_id=person_id, msg_count=1, last_seen_at=now)
                    )
                except IntegrityError:
                    pass

    async def chat_members(self, chat_id: int, limit: int = 50) -> list[Person]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(people)
                    .join(members, members.c.person_id == people.c.id)
                    .where(members.c.chat_id == chat_id)
                    .order_by(members.c.last_seen_at.desc())
                    .limit(limit)
                )
            ).all()
            return [_person(r) for r in rows]

    async def search_people(self, chat_id: int, query: str, limit: int = 5) -> list[Person]:
        """Поиск по имени/нику/номеру среди тех, кто писал в этот чат."""
        q = norm(query).lstrip("@")
        if not q:
            return []
        found: list[Person] = []
        for p in await self.chat_members(chat_id, limit=500):
            names = [norm(p.push_name), norm(p.nickname or ""), p.phone or ""]
            if any(n and (n == q or q in n or (len(n) >= 3 and n in q)) for n in names):
                found.append(p)
        # точные совпадения — первыми
        found.sort(key=lambda p: 0 if q in (norm(p.push_name), norm(p.nickname or "")) else 1)
        return found[:limit]

    # ---------- facts ----------
    async def add_fact(self, person_id: int, chat_id: int | None, fact: str, source: str, cap: int) -> bool:
        fact = fact.strip()
        if not fact:
            return False
        key = norm(fact)
        async with self.engine.begin() as conn:
            existing = (
                await conn.execute(
                    select(facts.c.id, facts.c.fact).where(facts.c.person_id == person_id, facts.c.chat_id == chat_id)
                )
            ).all()
            for _, old in existing:
                o = norm(old)
                if o == key or (len(key) > 12 and (key in o or o in key)):
                    return False
            await conn.execute(
                insert(facts).values(person_id=person_id, chat_id=chat_id, fact=fact[:500], source=source)
            )
            if len(existing) + 1 > cap:
                old_ids = [
                    r.id
                    for r in (
                        await conn.execute(
                            select(facts.c.id)
                            .where(facts.c.person_id == person_id, facts.c.chat_id == chat_id)
                            .order_by(facts.c.id)
                            .limit(len(existing) + 1 - cap)
                        )
                    ).all()
                ]
                await conn.execute(delete(facts).where(facts.c.id.in_(old_ids)))
        return True

    async def get_facts(
        self, person_id: int, chat_id: int | None, limit: int, share_across_chats: bool = False
    ) -> list[str]:
        cond = facts.c.person_id == person_id
        if not share_across_chats:
            cond = and_(cond, or_(facts.c.chat_id == chat_id, facts.c.chat_id.is_(None)))
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(select(facts.c.fact).where(cond).order_by(facts.c.id.desc()).limit(limit))
            ).all()
        return [r.fact for r in reversed(rows)]

    async def forget_facts(self, person_id: int, chat_id: int | None, needle: str | None) -> int:
        async with self.engine.begin() as conn:
            rows = (
                await conn.execute(
                    select(facts.c.id, facts.c.fact).where(facts.c.person_id == person_id, facts.c.chat_id == chat_id)
                )
            ).all()
            n = norm(needle or "")
            ids = [r.id for r in rows if not n or n in norm(r.fact)]
            if ids:
                await conn.execute(delete(facts).where(facts.c.id.in_(ids)))
            return len(ids)

    # ---------- messages ----------
    async def add_message(
        self,
        chat_id: int,
        role: str,
        text: str,
        *,
        wa_message_id: str | None = None,
        person_id: int | None = None,
        sender_name: str = "",
        kind: str = "text",
        quoted_wa_id: str | None = None,
    ) -> int | None:
        """Возвращает id или None, если такое wa_message_id уже было (дубль вебхука)."""
        try:
            async with self.engine.begin() as conn:
                res = await conn.execute(
                    insert(messages).values(
                        chat_id=chat_id,
                        role=role,
                        text=text,
                        wa_message_id=wa_message_id,
                        person_id=person_id,
                        sender_name=sender_name,
                        kind=kind,
                        quoted_wa_id=quoted_wa_id,
                        created_at=utcnow(),
                    )
                )
                return int(res.inserted_primary_key[0])
        except IntegrityError:
            return None

    async def recent_messages(self, chat_id: int, limit: int) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(messages).where(messages.c.chat_id == chat_id).order_by(messages.c.id.desc()).limit(limit)
                )
            ).mappings().all()
        return [dict(r) for r in reversed(rows)]

    async def messages_after(self, chat_id: int, after_id: int, limit: int) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(messages)
                    .where(messages.c.chat_id == chat_id, messages.c.id > after_id)
                    .order_by(messages.c.id)
                    .limit(limit)
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    async def get_message_by_wa_id(self, chat_id: int, wa_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(messages).where(messages.c.chat_id == chat_id, messages.c.wa_message_id == wa_id)
                )
            ).mappings().first()
            return dict(row) if row else None

    async def last_stella_reply(self, chat_id: int) -> list[dict[str, Any]]:
        """Её последний ответ целиком: подряд идущие сообщения Стеллы (не владельца, не удалённые)
        перед самыми свежими сообщениями людей."""
        rows = await self.recent_messages(chat_id, 40)
        reply: list[dict[str, Any]] = []
        for r in reversed(rows):
            if r["role"] == "user":
                if reply:
                    break
                continue
            if r.get("sender_name") == OWNER_SENDER:
                if reply:
                    break
                continue
            if r.get("kind") == "deleted" or not r.get("wa_message_id"):
                continue
            reply.append(r)
        return list(reversed(reply))

    async def recent_stella_messages(self, chat_id: int, limit: int = 15) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(messages)
                    .where(messages.c.chat_id == chat_id, messages.c.role == "assistant",
                           messages.c.sender_name != OWNER_SENDER, messages.c.kind != "deleted",
                           messages.c.wa_message_id.is_not(None))
                    .order_by(messages.c.id.desc())
                    .limit(limit)
                )
            ).mappings().all()
            return [dict(r) for r in rows]

    async def mark_deleted(self, chat_id: int, wa_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                update(messages).where(messages.c.chat_id == chat_id, messages.c.wa_message_id == wa_id)
                .values(kind="deleted", text="")
            )

    async def is_stella_message(self, wa_id: str) -> bool:
        """Отправила сама Стелла (а не владелец руками с её телефона)."""
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(messages.c.id).where(messages.c.wa_message_id == wa_id, messages.c.role == "assistant",
                                                messages.c.sender_name != OWNER_SENDER)
                )
            ).first()
            return row is not None

    async def is_bot_message(self, wa_id: str) -> bool:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    select(messages.c.id).where(messages.c.wa_message_id == wa_id, messages.c.role == "assistant")
                )
            ).first()
            return row is not None

    # ---------- wallets ----------
    async def get_wallet(self, chat_id: int, person_id: int, start_balance: int) -> dict[str, Any]:
        async with self.engine.begin() as conn:
            row = (
                await conn.execute(
                    select(wallets).where(wallets.c.chat_id == chat_id, wallets.c.person_id == person_id)
                )
            ).mappings().first()
            if row:
                return dict(row)
            try:
                await conn.execute(
                    insert(wallets).values(chat_id=chat_id, person_id=person_id, balance=start_balance)
                )
            except IntegrityError:
                pass
            row = (
                await conn.execute(
                    select(wallets).where(wallets.c.chat_id == chat_id, wallets.c.person_id == person_id)
                )
            ).mappings().one()
            return dict(row)

    async def update_wallet(self, chat_id: int, person_id: int, **values: Any) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                update(wallets).where(wallets.c.chat_id == chat_id, wallets.c.person_id == person_id).values(**values)
            )

    async def top_wallets(self, chat_id: int, limit: int = 10) -> list[tuple[Person, int]]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(people, wallets.c.balance)
                    .join(wallets, wallets.c.person_id == people.c.id)
                    .where(wallets.c.chat_id == chat_id)
                    .order_by(wallets.c.balance.desc())
                    .limit(limit)
                )
            ).all()
        return [(_person(r), int(r.balance)) for r in rows]

    # ---------- stickers ----------
    async def add_sticker(
        self, sha256: str, path: str, mood: str | None, source: str, wa_message_id: str | None = None
    ) -> bool:
        try:
            async with self.engine.begin() as conn:
                await conn.execute(
                    insert(stickers).values(
                        sha256=sha256, path=path, mood=mood, source=source, wa_message_id=wa_message_id
                    )
                )
            return True
        except IntegrityError:
            return False

    async def sticker_by_sha(self, sha256: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(stickers).where(stickers.c.sha256 == sha256))).mappings().first()
            return dict(row) if row else None

    async def sticker_by_wa_id(self, wa_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(select(stickers).where(stickers.c.wa_message_id == wa_id))
            ).mappings().first()
            return dict(row) if row else None

    async def set_sticker_mood(self, sticker_id: int, mood: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                update(stickers).where(stickers.c.id == sticker_id).values(mood=mood, source="learned")
            )

    async def stickers_for_mood(self, mood: str | None) -> list[dict[str, Any]]:
        cond = stickers.c.mood.is_(None) if mood is None else stickers.c.mood == mood
        async with self.engine.connect() as conn:
            rows = (await conn.execute(select(stickers).where(cond))).mappings().all()
            return [dict(r) for r in rows]

    async def sticker_moods(self) -> list[str]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(stickers.c.mood).where(stickers.c.mood.is_not(None)).group_by(stickers.c.mood)
                )
            ).all()
            return sorted(r.mood for r in rows)

    async def count_stickers(self, source: str) -> int:
        async with self.engine.connect() as conn:
            return (
                await conn.execute(select(func.count()).select_from(stickers).where(stickers.c.source == source))
            ).scalar_one()

    async def bump_sticker(self, sticker_id: int) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(update(stickers).where(stickers.c.id == sticker_id).values(uses=stickers.c.uses + 1))

    # ---------- kv ----------
    async def kv_get(self, key: str) -> tuple[str, float] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(kv).where(kv.c.key == key))).first()
            return (row.value, row.num) if row else None

    async def kv_set(self, key: str, value: str = "", num: float = 0.0) -> None:
        async with self.engine.begin() as conn:
            res = await conn.execute(update(kv).where(kv.c.key == key).values(value=value, num=num))
            if res.rowcount == 0:
                try:
                    await conn.execute(insert(kv).values(key=key, value=value, num=num))
                except IntegrityError:
                    await conn.execute(update(kv).where(kv.c.key == key).values(value=value, num=num))

    async def kv_add(self, key: str, delta: float) -> float:
        async with self.engine.begin() as conn:
            res = await conn.execute(update(kv).where(kv.c.key == key).values(num=kv.c.num + delta))
            if res.rowcount == 0:
                try:
                    await conn.execute(insert(kv).values(key=key, value="", num=delta))
                except IntegrityError:
                    await conn.execute(update(kv).where(kv.c.key == key).values(num=kv.c.num + delta))
            return (await conn.execute(select(kv.c.num).where(kv.c.key == key))).scalar_one()


def chat_paused(chat: dict[str, Any], now: datetime | None = None) -> bool:
    until = chat.get("paused_until")
    return bool(until and until > (now or utcnow()))
