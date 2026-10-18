"""Стелла — админ группы: точные запросы к Evolution, права, ошибки «я не админ», аватарка."""

import base64
import io
import json
import types

import httpx
import pytest
from PIL import Image

from bot import evolution as evolution_module
from bot import group_admin
from bot.db import DB, Person
from bot.evolution import Evolution
from bot.group_admin import NOT_ADMIN, GroupApi, avatar_jpeg, build_group_tools
from bot.tools import ToolContext, ToolError

from .conftest import BOT, GROUP, OWNER, PETYA, VASYA, make_settings

BOT_LID = "111111111111111@lid"
PETYA_LID = "222222222222222@lid"
CREATOR = "77033333333@s.whatsapp.net"
INFO_PATH = "/group/findGroupInfos/stella"

VASYA_P = Person(1, VASYA, "77011111111", "Вася", None)
PETYA_P = Person(2, PETYA, "77022222222", "Петя", None)
BOT_P = Person(3, BOT, "77000000001", "Стелла", None)
CREATOR_P = Person(4, CREATOR, "77033333333", "Создатель", None)
OWNER_P = Person(5, f"{OWNER}@s.whatsapp.net", OWNER, "Хозяин", None)
GROUP_CHAT = {"id": 1, "jid": GROUP, "is_group": True}
DM_CHAT = {"id": 2, "jid": VASYA, "is_group": False}


def group_info(*, bot_admin: bool = True, lid_group: bool = False) -> dict:
    """Ответ /group/findGroupInfos: бот, Вася (админ), Петя, создатель, владелец бота."""
    if lid_group:  # в LID-группе id участника — LID, номер — в phoneNumber
        bot = {"id": BOT_LID, "phoneNumber": BOT, "admin": "admin" if bot_admin else None}
        petya = {"id": PETYA_LID, "phoneNumber": PETYA, "admin": None}
    else:
        bot = {"id": BOT, "admin": "admin" if bot_admin else None}
        petya = {"id": PETYA, "admin": None}
    return {"id": GROUP, "subject": "Друзья", "owner": CREATOR, "participants": [
        bot, petya,
        {"id": VASYA, "admin": "admin"},
        {"id": CREATOR, "admin": "superadmin"},
        {"id": f"{OWNER}@s.whatsapp.net", "admin": "admin"},
    ]}


class Evo:
    """Настоящий клиент Evolution поверх httpx.MockTransport; запоминает каждый запрос."""

    def __init__(self, routes: dict | None = None):
        self.routes = {("GET", INFO_PATH): httpx.Response(200, json=group_info())}
        self.routes.update(routes or {})
        self.requests: list[dict] = []
        client = httpx.AsyncClient(base_url="http://evo", transport=httpx.MockTransport(self.handler),
                                   headers={"apikey": "k"})
        self.api = GroupApi(Evolution("http://evo", "k", "stella", client=client))

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append({"method": request.method, "path": request.url.path,
                              "params": dict(request.url.params), "json": body})
        resp = self.routes.get((request.method, request.url.path))
        if resp is None:
            return httpx.Response(201, json={"update": "success"})
        return resp(request) if callable(resp) else resp

    def changes(self) -> list[dict]:
        """Всё, кроме чтения списка участников."""
        return [r for r in self.requests if r["path"] != INFO_PATH]


def make_ctx(sender: Person | None = VASYA_P, *, is_admin: bool = False, chat_id: int = 1) -> ToolContext:
    people = [VASYA_P, PETYA_P, BOT_P, CREATOR_P, OWNER_P]
    return ToolContext(chat_id=chat_id, sender=sender, people_refs={p.ref: p for p in people}, is_admin=is_admin)


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


def make_tools(evo: Evo, ctx: ToolContext, settings, *, chat=GROUP_CHAT, wa_admins=(VASYA,), db=None,
               changed: list | None = None):
    checked: list[str] = []

    async def is_group_admin(chat_row, person):
        checked.append(person.jid)
        return person.jid in wa_admins

    async def on_changed():
        if changed is not None:
            changed.append(True)

    specs = build_group_tools(db, settings, ctx, api=evo.api, chat=chat, is_group_admin=is_group_admin,
                              bot_jids={BOT, BOT_LID}, on_members_changed=on_changed)
    tools = {t.name: t.handler for t in specs}
    tools["checked"] = checked
    return tools


