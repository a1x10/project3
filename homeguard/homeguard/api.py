import ipaddress
import json
import time
import urllib.request

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import antivirus, auth, blocklists, bravia, config, db, ha, miio, miot, scanner, telegram, vpn

DEVICE_TYPES = {"computer", "phone", "tv", "router", "speaker", "appliance", "iot", "unknown"}
REASONS = {
    "ads": "Рекламный домен",
    "trackers": "Трекер слежки",
    "malware": "Вредоносный сайт",
    "phishing": "Фишинг — попытка украсть данные",
    "adult": "Контент для взрослых",
    "doh": "Обход DNS-фильтра (DoH)",
    "suspicious_tld": "Подозрительная доменная зона",
}

app = FastAPI(title="HomeGuard", docs_url=None, redoc_url=None, openapi_url=None)
COOKIE = "hg_session"


def _is_panel_host(host: str) -> bool:
    """Панель открывают по IP или localhost; любое другое имя в Host — это перехваченный заблокированный сайт."""
    host = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0].lstrip("[")
    if host in ("localhost", "") or host.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _blocked_page(domain: str, reason: str | None) -> HTMLResponse:
    html = (config.WEB_DIR / "blocked.html").read_text(encoding="utf-8")
    safe = domain.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    html = html.replace("{{domain}}", safe).replace("{{reason}}", REASONS.get(reason or "", "Небезопасный сайт"))
    return HTMLResponse(html, status_code=403)


DEV_USER = {"tg_id": 0, "name": "dev", "username": None, "role": "owner", "kind": "web"}


def _session_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(COOKIE)


def _public(path: str) -> bool:
    return not path.startswith("/api/") or path.startswith("/api/auth/")


@app.middleware("http")
async def block_page_middleware(request: Request, call_next):
    host = request.headers.get("host", "")
    if not _is_panel_host(host):
        domain = host.rsplit(":", 1)[0].lower()
        _, reason = blocklists.check(domain, db.get_setting("level"))
        if request.url.path.startswith("/static/"):
            return await call_next(request)
        return _blocked_page(domain, reason)
    user = auth.user_by_token(_session_token(request)) if config.AUTH else DEV_USER
    request.state.user = user
    if user is None and not _public(request.url.path):
        return JSONResponse({"detail": "Нужно войти через Telegram"}, status_code=401)
    return await call_next(request)


def _owner(request: Request) -> dict:
    u = request.state.user
    if not u or u["role"] != "owner":
        raise HTTPException(403, "Только для владельца сети")
    return u


# ---------- Вход через Telegram ----------

@app.get("/api/auth/state")
def auth_state(request: Request):
    has_owner = auth.owner() is not None
    return {"bot_configured": bool(telegram.token()), "bot_username": telegram.username() if telegram.token() else "",
            "has_owner": has_owner, "user": request.state.user, "auth": config.AUTH}


class BotIn(BaseModel):
    token: str


@app.put("/api/auth/bot")
def auth_set_bot(body: BotIn, request: Request):
    # первый запуск: пока нет владельца, бота может настроить любой в сети (как настройка нового роутера)
    if auth.owner() is not None:
        _owner(request)
    try:
        name = telegram.configure(body.token)
    except telegram.TgError as e:
        raise HTTPException(400, str(e))
    return {"bot_username": name}


class LoginStart(BaseModel):
    kind: str = "web"


@app.post("/api/auth/start")
def auth_start(body: LoginStart):
    if not telegram.token():
        raise HTTPException(400, "Сначала подключи Telegram-бота")
    try:
        nonce = auth.start_login(body.kind)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return {"nonce": nonce, "link": telegram.deep_link(nonce), "bot": telegram.username()}


@app.get("/api/auth/poll")
def auth_poll(nonce: str, response: Response):
    status, token = auth.poll(nonce)
    out = {"status": status}
    if token:
        rows = db.query("SELECT kind FROM login_requests WHERE nonce = ?", (nonce,))
        if rows and rows[0]["kind"] == "app":
            out["token"] = token
        else:
            response.set_cookie(COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True, samesite="lax")
    return out


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    tok = _session_token(request)
    if tok:
        auth.logout(tok)
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/users")
def users_list(request: Request):
    _owner(request)
    return auth.list_users()


class RoleIn(BaseModel):
    role: str


@app.put("/api/users/{tg_id}")
def users_role(tg_id: int, body: RoleIn, request: Request):
    _owner(request)
    try:
        auth.set_role(tg_id, body.role)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/users/{tg_id}")
