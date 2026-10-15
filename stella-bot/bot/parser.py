"""Разбор вебхука Evolution API v2 (событие messages.upsert) в простой объект."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .util import normalize_jid

IGNORED_TYPES = {
    "protocolMessage",
    "senderKeyDistributionMessage",
    "messageContextInfo",
    "editedMessage",
    "pollUpdateMessage",
    "reactionMessage",
    "unknown",
}

MEDIA_KINDS = {
    "stickerMessage": "sticker",
    "imageMessage": "image",
    "videoMessage": "video",
    "ptvMessage": "video",
    "audioMessage": "audio",
    "documentMessage": "document",
    "locationMessage": "location",
    "liveLocationMessage": "location",
    "contactMessage": "contact",
    "contactsArrayMessage": "contact",
    "pollCreationMessage": "poll",
    "pollCreationMessageV2": "poll",
    "pollCreationMessageV3": "poll",
}

# Обёртки, внутри которых лежит настоящее сообщение
WRAPPERS = (
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "viewOnceMessageV2Extension",
    "documentWithCaptionMessage",
    "groupMentionedMessage",
    "botInvokeMessage",
    "lottieStickerMessage",
    "associatedChildMessage",  # фото из альбома (с подписью)
)


def event_name(payload: dict[str, Any]) -> str:
    """'MESSAGES_UPSERT' / 'messages.upsert' / 'messages-upsert' -> 'messages.upsert'."""
    return str(payload.get("event", "")).lower().replace("_", ".").replace("-", ".")


@dataclass
class Incoming:
    instance: str
    msg_id: str
    chat_jid: str
    is_group: bool
    from_me: bool
    sender_jid: str
    sender_alt: str | None
    push_name: str
    kind: str  # text|sticker|image|video|audio|document|location|contact|poll
    text: str
    timestamp: int
    source: str | None = None
    mentioned: list[str] = field(default_factory=list)
    quoted_id: str | None = None
    quoted_sender: str | None = None
    quoted_text: str | None = None
    quoted_kind: str | None = None
    quoted_message: dict[str, Any] | None = None
    duration: int | None = None
    raw_key: dict[str, Any] = field(default_factory=dict)
    raw_message: dict[str, Any] = field(default_factory=dict)
    bot_jid: str | None = None  # поле sender в вебхуке = номер самого бота
    lid_addressing: bool = False  # группа в режиме LID (участники видны по LID, а не по номерам)

    @property
    def is_dm(self) -> bool:
        return not self.is_group


def _unwrap(message: dict[str, Any]) -> dict[str, Any]:
    for _ in range(3):
        for w in WRAPPERS:
            inner = message.get(w)
            if isinstance(inner, dict) and isinstance(inner.get("message"), dict):
                message = inner["message"]
                break
        else:
            return message
    return message


def _content_type(message: dict[str, Any], hint: str | None) -> str | None:
    if hint and hint in message:
        return hint
    if "conversation" in message:
        return "conversation"
    if "extendedTextMessage" in message:
        return "extendedTextMessage"
    for key in message:
        if key.endswith("Message") and key not in ("messageContextInfo",):
            return key
    return hint


def _text_and_kind(message: dict[str, Any], ctype: str | None) -> tuple[str, str, int | None]:
    if ctype in ("conversation", "extendedTextMessage") or (ctype is None and "conversation" in message):
        text = message.get("conversation") or (message.get("extendedTextMessage") or {}).get("text") or ""
        return str(text), "text", None
    body = message.get(ctype or "", {}) or {}
    kind = MEDIA_KINDS.get(ctype or "", "other")
    text = ""
    if isinstance(body, dict):
        text = body.get("caption") or body.get("name") or ""
        if kind == "poll":
            options = [o.get("optionName", "") for o in body.get("options") or [] if isinstance(o, dict)]
            text = body.get("name") or ""
            if options:
                text = f"{text} (варианты: {' / '.join(o for o in options if o)})"
        seconds = body.get("seconds")
        return str(text), kind, int(seconds) if isinstance(seconds, (int, float)) else None
    return str(text), kind, None


def _pick_participant(key: dict[str, Any], data: dict[str, Any]) -> tuple[str, str | None]:
    """В группах WhatsApp всё чаще присылает LID (…@lid). Если есть номер — берём его."""
    participant = normalize_jid(key.get("participant") or data.get("participant") or "")
    candidates = [
        key.get("participantAlt"),
        key.get("participantPn"),
        key.get("senderPn"),
        data.get("participantAlt"),
    ]
    alt = next((normalize_jid(c) for c in candidates if isinstance(c, str) and c), None)
    if participant.endswith("@lid") and alt and alt.endswith("@s.whatsapp.net"):
        return alt, participant
    return participant, alt


def parse_upsert(payload: dict[str, Any]) -> Incoming | None:
    data = payload.get("data")
    if isinstance(data, list):  # на всякий случай: некоторые сборки шлют список
        data = data[0] if data else None
    if not isinstance(data, dict):
        return None
    key = data.get("key") or {}
    chat_jid = normalize_jid(key.get("remoteJid") or "")
    msg_id = key.get("id") or ""
    if not chat_jid or not msg_id:
        return None
    if chat_jid == "status@broadcast" or chat_jid.endswith("@broadcast") or chat_jid.endswith("@newsletter"):
        return None
    dm_alt = next((normalize_jid(key[k]) for k in ("remoteJidAlt", "senderPn") if isinstance(key.get(k), str) and key[k]), None)
    dm_lid = None
    if chat_jid.endswith("@lid") and dm_alt and dm_alt.endswith("@s.whatsapp.net"):
        dm_lid, chat_jid = chat_jid, dm_alt  # в личке отвечаем на номер, если он известен

    message = data.get("message") or {}
    if not isinstance(message, dict):
        return None
    message = _unwrap(message)
    ctype = _content_type(message, data.get("messageType"))
    if ctype in IGNORED_TYPES or ctype is None:
        return None
    text, kind, duration = _text_and_kind(message, ctype)
    if kind == "other":
        return None
    if kind == "text" and not text.strip():
        return None

    is_group = chat_jid.endswith("@g.us")
    from_me = bool(key.get("fromMe"))
    bot_jid = normalize_jid(payload.get("sender")) or None
    if is_group:
        sender_jid, sender_alt = _pick_participant(key, data)
    else:
        sender_jid = chat_jid
        sender_alt = dm_lid or (dm_alt if dm_alt and dm_alt != chat_jid else None)
    if from_me and bot_jid:
        sender_jid = bot_jid
    if not sender_jid:
        return None

    ctx = data.get("contextInfo") or {}
    if not ctx and ctype and isinstance(message.get(ctype), dict):
        ctx = message[ctype].get("contextInfo") or {}
    quoted = ctx.get("quotedMessage") if isinstance(ctx, dict) else None
    q_text = q_kind = None
    if isinstance(quoted, dict) and quoted:
        q_unwrapped = _unwrap(quoted)
        q_type = _content_type(q_unwrapped, None)
        q_text, q_kind, _ = _text_and_kind(q_unwrapped, q_type)
        quoted = q_unwrapped

    push_name = data.get("pushName") or ""
    if push_name == "Você":  # так Evolution подписывает свои же сообщения
        push_name = ""

    return Incoming(
        instance=str(payload.get("instance") or ""),
        msg_id=msg_id,
        chat_jid=chat_jid,
        is_group=is_group,
        from_me=from_me,
        sender_jid=sender_jid,
        sender_alt=sender_alt,
        push_name=str(push_name).strip(),
        kind=kind,
        text=text.strip(),
        timestamp=int(data.get("messageTimestamp") or 0),
        source=data.get("source"),
        mentioned=[normalize_jid(j) for j in ctx.get("mentionedJid") or [] if isinstance(j, str)] if isinstance(ctx, dict) else [],
        quoted_id=(ctx.get("stanzaId") or None) if isinstance(ctx, dict) else None,
        quoted_sender=(normalize_jid(ctx.get("participant")) or None) if isinstance(ctx, dict) else None,
        quoted_text=q_text or None,
        quoted_kind=q_kind,
        quoted_message=quoted if isinstance(quoted, dict) and quoted else None,
        duration=duration,
        raw_key=dict(key),
        raw_message=message,
        bot_jid=bot_jid,
        lid_addressing=is_group and (key.get("addressingMode") == "lid" or sender_jid.endswith("@lid")
                                     or bool(sender_alt and sender_alt.endswith("@lid"))),
    )
