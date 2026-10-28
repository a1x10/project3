"""Описания моделей Xiaomi (miot-spec.org) и хранилище устройств.

Панель управляет любым MIoT-устройством по его спецификации: свойства, допустимые значения, действия.
Описание скачивается один раз и кэшируется в data/miot/.
"""
from __future__ import annotations
import json
import re
import time
import urllib.request
import uuid

from . import bravia, config, db, miio

SPEC_HOST = "https://miot-spec.org/miot-spec-v2"

# Русские подписи для самых частых свойств/значений (остальное показываем как в спецификации).
LABELS = {
    "on": "Питание", "status": "Состояние", "mode": "Программа", "fault": "Ошибка",
    "target-temperature": "Температура, °C", "rinsh-times": "Полоскания", "spin-speed": "Отжим, об/мин",
    "drying-time": "Сушка, мин", "door-state": "Дверца", "left-time": "Осталось, мин",
    "physical-controls-locked": "Блокировка от детей", "appoint-time": "Отложенный старт, ч",
    "all-wash-time": "Общее время стирки, мин", "tone-switch": "Звук", "add-clothes": "Можно добавить бельё",
    "stroke": "Этап", "light-switch": "Подсветка", "wash-time": "Время стирки, мин",
    "start-wash": "Старт", "pause": "Пауза", "stop-wash": "Стоп",
}
VALUES = {
    "Off": "Выключена", "Idle": "Ожидание", "Paused": "Пауза", "Busy": "Идёт стирка", "Delay": "Отложенный старт",
    "Closed": "Закрыта", "Open": "Открыта", "None": "Нет", "Cold Water": "Холодная", "Smart": "Авто",
    "Daily Wash": "Ежедневная", "Quick Wash": "Быстрая", "Mite Removal": "Против клещей", "Intensive": "Интенсивная",
    "Delicate Wash": "Деликатная", "Rinse Spin": "Полоскание и отжим", "No Spin": "Без отжима",
    "Weighing": "Взвешивание", "Washing": "Стирка", "Rinsing": "Полоскание", "Spin": "Отжим", "Drying": "Сушка",
    "Door Lock Malfunction": "Не закрывается замок дверцы", "Water Intake Malfunction": "Нет набора воды",
    "Water Draining Malfunction": "Не сливается вода", "Water Level Sensor Malfunction": "Датчик уровня воды",
    "Overflow Malfunction": "Перелив",
}
# Важные для безопасности: только по подтверждению в панели
CONFIRM_ACTIONS = {"start-wash"}


class MiotError(Exception):
    pass


def _fetch_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except (OSError, ValueError) as e:
        raise MiotError("Не удалось загрузить описание модели с miot-spec.org (нужен интернет один раз)") from e


def spec_type_for(model: str) -> str:
    cache = config.MIOT_DIR / "instances.json"
    if not cache.exists() or time.time() - cache.stat().st_mtime > 30 * 86400:
        data = _fetch_json(f"{SPEC_HOST}/instances?status=released")
        best: dict[str, tuple[int, str]] = {}
        for i in data["instances"]:
            if i["model"] not in best or i["version"] > best[i["model"]][0]:
                best[i["model"]] = (i["version"], i["type"])
        config.MIOT_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({m: t for m, (_v, t) in best.items()}), encoding="utf-8")
    types = json.loads(cache.read_text(encoding="utf-8"))
    if model not in types:
        raise MiotError(f"Модель {model} не найдена в базе Xiaomi")
    return types[model]


