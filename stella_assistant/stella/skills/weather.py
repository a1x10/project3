"""Погода: сейчас, по часам, на день/выходные/неделю, осадки, восход/закат и температура воды.
Источник — Open-Meteo (бесплатно, без ключа)."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from ..nlp.numbers import plural
from ..nlp.timeparse import MONTHS_GEN, on_weekday, parse_day, parse_when
from .base import Reply, Skill, intent

WMO = {
    0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "изморозь и туман",
    51: "слабая морось", 53: "морось", 55: "сильная морось", 56: "ледяная морось", 57: "сильная ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "сильный ледяной дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снегопад", 77: "снежная крупа", 80: "кратковременный дождь",
    81: "ливень", 82: "сильный ливень", 85: "снегопад", 86: "сильный снегопад", 95: "гроза",
    96: "гроза с градом", 99: "сильная гроза с градом",
}
_STOP_PLACE = {"субботу", "воскресенье", "понедельник", "вторник", "среду", "четверг", "пятницу", "выходные",
               "течение", "ближайшие", "час", "часа", "часов", "минут", "это", "городе", "моем", "нашем", "мире"}


def temp(t: float) -> str:
    v = int(round(t))
    sign = "плюс " if v > 0 else "минус " if v < 0 else ""
    return f"{sign}{abs(v)} {plural(abs(v), 'градус', 'градуса', 'градусов')}"


def temp_short(t: float) -> str:
    v = int(round(t))
    return f"{'плюс ' if v > 0 else 'минус ' if v < 0 else ''}{abs(v)}"


def weather_emotion(code: int, t: float | None = None):
    if code in (95, 96, 99):
        return "fear", 0.6
    if code in (61, 63, 65, 66, 67, 80, 81, 82, 51, 53, 55):
        return "sadness", 0.5
    if code in (71, 73, 75, 77, 85, 86):
        return "surprise", 0.5
    if t is not None and t < -15:
        return "fear", 0.4
    if code in (0, 1) and (t is None or t > 12):
        return "joy", 0.8
    return None, 1.0


def _same_place(query: str, found: str) -> bool:
    q = query.lower().replace("ё", "е").replace("-", " ")
    f = found.lower().replace("ё", "е").replace("-", " ")
    return q == f or (f.startswith(q[:-1]) and abs(len(f) - len(q)) <= 2) or (q.startswith(f) and len(q) - len(f) <= 2)


def city_candidates(name: str) -> list[str]:
    """«москве» -> москва; «санкт-петербурге» -> санкт-петербург; «нижнем новгороде» -> нижний новгород."""
    words = name.split()
    variants = [[w] for w in words]
    for i, w in enumerate(words):
        v = [w]
        if w.endswith(("ем", "ом")) and len(words) > 1 and i < len(words) - 1:
            v += [w[:-2] + "ий", w[:-2] + "ый", w[:-2] + "ой"]
        elif w.endswith("е"):
            v += [w[:-1] + "а", w[:-1], w[:-1] + "я", w[:-1] + "ь"]
        elif w.endswith("и"):
            v += [w[:-1] + "ь", w[:-1] + "я", w[:-1] + "а"]
        elif w.endswith("у"):
            v += [w[:-1] + "а"]
        variants[i] = v
    out = []
    if len(words) == 1:
        out = variants[0]
    else:
        first, rest = variants[0], variants[1:]
        for a in first[:4]:
            for b in rest[0][:3]:
                out.append(" ".join([a, b] + words[2:]))
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq[:6]


class Weather(Skill):
    name = "weather"

    def __init__(self, a):
        super().__init__(a)
        self._cache: dict = {}

    # -------------------------------------------------------------- данные --
    def geocode(self, name: str):
        key = f"geo:{name}"
        hit = self.a.memory.kv_get(key)
        if hit:
            return tuple(hit)
        for cand in city_candidates(name):
            try:
                d = self.a.get_json("https://geocoding-api.open-meteo.com/v1/search",
                                    params={"name": cand, "count": 1, "language": "ru", "format": "json"})
            except Exception as e:
                self.log.warning("геокодер: %s", e)
                return None
            res = (d.get("results") or [])
            # геокодер ищет и по началу слова: «марс» -> «Марсель». Такие совпадения отбрасываем.
            res = [r for r in res if _same_place(cand, r.get("name", ""))]
            if res:
                r = res[0]
                out = (r["latitude"], r["longitude"], r.get("name", cand))
                self.a.memory.kv_set(key, list(out))
                return out
        return None

    def forecast(self, lat, lon):
        key = (round(lat, 2), round(lon, 2))
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < 600:
            return hit[1]
        try:
            return self._fetch_forecast(key, lat, lon)
        except Exception:
            if hit and time.time() - hit[0] < 3 * 3600:  # нет связи — отдаём недавний прогноз
                return hit[1]
            raise

    def _fetch_forecast(self, key, lat, lon):
        d = self.a.get_json("https://api.open-meteo.com/v1/forecast", timeout=12, params={
            "latitude": lat, "longitude": lon, "timezone": "auto", "wind_speed_unit": "ms", "forecast_days": 8,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,"
                       "wind_speed_10m,wind_gusts_10m,pressure_msl,is_day",
            "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                     "precipitation_sum,sunrise,sunset,wind_speed_10m_max,uv_index_max",
        })
        self._cache[key] = (time.time(), d)
        return d

    def _place(self, ctx):
        """Город из фразы («погода в Сочи», «в Казани в субботу») или город по умолчанию (city="")."""
        t = " " + ctx.norm + " "
        for pat in (r"\b(?:в|во|на)\s+(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье|"
                    r"выходн\w*|неделю|ближайшие дни|\d+ дн\w*)\b",
                    r"\b(?:завтра|сегодня|послезавтра|сейчас|утром|днем|вечером|ночью|на улице|за окном)\b",
                    r"\bчерез\s+\d*\s*\w+", r"\b(?:в|к|около)\s+\d{1,2}(?::\d{2})?(?:\s+час\w*)?\b",
                    r"\b(?:температур\w* )?(?:воды|моря)\b"):
            t = re.sub(pat, " ", t)
        m = re.search(r"\b(?:в|во|на)\s+([а-я-]{3,}(?:\s+[а-я-]{3,}){0,2})\s*$", t.strip()) or \
            re.search(r"\b(?:в|во)\s+([а-я-]{3,}(?:\s+[а-я-]{3,})?)\b", t)
        if m:
            name = m.group(1).strip()
            if name.split()[0] not in _STOP_PLACE:
                geo = self.geocode(name)
                if geo:
                    return geo
        lat, lon, _ = self.a.location()
        return lat, lon, ""

    @staticmethod
    def _in_city(city: str) -> str:
        return f" в городе {city}" if city else ""

    # ------------------------------------------------------------ ответы --
    def short_today(self) -> str:
        lat, lon, _ = self.a.location()
        d = self.forecast(lat, lon)
        dl = d["daily"]
        return (f"Сегодня от {temp_short(dl['temperature_2m_min'][0])} до {temp(dl['temperature_2m_max'][0])}, "
                f"{WMO.get(dl['weather_code'][0], '')}.")

    @intent(r"\bтемператур\w* (?:воды|моря|в море)\b|\bтеплая ли вода\b|\bкакая вода\b|\bможно ли купаться\b",
            priority=61)
    def water(self, ctx):
        lat, lon, city = self._place(ctx)
        try:
            d = self.a.get_json("https://marine-api.open-meteo.com/v1/marine",
                                params={"latitude": lat, "longitude": lon, "current": "sea_surface_temperature",
                                        "timezone": "auto"})
            t = d.get("current", {}).get("sea_surface_temperature")
        except Exception:
            t = None
        if t is None:
            return Reply(f"Не знаю температуру воды{self._in_city(city)} — данных о море рядом нет.", emotion="sadness")
        emo = "joy" if t >= 22 else "fear" if t < 14 else None
        advice = " Можно купаться!" if t >= 22 else " Бодрящая водичка." if t >= 17 else " Купаться холодно."
        return Reply(f"Температура воды{self._in_city(city)} — {temp(t)}.{advice}", emotion=emo)

    @intent(r"\b(?:погод\w*|прогноз\w*|температур\w*|градус\w*|холодно|тепло|жарко|мороз\w*|"
            r"дожд\w*|снег\w*|осадк\w*|зонт\w*|ветер|ветрено|что надеть|как одеться|восход\w*|закат\w*|"
            r"рассвет\w*|влажност\w*|давлени\w*)\b", priority=56)
    def weather(self, ctx):
        n = ctx.norm
        # «градусов» в «сколько градусов в фаренгейтах» — это конвертер, не погода
        if re.search(r"\d+\s+градус\w*\s+(?:в|во)\s", n) or re.search(r"\b(?:на|в) (?:кухне|спальне|комнате|детской|"
                                                                         r"гостиной|доме|квартире)\b", n):
            return None
        try:
            lat, lon, city = self._place(ctx)
            d = self.forecast(lat, lon)
        except Exception as e:
            self.log.warning("погода: %s", e, exc_info=True)
            return Reply("Не получилось узнать погоду — нет связи с метеосервисом.", emotion="sadness")
        if re.search(r"\b(?:восход\w*|рассвет\w*|закат\w*)\b", n):
            return self._sun(d, n, city)
        if re.search(r"\b(?:зонт\w*|дожд\w*|осадк\w*|снег\w*)\b", n) and re.search(r"\b(?:будет|нужен|брать|ли|пойдет)\b", n):
            return self._rain(d, n, city)
        if re.search(r"\bна (?:неделю|7 дней|ближайшие дни|несколько дней)\b", n):
            return self._week(d, city)
        if re.search(r"\bна выходн\w*|\bв выходн\w*", n):
            return self._weekend(d, city)
        if re.search(r"\bчто надеть\b|\bкак одеться\b", n):
            return self._clothes(d, city)
        day, offset = parse_day(ctx.text)
        hour = None
        when = parse_when(ctx.text, prefer="nearest")
        if when and when.has_time and (when.relative or re.search(r"\b(?:утром|днем|вечером|ночью|в \d)", n)):
            hour = when.dt
        if hour is not None and (hour - datetime.now()).total_seconds() < 6 * 86400:
            return self._at_hour(d, hour, city)
        if offset and offset > 0:
            return self._day(d, offset, city)
        return self._now(d, city)

    def _now(self, d, city):
        c = d["current"]
        dl = d["daily"]
        code = int(c["weather_code"])
        parts = [f"Сейчас{self._in_city(city)} {temp(c['temperature_2m'])}, {WMO.get(code, '')}"]
        if abs(c["apparent_temperature"] - c["temperature_2m"]) >= 3:
            parts.append(f"ощущается как {temp_short(c['apparent_temperature'])}")
        wind = int(round(c["wind_speed_10m"]))
        if wind >= 4:
            parts.append(f"ветер {wind} {plural(wind, 'метр', 'метра', 'метров')} в секунду")
        text = ", ".join(parts) + "."
        now_h = datetime.now().hour
        if now_h < 15:
            text += f" Днём до {temp(dl['temperature_2m_max'][0])}."
        else:
            text += f" Ночью до {temp(dl['temperature_2m_min'][1])}."
        prob = dl["precipitation_probability_max"][0]
        if prob is not None and prob >= 50 and code < 50:
            text += f" Вероятность осадков {prob} процентов — возьми зонт."
        emo, inten = weather_emotion(code, c["temperature_2m"])
        return Reply(text, emotion=emo, intensity=inten)

    def _day(self, d, offset, city):
        dl = d["daily"]
        if offset >= len(dl["time"]):
            return Reply("Так далеко я не вижу — прогноз есть только на неделю вперёд.")
        date = datetime.fromisoformat(dl["time"][offset])
        name = "Завтра" if offset == 1 else "Послезавтра" if offset == 2 else \
            f"{on_weekday(date.weekday()).capitalize()}, {date.day} {MONTHS_GEN[date.month - 1]},"
        code = int(dl["weather_code"][offset])
        text = (f"{name}{self._in_city(city)} от {temp_short(dl['temperature_2m_min'][offset])} до "
                f"{temp(dl['temperature_2m_max'][offset])}, {WMO.get(code, '')}.")
        prob = dl["precipitation_probability_max"][offset]
        if prob is not None and prob >= 30:
            text += f" Вероятность осадков {prob} процентов."
        wind = dl["wind_speed_10m_max"][offset]
        if wind and wind >= 10:
            text += f" Сильный ветер, до {int(round(wind))} метров в секунду."
        emo, inten = weather_emotion(code, dl["temperature_2m_max"][offset])
        return Reply(text, emotion=emo, intensity=inten)

    def _at_hour(self, d, when: datetime, city):
        h = d["hourly"]
        target = when.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00")
        if target not in h["time"]:
            return self._now(d, city)
        i = h["time"].index(target)
        code = int(h["weather_code"][i])
        day = "сегодня" if when.date() == datetime.now().date() else \
            "завтра" if when.date() == datetime.now().date() + timedelta(days=1) else on_weekday(when.weekday())
        text = (f"{day.capitalize()} в {when.hour}:00{self._in_city(city)} {temp(h['temperature_2m'][i])}, "
                f"{WMO.get(code, '')}")
        prob = h["precipitation_probability"][i]
        if prob:
            text += f", вероятность осадков {prob} процентов"
        emo, inten = weather_emotion(code, h["temperature_2m"][i])
        return Reply(text + ".", emotion=emo, intensity=inten)

    def _rain(self, d, n, city):
        h = d["hourly"]
        start = datetime.now().replace(minute=0, second=0, microsecond=0)
        if re.search(r"\bзавтра\b", n):
            start = (start + timedelta(days=1)).replace(hour=7)
        key = start.strftime("%Y-%m-%dT%H:00")
        i0 = h["time"].index(key) if key in h["time"] else 0
        window = range(i0, min(i0 + 14, len(h["time"])))
        probs = [(h["precipitation_probability"][i] or 0, i) for i in window]
        best = max(probs) if probs else (0, i0)
        if best[0] >= 50:
            t = datetime.fromisoformat(h["time"][best[1]])
            return Reply(f"Да, возьми зонт: около {t.hour}:00 вероятность осадков {best[0]} процентов, "
                         f"{WMO.get(int(h['weather_code'][best[1]]), 'осадки')}.", emotion="sadness", intensity=0.5)
        if best[0] >= 25:
            return Reply(f"Небольшой шанс осадков — до {best[0]} процентов. Зонт на всякий случай не помешает.")
        return Reply("Осадков не ожидается, зонт можно не брать.", emotion="joy", intensity=0.6)

    def _weekend(self, d, city):
        dl = d["daily"]
        out = []
        for i, ds in enumerate(dl["time"]):
            dt = datetime.fromisoformat(ds)
            if dt.weekday() in (5, 6) and i < 7:
                out.append(f"{on_weekday(dt.weekday())} от {temp_short(dl['temperature_2m_min'][i])} до "
                           f"{temp_short(dl['temperature_2m_max'][i])}, {WMO.get(int(dl['weather_code'][i]), '')}")
            if len(out) == 2:
                break
        if not out:
            return Reply("Прогноза на выходные пока нет.")
        return Reply(f"На выходных{self._in_city(city)}: " + "; ".join(out) + ".")

    def _week(self, d, city):
        dl = d["daily"]
        days = []
        for i in range(1, min(8, len(dl["time"]))):
            dt = datetime.fromisoformat(dl["time"][i])
            days.append(f"{on_weekday(dt.weekday())} {temp_short(dl['temperature_2m_max'][i])}, "
                        f"{WMO.get(int(dl['weather_code'][i]), '')}")
        tmin, tmax = min(dl["temperature_2m_min"][1:8]), max(dl["temperature_2m_max"][1:8])
        text = (f"На неделе{self._in_city(city)} от {temp_short(tmin)} до {temp(tmax)}. По дням: " +
                "; ".join(days) + ".")
        return Reply(text, card="\n".join(days))

    def _sun(self, d, n, city):
        dl = d["daily"]
        i = 1 if re.search(r"\bзавтра\b", n) else 0
        rise = datetime.fromisoformat(dl["sunrise"][i])
        sset = datetime.fromisoformat(dl["sunset"][i])
        when = "Завтра" if i else "Сегодня"
        if re.search(r"\bзакат\w*\b", n) and not re.search(r"\b(?:восход\w*|рассвет\w*)\b", n):
            return Reply(f"{when} закат в {sset.hour}:{sset.minute:02d}.")
        if not re.search(r"\bзакат\w*\b", n):
            return Reply(f"{when} рассвет в {rise.hour}:{rise.minute:02d}.")
        return Reply(f"{when} рассвет в {rise.hour}:{rise.minute:02d}, закат в {sset.hour}:{sset.minute:02d}.")

    def _clothes(self, d, city):
        c = d["current"]
        t = c["apparent_temperature"]
        code = int(c["weather_code"])
        if t < -15:
            tip = "очень холодно: пуховик, шапка, шарф и тёплые варежки"
        elif t < -5:
            tip = "морозно: зимняя куртка, шапка и перчатки"
        elif t < 5:
            tip = "прохладно: тёплая куртка и шапка"
        elif t < 12:
            tip = "свежо: лёгкая куртка или плащ"
        elif t < 20:
            tip = "комфортно: кофта или ветровка"
        elif t < 27:
            tip = "тепло: футболка и лёгкие брюки"
        else:
            tip = "жарко: лёгкая одежда, головной убор и вода с собой"
        rain = " И не забудь зонт!" if code >= 51 and code not in (71, 73, 75, 77, 85, 86) else ""
        return Reply(f"Ощущается как {temp_short(t)}, {tip}.{rain}", emotion="interest", intensity=0.5)
