"""Озвучка Стеллы через ElevenLabs. Готовые фразы кэшируются на диске."""
import hashlib
import os

import httpx

from . import config

_DIR = os.path.join(config.DATA_DIR, "tts")
_MAX_FILES = 400


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
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}",
            params={"output_format": "mp3_44100_64"},
            headers={"xi-api-key": config.ELEVENLABS_API_KEY},
            json={"text": text, "model_id": config.ELEVENLABS_MODEL,
                  "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "speed": 1.05}})
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    with open(path, "wb") as f:
        f.write(r.content)
    _trim()
    return r.content
