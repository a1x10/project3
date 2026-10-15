import io

from bot import notes
from bot.persona import system_prompt

from .conftest import GROUP, settle, upsert


def test_school_audience_rules(settings):
    settings.prompt_style = "full"
    sp = system_prompt(settings)
    assert "подростки 12–14 лет" in sp and "как подросток" in sp and "кд — как дела" in sp
    assert "без нравоучений" in sp and "ни учителям, ни родителям" in sp
    assert "без мата — даже если другие матерятся" in sp
    assert "советуешь рассказать" not in sp and "родителям или взрослому" not in sp
    settings.swear_level = 2
    assert "без мата — даже если другие матерятся" in system_prompt(settings)  # в школе мат выключен всегда
    settings.audience = "none"
    sp = system_prompt(settings)
    assert "подростки" not in sp and "крепкие" in sp


async def test_notes_cli_sets_about_shown_in_prompt(brain, monkeypatch):
    await brain.handle_payload(upsert("всем привет"))
    await settle(brain)
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    await brain.db.update_chat(chat["id"], title="7в без учителя")
    monkeypatch.setattr(notes.settings, "database_url", brain.s.database_url)
    monkeypatch.setattr(notes.settings, "evolution_instance", "stella")
    out = []
    code = await notes.main(["set", "--group", "7в"], stdin=io.StringIO("главный мем — Chicken Gun\n"),
                            out=out.append)
    assert code == 0 and "записала" in out[-1]
    brain.llm.queue = ["да, помню"]
    await brain.handle_payload(upsert("стелла какой у нас мем"))
    await settle(brain)
    prompt = brain.llm.calls[-1]["prompt"]
    assert "Про этот чат (рассказал владелец):\nглавный мем — Chicken Gun" in prompt
    out.clear()
    assert await notes.main(["show"], out=out.append) == 0
    assert any("Chicken Gun" in line for line in out)
    assert await notes.main(["set", "--group", "нет такой"], stdin=io.StringIO("x"), out=out.append) == 1


def test_minimal_prompt_is_short_and_functional(settings):
    from bot.config import Settings

    assert Settings().prompt_style == "minimal"
    sp = system_prompt(settings)
    assert "ИИ-ассистент" in sp and "Алексей" in sp and "Codex" in sp and "Stells" in sp
    assert "<молчу>" in sp and "@все" in sp and "remember" in sp
    assert "подростки" not in sp and "без мата" not in sp and "Характер:" not in sp
    assert len(sp) < 2000


async def test_prompt_lists_everyone_and_mentions_work(brain):
    from .conftest import PETYA, VASYA

    lid = "998877665544@lid"
    await brain.handle_payload(upsert("привет всем", sender=PETYA, name="Петя"))
    await brain.handle_payload(upsert("и я тут", sender=lid, name="Лида"))
    await brain.handle_payload(upsert("ку", sender=VASYA, name="Вася"))
    await settle(brain)
    brain.llm.queue = ["@Лида, @Петя и @все — го в майн"]
    await brain.handle_payload(upsert("стелла позови всех", sender=VASYA, name="Вася"))
    await settle(brain)
    prompt = brain.llm.calls[-1]["prompt"]
    assert "Все, кого ты видела в этом чате (3)" in prompt and "Лида [p" in prompt
    last = brain.evo.sent[-1]
    assert last["text"] == "@998877665544, @77022222222 и @все — го в майн"
    assert set(last["mentioned"]) == {lid, "77022222222"} and last["everyone"] is True


async def test_profiles_filled_by_tool_and_memory(brain, monkeypatch):
    import json

    from bot import profiles
    from .conftest import VASYA

    async def fill(tools, prompt):
        await tools["update_profile"].handler({"person": "я", "fields": {"игры": "Roblox, Minecraft"}})
        return "запомнила"

    brain.llm.queue = [fill]
    await brain.handle_payload(upsert("стелла я играю в роблокс и майн"))
    await settle(brain)
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    vasya = await brain.db.find_person_by_jid(VASYA)
    assert await brain.db.get_profile(vasya.id, chat["id"]) == {"игры": "Roblox, Minecraft"}

    # фоновый анализ обновляет анкету сам (продолжение разговора с ней тут не нужно)
    brain.s.continue_window = 0
    brain.s.memory_extract_every = 2
    brain.llm.queue = [json.dumps({"people": [{"ref": vasya.ref, "profile": {
        "игры": "Roblox, Minecraft, Chicken Gun", "характер": "весёлый, любит спорить"}}]})]
    await brain.handle_payload(upsert("чикен ган имба"))
    await brain.handle_payload(upsert("спорим?"))
    await settle(brain)
    profile = await brain.db.get_profile(vasya.id, chat["id"])
    assert profile == {"игры": "Roblox, Minecraft, Chicken Gun", "характер": "весёлый, любит спорить"}
    assert "анкета пустая" not in brain.llm.calls[-1]["prompt"]

    # анкета видна в контексте ответа и в find_person
    async def look(tools, prompt):
        assert "анкета — игры: Roblox, Minecraft, Chicken Gun; характер: весёлый, любит спорить" in prompt
        return await tools["find_person"].handler({"query": "Вася"})

    brain.llm.queue = [look]
    await brain.handle_payload(upsert("стелла что ты про меня знаешь"))
    await settle(brain)
    assert brain.evo.sent

    monkeypatch.setattr(profiles.settings, "database_url", brain.s.database_url)
    monkeypatch.setattr(profiles.settings, "evolution_instance", "stella")
    out = []
    assert await profiles.main([], out=out.append) == 0
    assert any("характер: весёлый, любит спорить" in line for line in out)


async def test_profile_limits(brain):
    from .conftest import VASYA

    await brain.handle_payload(upsert("привет"))
    await settle(brain)
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    vasya = await brain.db.find_person_by_jid(VASYA)
    big = {f"поле{i}": "x" * 500 for i in range(40)}
    profile = await brain.db.update_profile(vasya.id, chat["id"], big)
    assert len(profile) == 20 and all(len(v) == 200 for v in profile.values())
    profile = await brain.db.update_profile(vasya.id, chat["id"], {"поле0": ""})
    assert "поле0" not in profile
