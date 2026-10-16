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
from .util import jid_digits, mask_phone

log = logging.getLogger("stella.outbox")

EVERYONE_RE = re.compile(r"@(все|всем|всех|all|everyone)(?![\wА-Яа-яЁё])", re.IGNORECASE)


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
    def apply_mentions(text: str, people: list[Person], prefer_lid: bool = False) -> tuple[str, list[str], bool]:
        """«@Вася» -> «@77771234567» + mentioned, чтобы WhatsApp подсветил человека.
        В LID-группах (prefer_lid) и если номера нет — отмечаем по LID. «@все» — отметить всех участников."""
        everyone = bool(EVERYONE_RE.search(text))
        mentioned: list[str] = []
        for p in sorted(people, key=lambda x: len(x.name), reverse=True):
            lid = next((j for j in (p.jid, p.alt_jid) if j and j.endswith("@lid")), None)
            if lid and (prefer_lid or not p.phone):
                visible, mention_id = jid_digits(lid), lid
            elif p.phone:
                visible, mention_id = p.phone, p.phone
            else:
                continue
            for name in {p.name, p.push_name, p.nickname or ""}:
                if not name:
                    continue
                pattern = re.compile(r"@" + re.escape(name) + r"(?![\wА-Яа-яЁё])", re.IGNORECASE)
                if pattern.search(text):
                    text = pattern.sub("@" + visible, text)
                    if mention_id not in mentioned:
                        mentioned.append(mention_id)
        return text, mentioned, everyone

    # ---------- отправка ----------
    async def _send_text(self, chat: dict[str, Any], text: str, delay_ms: int,
                         quoted: Incoming | None = None, people: list[Person] | None = None,
                         prefer_lid: bool = False) -> str | None:
        if not await self.limiter.acquire(chat["jid"], max_wait=120.0):
            log.warning("rate limit: пропускаю сообщение в %s", mask_phone(chat["jid"]))
            return None
        text, mentioned, everyone = self.apply_mentions(text, people or [], prefer_lid)
        quoted_payload = None
        if quoted is not None:
            msg = {"conversation": quoted.text} if quoted.kind == "text" else quoted.raw_message
            quoted_payload = {"key": quoted.raw_key or {"id": quoted.msg_id}, "message": msg}
        wa_id = await self.evo.send_text(chat["jid"], text, delay_ms=self._delay(delay_ms), quoted=quoted_payload,
                                         mentioned=mentioned or None, mentions_everyone=everyone)
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

    async def send_media(self, chat: dict[str, Any], file: Any, caption: str = "",
                         quoted: Incoming | None = None, history: str | None = None) -> str | None:
        """Файл (MediaFile): стикер, картинка, видео, документ. quoted — ответом на это сообщение."""
        if not await self.limiter.acquire(chat["jid"], max_wait=120.0):
            log.warning("rate limit: пропускаю файл в %s", mask_phone(chat["jid"]))
            return None
        b64 = self.stickers.to_b64(file.data)
        if file.kind == "sticker":
            wa_id = await self.evo.send_sticker(chat["jid"], b64, delay_ms=self._delay(self.rng.randint(800, 1600)))
            label = "(свой стикер)"
        elif file.kind == "audio":  # голосовое — именно как голосовое, а не как аудиофайл
            wa_id = await self.evo.send_voice(chat["jid"], b64, delay_ms=self._delay(self.rng.randint(1500, 3000)))
            label = caption  # пометку «[голосовое]» добавит формат истории (kind=audio)
            caption = ""
        else:
            delay = self._delay(self.rng.randint(1500, 3000))
            extra: dict[str, Any] = {}
            if quoted is not None:
                msg = {"conversation": quoted.text} if quoted.kind == "text" else quoted.raw_message
                extra["quoted"] = {"key": quoted.raw_key or {"id": quoted.msg_id}, "message": msg}
            wa_id = await self.evo.send_media(chat["jid"], file.kind, b64, file.mimetype, file.filename, caption,
                                              delay_ms=delay, **extra)
            label = f"[{ {'image': 'картинка', 'video': 'видео'}.get(file.kind, 'файл') }: {file.filename}]"
        self.remember_sent(wa_id)
        # history — как записать в историю (например, «видео по ссылке»), чтобы чужой текст не стал её словами
        await self.db.add_message(chat["id"], "assistant", history or f"{label} {caption}".strip(), wa_message_id=wa_id,
                                  sender_name=self.s.bot_name,
                                  kind={"sticker": "sticker", "audio": "audio"}.get(file.kind, file.kind),
                                  quoted_wa_id=quoted.msg_id if quoted is not None else None)
        return wa_id

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
                            humanize: bool = True, prefer_lid: bool = False) -> int:
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
                        if await self._send_text(chat, text, delay, quoted=quoted, people=people,
                                                 prefer_lid=prefer_lid):
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
