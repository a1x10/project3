"""Клиент REST API Home Assistant: колонки (в т. ч. Яндекс Станция через интеграцию YandexStation)."""
from __future__ import annotations
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import db

ENTITY_RE = re.compile(r"^media_player\.[a-z0-9_]+$")
YANDEX_HINTS = ("yandex", "яндекс", "станция", "station", "алиса", "alice")


class HAError(Exception):
    pass


def normalize_url(url: str) -> str:
    """Принимаем только адреса из домашней сети: панель не должна ходить в интернет от имени пользователя."""
    url = url.strip().rstrip("/")
    if not re.match(r"^https?://", url):
        url = "http://" + url
    u = urllib.parse.urlparse(url)
    host = u.hostname or ""
    try:
        addr = ipaddress.ip_address(host)
        ok = addr.is_private or addr.is_loopback
    except ValueError:
        ok = host.endswith((".local", ".lan", ".home", ".internal")) or ("." not in host and host != "")
    if not ok:
        raise HAError("Адрес Home Assistant должен быть из локальной сети (192.168.x.x, homeassistant.local…)")
    return f"{u.scheme}://{u.netloc}"


def configured() -> bool:
    return bool(db.get_setting("ha_url") and db.get_setting("ha_token"))


def save(url: str, token: str) -> None:
    token = token.strip()
    if len(token) < 20:
        raise HAError("Это не похоже на долгоживущий токен Home Assistant")
    url = normalize_url(url)
    HA(url, token).ping()  # сохраняем только рабочие настройки
    db.set_setting("ha_url", url)
    db.set_setting("ha_token", token)


def clear() -> None:
    db.set_setting("ha_url", "")
    db.set_setting("ha_token", "")


class HA:
    def __init__(self, url: str, token: str, timeout: float = 8.0):
        self.url, self.token, self.timeout = url, token, timeout

    @classmethod
    def current(cls) -> "HA":
        if not configured():
            raise HAError("Home Assistant не подключён")
        return cls(db.get_setting("ha_url"), db.get_setting("ha_token"))

    def _req(self, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise HAError("Home Assistant отклонил токен — создай новый в профиле HA")
            raise HAError(f"Home Assistant ответил HTTP {e.code}")
        except (OSError, ValueError):
            raise HAError("Home Assistant не отвечает — проверь адрес и что он запущен")

    def ping(self) -> None:
        self._req("/api/")

    def players(self) -> list[dict]:
        out = []
        for s in self._req("/api/states"):
            eid = s["entity_id"]
            if not eid.startswith("media_player."):
                continue
            a = s.get("attributes", {})
            name = a.get("friendly_name") or eid
            hay = f"{eid} {name} {a.get('platform', '')} {a.get('device_class', '')}".lower()
            out.append({
                "entity_id": eid, "name": name, "state": s["state"],
                "yandex": any(h in hay for h in YANDEX_HINTS),
                "volume": a.get("volume_level"), "muted": a.get("is_volume_muted"),
                "title": a.get("media_title"), "artist": a.get("media_artist"), "source": a.get("source"),
            })
        out.sort(key=lambda p: (not p["yandex"], p["name"].lower()))
        return out

    def service(self, domain: str, service: str, data: dict) -> None:
        self._req(f"/api/services/{domain}/{service}", data)


# действие панели → (сервис HA, функция сборки данных)
def build_service(action: str, entity_id: str, value=None) -> tuple[str, dict]:
    if not ENTITY_RE.match(entity_id):
        raise HAError("Некорректное имя устройства")
    base = {"entity_id": entity_id}
    simple = {"play": "media_play", "pause": "media_pause", "next": "media_next_track",
              "prev": "media_previous_track", "on": "turn_on", "off": "turn_off", "stop": "media_stop"}
    if action in simple:
        return simple[action], base
    if action == "volume":
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            raise HAError("Громкость — число от 0 до 1")
        return "volume_set", {**base, "volume_level": float(value)}
    if action == "mute":
        if not isinstance(value, bool):
            raise HAError("Ожидается true/false")
        return "volume_mute", {**base, "is_volume_muted": value}
    if action in ("command", "tts"):
        if not isinstance(value, str) or not value.strip() or len(value) > 300:
            raise HAError("Текст команды: от 1 до 300 символов")
        return "play_media", {**base, "media_content_type": "text_command" if action == "command" else "tts",
                              "media_content_id": value.strip()}
    raise HAError("Неизвестное действие")
