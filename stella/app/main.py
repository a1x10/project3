import asyncio
import datetime as dt
import hmac
import json
import time

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from . import agent, bus, calendar_g, config, db, faces, habits, home, notifs, stt, vision

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


@app.on_event("startup")
async def startup():
    asyncio.create_task(_loop(calendar_reminders, 60))
    asyncio.create_task(_loop(habits_tick, 60))


@app.get("/health")
async def health():
    return {"ok": True, "calendar": calendar_g.enabled(), "home": home.enabled()}


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
    ans = await vision.look(await image.read())
    if ans:
        bus.publish("hud", text=ans)
    return {"text": ans}


@app.post("/vision/remember", dependencies=Auth)
async def vision_remember(image: UploadFile = File(...)):
    desc = await vision.remember(await image.read())
    bus.publish("hud", text="Запомнила: " + desc)
    return {"description": desc}


# ---------- лица ----------
@app.post("/faces/identify", dependencies=Auth)
async def faces_identify(image: UploadFile = File(...)):
    data = await image.read()
    bus.publish("scan", text="Сканирую лицо…")
    res = await asyncio.to_thread(faces.identify, data)
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
