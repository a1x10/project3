"""Распознавание речи (Vosk, офлайн) + слово-активатор «Стелла» + детектор шёпота.

Режимы:
  wake    — ждём «Стелла …». Если команда сказана в той же фразе («Стелла, какая погода»),
            она сразу уходит в обработку; если было только «Стелла» — переходим в command.
  command — слушаем команду без активатора (после «Стелла» или когда Стелла задала вопрос).
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from typing import Callable

import numpy as np
import requests

from . import dsp
from .io import RATE

log = logging.getLogger("stella.stt")


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


class WakeMatcher:
    """Нечёткое сравнение со словом-активатором: «стелла», «стела», «стеллу», «stella»…"""

    def __init__(self, words):
        self.words = [self._n(w) for w in words if w]

    @staticmethod
    def _n(w: str) -> str:
        w = w.lower().replace("ё", "е").replace("э", "е")
        return re.sub(r"(.)\1+", r"\1", w)  # «стелла» -> «стела»

    def is_wake(self, word: str) -> bool:
        w = self._n(word)
        if len(w) < 3:
            return False
        for ref in self.words:
            if w == ref:
                return True
            # падежи и мелкие ошибки распознавания, но первые буквы должны совпадать
            if len(ref) >= 4 and w[:3] == ref[:3] and _lev(w, ref) <= 1:
                return True
        return False

    def find(self, text: str):
        """-> (есть ли активатор, команда без активатора)."""
        words = text.split()
        for i, w in enumerate(words):
            if self.is_wake(w):
                rest = words[:i] + words[i + 1:]
                # «Стелла, стоп» / «включи музыку, Стелла»
                return True, " ".join(rest).strip()
            # Vosk иногда слышит «Стелла» как два слова: «с тела», «с телом»
            if w == "с" and i + 1 < len(words) and "стела" in self.words and \
                    re.fullmatch(r"тел+[аоуеы]?м?", words[i + 1]):
                rest = words[:i] + words[i + 2:]
                return True, " ".join(rest).strip()
        return False, text


class Listener(threading.Thread):
    def __init__(self, cfg, hub, on_wake: Callable[[], None], on_command: Callable[[str, bool], None],
                 on_timeout: Callable[[], None] | None = None, on_partial: Callable[[str], None] | None = None):
        super().__init__(daemon=True, name="stt")
        self.cfg = cfg
        self.hub = hub
        self.on_wake = on_wake
        self.on_command = on_command
        self.on_timeout = on_timeout or (lambda: None)
        self.on_partial = on_partial or (lambda text: None)
        self.wake = WakeMatcher(cfg.get("assistant.wake_words") or ["стелла"])
        self.mode = "wake"
        self.deadline = 0.0
        self.muted_until = 0.0          # не слушаем собственную речь
        self.allow_barge_in = False     # можно ли перебивать Стеллу словом «Стелла»
        self.whisper_detect = bool(cfg.get("stt.whisper_detect", True))
        self.ok = False
        self._stop = threading.Event()
        self._woke_at = 0.0
        self._buf: list[np.ndarray] = []
        self._rec = None
        self._last_partial = ""
        self._reset_pending = False

    # ------------------------------------------------------- управление --
    def listen_now(self, timeout: float | None = None):
        """Начать слушать команду без слова-активатора (диалоговый режим)."""
        self.mode = "command"
        self.deadline = time.time() + (timeout or float(self.cfg.get("assistant.listen_timeout", 8)))

    def mute(self, seconds: float):
        self.muted_until = max(self.muted_until, time.time() + seconds)

    def unmute(self):
        self.muted_until = 0.0
        self._reset_pending = True  # сбросим распознаватель в его собственном потоке (Vosk не потокобезопасен)

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------- поток --
    def run(self):
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError:
            log.error("Не установлен vosk: pip install vosk — голосовое управление выключено")
            return
        path = self.cfg.path_of("stt.vosk_model", "models/vosk-model-small-ru-0.22")
        if not path.exists():
            log.error("Модель Vosk не найдена: %s (запустите deploy/install.sh)", path)
            return
        SetLogLevel(-1)
        model = Model(str(path))
        rec = KaldiRecognizer(model, RATE)
        self._rec = rec
        self.ok = True
        q = self.hub.subscribe(maxsize=300)
        log.info("Распознавание речи запущено (Vosk: %s)", path.name)
        while not self._stop.is_set():
            try:
                data = q.get(timeout=0.3)
            except queue.Empty:
                self._check_timeout()
                continue
            now = time.time()
            muted = now < self.muted_until
            if self._reset_pending:  # хвост собственной речи Стеллы распознавать не нужно
                self._reset_pending = False
                rec.Reset()
                self._buf = []
                self._last_partial = ""
            self._buf.append(data)
            if len(self._buf) > 150:  # не больше 15 с
                self._buf = self._buf[-150:]
            if rec.AcceptWaveform(data.tobytes()):
                text = json.loads(rec.Result()).get("text", "").strip()
                audio = np.concatenate(self._buf) if self._buf else np.zeros(0, np.int16)
                self._buf = []
                self._last_partial = ""
                if text:
                    self._final(text, audio, muted)
            else:
                partial = json.loads(rec.PartialResult()).get("partial", "")
                if partial and partial != self._last_partial:
                    self._last_partial = partial
                    self._partial(partial, muted)
            self._check_timeout()

    def _check_timeout(self):
        if self.mode == "command" and time.time() > self.deadline:
            self.mode = "wake"
            self._woke_at = 0.0
            self.on_timeout()

    def _partial(self, text: str, muted: bool):
        if muted and not self.allow_barge_in:
            return
        if self.mode == "wake":
            found, _ = self.wake.find(text)
            if found and time.time() - self._woke_at > 3:
                self._woke_at = time.time()
                self.on_wake()
        elif not muted:
            self.on_partial(text)
            self.deadline = max(self.deadline, time.time() + 2.5)  # человек ещё говорит

    def _final(self, text: str, audio: np.ndarray, muted: bool):
        whisper = False
        if self.whisper_detect and len(audio) > RATE // 2:
            try:
                whisper = dsp.is_whisper(audio, RATE)
            except Exception:
                log.debug("ошибка детектора шёпота", exc_info=True)
        if self.mode == "wake":
            found, command = self.wake.find(text)
            if muted and not (found and self.allow_barge_in):
                return
            recently_woke = time.time() - self._woke_at < 4
            if not found and not recently_woke:
                return
            if not found:
                command = text  # активатор был в частичном результате, но потерялся в итоговом
            if self._woke_at == 0 or not recently_woke:
                self.on_wake()
            self._woke_at = 0.0
            if command:
                self._deliver(command, whisper, audio)
            else:
                self.listen_now()
        elif self.mode == "command":
            if muted:
                return
            _, command = self.wake.find(text)
            if command:
                self.mode = "wake"
                self._deliver(command, whisper, audio)

    def _deliver(self, text: str, whisper: bool, audio: np.ndarray):
        if len(audio) > RATE // 3:  # уточняем команду облачным распознаванием (Groq Whisper / SpeechKit)
            better = cloud_recognize(self.cfg, audio)
            if better:
                found, cmd = self.wake.find(_plain(better))
                text = cmd or text
        log.info("Услышала: %r%s", text, " (шёпотом)" if whisper else "")
        self.on_command(text, whisper)


def _plain(text: str) -> str:
    """«Стелла, какая погода?» -> «стелла какая погода» (как выдаёт Vosk)."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", text.lower().replace("ё", "е"))).strip()


