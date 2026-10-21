"""Кончились бонусные кредиты (LLM_SWITCH_AT) и LLM_BACKEND_AFTER=off — модель выключена, свой баланс не тратится."""

from datetime import date, timedelta

import pytest

from bot import admin, html_studio
from bot.llm import LLMOff, SwitchingLLM
from bot.sandbox import CodeSandbox, Progress, SandboxError

from .conftest import GROUP, OWNER, VASYA, make_settings, settle, upsert

OWNER_JID = f"{OWNER}@s.whatsapp.net"
PAST = date(2000, 1, 1)


def switch_off(brain, when=PAST):
    brain.s.llm_switch_at = when
    brain.s.llm_backend_after = "off"


def test_model_off_by_date(tmp_path):
    s = make_settings(tmp_path, llm_switch_at=date(2026, 10, 23), llm_backend_after="off")
    assert not s.model_off(date(2026, 10, 22))
    assert s.model_off(date(2026, 10, 23)) and s.model_off(date(2026, 12, 1))
    s.llm_backend_after = "messages_api"
    assert not s.model_off(date(2026, 10, 23))
    s.llm_switch_at = None
    assert not s.model_off(date(2030, 1, 1))


async def test_switching_llm_never_builds_a_backend_when_off(tmp_path):
    s = make_settings(tmp_path, llm_switch_at=date(2026, 10, 23), llm_backend_after="off")

    def factory(*_):
        pytest.fail("бэкенд не должен создаваться — это был бы запрос за свой баланс")

    llm = SwitchingLLM(s, today=lambda: date(2026, 10, 23), factory=factory)
    with pytest.raises(LLMOff):
        await llm.ask(system="s", prompt="p")


async def test_dm_gets_one_pause_notice_and_no_model_calls(brain):
    switch_off(brain)
    brain.connection_state = "open"
    for text in ("стелла привет", "ау", "ну ответь"):
        await brain.handle_payload(upsert(text, chat=VASYA, sender=VASYA))
        await settle(brain)
    assert brain.llm.calls == []
    to_vasya = [m["text"] for m in brain.evo.sent if m.get("type") == "text" and m.get("to") != OWNER]
    assert to_vasya == ["Я пока на паузе 🙏"]
    to_owner = [m["text"] for m in brain.evo.sent if m.get("to") == OWNER]
    assert len([t for t in to_owner if "Бонусные кредиты закончились" in t]) == 1


async def test_group_chatter_is_silent_and_commands_still_work(brain):
    switch_off(brain)
    await brain.handle_payload(upsert("кто идёт в кино?"))
    await settle(brain)
    assert brain.llm.calls == [] and not [m for m in brain.evo.sent if m.get("to") == GROUP]
    await brain.handle_payload(upsert("стелла баланс"))
    await settle(brain)
    texts = [m["text"] for m in brain.evo.sent if m.get("type") == "text" and m.get("to") == GROUP]
    assert texts and "пауз" not in " ".join(texts) and brain.llm.calls == []


async def test_memory_and_initiative_do_not_call_the_model(brain):
    await brain.handle_payload(upsert("я петя, люблю футбол"))
    await settle(brain)
    switch_off(brain)
    calls = len(brain.llm.calls)
    chat = await brain.db.get_chat_by_jid(brain.s.evolution_instance, GROUP)
    assert await brain.memory.extract(chat["id"]) == 0
    brain.s.initiative_per_week = 14
    brain.connection_state = "open"
    assert await brain.initiative_tick() == []
    assert len(brain.llm.calls) == calls


async def test_owner_warned_a_day_before_and_told_once_on_the_day(brain):
    brain.connection_state = "open"
    switch = date(2026, 10, 23)
    switch_off(brain, switch)
    await brain.model_off_tick(switch - timedelta(days=2))
    await brain.model_off_tick(switch - timedelta(days=1))
    await brain.model_off_tick(switch - timedelta(days=1))
    brain._last_alert.clear()
    await brain.model_off_tick(switch)
    await brain.model_off_tick(switch + timedelta(days=1))
    to_owner = [m["text"] for m in brain.evo.sent if m.get("to") == OWNER]
    assert len([t for t in to_owner if t.startswith("⏳ Завтра (23.10)")]) == 1
    assert len([t for t in to_owner if "Бонусные кредиты закончились" in t]) == 1
    brain.s.llm_backend_after = "messages_api"  # платить своим балансом — тогда и не предупреждаем
    assert not brain.s.model_off(switch)


async def test_studio_and_sandbox_stop_before_any_request(settings, monkeypatch):
    settings.llm_switch_at, settings.llm_backend_after = PAST, "off"

    def no_client(*_):
        pytest.fail("запрос к API при выключенной модели")

    monkeypatch.setattr(html_studio, "client", no_client)
    with pytest.raises(html_studio.StudioError):
        await html_studio._call(settings, {"model": "m", "messages": []}, "high", 0)

    class NoClient:
        def __getattr__(self, name):
            pytest.fail("запрос к API при выключенной модели")

    box = CodeSandbox(client=NoClient(), off=settings.model_off)
    with pytest.raises(SandboxError):
        await box._run("посчитай", [], None, False, Progress())
    with pytest.raises(SandboxError):
        await box._call(NoClient(), [], None, [], Progress())


def test_panel_can_switch_it():
    desc = admin.EDITABLE_KEYS["llm_backend_after"]
    assert admin.coerce(desc, "off") == "off" and admin.coerce(desc, "messages_api") == "messages_api"
    with pytest.raises(ValueError):
        admin.coerce(desc, "agent_sdk_free_forever")
