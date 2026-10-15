"""Стелла отвечает всем: звонки, паузы, несколько человек сразу, LID, сбои модели, старые сообщения."""

import json
import time
from datetime import timedelta

import httpx

from bot import diag
from bot.addressing import CONTINUE, DIRECT, BotIdentity, classify, name_stems
from bot.db import DB
from bot.evolution import MSG_CALL, Evolution
from bot.llm.base import LLMError
from bot.parser import parse_upsert
from bot.util import utcnow

from .conftest import BOT, GROUP, OWNER, PETYA, VASYA, settle, upsert

DM = VASYA
KOLYA = "77033333333@s.whatsapp.net"


async def feed(brain, *payloads):
    for p in payloads:
        await brain.handle_payload(p)
    await settle(brain)


# ---------- звонки и «владелец пишет сам» ----------

async def test_call_auto_reply_does_not_pause_dm(brain):
    """Evolution сам пишет звонящему «не могу ответить» — это не владелец, личка не должна замолкать."""
    await feed(brain, upsert(MSG_CALL, chat=DM, from_me=True, sender=BOT, msg_id="CALLMSG"))
    chat = await brain.db.get_chat_by_jid("stella", DM)
    assert chat is None or not chat["paused_until"]
    brain.llm.queue = ["привет!"]
    await feed(brain, upsert("привет", chat=DM))
    assert brain.evo.texts() == ["привет!"]


async def test_old_own_message_after_reconnect_does_not_pause(brain):
    old = upsert("это я писал вчера", from_me=True, sender=BOT, msg_id="OLDME")
    old["data"]["messageTimestamp"] = int(time.time()) - 3600
    await feed(brain, old)
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    assert not chat["paused_until"]


async def test_stale_incoming_is_stored_but_not_answered(brain):
    old = upsert("стелла ты где", msg_id="OLD1")
    old["data"]["messageTimestamp"] = int(time.time()) - 2 * 3600
    await feed(brain, old)
    assert brain.llm.calls == []
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    rows = await brain.db.recent_messages(chat["id"], 5)
    assert rows[-1]["text"] == "стелла ты где"


async def test_owner_notification_echo_is_not_owner_typing(brain):
    brain.connection_state = "open"
    await brain.notify_owner("test", "⚠️ проверка")
    sent = brain.evo.sent[-1]
    assert sent["to"] == OWNER and brain.outbox.is_ours(sent["id"])


# ---------- пауза ----------

async def test_anyone_cannot_silence_the_whole_group(brain):
    brain.llm.queue = ["сам заткнись 😄"]
    await feed(brain, upsert("стелла заткнись"))
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    assert not chat["paused_until"]
    assert len(brain.llm.calls) == 1  # ответила сама, а не ушла на паузу
    brain.llm.queue = ["да?"]
    await feed(brain, upsert("стелла а ты тут", sender=PETYA, name="Петя"))
    assert len(brain.llm.calls) == 2


async def test_group_admin_can_pause(brain):
    brain.evo.participants = [{"id": "999111@lid", "phoneNumber": VASYA, "admin": "admin"},
                              {"id": "999222@lid", "phoneNumber": PETYA, "admin": None}]
    await feed(brain, upsert("стелла помолчи 15"))
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    assert chat["paused_until"] > utcnow() + timedelta(minutes=10)


async def test_dm_can_be_paused_by_its_owner(brain):
    await feed(brain, upsert("стелла помолчи", chat=DM))
    chat = await brain.db.get_chat_by_jid("stella", DM)
    assert chat["paused_until"]


# ---------- несколько человек сразу ----------

async def test_each_person_gets_own_reply(brain):
    brain.llm.queue = ["тебе, Вася", "тебе, Петя", "тебе, Коля"]
    for sender, name, text in [(VASYA, "Вася", "стелла сколько будет 2+2"),
                               (PETYA, "Петя", "стелла а столица франции?"),
                               (KOLYA, "Коля", "стелла привет")]:
        await brain.handle_payload(upsert(text, sender=sender, name=name))
    await settle(brain)
    assert len(brain.llm.calls) == 3
    texts = [m for m in brain.evo.sent if m["type"] == "text"]
    assert [m["text"] for m in texts] == ["тебе, Вася", "тебе, Петя", "тебе, Коля"]
    # каждому — ответом на его сообщение, чтобы было понятно, кому
    assert [m["quoted"]["key"]["participant"] for m in texts] == [VASYA, PETYA, KOLYA]
    # во втором запросе видно, что Васе она уже ответила
    assert "тебе, Вася" in brain.llm.calls[1]["prompt"]


