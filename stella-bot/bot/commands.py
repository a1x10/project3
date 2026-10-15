"""Быстрые команды без модели: казино, пауза, стикеры, админка. Мгновенно и бесплатно."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from .casino import HELP, Casino, CasinoResult, parse_bet
from .config import Settings
from .db import DB, Person
from .evolution import Evolution, EvolutionError
from .parser import Incoming
from .stickers import StickerLibrary
from .util import money, norm, phone_of, utcnow

log = logging.getLogger("stella.commands")

CHIME_LEVELS = {"выкл": "off", "тихий": "rare", "тихо": "rare", "редко": "rare", "обычный": "normal",
                "норм": "normal", "болтушка": "chatty", "активный": "chatty"}

UNPAUSE = r"(вернись|проснись|говори|можешь говорить|отомри|ты тут)"
_AMOUNT = r"(\d+(?:[.,]\d+)?\s*(?:к|k|тыс)?)"


def _parse_amount(s: str) -> int:
    s = s.replace(" ", "")
    mult = 1000 if re.search(r"(к|k|тыс)$", s) else 1
    s = re.sub(r"(к|k|тыс)$", "", s)
    return int(float(s.replace(",", ".")) * mult)


class Commands:
    def __init__(self, db: DB, casino: Casino, stickers: StickerLibrary, evo: Evolution, settings: Settings):
        self.db = db
        self.casino = casino
        self.stickers = stickers
        self.evo = evo
        self.s = settings

    async def _target(self, inc: Incoming, chat_id: int, text: str) -> Person | None:
        """Кому: @упоминание > ответ на сообщение > имя в тексте."""
        for jid in inc.mentioned:
            p = await self.db.find_person_by_jid(jid)
            if p:
                return p
        name = re.sub(r"@\d+", "", text).strip(" ,.@")
        if name:
            found = await self.db.search_people(chat_id, name, limit=2)
            if len(found) == 1:
                return found[0]
        if inc.quoted_sender:
            return await self.db.find_person_by_jid(inc.quoted_sender)
        return None

    @staticmethod
    def is_unpause(body: str) -> bool:
        return bool(re.fullmatch(UNPAUSE, norm(body).strip(" !?.")))

    async def handle(self, inc: Incoming, chat: dict[str, Any], sender: Person, body: str) -> CasinoResult | None:
        """body — текст после обращения «стелла». None — это не команда, отдать модели."""
        t = norm(body).strip(" !?.")
        chat_id = chat["id"]
        admin = self.s.is_admin(phone_of(sender.jid) or sender.phone)

        # --- пауза ---
        m = re.fullmatch(r"(помолчи|замолчи|заткнись|не пиши|отдохни|тихо|стоп)(?:\s+(\d+)\s*(?:мин\w*|м)?)?", t)
        if m:
            minutes = min(int(m.group(2) or 30), 24 * 60)
            await self.db.update_chat(chat_id, paused_until=utcnow() + timedelta(minutes=minutes))
            return CasinoResult([f"ладно-ладно, молчу {minutes} мин 🤐", "позовёте — «стелла вернись»"])
        if re.fullmatch(UNPAUSE, t):
            was_paused = bool(chat.get("paused_until") and chat["paused_until"] > utcnow())
            if was_paused or t != "ты тут":  # «ты тут?» без паузы — обычный вопрос для модели
                await self.db.update_chat(chat_id, paused_until=None)
                return CasinoResult(["я тут 😌" if was_paused else "я и не уходила)"])

        # --- режим «встревания» в разговор ---
        m = re.fullmatch(r"режим\s+(\S+)", t)
        if m and m.group(1) in CHIME_LEVELS:
            if not admin:
                return CasinoResult(["режим меняет только админ 😌"])
            await self.db.update_chat(chat_id, chime_level=CHIME_LEVELS[m.group(1)])
            return CasinoResult([f"ок, режим «{m.group(1)}»"])

        # --- стикеры ---
        m = re.fullmatch(r"запомни\s+стикер\s+(.{2,40})", t)
        if m:
            return await self._learn_sticker(inc, m.group(1))

        # --- казино ---
        if re.fullmatch(r"(казино|игры|как играть|помощь|помощь казино)", t):
            return CasinoResult(list(HELP))
        if re.fullmatch(r"(бонус|ежедневка|ежедневный бонус|дай бананов|халява)", t):
            return await self.casino.bonus(chat_id, sender)
        if re.fullmatch(r"(топ|рейтинг|богачи|лидеры|топ богачей)", t):
            return await self.casino.top(chat_id)
        m = re.fullmatch(r"(?:баланс|сколько у меня бананов|мои бананы|кошелек)(?:\s+(.+))?", t)
        if m:
            target = sender
            if m.group(1) or inc.mentioned:
                target = await self._target(inc, chat_id, body.split(None, 1)[1] if len(body.split()) > 1 else "")
                if target is None:
                    return CasinoResult(["не поняла, чей баланс"])
            bal = await self.casino.balance(chat_id, target)
            return CasinoResult([f"у {target.name} {money(bal)}"])
        bet = parse_bet(t)  # раньше перевода: «кинь монетку 100» — это ставка
        if bet:
            return await self.casino.play(chat_id, sender, bet)
        m = re.fullmatch(rf"(?:переведи|перевод|передай|скинь|кинь|отправь)\s+(?:(.+?)\s+{_AMOUNT}|{_AMOUNT}\s+(.+?)|{_AMOUNT})"
                         r"(?:\s*(?:бананов|банана|банан|🍌))?", t)
        if m:
            who = m.group(1) or m.group(4) or ""
            amount = _parse_amount(m.group(2) or m.group(3) or m.group(5))
            target = await self._target(inc, chat_id, who)
            if target is None:
                return CasinoResult(["кому переводим? отметь человека через @ или ответь на его сообщение"])
            return await self.casino.transfer(chat_id, sender, target, amount)
        m = re.fullmatch(rf"(?:начисли|выдай|забери)\s+(.+?)\s+(-?){_AMOUNT}", t)
        if m and admin:
            target = await self._target(inc, chat_id, m.group(1))
            if target is None:
                return CasinoResult(["кому?"])
            amount = _parse_amount(m.group(3)) * (-1 if m.group(2) or t.startswith("забери") else 1)
            return await self.casino.grant(chat_id, target, amount)

        return None

    async def _learn_sticker(self, inc: Incoming, mood: str) -> CasinoResult:
        if inc.quoted_kind != "sticker" or not inc.quoted_id:
            return CasinoResult(["ответь этой командой на стикер, который запомнить)"])
        row = await self.db.sticker_by_wa_id(inc.quoted_id)
        data: bytes | None = None
        if row:
            try:
                with open(row["path"], "rb") as f:
                    data = f.read()
            except OSError:
                data = None
        if data is None:
            key = {"id": inc.quoted_id, "remoteJid": inc.chat_jid, "fromMe": False}
            if inc.quoted_sender:
                key["participant"] = inc.quoted_sender
            try:
                data = await self.evo.media_base64(key, inc.quoted_message)
            except EvolutionError:
                log.warning("не смогла скачать стикер", exc_info=True)
        if not data:
            return CasinoResult(["не получилось скачать стикер 😔 перешли его ещё раз и попробуй"])
        await self.stickers.learn(data, mood, inc.quoted_id)
        return CasinoResult([f"запомнила, это стикер «{mood.strip()}» 😌"])
