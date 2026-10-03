"""Разбор времени, дат и длительностей на русском.

    parse_duration("на полтора часа")            -> 5400
    parse_when("напомни завтра в 7 30 позвонить маме").dt -> завтра 07:30, rest="напомни позвонить маме"
    parse_when("в пятницу вечером").dt           -> ближайшая пятница 19:00
    parse_when("без пятнадцати восемь").dt       -> 07:45
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .numbers import plural
from .text import norm

# ------------------------------------------------------------ длительности --
_UNIT_PREFIX = (
    ("сек", 1), ("с", 1), ("мин", 60), ("м", 60), ("час", 3600), ("ч", 3600), ("сут", 86400),
    ("дн", 86400), ("день", 86400), ("недел", 604800), ("месяц", 2592000), ("год", 31536000), ("лет", 31536000),
)
_UNIT_WORD = re.compile(r"^(секунд\w*|сек|с|минут\w*|минутк\w*|мин|м|час\w*|ч|сутк\w*|суток|дн\w*|день|недел\w*|месяц\w*|год\w*|лет)$")
_BARE_UNIT = {"секунду": 1, "секундочку": 1, "минуту": 60, "минутку": 60, "час": 3600, "часик": 3600,
              "сутки": 86400, "день": 86400, "неделю": 604800, "месяц": 2592000, "год": 31536000}
_SPECIAL_DUR = {"полчаса": 1800, "полчасика": 1800, "полминуты": 30, "полдня": 43200, "полгода": 15768000}


def _unit_seconds(word: str) -> int:
    if not _UNIT_WORD.match(word):
        return 0
    for prefix, sec in _UNIT_PREFIX:
        if word.startswith(prefix) and (len(prefix) > 1 or word == prefix):
            return sec
    return 0


def _is_num(w: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", w))


def scan_duration(tokens: list[str], i: int = 0) -> tuple[float, int]:
    """Читает длительность из списка слов начиная с позиции i -> (секунды, позиция после)."""
    total, j, last_unit = 0.0, i, 0
    while j < len(tokens):
        w = tokens[j]
        nxt = tokens[j + 1] if j + 1 < len(tokens) else ""
        if _is_num(w) and _unit_seconds(nxt):
            last_unit = _unit_seconds(nxt)
            total += float(w) * last_unit
            j += 2
        elif w in _SPECIAL_DUR:
            total += _SPECIAL_DUR[w]
            j += 1
        elif w == "четверть" and nxt.startswith("час"):
            total += 900
            j += 2
        elif w in _BARE_UNIT and total == 0:
            last_unit = _BARE_UNIT[w]
            total += last_unit
            j += 1
        elif _is_num(w) and last_unit == 3600 and not _unit_seconds(nxt) and float(w) < 60:
            total += float(w) * 60  # «час двадцать», «2 часа 15»
            j += 1
            break
        elif w == "и" and total and (_is_num(nxt) or nxt in _SPECIAL_DUR):
            j += 1
        else:
            break
    return total, j


def parse_duration(text: str):
    """-> (секунды:int, остаток текста) или (None, текст)."""
    tokens = norm(text).split()
    for i in range(len(tokens)):
        sec, j = scan_duration(tokens, i)
        if sec > 0:
            k = i - 1 if i > 0 and tokens[i - 1] in ("на", "через", "в", "по") else i
            rest = " ".join(tokens[:k] + tokens[j:])
            return int(round(sec)), rest
    return None, " ".join(tokens)


def describe_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds <= 0:
        return "0 секунд"
    if seconds >= 300:  # больше 5 минут — секунды не важны
        seconds = int(round(seconds / 60.0)) * 60
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d} {plural(d, 'день', 'дня', 'дней')}")
    if h:
        parts.append(f"{h} {plural(h, 'час', 'часа', 'часов')}")
    if m:
        parts.append(f"{m} {plural(m, 'минуту', 'минуты', 'минут')}")
    if s and not d and not h:
        parts.append(f"{s} {plural(s, 'секунду', 'секунды', 'секунд')}")
    return " ".join(parts)


# ---------------------------------------------------------------- даты ------
WEEKDAYS_ACC = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
WEEKDAYS_NOM = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
_WD_STEMS = [("понедельник", 0), ("вторник", 1), ("сред", 2), ("четверг", 3), ("пятниц", 4), ("суббот", 5),
             ("воскресень", 6)]
_MONTH_RE = (r"(январ\w*|феврал\w*|март\w*|апрел\w*|ма[яйе]|июн\w*|июл\w*|август\w*|сентябр\w*|"
             r"октябр\w*|ноябр\w*|декабр\w*)")
_MONTH_STEMS = ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"]
_HALF_HOURS = {
    "полпервого": 1, "полвторого": 2, "полтретьего": 3, "полчетвертого": 4, "полпятого": 5,
    "полшестого": 6, "полседьмого": 7, "полвосьмого": 8, "полдевятого": 9, "полдесятого": 10,
    "полодиннадцатого": 11, "полдвенадцатого": 12,
}


def on_weekday(i: int) -> str:
    """«во вторник», «в среду»."""
    return ("во " if i == 1 else "в ") + WEEKDAYS_ACC[i]


def _weekday(word: str):
    for st, i in _WD_STEMS:
        if word.startswith(st):
            return i
    return None


def _month(word: str):
    if re.fullmatch(r"ма[яйе]", word):
        return 5
    for i, st in enumerate(_MONTH_STEMS):
        if st != "ма" and word.startswith(st):
            return i + 1
    return None


@dataclass
class When:
    dt: datetime | None = None
    has_date: bool = False
    has_time: bool = False
    relative: bool = False
    repeat: list[int] | None = None  # дни недели 0..6
    rest: str = ""
    spans: list = field(default_factory=list)


def _parse_repeat(t: str):
    if re.search(r"\b(кажд\w+ день|ежедневно|каждое утро|каждый вечер|каждую ночь)\b", t):
        return list(range(7)), re.search(r"\b(кажд\w+ день|ежедневно|каждое утро|каждый вечер|каждую ночь)\b", t).span()
    m = re.search(r"\b(по будням|в будни|по рабочим дням|в рабочие дни)\b", t)
    if m:
        return [0, 1, 2, 3, 4], m.span()
    m = re.search(r"\b(по выходным|в выходные дни)\b", t)
    if m:
        return [5, 6], m.span()
    m = re.search(r"\b(?:кажд\w+|по)\s+(понедельник\w*|вторник\w*|сред\w*|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*)", t)
    if m:
        return [_weekday(m.group(1))], m.span()
    return None, None


def parse_when(text: str, now: datetime | None = None, prefer: str = "nearest",
               default_time: time = time(9, 0)) -> When | None:
    """Ищет в тексте момент времени.

    prefer="nearest": «в 7» в 10 утра -> сегодня 19:00 (для напоминаний);
    prefer="morning": «в 7» -> ближайшие 7:00 (для будильников).
    """
    now = now or datetime.now()
    t = norm(text)
    for word, hour in _HALF_HOURS.items():
        t = re.sub(rf"\b{word}\b", f"в половине {hour}", t)
    t = re.sub(r"\bв в половине\b", "в половине", t)
    t = re.sub(r"\b(\d{1,2}) 0 0\b", r"\1:00", t)        # «восемнадцать ноль ноль»
    t = re.sub(r"\b(\d{1,2}) 0 (\d)\b", r"\1:0\2", t)   # «семь ноль пять»
    res = When()
    spans: list[tuple[int, int]] = []

    def finish(dt):
        res.dt = dt
        out, pos = [], 0
        for a, b in sorted(spans):
            if a >= pos:
                out.append(t[pos:a])
                pos = b
        out.append(t[pos:])
        rest = re.sub(r"\s+", " ", " ".join(out)).strip()
        rest = re.sub(r"^(?:в|на|к|и)\s+|\s+(?:в|на|к|и)$", "", rest).strip()
        res.rest = rest
        res.spans = spans
        return res

    res.repeat, rspan = _parse_repeat(t)
    if rspan:
        spans.append(rspan)

    # --- «через N минут» -----------------------------------------------------
    tokens = t.split()
    for i, w in enumerate(tokens):
        if w == "через":
            sec, j = scan_duration(tokens, i + 1)
            if sec > 0:
                res.relative = res.has_time = True
                start = len(" ".join(tokens[:i])) + (1 if i else 0)
                end = len(" ".join(tokens[:j]))
                spans.append((start, end))
                return finish(now + timedelta(seconds=sec))

    # --- дата ---------------------------------------------------------------
    day: date | None = None
    weekday_given = False
    m = re.search(r"\bпослезавтра\b", t)
    if m:
        day = (now + timedelta(days=2)).date()
        spans.append(m.span())
    else:
        m = re.search(r"\bзавтра\b", t)
        if m:
            day = (now + timedelta(days=1)).date()
            spans.append(m.span())
        else:
            m = re.search(r"\bсегодня\b", t)
            if m:
                day = now.date()
                spans.append(m.span())
    m = re.search(r"\b(?:(?:в|во)\s+)?(?:(следующ\w+|этот|эту|это)\s+)?"
                  r"(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)\b", t)
    if m and (day is not None or res.repeat):
        spans.append(m.span())  # «сегодня в субботу» — день уже известен
    elif m:
        wd = _weekday(m.group(2))
        ahead = (wd - now.weekday()) % 7
        if m.group(1) and m.group(1).startswith("следующ") and ahead == 0:
            ahead = 7
        day = (now + timedelta(days=ahead)).date()
        weekday_given = True
        spans.append(m.span())
    if day is None:
        m = re.search(r"\b(\d{1,2})(?:-?го|-?е)?\s+" + _MONTH_RE + r"(?:\s+(\d{4})(?:\s+год\w*)?)?\b", t)
        if m and 1 <= int(m.group(1)) <= 31:
            mon = _month(m.group(2))
            year = int(m.group(3)) if m.group(3) else now.year
            try:
                day = date(year, mon, int(m.group(1)))
                if not m.group(3) and day < now.date():
                    day = date(year + 1, mon, int(m.group(1)))
                spans.append(m.span())
            except ValueError:
                day = None
    if day is None:
        m = re.search(r"\b(\d{1,2})\s+числа\b", t)
        if m and 1 <= int(m.group(1)) <= 31:
            d = int(m.group(1))
            y, mo = now.year, now.month
            if d < now.day:
                mo += 1
                if mo > 12:
                    y, mo = y + 1, 1
            try:
                day = date(y, mo, d)
                spans.append(m.span())
            except ValueError:
                pass
    if day is None:
        m = re.search(r"\b(на выходных|в выходные)\b", t)
        if m:
            ahead = (5 - now.weekday()) % 7
            day = (now + timedelta(days=ahead)).date()
            spans.append(m.span())
    res.has_date = day is not None

    # --- время --------------------------------------------------------------
    hour = minute = None
    pod = None  # утро/день/вечер/ночь
    pod_explicit = False
    m = re.search(r"\b(?:в\s+)?(полдень|полночь)\b", t)
    if m:
        hour, minute = (12, 0) if m.group(1) == "полдень" else (0, 0)
        pod_explicit = True
        if m.group(1) == "полночь" and day is None:
            day = (now + timedelta(days=1)).date()
        spans.append(m.span())
    if hour is None:
        m = re.search(r"\b(?:в\s+)?без\s+(\d{1,2}|четверти)(?:\s+минут\w*)?\s+(\d{1,2})(?:\s+час\w*)?\b", t)
        if m:
            mins = 15 if m.group(1) == "четверти" else int(m.group(1))
            h = int(m.group(2))
            if 0 < mins < 60 and 1 <= h <= 24:
                hour, minute = (h - 1) % 24, 60 - mins
                spans.append(m.span())
    if hour is None:
        m = re.search(r"\b(?:в\s+)?(половин[еау]|четверть)\s+(\d{1,2})\b", t)
        if m and 1 <= int(m.group(2)) <= 24:
            hour = (int(m.group(2)) - 1) % 24
            minute = 30 if m.group(1).startswith("половин") else 15
            spans.append(m.span())
    if hour is None:
        m = re.search(
            # (?!\d): иначе «на 10 минут» откатывается до «1» и становится 01:00
            r"\b(?:(?:в|во|на|к|до|около|ровно в)\s+)(\d{1,2})(?!\d)(?:(?::|\.|\s+)(\d{2})(?!\d))?"
            r"(?!\s*(?:минут|мин\b|секунд|сек\b|дн|сут|недел|месяц|раз|год|лет|процент|градус|%|\.\d))"
            r"(?:\s+час(?:а|ов)?)?(?:\s+(\d{1,2})\s+минут\w*)?", t)
        if not m:
            m = re.search(r"\b(\d{1,2})(?::|\.)(\d{2})\b()", t)
        if not m:
            m = re.search(r"\b(\d{1,2})\s+час(?:а|ов)?(?:\s+(\d{1,2})\s+минут\w*)?()(?=\s+(?:утра|дня|вечера|ночи))", t)
        if m:
            h = int(m.group(1))
            mi = m.group(2) or (m.group(3) if m.lastindex and m.lastindex >= 3 else None)
            mi = int(mi) if mi else 0
            if 0 <= h <= 24 and 0 <= mi <= 59:
                hour, minute = h % 24, mi
                spans.append(m.span())
    if hour is not None:
        m = re.search(r"\b(утра|дня|вечера|ночи)\b", t)
        if m:
            pod, pod_explicit = m.group(1), True
            spans.append(m.span())
    m = re.search(r"\b(утром|днем|вечером|ночью|с утра|после обеда)\b", t)
    if m:
        spans.append(m.span())
        word = m.group(1)
        if hour is None:
            hour, minute = {"утром": (9, 0), "с утра": (9, 0), "днем": (13, 0), "после обеда": (14, 0),
                            "вечером": (19, 0), "ночью": (23, 0)}[word]
            pod_explicit = True
        else:
            pod = {"утром": "утра", "с утра": "утра", "днем": "дня", "после обеда": "дня",
                   "вечером": "вечера", "ночью": "ночи"}[word]
            pod_explicit = True
    if hour is not None and pod:
        if pod == "утра" and hour == 12:
            hour = 0
        elif pod in ("дня", "вечера") and hour < 12:
            hour += 12
        elif pod == "ночи":
            if hour == 12:
                hour = 0
            elif 6 <= hour < 12:
                hour += 12
    res.has_time = hour is not None

    if day is None and hour is None:
        if res.repeat:
            return None
        return None
    if hour is None:
        hour, minute = default_time.hour, default_time.minute
    base_day = day or now.date()
    dt = datetime.combine(base_day, time(hour, minute or 0))
    if dt <= now:
        if day is None:
            if prefer == "nearest" and not pod_explicit and hour < 12 and dt + timedelta(hours=12) > now:
                dt += timedelta(hours=12)
            else:
                dt += timedelta(days=1)
        elif weekday_given and dt.date() == now.date():
            dt += timedelta(days=7)
    if res.repeat and day is None:
        while dt.weekday() not in res.repeat:
            dt += timedelta(days=1)
    return finish(dt)


def describe_dt(dt: datetime, now: datetime | None = None) -> str:
    """'сегодня в 7:30', 'завтра в 19:00', 'в пятницу, 9 октября, в 10:00'."""
    now = now or datetime.now()
    hm = f"{dt.hour}:{dt.minute:02d}"
    delta_days = (dt.date() - now.date()).days
    if delta_days == 0:
        return f"сегодня в {hm}"
    if delta_days == 1:
        return f"завтра в {hm}"
    if delta_days == 2:
        return f"послезавтра в {hm}"
    if 0 < delta_days < 7:
        return f"{on_weekday(dt.weekday())} в {hm}"
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]} в {hm}"


def describe_repeat(days) -> str:
    if not days:
        return ""
    days = sorted(days)
    if days == list(range(7)):
        return "каждый день"
    if days == [0, 1, 2, 3, 4]:
        return "по будням"
    if days == [5, 6]:
        return "по выходным"
    names = ["понедельникам", "вторникам", "средам", "четвергам", "пятницам", "субботам", "воскресеньям"]
    return "по " + ", ".join(names[d] for d in days)


def parse_day(text: str, now: datetime | None = None):
    """Только день (для погоды/календаря): -> (date, сдвиг в днях) или (None, None)."""
    now = now or datetime.now()
    t = norm(text)
    if re.search(r"\bпослезавтра\b", t):
        return (now + timedelta(days=2)).date(), 2
    if re.search(r"\bзавтра\b", t):
        return (now + timedelta(days=1)).date(), 1
    if re.search(r"\bсегодня\b|\bсейчас\b", t):
        return now.date(), 0
    m = re.search(r"\b(?:в|во|на)\s+(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)\b", t)
    if m:
        ahead = (_weekday(m.group(1)) - now.weekday()) % 7
        return (now + timedelta(days=ahead)).date(), ahead
    if re.search(r"\b(на выходных|в выходные)\b", t):
        ahead = (5 - now.weekday()) % 7
        return (now + timedelta(days=ahead)).date(), ahead
    m = re.search(r"\b(\d{1,2})\s+" + _MONTH_RE, t)
    if m:
        try:
            d = date(now.year, _month(m.group(2)), int(m.group(1)))
            if d < now.date():
                d = date(now.year + 1, d.month, d.day)
            return d, (d - now.date()).days
        except ValueError:
            pass
    return None, None
