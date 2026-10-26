import asyncio
import datetime as dt
import hmac
import json
import time

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

import os
import re
import uuid

from . import wake, tts, agent, bus, calendar_g, config, db, faces, habits, home, meeting, model3d, notifs, stt, vision

app = FastAPI(title="Stella Core")


async def auth(request: Request, key: str = Query(default="")):
    """Ключ в заголовке Authorization: Bearer ... или ?key= (для SSE/EventSource)."""
    got = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or key
    if not config.API_KEY or not hmac.compare_digest(got, config.API_KEY):
        raise HTTPException(401, "bad key")


Auth = [Depends(auth)]


# ---------- фоновые задачи ----------
async def _loop(fn, every: int):
    while True:
        try:
            await fn()
        except Exception as e:
            print(f"[bg] {fn.__name__}: {e}")
        await asyncio.sleep(every)


async def calendar_reminders():
    if not calendar_g.enabled():
        return
    now = dt.datetime.now(config.TZ)
    evs = await asyncio.to_thread(calendar_g.list_events, now.isoformat(),
                                  (now + dt.timedelta(minutes=12)).isoformat())
    for e in evs:
        if "dateTime" not in str(e.get("start", "")) and "T" not in str(e.get("start", "")):
            continue
        start = calendar_g._parse(e["start"])
        mins = (start - now).total_seconds() / 60
        key = f"cal|{e['id']}|{e['start']}"
        if 0 < mins <= 10 and not db.q("SELECT 1 FROM reminded WHERE key=?", (key,)):
            db.x("INSERT INTO reminded(key,ts) VALUES(?,?)", (key, time.time()))
            txt = f"Через {max(1, round(mins))} мин: {e['title']}"
            bus.publish("hud", text=txt)
            bus.publish("speak", text=txt)


async def habits_tick():
    if home.enabled():
        await habits.record()
        habits.check_suggestions()


def _preload_stt():
    try:
        stt.load()
        print("[stt] whisper loaded")
    except Exception as e:
        print(f"[stt] load failed: {e}")


@app.on_event("startup")
async def startup():
    asyncio.create_task(_loop(calendar_reminders, 60))
    asyncio.create_task(_loop(habits_tick, 60))
    asyncio.create_task(asyncio.to_thread(_preload_stt))


@app.get("/health")
async def health():
    return {"ok": True, "calendar": calendar_g.enabled(), "home": home.enabled(), "tts": tts.enabled()}


# ---------- диалог ----------
class ChatIn(BaseModel):
    text: str
    speak: bool = True


@app.post("/chat", dependencies=Auth)
async def chat(body: ChatIn):
    ans = await agent.ask(body.text)
    bus.publish("hud", text=ans)
    if body.speak:
        bus.publish("speak", text=ans)
    return {"text": ans}


@app.post("/voice", dependencies=Auth)
async def voice(audio: UploadFile = File(...)):
    data = await audio.read()
    suffix = "." + (audio.filename or "a.wav").rsplit(".", 1)[-1]
    text = await asyncio.to_thread(stt.transcribe, data, suffix)
    if not text:
        return {"heard": "", "text": ""}
    ans = await agent.ask(text)
    bus.publish("hud", text=ans)
    bus.publish("speak", text=ans)
    return {"heard": text, "text": ans}


