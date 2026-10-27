"""Управление Sony Bravia по официальному REST API (Settings → Network → Home network → IP control).

Нужно на телевизоре: Authentication = «Normal and Pre-Shared Key», задан Pre-Shared Key,
для включения из режима ожидания — «Remote start» (и Wi-Fi/Network standby).
"""
import ipaddress
import json
import urllib.error
import urllib.request
import uuid
import time

from . import db


class BraviaError(Exception):
    pass


def check_ip(ip: str) -> str:
    """Только адреса из локальной сети — панель не должна стучаться в интернет от имени пользователя."""
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        raise BraviaError("Некорректный IP-адрес")
    if addr.version != 4 or not (addr.is_private or addr.is_loopback) or addr.is_unspecified:
        raise BraviaError("Нужен IP из локальной сети (например 192.168.x.x)")
    return str(addr)


class Bravia:
    def __init__(self, ip: str, psk: str, port: int = 80, timeout: float = 5.0):
        self.base = f"http://{check_ip(ip)}:{port}"
        self.psk = psk
        self.timeout = timeout
        self._ircc: dict[str, str] | None = None

    def _open(self, path: str, data: bytes, headers: dict) -> bytes:
        req = urllib.request.Request(self.base + path, data=data, headers={"X-Auth-PSK": self.psk, **headers})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise BraviaError("Телевизор отклонил Pre-Shared Key — проверь ключ в настройках ТВ")
            raise BraviaError(f"Телевизор ответил HTTP {e.code}")
        except (OSError, TimeoutError):
            raise BraviaError("Телевизор не отвечает (выключен глубоко или неверный IP)")

    def call(self, service: str, method: str, params=None, version: str = "1.0"):
        body = json.dumps({"method": method, "id": 1, "params": [params] if params is not None else [],
                           "version": version}).encode()
        out = json.loads(self._open(f"/sony/{service}", body, {"Content-Type": "application/json"}))
        if "error" in out:
            code, msg = (out["error"] + [None, ""])[:2] if isinstance(out["error"], list) else (None, str(out["error"]))
            raise BraviaError(f"ТВ: {msg} ({code})")
        return out.get("result", [])

    # ---- состояние ----
    def info(self) -> dict:
        r = self.call("system", "getSystemInformation")[0]
        return {"model": r.get("model"), "name": r.get("name") or r.get("product")}

    def power(self) -> bool:
        return self.call("system", "getPowerStatus")[0].get("status") == "active"

    def set_power(self, on: bool) -> None:
        self.call("system", "setPowerStatus", {"status": bool(on)})

    def volume(self) -> dict:
        for v in self.call("audio", "getVolumeInformation")[0]:
            if v.get("target") == "speaker":
                return {"volume": v["volume"], "mute": v["mute"], "min": v["minVolume"], "max": v["maxVolume"]}
        raise BraviaError("ТВ не вернул громкость динамиков")

    def set_volume(self, level: int) -> None:
        self.call("audio", "setAudioVolume", {"target": "speaker", "volume": str(max(0, min(100, int(level))))})

    def set_mute(self, mute: bool) -> None:
        self.call("audio", "setAudioMute", {"status": bool(mute)})

    def inputs(self) -> list[dict]:
        res = self.call("avContent", "getCurrentExternalInputsStatus", version="1.1")[0]
        return [{"uri": i["uri"], "title": i.get("title") or i["uri"], "connected": i.get("connection", False)}
                for i in res]

    def set_input(self, uri: str) -> None:
        self.call("avContent", "setPlayContent", {"uri": uri})

    def apps(self) -> list[dict]:
        return [{"uri": a["uri"], "title": a["title"]} for a in self.call("appControl", "getApplicationList")[0]]

    def launch_app(self, uri: str) -> None:
        self.call("appControl", "setActiveApp", {"uri": uri})

    def playing(self) -> dict | None:
        try:
            r = self.call("avContent", "getPlayingContentInfo")[0]
            return {"title": r.get("title") or r.get("programTitle"), "source": r.get("source"), "uri": r.get("uri")}
        except BraviaError:
            return None  # в режиме домашнего экрана/ожидания метод возвращает ошибку

    # ---- пульт (IRCC) ----
    def remote_codes(self) -> dict[str, str]:
        if self._ircc is None:
            res = self.call("system", "getRemoteControllerInfo")[1]
            self._ircc = {c["name"]: c["value"] for c in res}
        return self._ircc

    def press(self, button: str) -> None:
        codes = self.remote_codes()
        if button not in codes:
            raise BraviaError(f"У этого ТВ нет кнопки {button}")
        envelope = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                    '<u:X_SendIRCC xmlns:u="urn:schemas-sony-com:service:IRCC:1"><IRCCCode>'
                    f'{codes[button]}</IRCCCode></u:X_SendIRCC></s:Body></s:Envelope>').encode()
        self._open("/sony/IRCC", envelope, {
            "Content-Type": 'text/xml; charset=UTF-8',
            "SOAPACTION": '"urn:schemas-sony-com:service:IRCC:1#X_SendIRCC"'})


# Кнопки пульта, которые показываем в панели (имена из getRemoteControllerInfo).
REMOTE_BUTTONS = ["Up", "Down", "Left", "Right", "Confirm", "Return", "Home", "Options",
                  "Play", "Pause", "Prev", "Next", "ChannelUp", "ChannelDown"]


# ---------- хранилище ----------

def add_tv(name: str, ip: str, psk: str) -> dict:
    name = name.strip()[:60]
    if not name or not psk.strip():
        raise BraviaError("Нужны название и Pre-Shared Key")
    ip = check_ip(ip)
    tid = uuid.uuid4().hex[:8]
    db.execute("INSERT INTO tvs VALUES (?,?,?,?,?)", (tid, name, ip, psk.strip(), time.time()))
    return {"id": tid, "name": name, "ip": ip}


def list_tvs() -> list[dict]:
    return db.query("SELECT id, name, ip FROM tvs ORDER BY created")  # psk наружу не отдаём


def delete_tv(tid: str) -> None:
    db.execute("DELETE FROM tvs WHERE id = ?", (tid,))


def client(tid: str, port: int = 80) -> Bravia:
    rows = db.query("SELECT ip, psk FROM tvs WHERE id = ?", (tid,))
    if not rows:
        raise BraviaError("Телевизор не найден")
    return Bravia(rows[0]["ip"], rows[0]["psk"], port=port)
