"""Голосовые: Стелла слушает голосовые (речь → текст) и может ответить голосом (текст → речь).

Всё работает здесь, на сервере, без платных сервисов:
- распознавание — faster-whisper (модель Whisper, int8 на процессоре), русский и английский;
- озвучка — piper (русский голос irina, для английского текста — английский голос lessac).

Модуль необязательный. Тяжёлые библиотеки импортируются только при первом голосовом, модели
скачиваются в data/models при первом использовании. Нет библиотек, ffmpeg или модели — в лог пишется
понятная строка, голосовые просто не работают, а бот живёт дальше.

Чтобы не уронить маленький сервер: тяжёлая работа идёт в отдельном потоке и строго по одной за раз
(общий замок на распознавание и озвучку), голосовое — не длиннее 3 минут, текст для озвучки — до 600 знаков.
Если голосовых давно не было, модели выгружаются из памяти (снова загрузить с диска — пара секунд).
"""

from __future__ import annotations

import asyncio
import ctypes
import gc
import hashlib
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .media import MediaError, MediaFile

if TYPE_CHECKING:
    from .config import Settings
    from .db import DB
    from .llm.base import ToolSpec
    from .tools import ToolContext

log = logging.getLogger("stella.voice")

SAMPLE_RATE = 16_000  # Whisper слушает 16 кГц моно
MAX_INPUT_SECONDS = 180  # голосовые длиннее 3 минут не слушаем
MAX_INPUT_BYTES = 20 * 1024 * 1024
MIN_INPUT_SECONDS = 0.3  # короче — там нечего слушать
MAX_TRANSCRIPT_CHARS = 4000
MAX_SPEAK_CHARS = 600  # примерно 40 секунд речи
PIECE_CHARS = 100  # длинные фразы piper читает кусками: пик памяти растёт с длиной фразы (160 → ~410 МБ, 100 → ~340)
SENTENCE_PAUSE = 0.2  # пауза между фразами в озвучке, секунд

FFMPEG_TIMEOUT = 60
STT_TIMEOUT = 900  # в первый раз ещё и модель качается (~0.5 ГБ)
TTS_TIMEOUT = 600
QUEUE_WAIT = 600  # сколько ждать своей очереди, пока занято другим голосовым
RETRY_AFTER = 600  # модель не скачалась — пробуем снова через 10 минут
IDLE_UNLOAD = 1800  # полчаса без голосовых — выгружаем модели из памяти (0 — держать всегда)
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024

DEFAULT_WHISPER = "small"
DEFAULT_VOICE = "ru_RU-irina-medium"
DEFAULT_ENGLISH_VOICE = "en_US-lessac-medium"
LANGUAGE_HINT = "ru"  # если Whisper не уверен в языке — считаем, что говорят по-русски
LANGUAGE_SURE = 0.7

OGG_MIME = "audio/ogg; codecs=opus"

# Официальные голоса piper (rhasspy/piper-voices на Hugging Face), закреплены на теге v1.0.0
PIPER_VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
# Контрольные суммы известных голосов: скачанный файл сверяется, битый не используется
VOICE_SHA256 = {
    "ru_RU-irina-medium.onnx": "8ff38212d23da300bbe3705c645e6e5b9475f0bfde01558eb17813e22acaaaaa",
    "ru_RU-irina-medium.onnx.json": "c2ec28bb38e2b59e93b959b3e40348c1afebbd272f30fed5d41205d08e98a9d7",
    "ru_RU-denis-medium.onnx": "15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a",
    "ru_RU-denis-medium.onnx.json": "831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8",
    "en_US-lessac-medium.onnx": "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
    "en_US-lessac-medium.onnx.json": "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0",
}
_VOICE_NAME = re.compile(r"([a-z]{2,3})_([A-Z]{2})-([A-Za-z0-9_]+)-(x_low|low|medium|high)")


class VoiceError(MediaError):
    """Понятная ошибка с голосовым (можно показать модели или человеку)."""


class VoiceUnavailable(VoiceError):
    """Голосовые на сервере сейчас не работают: нет библиотеки, ffmpeg или модели."""


def _has_module(name: str) -> bool:
    if sys.modules.get(name) is not None:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _threads() -> int:
    return max(1, min(4, os.cpu_count() or 1))


def trim_memory() -> None:
    """Вернуть системе освободившуюся память: glibc держит её «про запас», и процесс зря пухнет."""
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):  # не Linux/glibc — ну и ладно
        pass