def load_spec(model: str) -> dict:
    """Упрощённое описание: {"properties": [...], "actions": [...]}."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", model)
    cache = config.MIOT_DIR / f"{safe}.json"
    if cache.exists():
        raw = json.loads(cache.read_text(encoding="utf-8"))
    else:
        raw = _fetch_json(f"{SPEC_HOST}/instance?type={spec_type_for(model)}")
        config.MIOT_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw), encoding="utf-8")
    return simplify(raw)


def _name(urn: str) -> str:
    return urn.split(":")[3]


def simplify(raw: dict) -> dict:
    props, actions = [], []
    for svc in raw.get("services", []):
        sname = _name(svc["type"])
        if sname == "device-information":
            continue
        for p in svc.get("properties", []):
            pname = _name(p["type"])
            access = p.get("access", [])
            vl = p.get("value-list")
            props.append({
                "siid": svc["iid"], "piid": p["iid"], "service": sname, "name": pname,
                "label": LABELS.get(pname) or p.get("description") or pname,
                "format": p["format"], "readable": "read" in access, "writable": "write" in access,
                "unit": p.get("unit") if p.get("unit") not in (None, "none") else None,
                "values": [{"value": v["value"], "label": VALUES.get(v["description"], v["description"])}
                           for v in vl] if vl else None,
                "range": p.get("value-range"),
            })
        for a in svc.get("actions", []):
            aname = _name(a["type"])
            actions.append({"siid": svc["iid"], "aiid": a["iid"], "name": aname, "service": sname,
                            "label": LABELS.get(aname) or a.get("description") or aname,
                            "confirm": aname in CONFIRM_ACTIONS, "args": a.get("in", [])})
    return {"properties": props, "actions": actions}


def validate_value(prop: dict, value):
    """Приводит значение к типу свойства и проверяет по спецификации — произвольное в устройство не уходит."""
    fmt = prop["format"]
    if fmt == "bool":
        if not isinstance(value, bool):
            raise MiotError("Ожидается true/false")
        return value
    if fmt.startswith(("uint", "int")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise MiotError("Ожидается целое число")
        value = int(value)
        if prop["values"] is not None and value not in [v["value"] for v in prop["values"]]:
            raise MiotError("Недопустимое значение для этого параметра")
        if prop["range"]:
            lo, hi = prop["range"][0], prop["range"][1]
            if not lo <= value <= hi:
                raise MiotError(f"Значение должно быть от {lo} до {hi}")
        return value
    raise MiotError("Этот тип параметра менять нельзя")


# ---------- хранилище ----------

def add_device(name: str, ip: str, token: str, model: str = "") -> dict:
    name = name.strip()[:60]
    token = token.strip().lower()
    if not name:
        raise MiotError("Укажи название")
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise MiotError("Токен — это 32 символа 0-9 a-f")
    try:
        ip = bravia.check_ip(ip)
    except bravia.BraviaError as e:
        raise MiotError(str(e))
    try:
        info = miio.MiioDevice(ip, token, port=config.MIIO_PORT).info()
    except miio.MiioError as e:
        raise MiotError(str(e))
    model = (info or {}).get("model") or model.strip()
    if not model:
        raise MiotError("Устройство не сообщило модель — укажи её вручную (например viomi.washer.v20)")
    load_spec(model)  # сразу проверим, что описание есть
    did = uuid.uuid4().hex[:8]
    db.execute("INSERT INTO miot_devices VALUES (?,?,?,?,?,?)", (did, name, ip, token, model, time.time()))
    return {"id": did, "name": name, "ip": ip, "model": model}


def list_devices() -> list[dict]:
    return db.query("SELECT id, name, ip, model FROM miot_devices ORDER BY created")  # токен наружу не отдаём


def delete_device(did: str) -> None:
    db.execute("DELETE FROM miot_devices WHERE id = ?", (did,))


def get(did: str) -> tuple[miio.MiioDevice, dict]:
    rows = db.query("SELECT ip, token, model FROM miot_devices WHERE id = ?", (did,))
    if not rows:
        raise MiotError("Устройство не найдено")
    r = rows[0]
    return miio.MiioDevice(r["ip"], r["token"], port=config.MIIO_PORT), load_spec(r["model"])


def read_state(dev: miio.MiioDevice, spec: dict) -> dict[str, object]:
    wanted = [(p["siid"], p["piid"]) for p in spec["properties"] if p["readable"]]
    got = dev.get_properties(wanted)
    return {f"{s}.{p}": v for (s, p), v in got.items()}