async def test_reply_each_max_merges_the_rest(brain):
    brain.s.reply_each_max = 2
    brain.s.batch_window_min = brain.s.batch_window_max = 0.3  # все трое попадают в одну пачку
    brain.s.batch_max_wait = 1
    brain.llm.queue = ["раз", "два"]
    for sender, name in [(VASYA, "Вася"), (PETYA, "Петя"), (KOLYA, "Коля")]:
        await brain.handle_payload(upsert("стелла привет", sender=sender, name=name))
    await settle(brain)
    assert len(brain.llm.calls) == 2
    assert brain.llm.calls[1]["prompt"].count("★") >= 2  # Петя и Коля — в одном общем ответе


async def test_follow_up_from_another_person_is_considered(brain):
    brain.s.chime_default = "normal"  # в режиме «выкл» в чужие разговоры не встревает вовсе
    brain.llm.queue = ["4", "я ИИ-ассистент, отвечаю на вопросы"]
    await feed(brain, upsert("стелла сколько будет 2+2"))
    await feed(brain, upsert("а ты вообще кто?", sender=PETYA, name="Петя"))
    assert len(brain.llm.calls) == 2
    assert "Возможно, это продолжение" in brain.llm.calls[1]["prompt"]


def test_follow_up_needs_her_recent_message():
    inc = parse_upsert(upsert("а ты вообще кто?", sender=PETYA, name="Петя"))
    kw = dict(stems=name_stems("Стелла"), bot=BotIdentity({BOT}), quoted_is_bot=False, talking_with_sender=False)
    assert classify(inc, **kw, bot_spoke_recently=True) == CONTINUE
    assert classify(inc, **kw, bot_spoke_recently=False) != CONTINUE


# ---------- как к ней обращаются ----------

def test_name_variants_and_latin_lookalikes():
    kw = dict(stems=name_stems("Стелла"), bot=BotIdentity({BOT}), quoted_is_bot=False, talking_with_sender=False)
    for text in ["Стеля привет", "Cтелла ау", "стелька помоги", "СТЕЛЛА", "stella hi", "стелааа"]:
        assert classify(parse_upsert(upsert(text)), **kw) == DIRECT, text
    for text in ["купил стеллаж", "постель", "стели постель"]:
        assert classify(parse_upsert(upsert(text)), **kw) != DIRECT, text


async def test_own_lid_from_evolution_makes_lid_mentions_work(brain):
    brain.evo.me = ["77000000001:12@s.whatsapp.net", "123456789:12@lid"]
    await brain.learn_own_jids()
    assert "123456789@lid" in brain.bot.jids
    brain.llm.queue = ["я тут"]
    await feed(brain, upsert("@123456789 помоги", mentioned=["123456789@lid"]))
    assert len(brain.llm.calls) == 1


async def test_group_participants_teach_own_lid_and_link_people(brain):
    brain.evo.participants = [{"id": "777000@lid", "phoneNumber": BOT, "admin": None},
                              {"id": "888000@lid", "phoneNumber": PETYA, "admin": None}]
    await feed(brain, upsert("всем привет", sender=PETYA, name="Петя"))
    assert "777000@lid" in brain.bot.jids
    petya = await brain.db.find_person_by_jid("888000@lid")
    assert petya and petya.phone == "77022222222"
    brain.llm.queue = ["привет)"]
    await feed(brain, upsert("@777000 привет", sender=PETYA, name="Петя", mentioned=["777000@lid"]))
    assert len(brain.llm.calls) == 1


async def test_lid_group_mentions_by_lid(brain):
    lid_msg = upsert("всем ку", sender="888000@lid", name="Петя")
    lid_msg["data"]["key"]["participantAlt"] = PETYA
    lid_msg["data"]["key"]["addressingMode"] = "lid"
    await feed(brain, lid_msg)
    brain.llm.queue = ["@Петя привет"]
    await feed(brain, upsert("стелла поздоровайся с петей"))
    last = brain.evo.sent[-1]
    assert last["text"] == "@888000 привет" and last["mentioned"] == ["888000@lid"]


