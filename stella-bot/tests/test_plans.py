"""Подписки и лимиты из панели: кончился лимит — «купите подписку», дальше молчит; подписка снимает лимит."""

import json
import time

from bot import plans

from .conftest import GROUP, OWNER, VASYA, settle, upsert

OWNER_JID = f"{OWNER}@s.whatsapp.net"


async def say(brain, text, **kw):
    await brain.handle_payload(upsert(text, **kw))
    await settle(brain)


async def test_free_limit_then_subscription(brain):
    brain.s.free_replies_per_day = 2
    brain.s.support_contact = "@stella_help"
    for _ in range(2):
        await say(brain, "привет", chat=VASYA, sender=VASYA)
    assert len(brain.llm.calls) == 2
    assert "лимит: 2 твоих ответов в день, сегодня осталось 2" in brain.llm.calls[0]["prompt"]
    assert "сегодня осталось 1" in brain.llm.calls[1]["prompt"] and "@stella_help" in brain.llm.calls[1]["prompt"]
    vasya = await brain.db.find_person_by_jid(VASYA)
    assert await plans.used_today(brain.db, vasya.id) == 2

    await say(brain, "ещё вопрос", chat=VASYA, sender=VASYA)
    assert len(brain.llm.calls) == 2  # модель не зовём — денег не тратим
    notice = brain.evo.texts()[-1]
    assert "Вы достигли лимита" in notice and "купите подписку" in notice and notice.endswith("@stella_help")

    await say(brain, "ау", chat=VASYA, sender=VASYA)  # второй раз за час — просто молчит
    assert len(brain.llm.calls) == 2 and brain.evo.texts()[-1] == notice
    assert sum(t == notice for t in brain.evo.texts()) == 1

    await plans.set_plan(brain.db, vasya.id, "unlimited", days=30)
    for _ in range(3):
        await say(brain, "а теперь?", chat=VASYA, sender=VASYA)
    assert len(brain.llm.calls) == 5
    assert "твоих ответов в день" not in brain.llm.calls[-1]["prompt"]

    await plans.set_plan(brain.db, vasya.id, "free")  # сняли подписку — снова общий лимит
    await say(brain, "ну и?", chat=VASYA, sender=VASYA)
    assert len(brain.llm.calls) == 5


async def test_owner_and_admins_are_never_limited(brain):
    brain.s.free_replies_per_day = 1
    for _ in range(3):
        await say(brain, "привет", chat=OWNER_JID, sender=OWNER_JID, name="Хозяин")
    assert len(brain.llm.calls) == 3
    owner = await brain.db.find_person_by_jid(OWNER_JID)
    await plans.set_plan(brain.db, owner.id, "limit", limit=1)  # даже свой лимит владельцу не мешает
    await say(brain, "ещё", chat=OWNER_JID, sender=OWNER_JID, name="Хозяин")
    assert len(brain.llm.calls) == 4


async def test_personal_limit_and_expiry(brain):
    await say(brain, "привет", chat=VASYA, sender=VASYA)
    vasya = await brain.db.find_person_by_jid(VASYA)
    # общего лимита нет, но Васе выдан свой — 1 ответ в день (уже потрачен)
    await plans.set_plan(brain.db, vasya.id, "limit", limit=1, days=7)
    assert await brain.reply_limit(vasya) == 1
    await say(brain, "ещё", chat=VASYA, sender=VASYA)
    assert len(brain.llm.calls) == 1 and "лимит" in brain.evo.texts()[-1]

    # подписка закончилась — снова общий (а он выключен: без лимита)
    plan = await plans.get_plan(brain.db, vasya.id)
    plan["until"] = time.time() - 1
    await brain.db.kv_set(plans.plan_key(vasya.id), json.dumps(plan), time.time())
    assert await plans.get_plan(brain.db, vasya.id) is None
    assert (await plans.get_plan(brain.db, vasya.id, expired=True))["kind"] == "limit"
    assert await brain.reply_limit(vasya) == 0
    await say(brain, "а сейчас?", chat=VASYA, sender=VASYA)
    assert len(brain.llm.calls) == 2


async def test_group_notice_only_when_addressed(brain):
    brain.s.free_replies_per_day = 1
    await say(brain, "стелла привет")
    assert len(brain.llm.calls) == 1
    await say(brain, "стелла как дела")
    assert len(brain.llm.calls) == 1
    sent = [m for m in brain.evo.sent if m.get("to") == GROUP]
    assert "Вы достигли лимита" in sent[-1]["text"] and sent[-1].get("quoted")


async def test_counter_resets_next_day(brain):
    await say(brain, "привет", chat=VASYA, sender=VASYA)
    vasya = await brain.db.find_person_by_jid(VASYA)
    await brain.db.kv_set(plans.used_key(vasya.id), "2000-01-01", 50)  # вчерашний счётчик не считается
    assert await plans.used_today(brain.db, vasya.id) == 0
    await plans.count_reply(brain.db, vasya.id)
    assert await plans.used_today(brain.db, vasya.id) == 1


def test_limit_text(settings):
    settings.support_contact = ""
    text = plans.limit_text(settings, 20)
    assert text.startswith("Вы достигли лимита") and text.endswith("у техподдержки")
    settings.support_contact = "@help"
    assert plans.limit_text(settings, 20).endswith("у техподдержки: @help")
    settings.limit_message = "Лимит {limit} в день кончился. Пиши"
    assert plans.limit_text(settings, 20) == "Лимит 20 в день кончился. Пиши\n@help"
    settings.limit_message = ""
    assert plans.limit_text(settings, 5).startswith("Вы достигли лимита")
