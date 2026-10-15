"""Мозг Стеллы: принимает события, решает — отвечать ли, собирает контекст, зовёт модель, отправляет."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Awaitable, Callable

import httpx

from .addressing import AMBIENT, CONTINUE, DIRECT, BotIdentity, classify, looks_like_open_question, name_stems, strip_name_prefix
from .casino import Casino
from .commands import Commands
from .config import Settings
from .db import DB, OWNER_SENDER, Person, chat_paused
from .evolution import Evolution, EvolutionError
from .humanize import Segment, parse_reply
from .llm.base import LLM, LLMError, LLMRefusal
from .memory import Memory
from .outbox import Outbox
from .parser import Incoming, event_name, parse_upsert
from .persona import (
    MODE_HINTS,
    OFFENDED_HINT,
    PromptContext,
    build_prompt,
    current_mood,
    format_transcript,
    system_prompt,
)
from .stickers import StickerLibrary
from .tools import ToolContext, build_tools
from .util import jid_digits, mask_phone, norm, phone_of, utcnow

log = logging.getLogger("stella.brain")

# off / rare / normal / chatty: (шанс вписаться, пауза между попытками, сколько новых сообщений нужно)
CHIME = {
    "off": (0.0, 0, 0),
    "rare": (0.15, 600, 6),
    "normal": (0.3, 240, 4),
    "chatty": (0.55, 90, 3),
}
AMBIENT_QUIET = (8.0, 15.0)  # ждём, пока в чате затихнет
AMBIENT_MAX_WAIT = 45.0

VOICE_REPLIES = [
    "голосовые я пока не слушаю, напиши, пожалуйста, текстом",
    "не могу послушать голосовое. напишешь текстом?",
]
FALLBACK_REPLIES = [
    "минутку, сейчас отвечу",
    "подожди немного, сейчас вернусь",
]
REFUSAL_REPLIES = ["об этом я говорить не буду", "давай лучше о чём-нибудь другом"]


class ChatRunner:
    """Очередь одного чата: собираем пачку сообщений, ждём паузу, отвечаем одним заходом."""

    def __init__(self, brain: "Brain", chat_jid: str):
        self.brain = brain
        self.chat_jid = chat_jid
        self.pending: list[tuple[Incoming, str]] = []
        self.deadline = 0.0
        self.first_at: float | None = None
        self.wake = asyncio.Event()
        self.task: asyncio.Task | None = None

    def feed(self, inc: Incoming, level: str) -> None:
        s = self.brain.s
        rng = self.brain.rng
        now = time.monotonic()
        self.pending.append((inc, level))
        if self.first_at is None:
            self.first_at = now
        if any(lvl in (DIRECT, CONTINUE) for _, lvl in self.pending):
            target = now + rng.uniform(s.batch_window_min, s.batch_window_max)
            cap = self.first_at + s.batch_max_wait
        else:
            target = now + rng.uniform(*self.brain.ambient_quiet)
            cap = self.first_at + AMBIENT_MAX_WAIT
        self.deadline = min(target, cap)
        self.wake.set()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while self.pending:
            while True:
                self.wake.clear()
                delay = self.deadline - time.monotonic()
                if delay <= 0:
                    break
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    break
            batch, self.pending = self.pending, []
            self.first_at = None
            try:
                await self.brain.respond(self.chat_jid, batch)
            except Exception:
                log.exception("ошибка при ответе в %s", mask_phone(self.chat_jid))


class _ChatActions:
    """Что Стелла может сделать в чате сама: опрос, удалить своё сообщение."""

    def __init__(self, brain: "Brain", chat: dict[str, Any]):
        self.brain = brain
        self.chat = chat

    async def send_poll(self, question: str, options: list[str], multiple: bool) -> None:
        try:
            await self.brain.outbox.send_poll(self.chat, question, options, multiple)
        except EvolutionError:
            log.warning("не удалось отправить опрос", exc_info=True)

    async def delete_mine(self, *, quoted_id: str | None = None, text: str | None = None) -> list[str]:
        """Удалить своё: процитированное сообщение, сообщение с этим текстом или весь последний ответ.
        Возвращает тексты удалённого."""
        db = self.brain.db
        chat_id = self.chat["id"]
        if quoted_id and await db.is_stella_message(quoted_id):
            row = await db.get_message_by_wa_id(chat_id, quoted_id)
            targets = [row] if row and row.get("kind") != "deleted" else []
        elif text and text.strip():
            needle = norm(text)
            targets = [r for r in await db.recent_stella_messages(chat_id) if needle in norm(r.get("text") or "")][:1]
        else:
            targets = await db.last_stella_reply(chat_id)
        deleted = []
        for row in targets:
            try:
                await self.brain.evo.delete_message({"id": row["wa_message_id"], "remoteJid": self.chat["jid"],
                                                     "fromMe": True})
            except EvolutionError:
                log.warning("не удалось удалить своё сообщение", exc_info=True)
                continue
            await db.mark_deleted(chat_id, row["wa_message_id"])
            deleted.append(row.get("text") or f"[{row.get('kind')}]")
        return deleted


class Brain:
    def __init__(self, settings: Settings, db: DB, evo: Evolution, llm: LLM, *,
                 rng: random.Random | None = None, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep):
        self.s = settings
        self.db = db
        self.evo = evo
        self.llm = llm
        self.rng = rng or random.Random()
        self.sleep = sleep
        self.stickers = StickerLibrary(db, settings.stickers_dir, rng=self.rng)
        self.casino = Casino(db, settings.casino_start_balance, settings.casino_bonus, settings.casino_bonus_hours,
                             settings.casino_min_bet)
        self.memory = Memory(db, llm, settings, on_cost=self.track_cost)
        self.outbox = Outbox(evo, db, self.stickers, settings, rng=self.rng, sleep=sleep)
        self.commands = Commands(db, self.casino, self.stickers, evo, settings)
        self.system = system_prompt(settings)
        self.stems = name_stems(settings.bot_name)
        self.bot = BotIdentity(set())
        self.ambient_quiet = AMBIENT_QUIET
        self.runners: dict[str, ChatRunner] = {}
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.talking: dict[str, dict[str, float]] = {}  # чат -> собеседник -> когда Стелла ему отвечала
        self.connection_state = "unknown"
        self.disconnected_at: float | None = None
        self._last_alert: dict[str, float] = {}
        self.tasks: set[asyncio.Task] = set()
        self._spend_day = date.today()
        self._today_spend = 0.0
        self._background: list[asyncio.Task] = []
        self.open_floor: dict[str, float] = {}  # чат -> до какого момента ответы считаются ответами ей

    # ---------- запуск ----------
    async def start(self) -> None:
        await self.db.init()
        await self.stickers.init()
        await self.refresh_spend()
        saved = await self.db.kv_get("bot_jids")
        if saved and saved[0]:
            self.bot.jids |= set(json.loads(saved[0]))
        if self.s.evolution_auto_setup:
            await self.ensure_instance()
        if self.s.initiative_per_week > 0:
            self._background.append(asyncio.create_task(self._initiative_loop()))

    async def ensure_instance(self) -> None:
        """Создать инстанс (если нет) и прописать вебхук. Ошибки не валят бота — Evolution может ещё стартовать."""
        for attempt in range(30):
            try:
                if await self.evo.find_own_instance() is None:
                    await self.evo.create_instance()
                    log.info("создан инстанс %s — подключите номер: python -m bot.setup --number ...",
                             self.s.evolution_instance)
                await self.evo.set_webhook(self.s.webhook_url, self.s.webhook_secret)
                inst = await self.evo.find_own_instance() or {}
                if inst.get("ownerJid"):
                    await self.add_bot_jid(inst["ownerJid"])
                if inst.get("connectionStatus"):
                    self.connection_state = inst["connectionStatus"]
                log.info("вебхук Evolution настроен, WhatsApp: %s", self.connection_state)
                return
            except EvolutionError as exc:
                if exc.status == 401:
                    log.error("Evolution не пускает: EVOLUTION_API_KEY в .env не совпадает с ключом Evolution")
                else:
                    log.warning("Evolution пока недоступен (%s), попытка %d", exc, attempt + 1)
                await self.sleep(min(5 * (attempt + 1), 30))
        log.error("не удалось настроить Evolution — проверьте docker compose logs evolution")

    async def add_bot_jid(self, jid: str) -> None:
        if not jid or jid in self.bot.jids:
            return
        self.bot.jids.add(jid)
        await self.db.kv_set("bot_jids", json.dumps(sorted(self.bot.jids)))

    def spawn(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    # ---------- события ----------
    async def handle_payload(self, payload: dict[str, Any]) -> None:
        event = event_name(payload)
        if event == "messages.upsert":
            inc = parse_upsert(payload)
            if inc:
                await self.on_message(inc)
        elif event == "connection.update":
            await self.on_connection(payload.get("data") or {})

    def _seen(self, key: str) -> bool:
        if key in self.seen:
            return True
        self.seen[key] = None
        while len(self.seen) > 5000:
            self.seen.popitem(last=False)
        return False

    def _allowed(self, inc: Incoming) -> bool:
        if inc.is_group:
            return not self.s.allowed_groups or inc.chat_jid in self.s.allowed_groups
        return self.s.allow_dms

    async def on_message(self, inc: Incoming) -> None:
        if self._seen(f"{inc.chat_jid}|{inc.msg_id}"):
            return
        if inc.bot_jid:
            await self.add_bot_jid(inc.bot_jid)
        if not self._allowed(inc):
            return
        if inc.from_me:
            if inc.is_group:  # в LID-группах так узнаём собственный LID бота (для @упоминаний)
                for k in ("participant", "participantAlt"):
                    if inc.raw_key.get(k):
                        await self.add_bot_jid(inc.raw_key[k])
            await self._on_own_message(inc)
            return

        chat = await self.db.get_or_create_chat(inc.instance or self.s.evolution_instance, inc.chat_jid, inc.is_group)
        if inc.is_group and not chat.get("title"):
            self.spawn(self._fetch_title(chat["id"], inc.chat_jid))
        sender = await self.db.upsert_person(inc.sender_jid, inc.push_name, phone_of(inc.sender_jid), inc.sender_alt)
        await self.db.touch_member(chat["id"], sender.id)

        text = await self._readable_mentions(inc)
        quoted_is_bot = False
        if inc.quoted_id:
            quoted_is_bot = self.outbox.is_ours(inc.quoted_id) or await self.db.is_bot_message(inc.quoted_id)
            if quoted_is_bot and inc.quoted_sender:
                await self.add_bot_jid(inc.quoted_sender)  # так узнаём LID самого бота
            elif inc.quoted_sender and inc.quoted_sender not in self.bot.jids:
                qp = await self.db.upsert_person(inc.quoted_sender, "", phone_of(inc.quoted_sender))
                await self.db.touch_member(chat["id"], qp.id)
        msg_id = await self.db.add_message(chat["id"], "user", text, wa_message_id=inc.msg_id, person_id=sender.id,
                                           sender_name=sender.name, kind=inc.kind, quoted_wa_id=inc.quoted_id)
        if msg_id is None:
            return  # дубль
        if inc.kind == "sticker" and self.s.sticker_collect:
            self.spawn(self._collect_sticker(inc))
        if not self.over_budget():
            await self.memory.note_message(chat["id"])

        addressed, body = strip_name_prefix(text, self.stems)
        if inc.is_dm:
            addressed = True
        if chat_paused(chat):
            if addressed and inc.kind == "text" and self.commands.is_unpause(body):
                res = await self.commands.handle(inc, chat, sender, body)
                if res:
                    self.spawn(self._send_command_result(chat, inc, res))
            return
        if addressed and inc.kind == "text":
            res = await self.commands.handle(inc, chat, sender, body)
            if res is not None:
                self.spawn(self._send_command_result(chat, inc, res))
                return

        now_m = time.monotonic()
        talking = now_m - self.talking.get(inc.chat_jid, {}).get(inc.sender_jid, -1e9) < self.s.continue_window
        talking = talking or now_m < self.open_floor.get(inc.chat_jid, 0)  # отвечают на её вопрос
        level = classify(inc, stems=self.stems, bot=self.bot, quoted_is_bot=quoted_is_bot, talking_with_sender=talking)
        if inc.kind == "audio":
            if level == DIRECT:
                self.spawn(self._send_command_result(chat, inc, self._canned(VOICE_REPLIES)))
            return
        if level == AMBIENT and self.over_budget():
            return
        self.runners.setdefault(inc.chat_jid, ChatRunner(self, inc.chat_jid)).feed(inc, level)

    async def _on_own_message(self, inc: Incoming) -> None:
        """fromMe: либо наше же сообщение (эхо), либо владелец сам пишет с телефона -> пауза в этом чате."""
        if self.outbox.is_ours(inc.msg_id):
            return
        await self.sleep(3)  # ответ sendText мог ещё не вернуться
        if self.outbox.is_ours(inc.msg_id) or await self.db.is_bot_message(inc.msg_id):
            return
        chat = await self.db.get_or_create_chat(inc.instance or self.s.evolution_instance, inc.chat_jid, inc.is_group)
        await self.db.add_message(chat["id"], "assistant", inc.text, wa_message_id=inc.msg_id,
                                  sender_name=OWNER_SENDER, kind=inc.kind, quoted_wa_id=inc.quoted_id)
        if self.s.owner_takeover_minutes > 0:
            await self.db.update_chat(chat["id"], paused_until=utcnow() + timedelta(minutes=self.s.owner_takeover_minutes),
                                      last_bot_at=utcnow())
            log.info("владелец пишет сам в %s — пауза %d мин", mask_phone(inc.chat_jid), self.s.owner_takeover_minutes)

    async def _readable_mentions(self, inc: Incoming) -> str:
        """«@77771234567» в тексте -> «@Вася», чтобы модель понимала, о ком речь."""
        text = inc.text
        for jid in inc.mentioned:
            digits = jid_digits(jid)
            if jid in self.bot.jids or digits in self.bot.digits():
                text = text.replace(f"@{digits}", f"@{self.s.bot_name}")
                continue
            p = await self.db.find_person_by_jid(jid)
            if p is None and jid.endswith("@s.whatsapp.net"):
                p = await self.db.upsert_person(jid, "", digits)
            if p:
                text = text.replace(f"@{digits}", f"@{p.name}")
        return text

    def _canned(self, options: list[str]):
        from .casino import CasinoResult

        return CasinoResult([self.rng.choice(options)])

    async def _send_command_result(self, chat: dict[str, Any], inc: Incoming, res) -> None:
        await self.sleep(self.rng.uniform(self.s.reply_delay_min * 0.5, self.s.reply_delay_max * 0.6))
        try:
            await self.evo.mark_read([inc.raw_key])
        except EvolutionError:
            pass
        await self.outbox.send_result(chat, res, reply_to=inc, quote=chat["is_group"] and self._others_after(inc))
        await self.db.update_chat(chat["id"], last_bot_at=utcnow())

    def _others_after(self, inc: Incoming) -> bool:
        runner = self.runners.get(inc.chat_jid)
        return bool(runner and any(i.sender_jid != inc.sender_jid for i, _ in runner.pending))

    async def _fetch_title(self, chat_id: int, jid: str) -> None:
        try:
            subject = await self.evo.group_subject(jid)
            if subject:
                await self.db.update_chat(chat_id, title=subject)
        except EvolutionError:
            pass

    async def _collect_sticker(self, inc: Incoming) -> None:
        try:
            data = await self.evo.media_base64(inc.raw_key, inc.raw_message)
            if data:
                await self.stickers.collect(data, inc.msg_id, self.s.sticker_collect_limit)
        except Exception:
            log.debug("не удалось сохранить стикер", exc_info=True)

    # ---------- ответ ----------
    async def _ambient_ok(self, chat: dict[str, Any], batch: list[tuple[Incoming, str]]) -> bool:
        level = chat.get("chime_level") or self.s.chime_default
        chance, cooldown, min_new = CHIME.get(level, CHIME["normal"])
        if chance <= 0:
            return False
        now = utcnow()
        if chat.get("last_eval_at") and now - chat["last_eval_at"] < timedelta(seconds=cooldown):
            return False
        recent = await self.db.recent_messages(chat["id"], 20)
        if not recent or recent[-1]["role"] == "assistant":
            return False
        since_bot = 0
        for r in reversed(recent):
            if r["role"] == "assistant":
                break
            since_bot += 1
        if since_bot < min_new:
            return False
        if any(looks_like_open_question(i.text) for i, _ in batch):
            chance = min(chance * 1.8, 0.9)
        await self.db.update_chat(chat["id"], last_eval_at=now)
        return self.rng.random() < chance

    async def respond(self, chat_jid: str, batch: list[tuple[Incoming, str]]) -> None:
        if not batch:
            return
        inc0 = batch[-1][0]
        chat = await self.db.get_chat_by_jid(inc0.instance or self.s.evolution_instance, chat_jid)
        if chat is None or chat_paused(chat):
            return
        levels = {lvl for _, lvl in batch}
        mode = DIRECT if DIRECT in levels else CONTINUE if CONTINUE in levels else AMBIENT
        if mode == AMBIENT and not await self._ambient_ok(chat, batch):
            return
        if mode == CONTINUE and self.over_budget():
            return
        starred = [i for i, lvl in batch if lvl == mode] or [batch[-1][0]]
        target = starred[-1]
        sender = await self.db.find_person_by_jid(target.sender_jid)
        if sender is None:
            return

        grudges = await self.db.active_grudges(chat["id"])
        extra_hint = ""
        if sender.id in grudges:
            reason = grudges[sender.id]
            extra_hint = OFFENDED_HINT.format(name=sender.name, reason=f" ({reason})" if reason else "")
        prompt, people = await self._build_prompt(chat, batch, starred, mode, grudges=grudges, extra_hint=extra_hint)
        tool_ctx = ToolContext(chat_id=chat["id"], sender=sender, people_refs={p.ref: p for p in people},
                               is_admin=self.s.is_admin(phone_of(sender.jid) or sender.phone),
                               actions=_ChatActions(self, chat), quoted_wa_id=target.quoted_id)
        tools = build_tools(self.db, self.casino, self.s, tool_ctx)

        started = time.monotonic()
        llm_task = asyncio.create_task(
            self.llm.ask(system=self.system, prompt=prompt, tools=tools, max_turns=self.s.llm_max_turns)
        )
        typing_task = None
        if mode in (DIRECT, CONTINUE):
            await self._sleep_unless(llm_task, self.rng.uniform(self.s.reply_delay_min, self.s.reply_delay_max))
            try:
                await self.evo.mark_read([i.raw_key for i, _ in batch])
            except EvolutionError:
                pass
            if mode == DIRECT:
                typing_task = asyncio.create_task(self._typing_until(chat_jid, llm_task))
        try:
            reply = await llm_task
        except LLMRefusal:
            if typing_task:
                typing_task.cancel()
            if mode == DIRECT:
                await self.outbox.send_result(chat, self._canned(REFUSAL_REPLIES))
            return
        except LLMError as exc:
            if typing_task:
                typing_task.cancel()
            log.error("модель недоступна: %s", exc)
            if mode == DIRECT:
                await self.outbox.send_result(chat, self._canned(FALLBACK_REPLIES))
                await self.notify_owner("llm", f"⚠️ Стелла: модель не ответила ({exc}). Чат {mask_phone(chat_jid)}")
            return
        finally:
            if typing_task:
                typing_task.cancel()
        await self.track_cost(reply.cost_usd)

        typed_for = max(0.0, time.monotonic() - started - self.s.reply_delay_max)
        for res in tool_ctx.pre_messages:
            await self.outbox.send_result(chat, res, reply_to=target)
        segments = parse_reply(reply.text, self.s.max_bubbles)
        sent = 0
        if segments:
            quote_first = chat["is_group"] and await self._newer_messages_exist(chat["id"], target)
            sent = await self.outbox.send_segments(chat, segments, reply_to=target, quote_first=quote_first,
                                                   people=people, already_typing_s=typed_for)
        elif not tool_ctx.after:
            log.info("%s: молчит (%s)", mask_phone(chat_jid), mode)
            return
        for action in tool_ctx.after:  # опрос — после её сообщения
            await action()
            sent += 1
        if sent or any(s.kind == "reaction" for s in segments):
            now = time.monotonic()
            talk = self.talking.setdefault(chat_jid, {})
            for i in starred:
                talk[i.sender_jid] = now
            await self.db.update_chat(chat["id"], last_bot_at=utcnow(), last_eval_at=utcnow())

    async def _sleep_unless(self, task: asyncio.Task, seconds: float) -> None:
        if seconds > 0:
            await asyncio.wait([task], timeout=seconds)

    async def _typing_until(self, chat_jid: str, task: asyncio.Task) -> None:
        try:
            while not task.done():
                await self.evo.send_presence(chat_jid, "composing", 4000)
        except (EvolutionError, asyncio.CancelledError):
            pass

    async def _newer_messages_exist(self, chat_id: int, target: Incoming) -> bool:
        rows = await self.db.recent_messages(chat_id, 6)
        ids = [r["wa_message_id"] for r in rows]
        return target.msg_id in ids and ids[-1] != target.msg_id

    async def _build_prompt(self, chat: dict[str, Any], batch: list[tuple[Incoming, str]], starred: list[Incoming],
                            mode: str, *, grudges: dict[int, str] | None = None,
                            extra_hint: str = "") -> tuple[str, list[Person]]:
        rows = await self.db.recent_messages(chat["id"], self.s.history_window)
        people_by_id: dict[int, Person] = {}
        order: list[int] = []

        async def add(pid: int | None) -> None:
            if pid and pid not in people_by_id:
                p = await self.db.get_person(pid)
                if p:
                    people_by_id[pid] = p
                    order.append(pid)

        # Сначала те, к кому сейчас отвечаем, и о ком спрашивают (ответы/упоминания)
        for inc in reversed(starred):
            p = await self.db.find_person_by_jid(inc.sender_jid)
            await add(p.id if p else None)
            for jid in ([inc.quoted_sender] if inc.quoted_sender else []) + inc.mentioned:
                if jid in self.bot.jids:
                    continue
                q = await self.db.find_person_by_jid(jid)
                await add(q.id if q else None)
        for r in reversed(rows):
            await add(r.get("person_id"))

        quoted_lookup: dict[str, dict[str, Any]] = {}
        by_wa = {r["wa_message_id"]: r for r in rows if r.get("wa_message_id")}
        for r in rows:
            qid = r.get("quoted_wa_id")
            if not qid or qid in quoted_lookup:
                continue
            q = by_wa.get(qid) or await self.db.get_message_by_wa_id(chat["id"], qid)
            if q:
                quoted_lookup[qid] = q
        for inc, _ in batch:  # цитата старого сообщения, которого нет в базе
            if inc.quoted_id and inc.quoted_id not in quoted_lookup and (inc.quoted_text or inc.quoted_kind):
                is_bot = inc.quoted_sender in self.bot.jids if inc.quoted_sender else False
                qp = await self.db.find_person_by_jid(inc.quoted_sender) if inc.quoted_sender else None
                quoted_lookup[inc.quoted_id] = {
                    "role": "assistant" if is_bot else "user",
                    "person_id": qp.id if qp else None,
                    "text": inc.quoted_text or "",
                    "kind": inc.quoted_kind or "text",
                    "sender_name": "",
                }
                if qp:
                    await add(qp.id)

        people_list = [people_by_id[pid] for pid in order][:14]
        people_facts = []
        for p in people_list:
            facts = await self.db.get_facts(p.id, chat["id"], self.s.memory_facts_in_prompt,
                                            self.s.memory_share_across_chats)
            people_facts.append((p, facts))
        transcript = format_transcript(rows, people_by_id, self.s.bot_name, self.s.timezone,
                                       {i.msg_id for i in starred}, quoted_lookup)
        ctx = PromptContext(
            chat_title=chat.get("title") or "",
            is_group=bool(chat["is_group"]),
            chat_notes=chat.get("notes") or "",
            chat_about=chat.get("about") or "",
            sticker_moods=await self.stickers.moods(),
            people=people_facts,
            transcript=transcript,
            mode_hint=(MODE_HINTS[mode].format(name=self.s.bot_name) + (" " + extra_hint if extra_hint else "")),
            mood=current_mood(chat, self.s.timezone),
            grudges=grudges or {},
        )
        return build_prompt(ctx, self.s), people_list

    # ---------- сама заводит разговор ----------
    INITIATIVE_TICK = 600  # раз в 10 минут бросаем кубик

    def initiative_probability(self) -> float:
        """Шанс на один тик, чтобы в среднем выходило INITIATIVE_PER_WEEK раз в неделю в «дневные» часы."""
        start, end = self.s.initiative_window()
        hours = end - start if end > start else 24 - start + end
        ticks = hours * (3600 / self.INITIATIVE_TICK) * 7
        return min(1.0, self.s.initiative_per_week / ticks) if ticks > 0 else 0.0

    def _in_initiative_hours(self, now_utc: datetime) -> bool:
        start, end = self.s.initiative_window()
        hour = now_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(self.s.timezone)).hour
        return start <= hour < end if end > start else (hour >= start or hour < end)

    async def _initiative_loop(self) -> None:
        while True:
            await asyncio.sleep(self.INITIATIVE_TICK)
            try:
                await self.initiative_tick()
            except Exception:
                log.exception("ошибка в инициативе")

    async def initiative_tick(self, now: datetime | None = None) -> list[int]:
        """Решить, в какие группы Стелла сама напишет сейчас. Возвращает id чатов."""
        now = now or utcnow()
        if (self.s.initiative_per_week <= 0 or self.connection_state != "open" or self.over_budget()
                or not self._in_initiative_hours(now)):
            return []
        p = self.initiative_probability()
        started = []
        for chat in await self.db.group_chats(self.s.evolution_instance):
            if self.s.allowed_groups and chat["jid"] not in self.s.allowed_groups:
                continue
            if chat_paused(chat, now):
                continue
            if (chat.get("chime_level") or self.s.chime_default) == "off":
                continue  # «стелла режим выкл» — сама не пишет
            last = chat.get("last_initiative_at")
            if last and now - last < timedelta(hours=self.s.initiative_min_gap_hours):
                continue
            recent = await self.db.recent_messages(chat["id"], 1)
            if not recent or recent[-1]["role"] == "assistant":
                continue  # сама написала последней и ей не ответили — второй раз не лезет
            if now - recent[-1]["created_at"] < timedelta(minutes=self.s.initiative_quiet_minutes):
                continue  # идёт живой разговор
            if await self.db.count_user_messages(chat["id"]) < 5:
                continue  # чат, который она толком не знает
            if self.rng.random() >= p:
                continue
            await self.db.update_chat(chat["id"], last_initiative_at=now)
            self.spawn(self.initiate(chat["jid"]))
            started.append(chat["id"])
        return started

    async def initiate(self, chat_jid: str) -> bool:
        """Стелла сама пишет в группу. True — если что-то отправила."""
        chat = await self.db.get_chat_by_jid(self.s.evolution_instance, chat_jid)
        if chat is None or chat_paused(chat):
            return False
        grudges = await self.db.active_grudges(chat["id"])
        prompt, people = await self._build_prompt(chat, [], [], "initiative", grudges=grudges)
        ctx = ToolContext(chat_id=chat["id"], sender=None, people_refs={p.ref: p for p in people}, is_admin=False,
                          actions=_ChatActions(self, chat))
        tools = [t for t in build_tools(self.db, self.casino, self.s, ctx) if t.name != "casino"]
        try:
            reply = await self.llm.ask(system=self.system, prompt=prompt, tools=tools, max_turns=self.s.llm_max_turns)
        except LLMError as exc:
            log.warning("инициатива: модель не ответила: %s", exc)
            return False
        await self.track_cost(reply.cost_usd)
        segments = parse_reply(reply.text, self.s.max_bubbles)
        sent = 0
        if segments:
            sent = await self.outbox.send_segments(chat, segments, reply_to=None, quote_first=False, people=people)
        for action in ctx.after:
            await action()
            sent += 1
        if sent:
            await self.db.update_chat(chat["id"], last_bot_at=utcnow())
            # ответы на её вопрос в ближайшие минуты — это ответы ей, даже без цитаты и имени
            self.open_floor[chat_jid] = time.monotonic() + self.s.initiative_open_minutes * 60
            log.info("%s: сама завела разговор", mask_phone(chat_jid))
        elif segments:
            # хотела написать, но не смогла (выгнали из группы, писать могут только админы) — неделю не пытается
            await self.db.update_chat(chat["id"], last_initiative_at=utcnow() + timedelta(days=7))
            log.warning("%s: не получилось написать в группу, пауза на неделю", mask_phone(chat_jid))
        return bool(sent)

    # ---------- расходы и алерты ----------
    async def track_cost(self, usd: float) -> None:
        if usd <= 0:
            return
        today = date.today()
        self._today_spend = await self.db.kv_add(f"spend:{today.isoformat()}", usd)
        self._spend_day = today
        await self.db.kv_add("spend:total", usd)
        if self.over_budget():
            log.warning("дневной бюджет %.2f$ исчерпан: только прямые ответы", self.s.daily_budget_usd)

    def over_budget(self) -> bool:
        if self._spend_day != date.today():
            self._spend_day, self._today_spend = date.today(), 0.0
        return self.s.daily_budget_usd > 0 and self._today_spend >= self.s.daily_budget_usd

    async def refresh_spend(self) -> float:
        self._spend_day = date.today()
        row = await self.db.kv_get(f"spend:{self._spend_day.isoformat()}")
        self._today_spend = row[1] if row else 0.0
        return self._today_spend

    async def on_connection(self, data: dict[str, Any]) -> None:
        state = str(data.get("state") or "")
        if not state:
            return
        prev, self.connection_state = self.connection_state, state
        if state == "open":
            if self.disconnected_at and time.monotonic() - self.disconnected_at > 120:
                minutes = int((time.monotonic() - self.disconnected_at) / 60)
                await self.notify_owner("conn", f"✅ Стелла снова в сети (не было ~{minutes} мин)")
            self.disconnected_at = None
        elif state == "close" and prev != "close":
            self.disconnected_at = time.monotonic()
            reason = data.get("statusReason")
            log.warning("WhatsApp отключился, причина %s", reason)
            await self.alert(f"⚠️ Стелла: WhatsApp отключился (statusReason={reason}). "
                             f"{'Нужно заново привязать номер: python -m bot.setup' if reason == 401 else 'Пробую переподключиться.'}")
            if reason != 401:
                self.spawn(self._reconnect())

    async def _reconnect(self) -> None:
        for attempt in range(5):
            await self.sleep(30 * (attempt + 1))
            if self.connection_state == "open":
                return
            try:
                await self.evo.connect()
            except EvolutionError:
                log.warning("переподключение не удалось", exc_info=True)

    async def alert(self, text: str) -> None:
        """Внешний алерт (ntfy/Telegram-вебхук и т.п.), если WhatsApp недоступен."""
        log.warning("ALERT: %s", text)
        if not self.s.alert_webhook_url:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(self.s.alert_webhook_url, json={"text": text})
        except httpx.HTTPError:
            log.warning("алерт не отправился", exc_info=True)

    async def notify_owner(self, kind: str, text: str) -> None:
        now = time.monotonic()
        if now - self._last_alert.get(kind, -1e9) < 600:
            return
        self._last_alert[kind] = now
        await self.alert(text)
        if self.s.owner_phone and self.connection_state == "open":
            try:
                await self.evo.send_text(self.s.owner_phone, text)
            except EvolutionError:
                log.warning("не смогла написать владельцу", exc_info=True)


__all__ = ["Brain", "ChatRunner", "Segment"]
