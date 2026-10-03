"""Синтез речи: Яндекс SpeechKit (облако) → Piper (офлайн) → RHVoice → eSpeak NG.

Голос подстраивается под эмоцию: радость — чуть быстрее и «дружелюбнее», злость —
резче («evil»/«strict» роль у голосов SpeechKit), грусть и скука — медленнее.
Режим шёпота: у голоса marina есть роль «whisper»; для остальных движков
речь превращается в шёпот DSP-эффектом (см. dsp.whisperize).
"""
from __future__ import annotations

import base64
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import OrderedDict

import numpy as np
import requests

from ..nlp.text import strip_markdown
from . import dsp

log = logging.getLogger("stella.tts")

# Роли голосов SpeechKit (API v3), по документации на 2026 год
VOICE_ROLES = {
    "marina": ["neutral", "whisper", "friendly"],
    "jane": ["neutral", "good", "evil"],
    "omazh": ["neutral", "evil"],
    "ermil": ["neutral", "good"],
    "zahar": ["neutral", "good"],
    "dasha": ["neutral", "good", "friendly"],
    "julia": ["neutral", "strict"],
    "lera": ["neutral", "friendly"],
    "masha": ["good", "strict", "friendly"],
    "alexander": ["neutral", "good"],
    "kirill": ["neutral", "strict", "good"],
    "anton": ["neutral", "good"],
    "saule_ru": ["neutral", "strict", "whisper"],
    "yulduz_ru": ["neutral", "strict", "friendly", "whisper"],
    "zamira_ru": ["neutral", "strict", "friendly"],
    "zhanar_ru": ["neutral", "strict", "friendly"],
    "filipp": [],
    "madi_ru": [],
    "john": [],
    "lea": [],
}
EMOTION_ROLES = {
    "joy": ["friendly", "good"], "love": ["friendly", "good"], "interest": ["friendly", "good"],
    "anger": ["evil", "strict"], "contempt": ["strict", "evil"], "confidence": ["strict"],
}
EMOTION_SPEED = {
    "joy": 1.06, "love": 0.95, "sadness": 0.88, "anger": 1.06, "fear": 1.15, "surprise": 1.1,
    "boredom": 0.86, "contempt": 0.95, "confidence": 0.97, "interest": 1.03,
}
LANG_VOICES = {"en": ("en-US", "john"), "de": ("de-DE", "lea"), "kk": ("kk-KK", "madi"),
               "uz": ("uz-UZ", "nigora"), "he": ("he-IL", "naomi")}

_REPLACE = [
    (r"(\d)\s*°\s*[CС]\b", r"\1 градусов"), (r"°", " градусов"), (r"(\d)\s*%", r"\1 процентов"),
    (r"\bкм/ч\b", "километров в час"), (r"\bм/с\b", "метров в секунду"), (r"№", "номер "),
    (r"&", " и "), (r"\bт\.е\.", "то есть"), (r"\bт\.д\.", "так далее"), (r"\bт\.п\.", "тому подобное"),
    (r"\bмм рт\. ?ст\.", "миллиметров ртутного столба"), (r"\s+—\s+", ", "), (r"[*_#`~|<>\[\]{}]", " "),
]


