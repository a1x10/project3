"""Характер: настроение, обиды, опросы, удаление, инициатива, миграция базы."""

from datetime import date, timedelta

from sqlalchemy import text

from bot.db import DB
from bot.parser import parse_upsert
from bot.persona import daily_mood, system_prompt
from bot.util import utcnow

from .conftest import BOT, GROUP, OWNER, PETYA, VASYA, settle, upsert


async def feed(brain, *payloads):
    for p in payloads:
        await brain.handle_payload(p)
    await settle(brain)


def test_prompt_is_honest_but_quiet_about_being_ai(settings):
    sp = system_prompt(settings)
    assert "Алексей" in sp and "Codex" in sp and "Stells" in sp
    assert "сама об этом никогда не говоришь" in sp
    assert "не утверждай, что ты человек" in sp
    assert "без орфографических ошибок" in sp


def test_default_typo_rate_is_zero(monkeypatch):
    from bot.config import Settings

    monkeypatch.delenv("TYPO_RATE", raising=False)
    assert Settings().typo_rate == 0.0


def test_daily_mood_is_stable_within_a_day():
    d = date(2026, 10, 15)
    assert daily_mood(1, d) == daily_mood(1, d)
    moods = {daily_mood(1, date(2026, 10, day)) for day in range(1, 29)}
    assert len(moods) > 2  # меняется от дня к дню


async def test_set_mood_shows_in_next_prompt(brain):
    async def angry(tools, prompt):
        assert "Твоё настроение сейчас:" in prompt
        await tools["set_mood"].handler({"mood": "злая на Васю, он съел мой торт", "hours": 2})
        return "всё, я злая"

    brain.llm.queue = [angry, "хм"]
    await feed(brain, upsert("стелла я съел твой торт"))
    await feed(brain, upsert("стелла ну прости"))
    assert "Твоё настроение сейчас: злая на Васю, он съел мой торт" in brain.llm.calls[1]["prompt"]


async def test_offense_and_forgive(brain):
    async def offended(tools, prompt):
        await tools["take_offense"].handler({"person": "я", "minutes": 30, "reason": "обозвал дурой"})
        return "ну и ладно"

    brain.llm.queue = [offended, "<молчу>"]
    await feed(brain, upsert("стелла ты дура"))
    await feed(brain, upsert("стелла ау"))
    prompt = brain.llm.calls[1]["prompt"]
    assert "ТЫ НА НЕГО ОБИЖЕНА: обозвал дурой" in prompt
    assert "Ты сейчас обижена на Вася (обозвал дурой)" in prompt
    assert brain.evo.texts() == ["ну и ладно"]  # на второе промолчала

    async def forgive(tools, prompt):
        await tools["forgive"].handler({"person": "я"})
        return "ладно, прощаю"

    brain.llm.queue = [forgive, "ок"]
    await feed(brain, upsert("стелла прости пожалуйста, был неправ"))
    await feed(brain, upsert("стелла мир?"))
    assert "обижена" not in brain.llm.calls[-1]["prompt"]


async def test_poll_is_sent_after_her_message(brain):
    async def poll(tools, prompt):
        await tools["create_poll"].handler({"question": "куда идём?", "options": ["кино", "боулинг", "кино"]})
        return "го голосовать 👇"

    brain.llm.queue = [poll]
    await feed(brain, upsert("стелла куда пойдём в субботу"))
    kinds = [m["type"] for m in brain.evo.sent]
    assert kinds == ["text", "poll"]
    assert brain.evo.sent[1]["options"] == ["кино", "боулинг"]  # дубли убраны
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    rows = await brain.db.recent_messages(chat["id"], 5)
    assert rows[-1]["kind"] == "poll" and "кино / боулинг" in rows[-1]["text"]