# ---------- точные эндпоинты Evolution v2.3.7 ----------
async def test_group_api_exact_requests():
    evo = Evo({
        ("POST", "/group/updateParticipant/stella"): httpx.Response(
            201, json={"updateParticipants": [{"status": "200", "jid": PETYA}]}),
        ("GET", "/group/inviteCode/stella"): httpx.Response(
            200, json={"inviteUrl": "https://chat.whatsapp.com/AAAAAAAAAAAAAAAAAAAAAA", "inviteCode": "A" * 22}),
        ("POST", "/group/revokeInviteCode/stella"): httpx.Response(201, json={"revoked": True, "inviteCode": "B" * 22}),
        ("DELETE", "/group/leaveGroup/stella"): httpx.Response(200, json={"groupJid": GROUP, "leave": True}),
    })
    api = evo.api
    assert (await api.info(GROUP))["subject"] == "Друзья"
    assert await api.update_participants(GROUP, "remove", [PETYA]) == [{"status": "200", "jid": PETYA}]
    await api.set_subject(GROUP, "Новое имя")
    await api.set_description(GROUP, "Описание")
    await api.set_picture(GROUP, "AAAA")
    await api.set_setting(GROUP, "announcement")
    assert await api.invite_code(GROUP) == "https://chat.whatsapp.com/" + "A" * 22
    assert await api.revoke_invite(GROUP) == "https://chat.whatsapp.com/" + "B" * 22
    await api.leave(GROUP)
    await api.set_profile_name("Стелла")
    await api.set_profile_status("на связи")
    await api.set_profile_picture("BBBB")
    g = {"groupJid": GROUP}
    assert [(r["method"], r["path"], r["params"], r["json"]) for r in evo.requests] == [
        ("GET", "/group/findGroupInfos/stella", g, None),
        ("POST", "/group/updateParticipant/stella", g, {"action": "remove", "participants": [PETYA]}),
        ("POST", "/group/updateGroupSubject/stella", g, {"subject": "Новое имя"}),
        ("POST", "/group/updateGroupDescription/stella", g, {"description": "Описание"}),
        ("POST", "/group/updateGroupPicture/stella", g, {"image": "AAAA"}),
        ("POST", "/group/updateSetting/stella", g, {"action": "announcement"}),
        ("GET", "/group/inviteCode/stella", g, None),
        ("POST", "/group/revokeInviteCode/stella", g, {}),
        ("DELETE", "/group/leaveGroup/stella", g, {}),
        ("POST", "/chat/updateProfileName/stella", {}, {"name": "Стелла"}),
        ("POST", "/chat/updateProfileStatus/stella", {}, {"status": "на связи"}),
        ("POST", "/chat/updateProfilePicture/stella", {}, {"picture": "BBBB"}),
    ]


# ---------- права ----------
async def test_stranger_is_denied(settings):
    evo = Evo()
    ctx = make_ctx(PETYA_P)
    t = make_tools(evo, ctx, settings)
    with pytest.raises(ToolError, match="не админ группы"):
        await t["group_manage"]({"action": "kick", "person": "p1"})
    with pytest.raises(ToolError, match="не админ группы"):
        await t["group_manage"]({"action": "rename", "value": "захват"})
    assert evo.requests == [] and t["checked"] == [PETYA, PETYA]
    assert ctx.side_effects is False


