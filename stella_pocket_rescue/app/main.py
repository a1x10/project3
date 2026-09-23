"""Stella Pocket Rescue — бэкенд (FastAPI).

Запуск на устройстве: uvicorn app.main:app --host 127.0.0.1 --port 8000
(снаружи всё проходит через nginx, см. deploy/nginx-stella.conf)
"""
import hmac
import logging
import re
import time
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, llm
from .db import Database
from .triage import PRIORITY_RANK, assess, fallback_reply, first_aid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("stella")

STATIC = Path(__file__).parent / "static"
SESSION_RE = re.compile(r"^[0-9a-f]{32}$")
STATUSES = ("new", "assigned", "resolved")
# Хосты, на которых отдаём портал; любой другой домен -> редирект (captive portal)
PORTAL_HOSTS = {config.PORTAL_HOST, "stella.rescue", "localhost", "127.0.0.1", "testserver"}

app = FastAPI(title="Stella Pocket Rescue", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
db = Database(config.DB_PATH)

_pending: set[str] = set()          # сессии, для которых диспетчер "печатает"
_pin_failures: dict[str, list[float]] = {}


# ---------------------------------------------------------------- captive portal
@app.middleware("http")
async def captive_portal(request: Request, call_next):
    """Телефон при подключении проверяет интернет (connectivitycheck.gstatic.com,
    captive.apple.com, msftconnecttest.com …). DNS отвечает нашим IP на любой домен,
    а здесь мы отвечаем редиректом — ОС понимает, что это портал, и открывает чат."""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host and host not in PORTAL_HOSTS:
        return RedirectResponse(config.PORTAL_URL, status_code=302)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/rescuer", include_in_schema=False)
def rescuer_page():
    return FileResponse(STATIC / "rescuer.html")


# Пути проверки связи, если запрос пришёл прямо на IP портала
@app.get("/generate_204", include_in_schema=False)
@app.get("/gen_204", include_in_schema=False)
@app.get("/hotspot-detect.html", include_in_schema=False)
@app.get("/connecttest.txt", include_in_schema=False)
@app.get("/ncsi.txt", include_in_schema=False)
@app.get("/canonical.html", include_in_schema=False)
def connectivity_check():
    return RedirectResponse(config.PORTAL_URL, status_code=302)


@app.get("/api/health")
async def health():
    return {"ok": True, "llm": await llm.healthy(), "time": time.time()}


# ---------------------------------------------------------------- пострадавшие
class ChatIn(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=config.MAX_MESSAGE_LEN)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)


def _check_session(session_id: str) -> str:
    if not SESSION_RE.match(session_id):
        raise HTTPException(400, "bad session_id")
    return session_id


@app.post("/api/session")
def new_session():
    return {"session_id": uuid.uuid4().hex}


@app.post("/api/chat")
def chat(body: ChatIn, background: BackgroundTasks):
    sid = _check_session(body.session_id)
    last = db.last_message(sid, "user")
    if last and time.time() - last["ts"] < config.MIN_SECONDS_BETWEEN_MESSAGES:
        raise HTTPException(429, "Слишком часто. Подождите пару секунд.")

    db.add_message(sid, "user", body.text.strip())
    result = update_incident(sid, body.lat, body.lon, body.accuracy)

    # Первая помощь выдаётся мгновенно и детерминированно, без ожидания нейросети
    given = {m["text"] for m in db.messages(sid) if m["role"] == "advice"}
    for tip in first_aid(result.tags):
        if tip not in given:
            db.add_message(sid, "advice", tip)

    background.add_task(dispatcher_reply, sid)
    return {"ok": True}


def update_incident(sid: str, lat=None, lon=None, accuracy=None):
    texts = [m["text"] for m in db.messages(sid) if m["role"] == "user"]
    result = assess(texts)
    fields = dict(
        priority=result.priority, score=result.score, tags=result.tags,
        people=result.people, location_text=result.location_text, panic=int(result.panic),
    )
    if lat is not None and lon is not None:       # геолокация браузера (если доступна)
        fields.update(lat=lat, lon=lon, accuracy=accuracy)
    elif result.coords:                           # координаты, присланные текстом
        fields.update(lat=result.coords[0], lon=result.coords[1], accuracy=None)
    incident = db.get_incident(sid)
    if incident and incident["status"] == "resolved":
        fields["status"] = "new"                  # человек снова пишет — вернуть в работу
    db.upsert_incident(sid, **fields)
    return result


