"""Напоминания: разбор местного времени, ошибки, права, повторы, отправка с настоящей отметкой и инструменты."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect

import bot.brain as brain_module
from bot.db import metadata
from bot.evolution import EvolutionError
from bot.reminders import MAX_ACTIVE_PER_CHAT, Reminders, build_reminder_tools, reminder_loop, run_due
from bot.tools import ToolContext, ToolError

from .conftest import GROUP, PETYA, VASYA, settle, upsert

KOLYA = "77033333333@s.whatsapp.net"
NOW = datetime(2026, 10, 16, 9, 0)  # UTC; в Москве пятница 12:00


async def feed(brain, *payloads):
    for p in payloads:
        await brain.handle_payload(p)
    await settle(brain)


async def setup_chat(brain, tz="Europe/Moscow"):
    brain.s.timezone = tz
    chat = await brain.db.get_or_create_chat(brain.s.evolution_instance, GROUP, True)
    people = {}
    for jid, name in ((VASYA, "Вася"), (PETYA, "Петя"), (KOLYA, "Коля")):
        p = await brain.db.upsert_person(jid, name, jid.split("@")[0])
        await brain.db.touch_member(chat["id"], p.id)
        people[name] = p
    return chat, people, Reminders(brain.db, brain.s)


def tools_for(brain, chat, sender, *, admin=False):
    ctx = ToolContext(chat_id=chat["id"], sender=sender, people_refs={}, is_admin=admin)
    return {t.name: t for t in build_reminder_tools(brain.db, brain.s, ctx)}


def local_str(tz: str, days: int = 1, hm: str = "08:00") -> str:
    """Дата через days дней по местному времени, как её передала бы модель."""
    return (datetime.now(ZoneInfo(tz)) + timedelta(days=days)).strftime(f"%Y-%m-%d {hm}")


# ---------- таблица и время ----------
async def test_table_is_created_by_db_init(brain):
    assert "reminders" in metadata.tables
    async with brain.db.engine.connect() as conn:
        names = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert "reminders" in names


async def test_add_converts_local_time_to_utc(brain):
    chat, ppl, rem = await setup_chat(brain)
    vasya = ppl["Вася"]
    rid = await rem.add(chat["id"], vasya.id, vasya.id, "контрольная", "2026-10-17 08:00", None, now=NOW)
    row = await rem.get(chat["id"], rid)
    assert row["due_at"] == datetime(2026, 10, 17, 5, 0)  # Москва = UTC+3
    assert row["person_id"] == vasya.id and row["created_by"] == vasya.id and row["done"] is False
    [item] = await rem.list_active(chat["id"], now=NOW)
    assert item["at"] == "17.10 в 08:00" and item["local"] == "2026-10-17 08:00" and item["when"] == "17.10 в 08:00"

    # другие форматы и datetime: без пояса — местное, с поясом — как есть
    assert rem.parse_local("2026-10-17T08:00") == datetime(2026, 10, 17, 5, 0)
    assert rem.parse_local("17.10.2026 08:00") == datetime(2026, 10, 17, 5, 0)
    assert rem.parse_local(datetime(2026, 10, 17, 8, 0)) == datetime(2026, 10, 17, 5, 0)
    assert rem.parse_local(datetime(2026, 10, 17, 8, 0, tzinfo=timezone.utc)) == datetime(2026, 10, 17, 8, 0)
    with pytest.raises(ValueError, match="ГГГГ-ММ-ДД"):
        rem.parse_local("завтра в 8")

    # часовой пояс бота по умолчанию — Алматы
    brain.s.timezone = "Asia/Almaty"
    expected = datetime(2026, 10, 17, 8, 0, tzinfo=ZoneInfo("Asia/Almaty")).astimezone(timezone.utc)
    assert rem.parse_local("2026-10-17 08:00") == expected.replace(tzinfo=None)
    # год показываем, только если он не текущий
    assert rem.fmt_at(datetime(2027, 1, 5, 3, 0), now=NOW) == "05.01.2027 в 08:00"


async def test_add_rejects_past_far_empty_and_bad_repeat(brain):
    chat, ppl, rem = await setup_chat(brain)
    pid = ppl["Вася"].id
    with pytest.raises(ValueError, match="уже прошло"):
        await rem.add(chat["id"], pid, pid, "x", "2026-10-16 11:00", None, now=NOW)
    # минута расхождения часов — не ошибка
    assert await rem.add(chat["id"], pid, pid, "сейчас", "2026-10-16 12:00", None, now=NOW + timedelta(seconds=40))
    with pytest.raises(ValueError, match="год"):
        await rem.add(chat["id"], pid, pid, "x", "2027-10-20 08:00", None, now=NOW)
    assert await rem.add(chat["id"], pid, pid, "через полгода", "2027-04-16 12:00", None, now=NOW)
    with pytest.raises(ValueError, match="о чём"):
        await rem.add(chat["id"], pid, pid, "   ", "2026-10-17 08:00", None, now=NOW)
    with pytest.raises(ValueError, match="repeat"):
        await rem.add(chat["id"], pid, pid, "x", "2026-10-17 08:00", "monthly", now=NOW)


async def test_limit_per_chat_and_no_duplicates(brain):
    chat, ppl, rem = await setup_chat(brain)
    pid = ppl["Вася"].id
    first = await rem.add(chat["id"], pid, pid, "дз", "2026-10-17 08:00", None, now=NOW)
    assert await rem.add(chat["id"], pid, pid, "дз", "2026-10-17 08:00", None, now=NOW) == first  # не дублируем
    for i in range(1, MAX_ACTIVE_PER_CHAT):
        await rem.add(chat["id"], pid, pid, f"дело {i}", "2026-10-17 08:00", None, now=NOW)
    with pytest.raises(ValueError, match=str(MAX_ACTIVE_PER_CHAT)):
        await rem.add(chat["id"], pid, pid, "лишнее", "2026-10-17 08:00", None, now=NOW)
    other = await brain.db.get_or_create_chat(brain.s.evolution_instance, "120363000000000002@g.us", True)
    assert await rem.add(other["id"], pid, pid, "в другом чате можно", "2026-10-17 08:00", None, now=NOW)
    assert await rem.cancel(chat["id"], first)
    assert await rem.add(chat["id"], pid, pid, "теперь влезло", "2026-10-17 08:00", None, now=NOW)


async def test_repeat_with_past_time_starts_from_next_time(brain):
    chat, ppl, rem = await setup_chat(brain)
    pid = ppl["Вася"].id
    # «каждый день в 7:30», а уже полдень — первый раз завтра
    rid = await rem.add(chat["id"], pid, pid, "зарядка", "2026-10-16 07:30", "daily", now=NOW)
    assert rem.to_local((await rem.get(chat["id"], rid))["due_at"]) == datetime(2026, 10, 17, 7, 30)
    # «по будням» с субботы — начинаем с понедельника
    rid = await rem.add(chat["id"], pid, pid, "школа", "2026-10-17 07:00", "weekdays", now=NOW)
    row = await rem.get(chat["id"], rid)
    assert rem.to_local(row["due_at"]) == datetime(2026, 10, 19, 7, 0)
    assert rem.fmt_when(row, now=NOW) == "по будням в 07:00 (ближайший — 19.10)"
    rid = await rem.add(chat["id"], pid, pid, "физра", "2026-10-19 07:30", "weekly", now=NOW)
    assert rem.fmt_when(await rem.get(chat["id"], rid), now=NOW) == "каждый понедельник в 07:30 (ближайший — 19.10)"
    # повтор, но дата давно в прошлом — это ошибка, а не «догнать»
    with pytest.raises(ValueError, match="уже прошло"):
        await rem.add(chat["id"], pid, pid, "x", "2026-09-01 07:30", "daily", now=NOW)


# ---------- срабатывание и повторы ----------
async def test_due_and_mark_sent_one_off(brain):
    chat, ppl, rem = await setup_chat(brain)
    pid = ppl["Вася"].id
    rid = await rem.add(chat["id"], pid, pid, "контрольная", "2026-10-16 12:30", None, now=NOW)
    assert await rem.due(NOW) == []
    [row] = await rem.due(NOW + timedelta(minutes=31))
    assert row["id"] == rid
    assert await rem.mark_sent(row, NOW + timedelta(minutes=31)) is None
    assert (await rem.get(chat["id"], rid))["done"] is True
    assert await rem.due(NOW + timedelta(days=1)) == []
    assert await rem.list_active(chat["id"]) == []


@pytest.mark.parametrize("repeat, expected", [
    ("daily", datetime(2026, 10, 17, 12, 30)),  # пт -> сб
    ("weekly", datetime(2026, 10, 23, 12, 30)),  # пт -> следующая пт
    ("weekdays", datetime(2026, 10, 19, 12, 30)),  # пт -> пн
])
async def test_mark_sent_moves_repeats_forward(brain, repeat, expected):
    chat, ppl, rem = await setup_chat(brain)
    pid = ppl["Вася"].id
    rid = await rem.add(chat["id"], pid, pid, "дело", "2026-10-16 12:30", repeat, now=NOW)
    sent_at = NOW + timedelta(minutes=31)
    [row] = await rem.due(sent_at)
    nxt = await rem.mark_sent(row, sent_at)
    row = await rem.get(chat["id"], rid)
    assert row["done"] is False and row["due_at"] == nxt
    assert rem.to_local(nxt) == expected
    assert await rem.due(sent_at) == []


async def test_missed_repeats_are_not_replayed(brain):
    chat, ppl, rem = await setup_chat(brain)
    pid = ppl["Вася"].id
    rid = await rem.add(chat["id"], pid, pid, "зарядка", "2026-10-16 12:30", "daily", now=NOW)
    row = await rem.get(chat["id"], rid)
    later = datetime(2026, 10, 20, 10, 0)  # бот лежал 4 дня; 20.10 12:30 по Москве = 09:30 UTC — уже прошло
    nxt = await rem.mark_sent(row, later)
    assert rem.to_local(nxt) == datetime(2026, 10, 21, 12, 30)
    assert len(await rem.due(later)) == 0


async def test_weekly_keeps_wall_clock_across_dst(brain):
    chat, ppl, rem = await setup_chat(brain, tz="Europe/Berlin")
    pid = ppl["Вася"].id
    rid = await rem.add(chat["id"], pid, pid, "физра", "2026-10-19 07:30", "weekly", now=NOW)
    row = await rem.get(chat["id"], rid)
    assert row["due_at"] == datetime(2026, 10, 19, 5, 30)  # летнее время, UTC+2
    nxt = await rem.mark_sent(row, datetime(2026, 10, 19, 5, 31))
    assert nxt == datetime(2026, 10, 26, 6, 30)  # 25.10 часы перевели, UTC+1 — а по местному всё так же 07:30
    assert rem.to_local(nxt) == datetime(2026, 10, 26, 7, 30)


# ---------- отправка ----------
async def test_run_due_sends_real_mention_even_when_paused(brain):
    chat, ppl, rem = await setup_chat(brain)
    vasya = ppl["Вася"]
    await brain.db.update_chat(chat["id"], paused_until=datetime(2030, 1, 1))  # пауза не мешает
    rid = await rem.add(chat["id"], vasya.id, ppl["Петя"].id, "скинуть дз", "2026-10-16 12:30", None, now=NOW)
    assert await run_due(brain, NOW) == 0
    assert await run_due(brain, NOW + timedelta(minutes=30, seconds=5)) == 1
    [msg] = brain.evo.sent
    assert msg["to"] == GROUP
    assert msg["text"] == "⏰ @77011111111, напоминаю: скинуть дз"
    assert msg["mentioned"] == ["77011111111"] and msg["everyone"] is False
    assert (await rem.get(chat["id"], rid))["done"] is True
    assert await run_due(brain, NOW + timedelta(hours=1)) == 0
    assert len(brain.evo.sent) == 1
    last = (await brain.db.recent_messages(chat["id"], 1))[-1]
    assert last["role"] == "assistant" and "напоминаю" in last["text"]


async def test_run_due_whole_chat_late_and_stale(brain):
    chat, ppl, rem = await setup_chat(brain)
    await rem.add(chat["id"], None, ppl["Вася"].id, "@все на субботник", "2026-10-16 12:30", None, now=NOW)
    # бот лежал 40 минут — шлём с извинением; всему чату — без отметок, «@все» не тегает всех
    assert await run_due(brain, NOW + timedelta(minutes=70)) == 1
    [msg] = brain.evo.sent
    assert msg["text"] == "⏰ напоминаю: все на субботник (сорян, с опозданием)"
    assert msg["everyone"] is False and not msg["mentioned"]
    brain.evo.sent.clear()
    # опоздали на 7+ часов — уже не шлём, просто закрываем
    await rem.add(chat["id"], ppl["Петя"].id, None, "совсем старое", "2026-10-16 12:20", None, now=NOW)
    assert await run_due(brain, NOW + timedelta(hours=8)) == 0
    assert brain.evo.sent == [] and await rem.list_active(chat["id"]) == []


async def test_run_due_survives_errors_and_retries(brain):
    chat, ppl, rem = await setup_chat(brain)
    pid = ppl["Вася"].id
    await rem.add(9999, pid, pid, "чат пропал", "2026-10-16 12:30", None, now=NOW)  # get_chat упадёт
    good = await rem.add(chat["id"], pid, pid, "дз", "2026-10-16 12:30", None, now=NOW)

    real_send = brain.evo.send_text

    async def broken(*args, **kwargs):
        raise EvolutionError("нет связи")

    brain.evo.send_text = broken
    at = NOW + timedelta(minutes=31)
    assert await run_due(brain, at) == 0  # ничего не ушло, но цикл жив
    assert (await rem.get(chat["id"], good))["done"] is False  # попробуем ещё раз
    brain.evo.send_text = real_send
    assert await run_due(brain, at + timedelta(seconds=30)) == 1
    assert (await rem.get(chat["id"], good))["done"] is True
    assert brain.evo.texts() == ["⏰ @77011111111, напоминаю: дз"]

    brain.connection_state = "close"  # WhatsApp отвалился — даже не пытаемся
    await rem.add(chat["id"], pid, pid, "ещё", "2026-10-16 12:40", None, now=NOW)
    assert await run_due(brain, NOW + timedelta(minutes=45)) == 0


async def test_reminder_loop_runs_and_can_be_cancelled(brain):
    import asyncio

    chat, ppl, rem = await setup_chat(brain)
    pid = ppl["Вася"].id
    soon = datetime.now(ZoneInfo(brain.s.timezone)).replace(tzinfo=None) + timedelta(seconds=1)
    await rem.add(chat["id"], pid, pid, "чай", soon)
    task = asyncio.create_task(reminder_loop(brain, every=0.05))
    for _ in range(100):
        await asyncio.sleep(0.05)
        if brain.evo.sent:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert brain.evo.texts() == ["⏰ @77011111111, напоминаю: чай"]


# ---------- инструменты ----------
async def test_tools_set_list_and_cancel_permissions(brain):
    chat, ppl, rem = await setup_chat(brain)
    tz = brain.s.timezone
    vasya, petya, kolya = ppl["Вася"], ppl["Петя"], ppl["Коля"]
    t_vasya = tools_for(brain, chat, vasya)
    at = local_str(tz)
    day = datetime.strptime(at, "%Y-%m-%d %H:%M").strftime("%d.%m")

    res = await t_vasya["set_reminder"].handler({"text": "контрольная", "at": at})
    assert res.startswith(f"ок, напомню {day} в 08:00") and "отмечу" not in res
    res = await t_vasya["set_reminder"].handler({"text": "скинуть дз", "at": at, "person": "Петя"})
    assert "отмечу Петя" in res
    res = await t_vasya["set_reminder"].handler({"text": "физра", "at": at, "person": "я", "repeat": "weekly"})
    assert res.startswith("ок, буду напоминать кажд") and "в 08:00 (ближайший" in res
    with pytest.raises(ToolError, match="уже прошло"):
        await t_vasya["set_reminder"].handler({"text": "x", "at": local_str(tz, days=-1)})
    with pytest.raises(ToolError, match="не нашла"):
        await t_vasya["set_reminder"].handler({"text": "x", "at": at, "person": "Зинаида"})

    listing = await t_vasya["list_reminders"].handler({})
    assert listing.count("№") == 3 and "Петя: скинуть дз" in listing and "Вася: контрольная" in listing
    ids = [r["id"] for r in await rem.list_active(chat["id"])]
    by_text = {r["text"]: r["id"] for r in await rem.list_active(chat["id"])}

    # Коля не ставил и не адресат — нельзя; Петя — адресат, можно; админ — всё
    with pytest.raises(ToolError, match="отменить может"):
        await tools_for(brain, chat, kolya)["cancel_reminder"].handler({"id": by_text["скинуть дз"]})
    res = await tools_for(brain, chat, petya)["cancel_reminder"].handler({"id": by_text["скинуть дз"]})
    assert "отменила" in res and "скинуть дз" in res
    with pytest.raises(ToolError, match="нет"):
        await t_vasya["cancel_reminder"].handler({"id": by_text["скинуть дз"]})
    assert "отменила" in await t_vasya["cancel_reminder"].handler({"id": f"№{by_text['физра']}"})
    assert "отменила" in await tools_for(brain, chat, kolya, admin=True)["cancel_reminder"].handler(
        {"id": by_text["контрольная"]})
    assert await rem.list_active(chat["id"]) == [] and len(ids) == 3
    assert "нет" in await t_vasya["list_reminders"].handler({})

    # напоминание в чужом чате отсюда не видно и не отменить
    other = await brain.db.get_or_create_chat(brain.s.evolution_instance, "120363000000000002@g.us", True)
    foreign = await rem.add(other["id"], vasya.id, vasya.id, "чужое", at)
    with pytest.raises(ToolError, match="нет"):
        await t_vasya["cancel_reminder"].handler({"id": foreign})


async def test_tools_without_sender_remind_whole_chat(brain):
    chat, _, rem = await setup_chat(brain)
    t_stella = tools_for(brain, chat, None)
    res = await t_stella["set_reminder"].handler({"text": "субботник", "at": local_str(brain.s.timezone)})
    assert "всему чату" in res
    [row] = await rem.list_active(chat["id"])
    assert row["person_id"] is None and row["created_by"] is None
    with pytest.raises(ToolError, match="отменить может"):
        await t_stella["cancel_reminder"].handler({"id": row["id"]})


@pytest.fixture
def reminder_tools_in_brain(monkeypatch):
    """Пока build_tools их не подключает — добавляем сами (если уже подключены, второй раз не добавляем)."""
    original = brain_module.build_tools

    def patched(db, casino, settings, ctx):
        specs = original(db, casino, settings, ctx)
        if not any(t.name == "set_reminder" for t in specs):
            specs += build_reminder_tools(db, settings, ctx)
        return specs

    monkeypatch.setattr(brain_module, "build_tools", patched)


async def test_reminder_via_model_then_mention(brain, reminder_tools_in_brain):
    tz = brain.s.timezone  # Алматы по умолчанию
    at = local_str(tz)

    async def set_it(tools, prompt):
        assert "Сейчас:" in prompt
        return await tools["set_reminder"].handler({"text": "контрольная", "at": at})

    brain.llm.queue = [set_it]
    await feed(brain, upsert("стелла напомни завтра в 8 про контрольную"))
    assert brain.evo.texts()[-1].startswith("ок, напомню")
    chat = await brain.db.get_chat_by_jid(brain.s.evolution_instance, GROUP)
    rem = Reminders(brain.db, brain.s)
    [row] = await rem.list_active(chat["id"])
    vasya = await brain.db.find_person_by_jid(VASYA)
    assert row["person_id"] == vasya.id and row["created_by"] == vasya.id and row["local"] == at

    # Петя просит напомнить Васе — отметка уйдёт Васе
    async def for_vasya(tools, prompt):
        return await tools["set_reminder"].handler({"text": "скинуть дз", "at": local_str(tz, hm="09:00"),
                                                    "person": "@Вася"})

    brain.llm.queue = [for_vasya]
    await feed(brain, upsert("стелла напомни @Вася завтра в 9 скинуть дз", sender=PETYA, name="Петя"))
    assert "отмечу Вася" in brain.evo.texts()[-1]

    brain.evo.sent.clear()
    assert await run_due(brain, row["due_at"] + timedelta(seconds=30)) == 1
    [msg] = brain.evo.sent
    assert msg["text"] == "⏰ @77011111111, напоминаю: контрольная" and msg["mentioned"] == ["77011111111"]

    # список и отмена — тоже через модель
    async def list_and_cancel(tools, prompt):
        listing = await tools["list_reminders"].handler({})
        rid = int(listing.split("№")[1].split(" ")[0])
        return await tools["cancel_reminder"].handler({"id": rid})

    brain.llm.queue = [list_and_cancel]
    await feed(brain, upsert("стелла отмени напоминание про дз"))  # Вася — адресат, ему можно
    assert brain.evo.texts()[-1].startswith("отменила")
    assert await rem.list_active(chat["id"]) == []