@app.get("/events", dependencies=Auth)
async def events():
    return StreamingResponse(bus.stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- AIUI (OpenAI-совместимый) ----------
@app.post("/v1/chat/completions", dependencies=Auth)
async def openai_compat(request: Request):
    body = await request.json()
    user = next((m for m in reversed(body.get("messages", [])) if m.get("role") == "user"), None)
    content = user.get("content", "") if user else ""
    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    ans = await agent.ask(content)
    base = {"id": f"stella-{int(time.time())}", "created": int(time.time()), "model": "stella"}
    if body.get("stream"):
        async def gen():
            yield "data: " + json.dumps({**base, "object": "chat.completion.chunk", "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": ans}, "finish_reason": None}]}) + "\n\n"
            yield "data: " + json.dumps({**base, "object": "chat.completion.chunk", "choices": [
                {"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return {**base, "object": "chat.completion", "choices": [
        {"index": 0, "message": {"role": "assistant", "content": ans}, "finish_reason": "stop"}]}


# ---------- сообщения и алерты ----------
class NotifIn(BaseModel):
    app: str
    sender: str
    text: str
    key: str = ""      # идентификатор уведомления на телефоне (для ответа)


@app.post("/notify", dependencies=Auth)
async def notify(n: NotifIn):
    return notifs.handle(n.app, n.sender, n.text, n.key)


class AlertIn(BaseModel):
    source: str
    text: str
    speak: bool = False


@app.post("/alert", dependencies=Auth)
async def alert(a: AlertIn):
    line = f"Алерт от {a.source}: {a.text}"
    bus.publish("hud", text=line)
    if a.speak:
        bus.publish("speak", text=line)
    return {"ok": True}


# ---------- зрение ----------
@app.post("/vision/look", dependencies=Auth)
async def vision_look(image: UploadFile = File(...)):
    try:
        ans = await vision.look(await image.read())
    except Exception as e:
        bus.publish("hud", text=f"Зрение не работает: {str(e)[:120]}")
        return {"text": None, "error": str(e)[:200]}
    if ans:
        bus.publish("hud", text=ans)
        bus.publish("speak", text=ans)
    return {"text": ans}


@app.post("/vision/remember", dependencies=Auth)
async def vision_remember(image: UploadFile = File(...)):
    try:
        desc = await vision.remember(await image.read())
    except Exception as e:
        bus.publish("hud", text=f"Память не работает: {str(e)[:120]}")
        return {"description": "", "error": str(e)[:200]}
    bus.publish("hud", text="Запомнила: " + desc)
    bus.publish("speak", text="Запомнила")
    return {"description": desc}


# ---------- лица ----------
@app.post("/faces/identify", dependencies=Auth)
async def faces_identify(image: UploadFile = File(...)):
    data = await image.read()
    bus.publish("scan", text="Сканирую лицо…")
    res = await asyncio.to_thread(faces.identify, data)
    import base64
    bus.publish("photo", image="data:image/jpeg;base64," + base64.b64encode(data).decode(), seconds=3)
    if res["found"]:
        bus.publish("card", name=res["name"], note=res["note"])
    else:
        bus.publish("hud", text="Нет в базе")
    return res


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return FileResponse(__file__.replace("main.py", "admin.html"))


@app.get("/admin/faces", dependencies=Auth)
async def admin_list():
    return [{"id": r["id"], "name": r["name"], "note": r["note"]} for r in db.q("SELECT id,name,note FROM faces")]


@app.post("/admin/faces", dependencies=Auth)
async def admin_add(name: str = Form(...), note: str = Form(""), consent: bool = Form(False),
                    photo: UploadFile = File(...)):
    if not consent:
        raise HTTPException(400, "нужно согласие человека")
    fid = await asyncio.to_thread(faces.add, name, note, await photo.read())
    if fid is None:
        raise HTTPException(422, "на фото не найдено лицо")
    return {"id": fid}


@app.delete("/admin/faces/{fid}", dependencies=Auth)
async def admin_del(fid: int):
    db.x("DELETE FROM faces WHERE id=?", (fid,))
    return {"ok": True}


# ---------- дом ----------
class HomeIn(BaseModel):
    device: str
    action: str
    data: dict | None = None
    confirmed: bool = False


@app.post("/home/act", dependencies=Auth)
async def home_act(h: HomeIn):
    return await home.act(h.device, h.action, h.data, h.confirmed)


# ---------- голосовой ответ ----------
def _to_ogg_opus(name: str) -> str:
    import shutil
    import subprocess
    if name.endswith(".ogg") or not shutil.which("ffmpeg"):
        return name
    src = os.path.join(config.DATA_DIR, "voice", name)
    out = src.rsplit(".", 1)[0] + ".ogg"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-c:a", "libopus", "-b:a", "32k", out])
    return os.path.basename(out) if r.returncode == 0 else name


@app.post("/voice/reply", dependencies=Auth)
async def voice_reply(sender: str = Query(...), audio: UploadFile = File(...)):
    """Очки записали голосовой ответ. Расшифровка идёт на HUD, отправка — после подтверждения."""
    n = notifs.find_recent(sender=sender)
    if not n:
        raise HTTPException(404, "нет сообщения от этого контакта")
    data = await audio.read()
    ext = (audio.filename or "a.wav").rsplit(".", 1)[-1]
    name = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(os.path.join(config.DATA_DIR, "voice"), exist_ok=True)
    with open(os.path.join(config.DATA_DIR, "voice", name), "wb") as f:
        f.write(data)
    text = await asyncio.to_thread(stt.transcribe, data, "." + ext)
    name = await asyncio.to_thread(_to_ogg_opus, name)   # WhatsApp воспроизводит голосовые в ogg/opus
    agent._drafts[sender.lower()] = {"key": n["key"], "app": n["app"], "sender": n["sender"],
                                     "text": text, "audio": f"/voice/files/{name}"}
    msg = f"Голосовое для {n['sender']}: «{text}». Отправить?"
    bus.publish("hud", text=msg)
    bus.publish("speak", text=msg)
    return {"text": text}


@app.get("/voice/files/{name}", dependencies=Auth)
async def voice_file(name: str):
    path = os.path.join(config.DATA_DIR, "voice", os.path.basename(name))
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path)


# ---------- совещание ----------
class MeetIn(BaseModel):
    mode: str = "meeting"
    context: str = ""


@app.post("/meeting/start", dependencies=Auth)
async def meeting_start(m: MeetIn):
    meeting.start(m.mode, m.context)
    return {"ok": True}


@app.post("/meeting/chunk", dependencies=Auth)
async def meeting_chunk(audio: UploadFile = File(...)):
    data = await audio.read()
    ext = (audio.filename or "a.webm").rsplit(".", 1)[-1]
    text = await asyncio.to_thread(stt.transcribe, data, "." + ext)
    if meeting.state["on"] and re.search(r"стел+а.*(заверш|законч|стоп|останов|выключ)", text.lower()):
        summary = await meeting.stop()
        bus.publish("hud", text=summary or "Совещание завершено.")
        bus.publish("speak", text="Совещание завершено.")
        return {"text": text, "stopped": True}
    return {"text": text, "hint": await meeting.chunk(text)}


@app.post("/meeting/stop", dependencies=Auth)
async def meeting_stop():
    return {"summary": await meeting.stop()}


# ---------- 3D ----------
class M3DIn(BaseModel):
    prompt: str


@app.post("/model3d", dependencies=Auth)
async def model3d_make(m: M3DIn):
    spec = await model3d.generate(m.prompt)
    bus.publish("model3d", spec=spec)
    return spec


# ---------- клиент для очков (HUD) ----------
_WEB = os.path.join(os.path.dirname(__file__), "web")


@app.get("/hud", response_class=HTMLResponse)
async def hud():
    return FileResponse(os.path.join(_WEB, "hud.html"))


@app.get("/lab3d", response_class=HTMLResponse)
async def lab3d():
    return FileResponse(os.path.join(_WEB, "lab3d.html"))


# ---------- данные для экранов HUD ----------
@app.get("/api/messages", dependencies=Auth)
async def api_messages():
    return [{"id": r["id"], "app": r["app"], "sender": r["sender"], "text": r["text"], "importance": r["importance"]}
            for r in db.q("SELECT * FROM notifs ORDER BY ts DESC LIMIT 15")]


@app.get("/api/calendar", dependencies=Auth)
async def api_calendar():
    now = dt.datetime.now(config.TZ)
    return await asyncio.to_thread(calendar_g.list_events, now.isoformat(), (now + dt.timedelta(days=2)).isoformat())


@app.get("/api/home", dependencies=Auth)
async def api_home():
    return await home.list_devices()


# ---------- всегда слушаю: обращение «Стелла, ...» ----------
WAKE = re.compile(r"\b(стел+а|стэл+а|стеля|stel+a|stella)\b[\s,.:!?-]*", re.I)
JUNK = re.compile(r"субтитры|продолжение следует|спасибо за просмотр|подписывайтесь", re.I)


@app.post("/voice/listen", dependencies=Auth)
async def voice_listen(audio: UploadFile = File(...), awake: int = Query(0)):
    """Фразы приходят постоянно. Реагируем на обращение по имени или внутри окна диалога (awake=1).
    Остальной разговор сразу отбрасывается и нигде не сохраняется."""
    data = await audio.read()
    ext = (audio.filename or "u.webm").rsplit(".", 1)[-1]
    text = await asyncio.to_thread(stt.transcribe, data, "." + ext)
    if not text or JUNK.search(text):
        return {"handled": False}
    addressed, cmd = wake.split(text)
    if not addressed and not awake:
        return {"handled": False}
    if len(cmd) < 2:
        return {"handled": True, "ack": True}
    ans = await agent.ask(cmd)
    if ans.strip(" .…") == "":
        return {"handled": False}
    bus.publish("hud", text=ans)
    bus.publish("speak", text=ans)
    return {"handled": True, "heard": cmd, "text": ans}


# ---------- голос ElevenLabs ----------
class TTSIn(BaseModel):
    text: str


@app.post("/tts", dependencies=Auth)
async def tts_make(t: TTSIn):
    from fastapi.responses import Response
    if not tts.enabled():
        raise HTTPException(503, "ELEVENLABS_API_KEY не задан")
    try:
        return Response(await tts.synth(t.text), media_type="audio/mpeg")
    except Exception as e:
        print(f"[tts] {e}")
        raise HTTPException(502, str(e)[:200])
