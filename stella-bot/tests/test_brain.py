import json
from datetime import timedelta

from bot.llm.base import LLMError
from bot.util import utcnow

from .conftest import BOT, GROUP, OWNER, PETYA, VASYA, settle, upsert

DM = VASYA


async def feed(brain, *payloads):
    for p in payloads:
        await brain.handle_payload(p)
    await settle(brain)


async def test_group_name_trigger_gets_human_like_bubbles(brain):
    brain.llm.queue = ["привет!!\nкак вы тут\n[стикер: привет]"]
    await feed(brain, upsert("Стелла привет"))
    assert len(brain.llm.calls) == 1
    prompt = brain.llm.calls[0]["prompt"]
    assert "★" in prompt and "Вася [p" in prompt and "Стелла привет" in prompt
    texts = brain.evo.texts()
    assert texts == ["привет!!", "как вы тут"]
    assert any(m["type"] == "sticker" for m in brain.evo.sent)


async def test_plain_group_talk_is_ignored_when_chime_off(brain):
    await feed(brain, upsert("пацаны го в кино"), upsert("давай", sender=PETYA, name="Петя"))
    assert brain.llm.calls == []
    assert brain.evo.sent == []


async def test_ambient_chime_in_can_stay_silent(brain):
    brain.s.chime_default = "chatty"
    brain.rng.random = lambda: 0.0  # всегда «решает» попробовать
    brain.llm.queue = ["<молчу>"]
    msgs = [upsert(f"сообщение {i}", sender=VASYA if i % 2 else PETYA, name="Вася" if i % 2 else "Петя")
            for i in range(4)]
    await feed(brain, *msgs)
    assert len(brain.llm.calls) == 1
    assert "К тебе напрямую не обращались" in brain.llm.calls[0]["prompt"]
    assert brain.evo.sent == []


async def test_casino_fast_path_without_model(brain):
    await feed(brain, upsert("стелла красное 500"))
    assert brain.llm.calls == []
    texts = brain.evo.texts()
    assert any("выпало" in t for t in texts)
    assert any("🍌" in t for t in texts)


async def test_reply_to_bot_message_is_direct(brain):
    brain.llm.queue = ["ахах да", "ну конечно"]
    await feed(brain, upsert("стелла как дела"))
    bot_msg_id = brain.evo.sent[-1]["id"]
    await feed(brain, upsert("а ты что делаешь", quoted={"stanzaId": bot_msg_id, "participant": BOT,
                                                          "quotedMessage": {"conversation": "ахах да"}}))
    assert len(brain.llm.calls) == 2


async def test_dm_always_answers_and_voice_gets_canned_reply(brain):
    brain.llm.queue = ["хай)"]
    await feed(brain, upsert("привет", chat=DM))
    assert brain.evo.texts() == ["хай)"]
    await feed(brain, upsert(chat=DM, message={"audioMessage": {"seconds": 5}}, message_type="audioMessage"))
    assert len(brain.llm.calls) == 1
    assert "голос" in brain.evo.texts()[-1]


async def test_duplicate_webhook_processed_once(brain):
    brain.llm.queue = ["раз", "два"]
    p = upsert("стелла ау", msg_id="SAME")
    await feed(brain, p, p)
    assert len(brain.llm.calls) == 1


async def test_pause_and_resume(brain):
    owner = f"{OWNER}@s.whatsapp.net"  # в группе ставить на паузу могут только админы
    await feed(brain, upsert("стелла помолчи 10", sender=owner, name="Алексей"))
    assert "помолчу 10" in brain.evo.texts()[-2]
    await feed(brain, upsert("стелла привет"))
    assert brain.llm.calls == []
    await feed(brain, upsert("стелла вернись"))
    assert "здесь" in brain.evo.texts()[-1]
    brain.llm.queue = ["о, привет"]
    await feed(brain, upsert("стелла привет"))
    assert len(brain.llm.calls) == 1


async def test_owner_typing_manually_pauses_chat(brain):
    await feed(brain, upsert("я сам отвечу", from_me=True, sender=BOT))
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    assert chat["paused_until"] > utcnow() + timedelta(minutes=20)
    rows = await brain.db.recent_messages(chat["id"], 5)
    assert rows[-1]["role"] == "assistant" and rows[-1]["text"] == "я сам отвечу"


async def test_tools_remember_and_facts_show_up_later(brain):
    async def use_tool(tools, prompt):
        await tools["remember"].handler({"person": "я", "fact": "учится на врача"})
        return "запомнила 😌"

    brain.llm.queue = [use_tool, "конечно помню"]
    await feed(brain, upsert("стелла я учусь на врача"))
    await feed(brain, upsert("стелла что ты про меня знаешь"))
    assert "учится на врача" in brain.llm.calls[1]["prompt"]


