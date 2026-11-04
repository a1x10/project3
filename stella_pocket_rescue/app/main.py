import asyncio
import hmac
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, config, diagnostics, mode, stations
from .db import Database
from .triage import PRIORITY_RANK, assess, fallback_reply, first_aid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("stella")

STATIC = Path(__file__).parent / "static"
SESSION_RE = re.compile(r"^[0-9a-f]{32}$")
STATUSES = ("new", "assigned", "resolved")
PORTAL_HOSTS = {config.PORTAL_HOST, "stella.rescue", "localhost", "127.0.0.1", "testserver"}
AI_TEST_SAMPLE = "Нас двое, у мамы кровь из ноги, мы на 3 этаже, дом 12 по улице Абая"
HELLO_CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS",
              "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Private-Network": "true",
              "Access-Control-Max-Age": "600"}
FALLBACK_PAGE = ("<!doctype html><html lang=\"ru\"><meta charset=\"utf-8\">"
                 "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                 "<title>Stella Pocket</title><body style=\"font:18px sans-serif;padding:24px\">"
                 "<h1>Stella Pocket</h1><p>Страница временно недоступна. Обновите её через минуту.</p>"
                 "</body></html>")
VALIDATION_RU = {"missing": "обязательное поле", "string_too_long": "слишком длинный текст",
                 "string_too_short": "пустое значение", "less_than_equal": "вне допустимого диапазона",
                 "greater_than_equal": "вне допустимого диапазона", "finite_number": "должно быть числом",
                 "float_parsing": "должно быть числом", "float_type": "должно быть числом",
                 "json_invalid": "некорректный JSON"}


def _open_db() -> Database:
    try:
        return Database(config.DB_PATH)
    except Exception as exc:
        log.error("база %s недоступна (%s) — работаю в памяти, вызовы не сохранятся", config.DB_PATH, exc)
        return Database(":memory:")


