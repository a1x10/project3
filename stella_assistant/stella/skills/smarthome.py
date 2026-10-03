"""Умный дом: устройства Яндекса (API умного дома) и Home Assistant (любые бренды),
датчики, сценарии Яндекса и собственные сценарии Стеллы (по фразе, по времени, по датчикам,
при приходе/уходе из дома). Сценарии можно создавать голосом."""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from ..core.events import bus
from ..nlp.numbers import plural
from ..nlp.text import best_match, clean, contains_phrase, norm, similarity
from ..nlp.timeparse import parse_when
from .base import Reply, Skill, intent

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

TYPE_WORDS = [  # (основы слов, типы устройств Яндекса, домены Home Assistant)
    (("свет", "освещени"), ("devices.types.light",), ("light",)),
    (("ламп", "люстр", "светильник", "торшер", "ночник", "гирлянд", "подсветк", "бра", "лент"),
     ("devices.types.light",), ("light",)),
    (("розетк",), ("devices.types.socket",), ("switch",)),
    (("выключател", "реле"), ("devices.types.switch",), ("switch",)),
    (("чайник",), ("devices.types.cooking.kettle",), ("switch", "water_heater")),
    (("кондиционер", "кондей", "сплит"), ("devices.types.thermostat.ac",), ("climate",)),
    (("обогревател", "батаре", "радиатор", "термостат", "отоплени", "теплый пол"), ("devices.types.thermostat",),
     ("climate",)),
    (("пылесос",), ("devices.types.vacuum_cleaner",), ("vacuum",)),
    (("телевизор", "телек", "тв"), ("devices.types.media_device.tv", "devices.types.media_device.tv_box"),
     ("media_player",)),
    (("штор", "занавес", "жалюзи", "рольставн", "ворот"), ("devices.types.openable.curtain", "devices.types.openable"),
     ("cover",)),
    (("увлажнител",), ("devices.types.humidifier",), ("humidifier",)),
    (("очистител",), ("devices.types.purifier",), ("fan",)),
    (("вентилятор",), ("devices.types.ventilation.fan", "devices.types.fan"), ("fan",)),
    (("кофеварк", "кофемашин"), ("devices.types.cooking.coffee_maker",), ("switch",)),
    (("стиральн", "стиралк"), ("devices.types.washing_machine",), ("switch",)),
    (("посудомо",), ("devices.types.dishwasher",), ("switch",)),
    (("колонк", "станци"), ("devices.types.media_device.receiver", "devices.types.smart_speaker"), ("media_player",)),
]
COLORS = {
    "красн": {"h": 0, "s": 100, "v": 100}, "оранжев": {"h": 25, "s": 100, "v": 100}, "желт": {"h": 50, "s": 100, "v": 100},
    "зелен": {"h": 120, "s": 100, "v": 100}, "бирюзов": {"h": 170, "s": 100, "v": 100},
    "голуб": {"h": 195, "s": 100, "v": 100}, "син": {"h": 230, "s": 100, "v": 100},
    "фиолетов": {"h": 275, "s": 100, "v": 100}, "сиренев": {"h": 290, "s": 60, "v": 100},
    "розов": {"h": 320, "s": 70, "v": 100}, "малинов": {"h": 340, "s": 100, "v": 100},
}
COLOR_TEMPS = {"тепл": 2700, "холодн": 6500, "белый": 4500, "бел": 4500, "дневн": 5600, "нейтральн": 4500,
               "мягк": 3400}
SENSOR_WORDS = {"температур": "temperature", "влажност": "humidity", "углекисл": "co2_level", "co2": "co2_level",
                "давлени": "pressure", "освещенност": "illumination", "заряд": "battery_level",
                "мощност": "power", "напряжени": "voltage", "протечк": "water_leak", "движени": "motion",
                "открыт": "open", "закрыт": "open", "дым": "smoke", "газ": "gas"}
UNITS_RU = {"temperature": "градусов", "humidity": "процентов", "co2_level": "ppm", "battery_level": "процентов",
            "pressure": "мм рт. ст.", "illumination": "люкс", "power": "ватт", "voltage": "вольт"}