def test_parser_strips_device_suffix_and_handles_lid_dm():
    p = upsert("привет", chat="555@lid")
    p["data"]["key"]["remoteJidAlt"] = "77044444444@s.whatsapp.net"
    inc = parse_upsert(p)
    assert inc.chat_jid == "77044444444@s.whatsapp.net" and inc.is_dm and inc.sender_alt == "555@lid"

    g = upsert("ку", sender="77011111111:5@s.whatsapp.net", mentioned=["123:7@lid"])
    inc = parse_upsert(g)
    assert inc.sender_jid == VASYA and inc.mentioned == ["123@lid"]

    d = upsert(message={"documentWithCaptionMessage": {"message": {"documentMessage": {"caption": "стелла глянь"}}}},
               message_type="documentWithCaptionMessage")
    inc = parse_upsert(d)
    assert inc.kind == "document" and inc.text == "стелла глянь"


# ---------- в личке ----------

async def test_dm_prompt_says_always_answer(brain):
    brain.llm.queue = ["ок"]
    await feed(brain, upsert("слушай", chat=DM))
    assert "Тебе пишут в личку" in brain.llm.calls[0]["prompt"]


async def test_minimal_mode_never_holds_grudges(brain):
    assert brain.s.prompt_style == "minimal"
    await feed(brain, upsert("привет"))
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    vasya = await brain.db.find_person_by_jid(VASYA)
    await brain.db.set_grudge(chat["id"], vasya.id, utcnow() + timedelta(hours=5), "обозвал")
    brain.llm.queue = ["слушаю"]
    await feed(brain, upsert("стелла помоги с домашкой"))
    call = brain.llm.calls[-1]
    assert "обижена" not in call["prompt"] and "take_offense" not in call["tools"]
    assert brain.evo.texts()[-1] == "слушаю"


# ---------- сбои модели ----------

async def test_llm_hiccup_is_retried(brain):
    brain.llm.queue = [LLMError("overloaded"), "вот ответ"]
    await feed(brain, upsert("стелла помоги"))
    assert len(brain.llm.calls) == 2
    assert brain.evo.texts() == ["вот ответ"]


async def test_no_retry_after_side_effects(brain):
    async def bet_then_fail(tools, prompt):
        await tools["casino"].handler({"action": "play", "game": "coin", "choice": "heads", "amount": 100})
        raise LLMError("timeout")

    brain.llm.queue = [bet_then_fail, "второй раз ставить нельзя"]
    await feed(brain, upsert("стелла поставь сотку на орла"))
    assert len(brain.llm.calls) == 1


# ---------- Evolution ----------

def _evo(handler):
    client = httpx.AsyncClient(base_url="http://evo", transport=httpx.MockTransport(handler), headers={"apikey": "k"})
    return Evolution("http://evo", "k", "stella", client=client)


async def test_send_is_not_retried_after_read_timeout():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("slow", request=request)

    evo = _evo(handler)
    try:
        await evo.send_text("77011111111@s.whatsapp.net", "привет")
    except Exception:
        pass
    assert calls == ["/message/sendText/stella"]  # без дублей


async def test_own_jids_and_poll_limit():
    seen = {}

    def handler(request):
        if request.url.path == "/baileys/getAuthState/stella":
            return httpx.Response(200, json={"me": {"id": "77000000001:3@s.whatsapp.net", "lid": "4242:3@lid"}})
        seen["poll"] = json.loads(request.content)
        return httpx.Response(201, json={"key": {"id": "P1"}})

    evo = _evo(handler)
    assert await evo.own_jids() == ["77000000001@s.whatsapp.net", "4242@lid"]
    await evo.send_poll(GROUP, "?", [str(i) for i in range(14)] + ["1"])
    assert len(seen["poll"]["values"]) == 10


# ---------- диагностика ----------