async def test_who_is_this_reply_includes_quoted_persons_facts(brain):
    brain.llm.queue = ["ок"]
    await feed(brain, upsert("я петя из алматы", sender=PETYA, name="Петя"))
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    petya = await brain.db.find_person_by_jid(PETYA)
    await brain.db.add_fact(petya.id, chat["id"], "живёт в Алматы", "tool", 50)
    brain.llm.queue = ["это петя"]
    await feed(brain, upsert("стелла кто это", quoted={"stanzaId": "OLD1", "participant": PETYA,
                                                        "quotedMessage": {"conversation": "лол"}}))
    prompt = brain.llm.calls[-1]["prompt"]
    assert "живёт в Алматы" in prompt and "(в ответ Петя: «лол»)" in prompt


async def test_casino_through_model_tool_sends_result_first(brain):
    async def bet(tools, prompt):
        await tools["casino"].handler({"action": "play", "game": "coin", "choice": "heads", "amount": 100})
        return "ну как тебе"

    brain.llm.queue = [bet]
    await feed(brain, upsert("стелла поставь за меня сотку на орла пожалуйста"))
    texts = brain.evo.texts()
    assert "монетку" in texts[0] and texts[-1] == "ну как тебе"


async def test_llm_failure_sends_fallback_and_notifies_owner(brain):
    brain.connection_state = "open"
    brain.llm.queue = [LLMError("boom"), LLMError("boom again")]  # вторая попытка тоже не удалась
    await feed(brain, upsert("стелла ты тут?"))
    to_group = [m for m in brain.evo.sent if m["to"] == GROUP]
    to_owner = [m for m in brain.evo.sent if m["to"] == OWNER]
    assert to_group and to_owner


async def test_mentions_are_readable_for_model_and_real_in_whatsapp(brain):
    await feed(brain, upsert("всем привет", sender=PETYA, name="Петя"))
    brain.llm.queue = ["@Петя привет тебе"]
    await feed(brain, upsert("стелла поздоровайся с @77022222222", mentioned=[PETYA]))
    assert "@Петя" in brain.llm.calls[-1]["prompt"]
    last = brain.evo.sent[-1]
    assert last["text"] == "@77022222222 привет тебе" and last["mentioned"] == ["77022222222"]


async def test_memory_extraction(brain):
    brain.s.memory_extract_every = 3
    brain.llm.queue = [json.dumps({"people": [{"ref": "p1", "facts": ["любит футбол"]}], "chat": ["тут друзья с универа"]})]
    for i in range(3):
        await brain.handle_payload(upsert(f"я обожаю футбол {i}"))
    await settle(brain)
    for _ in range(50):  # фоновая задача памяти
        chat = await brain.db.get_chat_by_jid("stella", GROUP)
        if chat["notes"]:
            break
        await settle(brain)
    vasya = await brain.db.find_person_by_jid(VASYA)
    assert "любит футбол" in await brain.db.get_facts(vasya.id, chat["id"], 10)
    assert "друзья с универа" in chat["notes"]


async def test_learn_sticker_command(brain):
    brain.evo.media = b"RIFF0000WEBPVP8 fake"
    await feed(brain, upsert("стелла запомни стикер обнимашки",
                             quoted={"stanzaId": "ST1", "participant": PETYA,
                                     "quotedMessage": {"stickerMessage": {"url": "x"}}}))
    assert "обнимашки" in brain.evo.texts()[-1]
    assert "обнимашки" in await brain.stickers.moods()


async def test_bot_learns_own_lid_from_echo_and_reacts_to_lid_mention(brain):
    echo = upsert("эхо", from_me=True, sender=BOT, msg_id="ECHO1")
    echo["data"]["key"]["participant"] = "555000111@lid"
    brain.outbox.remember_sent("ECHO1")
    await feed(brain, echo)
    assert "555000111@lid" in brain.bot.jids
    brain.llm.queue = ["да-да"]
    await feed(brain, upsert("@555000111 ты где", mentioned=["555000111@lid"]))
    assert len(brain.llm.calls) == 1
    assert "@Стелла ты где" in brain.llm.calls[0]["prompt"]


async def test_quote_used_when_chat_moved_on(brain):
    brain.llm.queue = ["отвечаю тебе"]
    first = upsert("стелла а ты что думаешь")
    await brain.handle_payload(first)
    await brain.handle_payload(upsert("кстати я тоже тут", sender=PETYA, name="Петя"))
    await settle(brain)
    sent = [m for m in brain.evo.sent if m["type"] == "text"]
    assert sent[0]["quoted"]["key"]["participant"] == VASYA