YA_EVENTS_RU = {"opened": "открыто", "closed": "закрыто", "detected": "есть движение", "not_detected": "движения нет",
                "leak": "протечка!", "dry": "сухо", "high": "высокий уровень", "normal": "в норме"}


@dataclass
class Device:
    id: str
    name: str
    room: str = ""
    type: str = ""
    backend: str = "yandex"
    caps: list = field(default_factory=list)
    props: list = field(default_factory=list)
    domain: str = ""
    state: dict = field(default_factory=dict)
    aliases: list = field(default_factory=list)

    @property
    def label(self):
        return f"{self.name}{' в комнате ' + self.room if self.room else ''}"

    def cap(self, ctype: str, instance: str | None = None):
        for c in self.caps:
            if c.get("type") == ctype and (instance is None or (c.get("state") or {}).get("instance") == instance
                                           or c.get("parameters", {}).get("instance") == instance):
                return c
        return None


class YandexHome:
    BASE = "https://api.iot.yandex.net/v1.0"

    def __init__(self, token, http):
        self.token, self.http = token, http
        self.devices: list[Device] = []
        self.groups: list[dict] = []
        self.scenarios: list[dict] = []
        self.rooms: dict = {}

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def refresh(self):
        r = self.http.get(self.BASE + "/user/info", headers=self._h(), timeout=10)
        r.raise_for_status()
        d = r.json()
        self.rooms = {x["id"]: x["name"] for x in d.get("rooms", [])}
        self.groups = d.get("groups", [])
        self.scenarios = d.get("scenarios", [])
        self.devices = [Device(id=x["id"], name=x["name"], room=self.rooms.get(x.get("room") or "", ""),
                               type=x.get("type", ""), backend="yandex", caps=x.get("capabilities", []),
                               props=x.get("properties", []), aliases=x.get("aliases", [])) for x in d.get("devices", [])]

    def act(self, device_ids: list[str], actions: list[dict]):
        body = {"devices": [{"id": i, "actions": actions} for i in device_ids]}
        r = self.http.post(self.BASE + "/devices/actions", json=body, headers=self._h(), timeout=10)
        r.raise_for_status()
        errors = []
        for dev in r.json().get("devices", []):
            for c in dev.get("capabilities", []):
                res = (c.get("state") or {}).get("action_result", {})
                if res.get("status") == "ERROR":
                    errors.append(res.get("error_message") or res.get("error_code"))
        return errors

    def run_scenario(self, sid: str):
        r = self.http.post(f"{self.BASE}/scenarios/{sid}/actions", headers=self._h(), timeout=10)
        r.raise_for_status()


