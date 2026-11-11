"""Сайт настроек /admin: вход, состояние коробки и действия через помощника stella-admin."""
import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import access, config, diagnostics, mode, stations

log = logging.getLogger("stella.admin")
router = APIRouter(prefix="/api/admin")

JOB_RE = re.compile(r"^[0-9a-f]{16}$")
UNITS = ("stella-app", "stella-llm", "stella-hw", "nginx", "hostapd", "dnsmasq", "stella-net", "stella-tunnel")
WEB_ACTIONS = {
    "pin.set", "pin.new", "ai.mode", "ai.model", "power.set", "power.reset", "wifi.ap", "wifi.home", "wifi.sos",
    "remote.off", "remote.test", "tls.sync", "restart", "reboot", "poweroff", "update",
}
CONFIRM = {"wifi.ap", "wifi.home", "remote.off", "reboot", "poweroff", "update"}
LOG_UNITS = ("app", "llm", "hw", "wifi", "dns", "nginx", "install", "home", "tunnel")
DEMO_NOTE = "Тестовая версия на сервере: здесь настройки только показываются, на настоящей коробке кнопка сработает."
HELPER_INFO_TTL = 60
_helper_info: dict = {"ts": 0.0, "data": None}
UPLINK_KINDS = (
    (re.compile(r"^(eth|end|enp|ens|eno)"), "кабель"),
    (re.compile(r"^(usb|rndis|enx)"), "телефон по USB"),
    (re.compile(r"^(wwan|ppp|wwp)"), "4G-модем"),
    (re.compile(r"^(wlan|wlp|wlx)"), "Wi-Fi"),
)


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class ActionIn(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    params: dict = Field(default_factory=dict)
    confirm: bool = False


class DemoIn(BaseModel):
    on: bool
    hours: float = Field(default=config.DEMO_MAX_HOURS, gt=0, le=config.DEMO_MAX_HOURS)


# ---------------------------------------------------------------- помощник с правами root

def run_helper(action: str, params: dict | None = None, timeout: float = 60) -> dict:
    helper = config.ADMIN_HELPER
    if not os.path.isfile(helper):
        raise HTTPException(503, "Помощник настроек не установлен: обновите коробку (sudo stella update)")
    try:
        proc = subprocess.run(["sudo", "-n", helper, action], input=json.dumps(params or {}, ensure_ascii=False),
                              capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise HTTPException(503, "На плате нет sudo: обновите коробку с интернетом (sudo stella update)")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Помощник не ответил вовремя")
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    try:
        data = json.loads(lines[-1]) if lines else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        log.warning("помощник %s: код %s, %s", action, proc.returncode, (proc.stderr or "")[:300])
        if "password" in (proc.stderr or "").lower():
            raise HTTPException(503, "Сайту не разрешен sudo для помощника: обновите коробку (sudo stella update)")
        raise HTTPException(502, "Помощник ответил непонятно")
    if not data.get("ok"):
        raise HTTPException(400, str(data.get("error") or "Действие не выполнено"))
    data.pop("ok", None)
    return data


# ---------------------------------------------------------------- демо для стенда

def demo_state(now: float | None = None) -> dict:
    data = diagnostics.read_json(config.DEMO_FILE) or {}
    until = data.get("until")
    now = now or time.time()
    if not isinstance(until, (int, float)) or until <= now:
        return {"on": False, "until": None}
    until = min(until, now + config.DEMO_MAX_HOURS * 3600)
    return {"on": True, "until": until}


def demo_active() -> bool:
    return demo_state()["on"] and diagnostics.mode_state().get("mode") != mode.EMERGENCY


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


# ---------------------------------------------------------------- состояние

def _env_file(path: Path) -> dict:
    values = {}
    with contextlib.suppress(OSError):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def uplinks() -> list[dict]:
    """Через что у коробки интернет: интерфейсы с маршрутом по умолчанию."""
    found = []
    with contextlib.suppress(OSError):
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            cols = line.split()
            if len(cols) > 7 and cols[1] == "00000000" and cols[7] == "00000000":
                iface = cols[0]
                kind = next((name for rx, name in UPLINK_KINDS if rx.match(iface)), "сеть")
                if iface not in [u["iface"] for u in found]:
                    found.append({"iface": iface, "kind": kind})
    return found


def addresses() -> list[dict]:
    out = []
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        proc = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True, timeout=5)
        for line in proc.stdout.splitlines():
            cols = line.split()
            if len(cols) >= 4 and cols[1] != "lo":
                out.append({"iface": cols[1], "ip": cols[3].split("/")[0]})
    return out


def _hostname() -> str | None:
    try:
        return socket.gethostname()
    except OSError:
        return None


async def helper_info(force: bool = False) -> dict:
    """Сведения от помощника (туннель, HTTPS, пароли SSH). Кэш на минуту: каждый вызов идет через sudo."""
    if config.DEMO:
        return {"demo": True}
    now = time.time()
    if not force and _helper_info["data"] is not None and now - _helper_info["ts"] < HELPER_INFO_TTL:
        return _helper_info["data"]
    try:
        data = await asyncio.to_thread(run_helper, "info", {}, 20)
    except HTTPException as exc:
        data = {"error": exc.detail}
    _helper_info.update(ts=now, data=data)
    return data


async def build_status() -> dict:
    if config.DEMO:
        units = ["active"] + [None] * (len(UNITS) - 1)  # на сервере работает только сам сайт
    else:
        units = await asyncio.gather(*(diagnostics.unit_state(u) for u in UNITS))
    internet = await diagnostics.reach_internet(config.CLOUD_HOST, 443, 4)
    tunnel = _env_file(config.TUNNEL_ENV)
    helper = await helper_info()
    ai = diagnostics.ai_snapshot()
    host = _hostname()
    return diagnostics.json_safe({
        "version": config.VERSION,
        "identity": diagnostics.identity(),
        "mode": diagnostics.mode_state(),
        "units": dict(zip(UNITS, units)),
        "internet": {"ok": internet[0], "ms": internet[1], "error": internet[2]},
        "uplinks": uplinks(),
        "addresses": addresses(),
        "clients": len(stations.connected()),
        "temps": diagnostics._sysfs_temps(),
        "power": diagnostics.read_json(config.POWER_FILE),
        "ai": {"mode": ai.get("mode"), "active": ai.get("active"),
               "cloud": {"configured": bool(config.ANTHROPIC_API_KEY), "model": config.CLOUD_MODEL,
                         "state": (ai.get("cloud") or {}).get("state")},
               "local": {"state": (ai.get("local") or {}).get("state"), "model": (ai.get("local") or {}).get("model")}},
        "settings": {
            "ssid": config.SSID, "channel": config.CHANNEL, "ai_mode": config.AI_MODE, "cloud_model": config.CLOUD_MODEL,
            "key_set": bool(config.ANTHROPIC_API_KEY), "power": os.getenv("STELLA_POWER", "auto"),
            "admin_http_wifi": config.ADMIN_HTTP_WIFI, "remote_chat": config.REMOTE_CHAT,
        },
        "remote": {
            "box_domain": config.BOX_DOMAIN or None, "promo_domain": config.PROMO_DOMAIN or None,
            "server": tunnel.get("STELLA_TUNNEL_HOST") or None, "ssh_forward": tunnel.get("STELLA_TUNNEL_SSH") == "1",
            "local_name": f"{host}.local" if host else None,
        },
        "helper": helper,
        "demo": demo_state(),
        "update": {"repo": config.UPDATE_REPO, "branch": config.UPDATE_BRANCH},
        "test_version": config.DEMO,
    })


# ---------------------------------------------------------------- маршруты

@router.get("/session")
def session(request: Request):
    current = access.read_session(request)
    allowed, reason = access.login_policy(request)
    return {"logged_in": bool(current), "csrf": access.csrf_token(current) if current else None,
            "expires": current["exp"] if current else None, "channel": access.channel(request),
            "https": access.is_https(request), "login_allowed": allowed, "reason": reason,
            "configured": access.password_configured(), "box_domain": config.BOX_DOMAIN or None,
            "demo": config.DEMO}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    access.check_origin(request)
    allowed, reason = access.login_policy(request)
    if not allowed:
        raise HTTPException(403, reason)
    if not access.password_configured():
        raise HTTPException(503, "Пароль администратора еще не задан. На плате: sudo stella admin password new")
    ch = access.channel(request)
    key = f"{ch}:{access.client_ip(request) or '?'}"
    if access.login_failures.blocked(key) or (ch == access.REMOTE and access.remote_login_failures.blocked("all")):
        raise HTTPException(429, "Слишком много неверных попыток. Подождите 15 минут")
    if not access.verify_password(body.password):
        access.login_failures.fail(key)
        if ch == access.REMOTE:
            access.remote_login_failures.fail("all")
        raise HTTPException(401, "Неверный пароль")
    access.login_failures.clear(key)
    value, ttl, csrf = access.issue_cookie(request)
    response.set_cookie(access.COOKIE, value, max_age=ttl, path="/", httponly=True, samesite="strict",
                        secure=access.is_https(request))
    log.info("вход администратора: канал %s", ch)
    return {"ok": True, "csrf": csrf, "expires": int(time.time() + ttl)}


@router.post("/logout")
def logout(request: Request, response: Response):
    access.check_origin(request)
    response.delete_cookie(access.COOKIE, path="/", httponly=True, samesite="strict",
                           secure=access.is_https(request))
    return {"ok": True}


@router.get("/status", dependencies=[Depends(access.require_admin)])
async def status():
    return await build_status()


@router.post("/action", dependencies=[Depends(access.require_admin_write)])
def action(body: ActionIn, request: Request):
    if body.action not in WEB_ACTIONS:
        raise HTTPException(400, "Это действие с сайта недоступно")
    if body.action in CONFIRM and not body.confirm:
        raise HTTPException(409, "Нужно подтверждение")
    if config.DEMO:
        return {"demo": True, "message": DEMO_NOTE, "text": DEMO_NOTE if body.action == "remote.test" else None}
    log.info("настройки: %s (канал %s)", body.action, access.channel(request))
    _helper_info["data"] = None
    return run_helper(body.action, body.params, timeout=60)


@router.get("/jobs/{job_id}", dependencies=[Depends(access.require_admin)])
def job(job_id: str):
    if not JOB_RE.match(job_id):
        raise HTTPException(404, "Нет такой задачи")
    state = diagnostics.read_json(config.JOBS_DIR / f"{job_id}.state")
    if not state:
        raise HTTPException(404, "Нет такой задачи")
    text = ""
    with contextlib.suppress(OSError):
        with open(config.JOBS_DIR / f"{job_id}.log", "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(fh.tell() - 6000, 0))
            text = fh.read().decode("utf-8", "replace")
    return diagnostics.json_safe({"job": job_id, **state, "log": text})


@router.get("/logs", dependencies=[Depends(access.require_admin)])
def logs(unit: str = "app"):
    if unit not in LOG_UNITS:
        raise HTTPException(400, "Нет такого журнала")
    if config.DEMO:
        return {"text": "Тестовая версия на сервере: журналы есть только на настоящей коробке."}
    return run_helper("logs", {"unit": unit}, timeout=40)


@router.post("/demo", dependencies=[Depends(access.require_admin_write)])
def demo(body: DemoIn):
    if body.on:
        if diagnostics.mode_state().get("mode") == mode.EMERGENCY:
            raise HTTPException(409, "Включен режим ЧС: демо сейчас нельзя")
        _write_json(config.DEMO_FILE, {"until": time.time() + body.hours * 3600, "by": "web"})
    else:
        with contextlib.suppress(FileNotFoundError):
            config.DEMO_FILE.unlink()
    return demo_state()
