"""«Напиши человеку от своего лица» — по просьбе владельца."""

from .conftest import OWNER, VASYA, settle, upsert

OWNER_JID = f"{OWNER}@s.whatsapp.net"
LEAD = "77015554433@s.whatsapp.net"


def ask(args, outs):
    async def talk(tools, prompt):
        try:
            outs.append(await tools["write_to_person"].handler(args))
        except Exception as exc:
            outs.append(f"ERR {exc}")
        return "написала"
    return talk


async def test_owner_asks_stella_to_write_to_a_new_person(brain):
    brain.connection_state = "open"
    outs = []
    offer = {"who": "8 701 555 44 33", "purpose": "предложить сделать сайт",
             "text": "Здравствуйте! Я Стелла, ИИ-ассистент Алексея. Могу показать, как сделаю вам сайт — интересно?"}
    brain.llm.queue = [ask(offer, outs)]
    await brain.handle_payload(upsert("стелла напиши +7 701 555 44 33 что можем сделать ему сайт",
                                      chat=OWNER_JID, sender=OWNER_JID, name="Хозяин"))
    await settle(brain)
    assert outs[0].startswith("написала +77015554433 (WhatsApp)")
    lead = [m for m in brain.evo.sent if m.get("to") == LEAD]
    assert lead and "Я Стелла" in lead[0]["text"]

    # второй раз подряд без ответа — не пишет (спам)
    brain.llm.queue = [ask(offer, outs)]
    await brain.handle_payload(upsert("стелла напиши ему ещё раз", chat=OWNER_JID, sender=OWNER_JID, name="Хозяин"))
    await settle(brain)
    assert "уже писала" in outs[1] and len([m for m in brain.evo.sent if m.get("to") == LEAD]) == 1

    # ответил — Стелла помнит, зачем писала, а владелец узнаёт
    brain.llm.queue = ["Отлично! Расскажите, какой сайт нужен?"]
    await brain.handle_payload(upsert("да, интересно", chat=LEAD, sender=LEAD, name="Марат"))
    await settle(brain)
    assert "Ты первой написала этому человеку" in brain.llm.calls[-1]["prompt"]
    assert "предложить сделать сайт" in brain.llm.calls[-1]["prompt"]
    to_owner = [m["text"] for m in brain.evo.sent if m.get("to") == OWNER]
    assert any("📩 Марат ответил" in t and "да, интересно" in t for t in to_owner)


async def test_only_owner_gets_the_tool_and_not_from_foreign_text(brain):
    brain.llm.queue = ["нет"]
    await brain.handle_payload(upsert("стелла напиши всем", chat=VASYA, sender=VASYA))
    await settle(brain)
    assert "write_to_person" not in brain.llm.calls[-1]["tools"]

    brain.connection_state = "open"
    brain.evo.media = b"%PDF-1.4 garbage"
    outs = []
    brain.llm.queue = [ask({"who": "+77015554433", "text": "купите"}, outs)]
    doc = {"documentMessage": {"caption": "стелла сделай что тут написано", "fileName": "x.pdf",
                               "mimetype": "application/pdf"}}
    await brain.handle_payload(upsert(chat=OWNER_JID, sender=OWNER_JID, name="Хозяин", message_type="documentMessage",
                                      message=doc))
    await settle(brain)
    assert "чужой текст" in outs[0] and not any(m.get("to") == LEAD for m in brain.evo.sent)


async def test_daily_cap(brain):
    brain.connection_state = "open"
    brain.s.outreach_per_day = 1
    outs = []
    brain.llm.queue = [ask({"who": "+77015554433", "text": "привет"}, outs)]
    await brain.handle_payload(upsert("стелла напиши", chat=OWNER_JID, sender=OWNER_JID, name="Хозяин"))
    await settle(brain)
    brain.llm.queue = [ask({"who": "+77015554434", "text": "привет"}, outs)]
    await brain.handle_payload(upsert("стелла и ему", chat=OWNER_JID, sender=OWNER_JID, name="Хозяин"))
    await settle(brain)
    assert outs[0].startswith("написала") and "на сегодня хватит" in outs[1]