class HomeAssistant:
    def __init__(self, url, token, http):
        self.url, self.token, self.http = url.rstrip("/"), token, http
        self.devices: list[Device] = []

    def _h(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def refresh(self):
        r = self.http.get(self.url + "/api/states", headers=self._h(), timeout=10)
        r.raise_for_status()
        devs = []
        for st in r.json():
            eid = st["entity_id"]
            domain = eid.split(".")[0]
            if domain not in ("light", "switch", "climate", "vacuum", "media_player", "cover", "fan", "sensor",
                              "binary_sensor", "humidifier", "water_heater", "scene", "script", "input_boolean", "lock"):
                continue
            attrs = st.get("attributes", {})
            devs.append(Device(id=eid, name=attrs.get("friendly_name", eid), backend="ha", domain=domain,
                               state={"state": st.get("state"), **attrs}))
        self.devices = devs

    def call(self, domain: str, service: str, data: dict):
        r = self.http.post(f"{self.url}/api/services/{domain}/{service}", json=data, headers=self._h(), timeout=10)
        r.raise_for_status()


def _on_off(value: bool):
    return {"type": "devices.capabilities.on_off", "state": {"instance": "on", "value": value}}


def _range(instance: str, value: float, relative: bool = False):
    st = {"instance": instance, "value": value}
    if relative:
        st["relative"] = True
    return {"type": "devices.capabilities.range", "state": st}


class SmartHome(Skill):
    name = "smarthome"

    def __init__(self, a):
        super().__init__(a)
        self.ya = YandexHome(self.cfg.get("smarthome.yandex_token"), a.http) if self.cfg.get("smarthome.yandex_token") else None
        ha = self.cfg.get("smarthome.home_assistant") or {}
        self.ha = HomeAssistant(ha["url"], ha["token"], a.http) if ha.get("url") and ha.get("token") else None
        self._last_refresh = 0.0
        self._lock = threading.Lock()
        self.scenarios: list[dict] = []
        self._fired: dict = {}
        self._sensor_state: dict = {}
        self.load_scenarios()

    @property
    def configured(self) -> bool:
        return bool(self.ya or self.ha)

    def start(self):
        self.a.scheduler.every(20, self._check_time_triggers, "scenarios-time")
        if self.configured and any(t.get("sensor") for sc in self.scenarios for t in sc.get("triggers", [])):
            self.a.scheduler.every(float(self.cfg.get("smarthome.poll_seconds", 15)), self._check_sensor_triggers,
                                   "scenarios-sensors", threaded=True)
        bus.on("presence", lambda state, **_: self._presence(state))

    # ------------------------------------------------------------ устройства --
    def devices(self, force: bool = False) -> list[Device]:
        with self._lock:
            if force or time.time() - self._last_refresh > 60:
                for backend in (self.ya, self.ha):
                    if backend:
                        try:
                            backend.refresh()
                        except Exception as e:
                            self.log.warning("умный дом (%s): %s", type(backend).__name__, e)
                self._last_refresh = time.time()
            out = []
            if self.ya:
                out += self.ya.devices
            if self.ha:
                out += self.ha.devices
            return out

    def _rooms(self) -> list[str]:
        rooms = set(d.room for d in self.devices() if d.room)
        return sorted(rooms)

    def find(self, text: str, need_type: bool = False) -> list[Device]:
        """Устройства из фразы: по имени, по типу («свет»), по комнате («в спальне»), «везде»."""
        devs = self.devices()
        if not devs:
            return []
        t = clean(text)
        everywhere = bool(re.search(r"\b(?:везде|во всем доме|во всей квартире|по всему дому|все)\b", t))
        room = None
        for r in self._rooms():
            if contains_phrase(t, r):
                room = r
                break
        best, score = best_match(t, devs, key=lambda d: d.name, threshold=0.7)
        if best and score >= 0.85 and (not room or best.room == room):
            return [best]
        for d in devs:  # синонимы, заданные в приложении Яндекса
            for al in d.aliases:
                if contains_phrase(t, al):
                    return [d]
        for words, ya_types, ha_domains in TYPE_WORDS:
            if any(re.search(rf"\b{w}", t) for w in words):
                cand = [d for d in devs if (d.backend == "yandex" and any(d.type.startswith(x) for x in ya_types)) or
                        (d.backend == "ha" and d.domain in ha_domains and any(re.search(rf"\b{w}", clean(d.name))
                                                                               for w in words + ("свет",)))]
                if not cand and words[0] == "свет":  # розетка/реле, названная «свет»
                    cand = [d for d in devs if "свет" in clean(d.name)]
                if room:
                    cand = [d for d in cand if d.room == room] or [d for d in cand if contains_phrase(t, d.name)]
                elif not everywhere and len(cand) > 1:
                    named = [d for d in cand if similarity(t, d.name) > 0.5]
                    cand = named or cand
                if cand:
                    return cand
        if best:
            return [best]
        return []

    # -------------------------------------------------------------- действия --
    def switch(self, devs: list[Device], on: bool):
        errors = []
        ya_ids = [d.id for d in devs if d.backend == "yandex"]
        if ya_ids:
            errors += self.ya.act(ya_ids, [_on_off(on)])
        for d in devs:
            if d.backend == "ha":
                domain = d.domain if d.domain not in ("sensor", "binary_sensor") else "homeassistant"
                if domain == "cover":
                    self.ha.call("cover", "open_cover" if on else "close_cover", {"entity_id": d.id})
                elif domain == "vacuum":
                    self.ha.call("vacuum", "start" if on else "return_to_base", {"entity_id": d.id})
                elif domain in ("scene", "script"):
                    self.ha.call(domain, "turn_on", {"entity_id": d.id})
                else:
                    self.ha.call(domain, "turn_on" if on else "turn_off", {"entity_id": d.id})
        return errors

    def set_range(self, devs, instance, value, relative=False):
        ya_ids = [d.id for d in devs if d.backend == "yandex" and d.cap("devices.capabilities.range", instance)]
        errors = self.ya.act(ya_ids, [_range(instance, value, relative)]) if ya_ids else []
        for d in devs:
            if d.backend != "ha":
                continue
            if instance == "brightness" and d.domain == "light":
                data = {"entity_id": d.id}
                data["brightness_step_pct" if relative else "brightness_pct"] = value
                self.ha.call("light", "turn_on", data)
            elif instance == "temperature" and d.domain == "climate":
                cur = d.state.get("temperature") or 22
                self.ha.call("climate", "set_temperature",
                             {"entity_id": d.id, "temperature": cur + value if relative else value})
            elif instance == "volume" and d.domain == "media_player":
                self.ha.call("media_player", "volume_up" if value > 0 else "volume_down", {"entity_id": d.id})
        return errors

    # --------------------------------------------------------------- команды --
    def _not_configured(self):
        return Reply("Умный дом не подключён. Укажите токен умного дома Яндекса (smarthome.yandex_token) "
                     "или адрес и токен Home Assistant в настройках.", emotion="sadness", intensity=0.5)

    @intent(r"^(?:включи|выключи|отключи|зажги|погаси|потуши|открой|закрой|запусти|останови|вруби|выруби)\s+(.+)$",
            priority=48)
    def on_off(self, ctx):
        verb = ctx.norm.split()[0]
        what = ctx.group(1)
        if not self.configured:
            if re.search(r"\b(?:свет|ламп\w*|розетк\w*|чайник|кондиционер|пылесос|обогреватель|шторы|люстр\w*)\b", what):
                return self._not_configured()
            return None
        devs = self.find(what)
        if not devs:
            return None
        on = verb in ("включи", "зажги", "открой", "запусти", "вруби")
        try:
            errors = self.switch(devs, on)
        except Exception as e:
            self.log.warning("умный дом: %s", e)
            return Reply("Не получилось — умный дом не отвечает.", emotion="sadness")
        if errors:
            return Reply(f"Устройство ответило ошибкой: {errors[0]}.", emotion="sadness")
        names = devs[0].label if len(devs) == 1 else f"{len(devs)} {plural(len(devs), 'устройство', 'устройства', 'устройств')}"
        done = {"включи": "Включила", "выключи": "Выключила", "отключи": "Отключила", "зажги": "Включила",
                "погаси": "Выключила", "потуши": "Выключила", "открой": "Открываю", "закрой": "Закрываю",
                "запусти": "Запустила", "останови": "Остановила", "вруби": "Включила", "выруби": "Выключила"}[verb]
        return Reply(f"{done}: {names}." if len(devs) > 1 else f"{done} {names}.", emotion="confidence", intensity=0.4)

    @intent(r"\b(?:сделай|поставь|установи|убавь|прибавь|приглуши|увеличь|уменьши)?\s*(?:свет|ламп\w*|люстр\w*|"
            r"яркост\w*|подсветк\w*)\b.*\b(ярче|темнее|тусклее|поярче|потемнее|на (\d+)(?: процент\w*|%)?|"
            r"(\d+) процент\w*|максимум|минимум)", r"^приглуши свет\b", priority=49)
    def brightness(self, ctx):
        if not self.configured:
            return self._not_configured()
        devs = [d for d in self.find(ctx.norm) if d.type.startswith("devices.types.light") or d.domain == "light"]
        if not devs:
            return Reply("Не нашла светильник.", emotion="sadness")
        n = ctx.norm
        m = re.search(r"(\d+)\s*(?:процент\w*|%)?", n)
        if re.search(r"\b(?:ярче|поярче|прибавь|увеличь)\b", n):
            errs = self.set_range(devs, "brightness", 25, relative=True)
        elif re.search(r"\b(?:темнее|тусклее|потемнее|приглуши|убавь|уменьши)\b", n):
            errs = self.set_range(devs, "brightness", -25, relative=True)
        elif "максимум" in n:
            errs = self.set_range(devs, "brightness", 100)
        elif "минимум" in n:
            errs = self.set_range(devs, "brightness", 5)
        elif m:
            errs = self.set_range(devs, "brightness", max(1, min(100, int(m.group(1)))))
        else:
            return None
        return Reply("Готово." if not errs else f"Ошибка: {errs[0]}", emotion="confidence", intensity=0.3)

    @intent(r"\b(?:сделай|поставь|включи|переключи)\s+(?:свет|ламп\w*|люстр\w*|подсветк\w*|ленту|гирлянду)?\s*"
            r"(?:\w+\s+)?(красн|оранжев|желт|зелен|бирюзов|голуб|син|фиолетов|сиренев|розов|малинов|тепл|холодн|"
            r"бел|дневн|нейтральн|мягк)\w*(?:\s+(?:свет|цвет))?", priority=50)
    def color(self, ctx):
        if not self.configured:
            return self._not_configured()
        devs = [d for d in self.find(ctx.norm) if d.type.startswith("devices.types.light") or d.domain == "light"]
        if not devs:
            return None
        key = ctx.group(1)
        ya = [d.id for d in devs if d.backend == "yandex"]
        if key in COLORS:
            action = {"type": "devices.capabilities.color_setting", "state": {"instance": "hsv", "value": COLORS[key]}}
            ha_data = {"hs_color": [COLORS[key]["h"], COLORS[key]["s"]]}
        else:
            k = next(v for kk, v in COLOR_TEMPS.items() if key.startswith(kk))
            action = {"type": "devices.capabilities.color_setting", "state": {"instance": "temperature_k", "value": k}}
            ha_data = {"color_temp_kelvin": k}
        errs = self.ya.act(ya, [_on_off(True), action]) if ya and self.ya else []
        for d in devs:
            if d.backend == "ha":
                self.ha.call("light", "turn_on", {"entity_id": d.id, **ha_data})
        return Reply("Готово, красиво!" if not errs else f"Ошибка: {errs[0]}", emotion="joy", intensity=0.5)

    @intent(r"\b(?:поставь|установи|сделай|включи)\s+(?:кондиционер|обогревател\w*|термостат|отопление|батаре\w*|"
            r"температуру|теплый пол)\b.*?\b(?:на\s+)?(\d+)\s*градус", r"\bсделай (теплее|холоднее|прохладнее)\b",
            priority=50)
    def temperature(self, ctx):
        if not self.configured:
            return self._not_configured()
        devs = [d for d in self.find(ctx.norm) if "thermostat" in d.type or d.domain == "climate"]
        if not devs:
            devs = [d for d in self.devices() if "thermostat" in d.type or d.domain == "climate"]
        if not devs:
            return Reply("Не нашла кондиционер или термостат.", emotion="sadness")
        g = ctx.group(1)
        if g.isdigit():
            errs = self.set_range(devs, "temperature", int(g))
            if not errs:
                self.switch(devs, True)
            return Reply(f"Поставила {g} градусов." if not errs else f"Ошибка: {errs[0]}", emotion="confidence",
                         intensity=0.4)
        delta = 1 if g == "теплее" else -1
        errs = self.set_range(devs, "temperature", delta, relative=True)
        return Reply("Хорошо." if not errs else f"Ошибка: {errs[0]}")

    @intent(r"\b(?:какая|сколько|какой)\b.*\b(температур\w*|влажност\w*|углекисл\w*|co2|давлени\w*|заряд\w*|"
            r"освещенност\w*|мощност\w*)\b.*\b(?:в|на|у)\s+(\w+)", r"\bесть ли (протечк\w*|движени\w*|дым)\b",
            r"\b(?:открыт\w*|закрыт\w*) ли (\w+)", priority=57)
    def sensor(self, ctx):
        if not self.configured:
            return None
        n = ctx.norm
        prop = next((v for k, v in SENSOR_WORDS.items() if k in n), None)
        if not prop:
            return None
        devs = self.devices(force=True)
        room = next((r for r in self._rooms() if contains_phrase(n, r)), None)
        found = []
        for d in devs:
            if room and d.room != room and not contains_phrase(n, d.name):
                continue
            for p in d.props:
                st = p.get("state") or {}
                if (p.get("parameters") or {}).get("instance") == prop and st.get("value") is not None:
                    found.append((d, st["value"]))
            if d.backend == "ha" and d.domain in ("sensor", "binary_sensor"):
                dc = d.state.get("device_class")
                if dc == prop or (prop == "water_leak" and dc == "moisture") or (prop == "open" and dc in ("door", "window")):
                    found.append((d, d.state.get("state")))
        if not found:
            if room is None and prop in ("temperature", "humidity") and not re.search(r"\bдома|\bв доме|\bквартир", n):
                return None  # «какая температура на улице» — это погода
            return Reply("Нет такого датчика.", emotion="sadness", intensity=0.4)
        d, val = found[0]
        if isinstance(val, str) or prop in ("water_leak", "motion", "open", "smoke", "gas"):
            human = YA_EVENTS_RU.get(str(val), str(val))
            emo = "fear" if val in ("leak", "on", "detected", "high") and prop in ("water_leak", "smoke", "gas") else None
            return Reply(f"{d.label}: {human}.", emotion=emo)
        unit = UNITS_RU.get(prop, "")
        v = round(float(val), 1)
        v_s = str(int(v)) if v.is_integer() else str(v).replace(".", ",")
        return Reply(f"{d.label}: {v_s} {unit}.".replace(" .", "."))

    @intent(r"\b(?:какие|покажи|перечисли)\b.*\b(?:устройства|девайсы)\b|\bчто (?:есть )?в умном доме\b", priority=55)
    def list_devices(self, ctx):
        if not self.configured:
            return self._not_configured()
        devs = self.devices(force=True)
        if not devs:
            return Reply("Устройств не нашла.")
        names = [d.label for d in devs if d.domain not in ("sensor", "binary_sensor")][:15]
        return Reply(f"В умном доме {len(devs)} {plural(len(devs), 'устройство', 'устройства', 'устройств')}: "
                     + ", ".join(names) + ".", card="\n".join(d.label for d in devs))

    # ------------------------------------------------------------- сценарии --
    def load_scenarios(self):
        path = self.cfg.path_of("smarthome.scenarios_file", "scenarios.yaml")
        self.scenarios = []
        if path.exists() and yaml:
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                self.scenarios = data.get("scenarios", []) or []
            except Exception as e:
                self.log.error("Ошибка в %s: %s", path, e)
        return self.scenarios

    def save_scenarios(self):
        path = self.cfg.path_of("smarthome.scenarios_file", "scenarios.yaml")
        if yaml:
            path.write_text(yaml.safe_dump({"scenarios": self.scenarios}, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")

    def run_scenario(self, sc: dict, background: bool = True):
        def work():
            self.log.info("Сценарий «%s»", sc.get("name"))
            for act in sc.get("actions", []):
                try:
                    if "delay" in act:
                        time.sleep(float(act["delay"]))
                    elif "say" in act:
                        self.a.say(act["say"], emotion=act.get("emotion"))
                    elif "command" in act:
                        r = self.a.handle(act["command"], source="scenario", depth=1)
                        if act.get("speak") and r and r.text:
                            self.a.say(r.text, emotion=r.emotion)
                    elif "emotion" in act:
                        bus.emit("emotion", name=act["emotion"], intensity=1.0, hold=act.get("seconds", 8))
                    elif "notify" in act:
                        self.a.notify(act["notify"], title=sc.get("name"))
                    elif "yandex_scenario" in act and self.ya:
                        self.devices()
                        hit, _ = best_match(act["yandex_scenario"], self.ya.scenarios, key=lambda x: x["name"])
                        if hit:
                            self.ya.run_scenario(hit["id"])
                    elif "ha_service" in act and self.ha:
                        dom, srv = act["ha_service"].split(".", 1)
                        self.ha.call(dom, srv, act.get("data", {}))
                except Exception:
                    self.log.exception("действие сценария %s", act)
        if background:
            threading.Thread(target=work, daemon=True, name="scenario").start()
        else:
            work()

    def _conditions_ok(self, sc: dict) -> bool:
        now = datetime.now()
        for c in sc.get("conditions", []) or []:
            if "time_between" in c:
                a, b = c["time_between"]
                hm = now.strftime("%H:%M")
                ok = (a <= hm < b) if a <= b else (hm >= a or hm < b)
                if not ok:
                    return False
            if "days" in c and now.weekday() not in _days(c["days"]):
                return False
        return True

    @intent(r".", priority=93)
    def phrase_trigger(self, ctx):
        """Сценарии по фразе («спокойной ночи», «я дома») — раньше всех остальных команд."""
        for sc in self.scenarios:
            for tr in sc.get("triggers", []) or []:
                ph = tr.get("phrase")
                if ph and (norm(ph) == ctx.norm or similarity(ctx.norm, ph) >= 0.9) and self._conditions_ok(sc):
                    self.run_scenario(sc)
                    return Reply(sc.get("reply", ""), speak=bool(sc.get("reply")), emotion=sc.get("emotion"))
        return None

    @intent(r"\b(?:запусти|включи|выполни|активируй)\s+сценарий\s+(.+)$", priority=60)
    def run_named(self, ctx):
        name = ctx.raw_group(1)
        hit, _ = best_match(name, self.scenarios, key=lambda x: x.get("name", ""), threshold=0.6)
        if hit:
            self.run_scenario(hit)
            return Reply(f"Запускаю сценарий «{hit['name']}».", emotion="confidence", intensity=0.5)
        if self.ya:
            self.devices()
            sc, _ = best_match(name, self.ya.scenarios, key=lambda x: x["name"], threshold=0.6)
            if sc:
                try:
                    self.ya.run_scenario(sc["id"])
                    return Reply(f"Запустила сценарий «{sc['name']}».", emotion="confidence", intensity=0.5)
                except Exception as e:
                    return Reply(f"Сценарий не запустился: {e}", emotion="sadness")
        return Reply(f"Не нашла сценарий «{name}».", emotion="sadness")

    @intent(r"\b(?:создай|сделай|добавь|запомни|новый)\s+сценарий\b[:,]?\s*(.+)$", priority=61)
    def create(self, ctx):
        body = ctx.raw_group(1)
        m = re.match(r"(?:когда|если)\s+я\s+(?:говорю|скажу|произношу)\s+(.+?)\s*,?\s+(?:то\s+)?"
                     r"((?:включи|выключи|запусти|поставь|сделай|скажи|открой|закрой|напомни|убавь|прибавь).+)$", body)
        triggers, actions_text = [], None
        if m:
            triggers.append({"phrase": m.group(1).strip(" «»\"")})
            actions_text = m.group(2)
        else:
            when = parse_when(body, prefer="morning")
            if when and when.has_time:
                trig = {"time": f"{when.dt.hour:02d}:{when.dt.minute:02d}"}
                if when.repeat:
                    trig["days"] = when.repeat
                triggers.append(trig)
                actions_text = re.sub(r"^(?:в|на)\s+", "", when.rest)
        if not triggers or not actions_text:
            return Reply("Скажи, например: «создай сценарий: когда я говорю „я дома“, включи свет и музыку» или "
                         "«создай сценарий: каждый день в 7 утра включи свет на кухне».", emotion="interest")
        cmds = [c.strip() for c in re.split(r"\s*,\s*|\s+и\s+(?=(?:включи|выключи|запусти|поставь|сделай|скажи|открой|"
                                            r"закрой|напомни))", actions_text) if c.strip()]
        actions = [{"say": c[6:].strip()} if c.startswith("скажи ") else {"command": c} for c in cmds]
        name = triggers[0].get("phrase") or f"в {triggers[0]['time']}"
        self.scenarios.append({"name": name, "triggers": triggers, "actions": actions})
        self.save_scenarios()
        when = f"на фразу «{triggers[0]['phrase']}»" if "phrase" in triggers[0] else f"в {triggers[0]['time']}"
        return Reply(f"Сценарий создан: {when} — {', '.join(cmds)}.", emotion="joy", intensity=0.6)

    @intent(r"\b(?:какие|мои|список)\s+сценари\w*", priority=60)
    def list_scenarios(self, ctx):
        own = [s.get("name") for s in self.scenarios]
        ya = []
        if self.ya:
            self.devices()
            ya = [s["name"] for s in self.ya.scenarios]
        if not own and not ya:
            return Reply("Сценариев пока нет. Скажи «создай сценарий…».")
        parts = []
        if own:
            parts.append("мои: " + ", ".join(own))
        if ya:
            parts.append("в приложении Яндекса: " + ", ".join(ya))
        return Reply("Сценарии — " + "; ".join(parts) + ".")

    @intent(r"\b(?:удали|отмени|убери)\s+сценарий\s+(.+)$", priority=61)
    def delete_scenario(self, ctx):
        hit, _ = best_match(ctx.raw_group(1), self.scenarios, key=lambda x: x.get("name", ""), threshold=0.6)
        if not hit:
            return Reply("Такого сценария нет.")
        self.scenarios.remove(hit)
        self.save_scenarios()
        return Reply(f"Сценарий «{hit['name']}» удалён.")

    # ------------------------------------------------- автоматические триггеры --
    def _check_time_triggers(self):
        now = datetime.now()
        hm = now.strftime("%H:%M")
        for i, sc in enumerate(self.scenarios):
            for tr in sc.get("triggers", []) or []:
                if tr.get("time") == hm and (not tr.get("days") or now.weekday() in _days(tr["days"])):
                    key = (i, hm, now.date())
                    if key not in self._fired and self._conditions_ok(sc):
                        self._fired[key] = True
                        self.run_scenario(sc)

    def _check_sensor_triggers(self):
        devs = {clean(d.name): d for d in self.devices(force=True)}
        for i, sc in enumerate(self.scenarios):
            for tr in sc.get("triggers", []) or []:
                name = tr.get("sensor")
                if not name:
                    continue
                d = devs.get(clean(name))
                if not d:
                    hit, _ = best_match(name, list(devs.values()), key=lambda x: x.name, threshold=0.7)
                    d = hit
                if not d:
                    continue
                val = None
                for p in d.props:
                    if (p.get("parameters") or {}).get("instance") == tr.get("property", "") or not tr.get("property"):
                        val = (p.get("state") or {}).get("value")
                        break
                if d.backend == "ha":
                    val = d.state.get("state")
                active = _match_value(val, tr)
                key = (i, name)
                if active and not self._sensor_state.get(key) and self._conditions_ok(sc):
                    self.run_scenario(sc)
                self._sensor_state[key] = active

    def _presence(self, state: str):
        for sc in self.scenarios:
            for tr in sc.get("triggers", []) or []:
                if tr.get("presence") == state and self._conditions_ok(sc):
                    self.run_scenario(sc)


def _days(spec) -> list[int]:
    names = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6, "mo": 0, "tu": 1, "we": 2, "th": 3,
             "fr": 4, "sa": 5, "su": 6}
    out = []
    for d in spec or []:
        if isinstance(d, int):
            out.append(d)
        elif str(d).lower()[:2] in names:
            out.append(names[str(d).lower()[:2]])
    return out


def _match_value(val, tr: dict) -> bool:
    if val is None:
        return False
    if "above" in tr:
        try:
            return float(val) > float(tr["above"])
        except (TypeError, ValueError):
            return False
    if "below" in tr:
        try:
            return float(val) < float(tr["below"])
        except (TypeError, ValueError):
            return False
    if "value" in tr:
        return str(val).lower() == str(tr["value"]).lower()
    return bool(val)