def users_delete(tg_id: int, request: Request):
    _owner(request)
    try:
        auth.remove_user(tg_id)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ---------- Антивирус ----------

class UrlIn(BaseModel):
    url: str


@app.post("/api/av/url")
def av_url(body: UrlIn):
    if len(body.url) > 4000:
        raise HTTPException(400, "Слишком длинная ссылка")
    return antivirus.check_url(body.url)


@app.post("/api/av/file")
async def av_file(request: Request):
    """Тело запроса — сам файл; имя — в заголовке X-Filename (URL-encoded)."""
    from urllib.parse import unquote
    name = unquote(request.headers.get("x-filename", "file"))[:200] or "file"
    size = int(request.headers.get("content-length") or 0)
    if size > config.AV_MAX_FILE:
        raise HTTPException(413, "Файл больше 32 МБ")
    data = await request.body()
    if len(data) > config.AV_MAX_FILE:
        raise HTTPException(413, "Файл больше 32 МБ")
    import asyncio
    return await asyncio.to_thread(antivirus.check_file, data, name)


@app.get("/api/av/history")
def av_history(limit: int = 50):
    return antivirus.history(min(max(limit, 1), 200))


@app.get("/api/av/keys")
def av_keys():
    return antivirus.keys_status()


class KeysIn(BaseModel):
    gsb: str | None = None
    vt: str | None = None


@app.put("/api/av/keys")
def av_set_keys(body: KeysIn, request: Request):
    _owner(request)
    if body.gsb is not None:
        db.set_setting("gsb_key", body.gsb.strip())
    if body.vt is not None:
        db.set_setting("vt_key", body.vt.strip())
    return antivirus.keys_status()


def _device_view(d: dict) -> dict:
    d["online"] = (time.time() - d["last_seen"]) < config.ONLINE_WINDOW
    d["display_name"] = d["name"] or d["hostname"] or d["ip"] or d["mac"]
    return d


@app.get("/api/devices")
def list_devices():
    rows = [_device_view(d) for d in db.query("SELECT * FROM devices")]
    rows.sort(key=lambda d: (not d["is_self"], not d["online"], d["display_name"].lower()))
    return rows


class DevicePatch(BaseModel):
    name: str | None = None
    type: str | None = None


@app.patch("/api/devices/{mac}")
def patch_device(mac: str, body: DevicePatch):
    if not db.query("SELECT 1 FROM devices WHERE mac = ?", (mac,)):
        raise HTTPException(404, "Устройство не найдено")
    if body.type is not None:
        if body.type not in DEVICE_TYPES:
            raise HTTPException(400, "Неизвестный тип")
        db.execute("UPDATE devices SET type = ? WHERE mac = ?", (body.type, mac))
    if body.name is not None:
        db.execute("UPDATE devices SET name = ? WHERE mac = ?", (body.name.strip() or None, mac))
    return {"ok": True}


@app.post("/api/scan")
async def scan_now():
    return {"found": await scanner.scan_once()}


@app.get("/api/queries")
def list_queries(limit: int = 200, blocked: bool = False, ip: str | None = None, q: str | None = None):
    sql = ("SELECT q.*, COALESCE(d.name, d.hostname, q.client_ip) AS device FROM queries q "
           "LEFT JOIN devices d ON d.ip = q.client_ip WHERE 1=1")
    args: list = []
    if blocked:
        sql += " AND q.action = 'blocked'"
    if ip:
        sql += " AND q.client_ip = ?"
        args.append(ip)
    if q:
        sql += " AND q.domain LIKE ?"
        args.append(f"%{q}%")
    sql += " ORDER BY q.ts DESC LIMIT ?"
    args.append(min(max(limit, 1), 1000))
    rows = db.query(sql, tuple(args))
    for r in rows:
        r["reason_text"] = REASONS.get(r["reason"] or "", "")
    return rows


@app.get("/api/stats")
def stats():
    since = time.time() - 24 * 3600
    total = db.query("SELECT COUNT(*) n FROM queries WHERE ts > ?", (since,))[0]["n"]
    blocked = db.query("SELECT COUNT(*) n FROM queries WHERE ts > ? AND action='blocked'", (since,))[0]["n"]
    threats = db.query("SELECT COUNT(*) n FROM queries WHERE ts > ? AND action='blocked' "
                       "AND reason IN ('malware','phishing')", (since,))[0]["n"]
    top = db.query("SELECT domain, COUNT(*) n FROM queries WHERE ts > ? AND action='allowed' "
                   "GROUP BY domain ORDER BY n DESC LIMIT 8", (since,))
    top_blocked = db.query("SELECT domain, reason, COUNT(*) n FROM queries WHERE ts > ? AND action='blocked' "
                           "GROUP BY domain ORDER BY n DESC LIMIT 8", (since,))
    devs = db.query("SELECT last_seen FROM devices")
    online = sum((time.time() - d["last_seen"]) < config.ONLINE_WINDOW for d in devs)
    return {"queries_24h": total, "blocked_24h": blocked, "threats_24h": threats,
            "devices_total": len(devs), "devices_online": online,
            "top_domains": top, "top_blocked": top_blocked, "list_sizes": blocklists.counts()}


