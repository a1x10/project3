import random

from stella.config import Config
from stella.core.memory import Memory
from stella.face.emotion_engine import EmotionEngine, detect_tone


def test_tones():
    assert "insult" in detect_tone("ты дура")
    assert "insult" not in detect_tone("ты не дура")
    assert detect_tone("сколько будет 100 долларов в рублях") == []   # «рублях» содержит «бля»
    assert "apology" in detect_tone("извини пожалуйста")
    assert "love" in detect_tone("я тебя люблю")


def test_anger_escalation_and_apology():
    e = EmotionEngine(Config(), Memory())
    assert e.level == "calm"
    e.on_user_text("ты тупая")
    e.on_user_text("дура")
    e.on_user_text("заткнись")
    assert e.level == "furious"
    random.seed(1)
    refusals = sum(e.should_refuse() for _ in range(100))
    assert refusals > 40                    # в ярости часто отказывается
    e.on_user_text("извини")
    e.on_user_text("прости меня")
    assert e.level in ("calm", "annoyed")
    assert "Ты" in e.mood_prompt() or e.mood_prompt() == "" or "ночь" in e.mood_prompt()


def test_touch_annoyance():
    e = EmotionEngine(Config(), Memory())
    results = [e.on_touch() for _ in range(6)]
    assert results[0] == "giggle"
    assert "annoyed" in results