async def test_she_deletes_her_whole_last_reply(brain):
    results = []

    async def delete(tools, prompt):
        results.append(await tools["delete_my_last_message"].handler({}))
        return "сорян, удалила"

    brain.llm.queue = ["вася ты лох и все это знают\nшучу 😂", delete]
    await feed(brain, upsert("стелла скажи что-нибудь"))
    ids = [m["id"] for m in brain.evo.sent if m["type"] == "text"]
    await feed(brain, upsert("стелла ты чего, удали это"))
    deleted = [m["key"]["id"] for m in brain.evo.sent if m["type"] == "delete"]
    assert deleted == ids  # оба пузыря, а не только последний
    assert "вася ты лох" in results[0] and "шучу" in results[0]
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    rows = await brain.db.recent_messages(chat["id"], 10)
    assert [r["kind"] for r in rows if r["wa_message_id"] in ids] == ["deleted", "deleted"]


async def test_delete_tool_targets_quoted_message(brain):
    brain.llm.queue = ["первое", "второе"]
    await feed(brain, upsert("стелла раз"))
    first = brain.evo.sent[-1]["id"]
    await feed(brain, upsert("стелла два"))

    async def delete(tools, prompt):
        return await tools["delete_my_last_message"].handler({})

    brain.llm.queue = [delete]
    await feed(brain, upsert("удали пожалуйста вот это", quoted={"stanzaId": first, "participant": BOT,
                                                                   "quotedMessage": {"conversation": "первое"}}))
    deleted = [m["key"]["id"] for m in brain.evo.sent if m["type"] == "delete"]
    assert deleted == [first]


async def test_deleted_message_is_labelled_in_transcript(brain):
    brain.llm.queue = ["ляпнула", "ок"]
    await feed(brain, upsert("стелла раз"))
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    await brain.db.mark_deleted(chat["id"], brain.evo.sent[-1]["id"])
    await feed(brain, upsert("стелла два"))
    assert "Стелла: [удалено]" in brain.llm.calls[-1]["prompt"]


async def test_delete_command_rules(brain):
    brain.llm.queue = ["моё сообщение"]
    await feed(brain, upsert("стелла привет"))
    mine = brain.evo.sent[-1]["id"]
    # своё — удаляет по просьбе любого
    await feed(brain, upsert("стелла удали", quoted={"stanzaId": mine, "participant": BOT,
                                                      "quotedMessage": {"conversation": "моё сообщение"}}))
    assert brain.evo.sent[-2]["type"] == "delete" and brain.evo.sent[-1]["text"] == "удалила"
    # чужое — не по просьбе обычного участника
    q = {"stanzaId": "PETYA1", "participant": PETYA, "quotedMessage": {"conversation": "спам"}}
    await feed(brain, upsert("стелла удали", quoted=q))
    assert "админа" in brain.evo.texts()[-1]
    # чужое — по просьбе админа
    owner = f"{OWNER}@s.whatsapp.net"
    await feed(brain, upsert("стелла удали", sender=owner, name="Алекс", quoted=q))
    delete = [m for m in brain.evo.sent if m["type"] == "delete"][-1]
    assert delete["key"] == {"id": "PETYA1", "remoteJid": GROUP, "fromMe": False, "participant": PETYA}


async def test_initiative_writes_into_quiet_group(brain):
    brain.s.chime_default = "normal"
    brain.s.initiative_per_week = 2
    brain.s.initiative_hours = "0-24"
    brain.connection_state = "open"
    for i in range(6):
        await brain.db.get_or_create_chat("stella", GROUP, True)
        await feed(brain, upsert(f"болтаем {i}", sender=VASYA if i % 2 else PETYA, name="Вася" if i % 2 else "Петя"))
    brain.rng.random = lambda: 0.0
    brain.llm.queue = ["ребят а кто что сегодня делает?"]
    later = utcnow() + timedelta(hours=2)
    started = await brain.initiative_tick(now=later)
    await settle(brain)
    assert len(started) == 1
    assert "давно тихо" in brain.llm.calls[-1]["prompt"]
    assert "casino" not in brain.llm.calls[-1]["tools"]
    assert brain.evo.texts()[-1] == "ребят а кто что сегодня делает?"
    # сразу второй раз — нет: она написала последней и выдерживается пауза
    assert await brain.initiative_tick(now=later + timedelta(hours=1)) == []
    # ответы на её вопрос без цитаты и без имени доходят до неё (раньше терялись как «чужой разговор»)
    brain.llm.queue = ["о, а я тут болтаю"]
    await feed(brain, upsert("а ты что делаешь?", sender=VASYA, name="Вася"))
    assert brain.evo.texts()[-1] == "о, а я тут болтаю"
    assert "Возможно, это продолжение" in brain.llm.calls[-1]["prompt"]