async def dispatcher_reply(sid: str):
    """Готовит ответ диспетчера. Если пока модель думала пришли новые сообщения,
    отвечаем ещё раз уже с учётом всего — но не больше трёх кругов."""
    if sid in _pending:
        return
    _pending.add(sid)
    try:
        for _ in range(3):
            answered = db.last_message(sid, "user")
            history = db.messages(sid)
            result = assess([m["text"] for m in history if m["role"] == "user"])
            text = await llm.generate(history, result) or fallback_reply(result)
            db.add_message(sid, "assistant", text)
            if db.last_message(sid, "user")["id"] == answered["id"]:
                break
    finally:
        _pending.discard(sid)


@app.get("/api/messages")
def messages(session_id: str, after: int = 0, after_broadcast: int = 0):
    sid = _check_session(session_id)
    return {
        "messages": db.messages(sid, after),
        "typing": sid in _pending,
        "broadcasts": db.broadcasts(after_broadcast),
    }


# ---------------------------------------------------------------- спасатели
def rescuer(request: Request):
    """PIN из заголовка. Сеть открытая, поэтому после 5 ошибок IP блокируется на 5 минут."""
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
    now = time.time()
    fails = [t for t in _pin_failures.get(ip, []) if now - t < 300]
    if len(fails) >= 5:
        raise HTTPException(429, "Слишком много попыток, подождите 5 минут")
    pin = request.headers.get("x-rescuer-pin", "")
    if not hmac.compare_digest(pin.encode(), config.RESCUER_PIN.encode()):
        _pin_failures[ip] = fails + [now]
        raise HTTPException(401, "Неверный PIN")
    _pin_failures.pop(ip, None)


class IncidentPatch(BaseModel):
    status: str | None = None
    note: str | None = Field(default=None, max_length=500)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@app.get("/api/rescuer/incidents", dependencies=[Depends(rescuer)])
def list_incidents():
    now = time.time()
    items = db.incidents()
    for it in items:
        it["waiting_min"] = round((now - it["created"]) / 60, 1)
    items.sort(key=lambda it: (
        it["status"] == "resolved",
        PRIORITY_RANK[it["priority"]],
        -it["score"],
        it["created"],
    ))
    counts = {p: sum(1 for i in items if i["priority"] == p and i["status"] != "resolved")
              for p in PRIORITY_RANK}
    return {"incidents": items, "counts": counts,
            "hub": {"lat": config.HUB_LAT, "lon": config.HUB_LON}}


@app.get("/api/rescuer/incidents/{incident_id}/messages", dependencies=[Depends(rescuer)])
def incident_messages(incident_id: int):
    incident = db.get_incident_by_id(incident_id) or _not_found()
    return {"incident": incident, "messages": db.messages(incident["session_id"])}


@app.patch("/api/rescuer/incidents/{incident_id}", dependencies=[Depends(rescuer)])
def patch_incident(incident_id: int, body: IncidentPatch):
    incident = db.get_incident_by_id(incident_id) or _not_found()
    fields = {}
    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(400, f"status must be one of {STATUSES}")
        fields["status"] = body.status
    if body.note is not None:
        fields["note"] = body.note
    return db.upsert_incident(incident["session_id"], **fields)


@app.post("/api/rescuer/incidents/{incident_id}/reply", dependencies=[Depends(rescuer)])
def rescuer_reply(incident_id: int, body: TextIn):
    """Спасатель пишет пострадавшему напрямую (в чате помечается отдельно)."""
    incident = db.get_incident_by_id(incident_id) or _not_found()
    db.add_message(incident["session_id"], "rescuer", body.text.strip())
    return {"ok": True}


@app.post("/api/rescuer/broadcast", dependencies=[Depends(rescuer)])
def broadcast(body: TextIn):
    """Объявление всем подключённым: пункт сбора, вода, где медики."""
    return {"id": db.add_broadcast(body.text.strip())}


def _not_found():
    raise HTTPException(404, "not found")


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
