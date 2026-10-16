"""Telegram: та же Стелла в личке и группах Telegram — рядом с WhatsApp, а не вместо.

Сообщения из Telegram превращаются в те же Incoming, что и из WhatsApp, а ответы уходят через клиент с теми же
методами, что у Evolution (send_text, send_media, …). Чаты и люди Telegram получают свои «JID»:
  чат  — «<chat_id>@tg.chat» (в личке chat_id = id человека), человек — «<user_id>@tg.user»,
  сообщение — «tg<chat_id>_<message_id>» (у Telegram номера сообщений свои в каждом чате).
Messenger отправляет каждый вызов туда, откуда чат: Telegram или WhatsApp.

Сообщения забираются long polling'ом (getUpdates) — сервер не должен быть виден из интернета.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any

import httpx

from .evolution import EvolutionError
from .parser import Incoming

log = logging.getLogger("stella.telegram")

API = "https://api.telegram.org"
CHAT_SUFFIX = "@tg.chat"
USER_SUFFIX = "@tg.user"
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
DOWNLOAD_LIMIT = 20 * 1024 * 1024  # больше бот скачать не может (ограничение Telegram)
# реакции, которые Telegram разрешает ботам ставить (остальные он отклоняет)
REACTIONS = set(
    "👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 🕊 🤡 🥱 🥴 😍 🐳 ❤‍🔥 🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 😐 🍓 🍾 💋 🖕 😈 "
    "😴 😭 🤓 👻 👨‍💻 👀 🎃 🙈 😇 😨 🤝 ✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 💊 🙊 😎 👾 🤷‍♂ 🤷 🤷‍♀ 😡".split()
)
REACTION_FALLBACK = {"😂": "🤣", "❤️": "❤", "😆": "😁", "😅": "😁", "🥲": "😢", "😮": "😱", "😲": "🤯", "👋": "🤝",
                     "💀": "🤣", "✨": "🔥", "😀": "😁", "😃": "😁", "😄": "😁", "🙂": "😁", "😊": "🥰", "🤍": "❤"}


def is_tg(jid: str | None) -> bool:
    return bool(jid) and (jid.endswith(CHAT_SUFFIX) or jid.endswith(USER_SUFFIX))


def chat_jid(chat_id: int | str) -> str:
    return f"{chat_id}{CHAT_SUFFIX}"


def user_jid(user_id: int | str) -> str:
    return f"{user_id}{USER_SUFFIX}"


def msg_id(chat_id: int | str, message_id: int | str) -> str:
    return f"tg{chat_id}_{message_id}"


def split_msg_id(value: str | None) -> tuple[int, int] | None:
    m = re.fullmatch(r"tg(-?\d+)_(\d+)", value or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _chat_id(jid: str) -> int:
    return int(jid.split("@", 1)[0])


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


class TelegramError(EvolutionError):
    """Ошибка Bot API (наследник EvolutionError — существующие обработчики ошибок отправки ловят и её)."""


class _Flood(Exception):
    def __init__(self, message: str, wait: int):
        super().__init__(message)
        self.wait = wait


# ---------- входящие ----------
def _kind_of(m: dict[str, Any]) -> str:
    if m.get("photo"):
        return "image"
    if m.get("sticker"):
        return "sticker"
    if m.get("voice") or m.get("audio"):
        return "audio"
    if m.get("video") or m.get("video_note") or m.get("animation"):
        return "video"
    if m.get("document"):
        return "document"
    if m.get("poll"):
        return "poll"
    if m.get("location") or m.get("venue"):
        return "location"
    if m.get("contact"):
        return "contact"
    return "text"


def _raw_message(m: dict[str, Any]) -> dict[str, Any]:
    """Сообщение в виде, привычном остальному коду (как у WhatsApp) + «tg» с тем, что нужно для скачивания."""
    kind = _kind_of(m)
    caption = m.get("caption") or ""
    tg: dict[str, Any] = {"kind": kind}
    raw: dict[str, Any] = {"tg": tg}
    if kind == "image":
        best = max(m["photo"], key=lambda p: p.get("file_size") or p.get("width", 0) * p.get("height", 0))
        tg.update(file_id=best.get("file_id"), size=best.get("file_size"), mime="image/jpeg")
        raw["imageMessage"] = {"caption": caption, "mimetype": "image/jpeg"}
    elif kind == "sticker":
        st = m["sticker"]
        animated = bool(st.get("is_animated") or st.get("is_video"))
        thumb = (st.get("thumbnail") or st.get("thumb") or {}).get("file_id")
        tg.update(file_id=thumb if animated else st.get("file_id"), animated=animated, emoji=st.get("emoji"),
                  mime="image/webp")
        raw["stickerMessage"] = {"isAnimated": animated, "mimetype": "image/webp"}
    elif kind == "audio":
        a = m.get("voice") or m.get("audio")
        tg.update(file_id=a.get("file_id"), size=a.get("file_size"), mime=a.get("mime_type") or "audio/ogg",
                  duration=a.get("duration"))
        raw["audioMessage"] = {"seconds": a.get("duration") or 0, "ptt": bool(m.get("voice")),
                               "mimetype": a.get("mime_type") or "audio/ogg"}
    elif kind == "video":
        v = m.get("video") or m.get("video_note") or m.get("animation")
        tg.update(file_id=v.get("file_id"), size=v.get("file_size"), mime=v.get("mime_type") or "video/mp4",
                  duration=v.get("duration"))
        raw["videoMessage"] = {"caption": caption, "seconds": v.get("duration") or 0}
    elif kind == "document":
        d = m["document"]
        tg.update(file_id=d.get("file_id"), size=d.get("file_size"), mime=d.get("mime_type"))
        raw["documentMessage"] = {"fileName": d.get("file_name") or "файл", "mimetype": d.get("mime_type"),
                                  "fileLength": d.get("file_size") or 0, "caption": caption}
    elif kind == "poll":
        raw["pollCreationMessage"] = {"name": (m["poll"].get("question") or "")}
    else:
        raw["conversation"] = m.get("text") or ""
    return raw


def _text_of(m: dict[str, Any]) -> str:
    if m.get("poll"):
        p = m["poll"]
        return f"{p.get('question') or ''} ({' / '.join(o.get('text', '') for o in p.get('options') or [])})"
    if m.get("location"):
        return "[место на карте]"
    if m.get("contact"):
        c = m["contact"]
        return f"[контакт: {c.get('first_name', '')} {c.get('phone_number', '')}]".strip()
    return m.get("text") or m.get("caption") or ""


def _name(user: dict[str, Any]) -> str:
    return " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x).strip() or (user.get("username") or "")


def parse_update(update: dict[str, Any], *, bot_id: int, bot_username: str, bot_name: str) -> Incoming | None:
    """Обновление Telegram -> Incoming (или None: не сообщение, канал, бот, служебное)."""
    m = update.get("message")
    if not isinstance(m, dict):
        return None  # правки, каналы, реакции и прочее — пропускаем
    chat = m.get("chat") or {}
    user = m.get("from") or {}
    if chat.get("type") not in ("private", "group", "supergroup") or not user.get("id"):
        return None
    if user.get("is_bot"):
        return None  # свои сообщения и чужие боты (чтобы два бота не переписывались бесконечно)
    if m.get("new_chat_members") or m.get("left_chat_member") or m.get("new_chat_title") or m.get("pinned_message"):
        return None
    chat_id = chat["id"]
    text = _text_of(m)
    entities = m.get("entities") or m.get("caption_entities") or []
    mentioned: list[str] = []
    me = f"@{bot_username}".lower() if bot_username else ""
    for e in entities:
        if e.get("type") == "text_mention" and (e.get("user") or {}).get("id"):
            mentioned.append(user_jid(e["user"]["id"]))
        elif e.get("type") in ("mention", "bot_command") and me:
            piece = _entity_text(text, e).lower()
            if piece == me or piece.endswith(me):
                mentioned.append(user_jid(bot_id))
    if me:  # «@stella_bot привет» -> «Стелла привет»; «/start@stella_bot» -> «/start»
        text = re.sub(r"(/\w+)" + re.escape(me), r"\1", text, flags=re.IGNORECASE)
        text = re.sub(re.escape(me), bot_name, text, flags=re.IGNORECASE)
    if text.strip().lower() in ("/start", "/help"):
        text = f"{bot_name}, привет!"  # первое сообщение боту в личке — пусть поздоровается
    kind = _kind_of(m)
    if kind == "text" and not text.strip():
        return None  # 🎲, игры, сторис, служебные (смена фото, перенос группы) — не сообщения для неё
    sender = user_jid(user["id"])
    inc = Incoming(
        instance="",
        msg_id=msg_id(chat_id, m["message_id"]),
        chat_jid=chat_jid(chat_id),
        is_group=chat.get("type") != "private",
        from_me=False,
        sender_jid=sender,
        sender_alt=None,
        push_name=_name(user),
        kind=kind,
        text=text,
        timestamp=int(m.get("date") or 0),
        source="telegram",
        mentioned=mentioned,
        raw_key={"id": msg_id(chat_id, m["message_id"]), "remoteJid": chat_jid(chat_id), "fromMe": False,
                 "participant": sender},
        raw_message=_raw_message(m),
        duration=(m.get("voice") or m.get("audio") or m.get("video") or {}).get("duration"),
    )
    reply = m.get("reply_to_message")
    # в темах форума каждое сообщение «отвечает» на начало темы — это не настоящий ответ
    topic_root = (m.get("is_topic_message") and isinstance(reply, dict)
                  and reply.get("message_id") == m.get("message_thread_id"))
    if isinstance(reply, dict) and reply.get("message_id") and not topic_root:
        r_user = reply.get("from") or {}
        inc.quoted_id = msg_id(chat_id, reply["message_id"])
        inc.quoted_sender = user_jid(r_user["id"]) if r_user.get("id") else None
        inc.quoted_text = _text_of(reply)
        inc.quoted_kind = _kind_of(reply)
        inc.quoted_message = _raw_message(reply)
        inc.quoted_name = _name(r_user) if r_user else None
    if m.get("message_thread_id") and m.get("is_topic_message"):
        inc.raw_key["thread"] = m["message_thread_id"]  # темы (форумы): отвечать в ту же тему
    return inc


def _entity_text(text: str, e: dict[str, Any]) -> str:
    """Кусок текста по смещению/длине в UTF-16 (как считает Telegram)."""
    raw = text.encode("utf-16-le")
    start, length = int(e.get("offset", 0)) * 2, int(e.get("length", 0)) * 2
    return raw[start:start + length].decode("utf-16-le", errors="ignore")


# ---------- клиент ----------
class Telegram:
    """Bot API с методами как у Evolution: send_text, send_media, send_sticker, send_voice, send_poll, …"""

    def __init__(self, token: str, *, client: httpx.AsyncClient | None = None):
        self.token = token
        self._http = client or httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15))
        self.bot_id = 0
        self.username = ""
        self.threads: dict[int, int] = {}  # чат -> тема форума последнего сообщения (отвечать туда же)

    async def close(self) -> None:
        await self._http.aclose()

    async def call(self, method: str, *, data: dict[str, Any] | None = None, files: dict[str, Any] | None = None,
                   timeout: float = 60) -> Any:
        try:
            return await self._call(method, data=data, files=files, timeout=timeout)
        except _Flood as exc:  # Telegram просит подождать — ждём (не дольше 30 с) и пробуем ещё раз
            if method == "sendChatAction" or exc.wait > 30:
                raise TelegramError(str(exc)) from None
            await asyncio.sleep(exc.wait)
            try:
                return await self._call(method, data=data, files=files, timeout=timeout)
            except _Flood as again:
                raise TelegramError(str(again)) from None

    async def _call(self, method: str, *, data: dict[str, Any] | None = None, files: dict[str, Any] | None = None,
                    timeout: float = 60) -> Any:
        url = f"{API}/bot{self.token}/{method}"
        try:
            if files:
                resp = await self._http.post(url, data={k: _form(v) for k, v in (data or {}).items() if v is not None},
                                             files=files, timeout=timeout)
            else:
                resp = await self._http.post(url, json={k: v for k, v in (data or {}).items() if v is not None},
                                             timeout=timeout)
        except httpx.HTTPError as exc:
            raise TelegramError(f"Telegram {method}: нет связи ({type(exc).__name__})") from None
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code == 429:
            wait = int(((body.get("parameters") or {}).get("retry_after")) or 1)
            raise _Flood(f"Telegram {method}: слишком часто, подождать {wait} с", wait)
        if not body.get("ok"):
            # описание ошибки без токена (он в URL, а не в теле — но на всякий случай вычищаем)
            desc = str(body.get("description") or resp.status_code).replace(self.token, "***")
            raise TelegramError(f"Telegram {method}: {desc}")
        return body.get("result")

    async def get_me(self) -> dict[str, Any]:
        me = await self.call("getMe")
        self.bot_id, self.username = int(me["id"]), me.get("username") or ""
        return me

    # --- как у Evolution ---
    async def own_jids(self) -> list[str]:
        return [user_jid(self.bot_id)] if self.bot_id else []

    async def _typing(self, chat_id: int, action: str, delay_ms: int) -> None:
        """«печатает…» на время задержки (Telegram держит статус ~5 с — повторяем)."""
        left = min(max(delay_ms, 0), 15000) / 1000
        while left > 0:
            try:
                await self.call("sendChatAction", data={"chat_id": chat_id, "action": action,
                                                        "message_thread_id": self.threads.get(chat_id)}, timeout=10)
            except TelegramError:
                return
            step = min(4.5, left)
            await asyncio.sleep(step)
            left -= step

    def _reply(self, quoted: dict[str, Any] | None) -> dict[str, Any] | None:
        ids = split_msg_id(((quoted or {}).get("key") or {}).get("id"))
        return {"message_id": ids[1], "allow_sending_without_reply": True} if ids else None

    def _base(self, number: str, quoted: dict[str, Any] | None = None) -> dict[str, Any]:
        chat_id = _chat_id(number)
        base: dict[str, Any] = {"chat_id": chat_id}
        thread = ((quoted or {}).get("key") or {}).get("thread") or self.threads.get(chat_id)
        if thread:
            base["message_thread_id"] = thread
        reply = self._reply(quoted)
        if reply:
            base["reply_parameters"] = reply
        return base

    async def send_text(self, number: str, text: str, *, delay_ms: int = 0, quoted: dict[str, Any] | None = None,
                        mentioned: list[str] | None = None, mentions_everyone: bool = False) -> str | None:
        chat_id = _chat_id(number)
        if delay_ms:
            await self._typing(chat_id, "typing", delay_ms)
        last = None
        for i, part in enumerate(_split_text(text or "…", TEXT_LIMIT)):  # длинное — несколькими сообщениями
            data = self._base(number, quoted if i == 0 else None)
            entities = _mention_entities(part, mentioned or [])
            data.update(text=part, link_preview_options={"is_disabled": True}, entities=entities or None)
            result = await self.call("sendMessage", data=data)
            last = msg_id(chat_id, result["message_id"])
        return last

    async def send_media(self, number: str, mediatype: str, media_b64: str, mimetype: str, filename: str,
                         caption: str = "", *, delay_ms: int = 0, quoted: dict[str, Any] | None = None) -> str | None:
        chat_id = _chat_id(number)
        method, field, action = {"image": ("sendPhoto", "photo", "upload_photo"),
                                 "video": ("sendVideo", "video", "upload_video")}.get(
            mediatype, ("sendDocument", "document", "upload_document"))
        if delay_ms:
            await self._typing(chat_id, action, delay_ms)
        data = self._base(number, quoted)
        if caption:
            data["caption"] = caption[:CAPTION_LIMIT]
        if mediatype == "video":
            data["supports_streaming"] = True
        files = {field: (filename or field, base64.b64decode(media_b64), mimetype or "application/octet-stream")}
        result = await self.call(method, data=data, files=files, timeout=180)
        return msg_id(chat_id, result["message_id"])

    async def send_sticker(self, number: str, sticker_b64: str, *, delay_ms: int = 0) -> str | None:
        chat_id = _chat_id(number)
        if delay_ms:
            await self._typing(chat_id, "choose_sticker", delay_ms)
        files = {"sticker": ("sticker.webp", base64.b64decode(sticker_b64), "image/webp")}
        result = await self.call("sendSticker", data=self._base(number), files=files, timeout=60)
        return msg_id(chat_id, result["message_id"])

    async def send_voice(self, number: str, audio_b64: str, *, delay_ms: int = 0) -> str | None:
        chat_id = _chat_id(number)
        if delay_ms:
            await self._typing(chat_id, "record_voice", delay_ms)
        files = {"voice": ("voice.ogg", base64.b64decode(audio_b64), "audio/ogg")}
        result = await self.call("sendVoice", data=self._base(number), files=files, timeout=120)
        return msg_id(chat_id, result["message_id"])

    async def send_poll(self, number: str, question: str, options: list[str], *, multiple: bool = False,
                        delay_ms: int = 0) -> str | None:
        chat_id = _chat_id(number)
        options = list(dict.fromkeys(o.strip()[:100] for o in options if o and o.strip()))[:10]
        if len(options) < 2:
            raise TelegramError("в опросе нужно хотя бы два варианта")
        if delay_ms:
            await self._typing(chat_id, "typing", delay_ms)
        data = self._base(number)
        data.update(question=question[:300], options=[{"text": o} for o in options],
                    allows_multiple_answers=multiple, is_anonymous=False)
        result = await self.call("sendPoll", data=data)
        return msg_id(chat_id, result["message_id"])

    async def send_reaction(self, key: dict[str, Any], emoji: str) -> None:
        ids = split_msg_id(key.get("id"))
        if not ids:
            return
        emoji = emoji.replace("️", "")
        emoji = emoji if emoji in REACTIONS else REACTION_FALLBACK.get(emoji, "")
        if not emoji:
            return  # такую реакцию Telegram ботам не разрешает
        await self.call("setMessageReaction", data={"chat_id": ids[0], "message_id": ids[1],
                                                    "reaction": [{"type": "emoji", "emoji": emoji}]})

    async def send_presence(self, number: str, presence: str = "composing", delay_ms: int = 3000) -> None:
        """«печатает…» и ждать delay_ms (как Evolution: мозг зовёт это в цикле, пока модель думает)."""
        chat_id = _chat_id(number)
        await self.call("sendChatAction", data={"chat_id": chat_id, "action": "typing",
                                                "message_thread_id": self.threads.get(chat_id)}, timeout=10)
        await asyncio.sleep(min(max(delay_ms, 1000), 4500) / 1000)

    async def mark_read(self, keys: list[dict[str, Any]]) -> None:
        return None  # у ботов в Telegram нет «прочитано»

    async def delete_message(self, key: dict[str, Any]) -> None:
        ids = split_msg_id(key.get("id"))
        if ids:
            await self.call("deleteMessage", data={"chat_id": ids[0], "message_id": ids[1]})

    async def media_base64(self, key: dict[str, Any], message: dict[str, Any] | None = None) -> bytes | None:
        """Скачать файл сообщения (фото, стикер, голосовое, документ) — до 20 МБ (ограничение Telegram)."""
        tg = (message or {}).get("tg") or {}
        file_id = tg.get("file_id")
        if not file_id:
            return None
        if (tg.get("size") or 0) > DOWNLOAD_LIMIT:
            raise TelegramError("файл больше 20 МБ — Telegram не даёт ботам его скачать")
        info = await self.call("getFile", data={"file_id": file_id})
        path = (info or {}).get("file_path")
        if not path:
            return None
        try:
            resp = await self._http.get(f"{API}/file/bot{self.token}/{path}", timeout=120)
        except httpx.HTTPError as exc:
            raise TelegramError(f"Telegram: файл не скачался ({type(exc).__name__})") from None
        if resp.status_code != 200 or len(resp.content) > DOWNLOAD_LIMIT:
            raise TelegramError("Telegram: файл не скачался")
        return resp.content

    async def group_info(self, group_jid: str) -> dict[str, Any]:
        chat_id = _chat_id(group_jid)
        chat = await self.call("getChat", data={"chat_id": chat_id})
        admins = await self.call("getChatAdministrators", data={"chat_id": chat_id})
        participants = [{"id": user_jid(a["user"]["id"]), "admin": "superadmin" if a.get("status") == "creator"
                         else "admin"} for a in admins or [] if (a.get("user") or {}).get("id")]
        return {"subject": (chat or {}).get("title") or "", "participants": participants}

    # --- приём сообщений ---
    async def updates(self, offset: int, timeout: int = 50) -> list[dict[str, Any]]:
        return await self.call("getUpdates", data={"offset": offset, "timeout": timeout,
                                                   "allowed_updates": ["message"]}, timeout=timeout + 15) or []


def _split_text(text: str, limit: int) -> list[str]:
    """Разрезать текст на куски ≤ limit (по строкам, потом по предложениям/словам)."""
    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = max(rest.rfind("\n", 0, limit), rest.rfind(". ", 0, limit) + 1, rest.rfind(" ", 0, limit))
        cut = cut if cut > limit // 2 else limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    parts.append(rest)
    return [p for p in parts if p] or ["…"]


def _form(v: Any) -> str:
    import json

    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _mention_entities(text: str, mentioned: list[str]) -> list[dict[str, Any]]:
    """«@Вася» в тексте -> подсветка Васи (text_mention). mentioned — «<id>@tg.user|Вася» от outbox."""
    entities = []
    for item in mentioned:
        jid, _, name = item.partition("|")
        if not jid.endswith(USER_SUFFIX) or not name:
            continue
        uid = jid.split("@", 1)[0]
        if not uid.isdigit():
            continue
        for m in re.finditer("@" + re.escape(name) + r"(?![\wА-Яа-яЁё])", text, re.IGNORECASE):
            entities.append({"type": "text_mention", "offset": _utf16_len(text[:m.start()]),
                             "length": _utf16_len(m.group(0)),
                             "user": {"id": int(uid), "is_bot": False, "first_name": name}})
    return sorted(entities, key=lambda e: e["offset"])


# ---------- общий отправитель: WhatsApp или Telegram по чату ----------
class Messenger:
    """Те же методы, что у Evolution; чаты Telegram уходят в Telegram, остальное — в WhatsApp (Evolution)."""

    def __init__(self, evo: Any, tg: Telegram | None):
        self.evo = evo
        self.tg = tg

    def _pick(self, jid: str | None) -> Any:
        if self.tg is not None and is_tg(jid):
            return self.tg
        if is_tg(jid):
            raise TelegramError("Telegram не настроен (TELEGRAM_BOT_TOKEN)")
        return self.evo

    def __getattr__(self, name: str) -> Any:  # всё прочее (настройка инстанса, вебхук, состояние) — Evolution
        return getattr(self.evo, name)

    async def send_text(self, number: str, text: str, **kw: Any) -> str | None:
        return await self._pick(number).send_text(number, text, **kw)

    async def send_media(self, number: str, *args: Any, **kw: Any) -> str | None:
        return await self._pick(number).send_media(number, *args, **kw)

    async def send_sticker(self, number: str, *args: Any, **kw: Any) -> str | None:
        return await self._pick(number).send_sticker(number, *args, **kw)

    async def send_voice(self, number: str, *args: Any, **kw: Any) -> str | None:
        return await self._pick(number).send_voice(number, *args, **kw)

    async def send_poll(self, number: str, *args: Any, **kw: Any) -> str | None:
        return await self._pick(number).send_poll(number, *args, **kw)

    async def send_presence(self, number: str, *args: Any, **kw: Any) -> None:
        return await self._pick(number).send_presence(number, *args, **kw)

    async def group_info(self, jid: str) -> dict[str, Any]:
        return await self._pick(jid).group_info(jid)

    async def send_reaction(self, key: dict[str, Any], emoji: str) -> None:
        return await self._pick(key.get("remoteJid")).send_reaction(key, emoji)

    async def delete_message(self, key: dict[str, Any]) -> None:
        return await self._pick(key.get("remoteJid")).delete_message(key)

    async def media_base64(self, key: dict[str, Any], message: dict[str, Any] | None = None) -> bytes | None:
        if self.tg is not None and (is_tg(key.get("remoteJid")) or (message or {}).get("tg")):
            return await self.tg.media_base64(key, message)
        return await self.evo.media_base64(key, message)

    async def mark_read(self, keys: list[dict[str, Any]]) -> None:
        wa = [k for k in keys if not is_tg(k.get("remoteJid"))]
        if wa:
            await self.evo.mark_read(wa)

    async def own_jids(self) -> list[str]:
        jids = list(await self.evo.own_jids())
        if self.tg is not None:
            jids += await self.tg.own_jids()
        return jids

    async def close(self) -> None:
        await self.evo.close()
        if self.tg is not None:
            await self.tg.close()


# ---------- цикл приёма ----------
async def poll_forever(brain: Any, tg: Telegram) -> None:
    """Забирать сообщения из Telegram и отдавать мозгу. Работает, пока бот жив; сбои сети — пауза и снова."""
    backoff = 2.0
    offset = 0  # только в памяти: подтверждённые обновления Telegram и так больше не отдаёт
    ready = False
    seen_groups: set[int] = set()
    while True:
        try:
            if not ready:
                me = await tg.get_me()
                await brain.add_bot_jid(user_jid(tg.bot_id))
                await tg.call("deleteWebhook", data={"drop_pending_updates": False})
                ready = True
                log.info("Telegram: бот @%s на связи", me.get("username"))
                backoff = 2.0
            updates = await tg.updates(offset)
            for upd in updates:
                offset = max(offset, int(upd.get("update_id", 0)) + 1)
                try:
                    inc = parse_update(upd, bot_id=tg.bot_id, bot_username=tg.username, bot_name=brain.s.bot_name)
                except Exception:
                    log.exception("Telegram: не разобрала обновление")
                    continue
                if inc is None:
                    continue
                chat_id = _chat_id(inc.chat_jid)
                if inc.is_group and chat_id not in seen_groups:  # id группы — для TELEGRAM_ALLOWED_CHATS
                    seen_groups.add(chat_id)
                    title = ((upd.get("message") or {}).get("chat") or {}).get("title") or ""
                    log.info("Telegram: группа «%s», id %s", title[:60], chat_id)
                brain.spawn(brain.on_message(inc))
            backoff = 2.0
        except asyncio.CancelledError:
            raise
        except TelegramError as exc:
            text = str(exc)
            if "Unauthorized" in text or "Not Found" in text:
                log.error("Telegram: токен не подходит (TELEGRAM_BOT_TOKEN) — проверь в @BotFather; жду 10 мин")
                await asyncio.sleep(600)
                continue
            if "webhook is active" in text:
                ready = False  # кто-то поставил вебхук — снимем и продолжим
            elif "Conflict" in text:
                log.warning("Telegram: этим ботом уже кто-то забирает сообщения (второй сервер?) — жду")
            else:
                log.warning("%s", text)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        except Exception:
            log.exception("Telegram: ошибка в цикле приёма")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