# ---------- одна тяжёлая задача за раз ----------
class _Gate:
    """Общий замок на распознавание и озвучку: на маленьком сервере две модели сразу — уже много."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None

    def lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._loop is not loop or self._lock is None:  # новый цикл событий (тесты, перезапуск)
            self._loop, self._lock = loop, asyncio.Lock()
        return self._lock


_GATE = _Gate()


async def _run_heavy(fn: Callable[..., Any], *args: Any, timeout: float, wait: float = QUEUE_WAIT) -> Any:
    """fn(*args) в отдельном потоке, строго по одной за раз.

    Поток нельзя прервать, поэтому замок отпускается, только когда работа в потоке правда закончилась —
    даже если мы перестали её ждать (вышло время). Так две модели никогда не считают одновременно.
    """
    lock = _GATE.lock()
    try:
        await asyncio.wait_for(lock.acquire(), wait)
    except TimeoutError as exc:
        raise VoiceError("сейчас занята другим голосовым, попробуй чуть позже") from exc
    task = asyncio.ensure_future(asyncio.to_thread(fn, *args))

    def done(t: asyncio.Future) -> None:
        lock.release()
        if not t.cancelled():
            t.exception()  # ошибку уже увидел тот, кто ждал; здесь — чтобы asyncio не ругался

    task.add_done_callback(done)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout)
    except TimeoutError as exc:
        raise VoiceError("слишком долго, не успела") from exc


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise VoiceUnavailable("на сервере нет ffmpeg — голосовые не работают")
    return path


class _Engine:
    """Общее у распознавания и озвучки: проверка, что всё установлено, и выгрузка моделей без дела."""

    module = ""  # что импортировать
    package = ""  # что ставить через pip
    purpose = ""  # для строки в логе

    def __init__(self, idle_unload: float) -> None:
        self.idle_unload = idle_unload
        self._broken: str | None = None  # навсегда: нет библиотеки
        self._retry_at: dict[str, float] = {}  # модель не скачалась — пауза до …
        self._warned = False
        self._timer: asyncio.TimerHandle | None = None

    def _loaded(self, name: str) -> bool:
        raise NotImplementedError

    def _unload(self) -> None:
        raise NotImplementedError

    def _problem(self, name: str) -> str | None:
        if not self._loaded(name):
            if self._broken:
                return self._broken
            if not _has_module(self.module):
                return self._disable(f"не установлен {self.package} (pip install {self.package})")
            if time.monotonic() < self._retry_at.get(name, 0.0):
                return "модель не загрузилась, попробую позже"
        if not shutil.which("ffmpeg"):
            return "на сервере нет ffmpeg"
        return None

    def _disable(self, reason: str) -> str:
        self._broken = reason
        if not self._warned:
            self._warned = True
            log.warning("голосовые: %s — %s не буду, бот работает дальше", reason, self.purpose)
        return reason

    def _failed(self, name: str, exc: Exception) -> VoiceUnavailable:
        self._retry_at[name] = time.monotonic() + RETRY_AFTER
        log.warning("голосовые: не удалось загрузить модель %s «%s» (%s: %s) — попробую снова через %d мин",
                    self.package, name, type(exc).__name__, exc, RETRY_AFTER // 60)
        return VoiceUnavailable("модель не загрузилась, попробую позже")

    def _touch(self) -> None:
        """После работы: через idle_unload секунд без дела модели выгрузятся."""
        if self.idle_unload <= 0:
            return
        if self._timer is not None:
            self._timer.cancel()
        self._timer = asyncio.get_running_loop().call_later(self.idle_unload, self._unload_if_idle)

    def _unload_if_idle(self) -> None:
        self._timer = None
        if _GATE.lock().locked():  # модель сейчас в работе (вся работа идёт под замком) — позже
            self._timer = asyncio.get_running_loop().call_later(60, self._unload_if_idle)
            return
        self._unload()
        gc.collect()
        trim_memory()
        log.info("голосовые: давно не было работы — %s выгружено из памяти", self.purpose)


# ---------- речь → текст ----------
def decode_audio(data: bytes) -> bytes:
    """Голосовое (OGG/Opus, m4a, mp3…) → PCM float32, 16 кГц, моно. Длиннее 3 минут — ошибка."""
    if not data:
        raise VoiceError("пустое голосовое")
    if len(data) > MAX_INPUT_BYTES:
        raise VoiceError("голосовое слишком большое")
    ffmpeg = _ffmpeg()
    # во временный файл, а не в stdin: некоторым форматам (m4a) нужно читать файл не по порядку
    with tempfile.TemporaryDirectory(prefix="stella-voice-") as tmp:
        src = os.path.join(tmp, "in")
        with open(src, "wb") as f:
            f.write(data)
        try:
            proc = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                 # только аудиоформаты и только этот файл: «голосовое» может оказаться манифестом
                 # DASH/HLS со ссылками на внутренние адреса — такой ffmpeg не откроет
                 "-format_whitelist", "ogg,mp3,mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,wav,aac,flac,amr,aiff",
                 "-protocol_whitelist", "file", "-i", src,
                 "-t", str(MAX_INPUT_SECONDS + 1), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
                capture_output=True, timeout=FFMPEG_TIMEOUT, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VoiceError("не получилось прочитать голосовое") from exc
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode(errors="replace").strip().splitlines()
        log.info("ffmpeg не прочитал голосовое: %s", err[-1][:200] if err else proc.returncode)
        raise VoiceError("не получилось прочитать голосовое")
    if len(proc.stdout) > MAX_INPUT_SECONDS * SAMPLE_RATE * 4:
        raise VoiceError("голосовое длиннее 3 минут — такое не слушаю, напиши текстом")
    return proc.stdout


def pick_language(probs: list[tuple[str, float]]) -> str:
    """Язык голосового: тот, в котором Whisper уверен (от 70 %), иначе — русский."""
    if not probs:
        return LANGUAGE_HINT
    lang, p = max(probs, key=lambda x: x[1])
    return lang if p >= LANGUAGE_SURE else LANGUAGE_HINT


# Что Whisper «слышит» в тишине и шуме (титры из обучающих видео) — такие куски выбрасываем
_HALLUCINATION = re.compile(r"субтитр|dimatorzok|amara\.org|продолжение следует\W*$|thanks? (you )?for watching",
                            re.IGNORECASE)


class Transcriber(_Engine):
    """Речь → текст (faster-whisper). Модель грузится и, если надо, скачивается при первом голосовом.

    model_size: tiny / base / small / medium… или путь к своей модели CTranslate2. small — хорошее качество
    для русского (~0.5 ГБ памяти), base — вдвое легче и быстрее, но ошибается чаще.
    """

    module, package, purpose = "faster_whisper", "faster-whisper", "расшифровывать голосовые"

    def __init__(self, model_size: str = DEFAULT_WHISPER, models_dir: str = "data/models/whisper", *,
                 hotwords: str | None = "Стелла", cpu_threads: int = 0, beam_size: int = 1,
                 idle_unload: float = IDLE_UNLOAD):
        super().__init__(idle_unload)
        self.model_size = model_size
        self.models_dir = models_dir
        self.hotwords = hotwords or None  # подсказка: её имя пишется «Стелла», а не «Стела» / «С тела»
        self.cpu_threads = cpu_threads or _threads()
        self.beam_size = max(1, beam_size)  # 1 — быстрее; 5 — чуть точнее и медленнее
        self._model: Any = None

    @property
    def problem(self) -> str | None:
        """Почему сейчас не получится расшифровать голосовое (None — можно пробовать)."""
        return self._problem(self.model_size)

    @property
    def available(self) -> bool:
        return self.problem is None

    def _loaded(self, name: str) -> bool:
        return self._model is not None

    def _unload(self) -> None:
        self._model = None

    async def transcribe(self, data: bytes, *, wait: float = QUEUE_WAIT) -> str:
        """Текст голосового. Пустая строка — речи не слышно. VoiceError — что-то не так (текст понятный)."""
        problem = self.problem
        if problem:
            raise VoiceUnavailable(problem)
        pcm = await asyncio.to_thread(decode_audio, data)
        if len(pcm) < MIN_INPUT_SECONDS * SAMPLE_RATE * 4:
            return ""
        try:
            return await _run_heavy(self._transcribe_sync, pcm, timeout=STT_TIMEOUT, wait=wait)
        finally:
            self._touch()

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except (ImportError, OSError) as exc:
            raise VoiceUnavailable(self._disable(f"faster-whisper не загружается: {exc}")) from exc
        os.makedirs(self.models_dir, exist_ok=True)
        opts = {"device": "cpu", "compute_type": "int8", "cpu_threads": self.cpu_threads,
                "download_root": self.models_dir}
        started = time.monotonic()
        try:
            try:  # сначала — уже скачанная модель, без похода в сеть
                model = WhisperModel(self.model_size, local_files_only=True, **opts)
            except Exception:
                log.info("голосовые: качаю модель Whisper «%s» в %s (один раз)…", self.model_size, self.models_dir)
                model = WhisperModel(self.model_size, **opts)
        except Exception as exc:
            raise self._failed(self.model_size, exc) from exc
        finally:
            trim_memory()  # веса приходят во float16 и пережимаются в int8 — черновики возвращаем системе
        log.info("голосовые: Whisper «%s» загружен за %.1f с", self.model_size, time.monotonic() - started)
        self._model = model
        return model

    def _transcribe_sync(self, pcm: bytes) -> str:
        model = self._load()
        import numpy as np  # приходит вместе с faster-whisper

        audio = np.frombuffer(pcm, dtype=np.float32)
        try:
            try:
                _, _, probs = model.detect_language(audio=audio, vad_filter=True)
            except Exception:
                log.debug("язык не определился", exc_info=True)
                probs = []
            language = pick_language(list(probs or []))
            segments, _info = model.transcribe(audio, language=language, task="transcribe",
                                               beam_size=self.beam_size, vad_filter=True,
                                               condition_on_previous_text=False, hotwords=self.hotwords)
            parts = [s.text.strip() for s in segments]  # распознавание идёт здесь, по мере чтения
        finally:
            trim_memory()
        text = " ".join(p for p in parts if p and not _HALLUCINATION.search(p))
        return re.sub(r"\s+", " ", text).strip()[:MAX_TRANSCRIPT_CHARS]


# ---------- текст → речь ----------
def voice_urls(voice: str) -> tuple[str, str]:
    """Ссылки на модель голоса piper и её настройки: (…/.onnx, …/.onnx.json)."""
    m = _VOICE_NAME.fullmatch(voice)
    if not m:
        raise VoiceUnavailable(f"непонятное имя голоса piper: {voice!r}")
    lang, region, name, quality = m.groups()
    url = f"{PIPER_VOICES_URL}/{lang}/{lang}_{region}/{name}/{quality}/{voice}.onnx"
    return url, url + ".json"


def download(url: str, dest: str, sha256: str | None = None) -> None:
    """Скачать файл целиком во временный и только потом переименовать — недокачанный не останется."""
    import httpx

    part = dest + ".part"
    digest = hashlib.sha256()
    size = 0
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(60, connect=20)) as r:
            r.raise_for_status()
            with open(part, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise VoiceError("файл голоса слишком большой")
                    digest.update(chunk)
                    f.write(chunk)
        if sha256 and digest.hexdigest() != sha256:
            raise VoiceError(f"файл {os.path.basename(dest)} скачался битым (не та контрольная сумма)")
        os.replace(part, dest)
    finally:
        if os.path.exists(part):
            os.remove(part)


_EMOJI_GLUE = {"‍", "︎", "️", "⃣"}


def clean_for_speech(text: str) -> str:
    """Убрать то, что вслух не читается: эмодзи, ссылки, разметку."""
    text = re.sub(r"https?://\S+|www\.\S+", " ", text or "")
    text = "".join(ch for ch in text  # So — эмодзи и значки, Sk — в том числе цвет кожи у эмодзи
                   if ch not in _EMOJI_GLUE and unicodedata.category(ch) not in ("So", "Sk", "Cs", "Co", "Cn"))
    text = re.sub(r"[*_~`#|<>\[\]{}^\\]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r" ([.,!?…:;])", r"\1", text).strip()


def split_for_speech(text: str, limit: int = PIECE_CHARS) -> list[str]:
    """По фразам; слишком длинные — ещё и по запятым или пробелам, не длиннее limit."""
    pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?…])\s+", text):
        sentence = sentence.strip()
        while len(sentence) > limit:
            cut = max(sentence.rfind(sep, 0, limit) for sep in (",", ";", ":", " —", " -"))
            if cut <= 0:
                cut = sentence.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit - 1
            pieces.append(sentence[:cut + 1].strip())
            sentence = sentence[cut + 1:].strip(" —-")
        if sentence:
            pieces.append(sentence)
    return pieces


def _is_english(text: str) -> bool:
    latin = sum(1 for ch in text.lower() if "a" <= ch <= "z")
    cyrillic = sum(1 for ch in text.lower() if "а" <= ch <= "я" or ch == "ё")
    return latin > cyrillic


def _open_piper(model: str, config: str, download_dir: str) -> Any:
    """Голос piper со своими настройками onnxruntime: без «запаса» памяти и не больше 4 потоков.

    С запасом (как в PiperVoice.load) процесс после длинной фразы так и остаётся ~500 МБ, без него — ~200 МБ;
    озвучка от этого медленнее, но всё равно быстрее реального времени в несколько раз.
    """
    from piper import PiperVoice

    try:
        import onnxruntime
        from piper.config import PiperConfig

        opts = onnxruntime.SessionOptions()
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        opts.intra_op_num_threads = _threads()
        with open(config, encoding="utf-8") as f:
            cfg = PiperConfig.from_dict(json.load(f))
        session = onnxruntime.InferenceSession(model, sess_options=opts, providers=["CPUExecutionProvider"])
        return PiperVoice(session=session, config=cfg, download_dir=Path(download_dir))
    except (ImportError, AttributeError, TypeError):  # другая версия piper — грузим как есть
        log.debug("piper: свои настройки не подошли, обычная загрузка", exc_info=True)
        return PiperVoice.load(model, config_path=config, download_dir=download_dir)


class Speaker(_Engine):
    """Текст → голосовое (piper). Голос скачивается при первой озвучке (~63 МБ).

    voice — голос из rhasspy/piper-voices («ru_RU-irina-medium», «ru_RU-denis-medium»…) или путь к своему .onnx.
    english_voice — чем читать текст латиницей (None — тем же голосом, с акцентом).
    """

    module, package, purpose = "piper", "piper-tts", "отвечать голосом"

    def __init__(self, voice: str = DEFAULT_VOICE, models_dir: str = "data/models/piper", *,
                 english_voice: str | None = DEFAULT_ENGLISH_VOICE, length_scale: float | None = None,
                 idle_unload: float = IDLE_UNLOAD):
        super().__init__(idle_unload)
        self.voice = voice
        self.english_voice = english_voice
        self.models_dir = models_dir
        self.length_scale = length_scale  # > 1 — медленнее, < 1 — быстрее
        self._voices: dict[str, Any] = {}

    @property
    def problem(self) -> str | None:
        """Почему сейчас не получится озвучить (None — можно пробовать)."""
        return self._problem(self.voice)

    @property
    def available(self) -> bool:
        return self.problem is None

    def _loaded(self, name: str) -> bool:
        return name in self._voices

    def _unload(self) -> None:
        self._voices.clear()

    async def speak(self, text: str, *, wait: float = QUEUE_WAIT) -> MediaFile:
        """Голосовое для WhatsApp: OGG/Opus, моно, 48 кГц."""
        text = clean_for_speech(text)
        if not text:
            raise VoiceError("нечего озвучивать: нужен обычный текст")
        if len(text) > MAX_SPEAK_CHARS:
            raise VoiceError(f"слишком длинно для голосового (до {MAX_SPEAK_CHARS} знаков) — скажи короче")
        problem = self.problem
        if problem:
            raise VoiceUnavailable(problem)
        try:
            data = await _run_heavy(self._speak_sync, text, timeout=TTS_TIMEOUT, wait=wait)
        finally:
            self._touch()
        return MediaFile("audio", data, OGG_MIME, "voice.ogg")

    def _files(self, voice: str) -> tuple[str, str]:
        """Пути к модели голоса; скачивает, если их ещё нет."""
        if voice.endswith(".onnx") and os.path.exists(voice):
            return voice, voice + ".json"
        model_url, config_url = voice_urls(voice)
        os.makedirs(self.models_dir, exist_ok=True)
        model = os.path.join(self.models_dir, f"{voice}.onnx")
        config = model + ".json"
        for url, path in ((config_url, config), (model_url, model)):
            if not os.path.exists(path):
                log.info("голосовые: качаю голос piper %s (один раз)…", os.path.basename(path))
                download(url, path, VOICE_SHA256.get(os.path.basename(path)))
        return model, config

    def _load(self, voice: str) -> Any:
        if voice in self._voices:
            return self._voices[voice]
        try:
            import piper  # noqa: F401  (тяжёлый импорт: onnxruntime, espeak-ng)
        except (ImportError, OSError) as exc:
            raise VoiceUnavailable(self._disable(f"piper-tts не загружается: {exc}")) from exc
        started = time.monotonic()
        try:
            model, config = self._files(voice)
            loaded = _open_piper(model, config, self.models_dir)
        except Exception as exc:
            raise self._failed(voice, exc) from exc
        log.info("голосовые: голос piper %s загружен за %.1f с", voice, time.monotonic() - started)
        self._voices[voice] = loaded
        return loaded

    def _pick_voice(self, text: str) -> Any:
        english = self.english_voice
        if english and _is_english(text) and time.monotonic() >= self._retry_at.get(english, 0.0):
            try:
                return self._load(english)
            except VoiceUnavailable:
                if self._broken:
                    raise
                # английский голос не скачался — прочитаем основным
        return self._load(self.voice)

    def _speak_sync(self, text: str) -> bytes:
        voice = self._pick_voice(text)
        config = None
        if self.length_scale:
            from piper import SynthesisConfig

            config = SynthesisConfig(length_scale=self.length_scale)
        rate, pcm = 0, bytearray()
        try:
            for piece in split_for_speech(text):
                for chunk in voice.synthesize(piece, syn_config=config):
                    if rate and pcm:
                        pcm += b"\x00\x00" * int(rate * SENTENCE_PAUSE)
                    rate = chunk.sample_rate
                    pcm += chunk.audio_int16_bytes
        finally:
            trim_memory()
        if not pcm:
            raise VoiceError("нечего озвучивать: нужен обычный текст")
        return encode_voice_note(bytes(pcm), rate)


def encode_voice_note(pcm: bytes, sample_rate: int) -> bytes:
    """PCM 16 бит моно → голосовое WhatsApp: OGG, Opus 32 кбит/с, моно, 48 кГц."""
    try:
        proc = subprocess.run(
            [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin",
             "-f", "s16le", "-ar", str(sample_rate), "-ac", "1", "-i", "pipe:0",
             "-c:a", "libopus", "-b:a", "32k", "-ac", "1", "-ar", "48000", "-application", "voip",
             "-map_metadata", "-1", "-f", "ogg", "pipe:1"],
            input=pcm, capture_output=True, timeout=FFMPEG_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VoiceError("не получилось собрать голосовое") from exc
    if proc.returncode != 0 or not proc.stdout.startswith(b"OggS"):
        err = (proc.stderr or b"").decode(errors="replace").strip().splitlines()
        log.warning("ffmpeg не собрал голосовое: %s", err[-1][:200] if err else proc.returncode)
        raise VoiceError("не получилось собрать голосовое")
    return proc.stdout


# ---------- инструмент модели ----------
SPEAK_TOOL_WAIT = 90  # инструмент не ждёт очередь дольше полутора минут


def build_voice_tools(db: DB, settings: Settings, ctx: ToolContext, *, speaker: Speaker) -> list[ToolSpec]:
    """Инструмент say_voice. Если озвучка на сервере не работает — пустой список (модель о ней не узнает)."""
    from .llm.base import ToolSpec
    from .media_tools import _Budget
    from .tools import ToolError

    if not speaker.available:
        return []
    budget = _Budget(db, settings, ctx)  # те же правила, что у файлов: не больше двух за ответ и дневной лимит

    async def say_voice(args: dict[str, Any]) -> str:
        await budget.take()
        try:
            file = await speaker.speak(str(args.get("text") or ""), wait=SPEAK_TOOL_WAIT)
        except VoiceUnavailable as exc:
            raise ToolError(f"голосом сейчас не получится ({exc}) — ответь текстом") from exc
        except VoiceError as exc:
            raise ToolError(str(exc)) from exc
        await budget.queue(file, str(args.get("text") or "")[:600])  # в истории — что она сказала
        return "голосовое записано — уйдёт в чат сразу после твоего сообщения; текстом его не повторяй"

    return [
        ToolSpec(
            "say_voice",
            "Записать и отправить ГОЛОСОВОЕ сообщение своим голосом. Только когда тебя прямо просят сказать "
            "что-то голосом или прислать голосовое («скажи голосом», «запиши голосовое», «поздравь вслух»). "
            f"text — что сказать, до {MAX_SPEAK_CHARS} знаков, так, как говорят вслух: без эмодзи, ссылок и "
            "списков, числа можно словами. Текстом в чате потом ответь коротко и не повторяй сказанное.",
            {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            say_voice,
        ),
    ]
