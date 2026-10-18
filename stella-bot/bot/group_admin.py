"""Стелла — админ группы и хозяйка своего профиля.

group_manage — по просьбе админа группы (или админа бота из .env) удалить/добавить человека, дать/снять админку,
поменять название/описание, закрыть/открыть группу, выдать или сбросить ссылку-приглашение.
set_my_profile — поменять своё имя, статус и аватарку в WhatsApp (только админы бота из .env).

Права проверяются в коде, а не в промпте. От brain модуль не зависит: всё нужное приходит параметрами.
Эндпоинты — Evolution API v2.3.7 (src/api/routes/group.router.ts и chat.router.ts).
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import media
from .config import Settings
from .db import DB, Person
from .evolution import Evolution, EvolutionError
from .llm.base import ToolSpec
from .util import normalize_jid, phone_of

if TYPE_CHECKING:
    from .tools import ToolContext

log = logging.getLogger("stella.group_admin")

INVITE_URL = "https://chat.whatsapp.com/"
AVATAR_SIZE = 640
# Ограничения WhatsApp
MAX_SUBJECT = 100
MAX_DESCRIPTION = 2048
MAX_PROFILE_NAME = 25
MAX_PROFILE_STATUS = 139

NOT_ADMIN = "я не админ в этой группе — сделайте меня админом группы, тогда смогу"
_NOT_ADMIN_RE = re.compile(r"forbidden|not[-_ ]authori[sz]ed|not[-_ ]admin", re.IGNORECASE)
_REASON_RE = re.compile(r"Error: ([\w\- ]{2,60})")

ACTIONS = ("kick", "add", "promote", "demote", "rename", "describe", "close", "open",
           "lock_info", "unlock_info", "invite_link", "revoke_invite")
# действие инструмента -> action в /group/updateParticipant и /group/updateSetting
PARTICIPANT_ACTIONS = {"kick": "remove", "add": "add", "promote": "promote", "demote": "demote"}
SETTING_ACTIONS = {"close": "announcement", "open": "not_announcement",
                   "lock_info": "locked", "unlock_info": "unlocked"}
# что друг владельца (режим друзей) может попросить, не будучи админом группы
FRIEND_ACTIONS = {"rename", "describe", "invite_link"}


class GroupApi:
    """Тонкие обёртки над Evolution: группа (groupJid — в query) и собственный профиль."""

    def __init__(self, evo: Evolution):
        self.evo = evo

    async def _group(self, method: str, route: str, group_jid: str, body: dict[str, Any] | None = None,
                     timeout: float | None = None) -> Any:
        # groupJid Evolution берёт из body или из query (abstract.router.ts, groupValidate); шлём в query.
        # Пустой {} вместо отсутствия тела — чтобы Express точно разобрал body у POST/DELETE.
        json = None if method == "GET" else (body or {})
        return await self.evo._call(method, f"/group/{route}/{self.evo.instance}", params={"groupJid": group_jid},
                                    json=json, timeout=timeout)

    # ---------- группа ----------
    async def info(self, group_jid: str) -> dict[str, Any]:
        """Название, owner (создатель) и участники [{id, phoneNumber?, lid?, admin: admin|superadmin|null}]."""
        return await self.evo.group_info(group_jid)

    async def update_participants(self, group_jid: str, action: str, participants: list[str]) -> list[dict[str, Any]]:
        """action: add | remove | promote | demote. Ответ — по каждому: {status: "200"|"403"|..., jid}."""
        data = await self._group("POST", "updateParticipant", group_jid,
                                 {"action": action, "participants": participants})
        result = (data or {}).get("updateParticipants") if isinstance(data, dict) else None
        return [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []

    async def set_subject(self, group_jid: str, subject: str) -> Any:
        return await self._group("POST", "updateGroupSubject", group_jid, {"subject": subject})

    async def set_description(self, group_jid: str, description: str) -> Any:
        return await self._group("POST", "updateGroupDescription", group_jid, {"description": description})

    async def set_picture(self, group_jid: str, image_b64: str) -> Any:
        """Фото группы: base64 без префикса data: (или URL)."""
        return await self._group("POST", "updateGroupPicture", group_jid, {"image": image_b64}, timeout=90)

    async def set_setting(self, group_jid: str, action: str) -> Any:
        """announcement — пишут только админы, not_announcement — все;
        locked — название/фото/описание меняют только админы, unlocked — все."""
        return await self._group("POST", "updateSetting", group_jid, {"action": action})

    async def invite_code(self, group_jid: str) -> str:
        """Ссылка-приглашение https://chat.whatsapp.com/…"""
        data = await self._group("GET", "inviteCode", group_jid)
        data = data if isinstance(data, dict) else {}
        return str(data.get("inviteUrl") or (INVITE_URL + str(data["inviteCode"]) if data.get("inviteCode") else ""))

    async def revoke_invite(self, group_jid: str) -> str:
        """Сбросить ссылку; вернуть новую (или "", если Evolution код не прислал)."""
        data = await self._group("POST", "revokeInviteCode", group_jid)
        data = data if isinstance(data, dict) else {}
        return INVITE_URL + str(data["inviteCode"]) if data.get("inviteCode") else ""

    async def leave(self, group_jid: str) -> Any:
        return await self._group("DELETE", "leaveGroup", group_jid)

    # ---------- свой профиль ----------
    async def set_profile_name(self, name: str) -> Any:
        return await self.evo._call("POST", f"/chat/updateProfileName/{self.evo.instance}", json={"name": name})

    async def set_profile_status(self, status: str) -> Any:
        return await self.evo._call("POST", f"/chat/updateProfileStatus/{self.evo.instance}", json={"status": status})

    async def set_profile_picture(self, picture_b64: str) -> Any:
        """Аватарка: base64 без префикса data: (или URL). После неё Evolution переподключает сессию."""
        return await self.evo._call("POST", f"/chat/updateProfilePicture/{self.evo.instance}",
                                    json={"picture": picture_b64}, timeout=90)


