"""Связь с другими Стеллами в доме (колонки в других комнатах): объявления, команды,
радионяня и звонки — звук идёт по WebSocket (PCM 16 кГц, 16 бит, моно)."""
from __future__ import annotations

import asyncio
import logging
import queue
import threading

import numpy as np
import requests

from ..audio import dsp
from ..nlp.text import best_match, stems

log = logging.getLogger("stella.peers")


class Peers:
    def __init__(self, assistant):
        self.a = assistant
        self.cfg = assistant.cfg

    @property
    def all(self) -> dict:
        return dict(self.cfg.get("peers") or {})

    def _headers(self):
        pw = self.cfg.get("web.password")
        return {"X-Stella-Key": pw} if pw else {}

    def find(self, text: str):
        """«на кухне» / «в детскую» -> ("кухня", url)."""
        peers = self.all
        if not peers:
            return None
        st = set(stems(text))
        for name, url in peers.items():
            if set(stems(name)) & st:
                return name, url
        hit, _ = best_match(text, list(peers.items()), key=lambda kv: kv[0], threshold=0.6)
        return hit

    def post(self, url: str, path: str, payload: dict, timeout: float = 8):
        r = requests.post(url.rstrip("/") + path, json=payload, headers=self._headers(), timeout=timeout,
                          verify=False)
        r.raise_for_status()
        return r.json() if r.content else {}

    def say(self, url: str, text: str, emotion: str | None = None):
        return self.post(url, "/api/say", {"text": text, "emotion": emotion, "from": self.a.name})

    def command(self, url: str, text: str):
        return self.post(url, "/api/command", {"text": text, "speak": True}, timeout=30)

    def ws_url(self, url: str, path: str) -> str:
        return url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + path


class AudioLink(threading.Thread):
    """Звук между устройствами. send_mic=False — только слушаем (радионяня), True — звонок."""

    def __init__(self, assistant, ws_url: str, send_mic: bool, headers: dict | None = None, on_end=None):
        super().__init__(daemon=True, name="audio-link")
        self.a = assistant
        self.url = ws_url
        self.send_mic = send_mic
        self.headers = headers or {}
        self.on_end = on_end
        self._stop = threading.Event()
        self.connected = False

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            asyncio.run(self._main())
        except Exception as e:
            log.warning("Аудиосвязь %s: %s", self.url, e)
        finally:
            self.connected = False
            if self.on_end:
                self.on_end()

    async def _main(self):
        import aiohttp
        try:
            import sounddevice as sd
        except Exception:
            sd = None
        out = None
        if sd is not None:
            out = sd.OutputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1600)
            out.start()
        mic_q = self.a.mic.subscribe() if self.send_mic else None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(self.url, headers=self.headers, ssl=False, heartbeat=15) as ws:
                    self.connected = True
                    loop = asyncio.get_running_loop()

                    async def sender():
                        while not self._stop.is_set() and mic_q is not None:
                            try:
                                frame = await loop.run_in_executor(None, lambda: mic_q.get(timeout=0.5))
                            except queue.Empty:
                                continue
                            await ws.send_bytes(frame.astype(np.int16).tobytes())

                    task = asyncio.create_task(sender()) if self.send_mic else None
                    while not self._stop.is_set():
                        try:
                            msg = await ws.receive(timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            data = np.frombuffer(msg.data, dtype=np.int16)
                            if out is not None:
                                await loop.run_in_executor(None, out.write, data.reshape(-1, 1))
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                    if task:
                        task.cancel()
                    await ws.close()
        finally:
            if mic_q is not None:
                self.a.mic.unsubscribe(mic_q)
            if out is not None:
                out.stop()
                out.close()


class LocalCall:
    """Входящий звонок (с телефона или другой Стеллы): наш микрофон -> send(), чужой звук -> play()."""

    def __init__(self, assistant):
        self.a = assistant
        self.q = assistant.mic.subscribe()
        self.active = True
        self.out = None
        try:
            import sounddevice as sd
            self.out = sd.OutputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1600)
            self.out.start()
        except Exception as e:
            log.warning("Звонок без динамика: %s", e)
        self._remote_level = 0.0

    def next_frame(self, timeout: float = 0.5):
        try:
            frame = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        if self._remote_level > 0.25:  # простое подавление эха: пока говорит собеседник, приглушаем микрофон
            frame = (frame.astype(np.float32) * 0.3).astype(np.int16)
        return frame

    def play(self, data: bytes):
        pcm = np.frombuffer(data, dtype=np.int16)
        self._remote_level = dsp.level01(pcm)
        if self.out is not None:
            self.out.write(pcm.reshape(-1, 1))

    def close(self):
        self.active = False
        self.a.mic.unsubscribe(self.q)
        if self.out is not None:
            try:
                self.out.stop()
                self.out.close()
            except Exception:
                pass