@app.get("/api/settings")
def get_settings():
    return {"level": db.get_setting("level"),
            "levels": {k: {"title": v["title"], "description": blocklists.LEVEL_DESCRIPTIONS[k]}
                       for k, v in blocklists.LEVELS.items()}}


class SettingsPatch(BaseModel):
    level: str


@app.put("/api/settings")
def put_settings(body: SettingsPatch):
    if body.level not in blocklists.LEVELS:
        raise HTTPException(400, "Неизвестный уровень защиты")
    db.set_setting("level", body.level)
    return {"ok": True}


# ---------- VPN ----------

@app.get("/api/vpn")
def vpn_status():
    return vpn.manager.status()


class ProfileIn(BaseModel):
    name: str
    content: str
    country: str | None = None
    username: str | None = None
    password: str | None = None


@app.post("/api/vpn/profiles")
def vpn_add(body: ProfileIn):
    try:
        return vpn.manager.add_profile(body.name, body.content, body.country, body.username, body.password)
    except vpn.VpnError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/vpn/profiles/{pid}")
def vpn_delete(pid: str):
    try:
        vpn.manager.delete_profile(pid)
    except vpn.VpnError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


class ConnectIn(BaseModel):
    id: str


@app.post("/api/vpn/connect")
def vpn_connect(body: ConnectIn):  # sync-эндпоинт: FastAPI выполнит в потоке, не блокируя loop
    try:
        vpn.manager.connect(body.id)
    except vpn.VpnError as e:
        raise HTTPException(400, str(e))
    return vpn.manager.status()


@app.post("/api/vpn/disconnect")
def vpn_disconnect():
    vpn.manager.disconnect()
    return vpn.manager.status()


class VpnSettings(BaseModel):
    kill_switch: bool


@app.put("/api/vpn/settings")
def vpn_settings(body: VpnSettings):
    vpn.manager.set_kill_switch(body.kill_switch)
    return vpn.manager.status()


@app.get("/api/vpn/ip")
def vpn_public_ip():
    """Внешний IP, который видит интернет (с этой машины)."""
    if config.VPN_DRYRUN:
        return {"ip": None}
    try:
        with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=5) as r:
            return {"ip": json.load(r)["ip"]}
    except (OSError, ValueError, KeyError):
        return {"ip": None}


# ---------- Sony Bravia ----------

def _tv(tid: str) -> bravia.Bravia:
    try:
        return bravia.client(tid, config.BRAVIA_PORT)
    except bravia.BraviaError as e:
        raise HTTPException(404, str(e))


def _tv_call(fn):
    try:
        return fn()
    except bravia.BraviaError as e:
        raise HTTPException(502, str(e))


@app.get("/api/tvs")
def tvs_list():
    return bravia.list_tvs()


class TvIn(BaseModel):
    name: str
    ip: str
    psk: str


@app.post("/api/tvs")
def tvs_add(body: TvIn):
    try:
        return bravia.add_tv(body.name, body.ip, body.psk)
    except bravia.BraviaError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/tvs/{tid}")
def tvs_delete(tid: str):
    bravia.delete_tv(tid)
    return {"ok": True}


@app.get("/api/tvs/{tid}/state")
def tv_state(tid: str):
    tv = _tv(tid)

    def get():
        st = {"power": tv.power()}
        if st["power"]:
            st["audio"] = tv.volume()
            st["playing"] = tv.playing()
        return st
    return _tv_call(get)


@app.get("/api/tvs/{tid}/inputs")
def tv_inputs(tid: str):
    return _tv_call(_tv(tid).inputs)


@app.get("/api/tvs/{tid}/apps")
def tv_apps(tid: str):
    return _tv_call(_tv(tid).apps)


class TvCmd(BaseModel):
    on: bool | None = None
    level: int | None = None
    mute: bool | None = None
    uri: str | None = None
    button: str | None = None


