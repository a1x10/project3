"""Отправка «по-человечески»: печатает…, пауза по длине текста, короткие пузыри, стикеры, реакции, лимиты."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections import OrderedDict, deque
from typing import Any, Awaitable, Callable

from .casino import CasinoResult
from .config import Settings
from .db import DB, Person
from .evolution import Evolution, EvolutionError
from .humanize import Segment, add_typo, casualize, typing_ms
from .parser import Incoming
from .stickers import StickerLibrary
from .util import mask_phone

log = logging.getLogger("stella.outbox")


class RateLimiter:
    """Не больше N сообщений в минуту на чат (защита от бана)."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep):
        self.per_minute = per_minute
        self.clock = clock
        self.sleep = sleep
        self._events: dict[str, deque[float]] = {}

    async def acquire(self, key: str, max_wait: float = 45.0) -> bool:
        if self.per_minute <= 0:
            return True
        q = self._events.setdefault(key, deque())
        waited = 0.0
        while True:
            now = self.clock()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) < self.per_minute:
                q.append(now)
                return True
            wait = 60 - (now - q[0]) + 0.1
            if waited + wait > max_wait:
                return False
            await self.sleep(wait)
            waited += wait


class Outbox:
    def __init__(self, evo: Evolution, db: DB, stickers: StickerLibrary, settings: Settings,
                 rng: random.Random | None = None, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep):
        self.evo = evo
        self.db = db
        self.stickers = stickers
        self.s = settings
        self.rng = rng or random.Random()
        self.sleep = sleep
        self.limiter = RateLimiter(settings.rate_limit_per_min, sleep=sleep)
        self.sent_ids: OrderedDict[str, None] = OrderedDict()  # id отправленных ботом сообщений
        self.sending: dict[str, int] = {}

    def remember_sent(self, wa_id: str | None) -> None:
        if not wa_id:
            return
        self.sent_ids[wa_id] = None
        while len(self.sent_ids) > 3000:
            self.sent_ids.popitem(last=False)

    def is_ours(self, wa_id: str) -> bool:
        return wa_id in self.sent_ids

    def _delay(self, ms: int) -> int:
        return ms if self.s.typing_chars_per_sec > 0 else 0

    # ---------- упоминания ----------
    @staticmethod
    def apply_mentions(text: str, people: list[Person]) -> tuple[str, list[str]]:
        """«@Вася» -> «@77771234567» + mentioned, чтобы WhatsApp подсветил человека."""
        mentioned: list[str] = []
        for p in sorted(people, key=lambda x: len(x.name), reverse=True):
            if not p.phone:
                continue
            for name in {p.name, p.push_name, p.nickname or ""}:
                if not name:
                    continue
                pattern = re.compile(r"@" + re.escape(name) + r"(?![\wА-Яа-яЁё])", re.IGNORECASE)
                if pattern.search(text):
                    text = pattern.sub("@" + p.phone, text)
                    if p.phone not in mentioned:
                        mentioned.append(p.phone)
        return text, mentioned

    # ---------- отправка ----------
    async def _send_text(self, chat: dict[str, Any], text: str, delay_ms: int,
                         quoted: Incoming | None = None, people: list[Person] | None = None) -> str | None:
        if not await self.limiter.acquire(chat["jid"]):
            log.warning("rate limit: пропускаю сообщение в %s", mask_phone(chat["jid"]))
            return None
        text, mentioned = self.apply_mentions(text, people or [])
        quoted_payload = None
        if quoted is not None:
            msg = {"conversation": quoted.text} if quoted.kind == "text" else quoted.raw_message
            quoted_payload = {"key": quoted.raw_key or {"id": quoted.msg_id}, "message": msg}
        wa_id = await self.evo.send_text(chat["jid"], text, delay_ms=self._delay(delay_ms), quoted=quoted_payload,
                                         mentioned=mentioned or None)
        self.remember_sent(wa_id)
        await self.db.add_message(chat["id"], "assistant", text, wa_message_id=wa_id, sender_name=self.s.bot_name,
                                  quoted_wa_id=quoted.msg_id if quoted else None)
        return wa_id

    async def _send_sticker(self, chat: dict[str, Any], mood: str) -> bool:
        picked = await self.stickers.pick(chat["jid"], mood)
        if not picked:
            return False
        if not await self.limiter.acquire(chat["jid"]):
            return False
        _, data = picked
        wa_id = await self.evo.send_sticker(chat["jid"], self.stickers.to_b64(data),
                                            delay_ms=self._delay(self.rng.randint(600, 1500)))
        self.remember_sent(wa_id)
        await self.db.add_message(chat["id"], "assistant", f"({mood})", wa_message_id=wa_id,
                                  sender_name=self.s.bot_name, kind="sticker")
        return True

    async def send_poll(self, chat: dict[str, Any], question: str, options: list[str], multiple: bool) -> str | None:
        if not await self.limiter.acquire(chat["jid"]):
            return None
        wa_id = await self.evo.send_poll(chat["jid"], question, options, multiple=multiple,
                                         delay_ms=self._delay(self.rng.randint(1500, 3000)))
        self.remember_sent(wa_id)
        await self.db.add_message(chat["id"], "assistant", f"{question} (варианты: {' / '.join(options)})",
                                  wa_message_id=wa_id, sender_name=self.s.bot_name, kind="poll")
        return wa_id

    async def _react(self, target: Incoming | None, emoji: str) -> None:
        if target is None:
            return
        await self.evo.send_reaction(target.raw_key, emoji)

    async def send_segments(self, chat: dict[str, Any], segments: list[Segment], *, reply_to: Incoming | None,
                            quote_first: bool, people: list[Person], already_typing_s: float = 0.0,
                            humanize: bool = True) -> int:
        """Отправить ответ модели. Возвращает число отправленных сообщений."""
        sent = 0
        first_text = True
        protect = {self.s.bot_name} | {p.name for p in people} | {p.push_name for p in people if p.push_name}
        self.sending[chat["jid"]] = self.sending.get(chat["jid"], 0) + 1
        try:
            for seg in segments:
                try:
                    if seg.kind == "reaction":
                        await self._react(reply_to, seg.value)
                        await self.sleep(self.rng.uniform(0.3, 0.9) if self.s.typing_chars_per_sec > 0 else 0)
                    elif seg.kind == "sticker":
                        if await self._send_sticker(chat, seg.value):
                            sent += 1
                    else:
                        text = seg.value
                        correction = None
                        if humanize:
                            text = casualize(text, self.rng)
                            if not re.search(r"\d", text):
                                text, correction = add_typo(text, self.rng, self.s.typo_rate, protect)
                        delay = typing_ms(text, self.rng, self.s.typing_chars_per_sec)
                        if first_text and already_typing_s:
                            delay = max(int(delay - already_typing_s * 1000 * 0.6), 500)
                        quoted = reply_to if (first_text and quote_first) else None
                        if await self._send_text(chat, text, delay, quoted=quoted, people=people):
                            sent += 1
                        first_text = False
                        if correction and self.rng.random() < self.s.typo_fix_rate:
                            await self._send_text(chat, correction, self.rng.randint(700, 1400))
                            sent += 1
                except EvolutionError:
                    log.exception("не удалось отправить в %s", mask_phone(chat["jid"]))
        finally:
            self.sending[chat["jid"]] -= 1
        return sent

    async def send_result(self, chat: dict[str, Any], res: CasinoResult, *, reply_to: Incoming | None = None,
                          quote: bool = False) -> None:
        """Готовые строки (казино, команды) — без опечаток, но с паузами."""
        for i, line in enumerate(res.lines):
            delay = typing_ms(line, self.rng, self.s.typing_chars_per_sec * 1.5)
            if i == 1 and res.pause_after_first and self.s.typing_chars_per_sec > 0:
                delay += self.rng.randint(1200, 2500)  # «крутится…»
            try:
                await self._send_text(chat, line, delay, quoted=reply_to if (i == 0 and quote) else None)
            except EvolutionError:
                log.exception("не удалось отправить строку")
        if res.mood:
            try:
                await self._send_sticker(chat, res.mood)
            except EvolutionError:
                log.exception("не удалось отправить стикер")