async def test_group_admin_can_kick_and_brain_is_told(settings):
    evo = Evo({("POST", "/group/updateParticipant/stella"): httpx.Response(
        201, json={"updateParticipants": [{"status": "200", "jid": PETYA}]})})
    ctx = make_ctx(VASYA_P)
    changed: list = []
    t = make_tools(evo, ctx, settings, changed=changed)
    out = await t["group_manage"]({"action": "kick", "person": "p2"})
    assert out == "удалила Петя из группы"
    assert ctx.side_effects is True and changed == [True]
    assert evo.changes() == [{"method": "POST", "path": "/group/updateParticipant/stella",
                              "params": {"groupJid": GROUP}, "json": {"action": "remove", "participants": [PETYA]}}]


async def test_env_admin_allowed_without_group_admin(settings):
    evo = Evo()
    ctx = make_ctx(OWNER_P, is_admin=True)
    t = make_tools(evo, ctx, settings, wa_admins=())
    assert await t["group_manage"]({"action": "rename", "value": "Клуб"}) == "переименовала группу в «Клуб»"
    assert evo.changes()[0]["json"] == {"subject": "Клуб"} and ctx.side_effects
    assert t["checked"] == []  # админ бота — WhatsApp-админку не спрашиваем


async def test_dm_rejected(settings):
    evo = Evo()
    t = make_tools(evo, make_ctx(OWNER_P, is_admin=True), settings, chat=DM_CHAT)
    with pytest.raises(ToolError, match="только в группах"):
        await t["group_manage"]({"action": "invite_link"})
    assert evo.requests == []


async def test_without_sender_rejected(settings):
    evo = Evo()
    t = make_tools(evo, make_ctx(None), settings)
    with pytest.raises(ToolError, match="по просьбе админа"):
        await t["group_manage"]({"action": "close"})
    assert evo.requests == []


@pytest.mark.parametrize("who", ["p3", "+7 700 000 0001"])
@pytest.mark.parametrize("action", ["kick", "demote", "promote", "add"])
async def test_cannot_touch_the_bot(settings, who, action):
    evo = Evo()
    ctx = make_ctx(VASYA_P)
    t = make_tools(evo, ctx, settings)
    with pytest.raises(ToolError, match="я сама"):
        await t["group_manage"]({"action": action, "person": who})
    assert evo.changes() == [] and not ctx.side_effects


async def test_cannot_kick_bot_by_lid(settings):
    evo = Evo({("GET", INFO_PATH): httpx.Response(200, json=group_info(lid_group=True))})
    lid_bot = Person(9, BOT_LID, None, "Стелла", None)
    ctx = ToolContext(chat_id=1, sender=VASYA_P, people_refs={lid_bot.ref: lid_bot}, is_admin=False)
    t = make_tools(evo, ctx, settings)
    with pytest.raises(ToolError, match="я сама"):
        await t["group_manage"]({"action": "kick", "person": lid_bot.ref})
    assert evo.changes() == []


@pytest.mark.parametrize("action", ["kick", "demote"])
async def test_cannot_kick_or_demote_creator(settings, action):
    evo = Evo()
    ctx = make_ctx(OWNER_P, is_admin=True)  # даже владельцу бота
    t = make_tools(evo, ctx, settings)
    with pytest.raises(ToolError, match="создатель группы"):
        await t["group_manage"]({"action": action, "person": "p4"})
    assert evo.changes() == [] and not ctx.side_effects


async def test_group_admin_cannot_kick_bot_owner(settings):
    evo = Evo()
    t = make_tools(evo, make_ctx(VASYA_P), settings)
    with pytest.raises(ToolError, match="владелец"):
        await t["group_manage"]({"action": "kick", "person": "p5"})
    assert evo.changes() == []


async def test_friend_in_friends_mode_cannot_kick_bot_owner(settings):
    settings.friends_mode = True
    evo = Evo()
    t = make_tools(evo, make_ctx(VASYA_P, is_admin=True), settings)  # друг: свой, но не владелец и не админ бота
    with pytest.raises(ToolError, match="владелец"):
        await t["group_manage"]({"action": "kick", "person": "p5"})
    assert evo.changes() == []