@app.post("/api/tvs/{tid}/{action}")
def tv_command(tid: str, action: str, body: TvCmd):
    tv = _tv(tid)
    if action == "power" and body.on is not None:
        _tv_call(lambda: tv.set_power(body.on))
    elif action == "volume" and body.level is not None:
        _tv_call(lambda: tv.set_volume(body.level))
    elif action == "mute" and body.mute is not None:
        _tv_call(lambda: tv.set_mute(body.mute))
    elif action == "input" and body.uri:
        _tv_call(lambda: tv.set_input(body.uri))
    elif action == "app" and body.uri:
        _tv_call(lambda: tv.launch_app(body.uri))
    elif action == "press" and body.button in bravia.REMOTE_BUTTONS + ["VolumeUp", "VolumeDown", "Mute", "Input", "Netflix"]:
        _tv_call(lambda: tv.press(body.button))
    else:
        raise HTTPException(400, "Неизвестная команда")
    return {"ok": True}


# ---------- Xiaomi (MIoT) ----------

def _home(did: str):
    try:
        return miot.get(did)
    except miot.MiotError as e:
        raise HTTPException(404, str(e))


def _home_call(fn):
    try:
        return fn()
    except miot.MiotError as e:
        raise HTTPException(400, str(e))
    except miio.MiioError as e:
        raise HTTPException(502, str(e))


@app.get("/api/home")
def home_list():
    return miot.list_devices()


class HomeIn(BaseModel):
    name: str
    ip: str
    token: str
    model: str = ""


@app.post("/api/home")
def home_add(body: HomeIn):
    return _home_call(lambda: miot.add_device(body.name, body.ip, body.token, body.model))


@app.delete("/api/home/{did}")
def home_delete(did: str):
    miot.delete_device(did)
    return {"ok": True}


@app.get("/api/home/{did}/spec")
def home_spec(did: str):
    return _home(did)[1]


@app.get("/api/home/{did}/state")
def home_state(did: str):
    dev, spec = _home(did)
    return _home_call(lambda: miot.read_state(dev, spec))


class HomeSet(BaseModel):
    siid: int
    piid: int
    value: bool | int | float | str


@app.post("/api/home/{did}/set")
def home_set(did: str, body: HomeSet):
    dev, spec = _home(did)
    prop = next((p for p in spec["properties"] if p["siid"] == body.siid and p["piid"] == body.piid), None)
    if not prop or not prop["writable"]:
        raise HTTPException(400, "Этот параметр менять нельзя")

    def go():
        dev.set_property(body.siid, body.piid, miot.validate_value(prop, body.value))
    _home_call(go)
    return {"ok": True}


class HomeAction(BaseModel):
    siid: int
    aiid: int


@app.post("/api/home/{did}/action")
def home_action(did: str, body: HomeAction):
    dev, spec = _home(did)
    act = next((a for a in spec["actions"] if a["siid"] == body.siid and a["aiid"] == body.aiid), None)
    if not act or act["args"]:  # действия с аргументами пока не поддерживаем
        raise HTTPException(400, "Неизвестное действие")
    _home_call(lambda: dev.action(body.siid, body.aiid))
    return {"ok": True}


# ---------- Home Assistant / Яндекс Станция ----------

def _ha_call(fn):
    try:
        return fn()
    except ha.HAError as e:
        raise HTTPException(400, str(e))


@app.get("/api/ha")
def ha_status():
    return {"configured": ha.configured(), "url": db.get_setting("ha_url")}  # токен наружу не отдаём


class HAIn(BaseModel):
    url: str
    token: str


@app.put("/api/ha")
def ha_save(body: HAIn):
    _ha_call(lambda: ha.save(body.url, body.token))
    return ha_status()


@app.delete("/api/ha")
def ha_clear():
    ha.clear()
    return ha_status()


@app.get("/api/ha/players")
def ha_players():
    return _ha_call(lambda: ha.HA.current().players())


class PlayerCmd(BaseModel):
    value: bool | float | int | str | None = None


@app.post("/api/ha/players/{entity_id}/{action}")
def ha_player_command(entity_id: str, action: str, body: PlayerCmd):
    def go():
        service, data = ha.build_service(action, entity_id, body.value)
        ha.HA.current().service("media_player", service, data)
    _ha_call(go)
    return {"ok": True}


@app.get("/blocked", response_class=HTMLResponse)
def blocked_preview(domain: str = "blocked-malware.test", reason: str = "malware"):
    return _blocked_page(domain, reason)


@app.get("/")
def index():
    return FileResponse(config.WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=config.WEB_DIR / "static"), name="static")