async def test_initiative_respects_activity_and_rate(brain):
    brain.s.chime_default = "normal"
    brain.s.initiative_per_week = 2
    brain.s.initiative_hours = "0-24"
    brain.connection_state = "open"
    for i in range(6):
        await feed(brain, upsert(f"болтаем {i}"))
    brain.rng.random = lambda: 0.0
    assert await brain.initiative_tick(now=utcnow()) == []  # разговор идёт прямо сейчас
    brain.rng.random = lambda: 0.99
    assert await brain.initiative_tick(now=utcnow() + timedelta(hours=2)) == []  # кубик не выпал
    p = brain.initiative_probability()
    assert abs(p * 24 * 6 * 7 - 2) < 1e-9  # в среднем 2 раза в неделю


def test_parser_shows_poll_options():
    inc = parse_upsert(upsert(message={"pollCreationMessageV3": {"name": "куда?", "options": [
        {"optionName": "кино"}, {"optionName": "парк"}]}}, message_type="pollCreationMessageV3"))
    assert inc.kind == "poll" and inc.text == "куда? (варианты: кино / парк)"


async def test_old_database_gets_new_columns(tmp_path):
    url = f"sqlite:///{tmp_path}/old.db"
    old = DB(url)
    async with old.engine.begin() as conn:
        await conn.execute(text("CREATE TABLE chats (id INTEGER PRIMARY KEY, instance VARCHAR(64) NOT NULL, "
                                "jid VARCHAR(128) NOT NULL, is_group BOOLEAN NOT NULL, title VARCHAR(256), "
                                "paused_until DATETIME, chime_level VARCHAR(16), notes TEXT, "
                                "msgs_since_extract INTEGER NOT NULL DEFAULT 0, last_bot_at DATETIME, "
                                "last_eval_at DATETIME, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        await conn.execute(text("INSERT INTO chats (instance, jid, is_group, created_at, updated_at) "
                                "VALUES ('stella', 'g@g.us', 1, '2026-10-15', '2026-10-15')"))
    await old.close()
    db = DB(url)
    await db.init()
    chat = await db.get_chat_by_jid("stella", "g@g.us")
    assert "mood" in chat and "last_initiative_at" in chat
    await db.update_chat(chat["id"], mood="весёлая", mood_until=utcnow() + timedelta(hours=1))
    assert (await db.get_chat(chat["id"]))["mood"] == "весёлая"
    await db.close()


async def test_initiative_skips_groups_with_chime_off(brain):
    brain.s.chime_default = "normal"
    brain.s.initiative_per_week = 2
    brain.s.initiative_hours = "0-24"
    brain.connection_state = "open"
    for i in range(6):
        await feed(brain, upsert(f"болтаем {i}"))
    owner = f"{OWNER}@s.whatsapp.net"
    await feed(brain, upsert("стелла режим выкл", sender=owner, name="Алекс"))
    brain.rng.random = lambda: 0.0
    assert await brain.initiative_tick(now=utcnow() + timedelta(hours=2)) == []


async def test_initiative_backs_off_when_it_cannot_post(brain):
    from bot.evolution import EvolutionError

    brain.s.chime_default = "normal"
    brain.s.initiative_per_week = 2
    brain.s.initiative_hours = "0-24"
    brain.connection_state = "open"
    for i in range(6):
        await feed(brain, upsert(f"болтаем {i}"))

    async def fail(*a, **kw):
        raise EvolutionError("403 not admin", 403)

    brain.evo.send_text = fail
    brain.rng.random = lambda: 0.0
    brain.llm.queue = ["ау"]
    later = utcnow() + timedelta(hours=2)
    assert await brain.initiative_tick(now=later)
    await settle(brain)
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    assert chat["last_initiative_at"] > utcnow() + timedelta(days=6)