async def test_friend_without_group_admin_rights_gets_only_harmless_actions(settings):
    # друг владельца (режим друзей), но в этой группе не админ: себя не повысит, никого не удалит, группу не закроет —
    # иначе сделал бы себя админом и руками удалил владельца
    settings.friends_mode = True
    evo = Evo()
    t = make_tools(evo, make_ctx(PETYA_P, is_admin=True), settings)
    for args in ({"action": "promote", "person": "я"}, {"action": "kick", "person": "p1"}, {"action": "close"},
                 {"action": "lock_info"}, {"action": "revoke_invite"}):
        with pytest.raises(ToolError, match="не админ группы"):
            await t["group_manage"](args)
    assert evo.changes() == []
    assert await t["group_manage"]({"action": "rename", "value": "Клуб"}) == "переименовала группу в «Клуб»"


# ---------- «я не админ» ----------
async def test_not_admin_error_from_whatsapp(settings):
    body = {"status": 400, "error": "Bad Request",
            "response": {"message": ["Error updating setting", "Error: forbidden"]}}
    evo = Evo({("POST", "/group/updateSetting/stella"): httpx.Response(400, json=body)})
    ctx = make_ctx(VASYA_P)
    t = make_tools(evo, ctx, settings)
    with pytest.raises(ToolError) as err:
        await t["group_manage"]({"action": "close"})
    assert str(err.value) == NOT_ADMIN and "сделайте меня админом группы, тогда смогу" in NOT_ADMIN
    assert evo.changes()[0]["json"] == {"action": "announcement"}


async def test_not_admin_error_after_500_retries(settings, monkeypatch):
    async def fast_sleep(_s):
        return None

    monkeypatch.setattr(evolution_module, "asyncio", types.SimpleNamespace(sleep=fast_sleep))
    body = {"status": 500, "error": "Internal Server Error",
            "response": {"message": ["Error updating group subject", "Error: not-authorized"]}}
    evo = Evo({("POST", "/group/updateGroupSubject/stella"): httpx.Response(500, json=body)})
    t = make_tools(evo, make_ctx(VASYA_P), settings)
    with pytest.raises(ToolError, match="сделайте меня админом группы"):
        await t["group_manage"]({"action": "rename", "value": "x"})


async def test_other_errors_are_not_called_not_admin(settings):
    body = {"status": 404, "error": "Not Found", "response": {"message": ["No invite code", "Error: item-not-found"]}}
    evo = Evo({("GET", "/group/inviteCode/stella"): httpx.Response(404, json=body)})
    t = make_tools(evo, make_ctx(VASYA_P), settings)
    with pytest.raises(ToolError) as err:
        await t["group_manage"]({"action": "invite_link"})
    assert "item-not-found" in str(err.value) and "админом" not in str(err.value)


async def test_bot_not_admin_is_detected_before_kick(settings):
    evo = Evo({("GET", INFO_PATH): httpx.Response(200, json=group_info(bot_admin=False))})
    ctx = make_ctx(VASYA_P)
    t = make_tools(evo, ctx, settings)
    with pytest.raises(ToolError, match="сделайте меня админом"):
        await t["group_manage"]({"action": "kick", "person": "p2"})
    assert evo.changes() == [] and not ctx.side_effects


# ---------- участники ----------
async def test_kick_in_lid_group_uses_participant_id(settings):
    evo = Evo({("GET", INFO_PATH): httpx.Response(200, json=group_info(lid_group=True))})
    t = make_tools(evo, make_ctx(VASYA_P), settings)
    await t["group_manage"]({"action": "kick", "person": "p2"})  # Петя известен по номеру, в группе он LID
    assert evo.changes()[0]["json"] == {"action": "remove", "participants": [PETYA_LID]}


async def test_promote_and_demote(settings):
    evo = Evo()
    t = make_tools(evo, make_ctx(VASYA_P), settings)
    assert await t["group_manage"]({"action": "promote", "person": "p2"}) == "сделала Петя админом группы"
    assert await t["group_manage"]({"action": "demote", "person": "p2"}) == "Петя и так не админ"
    assert await t["group_manage"]({"action": "promote", "person": "я"}) == "Вася и так админ"
    assert [r["json"] for r in evo.changes()] == [{"action": "promote", "participants": [PETYA]}]


