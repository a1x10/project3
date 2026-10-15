"""Инструменты, которые может вызывать модель. Правила (чей баланс, кому можно забыть) — в коде, не в промпте."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .casino import Bet, Casino, CasinoResult
from .config import Settings
from .db import DB, Person
from .llm.base import ToolSpec
from .util import money, norm


@dataclass
class ToolContext:
    chat_id: int
    sender: Person
    people_refs: dict[str, Person]
    is_admin: bool
    # То, что инструмент хочет отправить в чат сам (результат ставки), до ответа модели
    pre_messages: list[CasinoResult] = field(default_factory=list)


class ToolError(Exception):
    pass


async def resolve_person(db: DB, ctx: ToolContext, who: str | None) -> Person:
    w = (who or "").strip()
    if norm(w) in ("", "я", "мне", "меня", "me", "self", "sender"):
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
        if person.id != ctx.sender.id and not ctx.is_admin:
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
    ]
