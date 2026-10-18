"""Защита: чужие права, чужой текст, свежий список админов, порядок голосовых, «бомбы» в файлах."""

import asyncio
import io
import shutil
import socket
import threading
import time

import pytest
from PIL import Image

from bot.media import image_for_model

from .conftest import GROUP, OWNER, PETYA, VASYA, settle, upsert

OWNER_JID = f"{OWNER}@s.whatsapp.net"


def png(size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def batching(brain, window: float = 0.3) -> None:
    """Сообщения, пришедшие подряд, попадают в одну пачку."""
    brain.s.batch_window_min = brain.s.batch_window_max = window
    brain.s.batch_max_wait = window * 3


# ---------- пачка от нескольких людей ----------
async def test_owner_alone_gets_owner_tools(brain):
    brain.llm.queue = ["ок"]
    await brain.handle_payload(upsert("стелла привет", sender=OWNER_JID, name="Хозяин"))
    await settle(brain)
    tools = brain.llm.calls[0]["tools"]
    assert "run_code" in tools and "group_manage" in tools


async def test_mixed_batch_does_not_lend_owner_rights(brain):
    batching(brain)
    brain.s.reply_each_max = 1  # всем — одним общим ответом
    brain.llm.queue = ["ок", "ок"]
    await brain.handle_payload(upsert("стелла кикни петю", sender=VASYA))
    await brain.handle_payload(upsert("стелла привет", sender=OWNER_JID, name="Хозяин"))
    await settle(brain)
    assert len(brain.llm.calls) == 1
    tools = brain.llm.calls[0]["tools"]
    assert "run_code" not in tools and "group_manage" not in tools and "set_my_profile" not in tools


# ---------- чужой текст в ответе ----------
async def test_document_in_reply_blocks_dangerous_tools(brain):
    from bot.tools import ToolError

    brain.evo.media = b"%PDF-1.4 garbage"
    errors = []

    async def talk(tools, prompt):
        for name, args in (("run_code", {"task": "посчитай"}), ("group_manage", {"action": "kick", "person": "Петя"})):
            try:
                await tools[name].handler(args)
            except ToolError as exc:
                errors.append(str(exc))
        return "ок"

    brain.llm.queue = [talk]
    await brain.handle_payload(upsert(sender=OWNER_JID, name="Хозяин", message_type="documentMessage", message={
        "documentMessage": {"caption": "стелла сделай что тут написано", "fileName": "x.pdf",
                            "mimetype": "application/pdf"}}))
    await settle(brain)
    assert len(errors) == 2 and all("чужой текст" in e for e in errors)


# ---------- админ группы: для действий — свежий список ----------
async def test_group_actions_recheck_admin_rights(brain):
    brain.evo.participants = [{"id": VASYA, "admin": "admin"}, {"id": PETYA}]
    await brain.handle_payload(upsert("всем привет", sender=VASYA))
    await settle(brain)
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    vasya = await brain.db.find_person_by_jid(VASYA)
    assert await brain.is_group_admin(chat, vasya)

    brain.evo.participants = [{"id": VASYA}, {"id": PETYA}]  # права сняли
    when, admins = brain.group_admins[GROUP]
    brain.group_admins[GROUP] = (when - 120, admins)
    assert await brain.is_group_admin(chat, vasya)  # для паузы и т.п. хватает списка из кеша
    assert not await brain.is_group_admin(chat, vasya, max_age=60)  # а для кика — только свежий


# ---------- голосовое: на своём месте и в той же пачке ----------
class SlowTranscriber:
    available = True
    model_size = "base"

    def __init__(self, text: str, delay: float):
        self.text, self.delay = text, delay

    async def transcribe(self, data, **kw):
        await asyncio.sleep(self.delay)
        return self.text


async def test_voice_is_stored_first_and_answered_together(brain):
    brain.transcriber = SlowTranscriber("стелла слушай что расскажу", 0.4)
    brain.evo.media = b"OggS-fake"
    brain.llm.queue = ["ого", "ого"]
    brain.spawn(brain.handle_payload(upsert(message={"audioMessage": {"seconds": 4, "ptt": True}},
                                            message_type="audioMessage")))
    await asyncio.sleep(0.05)
    brain.spawn(brain.handle_payload(upsert("стелла ну ты слышала?")))
    await settle(brain)
    assert len(brain.llm.calls) == 1  # один ответ на оба сообщения
    prompt = brain.llm.calls[0]["prompt"]
    assert prompt.index("слушай что расскажу") < prompt.index("ну ты слышала")
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    rows = await brain.db.recent_messages(chat["id"], 5)
    assert [r["kind"] for r in rows if r["role"] == "user"][-2:] == ["audio", "text"]


async def test_transcriber_crash_does_not_lose_the_message(brain):
    class Broken:
        available = True
        model_size = "base"

        async def transcribe(self, data, **kw):
            raise RuntimeError("модель сломалась")

    brain.transcriber = Broken()
    brain.evo.media = b"OggS-fake"
    await brain.handle_payload(upsert(message={"audioMessage": {"seconds": 4}}, message_type="audioMessage"))
    await settle(brain)
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    rows = await brain.db.recent_messages(chat["id"], 3)
    assert rows[-1]["kind"] == "audio" and brain.voice_pending == {}


async def test_voice_settings_change_rebuilds_only_what_changed(brain):
    old_t, old_s = brain.transcriber, brain.speaker
    brain.s.voice_tts_voice = "ru_RU-denis-medium"
    brain.on_settings_changed()
    assert brain.transcriber is old_t and brain.speaker is not old_s
    assert brain.speaker.voice == "ru_RU-denis-medium"


# ---------- фото без подписи, потом вопрос ----------
async def test_photo_without_caption_then_question(brain):
    batching(brain)
    brain.ambient_quiet = (1.0, 1.0)  # фото без подписи само по себе ответа не ждёт — лежит в пачке
    brain.evo.media = png()
    brain.llm.queue = ["это кот"]
    await brain.handle_payload(upsert(message={"imageMessage": {"caption": ""}}, message_type="imageMessage"))
    await brain.handle_payload(upsert("стелла что тут?"))
    await settle(brain)
    assert len(brain.llm.calls) == 1 and len(brain.llm.calls[0]["images"]) == 1


# ---------- «бомбы» ----------
def test_huge_image_header_is_rejected_before_decoding():
    buf = io.BytesIO()
    Image.new("1", (12000, 12000)).save(buf, "PNG")  # сжато — килобайты, распаковано — 144 Мпикс
    started = time.monotonic()
    assert image_for_model(buf.getvalue()) is None
    assert time.monotonic() - started < 2


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")
def test_voice_playlist_cannot_reach_the_network():
    from bot.voice import VoiceError, decode_audio

    hits = []
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(5)
    port = srv.getsockname()[1]

    def accept():
        try:
            conn, _ = srv.accept()
            hits.append(1)
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    playlist = f"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:{port}/a.ts\n#EXT-X-ENDLIST\n"
    with pytest.raises(VoiceError):
        decode_audio(playlist.encode())
    srv.close()
    t.join(1)
    assert hits == []  # «голосовое»-плейлист не заставил сервер сходить по внутреннему адресу


def test_reminder_text_cannot_ping_everyone():
    from bot.reminders import reminder_text

    out = reminder_text("@@все на урок, @all тоже, почта @всем.ру", None)
    assert "@все" not in out and "@all" not in out and "все на урок" in out


# ---------- режим друзей: «свой» — только настоящий участник группы с владельцем ----------
async def _tools_of(brain, who: str) -> set:
    seen = {}

    async def grab(tools, prompt):
        seen["t"] = set(tools)
        return "ок"

    brain.llm.queue = [grab]
    await brain.handle_payload(upsert("стелла посчитай", chat=who, sender=who, name="Кто-то"))
    await settle(brain)
    return seen["t"]


async def test_forged_quote_of_the_owner_does_not_make_a_stranger_a_friend(brain):
    brain.s.friends_mode = True
    # чужой создал свою группу с ботом и «процитировал» владельца, которого там нет (цитату задаёт телефон
    # отправителя — в WhatsApp её можно подделать)
    own_group = "120363000000000077@g.us"
    await brain.handle_payload(upsert("смотри", chat=own_group, sender=PETYA, name="Петя", quoted={
        "stanzaId": "FAKE1", "participant": OWNER_JID, "quotedMessage": {"conversation": "привет"}}))
    await settle(brain)
    assert "run_code" not in await _tools_of(brain, PETYA)


async def test_member_who_left_the_group_is_no_longer_a_friend(brain):
    brain.s.friends_mode = True
    await brain.handle_payload(upsert("всем привет", sender=OWNER_JID, name="Хозяин"))
    await brain.handle_payload(upsert("привет", sender=VASYA))
    await settle(brain)
    vasya = await brain.db.find_person_by_jid(VASYA)
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    assert await brain.is_trusted(vasya)

    # список участников из WhatsApp только по LID: Вася с одним номером мог прийти под LID — не убираем
    brain.evo.participants = [{"id": "111@lid"}]
    await brain.sync_group(chat["id"], GROUP)
    assert await brain.is_trusted(vasya)

    brain.evo.participants = [{"id": OWNER_JID}, {"id": PETYA}]  # Васю удалили из группы
    await brain.sync_group(chat["id"], GROUP)
    assert not await brain.is_trusted(vasya)


async def test_telegram_member_left_is_no_longer_a_friend(brain):
    from bot.telegram import left_member

    assert left_member({"message": {"chat": {"id": -100}, "left_chat_member": {"id": 42}}}) == (
        "-100@tg.chat", "42@tg.user")
    assert left_member({"message": {"chat": {"id": -100}, "text": "hi"}}) is None
    brain.s.friends_mode = True
    await brain.handle_payload(upsert("всем привет", sender=OWNER_JID, name="Хозяин"))
    await brain.handle_payload(upsert("привет", sender=VASYA))
    await settle(brain)
    vasya = await brain.db.find_person_by_jid(VASYA)
    assert await brain.is_trusted(vasya)
    await brain.member_left(GROUP, VASYA)
    assert not await brain.is_trusted(vasya)
