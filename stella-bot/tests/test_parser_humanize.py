import random

from bot.humanize import add_typo, is_silence, parse_reply, typing_ms
from bot.parser import parse_upsert
from bot.util import mask_phone

from .conftest import BOT, GROUP, VASYA, upsert


def test_parse_group_text_with_mention_and_quote():
    p = upsert("@77000000001 привет", mentioned=[BOT],
               quoted={"stanzaId": "Q1", "participant": BOT, "quotedMessage": {"conversation": "я тут"}})
    inc = parse_upsert(p)
    assert inc and inc.is_group and inc.chat_jid == GROUP and inc.sender_jid == VASYA
    assert inc.text == "@77000000001 привет" and inc.kind == "text"
    assert inc.mentioned == [BOT] and inc.quoted_id == "Q1" and inc.quoted_text == "я тут"
    assert inc.bot_jid == BOT


def test_parse_lid_participant_prefers_phone():
    p = upsert("hi")
    p["data"]["key"]["participant"] = "123456789@lid"
    p["data"]["key"]["participantAlt"] = VASYA
    inc = parse_upsert(p)
    assert inc.sender_jid == VASYA and inc.sender_alt == "123456789@lid"


def test_parse_ignores_status_and_protocol():
    assert parse_upsert(upsert("x", chat="status@broadcast")) is None
    assert parse_upsert(upsert(message={"protocolMessage": {}}, message_type="protocolMessage")) is None
    assert parse_upsert(upsert("   ")) is None


def test_parse_media():
    inc = parse_upsert(upsert(message={"audioMessage": {"seconds": 7, "ptt": True}}, message_type="audioMessage"))
    assert inc.kind == "audio" and inc.duration == 7
    inc = parse_upsert(upsert(message={"stickerMessage": {"url": "x"}}, message_type="stickerMessage"))
    assert inc.kind == "sticker" and inc.text == ""
    inc = parse_upsert(upsert(message={"imageMessage": {"caption": "смотри"}}, message_type="imageMessage"))
    assert inc.kind == "image" and inc.text == "смотри"
    inc = parse_upsert(upsert(message={"ephemeralMessage": {"message": {"extendedTextMessage": {"text": "эфемер"}}}},
                              message_type="ephemeralMessage"))
    assert inc.kind == "text" and inc.text == "эфемер"


def test_parse_reply_bubbles_stickers_reactions():
    segs = parse_reply("Стелла: привет!!\n[реакция: 😂]\n**ну ты даёшь**\n[стикер: смех]\n[стикер: шок]\n- как дела")
    kinds = [(s.kind, s.value) for s in segs]
    assert kinds == [("text", "привет!!"), ("reaction", "😂"), ("text", "ну ты даёшь"), ("sticker", "смех"),
                     ("text", "как дела")]


def test_parse_reply_silence_and_limits():
    assert parse_reply("<молчу>") == []
    assert is_silence("  <молчу>  ")
    assert not is_silence("молчу как рыба")
    segs = parse_reply("\n".join(f"строка {i}" for i in range(10)), max_bubbles=4)
    texts = [s.value for s in segs if s.kind == "text"]
    assert len(texts) == 4 and texts[-1].startswith("строка 3") and texts[-1].endswith("строка 9")
    long = "Очень длинная мысль. " * 30
    assert len(parse_reply(long)) > 1


def test_typo_changes_one_word_and_offers_fix():
    rng = random.Random(3)
    text, fix = add_typo("сегодня отличная погода", rng, rate=1.0)
    assert text != "сегодня отличная погода" and fix and fix.startswith("*")
    assert fix[1:] in "сегодня отличная погода"
    assert add_typo("ок", rng, rate=1.0) == ("ок", None)
    assert add_typo("Вася красавчик", random.Random(1), rate=1.0, protect={"красавчик"})[1] is None


def test_typing_ms_bounds():
    rng = random.Random(0)
    assert 900 <= typing_ms("ок", rng, 9) <= 2000
    assert typing_ms("а" * 1000, rng, 9) == 9000
    assert typing_ms("что угодно", rng, 0) == 0


def test_mask_phone():
    assert mask_phone("77771234512@s.whatsapp.net") == "+7 777 *** ** 12"
    assert mask_phone(GROUP).startswith("group…")
