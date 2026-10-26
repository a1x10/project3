"""Async client for the ElevenLabs API: audio, music, voices, agents, image & video."""
import asyncio
import base64
import json

import httpx
import websockets

BASE = "https://api.elevenlabs.io"


class ElevenError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _error_message(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        return resp.text[:300] or resp.reason_phrase
    if isinstance(detail, dict):
        return detail.get("message") or detail.get("status") or json.dumps(detail, ensure_ascii=False)
    if isinstance(detail, list):
        return "; ".join(f"{'.'.join(map(str, d.get('loc', [])))}: {d.get('msg')}" for d in detail)
    return str(detail)


class Eleven:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.http = httpx.AsyncClient(
            base_url=BASE,
            headers={"xi-api-key": api_key},
            timeout=httpx.Timeout(600, connect=20),
        )

    async def close(self):
        await self.http.aclose()

    async def _req(self, method: str, path: str, *, raw: bool = False, **kw):
        if not self.api_key:
            raise ElevenError(401, "API-ключ ElevenLabs не задан. Добавьте его в .env или в профиле.")
        resp = await self.http.request(method, path, **kw)
        if resp.status_code >= 400:
            raise ElevenError(resp.status_code, _error_message(resp))
        if raw:
            return resp.content
        return resp.json() if resp.content else {}

    # ── speech ────────────────────────────────────────────────────────────
    async def tts(self, text: str, voice_id: str, model: str, s: dict) -> bytes:
        if model == "eleven_v4":
            return await self.dialogue([{"text": text, "voice_id": voice_id}], model)
        body = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": s["stability"],
                "similarity_boost": s["similarity"],
                "style": s["style"],
                "speed": s["speed"],
                "use_speaker_boost": True,
            },
        }
        return await self._req(
            "POST", f"/v1/text-to-speech/{voice_id}", params={"output_format": "mp3_44100_128"}, json=body, raw=True
        )

    async def dialogue(self, inputs: list[dict], model: str = "eleven_v3") -> bytes:
        return await self._req(
            "POST",
            "/v1/text-to-dialogue",
            params={"output_format": "mp3_44100_128"},
            json={"inputs": inputs, "model_id": model},
            raw=True,
        )

    async def sts(self, audio: bytes, filename: str, voice_id: str) -> bytes:
        return await self._req(
            "POST",
            f"/v1/voice-changer/{voice_id}",
            params={"output_format": "mp3_44100_128"},
            data={"model_id": "eleven_multilingual_sts_v2", "remove_background_noise": "true"},
            files={"audio": (filename, audio)},
            raw=True,
        )

    async def stt(self, media: bytes, filename: str, model: str, diarize: bool) -> dict:
        data = {"model_id": model, "tag_audio_events": "true"}
        if diarize:
            data["diarize"] = "true"
        return await self._req("POST", "/v1/speech-to-text", data=data, files={"file": (filename, media)})

    async def isolate(self, audio: bytes, filename: str) -> bytes:
        return await self._req("POST", "/v1/audio-isolation", files={"audio": (filename, audio)}, raw=True)

    async def sfx(self, text: str, duration: float, model: str) -> bytes:
        body = {"text": text, "model_id": model, "prompt_influence": 0.4}
        if duration:
            body["duration_seconds"] = duration
        return await self._req(
            "POST", "/v1/sound-generation", params={"output_format": "mp3_44100_128"}, json=body, raw=True
        )

    # ── music ─────────────────────────────────────────────────────────────
    async def music(self, prompt: str, length_s: int, model: str, instrumental: bool) -> bytes:
        body = {"prompt": prompt, "model_id": model, "force_instrumental": instrumental}
        if length_s:
            body["music_length_ms"] = int(length_s * 1000)
        return await self._req("POST", "/v1/music", json=body, raw=True)

    async def video_to_music(self, video: bytes, filename: str, description: str) -> bytes:
        data = {"add_sfx": "true"}
        if description:
            data["description"] = description
        return await self._req(
            "POST",
            "/v1/music/video-to-music",
            params={"output_format": "mp3_44100_128"},
            data=data,
            files=[("videos", (filename, video))],
            raw=True,
        )

    async def separate_stems(self, audio: bytes, filename: str) -> bytes:
        return await self._req(
            "POST",
            "/v1/music/stem-separation",
            params={"output_format": "mp3_44100_128"},
            files={"file": (filename, audio)},
            raw=True,
        )

    # ── voices ────────────────────────────────────────────────────────────
    async def voices(self, search: str | None = None, voice_type: str | None = None, page_size: int = 40) -> list:
        params = {"page_size": page_size}
        if search:
            params["search"] = search
        if voice_type:
            params["voice_type"] = voice_type
        data = await self._req("GET", "/v2/voices", params=params)
        return data.get("voices", [])

    async def design_voice(self, description: str) -> dict:
        return await self._req(
            "POST",
            "/v1/text-to-voice/design",
            params={"output_format": "mp3_44100_128"},
            json={"voice_description": description, "auto_generate_text": True, "model_id": "eleven_ttv_v3"},
        )

    async def save_designed_voice(self, name: str, description: str, generated_voice_id: str) -> dict:
        return await self._req(
            "POST",
            "/v1/text-to-voice",
            json={"voice_name": name, "voice_description": description, "generated_voice_id": generated_voice_id},
        )

    async def clone_voice(self, name: str, samples: list[tuple[str, bytes]]) -> dict:
        files = [("files", (fn, data)) for fn, data in samples]
        return await self._req(
            "POST", "/v1/voices/add", data={"name": name, "remove_background_noise": "true"}, files=files
        )

    async def delete_voice(self, voice_id: str):
        return await self._req("DELETE", f"/v1/voices/{voice_id}")

    async def subscription(self) -> dict:
        return await self._req("GET", "/v1/user/subscription")

    # ── dubbing ───────────────────────────────────────────────────────────
    async def dub_create(self, media: bytes, filename: str, target_lang: str) -> dict:
        return await self._req(
            "POST",
            "/v1/dubbing/project",
            data={"target_language": target_lang, "reference": "stells-bot"},
            files={"file": (filename, media)},
        )

    async def dub_project(self, project_id: str) -> dict:
        return await self._req("GET", f"/v1/dubbing/project/{project_id}")

    async def dub_language(self, project_id: str, language_id: str) -> dict:
        return await self._req("GET", f"/v1/dubbing/project/{project_id}/language/{language_id}")

    # ── image & video ─────────────────────────────────────────────────────
    async def image_create(self, body: dict) -> str:
        return (await self._req("POST", "/v1/flows/image", json=body))["id"]

    async def video_create(self, body: dict) -> str:
        return (await self._req("POST", "/v1/flows/video", json=body))["id"]

    async def generation(self, kind: str, gen_id: str) -> dict:
        return await self._req("GET", f"/v1/flows/{kind}/{gen_id}")

    async def wait_generation(self, kind: str, gen_id: str, on_status=None, timeout: int = 1200) -> dict:
        """Polls a flows generation until it completes, following the documented intervals."""
        delay = 2 if kind == "image" else 10
        waited = 0
        while waited < timeout:
            g = await self.generation(kind, gen_id)
            if on_status:
                await on_status(g["status"])
            if g["status"] == "completed":
                return g
            if g["status"] == "failed":
                raise ElevenError(422, f"{g.get('failure_reason')}: {g.get('error_message')}")
            await asyncio.sleep(delay)
            waited += delay
            delay = min(delay * 1.4, 60)
        raise ElevenError(504, "Генерация заняла слишком много времени")

    async def download(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.content

    # ── agents ────────────────────────────────────────────────────────────
    async def create_agent(self, name: str, prompt: str, first_message: str, voice_id: str, language: str = "ru") -> str:
        body = {
            "name": name,
            "tags": ["stells"],
            "conversation_config": {
                "agent": {
                    "first_message": first_message,
                    "language": language,
                    "prompt": {"prompt": prompt},
                },
                "tts": {"voice_id": voice_id, "model_id": "eleven_flash_v2_5"},
                "conversation": {"text_only": True},
            },
        }
        return (await self._req("POST", "/v1/convai/agents/create", json=body))["agent_id"]

    async def list_agents(self) -> list:
        return (await self._req("GET", "/v1/convai/agents", params={"page_size": 30}))["agents"]

    async def delete_agent(self, agent_id: str):
        return await self._req("DELETE", f"/v1/convai/agents/{agent_id}")

    async def signed_url(self, agent_id: str) -> str:
        data = await self._req("GET", "/v1/convai/conversation/get-signed-url", params={"agent_id": agent_id})
        return data["signed_url"]


def b64_ref(data: bytes, mime: str) -> dict:
    return {"type": "inline_base64", "content_base64": base64.b64encode(data).decode(), "mime_type": mime}


class AgentChat:
    """A text-only conversation with an ElevenLabs agent over WebSocket."""

    def __init__(self, client: Eleven, agent_id: str, context: str = ""):
        self.client = client
        self.agent_id = agent_id
        self.context = context
        self.ws = None
        self.reader: asyncio.Task | None = None
        self.events: asyncio.Queue = asyncio.Queue()

    @property
    def alive(self) -> bool:
        return self.ws is not None and self.reader is not None and not self.reader.done()

    async def connect(self):
        url = await self.client.signed_url(self.agent_id)
        self.ws = await websockets.connect(url, max_size=None, open_timeout=30)
        await self.ws.send(json.dumps({"type": "conversation_initiation_client_data"}))
        self.reader = asyncio.create_task(self._read())
        if self.context:
            await self.ws.send(json.dumps({"type": "contextual_update", "text": self.context}))

    async def _read(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "ping":
                    await self.ws.send(json.dumps({"type": "pong", "event_id": msg["ping_event"]["event_id"]}))
                elif t == "agent_chat_response_part":
                    part = msg["text_response_part"]
                    await self.events.put(("part", part.get("type"), part.get("text", "")))
                elif t == "agent_response":
                    await self.events.put(("final", None, msg["agent_response_event"]["agent_response"]))
                elif t == "client_error" or t == "error":
                    await self.events.put(("error", None, json.dumps(msg, ensure_ascii=False)[:300]))
        except websockets.ConnectionClosed:
            pass
        finally:
            await self.events.put(("closed", None, ""))

    async def next_reply(self, on_delta=None, timeout: float = 90) -> str:
        """Waits for one complete agent reply, streaming deltas to on_delta."""
        buf = ""
        while True:
            kind, part_type, text = await asyncio.wait_for(self.events.get(), timeout)
            if kind == "part":
                if part_type == "start":
                    buf = ""
                buf += text
                if on_delta and text:
                    await on_delta(buf)
            elif kind == "final":
                return text or buf
            elif kind == "error":
                raise ElevenError(500, text)
            elif kind == "closed":
                if buf:
                    return buf
                raise ElevenError(499, "Соединение с агентом закрыто")

    async def send(self, text: str):
        await self.ws.send(json.dumps({"type": "user_message", "text": text}))

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
        if self.reader is not None:
            self.reader.cancel()
