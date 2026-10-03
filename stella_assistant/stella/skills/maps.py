"""Карты: пробки (баллы 0–10), маршруты на машине/пешком/на велосипеде, поиск организаций с графиком работы.

Источники: TomTom (пробки, маршрут с учётом трафика — бесплатный ключ), OSRM/FOSSGIS (маршруты без ключа),
Nominatim (адреса), Яндекс «Поиск по организациям» (если есть ключ) или OpenStreetMap/Overpass (без ключа),
2ГИС (рейтинг и отзывы — по ключу)."""
from __future__ import annotations

import math
import re
from datetime import datetime

from ..nlp.numbers import plural
from ..nlp.timeparse import describe_duration
from .base import Reply, Skill, intent

OVERPASS = ["https://overpass.openstreetmap.fr/api/interpreter", "https://overpass-api.de/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]

CATEGORIES = [  # (основы слов, OSM-фильтр, как назвать)
    (("аптек",), '["amenity"="pharmacy"]', "аптека"),
    (("кафе", "кофейн"), '["amenity"="cafe"]', "кафе"),
    (("ресторан",), '["amenity"="restaurant"]', "ресторан"),
    (("пиццер",), '["cuisine"~"pizza"]', "пиццерия"),
    (("фастфуд", "бургер", "шаурм"), '["amenity"="fast_food"]', "фастфуд"),
    (("бар", "паб"), '["amenity"~"bar|pub"]', "бар"),
    (("супермаркет", "продукт", "магазин", "гастроном"), '["shop"~"supermarket|convenience"]', "магазин"),
    (("банкомат",), '["amenity"="atm"]', "банкомат"),
    (("банк",), '["amenity"="bank"]', "банк"),
    (("заправк", "азс", "бензоколон"), '["amenity"="fuel"]', "заправка"),
    (("больниц",), '["amenity"="hospital"]', "больница"),
    (("поликлиник", "клиник", "травмпункт"), '["amenity"~"clinic|doctors"]', "поликлиника"),
    (("стоматолог", "зубн"), '["amenity"="dentist"]', "стоматология"),
    (("почт",), '["amenity"="post_office"]', "почта"),
    (("пункт выдачи", "пвз", "озон", "вайлдберриз", "wildberries", "ozon"), '["shop"="outpost"]', "пункт выдачи"),
    (("парикмахер", "барбершоп", "салон красоты"), '["shop"~"hairdresser|beauty"]', "парикмахерская"),
    (("кинотеатр", "кино"), '["amenity"="cinema"]', "кинотеатр"),
    (("парк",), '["leisure"="park"]', "парк"),
    (("школ",), '["amenity"="school"]', "школа"),
    (("детск сад", "садик"), '["amenity"="kindergarten"]', "детский сад"),
    (("ветеринар", "ветклиник"), '["amenity"="veterinary"]', "ветклиника"),
    (("спортзал", "фитнес", "тренажерн"), '["leisure"="fitness_centre"]', "фитнес-клуб"),
    (("остановк",), '["highway"="bus_stop"]', "остановка"),
    (("метро",), '["station"="subway"]', "метро"),
    (("туалет",), '["amenity"="toilets"]', "туалет"),
    (("автомойк", "мойк"), '["amenity"="car_wash"]', "автомойка"),
    (("шиномонтаж",), '["shop"="tyres"]', "шиномонтаж"),
    (("цвет",), '["shop"="florist"]', "цветочный магазин"),
    (("библиотек",), '["amenity"="library"]', "библиотека"),
    (("музе",), '["tourism"="museum"]', "музей"),
    (("отел", "гостиниц"), '["tourism"="hotel"]', "гостиница"),
    (("церк", "храм"), '["amenity"="place_of_worship"]', "храм"),
]
DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_TURN = {"left": "налево", "right": "направо", "slight left": "плавно налево", "slight right": "плавно направо",
         "sharp left": "резко налево", "sharp right": "резко направо", "straight": "прямо", "uturn": "развернитесь"}


def haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def say_distance(m: float) -> str:
    if m < 950:
        v = int(round(m / 10.0) * 10)
        return f"{v} {plural(v, 'метр', 'метра', 'метров')}"
    km = m / 1000
    if km < 10:
        r = round(km, 1)
        if float(r).is_integer():
            return f"{int(r)} {plural(int(r), 'километр', 'километра', 'километров')}"
        return f"{str(r).replace('.', ',')} километра"
    v = int(round(km))
    return f"{v} {plural(v, 'километр', 'километра', 'километров')}"


def opening_hours_now(spec: str, now: datetime | None = None):
    """Простой разбор OSM opening_hours. -> (открыто ли, часы на сегодня строкой) или (None, '')."""
    now = now or datetime.now()
    if not spec:
        return None, ""
    spec = spec.strip()
    if spec in ("24/7", "Mo-Su 00:00-24:00", "00:00-24:00"):
        return True, "круглосуточно"
    today = DAYS[now.weekday()]
    chosen = None
    for rule in spec.split(";"):
        rule = rule.strip()
        if not rule or rule.startswith("PH"):
            continue
        m = re.match(r"^([A-Za-z,\- ]+?)\s+(.+)$", rule)
        days_part, times = (m.group(1), m.group(2)) if m and re.match(r"^[A-Z][a-z]", rule) else ("Mo-Su", rule)
        if _day_in(days_part, today):
            chosen = times.strip()
    if chosen is None:
        return False, "сегодня выходной"
    if chosen.lower() in ("off", "closed"):
        return False, "сегодня выходной"
    cur = now.hour * 60 + now.minute
    parts = []
    is_open = False
    for rng in chosen.split(","):
        mm = re.match(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", rng.strip())
        if not mm:
            continue
        a = int(mm.group(1)) * 60 + int(mm.group(2))
        b = int(mm.group(3)) * 60 + int(mm.group(4))
        parts.append(f"с {mm.group(1)}:{mm.group(2)} до {mm.group(3)}:{mm.group(4)}")
        if (a <= cur < b) if b > a else (cur >= a or cur < b):
            is_open = True
    return (is_open if parts else None), ", ".join(parts)


def _day_in(days_part: str, today: str) -> bool:
    for chunk in days_part.replace(" ", "").split(","):
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            if a in DAYS and b in DAYS:
                ia, ib, it = DAYS.index(a), DAYS.index(b), DAYS.index(today)
                if (ia <= it <= ib) if ia <= ib else (it >= ia or it <= ib):
                    return True
        elif chunk == today:
            return True
    return False


def yandex_hours_now(hours: dict, now: datetime | None = None):
    now = now or datetime.now()
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    wd = now.weekday()
    for av in hours.get("Availabilities", []) or []:
        if av.get("Everyday") or av.get(names[wd]) or (av.get("Weekdays") and wd < 5) or (av.get("Weekend") and wd >= 5):
            if av.get("TwentyFourHours"):
                return True, "круглосуточно"
            cur = now.hour * 60 + now.minute
            texts, op = [], False
            for iv in av.get("Intervals", []):
                a = int(iv["from"][:2]) * 60 + int(iv["from"][3:5])
                b = int(iv["to"][:2]) * 60 + int(iv["to"][3:5])
                texts.append(f"с {iv['from'][:5]} до {iv['to'][:5]}")
                if (a <= cur < b) if b > a else (cur >= a or cur < b):
                    op = True
            return op, ", ".join(texts)
    return None, hours.get("text", "")


class Maps(Skill):
    name = "maps"

    def origin(self):
        home = self.cfg.get("traffic.home")
        if home:
            return float(home[0]), float(home[1])
        lat, lon, _ = self.a.location()
        return lat, lon

    # ------------------------------------------------------------ геокодер --
    def geocode(self, query: str):
        key = self.cfg.get("places.yandex_geocoder_key")
        lat0, lon0 = self.origin()
        if key:
            try:
                d = self.a.get_json("https://geocode-maps.yandex.ru/v1/",
                                    params={"apikey": key, "geocode": query, "lang": "ru_RU", "format": "json",
                                            "results": 1, "ll": f"{lon0},{lat0}", "spn": "0.6,0.6"})
                fm = d["response"]["GeoObjectCollection"]["featureMember"]
                if fm:
                    g = fm[0]["GeoObject"]
                    lon, lat = map(float, g["Point"]["pos"].split())
                    return lat, lon, g.get("name", query)
            except Exception as e:
                self.log.warning("Яндекс Геокодер: %s", e)
        try:
            vb = f"{lon0 - 0.5},{lat0 + 0.35},{lon0 + 0.5},{lat0 - 0.35}"
            d = self.a.get_json("https://nominatim.openstreetmap.org/search",
                                params={"q": query, "format": "jsonv2", "accept-language": "ru", "limit": 1,
                                        "viewbox": vb})
            if d:
                return float(d[0]["lat"]), float(d[0]["lon"]), d[0].get("name") or query
        except Exception as e:
            self.log.warning("Nominatim: %s", e)
        return None

    # -------------------------------------------------------------- пробки --
    def traffic_score(self):
        key = self.cfg.get("traffic.tomtom_key")
        if not key:
            return None
        pts = self.cfg.get("traffic.points") or []
        if not pts:
            lat, lon = self.origin()
            pts = [(lat + 0.03 * math.cos(a), lon + 0.05 * math.sin(a)) for a in
                   [i * math.pi / 4 for i in range(8)]] + [(lat, lon)]
        ratios, weights = [], []
        for la, lo in pts:
            try:
                d = self.a.get_json("https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json",
                                    params={"point": f"{la},{lo}", "key": key, "unit": "KMPH"}, timeout=6, retries=0)
                f = d["flowSegmentData"]
                if f.get("roadClosure"):
                    continue
                if f["freeFlowSpeed"] > 0:
                    ratios.append(min(1.0, f["currentSpeed"] / f["freeFlowSpeed"]))
                    weights.append(max(0.2, f.get("confidence", 1)))
            except Exception as e:
                self.log.info("TomTom: %s", e)
        if not ratios:
            return None
        avg = sum(r * w for r, w in zip(ratios, weights)) / sum(weights)
        return max(0, min(10, int(round((1 - avg) * 14))))

    @intent(r"\b(?:пробк\w*|загруженност\w* дорог|какая обстановка на дорогах|дорожн\w* обстановк\w*)\b", priority=58)
    def traffic(self, ctx):
        score = self.traffic_score()
        if score is None:
            if not self.cfg.get("traffic.tomtom_key"):
                return Reply("Для пробок нужен бесплатный ключ TomTom в настройках (traffic.tomtom_key). Маршруты я "
                             "строю и без него — спроси «сколько ехать до работы».", emotion="sadness", intensity=0.5)
            return Reply("Не получилось узнать пробки.", emotion="sadness")
        desc = "дороги свободны" if score <= 2 else "движение в норме" if score <= 4 else \
            "местами затруднения" if score <= 6 else "серьёзные пробки" if score <= 8 else "город стоит"
        emo = "joy" if score <= 3 else "sadness" if score >= 7 else None
        text = f"Пробки {score} {plural(score, 'балл', 'балла', 'баллов')}, {desc}."
        work = self.cfg.get("traffic.work")
        if work:
            r = self._route(self.origin(), (float(work[0]), float(work[1])), "car")
            if r:
                text += f" До работы {describe_duration(r['time'])}."
        return Reply(text, emotion=emo, intensity=0.6)

    # ------------------------------------------------------------- маршрут --
    def _route(self, a, b, mode: str):
        key = self.cfg.get("traffic.tomtom_key")
        if mode == "car" and key:
            try:
                d = self.a.get_json(f"https://api.tomtom.com/routing/1/calculateRoute/{a[0]},{a[1]}:{b[0]},{b[1]}/json",
                                    params={"key": key, "traffic": "true", "travelMode": "car",
                                            "computeTravelTimeFor": "all"}, timeout=10)
                s = d["routes"][0]["summary"]
                return {"time": s["travelTimeInSeconds"], "dist": s["lengthInMeters"],
                        "delay": s.get("trafficDelayInSeconds", 0), "steps": []}
            except Exception as e:
                self.log.warning("TomTom route: %s", e)
        base = {"car": "https://router.project-osrm.org/route/v1/driving/",
                "foot": "https://routing.openstreetmap.de/routed-foot/route/v1/driving/",
                "bike": "https://routing.openstreetmap.de/routed-bike/route/v1/driving/"}[mode]
        try:
            d = self.a.get_json(f"{base}{a[1]},{a[0]};{b[1]},{b[0]}", params={"overview": "false", "steps": "true"},
                                timeout=12)
            if d.get("code") != "Ok":
                return None
            route = d["routes"][0]
            steps = []
            for st in route["legs"][0]["steps"]:
                m = st["maneuver"]
                name = st.get("name") or ""
                t, mod = m.get("type"), m.get("modifier", "")
                if t == "depart":
                    if name:
                        steps.append(f"двигайтесь по: {name}")
                elif t in ("turn", "end of road", "fork", "on ramp", "off ramp"):
                    steps.append(f"поверните {_TURN.get(mod, mod)}{', ' + name if name else ''}")
                elif t == "roundabout" or t == "rotary":
                    steps.append(f"на круговом движении съезд {m.get('exit', '')}".strip())
                elif t == "arrive":
                    steps.append("вы на месте")
            return {"time": route["duration"], "dist": route["distance"], "delay": 0, "steps": steps}
        except Exception as e:
            self.log.warning("OSRM: %s", e)
            return None

    # предлог — целым словом: иначе «сколько минут варить яйца» превращалось в маршрут до «арить яйца»
    @intent(r"\b(?:как (?:доехать|добраться|дойти|проехать|пройти)|"
            r"сколько (?:минут |времени |часов )?(?:ехать|идти|добираться|лететь)|"
            r"маршрут|проложи (?:маршрут|путь)|далеко ли|как далеко|расстояние)\b\s*(?:(?:до|к|в|на|от)\s+)?(.+)$",
            priority=57)
    def route(self, ctx):
        n = ctx.norm
        dest = ctx.group(1)
        dest = re.sub(r"\b(?:пешком|на машине|на автомобиле|на велосипеде|на велике|на такси|от дома|отсюда)\b", " ", dest)
        dest = re.sub(r"^(?:до|к|в|на)\s+", "", dest.strip()).strip()
        if not dest:
            return Reply("Куда построить маршрут?", expect_reply=True)
        mode = "foot" if re.search(r"\bпешком|\bидти\b|\bдойти\b|\bпройти\b", n) else \
            "bike" if re.search(r"\bвелосипед\w*|\bвелик\w*", n) else "car"
        target = None
        if re.match(r"^(?:работ\w*|офис\w*)$", dest) and self.cfg.get("traffic.work"):
            w = self.cfg.get("traffic.work")
            target = (float(w[0]), float(w[1]), "работы")
        elif re.match(r"^(?:дом\w*)$", dest) and self.cfg.get("traffic.home"):
            h = self.cfg.get("traffic.home")
            target = (float(h[0]), float(h[1]), "дома")
        elif re.match(r"^(?:работ\w*|офис\w*|дом\w*)$", dest):
            key = "traffic.home" if dest.startswith("дом") else "traffic.work"
            return Reply(f"Я не знаю, где {'твой дом' if key == 'traffic.home' else 'твоя работа'}: укажи координаты "
                         f"в настройках ({key}).", emotion="sadness", intensity=0.5)
        else:
            target = self.geocode(dest)
        if not target:
            if not re.search(r"\b(?:доехать|добраться|дойти|проехать|пройти|ехать|идти|добираться|маршрут|путь)\b", n):
                return None  # «как далеко луна», «расстояние от Земли до Солнца» — вопрос, а не маршрут
            return Reply(f"Не нашла на карте «{dest}».", emotion="sadness")
        r = self._route(self.origin(), target[:2], mode)
        if not r:
            return Reply("Не получилось построить маршрут.", emotion="sadness")
        how = {"car": "на машине", "foot": "пешком", "bike": "на велосипеде"}[mode]
        text = f"До {dest} {how} {describe_duration(r['time'])}, {say_distance(r['dist'])}."
        if r.get("delay", 0) > 120:
            text += f" Из них {describe_duration(r['delay'])} — из-за пробок."
        if r["steps"]:
            text += " Сначала " + ", затем ".join(r["steps"][:2]) + "."
        return Reply(text, card="\n".join(r["steps"]) if r["steps"] else None)

    # --------------------------------------------------------- организации --
    def _yandex_orgs(self, text: str, n: int = 3):
        key = self.cfg.get("places.yandex_geosearch_key")
        if not key:
            return None
        lat, lon = self.origin()
        r = self.a.http.get("https://search-maps.yandex.ru/v1/",
                            params={"apikey": key, "text": text, "type": "biz", "lang": "ru_RU",
                                    "ll": f"{lon},{lat}", "spn": "0.05,0.05", "results": n}, timeout=10)
        if not r.ok:  # ошибки сервис возвращает XML
            self.log.warning("Поиск по организациям: %s", r.status_code)
            return None
        out = []
        for f in r.json().get("features", []):
            meta = f["properties"].get("CompanyMetaData", {})
            plon, plat = f["geometry"]["coordinates"]
            is_open, hours = yandex_hours_now(meta.get("Hours") or {})
            out.append({"name": meta.get("name") or f["properties"].get("name"), "address": meta.get("address", ""),
                        "dist": haversine(lat, lon, plat, plon), "open": is_open, "hours": hours,
                        "phone": ((meta.get("Phones") or [{}])[0]).get("formatted", ""), "url": meta.get("url", "")})
        return sorted(out, key=lambda x: x["dist"])

    def _osm_places(self, osm_filter: str | None, name: str | None, n: int = 3):
        lat, lon = self.origin()
        radius = int(self.cfg.get("places.radius", 1500))
        if name:
            flt = f'["name"~"{re.escape(name)}",i]'
            radius = max(radius, 5000)
        else:
            flt = osm_filter
        q = f'[out:json][timeout:20];nwr{flt}(around:{radius},{lat},{lon});out center tags 40;'
        for url in OVERPASS:
            try:
                r = self.a.http.post(url, data={"data": q}, timeout=25)
                if r.status_code != 200:
                    continue
                els = r.json().get("elements", [])
                break
            except Exception as e:
                self.log.info("Overpass %s: %s", url, e)
        else:
            return None
        out = []
        for e in els:
            plat = e.get("lat") or e.get("center", {}).get("lat")
            plon = e.get("lon") or e.get("center", {}).get("lon")
            if plat is None:
                continue
            tags = e.get("tags", {})
            is_open, hours = opening_hours_now(tags.get("opening_hours", ""))
            addr = " ".join(x for x in (tags.get("addr:street", ""), tags.get("addr:housenumber", "")) if x)
            out.append({"name": tags.get("name") or tags.get("brand") or "", "address": addr,
                        "dist": haversine(lat, lon, plat, plon), "open": is_open, "hours": hours,
                        "phone": tags.get("phone") or tags.get("contact:phone", ""), "url": tags.get("website", "")})
        return sorted(out, key=lambda x: x["dist"])[:n]

    def _category(self, text: str):
        for stems_, flt, label in CATEGORIES:
            for st in stems_:
                if re.search(rf"\b{st}", text):
                    return flt, label
        return None, None

    @intent(r"\b(?:где (?:тут |здесь )?(?:ближайш\w*|рядом)|найди (?:рядом|поблизости|ближайш\w*)|"
            r"есть ли (?:рядом|поблизости)|ближайш\w*)\s+(.+)$|\b(.+?)\s+(?:рядом|поблизости|рядом со мной)$", priority=56)
    def nearest(self, ctx):
        what = (ctx.match.group(1) or ctx.match.group(2) or "").strip()
        flt, label = self._category(what)
        if not ctx.match.group(1) and not flt:
            return None  # «будь рядом», «посиди рядом» — не поиск на карте
        places = None
        try:
            places = self._yandex_orgs(what)
            if places is None:
                places = self._osm_places(flt, None if flt else what)
        except Exception as e:
            self.log.warning("поиск мест: %s", e)
        if places is None:
            return Reply("Не получилось поискать на карте, сервис недоступен.", emotion="sadness")
        if not places:
            return Reply(f"Рядом не нашла: {what}.", emotion="sadness")
        p = places[0]
        name = f"«{p['name']}»" if p["name"] else (label or what)
        text = f"Ближайшее — {name}, {say_distance(p['dist'])}"
        if p["address"]:
            text += f", {p['address']}"
        text += "."
        if p["open"] is True:
            text += f" Сейчас открыто{', ' + p['hours'] if p['hours'] else ''}."
        elif p["open"] is False:
            text += f" Сейчас закрыто{', ' + p['hours'] if p['hours'] else ''}."
        card = "\n".join(f"{x['name'] or label} — {say_distance(x['dist'])}, {x['address']} {x['hours']} {x['phone']}"
                         for x in places)
        return Reply(text, card=card)

    @intent(r"\b(?:до скольки|во сколько (?:открывается|закрывается)|когда (?:открывается|закрывается)|"
            r"график работы|режим работы|часы работы|открыт\w* ли|работает ли)\s+(.+)$", priority=57)
    def hours(self, ctx):
        what = re.sub(r"\b(?:работает|открыт\w*|сегодня|сейчас)\b", " ", ctx.group(1)).strip()
        flt, label = self._category(what)
        places = self._yandex_orgs(what)
        if places is None:
            places = self._osm_places(flt, None if flt else what)
        if not places:
            return Reply(f"Не нашла «{what}» поблизости.", emotion="sadness")
        p = places[0]
        name = p["name"] or label or what
        if not p["hours"]:
            return Reply(f"График работы «{name}» не знаю.")
        state = "сейчас открыто" if p["open"] else "сейчас закрыто" if p["open"] is False else ""
        return Reply(f"«{name}» работает {p['hours']}. {state.capitalize()}.".replace(". .", ".").strip())

    @intent(r"\b(?:отзыв\w*|рейтинг\w*|оценк\w*)\s+(?:о|об|про|на|у)?\s*(.+)$", priority=55)
    def reviews(self, ctx):
        key = self.cfg.get("places.dgis_key")
        what = ctx.group(1)
        if not key:
            return Reply("Рейтинги и отзывы я беру из 2ГИС — добавь ключ places.dgis_key в настройки.",
                         emotion="sadness", intensity=0.5)
        lat, lon = self.origin()
        try:
            d = self.a.get_json("https://catalog.api.2gis.com/3.0/items",
                                params={"q": what, "key": key, "location": f"{lon},{lat}", "sort": "distance",
                                        "fields": "items.reviews,items.address", "page_size": 1})
            items = d.get("result", {}).get("items", [])
            if not items:
                return Reply(f"Не нашла «{what}».")
            it = items[0]
            rv = it.get("reviews", {})
            rating, count = rv.get("general_rating"), rv.get("general_review_count")
            if not rating:
                return Reply(f"У «{it.get('name')}» пока нет оценок.")
            return Reply(f"У «{it.get('name')}» рейтинг {str(rating).replace('.', ',')} из 5, "
                         f"{count} {plural(count or 0, 'отзыв', 'отзыва', 'отзывов')}.")
        except Exception as e:
            self.log.warning("2ГИС: %s", e)
            return Reply("Не получилось получить отзывы.", emotion="sadness")

    @intent(r"\b(?:адрес|где находится|где находятся|телефон)\s+(.+)$", priority=54)
    def address(self, ctx):
        what = ctx.group(1)
        if re.search(r"\b(?:панели|твой|мой|тебя)\b", what):
            return None
        places = self._yandex_orgs(what)
        if places:
            p = places[0]
            extra = f" Телефон {p['phone']}." if p["phone"] and "телефон" in ctx.norm else ""
            return Reply(f"«{p['name']}»: {p['address']}, {say_distance(p['dist'])} отсюда.{extra}")
        g = self.geocode(what)
        if not g:
            return Reply(f"Не нашла «{what}».", emotion="sadness")
        lat, lon = self.origin()
        return Reply(f"{g[2]} — {say_distance(haversine(lat, lon, g[0], g[1]))} отсюда.")
