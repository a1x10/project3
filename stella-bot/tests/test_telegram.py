"""Telegram: та же Стелла в личке и группах Telegram, рядом с WhatsApp."""

import asyncio
import json
import random

import httpx
import pytest

from bot import telegram as tgm
from bot.brain import Brain
from bot.db import DB
from bot.telegram import Messenger, Telegram, parse_update

from .conftest import FakeEvolution, FakeLLM, nosleep, settle, upsert

BOT_ID = 8000000001
OWNER_TG = 5550001
VASYA_TG = 5550002
GROUP_ID = -1001234567890


def tg_update(text="", *, chat_id=GROUP_ID, chat_type="supergroup", user_id=VASYA_TG, first="Вася", mid=None,
              update_id=None, **extra):
    tg_update.n = getattr(tg_update, "n", 100) + 1
    m = {"message_id": mid or tg_update.n, "date": int(__import__("time").time()),
         "chat": {"id": chat_id, "type": chat_type, "title": "Друзья"},
         "from": {"id": user_id, "is_bot": False, "first_name": first}}
    if text:
        m["text"] = text
    m.update(extra)
    return {"update_id": update_id or tg_update.n, "message": m}


class FakeBotApi:
    """Подмена api.telegram.org: запоминает вызовы, отвечает как Telegram."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.updates: list[dict] = []
        self.next_id = 500
        self.files = {"FILE_PHOTO": b"\xff\xd8\xff photo", "FILE_VOICE": b"OggS voice"}
        self.fail: dict[str, tuple[int, dict]] = {}

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/file/bot" in path:
            name = path.rsplit("/", 1)[-1]
            return httpx.Response(200, content=self.files.get(name, b""))
        method = path.rsplit("/", 1)[-1]
        ctype = request.headers.get("content-type", "")
        if ctype.startswith("application/json"):
            body = json.loads(request.content or b"{}")
        else:
            body = {"_multipart": True, "_raw": request.content[:4000]}
        self.calls.append((method, body))
        if method in self.fail:
            code, payload = self.fail[method]
            return httpx.Response(code, json=payload)
        if method == "getMe":
            return self.ok({"id": BOT_ID, "is_bot": True, "first_name": "Стелла", "username": "stella_test_bot"})
        if method == "getUpdates":
            await asyncio.sleep(0.02)
            ups, self.updates = self.updates, []
            return self.ok(ups)
        if method == "getFile":
            return self.ok({"file_id": body["file_id"], "file_path": f"photos/{body['file_id']}"})
        if method == "getChat":
            return self.ok({"id": body["chat_id"], "type": "supergroup", "title": "Друзья"})
        if method == "getChatAdministrators":
            return self.ok([{"status": "creator", "user": {"id": OWNER_TG, "is_bot": False, "first_name": "Я"}}])
        if method.startswith("send"):
            self.next_id += 1
            return self.ok({"message_id": self.next_id, "chat": {"id": body.get("chat_id", 0)}})
        return self.ok(True)

    @staticmethod
    def ok(result):
        return httpx.Response(200, json={"ok": True, "result": result})

    def sent(self, method="sendMessage"):
        return [b for m, b in self.calls if m == method]


@pytest.fixture
def api():
    return FakeBotApi()


@pytest.fixture
def tg(api):
    client = Telegram("123:SECRET", client=httpx.AsyncClient(transport=httpx.MockTransport(api.handler)))
    client.bot_id, client.username = BOT_ID, "stella_test_bot"
    return client


@pytest.fixture
async def tbrain(settings, tg):
    settings.telegram_owner_id = str(OWNER_TG)
    evo = FakeEvolution()
    b = Brain(settings, DB(settings.database_url), Messenger(evo, tg), FakeLLM(), rng=random.Random(1), sleep=nosleep)
    b.ambient_quiet = (0.0, 0.0)
    await b.start()
    await b.add_bot_jid(f"{BOT_ID}@tg.user")
    b.wa = evo
    yield b
    await settle(b)
    for t in b._background:
        t.cancel()
    await asyncio.gather(*b._background, return_exceptions=True)
    await b.db.close()


async def feed_tg(brain, *updates):
    for u in updates:
        inc = parse_update(u, bot_id=BOT_ID, bot_username="stella_test_bot", bot_name=brain.s.bot_name)
        if inc is not None:
            await brain.on_message(inc)
    await settle(brain, timeout=10)


# ---------- разбор ----------
def test_parse_group_text_with_mention_and_reply():
    u = tg_update("@stella_test_bot как дела?", entities=[{"type": "mention", "offset": 0, "length": 16}],
                  reply_to_message={"message_id": 42, "from": {"id": BOT_ID, "is_bot": True, "first_name": "S"},
                                    "chat": {"id": GROUP_ID, "type": "supergroup"}, "text": "привет"})
    inc = parse_update(u, bot_id=BOT_ID, bot_username="stella_test_bot", bot_name="Стелла")
    assert inc.chat_jid == f"{GROUP_ID}@tg.chat" and inc.is_group and inc.sender_jid == f"{VASYA_TG}@tg.user"
    assert inc.text == "Стелла как дела?" and f"{BOT_ID}@tg.user" in inc.mentioned
    assert inc.quoted_id == f"tg{GROUP_ID}_42" and inc.quoted_sender == f"{BOT_ID}@tg.user"
    assert inc.msg_id.startswith(f"tg{GROUP_ID}_") and inc.raw_key["remoteJid"] == inc.chat_jid


def test_parse_media_kinds_and_skips():
    p = dict(bot_id=BOT_ID, bot_username="stella_test_bot", bot_name="Стелла")
    photo = parse_update(tg_update(photo=[{"file_id": "small", "width": 90, "height": 90, "file_size": 1000},
                                          {"file_id": "FILE_PHOTO", "width": 800, "height": 800, "file_size": 9000}],
                                   caption="стелла что тут"), **p)
    assert photo.kind == "image" and photo.text == "стелла что тут"
    assert photo.raw_message["tg"]["file_id"] == "FILE_PHOTO" and "imageMessage" in photo.raw_message
    voice = parse_update(tg_update(voice={"file_id": "FILE_VOICE", "duration": 4, "mime_type": "audio/ogg"}), **p)
    assert voice.kind == "audio" and voice.duration == 4
    sticker = parse_update(tg_update(sticker={"file_id": "anim", "is_animated": True,
                                              "thumbnail": {"file_id": "thumb"}}), **p)
    assert sticker.kind == "sticker" and sticker.raw_message["tg"]["file_id"] == "thumb"
    doc = parse_update(tg_update(document={"file_id": "D", "file_name": "план.docx", "file_size": 10}), **p)
    assert doc.raw_message["documentMessage"]["fileName"] == "план.docx"
    assert parse_update(tg_update("hi", user_id=999, first="bot") | {"message": {**tg_update("x")["message"],
                        "from": {"id": 9, "is_bot": True, "first_name": "b"}}}, **p) is None  # чужие боты
    assert parse_update({"update_id": 1, "edited_message": {}}, **p) is None
    assert parse_update(tg_update("x", chat_type="channel"), **p) is None
    start = parse_update(tg_update("/start", chat_id=VASYA_TG, chat_type="private"), **p)
    assert start.is_dm and start.text == "Стелла, привет!"


def test_forum_topic_is_not_a_reply():
    u = tg_update("привет", message_thread_id=7, is_topic_message=True,
                  reply_to_message={"message_id": 7, "chat": {"id": GROUP_ID, "type": "supergroup"},
                                    "forum_topic_created": {"name": "флуд"}})
    inc = parse_update(u, bot_id=BOT_ID, bot_username="stella_test_bot", bot_name="Стелла")
    assert inc.quoted_id is None and inc.raw_key["thread"] == 7


# ---------- клиент ----------
async def test_send_text_reply_mentions_and_thread(tg, api):
    tg.threads[GROUP_ID] = 7
    wa_id = await tg.send_text(f"{GROUP_ID}@tg.chat", "😀 @Вася, привет", quoted={"key": {"id": f"tg{GROUP_ID}_42"}},
                               mentioned=[f"{VASYA_TG}@tg.user|Вася"])
    body = api.sent()[-1]
    assert wa_id == f"tg{GROUP_ID}_{api.next_id}" and body["chat_id"] == GROUP_ID and body["message_thread_id"] == 7
    assert body["reply_parameters"]["message_id"] == 42
    ent = body["entities"][0]
    assert ent["type"] == "text_mention" and ent["user"]["id"] == VASYA_TG
    assert (ent["offset"], ent["length"]) == (3, 5)  # эмодзи — две единицы UTF-16


async def test_media_sticker_voice_poll_reaction(tg, api):
    import base64

    b64 = base64.b64encode(b"data").decode()
    await tg.send_media(f"{GROUP_ID}@tg.chat", "video", b64, "video/mp4", "v.mp4", "подпись",
                        quoted={"key": {"id": f"tg{GROUP_ID}_5"}})
    await tg.send_sticker(f"{GROUP_ID}@tg.chat", b64)
    await tg.send_voice(f"{GROUP_ID}@tg.chat", b64)
    await tg.send_poll(f"{GROUP_ID}@tg.chat", "куда?", ["кино", "парк", "кино"])
    methods = [m for m, _ in api.calls]
    assert methods == ["sendVideo", "sendSticker", "sendVoice", "sendPoll"]
    assert b'"message_id": 5' in api.calls[0][1]["_raw"] or b'"message_id":5' in api.calls[0][1]["_raw"]
    assert api.sent("sendPoll")[0]["options"] == [{"text": "кино"}, {"text": "парк"}]
    await tg.send_reaction({"id": f"tg{GROUP_ID}_5"}, "😂")
    await tg.send_reaction({"id": f"tg{GROUP_ID}_5"}, "🦖")  # не разрешена — тихо пропускаем
    reactions = api.sent("setMessageReaction")
    assert len(reactions) == 1 and reactions[0]["reaction"][0]["emoji"] == "🤣"


async def test_download_and_errors_hide_token(tg, api):
    data = await tg.media_base64({"id": "x"}, {"tg": {"file_id": "FILE_PHOTO"}})
    assert data == b"\xff\xd8\xff photo"
    with pytest.raises(tgm.TelegramError, match="20 МБ"):
        await tg.media_base64({}, {"tg": {"file_id": "big", "size": 50 * 1024 * 1024}})
    api.fail["sendMessage"] = (400, {"ok": False, "description": "Bad Request: chat not found 123:SECRET"})
    with pytest.raises(tgm.TelegramError) as e:
        await tg.send_text("1@tg.chat", "x")
    assert "SECRET" not in str(e.value)


async def test_messenger_routes_by_chat(tg, api):
    evo = FakeEvolution()
    m = Messenger(evo, tg)
    await m.send_text(f"{GROUP_ID}@tg.chat", "в телегу")
    await m.send_text("120363000000000001@g.us", "в вацап")
    assert api.sent()[-1]["text"] == "в телегу" and evo.texts() == ["в вацап"]
    await m.mark_read([{"remoteJid": f"{GROUP_ID}@tg.chat"}])
    assert f"{BOT_ID}@tg.user" in await m.own_jids()
    assert m.instance == evo.instance if hasattr(evo, "instance") else True
    with pytest.raises(tgm.TelegramError):
        await Messenger(evo, None).send_text("1@tg.chat", "x")


# ---------- Стелла в Telegram ----------
async def test_dm_in_telegram_gets_answer_in_telegram(tbrain, api):
    tbrain.llm.queue = ["привет! как ты?"]
    await feed_tg(tbrain, tg_update("привет", chat_id=VASYA_TG, chat_type="private"))
    assert [b["text"] for b in api.sent()] == ["привет! как ты?"] and tbrain.wa.sent == []
    assert "WhatsApp и Telegram" in tbrain.llm.calls[0]["system"]


async def test_group_name_call_and_reply_to_her(tbrain, api):
    tbrain.llm.queue = ["я тут", "ага"]
    await feed_tg(tbrain, tg_update("стелла ты тут?", mid=10))
    first = api.sent()[-1]
    assert first["text"] == "я тут" and first["chat_id"] == GROUP_ID
    her_id = api.next_id
    await feed_tg(tbrain, tg_update("а ты кто вообще?", reply_to_message={
        "message_id": her_id, "from": {"id": BOT_ID, "is_bot": True, "first_name": "Стелла"},
        "chat": {"id": GROUP_ID, "type": "supergroup"}, "text": "я тут"}))
    assert api.sent()[-1]["text"] == "ага"


async def test_telegram_owner_is_recognised(tbrain, api):
    from bot.tools import ToolError  # noqa: F401

    seen = {}

    async def grab(tools, prompt):
        seen.update(tools)
        return "ок"

    tbrain.llm.queue = [grab]
    await feed_tg(tbrain, tg_update("стелла привет", chat_id=OWNER_TG, chat_type="private", user_id=OWNER_TG,
                                    first="Хозяин"))
    assert "run_code" in seen  # владелец по TELEGRAM_OWNER_ID — как OWNER_PHONE в WhatsApp
    assert "group_manage" not in seen and "set_my_profile" not in seen  # это только для WhatsApp


async def test_group_admin_can_pause_in_telegram(tbrain, api):
    await feed_tg(tbrain, tg_update("стелла помолчи", user_id=OWNER_TG, first="Я"))
    chat = await tbrain.db.get_chat_by_jid(tbrain.s.evolution_instance, f"{GROUP_ID}@tg.chat")
    from bot.db import chat_paused

    assert chat_paused(chat)
    assert any(m == "getChatAdministrators" for m, _ in api.calls)


async def test_photo_in_telegram_is_seen(tbrain, api):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 0, 0)).save(buf, "PNG")
    api.files["FILE_PHOTO"] = buf.getvalue()
    tbrain.llm.queue = ["красный квадрат"]
    await feed_tg(tbrain, tg_update(photo=[{"file_id": "FILE_PHOTO", "width": 64, "height": 64, "file_size": 99}],
                                    caption="стелла что это?"))
    assert len(tbrain.llm.calls[0]["images"]) == 1


async def test_whatsapp_still_works_next_to_telegram(tbrain, api):
    tbrain.llm.queue = ["вацап на месте"]
    await tbrain.handle_payload(upsert("стелла привет"))
    await settle(tbrain)
    assert tbrain.wa.texts() == ["вацап на месте"] and api.sent() == []


async def test_owner_alert_goes_to_telegram_when_whatsapp_down(tbrain, api):
    tbrain.connection_state = "close"
    await tbrain.tell_owner("⚠️ проверка")
    assert api.sent()[-1]["chat_id"] == OWNER_TG and api.sent()[-1]["text"] == "⚠️ проверка"


async def test_polling_feeds_messages(tbrain, api, tg):
    tbrain.llm.queue = ["слышу"]
    tg.bot_id = 0  # пусть цикл сам спросит getMe
    api.updates = [tg_update("стелла слышишь?", chat_id=VASYA_TG, chat_type="private", update_id=777)]
    for _ in range(200):
        await asyncio.sleep(0.02)
        if any(b.get("text") == "слышу" for b in api.sent()):
            break
    assert any(b.get("text") == "слышу" for b in api.sent())
    offsets = [b.get("offset") for m, b in api.calls if m == "getUpdates"]
    assert 778 in offsets  # подтвердили полученное (номер — только в памяти, не в базе)


# ---------- после ревью ----------
async def test_typing_does_not_flood(tg, api):
    import time

    started = time.monotonic()
    await tg.send_presence(f"{GROUP_ID}@tg.chat", "composing", 1000)
    assert time.monotonic() - started >= 0.9  # как Evolution: «печатает» длится, а не долбит API в цикле
    assert len([m for m, _ in api.calls if m == "sendChatAction"]) == 1


async def test_flood_wait_then_retry(tg, api, monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(tgm.asyncio, "sleep", fake_sleep)
    api.fail["sendMessage"] = (429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 3}})
    orig = api.handler
    calls = {"n": 0}

    async def handler(request):
        if request.url.path.endswith("/sendMessage"):
            calls["n"] += 1
            if calls["n"] == 2:
                api.fail.pop("sendMessage", None)
        return await orig(request)

    tg._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await tg.send_text(f"{GROUP_ID}@tg.chat", "дошло") is not None
    assert sleeps == [3]


async def test_long_text_is_split_not_cut(tg, api):
    text = ("очень длинная строка. " * 400).strip()
    await tg.send_text(f"{GROUP_ID}@tg.chat", text, quoted={"key": {"id": f"tg{GROUP_ID}_9"}})
    parts = api.sent()
    assert len(parts) == 3 and all(len(p["text"]) <= 4096 for p in parts)
    assert "".join(p["text"].replace(" ", "") for p in parts) == text.replace(" ", "")
    assert "reply_parameters" in parts[0] and "reply_parameters" not in parts[1]


def test_empty_messages_are_dropped():
    p = dict(bot_id=BOT_ID, bot_username="stella_test_bot", bot_name="Стелла")
    assert parse_update(tg_update(dice={"emoji": "🎲", "value": 4}), **p) is None
    assert parse_update(tg_update(migrate_to_chat_id=-100555), **p) is None
    reply = parse_update(tg_update("стелла кто это?", reply_to_message={
        "message_id": 3, "from": {"id": 777, "is_bot": False, "first_name": "Петя"},
        "chat": {"id": GROUP_ID, "type": "supergroup"}, "text": "я"}), **p)
    assert reply.quoted_name == "Петя"


async def test_reply_goes_to_the_topic_where_she_was_asked(tbrain, api):
    tbrain.llm.queue = ["привет\nкак ты"]
    await feed_tg(tbrain, tg_update("стелла привет", message_thread_id=7, is_topic_message=True,
                                    reply_to_message={"message_id": 7, "chat": {"id": GROUP_ID, "type": "supergroup"},
                                                      "forum_topic_created": {"name": "флуд"}}))
    sent = api.sent()
    assert len(sent) == 2 and all(b.get("message_thread_id") == 7 for b in sent)


async def test_strangers_in_telegram_dm_have_a_daily_cap(tbrain, api):
    tbrain.s.telegram_dm_per_day = 2
    tbrain.llm.queue = ["1", "2", "3", "4"]
    for i in range(3):
        await feed_tg(tbrain, tg_update(f"привет {i}", chat_id=VASYA_TG, chat_type="private"))
    assert len(api.sent()) == 2
    await feed_tg(tbrain, tg_update("привет", chat_id=OWNER_TG, chat_type="private", user_id=OWNER_TG, first="Я"))
    assert len(api.sent()) == 3  # владельцу — без лимита


async def test_html_page_goes_to_telegram_as_file(tbrain, api, monkeypatch):
    from bot import html_studio, weblibs

    async def run(settings, brief, title, image=None, build=None):
        return html_studio.StudioResult("<h1>С днём рождения!</h1>", 0.4, 1.0)

    async def no_download(*a, **kw):
        return []

    monkeypatch.setattr(html_studio, "run", run)
    monkeypatch.setattr(weblibs, "ensure", no_download)

    async def make(tools, prompt):
        await tools["make_html"].handler({"title": "Открытка", "brief": "открытка Васе на день рождения, салют"})
        return "делаю открытку, минуты через 3"

    tbrain.llm.queue = [make]
    await feed_tg(tbrain, tg_update("стелла сделай открытку", chat_id=VASYA_TG, chat_type="private", mid=77))
    assert [b["text"] for b in api.sent()] == ["делаю открытку, минуты через 3"]
    doc = api.sent("sendDocument")
    assert len(doc) == 1 and b'filename="' in doc[0]["_raw"] and b"text/html" in doc[0]["_raw"]
    assert b'"message_id": 77' in doc[0]["_raw"] or b'"message_id":77' in doc[0]["_raw"]  # ответом на просьбу
    assert tbrain.wa.sent == []
