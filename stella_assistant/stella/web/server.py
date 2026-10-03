"""Веб-панель Стеллы (aiohttp): чат и голос из браузера телефона/компьютера, живое лицо, списки,
будильники, музыка, умный дом и сценарии, радионяня (/baby) и звонки (/call).

Работает в отдельном потоке со своим event loop. Если задан web.password — нужен вход."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import queue
import ssl
import subprocess
import threading
from pathlib import Path

from aiohttp import WSMsgType, web

from ..audio import dsp
from ..core.events import bus
from ..face.emotions import EMOTION_NAMES_RU, EMOTIONS
from ..integrations.peers import LocalCall

log = logging.getLogger("stella.web")
STATIC = Path(__file__).resolve().parent / "static"
PUBLIC = {"/login", "/api/login", "/static/style.css", "/static/favicon.svg", "/static/manifest.json"}
EVENT_TOPICS = {"reply", "heard", "emotion", "mood", "state", "notify", "baby_alert", "presence"}


def _token(pw: str) -> str:
    return hashlib.sha256(("stella:" + pw).encode()).hexdigest()


class WebServer(threading.Thread):
    def __init__(self, assistant):
        super().__init__(daemon=True, name="web")
        self.a = assistant
        self.cfg = assistant.cfg
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set = set()
        self.calls: set = set()
        assistant.web = self
        bus.on("*", self._on_event)

    # ------------------------------------------------------------- события --
    def _on_event(self, topic: str, **data):
        if topic not in EVENT_TOPICS or not self.loop or not self.clients:
            return
        payload = json.dumps({"topic": topic, **{k: v for k, v in data.items()
                                                 if isinstance(v, (str, int, float, bool, type(None), list, dict))}},
                             ensure_ascii=False)
        asyncio.run_coroutine_threadsafe(self._broadcast(payload), self.loop)

    async def _broadcast(self, payload: str):
        for ws in list(self.clients):
            try:
                await ws.send_str(payload)
            except Exception:
                self.clients.discard(ws)

    def hangup(self) -> bool:
        had = bool(self.calls)
        for c in list(self.calls):
            c.active = False
        return had

    # -------------------------------------------------------------- запуск --
    def run(self):
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("Веб-панель упала")

    def _ssl(self):
        if not self.cfg.get("web.https"):
            return None
        d = self.cfg.data_dir
        cert, key = d / "cert.pem", d / "key.pem"
        if not cert.exists():
            log.info("Создаю самоподписанный сертификат для HTTPS…")
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                            "-out", str(cert), "-days", "3650", "-subj", "/CN=stella.local"],
                           capture_output=True, check=True)
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(str(cert), str(key))
        return ctx

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        app = web.Application(middlewares=[self._auth], client_max_size=25 * 1024 * 1024)
        r = app.router
        r.add_get("/", self._page("index.html"))
        r.add_get("/baby", self._page("baby.html"))
        r.add_get("/call", self._page("call.html"))
        r.add_get("/login", self._page("login.html"))
        r.add_post("/api/login", self.login)
        r.add_get("/api/state", self.state)
        r.add_post("/api/command", self.command)
        r.add_post("/api/say", self.say)
        r.add_post("/api/emotion", self.emotion)
        r.add_post("/api/voice", self.voice)
        r.add_get("/api/tts", self.tts)
        r.add_post("/api/player", self.player)
        r.add_post("/api/lists/{name}", self.list_add)
        r.add_post("/api/items/{id}", self.item_update)
        r.add_delete("/api/items/{id}", self.item_delete)
        r.add_post("/api/notes", self.note_add)
        r.add_delete("/api/notes/{id}", self.note_delete)
        r.add_delete("/api/alarms/{id}", self.alarm_delete)
        r.add_get("/api/devices", self.devices)
        r.add_post("/api/devices/{id}", self.device_set)
        r.add_get("/api/scenarios", self.scenarios_get)
        r.add_post("/api/scenarios", self.scenarios_set)
        r.add_get("/api/face.mjpg", self.face_stream)
        r.add_get("/ws/events", self.ws_events)
        r.add_get("/ws/baby", self.ws_baby)
        r.add_get("/ws/call", self.ws_call)
        r.add_static("/static", STATIC)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        host, port = self.cfg.get("web.host", "0.0.0.0"), int(self.cfg.get("web.port", 8765))
        site = web.TCPSite(runner, host, port, ssl_context=self._ssl())
        await site.start()
        log.info("Веб-панель: %s://%s:%s", "https" if self.cfg.get("web.https") else "http", host, port)
        while not self.a.stop_event.is_set():
            await asyncio.sleep(0.5)
        await runner.cleanup()

    # ---------------------------------------------------------- авторизация --
    @web.middleware
    async def _auth(self, request, handler):
        pw = self.cfg.get("web.password")
        if not pw or request.path in PUBLIC:
            return await handler(request)
        if request.headers.get("X-Stella-Key") == pw or request.cookies.get("stella") == _token(pw):
            return await handler(request)
        if request.path.startswith(("/api/", "/ws/")):
            raise web.HTTPUnauthorized(text="нужен пароль")
        raise web.HTTPFound("/login")

    async def login(self, request):
        data = await request.json()
        pw = self.cfg.get("web.password")
        if pw and data.get("password") != pw:
            raise web.HTTPUnauthorized(text="неверный пароль")
        resp = web.json_response({"ok": True})
        if pw:
            resp.set_cookie("stella", _token(pw), max_age=3600 * 24 * 365, httponly=True, samesite="Lax")
        return resp

    def _page(self, name):
        async def handler(request):
            return web.FileResponse(STATIC / name)
        return handler

    async def _run(self, fn, *args, **kw):
        return await self.loop.run_in_executor(None, lambda: fn(*args, **kw))

    # ------------------------------------------------------------------ API --
    async def state(self, request):
        a = self.a
        m = a.memory
        cur = a.player.current()
        alarms = [{"id": x["id"], "kind": x["kind"], "due": x["due"], "label": x["label"], "repeat": x["repeat"],
                   "extra": x["extra"]} for x in m.alarms()]
        lists = {name: m.list_items(name, include_done=True) for name in set(m.list_names()) | {"покупки", "дела"}}
        return web.json_response({
            "name": a.name,
            "emotion": a.face.current_emotion() if a.face else None,
            "emotions": {e: EMOTION_NAMES_RU.get(e, e) for e in EMOTIONS},
            "mood": {"level": a.mood.level, "irritation": round(a.mood.irritation, 1),
                     "affection": round(a.mood.affection, 1), "sleeping": a.mood.sleeping},
            "whisper": a.whisper_mode,
            "player": {"playing": a.player.is_playing(), "active": a.player.is_active(),
                       "title": cur.display() if cur else "", "source": cur.source if cur else "",
                       "volume": a.player.volume},
            "alarms": alarms, "lists": lists, "notes": m.notes(30),
            "peers": list((self.cfg.get("peers") or {}).keys()),
            "baby": bool(getattr(a.skill("babymonitor"), "active", False)),
            "voice": bool(a.listener and a.listener.ok), "llm": a.brain.available,
            "face": a.face is not None,
        })

    async def command(self, request):
        data = await request.json()
        text = (data.get("text") or "").strip()
        reply = await self._run(self.a.ask, text, "web", 90, speak=bool(data.get("speak")))
        return web.json_response({"text": reply.text, "emotion": reply.emotion, "card": reply.card,
                                  "expect_reply": reply.expect_reply})

    async def say(self, request):
        data = await request.json()
        text = data.get("text", "")
        if data.get("from"):
            bus.emit("emotion", name="interest", intensity=0.8, hold=5)
        threading.Thread(target=self.a.say, args=(text,), kwargs={"emotion": data.get("emotion")}, daemon=True).start()
        return web.json_response({"ok": True})

    async def emotion(self, request):
        data = await request.json()
        if data.get("name") == "demo" and self.a.face:
            self.a.face.demo = not self.a.face.demo
        else:
            bus.emit("emotion", name=data.get("name", "neutral"), intensity=float(data.get("intensity", 1)), hold=10)
        return web.json_response({"ok": True})

    async def voice(self, request):
        """Голос из браузера: запись -> текст -> ответ + синтезированная речь (WAV base64)."""
        from ..audio.stt import decode_audio_file, recognize_pcm
        post = await request.post()
        f = post.get("audio")
        if f is None:
            raise web.HTTPBadRequest(text="нет аудио")
        raw = f.file.read()
        pcm = await self._run(decode_audio_file, raw)
        if pcm is None or len(pcm) < 1600:
            return web.json_response({"heard": "", "text": "Ничего не услышала."})
        heard = await self._run(recognize_pcm, self.cfg, pcm)
        heard = heard.replace("стелла", "").strip() if heard else ""
        if not heard:
            return web.json_response({"heard": "", "text": "Не разобрала, повтори, пожалуйста."})
        reply = await self._run(self.a.ask, heard, "web", 90)
        audio = None
        if reply.text:
            samples, sr = await self._run(self.a.tts.synth, reply.text, reply.emotion or "neutral")
            if samples is not None:
                audio = base64.b64encode(dsp.wav_bytes(samples, sr)).decode()
        return web.json_response({"heard": heard, "text": reply.text, "emotion": reply.emotion, "card": reply.card,
                                  "audio": audio})

    async def tts(self, request):
        text = request.query.get("text", "")[:1000]
        samples, sr = await self._run(self.a.tts.synth, text, request.query.get("emotion", "neutral"))
        if samples is None:
            raise web.HTTPServiceUnavailable(text="нет синтеза речи")
        return web.Response(body=dsp.wav_bytes(samples, sr), content_type="audio/wav")

    async def player(self, request):
        data = await request.json()
        p = self.a.player
        act = data.get("action")
        if act == "pause":
            await self._run(p.pause)
        elif act == "resume":
            ok = await self._run(p.resume)
            if not ok:
                music = self.a.skill("music")
                if music:
                    await self._run(music.play_default)
        elif act == "next":
            await self._run(p.next)
        elif act == "prev":
            await self._run(p.prev)
        elif act == "stop":
            await self._run(p.stop)
        elif act == "volume":
            await self._run(p.set_volume, int(data.get("value", 60)))
        return web.json_response({"ok": True})

    async def list_add(self, request):
        data = await request.json()
        item_id = self.a.memory.list_add(request.match_info["name"], data.get("text", ""))
        return web.json_response({"id": item_id})

    async def item_update(self, request):
        data = await request.json()
        self.a.memory.item_set(int(request.match_info["id"]), **{k: v for k, v in data.items() if k in ("done", "text")})
        return web.json_response({"ok": True})

    async def item_delete(self, request):
        self.a.memory.item_delete(int(request.match_info["id"]))
        return web.json_response({"ok": True})

    async def note_add(self, request):
        data = await request.json()
        return web.json_response({"id": self.a.memory.note_add(data.get("text", ""))})

    async def note_delete(self, request):
        self.a.memory.note_delete(int(request.match_info["id"]))
        return web.json_response({"ok": True})

    async def alarm_delete(self, request):
        self.a.memory.alarm_delete(int(request.match_info["id"]))
        return web.json_response({"ok": True})

    async def devices(self, request):
        sh = self.a.skill("smarthome")
        if not (sh and sh.configured):
            return web.json_response({"configured": False, "devices": []})
        devs = await self._run(sh.devices, True)
        out = []
        for d in devs:
            on = None
            c = d.cap("devices.capabilities.on_off")
            if c and c.get("state"):
                on = c["state"].get("value")
            if d.backend == "ha":
                on = d.state.get("state") == "on" if d.state.get("state") in ("on", "off") else None
            out.append({"id": d.id, "name": d.name, "room": d.room, "type": d.type or d.domain, "on": on,
                        "backend": d.backend})
        return web.json_response({"configured": True, "devices": out})

    async def device_set(self, request):
        sh = self.a.skill("smarthome")
        data = await request.json()
        devs = [d for d in await self._run(sh.devices) if d.id == request.match_info["id"]]
        if devs:
            await self._run(sh.switch, devs, bool(data.get("on")))
        return web.json_response({"ok": bool(devs)})

    async def scenarios_get(self, request):
        path = self.cfg.path_of("smarthome.scenarios_file", "scenarios.yaml")
        return web.json_response({"yaml": path.read_text(encoding="utf-8") if path.exists() else "scenarios: []\n"})

    async def scenarios_set(self, request):
        import yaml
        data = await request.json()
        text = data.get("yaml", "")
        try:
            parsed = yaml.safe_load(text) or {}
            if not isinstance(parsed.get("scenarios", []), list):
                raise ValueError("ожидается список scenarios")
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)
        path = self.cfg.path_of("smarthome.scenarios_file", "scenarios.yaml")
        path.write_text(text, encoding="utf-8")
        sh = self.a.skill("smarthome")
        if sh:
            sh.load_scenarios()
        return web.json_response({"ok": True, "count": len(parsed.get("scenarios", []))})

    # ------------------------------------------------------------- потоки --
    async def face_stream(self, request):
        face = self.a.face
        if face is None:
            raise web.HTTPNotFound(text="лицо не запущено")
        resp = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame",
                                           "Cache-Control": "no-cache"})
        await resp.prepare(request)
        last = None
        try:
            while True:
                face.request_frames(3.0)
                jpg = face.latest_jpeg()
                if jpg is not None and jpg is not last:
                    last = jpg
                    await resp.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                     str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                await asyncio.sleep(0.08)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return resp

    async def ws_events(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.clients.add(ws)
        try:
            async for _ in ws:
                pass
        finally:
            self.clients.discard(ws)
        return ws

    async def ws_baby(self, request):
        bm = self.a.skill("babymonitor")
        if not (bm and bm.active):
            raise web.HTTPForbidden(text="Радионяня выключена. Скажите Стелле: «включи радионяню».")
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        q = self.a.mic.subscribe(maxsize=50)
        try:
            while bm.active and not ws.closed:
                try:
                    frame = await self.loop.run_in_executor(None, lambda: q.get(timeout=0.5))
                except queue.Empty:
                    continue
                await ws.send_bytes(frame.tobytes())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.a.mic.unsubscribe(q)
        return ws

    async def ws_call(self, request):
        """Звонок с телефона (страница /call) или с другой Стеллы: звук в обе стороны."""
        who = request.query.get("from", "телефон")
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        call = LocalCall(self.a)
        self.calls.add(call)
        bus.emit("emotion", name="surprise", intensity=0.9, hold=4)
        bus.emit("info", text=f"Звонок: {who}")
        await self._run(self.a.say, f"Входящий звонок: {who}.", "joy")
        if self.a.listener:  # не отвечаем на голоса из звонка, но «Стелла, положи трубку» работает
            self.a.listener.mute(3600)
            self.a.listener.allow_barge_in = True

        async def sender():
            while call.active and not ws.closed:
                frame = await self.loop.run_in_executor(None, call.next_frame, 0.5)
                if frame is not None:
                    await ws.send_bytes(frame.tobytes())
            await ws.close()

        task = asyncio.create_task(sender())
        try:
            async for msg in ws:
                if not call.active:
                    break
                if msg.type == WSMsgType.BINARY:
                    await self.loop.run_in_executor(None, call.play, msg.data)
        finally:
            call.close()
            self.calls.discard(call)
            task.cancel()
            bus.emit("info", text="")
            if self.a.listener:
                self.a.listener.allow_barge_in = False
                self.a.listener.unmute()
        return ws
