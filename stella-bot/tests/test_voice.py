"""Голосовые: распознавание (faster-whisper) и озвучка (piper).

Тяжёлые библиотеки и модели здесь подменены — тесты идут без них. ffmpeg нужен настоящий (есть в Docker-образе);
без него такие тесты пропускаются. Настоящий прогон с моделями — в самом конце, только если модели уже скачаны
(STELLA_VOICE_MODELS, по умолчанию data/models).
"""

from __future__ import annotations

import array
import asyncio
import importlib.util
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import types
from typing import Any, ClassVar

import pytest

from bot import voice
from bot.media import MediaFile
from bot.tools import ToolContext, ToolError

from .conftest import make_settings

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")


def make_ogg(seconds: float, freq: int = 440) -> bytes:
    """Голосовое как из WhatsApp: OGG/Opus, моно, 48 кГц (тон, речи там нет — модель всё равно подменена)."""
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
         "-ac", "1", "-c:a", "libopus", "-b:a", "16k", "-f", "ogg", "pipe:1"],
        capture_output=True, check=True, timeout=60).stdout


def probe(data: bytes, tmp_path) -> dict[str, str]:
    path = tmp_path / "probe.ogg"
    path.write_bytes(data)
    out = subprocess.run(["ffprobe", "-v", "error", "-of", "default=nw=1",
                          "-show_entries", "stream=codec_name,sample_rate,channels:format=format_name", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in out.split())


# ---------- подмены тяжёлых библиотек ----------
class FakeSegment:
    def __init__(self, text: str):
        self.text = text


class FakeWhisperModel:
    inits: ClassVar[list[dict[str, Any]]] = []
    calls: ClassVar[list[dict[str, Any]]] = []
    cached = True  # модель уже скачана
    broken = False  # не грузится вообще (нет сети)
    probs: ClassVar[list[tuple[str, float]]] = [("ru", 0.97), ("en", 0.02)]
    segments: ClassVar[list[str]] = [" Привет, Стелла! ", "Как дела?", "Субтитры сделал DimaTorzok"]
    delay = 0.0
    active = 0
    peak = 0
    _guard = threading.Lock()

    def __init__(self, size: str, **kw: Any):
        type(self).inits.append({"size": size, **kw})
        if type(self).broken or (kw.get("local_files_only") and not type(self).cached):
            raise RuntimeError("нет модели")

    def detect_language(self, audio=None, vad_filter=False, **kw):
        probs = type(self).probs
        return probs[0][0], probs[0][1], probs

    def transcribe(self, audio, **kw):
        cls = type(self)
        with cls._guard:
            cls.active += 1
            cls.peak = max(cls.peak, cls.active)
        time.sleep(cls.delay)
        with cls._guard:
            cls.active -= 1
        cls.calls.append({"samples": len(audio), **kw})
        return iter(FakeSegment(t) for t in cls.segments), types.SimpleNamespace(language=kw.get("language"))


@pytest.fixture
def fake_whisper(monkeypatch):
    model = type("WhisperModel", (FakeWhisperModel,), {"inits": [], "calls": []})
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = model
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    if importlib.util.find_spec("numpy") is None:  # numpy приходит вместе с faster-whisper; здесь его может не быть
        np = types.ModuleType("numpy")
        np.float32 = "float32"
        np.frombuffer = lambda data, dtype=None: array.array("f", data)
        monkeypatch.setitem(sys.modules, "numpy", np)
    return model


class FakeChunk:
    def __init__(self, seconds: float, rate: int = 22050):
        self.sample_rate = rate
        n = int(seconds * rate)
        self.audio_int16_bytes = array.array("h", (int(8000 * math.sin(2 * math.pi * 220 * i / rate))
                                                   for i in range(n))).tobytes()


class FakePiperVoice:
    loads: ClassVar[list[str]] = []

    def __init__(self, model: str):
        self.model = model
        self.texts: list[str] = []

    @classmethod
    def load(cls, model_path, config_path=None, download_dir=None, **kw):
        cls.loads.append(os.path.basename(str(model_path)))
        return cls(str(model_path))

    def synthesize(self, text, syn_config=None):
        self.texts.append(text)
        for _sentence in [s for s in text.replace("!", ".").split(".") if s.strip()]:
            yield FakeChunk(0.3)


@pytest.fixture
def fake_piper(monkeypatch):
    cls = type("PiperVoice", (FakePiperVoice,), {"loads": []})
    module = types.ModuleType("piper")
    module.PiperVoice = cls
    module.SynthesisConfig = lambda **kw: kw
    monkeypatch.setitem(sys.modules, "piper", module)
    monkeypatch.setitem(sys.modules, "piper.config", None)  # своих настроек onnxruntime у подмены нет
    return cls


def voice_files(root, *names: str) -> str:
    os.makedirs(root, exist_ok=True)
    for name in names:
        for ext in (".onnx", ".onnx.json"):
            with open(os.path.join(root, name + ext), "w") as f:
                f.write("{}")
    return str(root)


# ---------- мелочи ----------
def test_language_hint_is_russian():
    assert voice.pick_language([("ru", 0.9), ("en", 0.05)]) == "ru"
    assert voice.pick_language([("en", 0.95), ("ru", 0.03)]) == "en"
    assert voice.pick_language([("uk", 0.5), ("ru", 0.4)]) == "ru"  # не уверен — значит, русский
    assert voice.pick_language([]) == "ru"


def test_text_is_cleaned_and_split_for_speech():
    assert voice.clean_for_speech("Привет 😀👍🏽 *мир* https://example.com/x ❤️ #тег") == "Привет мир тег"
    assert voice.clean_for_speech("👍🏽🎉") == ""
    long = "Сегодня отличная погода, и я хочу рассказать тебе, как прошёл мой день: утром я пила кофе, " \
           "а потом долго гуляла по парку и встретила там старого друга, который давно уехал."
    pieces = voice.split_for_speech("Привет! " + long, limit=60)
    assert pieces[0] == "Привет!"
    assert all(len(p) <= 60 for p in pieces)
    assert " ".join(pieces[1:]).split() == long.split()  # ничего не потерялось
    assert voice.split_for_speech("а" * 150, limit=60) == ["а" * 60, "а" * 60, "а" * 30]


def test_piper_voice_urls():
    assert voice.voice_urls("ru_RU-irina-medium") == (
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx",
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json",
    )
    assert voice.voice_urls("en_US-lessac-medium")[0].endswith("/en/en_US/lessac/medium/en_US-lessac-medium.onnx")
    for bad in ("irina", "../../etc/passwd", "ru_RU-irina-medium/../x"):
        with pytest.raises(voice.VoiceUnavailable):
            voice.voice_urls(bad)


async def test_heavy_work_runs_one_at_a_time():
    active, peak, order = [0], [0], []
    guard = threading.Lock()

    def job(name: str, seconds: float) -> str:
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        order.append(("start", name))
        time.sleep(seconds)
        order.append(("end", name))
        with guard:
            active[0] -= 1
        return name

    slow = asyncio.create_task(voice._run_heavy(job, "slow", 0.3, timeout=0.05))
    await asyncio.sleep(0.01)
    with pytest.raises(voice.VoiceError, match="занята"):  # очередь ждать не стали
        await voice._run_heavy(job, "x", 0, timeout=5, wait=0.01)
    rest = [voice._run_heavy(job, name, 0.02, timeout=5) for name in "ab"]
    with pytest.raises(voice.VoiceError, match="долго"):
        await slow
    assert sorted(await asyncio.gather(*rest)) == ["a", "b"]
    # медленную перестали ждать, но следующая началась только когда она правда закончилась
    assert order[:2] == [("start", "slow"), ("end", "slow")]
    assert peak[0] == 1


# ---------- речь → текст ----------
@needs_ffmpeg
async def test_decode_voice_note():
    pcm = await asyncio.to_thread(voice.decode_audio, make_ogg(2.0))
    seconds = len(pcm) / 4 / voice.SAMPLE_RATE
    assert 1.9 < seconds < 2.1
    for bad, msg in ((b"", "пустое"), (b"not an audio file at all", "прочитать"),
                     (b"0" * (voice.MAX_INPUT_BYTES + 1), "большое")):
        with pytest.raises(voice.VoiceError, match=msg):
            voice.decode_audio(bad)


@needs_ffmpeg
async def test_voice_longer_than_three_minutes_is_refused(fake_whisper, tmp_path):
    t = voice.Transcriber(models_dir=str(tmp_path), idle_unload=0)
    with pytest.raises(voice.VoiceError, match="3 минут"):
        await t.transcribe(make_ogg(voice.MAX_INPUT_SECONDS + 2))
    assert fake_whisper.inits == []  # модель даже не грузили


@needs_ffmpeg
async def test_transcribe_with_whisper(fake_whisper, tmp_path):
    models = str(tmp_path / "whisper")
    t = voice.Transcriber("small", models, idle_unload=0)
    assert t.available
    text = await t.transcribe(make_ogg(1.5))
    assert text == "Привет, Стелла! Как дела?"  # «титры» из тишины выброшены
    (init,) = fake_whisper.inits
    assert init["size"] == "small" and init["device"] == "cpu" and init["compute_type"] == "int8"
    assert init["download_root"] == models and init["local_files_only"] is True
    call = fake_whisper.calls[0]
    assert call["vad_filter"] is True and call["language"] == "ru" and call["hotwords"] == "Стелла"
    assert 1.4 * voice.SAMPLE_RATE < call["samples"] < 1.6 * voice.SAMPLE_RATE

    fake_whisper.probs = [("en", 0.98), ("ru", 0.01)]
    fake_whisper.segments = [" Hello, Stella. "]
    assert await t.transcribe(make_ogg(1.0)) == "Hello, Stella."
    assert fake_whisper.calls[1]["language"] == "en"
    assert len(fake_whisper.inits) == 1  # модель загружена один раз

    assert await t.transcribe(make_ogg(0.1)) == ""  # слишком коротко — нечего слушать
    assert len(fake_whisper.calls) == 2


@needs_ffmpeg
async def test_whisper_downloads_on_first_use_and_retries_later(fake_whisper, tmp_path, caplog):
    fake_whisper.cached = False
    t = voice.Transcriber("small", str(tmp_path), idle_unload=0)
    assert await t.transcribe(make_ogg(1.0))
    assert [i.get("local_files_only", False) for i in fake_whisper.inits] == [True, False]  # второй — с загрузкой

    fake_whisper.broken = True
    t2 = voice.Transcriber("small", str(tmp_path), idle_unload=0)
    with caplog.at_level(logging.WARNING, logger="stella.voice"), pytest.raises(voice.VoiceUnavailable):
        await t2.transcribe(make_ogg(1.0))
    assert "попробую снова" in caplog.text
    tries = len(fake_whisper.inits)
    assert not t2.available and "позже" in t2.problem
    with pytest.raises(voice.VoiceUnavailable):
        await t2.transcribe(make_ogg(1.0))
    assert len(fake_whisper.inits) == tries  # до паузы больше не пробует


@needs_ffmpeg
async def test_models_are_unloaded_when_idle(fake_whisper, tmp_path):
    t = voice.Transcriber("small", str(tmp_path), idle_unload=0.05)
    await t.transcribe(make_ogg(1.0))
    assert t._model is not None
    await asyncio.sleep(0.2)
    assert t._model is None
    await t.transcribe(make_ogg(1.0))  # снова загрузится сама
    assert len(fake_whisper.inits) == 2


@needs_ffmpeg
async def test_transcriptions_never_overlap(fake_whisper, tmp_path):
    fake_whisper.delay = 0.05
    t = voice.Transcriber("small", str(tmp_path), idle_unload=0)
    clip = make_ogg(1.0)
    results = await asyncio.gather(*(t.transcribe(clip) for _ in range(4)))
    assert len(results) == 4 and fake_whisper.peak == 1


async def test_without_libraries_bot_keeps_working(monkeypatch, tmp_path, caplog):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # как будто не установлено
    monkeypatch.setitem(sys.modules, "piper", None)
    t = voice.Transcriber(models_dir=str(tmp_path))
    s = voice.Speaker(models_dir=str(tmp_path))
    with caplog.at_level(logging.WARNING, logger="stella.voice"):
        assert not t.available and "faster-whisper" in t.problem
        assert not s.available and "piper-tts" in s.problem
        for _ in range(2):
            with pytest.raises(voice.VoiceUnavailable):
                await t.transcribe(b"OggS...")
            with pytest.raises(voice.VoiceUnavailable):
                await s.speak("Привет")
    lines = [r.getMessage() for r in caplog.records]
    assert sum("faster-whisper" in x for x in lines) == 1  # понятная строка в логе — один раз
    assert sum("piper-tts" in x for x in lines) == 1
    tools = voice.build_voice_tools(FakeDB(), make_settings(tmp_path), make_ctx(), speaker=s)
    assert tools == []  # модель про голосовые даже не узнает


@needs_ffmpeg
async def test_broken_library_is_disabled_once(monkeypatch, tmp_path):
    """Библиотека вроде стоит, но не импортируется (нет системной .so) — выключаемся, а не падаем."""
    monkeypatch.setattr(voice, "_has_module", lambda name: True)
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    t = voice.Transcriber(models_dir=str(tmp_path), idle_unload=0)
    with pytest.raises(voice.VoiceUnavailable):
        await t.transcribe(make_ogg(1.0))
    assert "не загружается" in t.problem


# ---------- текст → речь ----------
@needs_ffmpeg
async def test_speak_makes_whatsapp_voice_note(fake_piper, tmp_path):
    models = voice_files(tmp_path / "piper", "ru_RU-irina-medium", "en_US-lessac-medium")
    s = voice.Speaker(models_dir=models, idle_unload=0)
    assert s.available
    f = await s.speak("Привет! Это Стелла 😊. Как дела?")
    assert isinstance(f, MediaFile)
    assert (f.kind, f.mimetype, f.filename) == ("audio", "audio/ogg; codecs=opus", "voice.ogg")
    assert f.data.startswith(b"OggS")
    if shutil.which("ffprobe"):
        info = probe(f.data, tmp_path)
        assert info["codec_name"] == "opus" and info["channels"] == "1" and info["sample_rate"] == "48000"
        assert info["format_name"] == "ogg"
    assert fake_piper.loads == ["ru_RU-irina-medium.onnx"]

    await s.speak("Hello! My name is Stella.")  # латиницей — английским голосом
    assert fake_piper.loads == ["ru_RU-irina-medium.onnx", "en_US-lessac-medium.onnx"]
    await s.speak("Ещё раз привет")
    assert len(fake_piper.loads) == 2  # голоса загружены один раз


@needs_ffmpeg
async def test_voice_is_downloaded_once(fake_piper, monkeypatch, tmp_path):
    got: list[tuple[str, str, str | None]] = []

    def download(url, dest, sha256=None):
        got.append((url, os.path.basename(dest), sha256))
        with open(dest, "w") as f:
            json.dump({}, f)

    monkeypatch.setattr(voice, "download", download)
    s = voice.Speaker(models_dir=str(tmp_path / "piper"), english_voice=None, idle_unload=0)
    await s.speak("Привет")
    await s.speak("Hello there")  # английского голоса нет — читает основным
    base = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx"
    assert got == [
        (base + ".json", "ru_RU-irina-medium.onnx.json", voice.VOICE_SHA256["ru_RU-irina-medium.onnx.json"]),
        (base, "ru_RU-irina-medium.onnx", voice.VOICE_SHA256["ru_RU-irina-medium.onnx"]),
    ]
    assert fake_piper.loads == ["ru_RU-irina-medium.onnx"]


@needs_ffmpeg
async def test_english_voice_failure_falls_back_to_russian(fake_piper, monkeypatch, tmp_path):
    models = voice_files(tmp_path / "piper", "ru_RU-irina-medium")

    def download(url, dest, sha256=None):
        raise OSError("нет сети")

    monkeypatch.setattr(voice, "download", download)
    s = voice.Speaker(models_dir=models, idle_unload=0)
    f = await s.speak("Hello! My name is Stella.")
    assert f.data.startswith(b"OggS")
    assert fake_piper.loads == ["ru_RU-irina-medium.onnx"]
    assert s.available  # основной голос работает


async def test_speak_limits(fake_piper, tmp_path):
    s = voice.Speaker(models_dir=str(tmp_path))
    with pytest.raises(voice.VoiceError, match="600"):
        await s.speak("а" * (voice.MAX_SPEAK_CHARS + 1))
    with pytest.raises(voice.VoiceError, match="нечего"):
        await s.speak("🎉🎉🎉 https://example.com")
    assert fake_piper.loads == []


# ---------- инструмент модели ----------
class FakeDB:
    def __init__(self) -> None:
        self.kv: dict[str, float] = {}

    async def kv_get(self, key: str):
        return ("", self.kv[key]) if key in self.kv else None

    async def kv_add(self, key: str, delta: float) -> float:
        self.kv[key] = self.kv.get(key, 0) + delta
        return self.kv[key]


class FakeActions:
    def __init__(self) -> None:
        self.sent: list[tuple[Any, str]] = []

    async def send_file(self, file, caption: str = "") -> None:
        self.sent.append((file, caption))


def make_ctx() -> ToolContext:
    return ToolContext(chat_id=1, sender=None, people_refs={}, is_admin=False, actions=FakeActions())


class StubSpeaker(voice.Speaker):
    def __init__(self, error: Exception | None = None):
        super().__init__(idle_unload=0)
        self.error = error
        self.said: list[str] = []

    @property
    def problem(self):
        return None

    async def speak(self, text: str, *, wait: float = voice.QUEUE_WAIT) -> MediaFile:
        if self.error:
            raise self.error
        self.said.append(text)
        return MediaFile("audio", b"OggS-fake", voice.OGG_MIME, "voice.ogg")


async def test_say_voice_tool_queues_voice_note(tmp_path):
    ctx, speaker = make_ctx(), StubSpeaker()
    (tool,) = voice.build_voice_tools(FakeDB(), make_settings(tmp_path), ctx, speaker=speaker)
    assert tool.name == "say_voice" and "голос" in tool.description.lower()
    assert tool.input_schema["required"] == ["text"]
    reply = await tool.handler({"text": "С днём рождения!"})
    assert "после твоего сообщения" in reply
    await tool.handler({"text": "И ещё раз!"})
    with pytest.raises(ToolError, match="двух файлов"):  # то же правило, что у других файлов
        await tool.handler({"text": "третий"})
    assert ctx.media_queued == 2 and speaker.said == ["С днём рождения!", "И ещё раз!"]
    assert ctx.actions.sent == []  # уходит только после её сообщения
    for action in ctx.after:
        await action()
    sent = [(f.kind, f.mimetype, f.filename) for f, _ in ctx.actions.sent]
    assert sent == [("audio", voice.OGG_MIME, "voice.ogg")] * 2


async def test_say_voice_tool_explains_failures(tmp_path):
    for error, msg in ((voice.VoiceUnavailable("модель не загрузилась"), "ответь текстом"),
                       (voice.VoiceError("слишком длинно для голосового"), "слишком длинно")):
        ctx = make_ctx()
        (tool,) = voice.build_voice_tools(FakeDB(), make_settings(tmp_path), ctx, speaker=StubSpeaker(error))
        with pytest.raises(ToolError, match=msg):
            await tool.handler({"text": "привет"})
        assert ctx.after == [] and ctx.media_queued == 0


# ---------- настоящие модели (если уже скачаны) ----------
MODELS = os.environ.get("STELLA_VOICE_MODELS", "data/models")


def _real_models_ready() -> bool:
    if not shutil.which("ffmpeg"):
        return False
    if importlib.util.find_spec("faster_whisper") is None or importlib.util.find_spec("piper") is None:
        return False
    if not os.path.exists(os.path.join(MODELS, "piper", "ru_RU-irina-medium.onnx")):
        return False
    whisper = os.path.join(MODELS, "whisper")
    return any("model.bin" in files for _, _, files in os.walk(whisper)) if os.path.isdir(whisper) else False


@pytest.mark.skipif(not _real_models_ready(), reason="нет faster-whisper/piper или моделей в STELLA_VOICE_MODELS")
async def test_real_round_trip(tmp_path):
    speaker = voice.Speaker(models_dir=os.path.join(MODELS, "piper"), idle_unload=0)
    note = await speaker.speak("Привет! Меня зовут Стелла. Сегодня отличная погода.")
    assert note.data.startswith(b"OggS")
    info = probe(note.data, tmp_path)
    assert info["codec_name"] == "opus" and info["channels"] == "1" and info["sample_rate"] == "48000"
    text = await voice.Transcriber("small", os.path.join(MODELS, "whisper"), idle_unload=0).transcribe(note.data)
    low = text.lower()
    assert "привет" in low and "стелла" in low and "погода" in low, text
