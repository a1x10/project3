"""Озвучка Стеллы через ElevenLabs. Готовые фразы кэшируются на диске."""
import hashlib
import os

import httpx

from . import config

_DIR = os.path.join(config.DATA_DIR, "tts")
_MAX_FILES = 400


FALLBACK = "eleven_flash_v2_5"


async def _request(text: str, model: str, settings: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=40) as c:
        return await c.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}",
            params={"output_format": "mp3_44100_64"},
            headers={"xi-api-key": config.ELEVENLABS_API_KEY},
            json={"text": text, "model_id": model, "voice_settings": settings})


def enabled() -> bool:
    return bool(config.ELEVENLABS_API_KEY)


def _trim():
    files = sorted((os.path.join(_DIR, f) for f in os.listdir(_DIR)), key=os.path.getmtime)
    for f in files[:-_MAX_FILES]:
        os.remove(f)


async def synth(text: str) -> bytes:
    text = text.strip()[:900]
    os.makedirs(_DIR, exist_ok=True)
    key = hashlib.sha1(f"{config.ELEVENLABS_VOICE_ID}|{config.ELEVENLABS_MODEL}|{text}".encode()).hexdigest()
    path = os.path.join(_DIR, key + ".mp3")
    if os.path.exists(path):
        os.utime(path)
        with open(path, "rb") as f:
            return f.read()
    settings = {"stability": config.ELEVENLABS_STABILITY, "similarity_boost": config.ELEVENLABS_SIMILARITY}
    if config.ELEVENLABS_SPEED:
        settings["speed"] = float(config.ELEVENLABS_SPEED)
    r = await _request(text, config.ELEVENLABS_MODEL, settings)
    if r.status_code >= 400 and config.ELEVENLABS_MODEL != FALLBACK:
        # неверное имя модели или модель недоступна на тарифе — один раз пробуем быструю
        print(f"[tts] {config.ELEVENLABS_MODEL} -> {r.status_code}: {r.text[:200]}; fallback {FALLBACK}")
        r = await _request(text, FALLBACK, {k: v for k, v in settings.items() if k != "speed"})
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    with open(path, "wb") as f:
        f.write(r.content)
    _trim()
    return r.content
