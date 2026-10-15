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


async def test_she_can_delete_her_own_last_message(brain):
    async def delete(tools, prompt):
        assert await tools["delete_my_last_message"].handler({}) == "удалила"
        return "сорян, удалила"

    brain.llm.queue = ["упс, не то", delete]
    await feed(brain, upsert("стелла скажи что-нибудь"))
    first_id = brain.evo.sent[0]["id"]
    await feed(brain, upsert("стелла ты чего"))
    deletes = [m for m in brain.evo.sent if m["type"] == "delete"]
    assert deletes and deletes[0]["key"] == {"id": first_id, "remoteJid": GROUP, "fromMe": True}


async def test_delete_command_rules(brain):
    brain.llm.queue = ["моё сообщение"]
    await feed(brain, upsert("стелла привет"))
    mine = brain.evo.sent[-1]["id"]
    # своё — удаляет по просьбе любого
    await feed(brain, upsert("стелла удали", quoted={"stanzaId": mine, "participant": BOT,
                                                      "quotedMessage": {"conversation": "моё сообщение"}}))
    assert brain.evo.sent[-2]["type"] == "delete" and brain.evo.sent[-1]["text"] == "удалила 🫡"
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


async def test_initiative_respects_activity_and_rate(brain):
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