def avatar_jpeg(svg: str, size: int = AVATAR_SIZE) -> bytes:
    """SVG -> квадратный JPEG size×size на белом фоне (прозрачность WhatsApp всё равно не показывает)."""
    from PIL import Image

    img = media.render_svg(svg, size, size)
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    img = img.convert("RGBA")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[-1])
    buf = io.BytesIO()
    bg.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def is_not_admin_error(exc: EvolutionError) -> bool:
    """WhatsApp отказал, потому что Стелла не админ группы (Baileys: «forbidden» / «not-authorized»)."""
    return exc.status != 401 and bool(_NOT_ADMIN_RE.search(str(exc)))  # 401 — это неверный apikey Evolution


def _reason(exc: EvolutionError) -> str:
    m = _REASON_RE.search(str(exc))
    if m:
        return m.group(1).strip()
    return f"код {exc.status}" if exc.status else "Evolution недоступен"


def _phone_digits(text: str | None) -> str:
    """«+7 701 123-45-67» -> «77011234567»; не похоже на номер — ""."""
    t = (text or "").strip()
    if not re.fullmatch(r"\+?[\d\s\-()]{10,24}", t):
        return ""
    digits = re.sub(r"\D", "", t)
    return digits if 10 <= len(digits) <= 15 else ""


def _part_ids(part: dict[str, Any]) -> set[str]:
    ids = {normalize_jid(part.get(k)) for k in ("id", "phoneNumber", "lid", "jid") if isinstance(part.get(k), str)}
    ids.discard("")
    return ids


def _phones(ids: set[str]) -> set[str]:
    return {phone_of(j) for j in ids if phone_of(j)}


@dataclass
class _Target:
    label: str
    ids: set[str]  # jid / LID человека
    digits: set[str]  # его номера
    person: Person | None = None

    def matches(self, part: dict[str, Any]) -> bool:
        pids = _part_ids(part)
        return bool(pids & self.ids or _phones(pids) & self.digits)


def _participant_problem(action: str, status: str, label: str) -> str | None:
    """Ответ WhatsApp по конкретному человеку -> понятная причина (None — всё получилось)."""
    if status in ("", "200"):
        return None
    if action == "add":
        if status == "409":
            return f"{label} уже в группе"
        if status == "403":
            return (f"{label} не даёт добавлять себя в группы (настройки приватности) — "
                    "можно скинуть ему ссылку-приглашение (invite_link)")
        if status == "408":
            return f"{label} недавно вышел из группы — WhatsApp пока даёт вернуться только по ссылке (invite_link)"
        if status in ("400", "404"):
            return f"номера {label} нет в WhatsApp"
    elif status == "404":
        return f"{label} нет в этой группе"
    return f"WhatsApp не дал это сделать с {label} (код {status})"