async def test_diag_reports_pauses_and_unpauses(settings, monkeypatch):
    db = DB(settings.database_url)
    await db.init()
    chat = await db.get_or_create_chat("stella", GROUP, True)
    await db.update_chat(chat["id"], title="7в", paused_until=utcnow() + timedelta(minutes=20))
    await db.close()
    monkeypatch.setattr(diag, "settings", settings)
    lines: list[str] = []
    await diag.main([], out=lines.append)
    assert any("7в" in line and "ПАУЗА" in line for line in lines)
    lines.clear()
    await diag.main(["--unpause"], out=lines.append)
    assert any("пауза снята в чатах: 1" in line for line in lines)
    assert not any("ПАУЗА" in line for line in lines)


# ---------- второй круг: что нашла проверка ----------

async def test_person_first_seen_by_lid_in_quote_still_gets_answer(brain):
    """Петю сначала процитировали по LID, потом он пишет сам (LID + номер) — Стелла ему отвечает."""
    lid = "888000@lid"
    await feed(brain, upsert("смотрите что он написал", quoted={"stanzaId": "Q1", "participant": lid,
                                                                  "quotedMessage": {"conversation": "лол"}}))
    msg = upsert("стелла привет", sender=lid, name="Петя")
    msg["data"]["key"]["participantAlt"] = PETYA
    brain.llm.queue = ["привет, Петя"]
    await feed(brain, msg)
    assert brain.evo.texts()[-1] == "привет, Петя"
    p1 = await brain.db.find_person_by_jid(PETYA)
    p2 = await brain.db.find_person_by_jid(lid)
    assert p1 and p2 and p1.id == p2.id


async def test_known_person_quoted_by_lid_is_not_duplicated(brain):
    msg = upsert("всем ку", sender="888000@lid", name="Петя")
    msg["data"]["key"]["participantAlt"] = PETYA
    await feed(brain, msg)
    await feed(brain, upsert("ахах", quoted={"stanzaId": "Q2", "participant": "888000@lid",
                                              "quotedMessage": {"conversation": "всем ку"}}))
    chat = await brain.db.get_chat_by_jid("stella", GROUP)
    members = await brain.db.chat_members(chat["id"], limit=50)
    assert len([m for m in members if "888000@lid" in (m.jid, m.alt_jid)]) == 1


async def test_follow_up_and_new_question_in_one_batch_both_handled(brain):
    brain.s.chime_default = "normal"
    brain.llm.queue = ["4"]
    await feed(brain, upsert("стелла сколько будет 2+2"))
    brain.s.batch_window_min = brain.s.batch_window_max = 0.3
    brain.s.batch_max_wait = 1
    brain.llm.queue = ["потому что так считают", "привет, Петя"]
    await brain.handle_payload(upsert("а почему так?"))  # Вася продолжает
    await brain.handle_payload(upsert("стелла привет", sender=PETYA, name="Петя"))
    await settle(brain)
    assert len(brain.llm.calls) == 3
    assert "Возможно, это продолжение" in brain.llm.calls[1]["prompt"]
    assert brain.evo.texts()[-2:] == ["потому что так считают", "привет, Петя"]


async def test_follow_up_after_command_goes_to_her(brain):
    await feed(brain, upsert("стелла баланс"))
    brain.llm.queue = ["бонус раз в 12 часов"]
    await feed(brain, upsert("а как получить больше"))
    assert len(brain.llm.calls) == 1


async def test_bare_stop_in_dm_is_not_a_pause_and_au_unpauses(brain):
    brain.llm.queue = ["ок, остановилась"]
    await feed(brain, upsert("стоп", chat=DM))
    chat = await brain.db.get_chat_by_jid("stella", DM)
    assert not chat["paused_until"] and len(brain.llm.calls) == 1
    await feed(brain, upsert("стелла помолчи", chat=DM))
    chat = await brain.db.get_chat_by_jid("stella", DM)
    assert chat["paused_until"]
    await feed(brain, upsert("ау", chat=DM))
    chat = await brain.db.get_chat_by_jid("stella", DM)
    assert not chat["paused_until"] and "снова здесь" in brain.evo.texts()[-1]


def test_stretched_names():
    kw = dict(stems=name_stems("Стелла"), bot=BotIdentity({BOT}), quoted_is_bot=False, talking_with_sender=False)
    for text in ["СТЕЛЛАААА", "Стелллла", "Стелличка", "stellaa", "Stell ау"]:
        assert classify(parse_upsert(upsert(text)), **kw) == DIRECT, text
    for text in ["steel", "стеллажи"]:
        assert classify(parse_upsert(upsert(text)), **kw) != DIRECT, text


