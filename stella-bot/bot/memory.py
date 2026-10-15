"""Фоновая память: раз в N сообщений дешёвая модель выжимает из переписки факты о людях и о чате."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from .config import Settings
from .db import DB, Person
from .llm.base import LLM, LLMError
from .persona import format_transcript

log = logging.getLogger("stella.memory")

EXTRACT_SYSTEM = """Ты — модуль памяти чат-бота. По куску переписки выпиши новые устойчивые факты о людях: имя и как любит, чтобы называли, возраст, город, учёба/работа, увлечения, вкусы, питомцы, отношения, планы, важные события, характерные шутки.
Не записывай: разовые реплики, настроение на минуту, то, что уже есть в списке известного, догадки. Только то, что человек сказал о себе или что прямо сказали о нём.
Номера телефонов, адреса, пароли и прочие чувствительные данные не записывай.
Ответь ТОЛЬКО JSON без пояснений:
{"people": [{"ref": "p12", "facts": ["коротко от третьего лица"], "nickname": null}], "chat": ["заметка о самом чате, если есть"]}
Если ничего нового — {"people": [], "chat": []}"""


def parse_json_block(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class Memory:
    def __init__(self, db: DB, llm: LLM, settings: Settings, on_cost=None):
        self.db = db
        self.llm = llm
        self.s = settings
        self.on_cost = on_cost
        self._running: set[int] = set()

    async def note_message(self, chat_id: int) -> None:
        """Вызывается на каждое входящее сообщение; запускает выжимку, когда накопилось."""
        if self.s.memory_extract_every <= 0:
            return
        count = await self.db.bump_extract_counter(chat_id)
        if count >= self.s.memory_extract_every and chat_id not in self._running:
            self._running.add(chat_id)
            asyncio.create_task(self._run(chat_id))

    async def _run(self, chat_id: int) -> None:
        try:
            await self.extract(chat_id)
        except Exception:
            log.exception("memory extraction failed")
        finally:
            self._running.discard(chat_id)

    async def extract(self, chat_id: int) -> int:
        await self.db.update_chat(chat_id, msgs_since_extract=0)
        rows = await self.db.recent_messages(chat_id, max(self.s.memory_extract_every * 2, 40))
        if not any(r["role"] == "user" for r in rows):
            return 0
        person_ids = {r["person_id"] for r in rows if r.get("person_id")}
        people: dict[int, Person] = {}
        for pid in person_ids:
            p = await self.db.get_person(pid)
            if p:
                people[pid] = p
        known_lines = []
        for p in people.values():
            facts = await self.db.get_facts(p.id, chat_id, 30, self.s.memory_share_across_chats)
            known_lines.append(f"- {p.name} [{p.ref}]: {'; '.join(facts) if facts else '—'}")
        chat = await self.db.get_chat(chat_id)
        transcript = format_transcript(rows, people, self.s.bot_name, self.s.timezone, set(), {})
        prompt = (
            "Уже известно:\n" + "\n".join(known_lines)
            + f"\n\nЗаметки о чате:\n{chat.get('notes') or '—'}"
            + "\n\nПереписка:\n" + "\n".join(transcript)
        )
        try:
            reply = await self.llm.ask(system=EXTRACT_SYSTEM, prompt=prompt, model=self.s.llm_memory_model,
                                       max_turns=1)
        except LLMError as exc:
            log.warning("memory: модель недоступна: %s", exc)
            return 0
        if self.on_cost:
            await self.on_cost(reply.cost_usd)
        data = parse_json_block(reply.text)
        if not data:
            return 0
        refs = {p.ref: p for p in people.values()}
        added = 0
        for item in data.get("people") or []:
            if not isinstance(item, dict):
                continue
            p = refs.get(str(item.get("ref", "")).strip("[] "))
            if not p:
                continue
            for fact in item.get("facts") or []:
                if isinstance(fact, str) and await self.db.add_fact(p.id, chat_id, fact, "auto",
                                                                   self.s.memory_max_facts):
                    added += 1
            nick = item.get("nickname")
            if isinstance(nick, str) and nick.strip() and not p.nickname:
                await self.db.set_nickname(p.id, nick.strip()[:60])
        chat_notes = [n for n in (data.get("chat") or []) if isinstance(n, str) and n.strip()]
        if chat_notes:
            old = [n for n in (chat.get("notes") or "").split("\n") if n.strip()]
            merged = old + [f"- {n.strip()[:200]}" for n in chat_notes if f"- {n.strip()[:200]}" not in old]
            await self.db.update_chat(chat_id, notes="\n".join(merged[-25:]))
        log.info("memory: чат %s, новых фактов %d", chat_id, added)
        return added
