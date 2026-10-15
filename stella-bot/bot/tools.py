"""Инструменты, которые может вызывать модель. Правила (чей баланс, кому можно забыть) — в коде, не в промпте."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Awaitable, Callable, Protocol

from .casino import Bet, Casino, CasinoResult
from .config import Settings
from .db import DB, Person
from .llm.base import ToolSpec
from .util import money, norm, utcnow


class ChatActions(Protocol):
    """Действия Стеллы в конкретном чате (реализация — в brain)."""

    async def send_poll(self, question: str, options: list[str], multiple: bool) -> None: ...

    async def delete_mine(self, *, quoted_id: str | None = None, text: str | None = None) -> list[str]: ...


@dataclass
class ToolContext:
    chat_id: int
    sender: Person | None  # None — Стелла пишет сама, без чьего-то сообщения
    people_refs: dict[str, Person]
    is_admin: bool
    actions: ChatActions | None = None
    quoted_wa_id: str | None = None  # на какое сообщение ответили (для «удали это»)
    polls_queued: int = 0
    # То, что инструмент хочет отправить в чат сам (результат ставки), до ответа модели
    pre_messages: list[CasinoResult] = field(default_factory=list)
    # Действия после ответа модели (опрос — после её сообщения «го голосовать»)
    after: list[Callable[[], Awaitable[Any]]] = field(default_factory=list)


class ToolError(Exception):
    pass


async def resolve_person(db: DB, ctx: ToolContext, who: str | None) -> Person:
    w = (who or "").strip()
    if norm(w) in ("", "я", "мне", "меня", "me", "self", "sender"):
        if ctx.sender is None:
            raise ToolError("укажи человека (pNN или имя)")
        return ctx.sender
    m = re.fullmatch(r"\[?p(\d+)\]?", w.lower())
    if m:
        ref = f"p{m.group(1)}"
        if ref in ctx.people_refs:
            return ctx.people_refs[ref]
        for p in await db.chat_members(ctx.chat_id, limit=1000):
            if p.ref == ref:
                return p
        raise ToolError(f"{ref} нет в этом чате")
    found = await db.search_people(ctx.chat_id, w)
    if not found:
        raise ToolError(f"не нашла никого по запросу «{w}» в этом чате")
    if len(found) > 1 and norm(found[0].name) != norm(w.lstrip("@")):
        options = ", ".join(f"{p.name} [{p.ref}]" for p in found)
        raise ToolError(f"несколько подходят: {options}. уточни через pNN")
    return found[0]


def build_tools(db: DB, casino: Casino, settings: Settings, ctx: ToolContext) -> list[ToolSpec]:
    async def remember(args: dict[str, Any]) -> str:
        person = await resolve_person(db, ctx, args.get("person"))
        fact = str(args.get("fact") or "").strip()
        if not fact:
            raise ToolError("пустой факт")
        added = await db.add_fact(person.id, ctx.chat_id, fact, "tool", settings.memory_max_facts)
        return f"запомнила про {person.name}" if added else f"это я про {person.name} уже знаю"

    async def forget(args: dict[str, Any]) -> str:
        person = await resolve_person(db, ctx, args.get("person"))
        if (ctx.sender is None or person.id != ctx.sender.id) and not ctx.is_admin:
            raise ToolError("забывать можно только про себя (или если просит админ)")
        n = await db.forget_facts(person.id, ctx.chat_id, args.get("about") or None)
        return f"удалено фактов: {n}"

    async def find_person(args: dict[str, Any]) -> str:
        query = str(args.get("query") or "").strip()
        try:
            person = await resolve_person(db, ctx, query)
        except ToolError as exc:
            return str(exc)
        facts = await db.get_facts(person.id, ctx.chat_id, 40, settings.memory_share_across_chats)
        names = [person.name]
        if person.push_name and person.push_name != person.name:
            names.append(f"в WhatsApp «{person.push_name}»")
        known = "; ".join(facts) if facts else "фактов пока нет"
        return f"{', '.join(names)} [{person.ref}]: {known}"

    async def set_nickname(args: dict[str, Any]) -> str:
        person = await resolve_person(db, ctx, args.get("person"))
        nickname = str(args.get("nickname") or "").strip()[:60] or None
        await db.set_nickname(person.id, nickname)
        return f"ок, теперь {person.push_name or person.ref} = {nickname}" if nickname else "ник сброшен"

    async def remember_chat(args: dict[str, Any]) -> str:
        note = str(args.get("note") or "").strip()
        if not note:
            raise ToolError("пустая заметка")
        chat = await db.get_chat(ctx.chat_id)
        notes = [n for n in (chat.get("notes") or "").split("\n") if n.strip()]
        if norm(note) in {norm(n.lstrip("- ")) for n in notes}:
            return "это уже есть"
        notes.append(f"- {note[:200]}")
        await db.update_chat(ctx.chat_id, notes="\n".join(notes[-25:]))
        return "запомнила про чат"

    async def casino_tool(args: dict[str, Any]) -> str:
        if ctx.sender is None:
            raise ToolError("казино — только когда кто-то сам просит")
        action = args.get("action")
        if action == "play":
            game = args.get("game")
            if game not in ("roulette", "slots", "coin", "dice"):
                raise ToolError("game: roulette | slots | coin | dice")
            amount = args.get("amount")
            bet = Bet(
                game=game,
                choice=str(args["choice"]).lower() if args.get("choice") not in (None, "") else None,
                amount=int(amount) if amount not in (None, "") else None,
                all_in=bool(args.get("all_in")),
            )
            if bet.choice and game == "roulette" and bet.choice not in ("red", "black", "zero", "even", "odd") \
                    and not (bet.choice.isdigit() and 0 <= int(bet.choice) <= 36):
                raise ToolError("choice для рулетки: red/black/zero/even/odd или число 0-36")
            res = await casino.play(ctx.chat_id, ctx.sender, bet)
        elif action == "balance":
            person = await resolve_person(db, ctx, args.get("person"))
            return f"у {person.name} {money(await casino.balance(ctx.chat_id, person))}"
        elif action == "bonus":
            res = await casino.bonus(ctx.chat_id, ctx.sender)
        elif action == "top":
            res = await casino.top(ctx.chat_id)
        elif action == "transfer":
            dst = await resolve_person(db, ctx, args.get("person"))
            res = await casino.transfer(ctx.chat_id, ctx.sender, dst, int(args.get("amount") or 0))
        else:
            raise ToolError("action: play | balance | bonus | top | transfer")
        ctx.pre_messages.append(res)
        return "в чат уже отправлено: " + " / ".join(res.lines)

    async def create_poll(args: dict[str, Any]) -> str:
        if ctx.actions is None:
            raise ToolError("опросы здесь недоступны")
        question = str(args.get("question") or "").strip()[:250]
        options = [str(o).strip()[:100] for o in (args.get("options") or []) if str(o).strip()]
        options = list(dict.fromkeys(options))[:12]
        if not question or len(options) < 2:
            raise ToolError("нужен вопрос и минимум 2 варианта")
        if ctx.polls_queued >= 1:
            raise ToolError("одного опроса за раз хватит")
        multiple = bool(args.get("multiple"))
        ctx.polls_queued += 1
        ctx.after.append(lambda: ctx.actions.send_poll(question, options, multiple))
        return "опрос уйдёт в чат сразу после твоего сообщения"

    async def delete_my_last_message(args: dict[str, Any]) -> str:
        if ctx.actions is None:
            raise ToolError("недоступно")
        deleted = await ctx.actions.delete_mine(quoted_id=ctx.quoted_wa_id, text=args.get("text") or None)
        if not deleted:
            return "нечего удалять (или не получилось)"
        return "удалила: " + " / ".join(f"«{t[:80]}»" for t in deleted)

    async def set_mood(args: dict[str, Any]) -> str:
        mood = str(args.get("mood") or "").strip()[:150]
        if not mood:
            raise ToolError("опиши настроение")
        try:
            hours = min(max(float(args.get("hours") or 3), 0.25), 24)
        except (TypeError, ValueError):
            hours = 3.0
        await db.update_chat(ctx.chat_id, mood=mood, mood_until=utcnow() + timedelta(hours=hours))
        return f"настроение: {mood} (на {hours:g} ч)"

    async def take_offense(args: dict[str, Any]) -> str:
        # Обижается только на автора сообщения: чтобы её нельзя было натравить на третьего человека
        person = ctx.sender
        if person is None:
            raise ToolError("обижаться можно только на того, кто тебе сейчас написал")
        if person.id in await db.active_grudges(ctx.chat_id):
            return f"ты и так обижена на {person.name}"
        minutes = min(max(int(float(args.get("minutes") or 60)), 5), 24 * 60)
        reason = str(args.get("reason") or "").strip()[:100]
        await db.set_grudge(ctx.chat_id, person.id, utcnow() + timedelta(minutes=minutes), reason)
        return f"ты обижена на {person.name} на {minutes} мин"

    async def forgive(args: dict[str, Any]) -> str:
        person = await resolve_person(db, ctx, args.get("person"))
        return f"простила {person.name}" if await db.clear_grudge(ctx.chat_id, person.id) else "обиды и не было"

    person_hint = "кто: p12 из контекста, имя/ник или «я» (автор сообщения)"
    return [
        ToolSpec(
            "remember",
            "Запомнить факт о человеке из чата (долговременная память).",
            {
                "type": "object",
                "properties": {
                    "person": {"type": "string", "description": person_hint},
                    "fact": {"type": "string", "description": "коротко, от третьего лица: «учится на врача в КазНМУ»"},
                },
                "required": ["person", "fact"],
            },
            remember,
        ),
        ToolSpec(
            "forget",
            "Забыть факты о человеке, если он сам просит (about пусто = всё).",
            {
                "type": "object",
                "properties": {
                    "person": {"type": "string", "description": person_hint},
                    "about": {"type": "string", "description": "о чём забыть, подстрока факта"},
                },
                "required": ["person"],
            },
            forget,
        ),
        ToolSpec(
            "find_person",
            "Найти человека из этого чата по имени/нику и получить всё, что ты о нём помнишь.",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            find_person,
        ),
        ToolSpec(
            "set_nickname",
            "Запомнить, как называть человека (ник). Пустой nickname — сбросить.",
            {
                "type": "object",
                "properties": {
                    "person": {"type": "string", "description": person_hint},
                    "nickname": {"type": "string"},
                },
                "required": ["person", "nickname"],
            },
            set_nickname,
        ),
        ToolSpec(
            "remember_chat",
            "Запомнить что-то про сам чат: общие шутки, традиции, планы компании.",
            {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]},
            remember_chat,
        ),
        ToolSpec(
            "casino",
            "Игрушечное казино на бананы 🍌 за автора сообщения: play (ставка), balance, bonus (раз в "
            f"{settings.casino_bonus_hours:g}ч), top, transfer. Результат сам уходит в чат.",
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["play", "balance", "bonus", "top", "transfer"]},
                    "game": {"type": "string", "enum": ["roulette", "slots", "coin", "dice"]},
                    "choice": {
                        "type": "string",
                        "description": "рулетка: red/black/zero/even/odd или число 0-36; монетка: heads/tails",
                    },
                    "amount": {"type": "integer"},
                    "all_in": {"type": "boolean", "description": "поставить всё"},
                    "person": {"type": "string", "description": "для balance/transfer: " + person_hint},
                },
                "required": ["action"],
            },
            casino_tool,
        ),
        ToolSpec(
            "create_poll",
            "Создать опрос (голосование) в чате. Сама решаешь, когда это к месту.",
            {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 12},
                    "multiple": {"type": "boolean", "description": "можно выбрать несколько вариантов"},
                },
                "required": ["question", "options"],
            },
            create_poll,
        ),
        ToolSpec(
            "delete_my_last_message",
            "Удалить своё сообщение у всех (если ляпнула лишнее или ошиблась). Без аргументов — весь твой "
            "последний ответ; если тебя просят удалить ответом на твоё сообщение — удалится именно оно; "
            "text — кусок текста, если нужно удалить конкретное. Вернёт, что удалено.",
            {"type": "object", "properties": {"text": {"type": "string"}}},
            delete_my_last_message,
        ),
        ToolSpec(
            "set_mood",
            "Поменять своё настроение (как ты себя сейчас чувствуешь и почему), на сколько часов.",
            {
                "type": "object",
                "properties": {
                    "mood": {"type": "string", "description": "например «злая на Васю, он съел мой торт» или «на седьмом небе»"},
                    "hours": {"type": "number", "description": "на сколько часов, по умолчанию 3"},
                },
                "required": ["mood"],
            },
            set_mood,
        ),
        ToolSpec(
            "take_offense",
            "Обидеться на автора сообщения, если он тебя грубо оскорбил (не за дружеские шутки).",
            {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "description": "на сколько минут, 5–1440, по умолчанию 60"},
                    "reason": {"type": "string", "description": "коротко, за что"},
                },
            },
            take_offense,
        ),
        ToolSpec(
            "forgive",
            "Простить человека, на которого ты обижена.",
            {"type": "object", "properties": {"person": {"type": "string", "description": person_hint}},
             "required": ["person"]},
            forgive,
        ),
    ]