def test_parser_album_child_and_poll_v2():
    album = upsert(message={"messageContextInfo": {}, "associatedChildMessage": {"message": {
        "imageMessage": {"caption": "стелла что это"}}}}, message_type="associatedChildMessage")
    inc = parse_upsert(album)
    assert inc and inc.kind == "image" and inc.text == "стелла что это"
    poll = upsert(message={"pollCreationMessageV2": {"name": "куда идём", "options": [{"optionName": "кино"}]}},
                  message_type="pollCreationMessageV2")
    inc = parse_upsert(poll)
    assert inc and inc.kind == "poll"


async def test_casino_result_shown_even_if_model_fails_after(brain):
    async def bet_then_fail(tools, prompt):
        await tools["casino"].handler({"action": "play", "game": "coin", "choice": "heads", "amount": 100})
        raise LLMError("timeout")

    brain.llm.queue = [bet_then_fail]
    await feed(brain, upsert("стелла поставь сотку на орла"))
    texts = brain.evo.texts()
    assert any("монетку" in t for t in texts)
    assert not any("зависла" in t for t in texts)


async def test_resend_after_fallback_is_heard(brain):
    brain.llm.queue = [LLMError("a"), LLMError("b")]
    await feed(brain, upsert("стелла помоги"))
    assert "зависла" in brain.evo.texts()[-1] or "получилось" in brain.evo.texts()[-1]
    brain.llm.queue = ["вот"]
    await feed(brain, upsert("помоги пж"))  # без имени — но это ей
    assert brain.evo.texts()[-1] == "вот"


# ---------- бэкенды модели ----------

async def test_agent_sdk_keeps_text_when_turns_run_out(monkeypatch, tmp_path):
    import claude_agent_sdk as sdk

    from bot.llm.agent_sdk import AgentSdkLLM

    def fake_query(stop_reason=None, subtype="error_max_turns"):
        async def q(prompt, options):
            yield sdk.AssistantMessage(content=[sdk.TextBlock(text="запомнила, Аня!")], model="m",
                                       stop_reason=stop_reason)
            yield sdk.ResultMessage(subtype=subtype, duration_ms=1, duration_api_ms=1, is_error=True, num_turns=5,
                                    session_id="s", total_cost_usd=0.01)
            raise RuntimeError("Claude Code returned an error result (exit code: 1)")
        return q

    llm = AgentSdkLLM("claude-sonnet-5-5", sandbox_dir=str(tmp_path / "sb"))
    monkeypatch.setattr(sdk, "query", fake_query())
    reply = await llm.ask(system="s", prompt="p")
    assert reply.text == "запомнила, Аня!" and reply.cost_usd == 0.01

    from bot.llm.base import LLMRefusal
    monkeypatch.setattr(sdk, "query", fake_query(stop_reason="refusal", subtype="success"))
    try:
        await llm.ask(system="s", prompt="p")
        raise AssertionError("ожидали отказ")
    except LLMRefusal:
        pass


async def test_messages_api_keeps_text_before_empty_last_turn():
    from types import SimpleNamespace as NS

    from bot.llm.base import ToolSpec
    from bot.llm.messages_api import MessagesApiLLM

    async def remember(args):
        return "ок"

    usage = NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    first = NS(stop_reason="tool_use", usage=usage, stop_details=None, content=[
        NS(type="text", text="Привет, Аня!"), NS(type="tool_use", id="t1", name="remember", input={})])
    second = NS(stop_reason="end_turn", usage=usage, stop_details=None, content=[])

    class Fake:
        def __init__(self):
            self.items = [first, second]

        async def create(self, **kw):
            return self.items.pop(0)

    fake = Fake()
    llm = MessagesApiLLM("claude-haiku-5-5", client=NS(messages=fake, beta=NS(messages=fake)))
    reply = await llm.ask(system="s", prompt="p", tools=[ToolSpec("remember", "d", {"type": "object"}, remember)])
    assert reply.text == "Привет, Аня!"


# ---------- третий круг: после независимой проверки ----------