def speakable(text: str) -> str:
    text = strip_markdown(text)
    for pat, rep in _REPLACE:
        text = re.sub(pat, rep, text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", text)  # эмодзи не читаем
    return re.sub(r"\s+", " ", text).strip()


def _iter_json(s: str):
    """Ответ SpeechKit v3 — поток JSON-объектов (через перевод строки или подряд)."""
    dec, i, n = json.JSONDecoder(), 0, len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        try:
            obj, i = dec.raw_decode(s, i)
        except ValueError:
            break
        yield obj


class TTS:
    def __init__(self, cfg):
        self.cfg = cfg
        t = cfg["tts"]
        self.speed = float(t.get("speed", 1.0))
        self.voice = t.get("yandex_voice", "marina")
        self.role = t.get("yandex_role", "neutral")
        self._piper = None
        self._piper_lock = threading.Lock()
        self._cache: OrderedDict = OrderedDict()
        self.engines = self._detect_engines(t.get("engine", "auto"))
        log.info("Синтез речи: %s", " → ".join(self.engines) or "нет движков!")

    # ------------------------------------------------------------ движки --
    def _has_yandex(self):
        return bool(self.cfg.get("yandex.api_key") or self.cfg.get("yandex.iam_token"))

    def _detect_engines(self, wanted: str):
        avail = []
        if self._has_yandex():
            avail.append("yandex")
        if self.cfg.path_of("tts.piper_model").exists():
            if importlib.util.find_spec("piper") is not None or shutil.which("piper"):
                avail.append("piper")
        if shutil.which("RHVoice-test"):
            avail.append("rhvoice")
        if shutil.which("espeak-ng") or shutil.which("espeak"):
            avail.append("espeak")
        if wanted and wanted != "auto":
            return [wanted] + [e for e in avail if e != wanted]
        return avail

    # ------------------------------------------------------------- синтез --
    def synth(self, text: str, emotion: str = "neutral", whisper: bool = False, lang: str = "ru",
              speed: float | None = None):
        """-> (int16 samples, sample_rate) или (None, 0)."""
        text = speakable(text)
        if not text:
            return None, 0
        spd = (speed or self.speed) * EMOTION_SPEED.get(emotion, 1.0)
        key = (text, emotion, whisper, lang, round(spd, 2))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        result = (None, 0)
        native_whisper = False
        engines = self.engines if lang == "ru" else [e for e in self.engines if e in ("yandex", "espeak")]
        for eng in engines:
            try:
                if eng == "yandex":
                    samples, sr, native_whisper = self._yandex(text, emotion, whisper, lang, spd)
                elif eng == "piper":
                    samples, sr = self._piper_synth(text, spd)
                elif eng == "rhvoice":
                    samples, sr = self._rhvoice(text, spd)
                elif eng == "espeak":
                    samples, sr = self._espeak(text, spd, lang)
                else:
                    continue
                if samples is not None and len(samples):
                    result = (samples, sr)
                    break
            except Exception as e:
                log.warning("TTS %s не сработал: %s", eng, e)
        samples, sr = result
        if samples is not None and whisper and not native_whisper:
            samples = dsp.whisperize(samples, sr)
        result = (samples, sr)
        if samples is not None and len(text) < 120:
            self._cache[key] = result
            if len(self._cache) > 150:
                self._cache.popitem(last=False)
        return result

    def _yandex(self, text, emotion, whisper, lang, speed):
        key, iam, folder = self.cfg.get("yandex.api_key"), self.cfg.get("yandex.iam_token"), \
            self.cfg.get("yandex.folder_id")
        headers = {"Authorization": f"Api-Key {key}" if key else f"Bearer {iam}"}
        user_iam = not key and folder  # каталог передаём только с IAM-токеном пользователя
        if user_iam:
            headers["x-folder-id"] = folder
        voice = self.voice
        if lang != "ru" and lang in LANG_VOICES:
            voice = LANG_VOICES[lang][1]
        roles = VOICE_ROLES.get(voice, ["neutral"])
        role = None
        native_whisper = False
        if whisper and "whisper" in roles:
            role, native_whisper = "whisper", True
        else:
            for r in EMOTION_ROLES.get(emotion, []):
                if r in roles:
                    role = r
                    break
            if role is None and self.role in roles:
                role = self.role
        sr = 22050
        # каждый элемент hints — ровно один ключ
        hints = [{"voice": voice}, {"speed": round(min(3.0, max(0.1, speed)), 2)}]
        if role and roles:
            hints.append({"role": role})
        body = {"text": text[:4900], "hints": hints, "loudnessNormalizationType": "LUFS", "unsafeMode": True,
                "outputAudioSpec": {"rawAudio": {"audioEncoding": "LINEAR16_PCM", "sampleRateHertz": sr}}}
        r = requests.post("https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis", headers=headers,
                          json=body, timeout=25)
        if r.ok:
            pcm = bytearray()
            for obj in _iter_json(r.text):
                if "error" in obj:
                    raise RuntimeError(str(obj["error"])[:200])
                chunk = (obj.get("result") or {}).get("audioChunk", {}).get("data")
                if chunk:
                    pcm += base64.b64decode(chunk)
            if pcm:
                return np.frombuffer(bytes(pcm), dtype=np.int16), sr, native_whisper
        log.info("SpeechKit v3: %s %s — пробую v1", r.status_code, r.text[:160])
        # запасной вариант — REST API v1
        data = {"text": text[:4900], "lang": LANG_VOICES.get(lang, ("ru-RU", ""))[0] if lang != "ru" else "ru-RU",
                "voice": voice, "speed": f"{speed:.2f}", "format": "lpcm", "sampleRateHertz": 48000}
        if user_iam:
            data["folderId"] = folder
        if role in ("good", "evil", "whisper", "friendly", "neutral"):
            data["emotion"] = role
        r = requests.post("https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize", headers=headers,
                          data=data, timeout=20)
        r.raise_for_status()
        return np.frombuffer(r.content, dtype=np.int16), 48000, False

    def _piper_synth(self, text, speed):
        model = self.cfg.path_of("tts.piper_model")
        try:
            from piper import PiperVoice
        except ImportError:
            return self._piper_cli(text, speed, model)
        with self._piper_lock:
            if self._piper is None:
                self._piper = PiperVoice.load(str(model))
            voice = self._piper
            try:  # piper-tts >= 1.3
                from piper import SynthesisConfig
                cfg = SynthesisConfig(length_scale=1.0 / max(0.3, speed))
                chunks = list(voice.synthesize(text, syn_config=cfg))
                if not chunks:
                    return None, 0
                audio = np.concatenate([c.audio_int16_array for c in chunks])
                return audio.astype(np.int16), chunks[0].sample_rate
            except ImportError:  # старый piper-tts 1.2
                import io
                import wave
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    voice.synthesize(text, wf, length_scale=1.0 / max(0.3, speed))
                return dsp.read_wav(buf.getvalue())

    def _piper_cli(self, text, speed, model):
        exe = shutil.which("piper")
        if not exe:
            return None, 0
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "o.wav")
            subprocess.run([exe, "-m", str(model), "-f", out, "--length-scale", f"{1 / speed:.2f}"],
                           input=text.encode(), check=True, capture_output=True, timeout=60)
            return dsp.read_wav(out)

    def _rhvoice(self, text, speed):
        voice = self.cfg.get("tts.rhvoice_voice", "anna")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "o.wav")
            subprocess.run(["RHVoice-test", "-p", voice, "-r", str(int(100 * speed)), "-o", out],
                           input=text.encode(), check=True, capture_output=True, timeout=60)
            return dsp.read_wav(out)

    def _espeak(self, text, speed, lang="ru"):
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        voice = self.cfg.get("tts.espeak_voice", "ru") if lang == "ru" else lang
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "o.wav")
            subprocess.run([exe, "-v", voice, "-s", str(int(165 * speed)), "-w", out, text],
                           check=True, capture_output=True, timeout=60)
            return dsp.read_wav(out)