async def _guarded(what: str, action, timeout: float = 15) -> None:
    try:
        await asyncio.wait_for(action(), timeout)
    except Exception as exc:
        log.warning("%s: %r", what, exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("Stella Pocket %s · узел %s", config.VERSION, diagnostics.node_id())
    await _guarded("запуск ИИ", ai.start)
    try:
        yield
    finally:
        await _guarded("остановка ИИ", ai.stop)


app = FastAPI(title="Stella Pocket Rescue", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
db = _open_db()

_pending: set[str] = set()
_busy: set[str] = set()
_pin_failures: dict[str, list[float]] = {}


@app.middleware("http")
async def captive_portal(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":")[0].lower()
    is_ip = bool(re.fullmatch(r"[0-9.]+", host)) or host.startswith("[")
    if host and host not in PORTAL_HOSTS and not is_ip:
        return RedirectResponse(config.PORTAL_URL, status_code=302)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _page(name: str):
    path = STATIC / name
    if path.is_file():
        return FileResponse(path)
    log.error("нет страницы %s", path)
    return HTMLResponse(FALLBACK_PAGE, status_code=503)


@app.get("/", include_in_schema=False)
def index():
    return _page("index.html")


@app.get("/rescuer", include_in_schema=False)
def rescuer_page():
    return _page("rescuer.html")


@app.get("/verify", include_in_schema=False)
def verify_page():
    return _page("verify.html")


@app.get("/generate_204", include_in_schema=False)
@app.get("/gen_204", include_in_schema=False)
@app.get("/hotspot-detect.html", include_in_schema=False)
@app.get("/connecttest.txt", include_in_schema=False)
@app.get("/ncsi.txt", include_in_schema=False)
@app.get("/canonical.html", include_in_schema=False)
def connectivity_check():
    return RedirectResponse(config.PORTAL_URL, status_code=302)


def _active_engine(snap: dict) -> str:
    active = snap.get("active")
    return active if active in ai.ENGINES else "reserve"


@app.get("/api/status")
async def status():
    m = diagnostics.mode_state()
    return {"mode": m["mode"], "source": m.get("source"), "since": m.get("since"), "note": m.get("note"),
            "ai": _active_engine(diagnostics.ai_snapshot())}


@app.get("/api/health")
async def health():
    snap = diagnostics.ai_snapshot()
    local = snap.get("local") if isinstance(snap.get("local"), dict) else {}
    return {"ok": True, "llm": local.get("state") == "ok", "ai": _active_engine(snap), "time": time.time()}


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


def _client_ip(request: Request) -> str | None:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


class DeviceInfo(BaseModel):
    ua: str | None = Field(default=None, max_length=400)
    platform: str | None = Field(default=None, max_length=80)
    lang: str | None = Field(default=None, max_length=40)
    tz: str | None = Field(default=None, max_length=60)
    screen: str | None = Field(default=None, max_length=20)
    dpr: float | None = None
    cores: int | None = Field(default=None, ge=0, le=256)
    memory_gb: float | None = Field(default=None, ge=0, le=1024)
    touch: bool | None = None
    net_type: str | None = Field(default=None, max_length=20)
    downlink: float | None = Field(default=None, ge=0)
    battery: float | None = Field(default=None, ge=0, le=1)
    charging: bool | None = None


class SessionIn(BaseModel):
    device: DeviceInfo | None = None


_DEVICE_PATTERNS = [
    (re.compile(r"iPhone"), "iPhone"),
    (re.compile(r"iPad"), "iPad"),
    (re.compile(r"(SM-[A-Z0-9]+)"), "Samsung {0}"),
    (re.compile(r"(Pixel \d+[a-zA-Z]*)"), "{0}"),
    (re.compile(r"(Redmi[^;)]*|POCO[^;)]*|Mi \d[^;)]*)"), "Xiaomi {0}"),
    (re.compile(r"(HUAWEI[^;)]*|Honor[^;)]*)"), "{0}"),
    (re.compile(r"(RMX\d+|realme[^;)]*)"), "realme {0}"),
    (re.compile(r"Windows NT"), "ПК Windows"),
    (re.compile(r"Macintosh"), "Mac"),
    (re.compile(r"Android"), "Android-телефон"),
]


def _device_name(ua: str | None) -> str | None:
    if not ua:
        return None
    for rx, tmpl in _DEVICE_PATTERNS:
        m = rx.search(ua)
        if m:
            return tmpl.format(*m.groups()).strip()[:60]
    return "телефон"


@app.post("/api/session")
def new_session(body: SessionIn | None = None, request: Request = None):
    sid = uuid.uuid4().hex
    info = body.device.model_dump() if body and body.device else {}
    db.upsert_incident(
        sid,
        client_ip=_client_ip(request),
        device=_device_name(info.get("ua")),
        device_info=info,
        battery=info.get("battery"),
        charging=None if info.get("charging") is None else int(info["charging"]),
        last_seen=time.time(),
    )
    return {"session_id": sid}


@app.post("/api/chat")
def chat(body: ChatIn, background: BackgroundTasks, request: Request):
    sid = _check_session(body.session_id)
    last = db.last_message(sid, "user")
    if last and time.time() - last["ts"] < config.MIN_SECONDS_BETWEEN_MESSAGES:
        raise HTTPException(429, "Слишком часто. Подождите пару секунд.")

    db.add_message(sid, "user", body.text.strip())
    db.touch(sid, client_ip=_client_ip(request))
    result = update_incident(sid, body.lat, body.lon, body.accuracy)
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
    if lat is not None and lon is not None:
        fields.update(lat=lat, lon=lon, accuracy=accuracy)
    elif result.coords:
        fields.update(lat=result.coords[0], lon=result.coords[1], accuracy=None)
    incident = db.get_incident(sid)
    if incident and incident["status"] == "resolved":
        fields["status"] = "new"
    db.upsert_incident(sid, **fields)
    return result


async def _ai_reply(history: list[dict], result) -> tuple[str, str]:
    try:
        text, engine = await asyncio.wait_for(ai.reply(history, result), config.REPLY_DEADLINE + 15)
    except Exception as exc:
        log.warning("ИИ не ответил, отвечаю по правилам: %r", exc)
        return fallback_reply(result), "reserve"
    if not isinstance(text, str) or not text.strip():
        return fallback_reply(result), "reserve"
    return text.strip(), engine if engine in ai.ENGINES else "reserve"


async def dispatcher_reply(sid: str):
    if sid in _pending:
        return
    _pending.add(sid)
    try:
        for _ in range(3):
            answered = db.last_message(sid, "user")
            if not answered:
                break
            history = db.messages(sid)
            result = assess([m["text"] for m in history if m["role"] == "user"])
            text, engine = await _ai_reply(history, result)
            db.add_message(sid, "assistant", text, engine=engine)
            latest = db.last_message(sid, "user")
            if not latest or latest["id"] == answered["id"]:
                break
    except Exception as exc:
        log.error("ответ диспетчера для %s не записан: %r", sid, exc)
    finally:
        _pending.discard(sid)


class Heartbeat(BaseModel):
    battery: float | None = Field(default=None, ge=0, le=1)
    charging: bool | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)


@app.get("/api/messages")
def messages(session_id: str, after: int = 0, after_broadcast: int = 0):
    sid = _check_session(session_id)
    if db.get_incident(sid):
        db.touch(sid)
    return {
        "messages": db.messages(sid, after),
        "typing": sid in _pending,
        "broadcasts": db.broadcasts(after_broadcast),
    }


@app.post("/api/heartbeat")
def heartbeat(body: Heartbeat, request: Request, session_id: str):
    sid = _check_session(session_id)
    if not db.get_incident(sid):
        raise HTTPException(404, "unknown session")
    fields = {"client_ip": _client_ip(request)}
    if body.battery is not None:
        fields["battery"] = body.battery
    if body.charging is not None:
        fields["charging"] = int(body.charging)
    if body.lat is not None and body.lon is not None:
        fields.update(lat=body.lat, lon=body.lon, accuracy=body.accuracy)
    db.touch(sid, **fields)
    return {"ok": True}


def rescuer(request: Request):
    ip = _client_ip(request) or "?"
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


def _enrich(items: list[dict], by_ip: dict[str, dict]) -> None:
    now = time.time()
    for it in items:
        it["waiting_min"] = round((now - it["created"]) / 60, 1)
        it["online"] = bool(it.get("last_seen") and now - it["last_seen"] <= config.ONLINE_WINDOW)
        st = by_ip.get(it.get("client_ip") or "")
        if st:
            it["mac"] = st["mac"]
            it["signal"] = st["signal"]
            it["proximity"] = st["proximity"]
            it["distance_m"] = st["distance_m"]
            it["link_kb"] = st["kb"]
        else:
            it.setdefault("signal", None)
            it.setdefault("proximity", None)
            it.setdefault("distance_m", None)


@app.get("/api/rescuer/incidents", dependencies=[Depends(rescuer)])
def list_incidents():
    items = db.incidents()
    _enrich(items, stations.by_ip(stations.connected()))
    items.sort(key=lambda it: (
        it["status"] == "resolved",
        PRIORITY_RANK[it["priority"]],
        -it["score"],
        it["created"],
    ))
    counts = {p: sum(1 for i in items if i["priority"] == p and i["status"] != "resolved")
              for p in PRIORITY_RANK}
    return {"incidents": items, "counts": counts,
            "hub": {**diagnostics.hub_location(), "mode": config.HUB_MODE},
            "server": stations.uptime()}


@app.get("/api/rescuer/connections", dependencies=[Depends(rescuer)])
def connections():
    conns = stations.connected()
    incidents = {i.get("client_ip"): i for i in db.incidents() if i.get("client_ip")}
    now = time.time()
    for c in conns:
        inc = incidents.get(c["ip"])
        if inc:
            c["incident_id"] = inc["id"]
            c["priority"] = inc["priority"]
            c["device"] = inc.get("device")
            c["battery"] = inc.get("battery")
            c["people"] = inc.get("people")
            c["online"] = bool(inc.get("last_seen") and now - inc["last_seen"] <= config.ONLINE_WINDOW)
    return {"connections": conns, "server": stations.uptime(),
            "hub": {"iface": config.WLAN_IFACE, "ip": config.PORTAL_HOST, "ssid": config.SSID}}


@app.get("/api/rescuer/incidents/{incident_id}/messages", dependencies=[Depends(rescuer)])
def incident_messages(incident_id: int):
    incident = db.get_incident_by_id(incident_id) or _not_found()
    _enrich([incident], stations.by_ip(stations.connected()))
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
    incident = db.get_incident_by_id(incident_id) or _not_found()
    db.add_message(incident["session_id"], "rescuer", body.text.strip())
    return {"ok": True}


class ModeIn(BaseModel):
    mode: str
    source: str = "manual"
    note: str | None = Field(default=None, max_length=200)


@app.post("/api/rescuer/mode", dependencies=[Depends(rescuer)])
def set_mode(body: ModeIn):
    if body.mode not in (mode.STANDBY, mode.EMERGENCY):
        raise HTTPException(400, "mode must be standby or emergency")
    if body.source not in mode.SOURCES:
        raise HTTPException(400, f"source must be one of {mode.SOURCES}")
    before = mode.read()["mode"]
    m = mode.write(body.mode, body.source if body.mode == mode.EMERGENCY else None, body.note)
    if body.mode == mode.EMERGENCY and before != mode.EMERGENCY:
        text = ("УЧЕБНАЯ ТРЕВОГА. " if body.source == "drill" else "") + \
               "Режим ЧС: землетрясение. Сохраняйте спокойствие. Опишите, где вы и есть ли раненые."
        db.add_broadcast(text)
    return m


@app.post("/api/rescuer/broadcast", dependencies=[Depends(rescuer)])
def broadcast(body: TextIn):
    return {"id": db.add_broadcast(body.text.strip())}


@app.get("/api/rescuer/ai", dependencies=[Depends(rescuer)])
async def rescuer_ai():
    return diagnostics.json_safe({
        "ai": diagnostics.ai_snapshot(),
        "power": diagnostics.read_json(config.POWER_FILE),
        "hw": diagnostics.read_json(config.HW_STATE_FILE),
    })


@app.post("/api/rescuer/ai/probe", dependencies=[Depends(rescuer)])
async def rescuer_ai_probe():
    try:
        snap = await asyncio.wait_for(ai.probe_now(), 20)
    except Exception as exc:
        log.warning("проверка ИИ не завершилась: %r", exc)
        return diagnostics.json_safe({"ai": diagnostics.ai_snapshot(),
                                      "error": "Проверка ИИ не завершилась, показано последнее состояние"})
    return diagnostics.json_safe({"ai": snap if isinstance(snap, dict) else diagnostics.ai_snapshot()})


@app.options("/api/verify/hello", include_in_schema=False)
def verify_hello_preflight():
    return Response(status_code=204, headers=HELLO_CORS)


@app.get("/api/verify/hello")
def verify_hello(response: Response):
    response.headers.update(HELLO_CORS)
    return {
        "node": diagnostics.node_id(),
        "name": "Stella Pocket",
        "version": config.VERSION,
        "ssid": config.SSID,
        "portal": config.PORTAL_URL,
        "uptime_s": diagnostics.uptime_s(),
        "time": time.time(),
        "mode": diagnostics.mode_state()["mode"],
    }


@app.get("/api/verify/report", dependencies=[Depends(rescuer)])
async def verify_report():
    return await diagnostics.run(db)


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    label: str | None = Field(default=None, max_length=80)


@app.post("/api/verify/location", dependencies=[Depends(rescuer)])
def set_location(body: LocationIn):
    try:
        hub = diagnostics.save_hub(body.lat, body.lon, body.label)
    except (OSError, ValueError) as exc:
        log.error("координаты коробки не сохранены: %r", exc)
        raise HTTPException(500, "Не удалось сохранить координаты коробки")
    return {"hub": hub}


@app.delete("/api/verify/location", dependencies=[Depends(rescuer)])
def clear_location():
    try:
        hub = diagnostics.clear_hub()
    except OSError as exc:
        log.error("координаты коробки не удалены: %r", exc)
        raise HTTPException(500, "Не удалось сбросить координаты коробки")
    return {"hub": hub}


class AiTestIn(BaseModel):
    text: str | None = Field(default=None, max_length=300)


@app.post("/api/verify/ai-test", dependencies=[Depends(rescuer)])
async def verify_ai_test(body: AiTestIn | None = None):
    text = ((body.text if body else None) or "").strip() or AI_TEST_SAMPLE
    if "ai-test" in _busy:
        raise HTTPException(429, "Проверка ИИ уже идёт, подождите")
    _busy.add("ai-test")
    try:
        result = await asyncio.wait_for(ai.self_test(text), config.REPLY_DEADLINE + 15)
    except asyncio.TimeoutError:
        raise HTTPException(504, "ИИ не ответил вовремя")
    except Exception as exc:
        log.warning("самопроверка ИИ упала: %r", exc)
        raise HTTPException(502, "Самопроверка ИИ не удалась")
    finally:
        _busy.discard("ai-test")
    if not isinstance(result, dict):
        raise HTTPException(502, "ИИ вернул некорректный ответ")
    return diagnostics.json_safe(result)


def _not_found():
    raise HTTPException(404, "not found")


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


def _validation_message(errors: list) -> str:
    if not errors:
        return "Неверные данные"
    first = errors[0] if isinstance(errors[0], dict) else {}
    field = ".".join(str(p) for p in first.get("loc", ()) if p != "body") or "запрос"
    return f"Неверные данные: {field} — {VALIDATION_RU.get(first.get('type'), 'неверное значение')}"


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errors = exc.errors()
    detail = diagnostics.json_safe(jsonable_encoder(errors))
    return JSONResponse({"error": _validation_message(errors), "detail": detail}, status_code=422)


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception):
    log.exception("ошибка на %s %s", request.method, request.url.path)
    return JSONResponse({"error": "Внутренняя ошибка сервера"}, status_code=500)
