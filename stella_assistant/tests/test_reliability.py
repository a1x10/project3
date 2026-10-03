"""Надёжность: запуск без микрофона и экрана, будильники, прерывание речи, сессии, разбор команд.

Каждый тест — сценарий, который раньше ломался (см. историю коммитов).
"""
import time
from datetime import datetime, timedelta

import numpy as np
import pytest
import requests

from stella.audio import io as audio_io
from stella.audio.player import MusicPlayer, Track
from stella.audio.stt import Listener, WakeMatcher
from stella.config import Config
from stella.core.assistant import Assistant
from stella.core.events import bus
from stella.face.emotion_engine import detect_tone
from stella.face.face import Face
from stella.integrations.telegram_bot import parse_allowed
from stella.llm.groq import GroqLLM
from stella.llm.yandexgpt import LLMError
from stella.nlp.text import norm
from stella.nlp.timeparse import When, parse_when
from stella.skills.alarms import Ringer
from stella.skills.base import Context, Reply
from stella.skills.smarthome import Device

LONG = "Очень длинная статья про всё на свете. " * 25


def wait_until(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def no_network(*a, **k):
    raise requests.ConnectionError("нет сети в тестах")


class FakeSpeaker:
    """Динамик, который «играет» звук ровно столько, сколько он длится, и останавливается по stop()."""

    def __init__(self, spk):
        self.spk = spk
        self.calls = []

    def play(self, samples, sr, animate=True, volume=1.0):
        spk = self.spk
        with spk._lock:
            spk._stop.clear()
            spk.speaking = True
            self.calls.append((len(samples) / sr, animate))
            try:
                end = time.time() + len(samples) / sr
                while time.time() < end:
                    if spk._stop.wait(0.005):
                        return False
                return True
            finally:
                spk.speaking = False


@pytest.fixture
def live(tmp_path):
    cfg = Config()
    cfg.set("data_dir", str(tmp_path / "data"))
    cfg.set("smarthome.scenarios_file", str(tmp_path / "scenarios.yaml"))
    cfg.set("music.music_dir", str(tmp_path / "music"))
    cfg.set("music.audiobooks_dir", str(tmp_path / "books"))
    a = Assistant(cfg, voice=False)
    a.tts.synth = lambda text, emotion="neutral", whisper=False, lang="ru": (
        np.zeros(int(22050 * 0.02 * len(text)), np.int16), 22050)
    a.fake_speaker = FakeSpeaker(a.speaker)
    a.speaker.play = a.fake_speaker.play
    a.player.duck = a.player.unduck = lambda: None
    a.player.is_playing = a.player.is_active = lambda: False
    a.http.request = no_network
    a.skill("music")._play_what = lambda what: Reply(f"музыка: {what}")
    yield a
    a.shutdown()


def ring_alarm(a):
    a.memory.alarm_add("alarm", time.time() - 1, "")
    a.skill("alarms").check_due()
    assert wait_until(lambda: a.ringing is not None)
    return a.ringing


# ------------------------------------------------------------------- запуск --
class FakeSD:
    """sounddevice без нужного микрофона или с микрофоном, который умеет только стерео 48 кГц."""

    def __init__(self, has_device=True, channels=(1,), rates=(16000,)):
        self.has_device, self.channels, self.rates = has_device, channels, rates

    def RawInputStream(self, samplerate, blocksize, device, channels, dtype, callback):
        if not self.has_device:
            raise ValueError(f"No input device matching {device!r}")
        if channels not in self.channels or samplerate not in self.rates:
            raise RuntimeError("Invalid number of channels / sample rate")
        return type("Stream", (), {"start": lambda self: None, "device": device})()

    def query_devices(self, device, kind):
        if not self.has_device:
            raise ValueError(f"No input device matching {device!r}")
        return {"default_samplerate": 48000.0, "max_input_channels": 2}


def test_missing_microphone_does_not_crash(monkeypatch):
    cfg = Config()
    cfg.set("audio.input_device", "ReSpeaker")
    monkeypatch.setattr(audio_io, "_sd", lambda: FakeSD(has_device=False))
    hub = audio_io.MicHub(cfg)
    assert hub.start() is False and not hub.ok


def test_stereo_only_microphone_is_downmixed(monkeypatch):
    monkeypatch.setattr(audio_io, "_sd", lambda: FakeSD(channels=(2,), rates=(48000,)))
    hub = audio_io.MicHub(Config())
    assert hub.start() and (hub.native_rate, hub.channels) == (48000, 2)
    q = hub.subscribe()
    stereo = np.stack([np.full(4800, 1000, np.int16), np.full(4800, 3000, np.int16)], axis=1)
    hub._callback(stereo.tobytes(), 4800, None, None)
    mono = q.get_nowait()
    assert len(mono) == 1600 and abs(int(np.median(mono)) - 2000) < 50


def test_face_survives_missing_display(monkeypatch):
    original = Face._open_window
    tried = []

    def flaky(self, pygame):
        tried.append(self.headless)
        if not self.headless:
            raise RuntimeError("kmsdrm not available")
        return original(self, pygame)
    monkeypatch.setattr(Face, "_open_window", flaky)
    cfg = Config()
    cfg.set("display.fullscreen", False)
    face = Face(cfg)
    face._init_display()
    assert tried == [False, True] and face.headless and face.screen is not None


def test_telegram_allowed_users_accepts_names():
    assert parse_allowed([12345, "-100777", "@Masha", " petya "]) == ({12345, -100777}, {"masha", "petya"})
    assert parse_allowed("@solo") == (set(), {"solo"})
    assert parse_allowed(None) == (set(), set())


# ------------------------------------------------------------- слово «Стелла» --
@pytest.mark.parametrize("heard,expected", [
    ("стелла", (True, "")),
    ("с тела какая погода", (True, "какая погода")),    # так Vosk слышит «Стелла, какая погода»
    ("тела стоп", (True, "стоп")),                      # …и «Стелла, стоп»
    ("стила который час", (True, "который час")),
    ("эй стелла", (True, "")),
    ("включи музыку стелла", (True, "включи музыку")),
    ("стена", (False, "стена")),
    ("стёпа иди сюда", (False, "стёпа иди сюда")),
    ("стекла грязные", (False, "стекла грязные")),
    ("стели постель", (False, "стели постель")),
    ("я стелю постель", (False, "я стелю постель")),
    ("тело болит", (False, "тело болит")),
])
def test_wake_word_variants(heard, expected):
    assert WakeMatcher(["стелла", "стела", "стелло", "stella"]).find(heard) == expected


def make_listener(events):
    cfg = Config()
    cfg.set("stt.cloud", "off")
    return Listener(cfg, None, on_wake=lambda: events.append("wake"),
                    on_command=lambda text, whisper: events.append(("cmd", text)),
                    on_timeout=lambda: events.append("timeout"))


def test_wake_heard_only_in_partial_result_times_out():
    events = []
    lis = make_listener(events)
    lis._partial("стелла", muted=False)
    assert events == ["wake"] and lis.mode == "command"   # ждём команду, а не висим в «слушаю»
    lis.deadline = time.time() - 1
    lis._check_timeout()
    assert events == ["wake", "timeout"] and lis.mode == "wake"


def test_command_after_partial_wake_is_delivered():
    events = []
    lis = make_listener(events)
    lis._partial("стелла", muted=False)
    lis._final("стелла какая погода", np.zeros(800, np.int16), muted=False)
    assert wait_until(lambda: ("cmd", "какая погода") in events)
    lis.stop()


class FakeListener:
    def __init__(self):
        self.listen_calls = []

    def listen_now(self, timeout=None):
        self.listen_calls.append(timeout)

    def mute(self, seconds):
        pass

    def unmute(self, reset=True):
        pass

    def stop(self):
        pass


def test_space_key_wake_listens_for_command(live):
    live.listener = FakeListener()
    bus.emit("wake", source="key")                   # пробел на клавиатуре — как «Стелла»
    assert live.listener.listen_calls and live.listening


# ------------------------------------------------------------------- время --
def test_minutes_are_not_hours():
    now = datetime(2026, 10, 3, 18, 50)
    for phrase in ("поставь будильник на 10 минут", "на 20 минут", "напомни на 15 минут позже"):
        assert parse_when(phrase, now=now, prefer="morning") is None, phrase
    assert parse_when("будильник на 7", now=now, prefer="morning").dt == datetime(2026, 10, 4, 7, 0)


def test_alarm_in_minutes_is_relative(live):
    r = live.ask("поставь будильник на 10 минут", source="test")
    due = live.memory.alarms("alarm")[0]["due"]
    assert "через 10 минут" in r.text and abs(due - (time.time() + 600)) < 5


def test_reminder_for_today_in_the_past_asks_for_time(live):
    al = live.skill("alarms")
    past = When(dt=datetime.now() - timedelta(hours=3), has_date=True, has_time=False)
    r = al._create_reminder(past, "позвонить маме")
    assert r.expect_reply and "Во сколько" in r.text and not live.memory.alarms("reminder")
    r = live.ask("через 2 часа", source="test")
    reminders = live.memory.alarms("reminder")
    assert "позвонить маме" in r.text and len(reminders) == 1 and reminders[0]["due"] > time.time() + 3600


# ------------------------------------------------------------- будильники --
def test_wake_during_alarm_then_snooze_keeps_weekday_alarm(live):
    live.ask("поставь будильник на 7 утра по будням", source="test")
    alarm = live.memory.alarms("alarm")[0]
    live.memory.alarm_update(alarm["id"], due=time.time() - 1)
    greet = []
    live.skill("alarms").morning_greeting = lambda: greet.append(1)
    live.skill("alarms").check_due()
    assert wait_until(lambda: live.ringing is not None)
    ringer = live.ringing
    live.on_wake()                                   # «Стелла, …» — звонок замолкает, но не выключается
    assert live.ringing is ringer and ringer.silenced and ringer.active
    r = live.handle("отложи будильник на 10 минут", source="voice")
    assert "10 минут" in r.text and not ringer.active
    alarms = live.memory.alarms("alarm")
    assert any(x["repeat"] == [0, 1, 2, 3, 4] for x in alarms)          # постоянный будильник цел
    assert any(x["extra"].get("snoozed") for x in alarms)
    r = live.handle("отключи будильник", source="voice")                 # сразу после звонка — не удаляет
    assert [x["repeat"] for x in live.memory.alarms("alarm")] == [[0, 1, 2, 3, 4]]
    assert not greet


def test_wake_without_command_resumes_alarm(live):
    ringer = ring_alarm(live)
    live.on_wake()
    assert ringer.silenced
    live.on_timeout()                                # позвали и замолчали — звонит дальше
    assert ringer.active and not ringer.silenced
    ringer.stop()


def test_other_command_dismisses_alarm_without_greeting(live):
    greet = []
    live.skill("alarms").morning_greeting = lambda: greet.append(1)
    ringer = ring_alarm(live)
    live.on_wake()
    live.handle("который час", source="voice")
    assert not ringer.active
    assert wait_until(lambda: live.ringing is None)
    time.sleep(0.2)
    assert not greet


def test_touch_dismisses_alarm_with_greeting(live):
    greet = []
    live.skill("alarms").morning_greeting = lambda: greet.append(1)
    ring_alarm(live)
    bus.emit("touch", x=10, y=10, w=800, h=480)
    assert wait_until(lambda: greet == [1])


def test_music_alarm_falls_back_to_melody(live, monkeypatch):
    monkeypatch.setattr(Ringer, "MUSIC_WAIT", 0.3)
    live.skill("music").play_default = lambda **k: Reply("Не получилось включить")   # сети нет — музыки нет
    live.memory.alarm_add("alarm", time.time() - 1, "", extra={"music": True})
    live.skill("alarms").check_due()
    assert wait_until(lambda: any(not animate for _, animate in live.fake_speaker.calls), 5)   # мелодия звучит
    live.ringing.stop()


def test_presence_needs_three_misses_to_leave(live):
    al = live.skill("alarms")
    al._home, al._seen, events = None, [], []
    al._presence_event = events.append
    for home in (True, True, True, False, True, True, False, True):
        al._phone_home = lambda h=home: h
        al.check_presence()
    assert events == []                              # телефон «уснул» в Wi-Fi — это не уход из дома
    for home in (False, False, False, True):
        al._phone_home = lambda h=home: h
        al.check_presence()
    assert events == ["leave", "arrive"]


# ------------------------------------------------------------------ речь --
def test_web_stop_cuts_long_speech_immediately(live):
    live.say(LONG, wait=False)
    assert wait_until(lambda: live.speaker.speaking)
    started = time.time()
    live.ask("стоп", source="web", timeout=5)
    assert time.time() - started < 1.0
    assert wait_until(lambda: not live.is_speaking(), 1.0)


def test_commands_are_answered_while_speaking(live):
    live.say(LONG, wait=False)
    assert wait_until(lambda: live.speaker.speaking)
    started = time.time()
    r = live.ask("который час", source="web", timeout=5)
    assert "Сейчас" in r.text and time.time() - started < 1.0 and live.is_speaking()


def test_timer_interrupts_speech(live):
    live.start()
    live.say(LONG, wait=False)
    assert wait_until(lambda: live.speaker.speaking)
    live.memory.alarm_add("timer", time.time() + 0.2, "паста")
    assert wait_until(lambda: live.ringing is not None, 3.0)
    live.ringing.stop()
    assert wait_until(lambda: not live.is_speaking(), 2.0)


def test_touch_interrupts_speech(live):
    live.say(LONG, wait=False)
    assert wait_until(lambda: live.speaker.speaking)
    bus.emit("touch", x=10, y=10, w=800, h=480)
    assert wait_until(lambda: not live.is_speaking(), 1.0)


def test_face_stays_asleep_after_reply(live):
    states = []
    handler = bus.on("state", lambda state, **_: states.append(state))
    try:
        live.say("Сладких снов! Если что — зови.", wait=False)
        assert wait_until(lambda: live.speaker.speaking)
        live.mood.sleep()                            # уснула, пока договаривала
        assert wait_until(lambda: not live.is_speaking(), 3.0)
        assert states[-1] == "sleep"
    finally:
        bus.off("state", handler)


def test_demo_end_clears_caption_and_restores_mood():
    face = Face(Config())
    resets = []
    handler = bus.on("face_reset", lambda **_: resets.append(1))
    try:
        face.demo = True
        face.demo_tick(4 * 3 + 0.1)                  # «злость»
        assert face.anim.info and face.mood[0] == "anger"
        face.end_demo()
        assert face.anim.info == "" and face.mood[0] == "neutral" and not face.demo and resets == [1]
    finally:
        bus.off("face_reset", handler)


# ----------------------------------------------------------------- сессии --
def test_game_does_not_swallow_other_commands(live):
    live.ask("угадай число", source="test")
    r = live.ask("поставь будильник на 7", source="test")
    assert "Будильник" in r.text and live.session is not None
    r = live.ask("50", source="test")
    assert "Моё число" in r.text or "Угадал" in r.text
    live.session.last_used -= 1000                   # долго молчали — игра закончилась сама
    live.ask("37", source="test")
    assert live.session is None


def test_recipe_navigation_needs_a_navigation_phrase(live):
    live.ask("как приготовить блины", source="test")
    assert "Шаг 1" in live.ask("начинаем", source="test").text
    assert "Шаг" not in live.ask("следующая песня", source="test").text
    assert "Шаг" not in live.ask("давай включим радио", source="test").text
    assert "Шаг 2" in live.ask("ну давай дальше", source="test").text


def test_cities_game_ignores_commands(live):
    live.ask("давай сыграем в города", source="test")
    r = live.ask("включи музыку", source="test")
    assert "города" not in r.text and r.text == "музыка: музыку"


def test_scenario_commands_bypass_session(live):
    live.ask("угадай число", source="test")
    r = live.handle("50", source="scenario")
    assert "Моё число" not in r.text


# ------------------------------------------------------------ разбор фраз --
@pytest.mark.parametrize("phrase,intent", [
    ("включи синий трактор", "music.play"),
    ("поставь белый шум", "music.play"),
    ("включи холодное сердце", "music.play"),
    ("включи аудиокнигу война и мир", "music.play"),
    ("включи радио мир", "music.play"),
    ("сделай свет синим", "smarthome.color"),
    ("не забудь купить молоко", "lists.need_to_buy"),
    ("мир", "social.apology"),
    ("сколько минут осталось на таймере", "alarms.timer_left"),
    ("поставь таймер на 5 минут", "alarms.set_timer"),
    ("послушай меня", None),
    ("слушай внимательно", None),
    ("будь рядом", None),
    ("сколько минут варить яйца", None),
    ("как далеко луна", None),
    ("фу", None),                                  # музыка не играет — это не дизлайк
    ("мне нравится", None),
])
def test_phrase_goes_to_the_right_skill(live, phrase, intent):
    ctx = Context(text=phrase, norm=norm(phrase), source="test", assistant=live)
    reply = live.route(ctx)
    assert (live.last_intent if reply else None) == intent


@pytest.mark.parametrize("phrase,insult", [
    ("какая ужасная погода", False), ("мне надоела эта песня", False), ("я достала молоко", False),
    ("ненавижу понедельники", False), ("замолчи", False), ("включи радио мир", False),
    ("ты меня достала", True), ("надоела", True), ("ты тупая", True), ("ненавижу тебя", True),
])
def test_insults_need_to_be_addressed(phrase, insult):
    assert ("insult" in detect_tone(phrase)) == insult


def test_repeating_commands_does_not_annoy(live):
    for _ in range(6):
        live.mood.on_user_text("дальше")
        live.mood.on_user_text("громче")
    assert live.mood.irritation < 1


def test_smart_home_device_matching(live):
    live.cfg.set("smarthome.yandex_token", "test")
    sh = live.skill("smarthome")
    on_off = [{"type": "devices.capabilities.on_off"}]
    devs = [Device("1", "Люстра", "Гостиная", "devices.types.light", caps=on_off),
            Device("2", "Свет", "Кухня", "devices.types.light", caps=on_off),
            Device("3", "Телевизор", "Гостиная", "devices.types.media_device.tv", caps=on_off),
            Device("4", "Яндекс Станция", "Гостиная", "devices.types.smart_speaker", caps=on_off),
            Device("5", "Бра", "Спальня", "devices.types.light", caps=on_off)]
    sh.devices = lambda force=False: devs
    assert sh.find("твою любимую песню") == []          # «тв» — не телевизор
    assert sh.find("брата") == []                       # «бра» — не «брата»
    assert sh.find("станцию маяк") == []                # это радио
    assert [d.name for d in sh.find("тв")] == ["Телевизор"]
    assert {d.name for d in sh.find("свет")} == {"Люстра", "Свет", "Бра"}   # весь свет, а не устройство «Свет»
    assert [d.name for d in sh.find("свет на кухне")] == ["Свет"]
    live.cfg.set("smarthome.room", "Гостиная")
    assert [d.name for d in sh.find("свет")] == ["Люстра"]                  # свет там, где стоит Стелла
    assert len(sh.find("весь свет")) == 3


# ------------------------------------------------------------ Groq и mpv --
def test_groq_gives_up_fast_without_network(monkeypatch):
    cfg = Config()
    cfg.set("groq.api_key", "gsk_test")
    g = GroqLLM(cfg)
    monkeypatch.setattr(g.session, "post", no_network)
    started = time.time()
    with pytest.raises(LLMError):
        g.complete([{"role": "user", "text": "привет"}])
    assert time.time() - started < 3


def test_groq_respects_time_budget(monkeypatch):
    cfg = Config()
    cfg.set("groq.api_key", "gsk_test")
    g = GroqLLM(cfg)
    busy = type("R", (), {"status_code": 429, "ok": False, "text": "rate limit", "headers": {"retry-after": "10"}})()
    monkeypatch.setattr(g.session, "post", lambda *a, **k: busy)
    started = time.time()
    with pytest.raises(LLMError):
        g.complete([{"role": "user", "text": "привет"}], budget=3)
    assert time.time() - started < 4


def test_audiobook_resume_uses_named_loadfile():
    sent = []
    fake = type("M", (), {
        "command": lambda self, *a, **k: sent.append(("pos", a)),
        "command_named": lambda self, name, **kw: sent.append(("named", name, kw)),
        "set": lambda self, *a: None, "alive": lambda self: True})()
    p = MusicPlayer(Config())
    p._ensure = lambda: fake
    p.queue = [Track("Глава 3", url="/books/3.mp3", source="audiobook", start=125.5)]
    assert p._play_index(0)
    assert sent == [("named", "loadfile", {"url": "/books/3.mp3", "flags": "replace", "options": {"start": "125.5"}})]
