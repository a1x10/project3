"""Распознавание речи: локальный Whisper и/или ElevenLabs Scribe.

quality:
  gate     — фильтр «к ней ли обращаются» (всегда Whisper в hybrid: дёшево)
  accurate — команда/диктовка (Scribe в hybrid и elevenlabs)
  stream   — непрерывные куски совещания (Scribe только в режиме elevenlabs)
"""
import mimetypes
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


def whisper(data: bytes, suffix: str = ".wav") -> str:
    load()
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(data)
        f.flush()
        segs, _ = _model.transcribe(f.name, language=config.WHISPER_LANG or None, vad_filter=True,
                                    initial_prompt="Стелла, привет. Стелла, запиши в календарь.")
        return " ".join(s.text.strip() for s in segs).strip()


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
    return whisper(data, suffix)