async def test_add_by_phone_and_privacy_refusal(settings):
    evo = Evo({("POST", "/group/updateParticipant/stella"): httpx.Response(
        201, json={"updateParticipants": [{"status": "403", "jid": "77044444444@s.whatsapp.net"}]})})
    t = make_tools(evo, make_ctx(VASYA_P), settings)
    with pytest.raises(ToolError, match="ссылку-приглашение"):
        await t["group_manage"]({"action": "add", "value": "+7 (704) 444-44-44"})
    assert evo.changes()[0]["json"] == {"action": "add", "participants": ["77044444444"]}


async def test_add_ok_and_already_member(settings):
    evo = Evo({("POST", "/group/updateParticipant/stella"): httpx.Response(
        201, json={"updateParticipants": [{"status": "200", "jid": "77055555555@s.whatsapp.net"}]})})
    t = make_tools(evo, make_ctx(VASYA_P), settings)
    assert await t["group_manage"]({"action": "add", "person": "77055555555"}) == "добавила +77055555555 в группу"
    assert await t["group_manage"]({"action": "add", "person": "p2"}) == "Петя уже в группе"
    assert len(evo.changes()) == 1


async def test_add_unknown_person_needs_phone(settings, tmp_path):
    db = DB(settings.database_url)
    await db.init()
    try:
        evo = Evo()
        t = make_tools(evo, make_ctx(VASYA_P), settings, db=db)
        with pytest.raises(ToolError, match="номер"):
            await t["group_manage"]({"action": "add", "person": "Незнакомка"})
        with pytest.raises(ToolError, match="номер"):
            await t["group_manage"]({"action": "add"})
        assert evo.changes() == []
        # незнакомку по имени не нашли, но номер дали в value
        await t["group_manage"]({"action": "add", "person": "Незнакомка", "value": "77066666666"})
        assert evo.changes()[0]["json"] == {"action": "add", "participants": ["77066666666"]}
    finally:
        await db.close()


async def test_kick_by_name_from_db(settings):
    db = DB(settings.database_url)
    await db.init()
    try:
        chat = await db.get_or_create_chat("stella", GROUP, True)
        petya = await db.upsert_person(PETYA, "Петя", "77022222222")
        await db.touch_member(chat["id"], petya.id)
        evo = Evo()
        ctx = ToolContext(chat_id=chat["id"], sender=VASYA_P, people_refs={}, is_admin=False)
        t = make_tools(evo, ctx, settings, chat={**GROUP_CHAT, "id": chat["id"]}, db=db)
        assert await t["group_manage"]({"action": "kick", "person": "Петя"}) == "удалила Петя из группы"
        assert evo.changes()[0]["json"]["participants"] == [PETYA]
    finally:
        await db.close()


# ---------- настройки и ссылки ----------
async def test_settings_actions(settings):
    evo = Evo()
    t = make_tools(evo, make_ctx(VASYA_P), settings)
    for action in ("close", "open", "lock_info", "unlock_info"):
        await t["group_manage"]({"action": action})
    assert [r["json"]["action"] for r in evo.changes()] == ["announcement", "not_announcement", "locked", "unlocked"]
    await t["group_manage"]({"action": "describe", "value": "правила: не спамить"})
    assert evo.changes()[-1]["json"] == {"description": "правила: не спамить"}
    with pytest.raises(ToolError, match="value"):
        await t["group_manage"]({"action": "rename"})
    with pytest.raises(ToolError, match="action"):
        await t["group_manage"]({"action": "explode"})


async def test_invite_link_and_revoke(settings):
    evo = Evo({
        ("GET", "/group/inviteCode/stella"): httpx.Response(
            200, json={"inviteUrl": "https://chat.whatsapp.com/" + "A" * 22, "inviteCode": "A" * 22}),
        ("POST", "/group/revokeInviteCode/stella"): httpx.Response(201, json={"revoked": True, "inviteCode": "B" * 22}),
    })
    ctx = make_ctx(VASYA_P)
    t = make_tools(evo, ctx, settings)
    assert (await t["group_manage"]({"action": "invite_link"})).endswith("https://chat.whatsapp.com/" + "A" * 22)
    assert ctx.side_effects is False  # только прочитали
    assert (await t["group_manage"]({"action": "revoke_invite"})).endswith("https://chat.whatsapp.com/" + "B" * 22)
    assert ctx.side_effects is True