_GROQ = None


def cloud_recognize(cfg, audio: np.ndarray, sr: int = RATE) -> str | None:
    """Облачное распознавание фразы. stt.cloud: auto (Groq Whisper, если есть ключ; SpeechKit, если
    stt.yandex_stt: true) | groq | yandex | off. Слово-активатор всегда ищется офлайн."""
    global _GROQ
    mode = str(cfg.get("stt.cloud", "auto")).lower()
    if mode in ("off", "none", "false", "vosk"):
        return None
    engines = []
    if mode in ("auto", "groq") and cfg.get("groq.api_key"):
        engines.append("groq")
    if mode == "yandex" or (mode == "auto" and cfg.get("stt.yandex_stt")):
        engines.append("yandex")
    for eng in engines:
        if eng == "groq":
            if _GROQ is None:
                from ..llm.groq import GroqLLM
                _GROQ = GroqLLM(cfg)
            text = _GROQ.transcribe(dsp.wav_bytes(audio, sr))
        else:
            text = yandex_recognize(cfg, audio, sr)
        if text:
            return text
    return None


def yandex_recognize(cfg, audio: np.ndarray, sr: int = RATE) -> str | None:
    """Облачное распознавание SpeechKit (короткие фразы до 30 с) — точнее, чем Vosk small."""
    key, iam, folder = cfg.get("yandex.api_key"), cfg.get("yandex.iam_token"), cfg.get("yandex.folder_id")
    if not (key or iam):
        return None
    headers = {"Authorization": f"Api-Key {key}" if key else f"Bearer {iam}"}
    params = {"lang": "ru-RU", "format": "lpcm", "sampleRateHertz": sr, "topic": "general"}
    if folder and not key:  # каталог нужен только с IAM-токеном пользователя
        params["folderId"] = folder
    try:
        r = requests.post("https://stt.api.cloud.yandex.net/speech/v1/stt:recognize", params=params,
                          headers=headers, data=dsp.to_int16(audio).tobytes(), timeout=10)
        if r.ok:
            return (r.json().get("result") or "").strip() or None
        log.warning("SpeechKit STT: %s %s", r.status_code, r.text[:200])
    except requests.RequestException as e:
        log.warning("SpeechKit STT недоступен: %s", e)
    return None


