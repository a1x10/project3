"""Быстрые команды без модели: казино, пауза, стикеры, админка. Мгновенно и бесплатно."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any, Awaitable, Callable

from .casino import HELP, Casino, CasinoResult, parse_bet
from .config import Settings
from .db import DB, Person
from .evolution import Evolution, EvolutionError
from .parser import Incoming
from .stickers import StickerLibrary
from .util import mask_phone, money, norm, phone_of, utcnow

log = logging.getLogger("stella.commands")

CHIME_LEVELS = {"выкл": "off", "тихий": "rare", "тихо": "rare", "редко": "rare", "обычный": "normal",
                "норм": "normal", "болтушка": "chatty", "активный": "chatty"}

UNPAUSE = r"(вернись|проснись|говори|можешь говорить|отомри|ты тут)"
# в личке на паузе хватит и «ау», и «стелла вернись пожалуйста»
UNPAUSE_LENIENT = r"(^|[^а-яё])(вернись|проснись|говори|отомри|ты тут|ты здесь|ау)([^а-яё]|$)"
_AMOUNT = r"(\d+(?:[.,]\d+)?\s*(?:к|k|тыс)?)"


def _parse_amount(s: str) -> int:
    s = s.replace(" ", "")
    mult = 1000 if re.search(r"(к|k|тыс)$", s) else 1
    s = re.sub(r"(к|k|тыс)$", "", s)
    return int(float(s.replace(",", ".")) * mult)


class Commands:
    def __init__(self, db: DB, casino: Casino, stickers: StickerLibrary, evo: Evolution, settings: Settings,
                 group_admin: Callable[[dict[str, Any], Person], Awaitable[bool]] | None = None,
                 panel_unlock: Callable[[], Awaitable[None]] | None = None,
                 giveaway_links: Callable[[], Awaitable[list[str] | None]] | None = None):
        self.group_admin = group_admin  # админ группы в WhatsApp (проверяет Brain по списку участников)
        self.panel_unlock = panel_unlock
        self.giveaway_links = giveaway_links
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
    def is_unpause(body: str, lenient: bool = False) -> bool:
        t = norm(body).strip(" !?.")
        return bool(re.fullmatch(UNPAUSE, t) or (lenient and re.search(UNPAUSE_LENIENT, t)))

    async def handle(self, inc: Incoming, chat: dict[str, Any], sender: Person, body: str,
                     named: bool = True) -> CasinoResult | None:
        """body — текст после обращения «стелла». None — это не команда, отдать модели.
        named — к ней обратились по имени (в личке без имени «стоп» — просто слово, а не пауза)."""
        t = norm(body).strip(" !?.")
        chat_id = chat["id"]
        admin = self.s.is_admin(phone_of(sender.jid) or sender.phone)

        # --- пауза ---
        m = re.fullmatch(r"(помолчи|замолчи|заткнись|не пиши|отдохни|тихо|стоп)(?:\s+(\d+)\s*(?:мин\w*|м)?)?", t)
        if m and chat["is_group"] and not await self._is_admin(chat, sender, admin):
            return None  # в группе выключить её для всех могут только админы; остальным она ответит сама
        if m and not chat["is_group"] and not named:
            return None  # «стоп» в личке без «стелла» — обычное сообщение
        if m:
            minutes = min(int(m.group(2) or 30), 24 * 60)
            await self.db.update_chat(chat_id, paused_until=utcnow() + timedelta(minutes=minutes))
            return CasinoResult([f"хорошо, помолчу {minutes} мин", "если понадоблюсь, напишите «стелла вернись»"])
        strict = bool(re.fullmatch(UNPAUSE, t))
        if strict or (not chat["is_group"] and self.is_unpause(t, lenient=True)):
            was_paused = bool(chat.get("paused_until") and chat["paused_until"] > utcnow())
            # «ты тут?» без паузы — обычный вопрос для модели
            if was_paused or (strict and t != "ты тут"):
                await self.db.update_chat(chat_id, paused_until=None)
                return CasinoResult(["я снова здесь" if was_paused else "я здесь"])

        # --- панель: снять блокировку подбора паролей (только владелец/админы из .env, только в личке) ---
        if re.fullmatch(r"разблокируй панель", t) and self.panel_unlock is not None:
            if not admin or chat["is_group"]:
                return None
            await self.panel_unlock()
            return CasinoResult(["готово, вход в панель снова открыт"])

        # --- розыгрыш: ссылка на страницу и одноразовая — в админку (владелец/админы из .env, только в личке) ---
        if re.fullmatch(r"/?(розыгрыш|giveaway)( админка| ссылка)?", t) and self.giveaway_links is not None:
            if chat["is_group"]:
                return None
            if not admin:
                if not t.startswith("/"):
                    return None  # «розыгрыш» словом — обычный разговор
                # команду набрали, но владельцем бот этого человека не считает — подскажем, что вписать в .env
                me = phone_of(sender.jid) or sender.phone or ""
                hint = f"TELEGRAM_OWNER_ID={me[2:]}" if me.startswith("tg") else f"OWNER_PHONE={me} (или ADMIN_PHONES)"
                log.info("«/розыгрыш» не от владельца/админа (%s)", mask_phone(sender.jid or me))
                return CasinoResult(["это команда владельца бота",
                                     f"если владелец — ты, впиши на сервере в .env {hint} и перезапусти бота"])
            lines = await self.giveaway_links()
            if lines is None:
                return CasinoResult(["розыгрыш выключен (GIVEAWAY_ENABLED=false)"])
            res = CasinoResult(lines)
            res.follow_up = False
            return res

        # --- режим «встревания» в разговор ---
        m = re.fullmatch(r"режим\s+(\S+)", t)
        if m and m.group(1) in CHIME_LEVELS:
            if not await self._is_admin(chat, sender, admin):
                return CasinoResult(["режим может поменять только админ"])
            await self.db.update_chat(chat_id, chime_level=CHIME_LEVELS[m.group(1)])
            return CasinoResult([f"ок, режим «{m.group(1)}»"])

        # --- удалить сообщение (ответом на него) ---
        if re.fullmatch(r"(удали|удаляй|снеси)( это| его| сообщение| это сообщение)?( пожалуйста| пж| плиз| плз)?", t):
            return await self._delete_quoted(inc, chat, admin or await self._is_admin(chat, sender, admin))

        # --- стикеры ---
        m = re.fullmatch(r"запомни\s+стикер\s+(.{2,40})", t)
        if m:
            return await self._learn_sticker(inc, m.group(1))

        # --- казино ---
        if re.fullmatch(r"(казино|игры|как играть|помощь|помощь казино)", t):
            return CasinoResult(list(HELP))
        if re.fullmatch(r"(бонус|ежедневка|ежедневный бонус|дай бананов|халява)", t):
            return self._no_follow_up(await self.casino.bonus(chat_id, sender))
        if re.fullmatch(r"(топ|рейтинг|богачи|лидеры|топ богачей)", t):
            return self._no_follow_up(await self.casino.top(chat_id))
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
            return self._no_follow_up(await self.casino.play(chat_id, sender, bet))
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

    @staticmethod
    def _no_follow_up(res: CasinoResult) -> CasinoResult:
        """После ставки/бонуса/топа следующая болтовня человека — не обязательно ей (не тратим модель)."""
        res.follow_up = False
        return res

    async def _is_admin(self, chat: dict[str, Any], sender: Person, admin: bool) -> bool:
        if admin:
            return True
        if self.group_admin is None or not chat.get("is_group"):
            return False
        try:
            return await self.group_admin(chat, sender)
        except Exception:
            log.warning("не удалось проверить админов группы", exc_info=True)
            return False

    async def _delete_quoted(self, inc: Incoming, chat: dict[str, Any], admin: bool) -> CasinoResult:
        """Своё сообщение Стелла удаляет по просьбе любого, чужое — только по просьбе админа."""
        if not inc.quoted_id:
            return CasinoResult(["ответь этой командой на сообщение, которое удалить"])
        mine = await self.db.is_stella_message(inc.quoted_id)
        from_me = mine or await self.db.is_bot_message(inc.quoted_id)  # набранное владельцем с её телефона
        if not mine and not admin:
            return CasinoResult(["чужие сообщения я удаляю только по просьбе админа"])
        key: dict[str, Any] = {"id": inc.quoted_id, "remoteJid": inc.chat_jid, "fromMe": from_me}
        if not from_me and inc.quoted_sender:
            key["participant"] = inc.quoted_sender
        try:
            await self.evo.delete_message(key)
        except EvolutionError:
            log.warning("не удалось удалить сообщение", exc_info=True)
            return CasinoResult(["не получилось удалить" + ("" if mine else ", для этого меня нужно сделать админом группы")])
        await self.db.mark_deleted(chat["id"], inc.quoted_id)
        return CasinoResult(["удалила"])

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
            return CasinoResult(["не получилось сохранить стикер, перешли его ещё раз"])
        await self.stickers.learn(data, mood, inc.quoted_id)
        return CasinoResult([f"запомнила, это стикер «{mood.strip()}»"])
