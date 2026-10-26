"""Tiny JSON-backed persistence for users, their settings and stats."""
import asyncio
import copy
import json
import time
from pathlib import Path

DEFAULT_SETTINGS = {
    "voice_id": "EXAVITQu4vr4xnSDxMaL",
    "voice_name": "Sarah",
    "tts_model": "eleven_multilingual_v2",
    "stability": 0.5,
    "similarity": 0.75,
    "style": 0.0,
    "speed": 1.0,
    "music_model": "music_v1",
    "music_length": 30,
    "instrumental": False,
    "sfx_model": "eleven_text_to_sound_v2",
    "sfx_duration": 0,
    "image_model": "gemini-3.1-flash-image",
    "image_aspect": "1:1",
    "video_model": "veo-3.1-fast-generate-001",
    "video_duration": 8,
    "video_aspect": "16:9",
    "video_resolution": "720p",
    "video_audio": True,
    "dub_lang": "en",
    "stt_model": "scribe_v2",
    "stt_diarize": False,
    "agent_voice": False,
}


class Storage:
    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self._data = {"users": {}, "global": {}}
        if path.exists():
            self._data = json.loads(path.read_text("utf-8"))
            self._data.setdefault("users", {})
            self._data.setdefault("global", {})

    async def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.path)

    def user(self, uid: int) -> dict:
        u = self._data["users"].get(str(uid))
        if u is None:
            u = {
                "activated": False,
                "name": None,
                "joined": int(time.time()),
                "settings": {},
                "stats": {},
                "history": [],
                "api_key": None,
                "agents": [],
            }
            self._data["users"][str(uid)] = u
        return u

    def settings(self, uid: int) -> dict:
        s = copy.deepcopy(DEFAULT_SETTINGS)
        s.update(self.user(uid)["settings"])
        return s

    async def update(self, uid: int, **fields):
        async with self._lock:
            self.user(uid).update(fields)
            await self._save()

    async def set_setting(self, uid: int, key: str, value):
        async with self._lock:
            self.user(uid)["settings"][key] = value
            await self._save()

    async def track(self, uid: int, feature: str, note: str = ""):
        async with self._lock:
            u = self.user(uid)
            u["stats"][feature] = u["stats"].get(feature, 0) + 1
            u["history"] = ([{"f": feature, "t": int(time.time()), "n": note[:60]}] + u["history"])[:30]
            await self._save()

    async def add_agent(self, uid: int, agent_id: str, name: str):
        async with self._lock:
            u = self.user(uid)
            u["agents"] = [a for a in u["agents"] if a["id"] != agent_id] + [{"id": agent_id, "name": name}]
            await self._save()

    async def remove_agent(self, uid: int, agent_id: str):
        async with self._lock:
            u = self.user(uid)
            u["agents"] = [a for a in u["agents"] if a["id"] != agent_id]
            await self._save()

    def get_global(self, key: str):
        return self._data["global"].get(key)

    async def set_global(self, key: str, value):
        async with self._lock:
            self._data["global"][key] = value
            await self._save()