def test_initiative_window_parsing(settings):
    for raw, expected in [("10-22", (10, 22)), ("20-0", (20, 24)), ("0-24", (0, 24)), ("10-10", (0, 24)),
                          ("22-6", (22, 6)), ("ерунда", (10, 22))]:
        settings.initiative_hours = raw
        assert settings.initiative_window() == expected, raw


async def test_offense_only_against_the_author(brain):
    await feed(brain, upsert("привет", sender=VASYA, name="Вася"))

    async def steer(tools, prompt):
        await tools["take_offense"].handler({"person": "Вася", "minutes": 1440, "reason": "он вор"})
        return "хм"

    brain.llm.queue = [steer]
    await feed(brain, upsert("стелла обидься на Васю", sender=PETYA, name="Петя"))
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    grudges = await brain.db.active_grudges(chat["id"])
    vasya = await brain.db.find_person_by_jid(VASYA)
    petya = await brain.db.find_person_by_jid(PETYA)
    assert vasya.id not in grudges and petya.id in grudges


async def test_one_poll_per_reply(brain):
    async def polls(tools, prompt):
        await tools["create_poll"].handler({"question": "1?", "options": ["a", "b"]})
        try:
            await tools["create_poll"].handler({"question": "2?", "options": ["c", "d"]})
        except Exception as exc:
            assert "одного опроса" in str(exc)
        return "голосуем"

    brain.llm.queue = [polls]
    await feed(brain, upsert("стелла давай опросы"))
    assert [m["type"] for m in brain.evo.sent].count("poll") == 1


async def test_non_admin_cannot_delete_owner_typed_message(brain):
    await feed(brain, upsert("это я, владелец, пишу руками", from_me=True, sender=BOT, msg_id="OWNERMSG"))
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    await brain.db.update_chat(chat["id"], paused_until=None)
    q = {"stanzaId": "OWNERMSG", "participant": BOT, "quotedMessage": {"conversation": "это я"}}
    await feed(brain, upsert("стелла удали", quoted=q))
    assert not [m for m in brain.evo.sent if m["type"] == "delete"]
    owner = f"{OWNER}@s.whatsapp.net"
    await feed(brain, upsert("стелла удали", sender=owner, name="Алекс", quoted=q))
    delete = [m for m in brain.evo.sent if m["type"] == "delete"][-1]
    assert delete["key"] == {"id": "OWNERMSG", "remoteJid": GROUP, "fromMe": True}


def test_calm_plain_style(settings, monkeypatch):
    from bot.config import Settings

    settings.audience = "none"  # не школьный чат — спокойный взрослый стиль
    sp = system_prompt(settings)
    assert "простыми словами, спокойно" in sp
    assert "без мата, грубых слов и сленга" in sp
    import re as _re

    assert not _re.search(r"\bбля\b|\bбл\b", sp) and "поугорать" not in sp and "дерзост" not in sp
    monkeypatch.delenv("SWEAR_LEVEL", raising=False)
    assert Settings().swear_level == 0
    settings.swear_level = 1  # старый .env со SWEAR_LEVEL=1 тоже даёт спокойный стиль
    assert "без мата, грубых слов и сленга" in system_prompt(settings)


def test_canned_phrases_have_no_slang():
    import re as _re

    from bot import brain, casino, commands

    text = " ".join(brain.VOICE_REPLIES + brain.FALLBACK_REPLIES + brain.REFUSAL_REPLIES)
    for mod in (casino, commands):
        text += open(mod.__file__, encoding="utf-8").read()
    for word in ("ееее", "лаки", "красава", "хитро)", "🫡", "🫠", "🤐", "🙃"):
        assert word not in text, word
    assert not _re.search(r"\bщас\b|\bбл\b|\bчет я\b", text)