# ------------------------------------------------- распознавание целой записи --
_MODEL = None
_MODEL_LOCK = threading.Lock()


def get_model(cfg):
    """Общая модель Vosk (для веб-панели и Telegram — чтобы не грузить её дважды)."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from vosk import Model, SetLogLevel
            SetLogLevel(-1)
            path = cfg.path_of("stt.vosk_model", "models/vosk-model-small-ru-0.22")
            if not path.exists():
                raise FileNotFoundError(f"Модель Vosk не найдена: {path}")
            _MODEL = Model(str(path))
        return _MODEL


def recognize_pcm(cfg, pcm: np.ndarray, sr: int = RATE) -> str:
    """Текст из записи (PCM int16): облако (Groq Whisper / SpeechKit), если настроено, иначе Vosk."""
    if sr != RATE:
        pcm = dsp.resample(pcm, sr, RATE)
    text = cloud_recognize(cfg, pcm)
    if text:
        return _plain(text)
    try:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(get_model(cfg), RATE)
    except Exception as e:
        log.warning("Vosk недоступен: %s", e)
        return ""
    data = dsp.to_int16(pcm).tobytes()
    for i in range(0, len(data), 8000):
        rec.AcceptWaveform(data[i:i + 8000])
    return json.loads(rec.FinalResult()).get("text", "").strip()


def decode_audio_file(data: bytes) -> np.ndarray | None:
    """Любой аудиофайл (ogg/opus из Telegram, webm из браузера) -> PCM 16 кГц через ffmpeg."""
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        log.warning("Нужен ffmpeg для голосовых сообщений")
        return None
    try:
        out = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(RATE),
                              "-f", "s16le", "pipe:1"], input=data, capture_output=True, timeout=60)
        return np.frombuffer(out.stdout, dtype=np.int16) if out.stdout else None
    except Exception as e:
        log.warning("ffmpeg: %s", e)
        return None


def encode_ogg_opus(samples: np.ndarray, sr: int) -> bytes | None:
    """Синтезированная речь -> OGG/Opus для голосового ответа в Telegram."""
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        return None
    try:
        out = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
                              "-c:a", "libopus", "-b:a", "32k", "-ar", "48000", "-f", "ogg", "pipe:1"],
                             input=dsp.to_int16(samples).tobytes(), capture_output=True, timeout=60)
        return out.stdout or None
    except Exception as e:
        log.warning("ffmpeg: %s", e)
        return None
