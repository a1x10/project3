"""Сценарий мультика от модели -> проверенный план для рендера (бета).

Модель пишет JSON; здесь всё приводится к допустимому: неизвестное — к похожему или выкидывается (с пометкой для
модели), числа зажимаются, тексты обрезаются, эмодзи заменяются тем, что есть в шрифте. Код от модели не исполняется.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import unicodedata
import zlib
from typing import Any

FORMATS = {"square": (720, 720), "wide": (1280, 720), "tall": (720, 1280)}
KINDS = ("cat", "fox", "bunny", "bear", "toy")
KIND_ALIASES = {
    "кот": "cat", "кошка": "cat", "котик": "cat", "котёнок": "cat", "котенок": "cat", "kitty": "cat",
    "лиса": "fox", "лис": "fox", "лисичка": "fox", "заяц": "bunny", "зайка": "bunny", "зайчик": "bunny",
    "кролик": "bunny", "rabbit": "bunny", "медведь": "bear", "мишка": "bear", "медвежонок": "bear",
    "игрушка": "toy", "зверёк": "toy", "зверек": "toy", "3d": "toy", "blob": "toy",
}
DEFAULT_COLORS = {"cat": "#ff9f43", "fox": "#f26a1b", "bunny": "#f4d6e4", "bear": "#a0673a", "toy": "#8cbcff"}
SHAPES = ("gem", "star", "donut", "ball")
SHAPE_ALIASES = {"кристалл": "gem", "алмаз": "gem", "diamond": "gem", "звезда": "star", "пончик": "donut",
                 "бублик": "donut", "torus": "donut", "шар": "ball", "мяч": "ball", "планета": "ball",
                 "sphere": "ball", "planet": "ball"}
DEFAULT_SHAPE_COLORS = {"gem": "#4fd8ff", "star": "#ffd23f", "donut": "#ff8cc6", "ball": "#72cc5a"}
BACKGROUNDS = ("meadow", "sunset", "night")
BG_ALIASES = {"лужайка": "meadow", "поляна": "meadow", "парк": "meadow", "день": "meadow", "day": "meadow",
              "park": "meadow", "закат": "sunset", "вечер": "sunset", "evening": "sunset", "ночь": "night"}
ACTS = ("walk", "wave", "jump", "dance", "spin")
ACT_ALIASES = {"run": "walk", "идёт": "walk", "идет": "walk", "идти": "walk", "бежит": "walk", "ходит": "walk",
               "hop": "jump", "прыгает": "jump", "прыжок": "jump", "машет": "wave", "привет": "wave",
               "танцует": "dance", "танец": "dance", "крутится": "spin", "вращается": "spin", "turn": "spin"}
ACT_SECONDS = {"walk": 1.6, "wave": 1.8, "jump": 0.9, "dance": 2.6, "spin": 1.0}
EMOTIONS = ("neutral", "happy", "laugh", "love", "wow", "sad", "angry", "scared")
EMOTION_ALIASES = {
    "surprised": "wow", "excited": "happy", "cry": "sad", "joy": "happy", "mad": "angry", "fear": "scared",
    "радость": "happy", "рад": "happy", "весёлый": "happy", "веселый": "happy", "смех": "laugh",
    "смеётся": "laugh", "любовь": "love", "влюблён": "love", "удивление": "wow", "удивлён": "wow", "вау": "wow",
    "грусть": "sad", "грустный": "sad", "плачет": "sad", "злой": "angry", "злость": "angry", "страх": "scared",
    "испуг": "scared",
}

MAX_TOTAL = 20.0
MAX_CAST = 4
MAX_THINGS = 3
MAX_SCENES = 4
MAX_EVENTS = 24
MAX_CONFETTI = 4
MAX_SAY = 80
MAX_JSON = 24_000
GROUND_Y = {"square": 0.86, "wide": 0.88, "tall": 0.84}
CHAR_SIZE = {"square": 0.40, "wide": 0.42, "tall": 0.28}

_HEX = re.compile(r"#?([0-9a-fA-F]{6})")
_EMOJI_MAP = {"❤": "♥", "❤️": "♥", "💖": "♥", "💕": "♥", "⭐": "★", "🌟": "★", "🎵": "♪", "🎶": "♪",
              "😊": "☺", "🙂": "☺"}
_KEEP_SYMBOLS = set("♥★☆♪♫☺☻✓№₽«»—–…")


class SpecError(Exception):
    """Понятная модели ошибка в сценарии."""


def clean_text(value: Any, limit: int) -> str:
    """Текст для пузыря: эмодзи — на значки из шрифта, прочее нерисуемое — долой, длина ≤ limit."""
    text = str(value or "")
    for k, v in _EMOJI_MAP.items():
        text = text.replace(k, v)
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in _KEEP_SYMBOLS or cat[0] in "LNP" or ch == " ":
            out.append(ch)
        elif cat[0] == "Z" or ch in "\n\t":
            out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip()[:limit]


def _num(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    return min(hi, max(lo, x))


def _color(value: Any, default: str) -> str:
    m = _HEX.fullmatch(str(value or "").strip())
    return "#" + m.group(1).lower() if m else default


def _pick(value: Any, allowed: tuple[str, ...], aliases: dict[str, str], warnings: list[str], what: str,
          default: str | None) -> str | None:
    if value is None or value == "":
        return default
    key = str(value).strip().lower()
    if key in allowed:
        return key
    if key in aliases:
        return aliases[key]
    close = difflib.get_close_matches(key, list(allowed) + list(aliases), n=1, cutoff=0.6)
    if close:
        got = aliases.get(close[0], close[0])
        warnings.append(f"{what} «{key}» → {got}")
        return got
    warnings.append(f"{what} «{key}» нет (можно: {', '.join(allowed)}) — {'пропустила' if default is None else default}")
    return default


def _id(value: Any) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip().lower())[:24]


def _char_w(c: dict, w: int, h: int) -> float:
    """Ширина персонажа в долях ширины кадра (с ушами и хвостом)."""
    return c["size"] * h / w * (0.62 if c["kind"] == "toy" else 0.8)


def _spread(xs: list[float], gap: float, lo: float, hi: float) -> list[float]:
    """Раздвинуть точки: соседи не ближе gap, все внутри [lo, hi]; порядок слева направо сохраняется."""
    if not xs:
        return []
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    v = [min(hi, max(lo, xs[i])) for i in order]
    if (len(v) - 1) * gap > hi - lo:  # не влезают с таким зазором — поровну по всей ширине
        v = [lo + (hi - lo) * k / max(1, len(v) - 1) for k in range(len(v))] if len(v) > 1 else [(lo + hi) / 2]
    else:
        for k in range(1, len(v)):
            v[k] = max(v[k], v[k - 1] + gap)
        if v[-1] > hi:
            v[-1] = hi
            for k in range(len(v) - 2, -1, -1):
                v[k] = min(v[k], v[k + 1] - gap)
    out = [0.0] * len(xs)
    for k, i in enumerate(order):
        out[i] = round(v[k], 4)
    return out


def parse(raw: Any) -> tuple[dict, list[str], str]:
    """JSON модели -> (план для рендера, предупреждения, подпись к видео). SpecError — если рисовать нечего."""
    if not isinstance(raw, dict):
        raise SpecError("нужен объект сценария: {cast, things?, scenes: [{seconds, place, events}]}")
    try:
        raw_json = json.dumps(raw, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        raise SpecError("сценарий не похож на JSON") from exc
    if len(raw_json) > MAX_JSON:
        raise SpecError("сценарий слишком длинный, сократи")
    warnings: list[str] = []
    fmt = _pick(raw.get("format"), tuple(FORMATS), {"квадрат": "square", "вертикальное": "tall",
                                                     "широкое": "wide"}, warnings, "format", "square")
    w, h = FORMATS[fmt]

    # ---------- персонажи и предметы ----------
    cast: dict[str, dict] = {}
    raw_cast = raw.get("cast") if isinstance(raw.get("cast"), dict) else {}
    for cid, c in list(raw_cast.items())[:MAX_CAST * 2]:
        c = c if isinstance(c, dict) else {"kind": c}
        kind = _pick(c.get("kind") or c.get("base") or cid, KINDS, KIND_ALIASES, warnings, f"cast.{cid}.kind", None)
        if kind is None:
            continue
        if len(cast) >= MAX_CAST:
            warnings.append(f"больше {MAX_CAST} персонажей нельзя — «{cid}» убрала")
            continue
        cast[_id(cid)] = {"kind": kind, "color": _color(c.get("color"), DEFAULT_COLORS[kind]),
                          "eyes": _color(c.get("eyes"), "#3a7bd5"),
                          "size": CHAR_SIZE[fmt] * (0.9 if kind == "toy" else 1.0) * _num(c.get("size"), 1.0, 0.7, 1.3)}
    things: dict[str, dict] = {}
    raw_things = raw.get("things") if isinstance(raw.get("things"), dict) else {}
    for tid, th in list(raw_things.items())[:MAX_THINGS * 2]:
        th = th if isinstance(th, dict) else {"shape": th}
        shape = _pick(th.get("shape") or th.get("kind") or tid, SHAPES, SHAPE_ALIASES, warnings,
                      f"things.{tid}.shape", None)
        if shape is None or _id(tid) in cast:
            continue
        if len(things) >= MAX_THINGS:
            warnings.append(f"больше {MAX_THINGS} предметов нельзя — «{tid}» убрала")
            continue
        things[_id(tid)] = {"shape": shape, "color": _color(th.get("color"), DEFAULT_SHAPE_COLORS[shape]),
                            "size": _num(th.get("size"), 1.0, 0.4, 1.4)}

    def ensure_actor(who: str) -> str | None:
        """Актёр из событий, которого нет в cast: «кот» -> создать кота."""
        if who in cast or who in things:
            return who
        kind = KIND_ALIASES.get(who) or (who if who in KINDS else None)
        if kind and len(cast) < MAX_CAST:
            cast[who] = {"kind": kind, "color": DEFAULT_COLORS[kind], "eyes": "#3a7bd5", "size": CHAR_SIZE[fmt]}
            warnings.append(f"«{who}» не было в cast — добавила")
            return who
        return None

    # ---------- сцены ----------
    raw_scenes = raw.get("scenes")
    if not isinstance(raw_scenes, list):
        raw_scenes = [raw] if isinstance(raw.get("events"), list) else []
    raw_scenes = [s for s in raw_scenes if isinstance(s, dict)][:MAX_SCENES]
    if not raw_scenes:
        raise SpecError("нужна хотя бы одна сцена: scenes: [{seconds, place, events: [...]}]")
    scenes: list[dict] = []
    pending: list[tuple] = []
    for si, rs in enumerate(raw_scenes):
        events = []
        confetti = 0
        prev_end = 0.3
        for ev in (rs.get("events") if isinstance(rs.get("events"), list) else [])[:MAX_EVENTS * 2]:
            if not isinstance(ev, dict):
                continue
            if len(events) >= MAX_EVENTS:
                warnings.append(f"в сцене {si + 1} больше {MAX_EVENTS} событий — лишние убрала")
                break
            t = _num(ev.get("t", ev.get("at")), prev_end, 0.0, MAX_TOTAL)
            fx = ev.get("fx") or ev.get("effect")
            if fx:
                if str(fx).strip().lower() not in ("confetti", "конфетти"):
                    warnings.append(f"эффект «{fx}» пока не умею — только confetti")
                    continue
                if confetti >= MAX_CONFETTI:
                    continue
                confetti += 1
                events.append({"t": t, "fx": "confetti", "x": _num(ev.get("x"), 0.5, 0.05, 0.95),
                               "y": _num(ev.get("y"), 0.3, 0.05, 0.9), "dur": _num(ev.get("dur"), 2.6, 0.8, 4.0)})
                continue
            who = ensure_actor(_id(ev.get("who")))
            if who is None:
                warnings.append(f"событие без понятного «who» ({ev.get('who')!r}) — пропустила")
                continue
            out: dict[str, Any] = {"t": t, "who": who}
            dur = 0.0
            act = _pick(ev.get("do") or ev.get("act"), ACTS, ACT_ALIASES, warnings, "do", None)
            if act and who in things:
                act = "spin"  # предметы умеют только вращаться
            if act:
                out["act"] = act
                if act == "walk":
                    out["to"] = _num(ev.get("to"), 0.5, 0.08, 0.92)
                dur = _num(ev.get("dur"), ACT_SECONDS[act], 0.4, 8.0)
            say = clean_text(ev.get("say"), MAX_SAY) if ev.get("say") else ""
            if say and who in cast:
                out["say"] = say
                dur = max(dur, _num(ev.get("dur"), min(5.0, max(1.2, 0.6 + len(say) / 13)), 0.8, 6.0))
            emo = _pick(ev.get("emotion"), EMOTIONS, EMOTION_ALIASES, warnings, "emotion", None)
            if emo and who in cast:
                out["emotion"] = emo
            if len(out) == 2:
                continue
            out["dur"] = max(dur, 0.4)
            events.append(out)
            prev_end = t + (dur if act or say else 0.0)
        last = max((e["t"] + e.get("dur", 0) for e in events), default=1.2)
        seconds = _num(rs.get("seconds", rs.get("dur")), last + 0.8, 1.5, MAX_TOTAL)
        if seconds < min(last, MAX_TOTAL) - 0.05:  # события не влезают — продлеваем, а не обрезаем молча
            seconds = min(last + 0.5, MAX_TOTAL)
            warnings.append(f"сцена {si + 1}: события идут до {last:.1f} с — продлила сцену до {seconds:.1f} с")
        bg = _pick(rs.get("background") or rs.get("bg"), BACKGROUNDS, BG_ALIASES, warnings, "background", "meadow")
        # кто в кадре: place + участники событий; place не указан — весь cast
        raw_place = rs.get("place") if isinstance(rs.get("place"), dict) else {}
        raw_place = {_id(k): v for k, v in raw_place.items()}
        present = []
        names = list(raw_place) + [e["who"] for e in events if "who" in e]
        if not raw_place:
            names += list(cast)
        for pid in names:
            pid = ensure_actor(pid) if pid not in cast and pid not in things else pid
            if pid and pid not in present:
                present.append(pid)
        if not any(p in cast for p in present):
            present += list(cast)
        if si == 0 and not any(p in things for p in present):
            present += list(things)
        pending.append((si, rs, events, present, raw_place, seconds, bg))

    # персонажи не должны налезать друг на друга и вылезать за кадр: если в сцене их много — все чуть меньше
    zoom_default = 1.06
    crowd = max((sum(1 for p in pend[3] if p in cast) for pend in pending), default=1)
    room = 1 - 2 * (0.5 - 0.5 / zoom_default) - 0.04
    widest = max((_char_w(c, w, h) for c in cast.values()), default=0.0)
    if crowd and widest and crowd * widest > room:
        k = max(0.6, room / (crowd * widest))
        for c in cast.values():
            c["size"] *= k
    for si, rs, events, present, raw_place, seconds, bg in pending:
        actors = [p for p in present if p in cast]
        zoom = _num(rs.get("zoom"), zoom_default, 1.0, 1.3 if len(actors) < 3 else 1.08)  # толпу не обрезаем
        place: dict[str, dict] = {}
        n = max(1, len(actors))
        cw = max((_char_w(cast[a], w, h) for a in actors), default=0.2)
        lo = 0.5 - 0.5 / zoom + cw / 2 + 0.01
        hi = 1 - lo
        wanted = []
        for k, pid in enumerate(actors):
            rp = raw_place.get(pid) if isinstance(raw_place.get(pid), dict) else {}
            default_x = 0.5 if n == 1 else lo + (hi - lo) * k / (n - 1)
            wanted.append(_num(rp.get("x"), default_x, 0.0, 1.0))
        xs = _spread(wanted, cw * 0.92, lo, hi)
        for pid, x, want in zip(actors, xs, wanted, strict=True):
            rp = raw_place.get(pid) if isinstance(raw_place.get(pid), dict) else {}
            facing = str(rp.get("facing") or "").lower()
            face = -1 if facing in ("left", "влево") else 1 if facing in ("right", "вправо") else (1 if x < 0.5 else -1)
            place[pid] = {"x": x, "y": GROUND_Y[fmt] + (0.02 if cast[pid]["kind"] == "toy" else 0.0), "face": face}
            if abs(x - want) > 0.08 and "x" in rp:
                warnings.append(f"сцена {si + 1}: {pid} сдвинула на x={x:.2f}, чтобы не налезал на соседей и край")
        for k, pid in enumerate(p for p in present if p in things):
            rp = raw_place.get(pid) if isinstance(raw_place.get(pid), dict) else {}
            place[pid] = {"x": _num(rp.get("x"), (0.5, 0.22, 0.78)[k % 3], 0.1, 0.9),
                          "y": _num(rp.get("y"), 0.3, 0.15, 0.7)}
        for e in events:
            if e.get("act") == "walk":
                e["to"] = [min(hi, max(lo, e["to"])), place[e["who"]]["y"]] if e["who"] in place else None
        events = [e for e in events if "who" not in e or (e["who"] in place and e.get("to", 0) is not None)]
        # камера наезжает и чуть опускается — но так, чтобы низ кадра не вышел за край фона
        scenes.append({"dur": seconds, "bg": bg, "place": place, "events": events,
                       "camera": [{"t": 0, "zoom": 1.0, "x": 0.5, "y": 0.5},
                                  {"t": seconds, "zoom": zoom, "x": 0.5, "y": 0.5 + min(0.03, 0.5 - 0.5 / zoom)}]})

    total = sum(s["dur"] for s in scenes)
    if total > MAX_TOTAL * 1.5:
        raise SpecError(f"слишком длинно: {total:.0f} с, можно до {MAX_TOTAL:.0f} с — сократи сцены")
    if total > MAX_TOTAL:  # чуть длиннее лимита — сжимаем по времени
        k = MAX_TOTAL / total
        for s in scenes:
            s["dur"] *= k
            s["camera"][1]["t"] = s["dur"]
            for e in s["events"]:
                e["t"] *= k
                e["dur"] = max(0.3, e["dur"] * k)
        warnings.append(f"сжала до {MAX_TOTAL:.0f} с")
    if not cast and not things:
        raise SpecError("в мультике никого нет: добавь cast (kind: " + ", ".join(KINDS) + ")")
    plan = {"fps": 24, "size": [w, h], "seed": zlib.crc32(raw_json.encode()) & 0x7FFFFFFF, "cast": cast,
            "things": things, "scenes": scenes}
    caption = clean_text(raw.get("caption"), 300)
    return plan, warnings[:12], caption
