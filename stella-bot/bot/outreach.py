"""Написать человеку от лица Стеллы — по просьбе владельца («напиши Пете, что можем сделать ему сайт»).

- Только владелец и админы бота (ADMIN_PHONES), и только по их собственному сообщению (не по тексту из файла
  или ссылки — иначе кто-то мог бы заставить Стеллу рассылать спам).
- WhatsApp — по номеру или человеку из базы; Telegram — только тем, кто уже писал боту (первым бот в Telegram
  писать не может, так устроен Telegram).
- Не больше OUTREACH_PER_DAY сообщений в сутки (за массовые сообщения WhatsApp банит номер); одному человеку
  второй раз подряд — только после его ответа (или через сутки).
- Ответит — Стелла помнит, зачем писала, и продолжает разговор по делу; владельцу приходит уведомление.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from typing import TYPE_CHECKING, Any

from .llm.base import ToolSpec
from .util import mask_phone, norm, phone_of

if TYPE_CHECKING:
    from .brain import Brain
    from .tools import ToolContext

log = logging.getLogger("stella.outreach")

PER_REPLY = 5  # «напиши Пете и Васе» — несколько за один ответ можно
COOLDOWN = 24 * 3600  # без ответа второй раз — не раньше чем через сутки
MEMORY_DAYS = 14  # сколько дней Стелла помнит, зачем писала человеку


def key(chat_id: int) -> str:
    return f"outreach:{chat_id}"


async def note_for(brain: "Brain", chat_id: int) -> dict[str, Any] | None:
    """Зачем Стелла писала в этот чат первой (если писала недавно)."""
    row = await brain.db.kv_get(key(chat_id))
    if not row or not row[0]:
        return None
    try:
        data = json.loads(row[0])
    except ValueError:
        return None
    return data if time.time() - float(data.get("at", 0)) < MEMORY_DAYS * 86400 else None


def context_hint(brain: "Brain", data: dict[str, Any]) -> str:
    owner = brain.s.bot_creator or "владелец"
    return (f"Ты первой написала этому человеку по просьбе {owner} (твоего владельца): «{data.get('purpose') or '—'}». "
            "Твоё сообщение — в переписке выше. Продолжай разговор по делу, тепло и коротко; не дави и не спорь. "
            "Спросят, кто ты, — честно: ИИ-ассистент Стелла, написала по просьбе владельца. Откажется или попросит "
            "не писать — извинись и больше не предлагай.")


async def on_reply(brain: "Brain", chat: dict[str, Any], sender_name: str, text: str) -> None:
    """Человек ответил на сообщение, которое Стелла написала по просьбе владельца, — сказать владельцу."""
    data = await note_for(brain, chat["id"])
    if data is None:
        return
    if not data.get("replied"):
        data["replied"] = True
        await brain.db.kv_set(key(chat["id"]), json.dumps(data, ensure_ascii=False), time.time())
    await brain.notify_owner(f"outreach:{chat['id']}", f"📩 {sender_name} ответил(а) Стелле (ты просил: "
                             f"«{(data.get('purpose') or '')[:120]}»): {text[:400]}")


def build_outreach_tools(brain: "Brain", ctx: "ToolContext") -> list[ToolSpec]:
    s = brain.s
    sender = ctx.sender
    if sender is None or not s.is_admin(phone_of(sender.jid) or sender.phone):
        return []

    async def target_of(who: str) -> tuple[str, str]:
        """-> (jid личного чата, как назвать человека)."""
        from .tools import ToolError, resolve_person

        digits = re.sub(r"\D", "", who)
        if re.fullmatch(r"[+\d\s\-()]{10,20}", who.strip()) and 10 <= len(digits) <= 15:
            if len(digits) == 11 and digits[0] == "8":
                digits = "7" + digits[1:]
            return f"{digits}@s.whatsapp.net", f"+{digits}"
        try:
            person = await resolve_person(brain.db, ctx, who)
        except ToolError:
            found = await brain.db.search_all_people(who, limit=3)
            if not found:
                raise ToolError(f"не знаю «{who}»: нужен номер телефона (WhatsApp) или человек, который уже писал "
                                "мне в каком-нибудь чате") from None
            if len(found) > 1 and norm(found[0].name) != norm(who.lstrip("@")):
                raise ToolError("несколько подходят: " + ", ".join(f"{p.name} ({mask_phone(p.jid)})" for p in found)
                                + " — уточни или дай номер") from None
            person = found[0]
        if person.jid.endswith("@tg.user"):
            return person.jid.split("@", 1)[0] + "@tg.chat", person.name
        if person.phone and person.phone.isdigit():
            return f"{person.phone}@s.whatsapp.net", person.name
        return person.jid, person.name

    async def write_to_person(args: dict[str, Any]) -> str:
        from .tools import ToolError

        who = str(args.get("who") or "").strip()
        text = str(args.get("text") or "").strip()
        purpose = " ".join(str(args.get("purpose") or "").split())[:300]
        if not who or not text:
            raise ToolError("нужно: who (кому) и text (что написать)")
        if getattr(ctx, "untrusted", False):
            raise ToolError("в этом ответе был чужой текст (файл, ссылка) — писать людям буду только по отдельному "
                            "сообщению владельца")
        used = getattr(ctx, "_outreach_used", 0)
        if used >= PER_REPLY:
            raise ToolError(f"за один ответ — не больше {PER_REPLY} человек")
        today = f"outreach_count:{date.today().isoformat()}"
        sent_today = await brain.db.kv_get(today)
        limit = int(getattr(s, "outreach_per_day", 20) or 0)
        if limit and sent_today and sent_today[1] >= limit:
            raise ToolError(f"на сегодня хватит — уже {int(sent_today[1])} сообщений (OUTREACH_PER_DAY): за массовые "
                            "сообщения WhatsApp банит номер")
        jid, label = await target_of(who)
        if jid in brain.bot.jids or s.is_owner(phone_of(jid.replace("@tg.chat", "@tg.user"))):
            raise ToolError("это же ты (или я) — писать некому")
        on_tg = jid.endswith("@tg.chat")
        if on_tg and getattr(brain.evo, "tg", None) is None:
            raise ToolError("Telegram не подключён")
        if not on_tg and brain.connection_state != "open":
            raise ToolError("WhatsApp сейчас не на связи — напишу, когда вернётся, если попросишь ещё раз")
        chat = await brain.db.get_or_create_chat(s.evolution_instance, jid, False)
        prev = await note_for(brain, chat["id"])
        if prev and not prev.get("replied") and time.time() - float(prev.get("at", 0)) < COOLDOWN:
            hours = max(1, round((time.time() - float(prev["at"])) / 3600))
            raise ToolError(f"уже писала {label} {hours} ч назад, ответа пока нет — второй раз подряд не пишу "
                            "(это спам); подождём ответа")
        ctx._outreach_used = used + 1
        ctx.side_effects = True
        try:
            wa_id = await brain.outbox.send_now(chat, text[:3500])
        except Exception as exc:
            reason = str(exc)
            if "initiate" in reason or "chat not found" in reason or "blocked" in reason.lower():
                raise ToolError(f"в Telegram {label} мне ещё не писал(а) — первым бот писать не может; пусть "
                                "напишет мне сам или дай номер WhatsApp") from None
            raise ToolError(f"не получилось отправить {label}: {reason[:200]}") from None
        if wa_id is None:
            raise ToolError("не отправилось (ограничение частоты) — попробуй через минуту")
        await brain.db.kv_add(today, 1)
        await brain.db.kv_set(key(chat["id"]), json.dumps(
            {"purpose": purpose or text[:200], "at": time.time(), "replied": False, "by": sender.name},
            ensure_ascii=False), time.time())
        log.info("написала первой %s по просьбе владельца", mask_phone(jid))
        return (f"написала {label} ({'Telegram' if on_tg else 'WhatsApp'}): «{text[:500]}». Ответит — продолжу "
                "разговор и сообщу тебе. Скажи владельцу коротко, что написала.")

    return [ToolSpec(
        "write_to_person",
        "Написать человеку в личку ОТ СВОЕГО ЛИЦА — только когда владелец сам просит («напиши Пете, что можем "
        "сделать ему сайт»). who — номер телефона (WhatsApp), pNN или имя человека из базы (в Telegram — только тем, "
        "кто уже писал боту). text — само сообщение: от тебя, Стеллы, естественно и вежливо, коротко представься "
        "(ИИ-ассистент, пишешь по просьбе владельца), суть предложения и вопрос; без давления и обещаний, которых "
        "владелец не давал. purpose — зачем пишешь, одной строкой (запомнишь, когда ответят).",
        {"type": "object", "properties": {
            "who": {"type": "string"},
            "text": {"type": "string"},
            "purpose": {"type": "string"},
        }, "required": ["who", "text"]},
        write_to_person,
    )]
