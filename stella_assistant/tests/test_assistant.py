"""Сквозные проверки навыков без интернета, микрофона и динамика."""
import tempfile

import pytest

from stella.config import Config
from stella.core.assistant import Assistant


@pytest.fixture(scope="module")
def a():
    cfg = Config()
    cfg.set("data_dir", tempfile.mkdtemp())
    cfg.set("smarthome.scenarios_file", tempfile.mktemp(suffix=".yaml"))
    cfg.set("music.music_dir", tempfile.mkdtemp())
    cfg.set("music.audiobooks_dir", tempfile.mkdtemp())
    assistant = Assistant(cfg, voice=False)
    assistant.tts.engines = []
    assistant.say = lambda *args, **kw: None
    yield assistant
    assistant.shutdown()


def ask(a, text):
    return a.ask(text, source="test", timeout=30)


def test_basic_info(a):
    assert "Сейчас" in ask(a, "который час").text
    assert "Сегодня" in ask(a, "какое сегодня число").text
    assert "Стелла" in ask(a, "как тебя зовут").text


def test_memory_and_name(a):
    ask(a, "меня зовут саша")
    assert "Саша" in ask(a, "как меня зовут").text
    ask(a, "запомни что мой любимый цвет синий")
    assert "синий" in ask(a, "что ты знаешь обо мне").text


def test_lists(a):
    r = ask(a, "добавь молоко, хлеб и яйца в список покупок")
    assert "молоко" in r.text and "яйца" in r.text
    ask(a, "вычеркни хлеб из списка покупок")
    r = ask(a, "что в списке покупок")
    assert "молоко" in r.text and "хлеб" not in r.text
    ask(a, "добавь задачу помыть машину")
    assert "помыть машину" in ask(a, "мои задачи").text


def test_alarms_timers_reminders(a):
    assert "Будильник" in ask(a, "разбуди меня в семь тридцать").text
    assert "по будням" in ask(a, "поставь будильник на шесть утра по будням").text
    assert "2 будильника" in ask(a, "какие будильники").text
    ask(a, "удали все будильники")
    assert "нет" in ask(a, "какие будильники").text
    assert "5 минут" in ask(a, "поставь таймер на пять минут для пасты").text
    assert "Осталось" in ask(a, "сколько осталось").text
    ask(a, "отмени таймер")
    assert "позвонить маме" in ask(a, "напомни завтра в десять позвонить маме").text


def test_calc_and_units(a):
    assert "100" in ask(a, "сколько будет 25 умножить на 4").text
    assert "8,05" in ask(a, "сколько будет 5 миль в километрах").text


def test_character_gets_angry(a):
    ask(a, "ты тупая железяка")
    ask(a, "дура")
    r = ask(a, "заткнись")
    assert r.emotion == "anger"
    assert a.mood.level == "furious"
    r = ask(a, "ты злишься?")
    assert r.emotion == "anger"
    ask(a, "извини")
    ask(a, "прости пожалуйста")
    assert a.mood.level in ("calm", "annoyed")


def test_games_and_recipes(a):
    r = ask(a, "загадай загадку")
    assert r.expect_reply
    assert "Это" in ask(a, "сдаюсь").text
    r = ask(a, "как приготовить блины")
    assert "Блины" in r.text
    assert "Шаг 1" in ask(a, "начинаем").text
    assert "Шаг 2" in ask(a, "дальше").text
    assert "закончили" in ask(a, "хватит").text


def test_emotions_on_request(a):
    assert ask(a, "покажи эмоцию грусть").emotion == "sadness"
    assert ask(a, "покажи удивление").emotion == "surprise"


def test_scenario_creation(a):
    r = ask(a, "создай сценарий когда я говорю я дома включи свет и скажи привет")
    assert "Сценарий создан" in r.text
    assert any(t.get("phrase") == "я дома" for s in a.skill("smarthome").scenarios for t in s["triggers"])


def test_whisper_mode(a):
    ask(a, "говори шепотом")
    assert a.whisper_mode
    ask(a, "говори нормально")
    assert not a.whisper_mode