def build_group_tools(
    db: DB,
    settings: Settings,
    ctx: ToolContext,
    *,
    api: GroupApi,
    chat: dict[str, Any],
    is_group_admin: Callable[[dict[str, Any], Person], Awaitable[bool]],
    bot_jids: set[str],
    on_members_changed: Callable[[], Awaitable[Any]] | None = None,
) -> list[ToolSpec]:
    """Инструменты group_manage и set_my_profile для одного ответа.

    chat — строка чата из БД (id, jid, is_group); is_group_admin — проверка «админ группы в WhatsApp»;
    bot_jids — свои jid и LID; on_members_changed — вызвать после смены участников/админов (обновить кэш админов).
    """
    from .tools import ToolError, resolve_person

    group_jid = str(chat.get("jid") or "")
    bot_ids = {normalize_jid(j) for j in bot_jids}
    bot_digits = _phones(bot_ids)

    async def call(coro: Awaitable[Any]) -> Any:
        """Вызов Evolution: «не админ» и прочие отказы -> понятная модели ошибка."""
        try:
            return await coro
        except EvolutionError as exc:
            if is_not_admin_error(exc):
                raise ToolError(NOT_ADMIN) from exc
            log.warning("группа %s: Evolution ответил ошибкой: %s", group_jid[-12:], exc)
            raise ToolError(f"не получилось, WhatsApp ответил ошибкой ({_reason(exc)})") from exc

    def asker_is_bot_admin() -> bool:
        return bool(ctx.sender) and settings.is_admin(phone_of(ctx.sender.jid) or ctx.sender.phone)

    async def check_rights(action: str) -> None:
        if not chat.get("is_group") or not group_jid.endswith("@g.us"):
            raise ToolError("это работает только в группах")
        if getattr(ctx, "untrusted", False):
            raise ToolError("в этом ответе был чужой текст (файл, ссылка или старая переписка) — такие действия "
                            "только по отдельному сообщению админа")
        if ctx.sender is None:
            raise ToolError("управлять группой можно только по просьбе админа")
        if asker_is_bot_admin():
            return
        # друзьям (режим друзей) без прав админа группы — только безобидное; удалить, повысить, закрыть —
        # если сами админы этой группы: иначе друг сделал бы себя админом и руками удалил владельца
        if ctx.is_admin and action in FRIEND_ACTIONS:
            return
        try:
            allowed = await is_group_admin(chat, ctx.sender)
        except Exception:  # не смогли проверить — значит, нельзя
            log.warning("не удалось проверить админа группы", exc_info=True)
            allowed = False
        if not allowed:
            raise ToolError(f"{ctx.sender.name} не админ группы — такое могут просить только админы группы")

    def is_bot(t: _Target) -> bool:
        return bool(t.ids & bot_ids or t.digits & bot_digits)

    async def find_target(who: str, value: str, action: str) -> _Target:
        phone = _phone_digits(who)
        if phone:
            return _Target(f"+{phone}", {f"{phone}@s.whatsapp.net"}, {phone})
        if who:
            try:
                p = await resolve_person(db, ctx, who)
            except ToolError:
                phone = _phone_digits(value)
                if not phone:
                    if action == "add":
                        raise ToolError(f"не знаю «{who}» — для добавления нужен номер телефона в value") from None
                    raise
                return _Target(f"+{phone}", {f"{phone}@s.whatsapp.net"}, {phone})
            ids = {normalize_jid(j) for j in (p.jid, p.alt_jid) if j}
            digits = _phones(ids) | ({p.phone} if p.phone else set())
            return _Target(p.name, ids, digits, p)
        phone = _phone_digits(value)
        if phone:
            return _Target(f"+{phone}", {f"{phone}@s.whatsapp.net"}, {phone})
        if action == "add":
            raise ToolError("кого добавить? нужен номер телефона в value (или человек из чата в person)")
        raise ToolError("кого? укажи person: p12 из контекста, имя/ник или номер")

    async def changed() -> None:
        if on_members_changed is None:
            return
        try:
            await on_members_changed()
        except Exception:
            log.warning("не удалось обновить участников после изменения", exc_info=True)

    async def participants_action(action: str, args: dict[str, Any]) -> str:
        who = str(args.get("person") or "").strip()
        value = str(args.get("value") or "").strip()
        target = await find_target(who, value, action)
        if is_bot(target):
            raise ToolError("это же я сама — себя трогать не буду")
        try:
            info = await api.info(group_jid)
        except EvolutionError as exc:
            log.warning("не удалось получить участников группы: %s", exc)
            raise ToolError("не получилось получить список участников группы, попробуй чуть позже") from exc
        parts = [p for p in (info.get("participants") or []) if isinstance(p, dict)]
        part = next((p for p in parts if target.matches(p)), None)
        me = next((p for p in parts if _part_ids(p) & bot_ids or _phones(_part_ids(p)) & bot_digits), None)
        if part is not None and part is me:
            raise ToolError("это же я сама — себя трогать не буду")

        if action == "add":
            if part is not None:
                return f"{target.label} уже в группе"
            phone = min(target.digits) if target.digits else _phone_digits(value)
            lids = sorted(j for j in target.ids if j.endswith("@lid"))
            if phone:
                member = phone  # только цифры: jid соберёт сам Evolution (createJid)
            elif lids:
                member = lids[0]  # номер неизвестен — пробуем по LID
            else:
                raise ToolError(f"не знаю номера {target.label} — дай номер телефона в value")
        else:
            if part is None:
                raise ToolError(f"{target.label} нет в этой группе")
            owner = normalize_jid(info.get("owner")) if isinstance(info.get("owner"), str) else ""
            is_creator = part.get("admin") == "superadmin" or (owner and owner in _part_ids(part))
            if action in ("kick", "demote"):
                if is_creator:
                    raise ToolError("это создатель группы — его нельзя ни удалить, ни снять с админов")
                protected = target.digits | _phones(_part_ids(part))
                # владельца и админов бота трогают только они сами (друзья в режиме друзей — нет)
                if not asker_is_bot_admin() and any(settings.is_admin(d) for d in protected):
                    raise ToolError("это мой владелец — по просьбе админа группы его трогать не буду")
            if action == "promote" and part.get("admin"):
                return f"{target.label} и так админ"
            if action == "demote" and not part.get("admin"):
                return f"{target.label} и так не админ"
            if me is not None and not me.get("admin"):
                raise ToolError(NOT_ADMIN)
            member = str(part.get("id") or min(target.ids))  # тот jid/LID, под которым он в группе

        ctx.side_effects = True
        result = await call(api.update_participants(group_jid, PARTICIPANT_ACTIONS[action], [member]))
        for r in result:
            problem = _participant_problem(action, str(r.get("status") or ""), target.label)
            if problem:
                raise ToolError(problem)
        if action == "kick" and target.person is not None and db is not None:
            # больше не участник (и не «свой» в режиме друзей)
            await db.remove_members(ctx.chat_id, [target.person.id])
        await changed()
        return {
            "kick": f"удалила {target.label} из группы",
            "add": f"добавила {target.label} в группу",
            "promote": f"сделала {target.label} админом группы",
            "demote": f"сняла {target.label} с админов",
        }[action]

    async def group_manage(args: dict[str, Any]) -> str:
        action = str(args.get("action") or "").strip()
        if action not in ACTIONS:
            raise ToolError("action: " + " | ".join(ACTIONS))
        await check_rights(action)
        if action in PARTICIPANT_ACTIONS:
            return await participants_action(action, args)
        value = str(args.get("value") or "").strip()
        if action == "rename":
            subject = value[:MAX_SUBJECT]
            if not subject:
                raise ToolError("новое название — в value")
            ctx.side_effects = True
            await call(api.set_subject(group_jid, subject))
            return f"переименовала группу в «{subject}»"
        if action == "describe":
            description = value[:MAX_DESCRIPTION]
            if not description:
                raise ToolError("текст описания — в value")
            ctx.side_effects = True
            await call(api.set_description(group_jid, description))
            return "обновила описание группы"
        if action in SETTING_ACTIONS:
            ctx.side_effects = True
            await call(api.set_setting(group_jid, SETTING_ACTIONS[action]))
            return {
                "close": "закрыла группу: писать могут только админы",
                "open": "открыла группу: писать могут все",
                "lock_info": "теперь название, фото и описание группы меняют только админы",
                "unlock_info": "теперь название, фото и описание группы могут менять все",
            }[action]
        if action == "invite_link":
            url = await call(api.invite_code(group_jid))
            if not url:
                raise ToolError("WhatsApp не дал ссылку")
            return f"ссылка-приглашение в группу: {url}"
        # revoke_invite
        ctx.side_effects = True
        url = await call(api.revoke_invite(group_jid))
        return f"старая ссылка больше не работает, новая: {url}" if url else "старая ссылка больше не работает"

    async def set_my_profile(args: dict[str, Any]) -> str:
        if not ctx.is_admin:
            raise ToolError("мой профиль меняю только по просьбе владельца (админов бота)")
        if getattr(ctx, "untrusted", False):
            raise ToolError("в этом ответе был чужой текст — профиль меняю только по отдельному сообщению")
        name = str(args.get("name") or "").strip()[:MAX_PROFILE_NAME]
        status = str(args.get("status") or "").strip()[:MAX_PROFILE_STATUS]
        svg = str(args.get("avatar_svg") or "").strip()
        if not (name or status or svg):
            raise ToolError("что поменять: name, status или avatar_svg")
        picture = ""
        if svg:  # сначала рисуем: ошибку в рисунке модель увидит и поправит, а профиль пока не тронут
            try:
                picture = base64.b64encode(await asyncio.to_thread(avatar_jpeg, svg)).decode("ascii")
            except media.MediaError as exc:
                raise ToolError(str(exc)) from exc
        ctx.side_effects = True
        done: list[str] = []
        failed: list[str] = []
        # аватарка последней: после неё Evolution переподключает WhatsApp
        steps = [("имя", f"имя «{name}»", api.set_profile_name, name),
                 ("статус", f"статус «{status}»", api.set_profile_status, status),
                 ("аватарка", "новая аватарка", api.set_profile_picture, picture)]
        for what, ok_text, fn, arg in steps:
            if not arg:
                continue
            try:
                await fn(arg)
                done.append(ok_text)
            except EvolutionError as exc:
                log.warning("профиль: не удалось поменять %s: %s", what, exc)
                failed.append(f"{what} ({_reason(exc)})")
        if not done:
            raise ToolError("не получилось поменять: " + ", ".join(failed))
        text = "готово: " + ", ".join(done)
        return text + (". не вышло: " + ", ".join(failed) if failed else "")

    from .media_tools import SVG_RULES

    return [
        ToolSpec(
            "group_manage",
            "Управлять этой группой WhatsApp — ТОЛЬКО по просьбе админа группы или твоего владельца (права "
            "проверятся сами; остальным откажи по-человечески). У тебя самой должна быть админка в группе. "
            "action: kick — удалить человека, add — добавить (кого нет в чате — номер телефона в value), "
            "promote / demote — дать / снять админку, rename — новое название (value), describe — описание "
            "(value), close / open — писать могут только админы / все, lock_info / unlock_info — название, фото "
            "и описание меняют только админы / все, invite_link — ссылка-приглашение, revoke_invite — сбросить "
            "старую ссылку и получить новую.",
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": list(ACTIONS)},
                    "person": {"type": "string",
                               "description": "для kick/add/promote/demote: p12 из контекста, имя/ник, «я» или номер"},
                    "value": {"type": "string",
                              "description": "rename — название, describe — описание, add — номер телефона"},
                },
                "required": ["action"],
            },
            group_manage,
        ),
        ToolSpec(
            "set_my_profile",
            "Поменять СВОЙ профиль в WhatsApp — только по просьбе твоего владельца (админа бота): name — имя "
            f"(до {MAX_PROFILE_NAME} символов), status — статус «о себе» (до {MAX_PROFILE_STATUS}), avatar_svg — "
            "новая аватарка, рисуешь сама. " + SVG_RULES + " viewBox=\"0 0 640 640\", фон закрась целиком, "
            "главное — крупно по центру (WhatsApp обрежет в круг). Можно поменять что-то одно.",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "status": {"type": "string"},
                    "avatar_svg": {"type": "string"},
                },
            },
            set_my_profile,
        ),
    ]