async def test_owner_takeover_in_dm_is_not_ended_by_everyday_words(brain):
    await feed(brain, upsert("я сам отвечу", chat=DM, from_me=True, sender=BOT, msg_id="OWN1"))
    await feed(brain, upsert("ну не говори маме пожалуйста", chat=DM))
    await feed(brain, upsert("ау", chat=DM))
    chat = await brain.db.get_chat_by_jid("stella", DM)
    assert chat["paused_until"] and brain.llm.calls == [] and brain.evo.texts() == []


def test_insoles_are_not_her_name():
    kw = dict(stems=name_stems("Стелла"), bot=BotIdentity({BOT}), quoted_is_bot=False, talking_with_sender=False)
    for text in ["купила новые стельки", "стельку порвал", "со стелькой", "в стельке дырка"]:
        assert classify(parse_upsert(upsert(text)), **kw) != DIRECT, text
    assert classify(parse_upsert(upsert("Стелька, привет")), **kw) == DIRECT


def test_follow_up_rule_is_narrow():
    from bot.addressing import looks_like_question_to_her

    stems = name_stems("Стелла")
    assert looks_like_question_to_her("а ты вообще кто?", stems)
    assert looks_like_question_to_her("объясни ещё раз", stems)
    for text in ["коля, ты придёшь завтра?", "кто идёт в кино?", "давай в кино", "мне тоже", "ты где"]:
        assert not looks_like_question_to_her(text, stems), text


async def test_casino_bets_do_not_turn_chatter_into_model_calls(brain):
    await feed(brain, upsert("стелла красное 100"))
    await feed(brain, upsert("блин опять проиграл"), upsert("ладно пофиг"))
    assert brain.llm.calls == []


async def test_no_retry_after_delete_tool(brain):
    brain.llm.queue = ["первый ответ"]
    await feed(brain, upsert("стелла привет"))

    async def delete_then_fail(tools, prompt):
        await tools["delete_my_last_message"].handler({})
        raise LLMError("overloaded")

    brain.llm.queue = [delete_then_fail, "второй раз удалять нельзя"]
    await feed(brain, upsert("стелла удали своё последнее сообщение пожалуйста"))
    assert len([m for m in brain.evo.sent if m["type"] == "delete"]) == 1
    assert len(brain.llm.calls) == 2


def test_pn_group_is_not_flagged_as_lid():
    p = upsert("ку", sender=VASYA)
    p["data"]["key"]["participantAlt"] = "999@lid"
    p["data"]["key"]["addressingMode"] = "pn"
    assert parse_upsert(p).lid_addressing is False
    q = upsert("ку", sender="999@lid")
    q["data"]["key"]["participantAlt"] = VASYA
    assert parse_upsert(q).lid_addressing is True


async def test_duplicate_rows_for_one_person_are_merged(brain):
    db = brain.db
    chat = await db.get_or_create_chat("stella", GROUP, True)
    by_phone = await db.upsert_person(PETYA, "Петя", "77022222222")
    by_lid = await db.upsert_person("888000@lid", "")
    assert by_phone.id != by_lid.id
    await db.touch_member(chat["id"], by_phone.id)
    await db.touch_member(chat["id"], by_phone.id)
    await db.touch_member(chat["id"], by_lid.id)
    await db.update_profile(by_phone.id, chat["id"], {"увлечения": "футбол"})
    await db.update_profile(by_lid.id, chat["id"], {"учёба": "7в"})
    await db.add_fact(by_lid.id, chat["id"], "любит пиццу", "auto", 50)
    await brain.casino.grant(chat["id"], by_lid, 3000)
    rich = await brain.casino.balance(chat["id"], by_lid)

    merged = await db.upsert_person(PETYA, "Петя", "77022222222", "888000@lid")
    assert merged.id == by_phone.id and merged.alt_jid == "888000@lid"
    assert (await db.find_person_by_jid("888000@lid")).id == by_phone.id
    assert await db.get_profile(by_phone.id, chat["id"]) == {"увлечения": "футбол", "учёба": "7в"}
    assert "любит пиццу" in await db.get_facts(by_phone.id, chat["id"], 10)
    members = await db.chat_members(chat["id"], limit=10)
    assert [m.id for m in members] == [by_phone.id]
    assert await brain.casino.balance(chat["id"], merged) == rich  # бананы не потерялись
