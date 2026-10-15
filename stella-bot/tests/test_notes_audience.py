import io

from bot import notes
from bot.persona import system_prompt

from .conftest import GROUP, settle, upsert


def test_school_audience_rules(settings):
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
