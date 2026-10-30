"""Быстрые голосовые команды: музыка (Spotify и любой плеер) и погода (бесплатно, без ключей).

Команды распознаются локально сразу после слова «Стелла», без облака и без минут ElevenLabs.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WAKE = "стелла"

# ---------- разбор фразы ----------
NEXT = {"дальше", "следующая", "следующий", "следующую", "вперёд", "вперед"}
PREV = {"назад", "предыдущая", "предыдущий", "предыдущую"}
LIKE = {"лайк", "лайкни"}
PAUSE = {"пауза", "стоп", "останови", "пауз"}
RESUME = {"продолжи", "продолжай", "играй"}
PLAYLIST = {"плейлист", "плейлисте"}
MUSIC = {"музыку", "музыка"}
WEATHER = {"погода", "погоду", "погоды"}
TOMORROW = {"завтра"}
FILLER = {"включи", "запусти", "мой", "мою", "моё", "моя", "какая", "какой", "сегодня", "сейчас", "на", "в", "и", "ещё",
          "поставь", "дальше"}

# слова для узкой грамматики распознавателя (быстрее и точнее, чем свободная речь)
GRAMMAR = sorted({WAKE} | NEXT | PREV | LIKE | PAUSE | RESUME | PLAYLIST | MUSIC | WEATHER | TOMORROW | FILLER
                 | {"плейлист", "включи", "мой"})


def parse_command(text: str, wake: str = WAKE):
    """Текст после/вместе со словом «Стелла» → (команда, подробность).
    Команды: next, prev, like, pause, resume, playlist, weather, None (просто разговор)."""
    words = text.lower().replace("ё", "е").split()
    words = [w for w in words if w != "[unk]"]
    if wake not in words:
        return None, ""
    after = set(words[words.index(wake) + 1:])
    norm = lambda s: {w.replace("ё", "е") for w in s}
    if after & norm(NEXT): return "next", ""
    if after & norm(PREV): return "prev", ""
    if after & norm(LIKE): return "like", ""
    if after & norm(PAUSE): return "pause", ""
    if after & norm(RESUME): return "resume", ""
    if after & norm(WEATHER): return "weather", ("tomorrow" if after & norm(TOMORROW) else "today")
    if after & norm(PLAYLIST) or ("включи" in after and after & norm(MUSIC)): return "playlist", ""
    return None, ""


# ---------- музыка ----------
_VK = {"next": 0xB0, "prev": 0xB1, "playpause": 0xB3}


def media_key(name: str) -> bool:
    """Медиаклавиши: работают с любым плеером (Spotify, браузер, и т. д.), Premium не нужен."""
    if sys.platform == "win32":
        import ctypes
        vk = _VK[name]
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        return True
    cmd = {"next": "next", "prev": "previous", "playpause": "play-pause"}[name]
    try:
        subprocess.run(["playerctl", cmd], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _spotify_uri(link: str) -> str:
    link = link.strip()
    m = re.search(r"open\.spotify\.com/(?:intl-[a-z]+/)?(playlist|album|artist|track)/([A-Za-z0-9]+)", link)
    if m:
        kind = m.group(1)
        return f"spotify:{kind}:{m.group(2)}" + (":play" if kind in ("playlist", "album") else "")
    return link  # уже spotify:... или свой URI


def hide_spotify(seconds: float = 10.0) -> int:
    """Скрывает окна Spotify (музыка продолжает играть, медиаклавиши работают).
    Windows: несколько секунд подряд прячет окно, пока приложение запускается. Возвращает число скрытых окон."""
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def exe_name(hwnd):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        buf, size = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        kernel32.CloseHandle(handle)
        return os.path.basename(buf.value).lower() if ok else ""

    hidden = [0]

    def on_window(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0 and exe_name(hwnd) == "spotify.exe":
            user32.ShowWindow(hwnd, 0)  # SW_HIDE
            hidden[0] += 1
        return True

    callback = enum_proc(on_window)
    deadline = time.time() + seconds
    while time.time() < deadline:
        user32.EnumWindows(callback, 0)
        time.sleep(0.3)
    return hidden[0]


def keep_spotify_hidden(seconds: float = 10.0):
    """Фоновое скрытие окна Spotify (отключается SPOTIFY_HIDDEN=0 в .env)."""
    if os.getenv("SPOTIFY_HIDDEN", "1") != "0":
        threading.Thread(target=lambda: hide_spotify(seconds), daemon=True).start()


def play_playlist() -> str:
    """Запускает плейлист из playlists.json (ключ "default") в приложении Spotify."""
    path = os.path.join(HERE, "playlists.json")
    if not os.path.exists(path):
        # плейлист не задан: просто продолжаем то, что играло
        media_key("playpause")
        return "Файла playlists.json нет, поэтому просто нажала «играть/пауза»."
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    link = data.get("default") or next(iter(data.values()), "")
    uri = _spotify_uri(link)
    if sys.platform == "win32":
        os.startfile(uri)  # откроет Spotify и начнёт плейлист
        keep_spotify_hidden()
    elif sys.platform == "darwin":
        subprocess.Popen(["open", uri])
    else:
        subprocess.Popen(["xdg-open", uri])
    return "Включаю ваш плейлист."


def like_current() -> str:
    import spotify_api
    return spotify_api.like_current()


# ---------- погода ----------
WMO = {0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "изморозь",
       51: "слабая морось", 53: "морось", 55: "сильная морось", 56: "ледяная морось", 57: "ледяная морось",
       61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "ледяной дождь",
       71: "небольшой снег", 73: "снег", 75: "сильный снегопад", 77: "снежная крупа", 80: "ливень", 81: "сильный ливень",
       82: "очень сильный ливень", 85: "снегопад", 86: "сильный снегопад", 95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом"}


def _get_json(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "stella-speaker/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _location():
    """Город: WEATHER_CITY из .env, иначе приблизительно по IP."""
    city = os.getenv("WEATHER_CITY", "").strip()
    if city:
        g = _get_json("https://geocoding-api.open-meteo.com/v1/search?" +
                      urllib.parse.urlencode({"name": city, "count": 1, "language": "ru"}))
        r = (g.get("results") or [None])[0]
        if r:
            return r["name"], r["latitude"], r["longitude"]
        return city, None, None
    for url in ("https://ipapi.co/json/", "http://ip-api.com/json/?lang=ru"):
        try:
            d = _get_json(url)
            lat, lon = d.get("latitude", d.get("lat")), d.get("longitude", d.get("lon"))
            if lat is not None:
                return d.get("city") or "ваш город", lat, lon
        except Exception:
            continue
    raise RuntimeError("не удалось определить город (задайте WEATHER_CITY в .env)")


def _num(n):
    n = round(float(n))
    return "ноль градусов" if n == 0 else (f"плюс {n}" if n > 0 else f"минус {-n}")


def _fmt_open_meteo(name, w, day):
    c, d = w["current"], w["daily"]
    i = 1 if day == "tomorrow" else 0
    desc = WMO.get(d["weather_code"][i] if day == "tomorrow" else c["weather_code"], "")
    prob = d.get("precipitation_probability_max", [None, None])[i]
    parts = []
    if day == "today":
        parts.append(f"Сейчас {_num(c['temperature_2m'])}, ощущается как {_num(c['apparent_temperature'])}, {desc}.")
    else:
        parts.append(f"Завтра {desc}.")
    parts.append(f"{'Сегодня' if day == 'today' else 'Завтра'} днём до {_num(d['temperature_2m_max'][i])}, "
                 f"ночью до {_num(d['temperature_2m_min'][i])}.")
    if prob is not None and prob >= 30:
        parts.append(f"Вероятность осадков {int(prob)} процентов.")
    if day == "today" and c.get("wind_speed_10m", 0) >= 6:
        parts.append(f"Ветер {round(c['wind_speed_10m'])} метров в секунду.")
    return f"Город: {name}. " + " ".join(parts)


def _fmt_wttr(name, w, day):
    c = w["current_condition"][0]
    i = 1 if day == "tomorrow" else 0
    dd = w["weather"][i]
    desc = (c.get("lang_ru") or c.get("weatherDesc") or [{"value": ""}])[0]["value"].lower()
    rain = max(int(h.get("chanceofrain", 0)) for h in dd["hourly"])
    parts = []
    if day == "today":
        parts.append(f"Сейчас {_num(c['temp_C'])}, ощущается как {_num(c['FeelsLikeC'])}, {desc}.")
    parts.append(f"{'Сегодня' if day == 'today' else 'Завтра'} днём до {_num(dd['maxtempC'])}, ночью до {_num(dd['mintempC'])}.")
    if rain >= 30:
        parts.append(f"Вероятность осадков {rain} процентов.")
    return f"Город: {name}. " + " ".join(parts)


def weather_report(day="today") -> str:
    """Бесплатно и без ключей: Open-Meteo, а при сбое wttr.in."""
    name, lat, lon = _location()
    if lat is not None:
        try:
            q = urllib.parse.urlencode({
                "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2, "wind_speed_unit": "ms",
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"})
            return _fmt_open_meteo(name, _get_json("https://api.open-meteo.com/v1/forecast?" + q), day)
        except Exception:
            pass
    w = _get_json(f"https://wttr.in/{urllib.parse.quote(name)}?format=j1&lang=ru")
    return _fmt_wttr(name, w, day)
