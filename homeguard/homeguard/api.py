import ipaddress
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import blocklists, config, db, scanner

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

app = FastAPI(title="HomeGuard")


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


@app.middleware("http")
async def block_page_middleware(request: Request, call_next):
    host = request.headers.get("host", "")
    if not _is_panel_host(host):
        domain = host.rsplit(":", 1)[0].lower()
        _, reason = blocklists.check(domain, db.get_setting("level"))
        if request.url.path.startswith("/static/"):
            return await call_next(request)
        return _blocked_page(domain, reason)
    return await call_next(request)


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
    top = db.query("SELECT domain, COUNT(*) n FROM queries WHERE ts > ? AND action='allowed' "
                   "GROUP BY domain ORDER BY n DESC LIMIT 8", (since,))
    top_blocked = db.query("SELECT domain, reason, COUNT(*) n FROM queries WHERE ts > ? AND action='blocked' "
                           "GROUP BY domain ORDER BY n DESC LIMIT 8", (since,))
    devs = db.query("SELECT last_seen FROM devices")
    online = sum((time.time() - d["last_seen"]) < config.ONLINE_WINDOW for d in devs)
    return {"queries_24h": total, "blocked_24h": blocked,
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


@app.get("/blocked", response_class=HTMLResponse)
def blocked_preview(domain: str = "blocked-malware.test", reason: str = "malware"):
    return _blocked_page(domain, reason)


@app.get("/")
def index():
    return FileResponse(config.WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=config.WEB_DIR / "static"), name="static")