# ---------- свой профиль ----------
async def test_set_my_profile_only_for_env_admin(settings):
    evo = Evo()
    ctx = make_ctx(VASYA_P)  # админ группы, но не админ бота
    t = make_tools(evo, ctx, settings)
    with pytest.raises(ToolError, match="владельца"):
        await t["set_my_profile"]({"name": "Хакер"})
    assert evo.requests == [] and not ctx.side_effects


async def test_set_my_profile_name_status_avatar(settings, monkeypatch):
    rendered = []

    def fake_render(svg, w, h):
        rendered.append((svg, w, h))
        return Image.new("RGBA", (w, h), (200, 30, 90, 255))

    monkeypatch.setattr(group_admin.media, "render_svg", fake_render)
    evo = Evo()
    ctx = make_ctx(OWNER_P, is_admin=True)
    t = make_tools(evo, ctx, settings, chat=DM_CHAT)  # и в личке тоже
    long_name = "Стелла ✨ очень-очень длинное имя"
    out = await t["set_my_profile"]({"name": long_name, "status": "на связи", "avatar_svg": "<svg/>"})
    assert out.startswith("готово") and "аватарка" in out and ctx.side_effects
    assert rendered == [("<svg/>", 640, 640)]
    paths = [r["path"] for r in evo.requests]
    assert paths == ["/chat/updateProfileName/stella", "/chat/updateProfileStatus/stella",
                     "/chat/updateProfilePicture/stella"]  # аватарка последней: после неё Evolution переподключается
    assert evo.requests[0]["json"] == {"name": long_name[:25]}  # WhatsApp: имя до 25 символов
    img = Image.open(io.BytesIO(base64.b64decode(evo.requests[2]["json"]["picture"], validate=True)))
    assert img.format == "JPEG" and img.size == (640, 640)


async def test_set_my_profile_bad_svg_changes_nothing(settings, monkeypatch):
    def broken(svg, w, h):
        raise group_admin.media.MediaError("не получилось нарисовать SVG: syntax error")

    monkeypatch.setattr(group_admin.media, "render_svg", broken)
    evo = Evo()
    ctx = make_ctx(OWNER_P, is_admin=True)
    t = make_tools(evo, ctx, settings)
    with pytest.raises(ToolError, match="нарисовать SVG"):
        await t["set_my_profile"]({"name": "Стелла", "avatar_svg": "<svg"})
    assert evo.requests == [] and not ctx.side_effects


async def test_set_my_profile_partial_failure(settings):
    evo = Evo({("POST", "/chat/updateProfileStatus/stella"): httpx.Response(
        400, json={"status": 400, "error": "Bad Request", "response": {"message": ["Error: bad-request"]}})})
    t = make_tools(evo, make_ctx(OWNER_P, is_admin=True), settings)
    out = await t["set_my_profile"]({"name": "Стелла", "status": "x"})
    assert out.startswith("готово: имя «Стелла»") and "не вышло: статус" in out
    with pytest.raises(ToolError, match="name, status или avatar_svg"):
        await t["set_my_profile"]({})


def test_avatar_jpeg_real_render():
    pytest.importorskip("cairosvg")
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640">'
           '<circle cx="320" cy="320" r="250" fill="#ff66aa" stroke="#222" stroke-width="20"/></svg>')
    img = Image.open(io.BytesIO(avatar_jpeg(svg)))
    assert img.format == "JPEG" and img.size == (640, 640)
    assert img.getpixel((320, 320))[0] > 200  # розовый круг
    assert min(img.getpixel((5, 5))) >= 245  # прозрачный фон стал белым
