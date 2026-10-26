"""Распознавание речи: локальный Whisper и/или ElevenLabs Scribe.

quality:
  gate     — фильтр «к ней ли обращаются» (всегда Whisper в hybrid: дёшево)
  accurate — команда/диктовка (Scribe в hybrid и elevenlabs)
  stream   — непрерывные куски совещания (Scribe только в режиме elevenlabs)
"""
import mimetypes
import shutil
import subprocess
import tempfile

import httpx

from . import config

_model = None


def load():
    """Whisper заранее (при старте), иначе первый запрос ждёт скачивания модели."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def _boost(data: bytes, suffix: str) -> bytes:
    """Тихий микрофон очков: убираем гул и выравниваем громкость (ffmpeg). Нет ffmpeg/ошибка — как есть."""
    if not shutil.which("ffmpeg"):
        return data
    try:
        r = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000",
             "-af", "highpass=f=70,dynaudnorm=f=120:g=11:p=0.9:m=20", "-f", "wav", "pipe:1"],
            input=data, capture_output=True, timeout=20)
        return r.stdout if r.returncode == 0 and len(r.stdout) > 1000 else data
    except Exception:
        return data


def _vad_params() -> dict:
    """Мягкий фильтр речи для тихого микрофона. Имена параметров зависят от версии faster-whisper."""
    try:
        import dataclasses
        from faster_whisper.vad import VadOptions
        names = {f.name for f in dataclasses.fields(VadOptions)}
    except Exception:
        return {}
    p = {}
    if "onset" in names:
        p.update(onset=0.25, offset=0.1)
    elif "threshold" in names:
        p["threshold"] = 0.25
    if "min_silence_duration_ms" in names:
        p["min_silence_duration_ms"] = 600
    if "speech_pad_ms" in names:
        p["speech_pad_ms"] = 300
    return p


def _segments(path: str, vad: bool, common: dict):
    if vad:
        segs, _ = _model.transcribe(path, vad_filter=True, vad_parameters=_vad_params(), no_speech_threshold=0.8, **common)
        return [s.text.strip() for s in segs]
    # без фильтра речи: отбрасываем сегменты, которые Whisper сам считает шумом
    segs, _ = _model.transcribe(path, vad_filter=False, no_speech_threshold=0.6, **common)
    return [s.text.strip() for s in segs if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0]


def whisper(data: bytes, suffix: str = ".wav") -> str:
    load()
    data = _boost(data, suffix)
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(data)
        f.flush()
        common = dict(language=config.WHISPER_LANG or None, condition_on_previous_text=False,
                      initial_prompt="Стелла, привет. Стелла, запиши в календарь.")
        for vad in (True, False):       # сначала с фильтром речи, при пустом результате — без него
            try:
                text = " ".join(_segments(f.name, vad, common)).strip()
            except Exception as e:
                print(f"[stt] whisper vad={vad} failed: {e}")
                continue
            if text:
                return text
        return ""


def _post(url: str, **kw) -> httpx.Response:     # отдельная функция — удобно подменять в тестах
    return httpx.post(url, **kw)


def scribe(data: bytes, suffix: str = ".webm") -> str:
    mime = mimetypes.types_map.get(suffix, "audio/webm")
    form = {"model_id": config.ELEVENLABS_STT_MODEL, "tag_audio_events": "false", "diarize": "false"}
    if config.WHISPER_LANG:
        form["language_code"] = config.WHISPER_LANG
    if config.ELEVENLABS_STT_KEYTERMS:
        form["keyterms"] = config.ELEVENLABS_STT_KEYTERMS      # подсказка: имя ассистента (+20% к цене Scribe)
    r = _post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": config.ELEVENLABS_API_KEY},
              data=form, files={"file": ("audio" + suffix, data, mime)}, timeout=40)
    if r.status_code >= 400:
        raise RuntimeError(f"Scribe {r.status_code}: {r.text[:200]}")
    return (r.json().get("text") or "").strip()


def use_scribe(quality: str) -> bool:
    if not config.ELEVENLABS_API_KEY or config.STT_ENGINE == "whisper":
        return False
    if config.STT_ENGINE == "elevenlabs":
        return True
    return quality == "accurate"       # hybrid


def transcribe(data: bytes, suffix: str = ".wav", quality: str = "gate") -> str:
    if use_scribe(quality):
        try:
            return scribe(data, suffix)
        except Exception as e:         # нет интернета/кончились минуты — работаем на Whisper
            print(f"[stt] scribe failed, whisper fallback: {e}")
    text = whisper(data, suffix)
    # Whisper ничего не услышал, а запись не пустая — второе мнение у Scribe (STT_SCRIBE_ON_EMPTY=0 отключает)
    if (not text and len(data) > 5000 and config.STT_SCRIBE_ON_EMPTY and config.ELEVENLABS_API_KEY
            and config.STT_ENGINE != "whisper" and quality == "gate"):
        try:
            text = scribe(data, suffix)
            print(f"[stt] whisper пусто -> scribe: {text!r}")
        except Exception as e:
            print(f"[stt] scribe (second opinion) failed: {e}")
    return text
