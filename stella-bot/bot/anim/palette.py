"""Цвета мультика: единая обводка, разбор цветов от модели (#hex и названия по-русски/по-английски), тона кожи,
«игрушечная» палитра и операции над цветом (смешать, осветлить, контраст).

Цвет — кортеж RGB 0..1. Чистый Python, без cairo.
"""

from __future__ import annotations

import difflib
import math
import re

from .ease import hash01
from .model import RGB

INK: RGB = (0.12, 0.09, 0.16)  # единый тёплый почти-чёрный цвет обводки #1F1729


def hx(s: str) -> RGB:
    """«#RRGGBB» или «#RGB» (решётка не обязательна) → RGB 0..1. Неверная строка — ValueError."""
    s = s.strip().lstrip("#")
    if len(s) in (3, 4):
        s = "".join(ch * 2 for ch in s[:3])
    elif len(s) == 8:
        s = s[:6]
    if len(s) != 6:
        raise ValueError(f"не цвет: {s!r}")
    return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)


def _c(*names_and_hex: str) -> dict[str, RGB]:
    *names, value = names_and_hex
    rgb = hx(value)
    return {n: rgb for n in names}


COLOR_NAMES: dict[str, RGB] = {
    **_c("красный", "red", "#ff3b3b"),
    **_c("алый", "scarlet", "#ff2d3d"),
    **_c("бордовый", "maroon", "burgundy", "#8c1c3a"),
    **_c("вишнёвый", "вишневый", "cherry", "#c2185b"),
    **_c("малиновый", "raspberry", "crimson", "#e0245e"),
    **_c("розовый", "pink", "#ff7eb6"),
    **_c("ярко-розовый", "hot pink", "hotpink", "fuchsia", "фуксия", "magenta", "маджента", "#ff3fa4"),
    **_c("коралловый", "coral", "#ff7f6b"),
    **_c("персиковый", "peach", "#ffb38a"),
    **_c("оранжевый", "orange", "#ff9f1c"),
    **_c("рыжий", "ginger", "#e8772e"),
    **_c("морковный", "carrot", "#f26b1d"),
    **_c("жёлтый", "желтый", "yellow", "#ffd23f"),
    **_c("лимонный", "lemon", "#fff04d"),
    **_c("золотой", "золотистый", "gold", "golden", "#f2b822"),
    **_c("горчичный", "mustard", "#d9a520"),
    **_c("бежевый", "beige", "#e8d3b0"),
    **_c("кремовый", "cream", "#fff3d6"),
    **_c("салатовый", "лаймовый", "lime", "#a6e34b"),
    **_c("зелёный", "зеленый", "green", "#3ec46d"),
    **_c("тёмно-зелёный", "темно-зеленый", "dark green", "darkgreen", "#1f7a4a"),
    **_c("изумрудный", "emerald", "#11b07a"),
    **_c("мятный", "mint", "#7ee8c0"),
    **_c("оливковый", "olive", "#8a9a3b"),
    **_c("хаки", "khaki", "#a89f68"),
    **_c("бирюзовый", "turquoise", "teal", "#2ec4b6"),
    **_c("голубой", "light blue", "lightblue", "sky blue", "skyblue", "небесный", "#5cc8ff"),
    **_c("бирюзово-голубой", "cyan", "циан", "aqua", "#3fe0f0"),
    **_c("синий", "blue", "#3a6df0"),
    **_c("тёмно-синий", "темно-синий", "navy", "dark blue", "darkblue", "#2b3a67"),
    **_c("индиго", "indigo", "#4b3fbf"),
    **_c("фиолетовый", "purple", "violet", "#8a4dff"),
    **_c("сиреневый", "лиловый", "lilac", "lavender", "лавандовый", "#b48cff"),
    **_c("сливовый", "plum", "#8e4585"),
    **_c("коричневый", "brown", "#8b5a3c"),
    **_c("шоколадный", "chocolate", "#5c3a21"),
    **_c("каштановый", "chestnut", "#7a3f22"),
    **_c("медный", "copper", "#c8743a"),
    **_c("бронзовый", "bronze", "#b0793a"),
    **_c("песочный", "sand", "sandy", "#e6c88f"),
    **_c("белый", "white", "#ffffff"),
    **_c("снежный", "snow", "#f4f7ff"),
    **_c("серебряный", "серебристый", "silver", "#c3ccd9"),
    **_c("серый", "grey", "gray", "#9aa0ab"),
    **_c("светло-серый", "light grey", "light gray", "lightgray", "#cfd3da"),
    **_c("тёмно-серый", "темно-серый", "dark grey", "dark gray", "darkgray", "графитовый", "graphite", "#4a4e57"),
    **_c("чёрный", "черный", "black", "#1f1729"),
    **_c("блондин", "блонд", "blonde", "blond", "пшеничный", "#f0d27a"),
    **_c("брюнет", "#2d1d17"),
    **_c("шатен", "#6b3f2a"),
    **_c("платиновый", "platinum", "#ece6da"),
}

SKIN_TONES: dict[str, RGB] = {
    "light": hx("#ffe0cf"),
    "fair": hx("#f6c9a8"),
    "tan": hx("#e0a77e"),
    "brown": hx("#b97a52"),
    "dark": hx("#8d5a3b"),
    "deep": hx("#5e3a26"),
}

# 24 сочных «игрушечных» цвета по кругу оттенков (поверх них хорошо смотрится обводка INK)
TOY_COLORS: tuple[RGB, ...] = tuple(hx(s) for s in (
    "#ff3b3b", "#ff5d8f", "#ff7eb6", "#ff3fa4", "#e0245e", "#ff7f6b",
    "#ff9f1c", "#ffb347", "#ffd23f", "#fff04d", "#a6e34b", "#7cdf6b",
    "#3ec46d", "#06d6a0", "#2ec4b6", "#3fe0f0", "#3ec1ff", "#5cc8ff",
    "#3a6df0", "#5b4bd6", "#7b6cf6", "#8a4dff", "#b06bff", "#b48cff",
))


# ---------- операции ----------
def _c01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def mul(c: RGB, k: float) -> RGB:
    return (_c01(c[0] * k), _c01(c[1] * k), _c01(c[2] * k))


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def lighten(c: RGB, t: float) -> RGB:
    return mix(c, (1.0, 1.0, 1.0), t)


def darken(c: RGB, t: float) -> RGB:
    return mix(c, (0.0, 0.0, 0.0), t)


def luminance(c: RGB) -> float:
    """Относительная яркость по WCAG (0 — чёрный, 1 — белый)."""

    def lin(v: float) -> float:
        v = _c01(v)
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def contrast(a: RGB, b: RGB) -> float:
    """Контраст по WCAG: 1 (одинаковые) … 21 (чёрный на белом)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(c: RGB, bg: RGB, min_ratio: float = 1.6) -> RGB:
    """Если цвет почти сливается с фоном — сдвинуть его светлоту шагами по 12 % от фона (на светлом — темнее,
    на тёмном — светлее), пока контраст не станет ≥ min_ratio. Достаточно контрастный цвет не меняется."""
    if contrast(c, bg) >= min_ratio:
        return c
    first = darken if luminance(bg) > 0.18 else lighten
    second = lighten if first is darken else darken
    best, best_k = c, contrast(c, bg)
    for fn in (first, second):
        cur = c
        for _ in range(8):
            cur = fn(cur, 0.12)
            k = contrast(cur, bg)
            if k >= min_ratio:
                return cur
            if k > best_k:
                best, best_k = cur, k
    return best


def pick(seed: int, i: int) -> RGB:
    """i-й цвет «игрушечной» палитры для данного seed: соседние i — разные, 24 подряд не повторяются."""
    n = len(TOY_COLORS)
    start = int(hash01(seed, "palette") * n)
    return TOY_COLORS[(start + i * 5) % n]


# ---------- разбор цвета от модели ----------
_ENDINGS = ("ого", "его", "ому", "ему", "ыми", "ими", "ый", "ий", "ой", "ая", "яя", "ое", "ее", "ые", "ие",
            "ую", "юю", "ых", "их")
_MODS = {
    "светло": 0.38, "светлый": 0.38, "light": 0.38, "бледно": 0.5, "pale": 0.5, "пастельно": 0.45, "pastel": 0.45,
    "тёмно": -0.38, "темно": -0.38, "тёмный": -0.38, "темный": -0.38, "dark": -0.38, "deep": -0.25,
    "ярко": 0.0, "bright": 0.0, "насыщенно": 0.0,
}


def _norm(s: str) -> str:
    s = s.lower().replace("ё", "е").replace("_", " ")
    return re.sub(r"\s+", " ", s).strip(" .,!;")


def _stem(word: str) -> str:
    for end in _ENDINGS:
        if len(word) >= len(end) + 2 and word.endswith(end):
            return word[: -len(end)]
    return word


_BY_NAME: dict[str, RGB] = {}
_BY_STEM: dict[str, RGB] = {}
for _name, _rgb in COLOR_NAMES.items():
    _n = _norm(_name)
    _BY_NAME.setdefault(_n, _rgb)
    _BY_NAME.setdefault(_n.replace(" ", ""), _rgb)
    _BY_STEM.setdefault(" ".join(_stem(w) for w in re.split(r"[ -]", _n)), _rgb)


def _lookup(name: str) -> RGB | None:
    if name in _BY_NAME:
        return _BY_NAME[name]
    stem = " ".join(_stem(w) for w in re.split(r"[ -]", name) if w)
    if stem in _BY_STEM:
        return _BY_STEM[stem]
    return None


def _parse_name(text: str) -> RGB | None:
    name = _norm(text)
    if not name or len(name) > 40:
        return None
    found = _lookup(name)
    if found is not None:
        return found
    # «светло-зелёный», «dark red», «ярко-жёлтый»: модификатор + основной цвет
    parts = re.split(r"[ -]", name, maxsplit=1)
    if len(parts) == 2 and parts[0] in _MODS:
        base = _lookup(parts[1])
        if base is not None:
            k = _MODS[parts[0]]
            return lighten(base, k) if k > 0 else darken(base, -k) if k < 0 else base
    # опечатка («крассный», «purpel»)
    close = difflib.get_close_matches(name, list(_BY_NAME), n=1, cutoff=0.8)
    return _BY_NAME[close[0]] if close else None


_HEX_RE = re.compile(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)")


def _from_numbers(vals: list[float]) -> RGB | None:
    if len(vals) < 3 or not all(math.isfinite(v) for v in vals[:3]):
        return None
    r, g, b = vals[:3]
    if max(r, g, b) > 1.0:  # 0..255
        r, g, b = r / 255.0, g / 255.0, b / 255.0
    return (_c01(r), _c01(g), _c01(b))


def parse_color(value: object, default: RGB | None = None) -> RGB | None:
    """Цвет от модели → RGB 0..1. Понимает «#RRGGBB», «#RGB», «rgb(…)», [r, g, b] (0..1 или 0..255),
    названия по-русски и по-английски в любом роде («красная», «синее»), с «светло-/тёмно-», с мелкими
    опечатками. Всё непонятное — default."""
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (list, tuple)):
        try:
            got = _from_numbers([float(v) for v in value[:3]])
        except (TypeError, ValueError):
            got = None
        return got if got is not None else default
    if not isinstance(value, str):
        return default
    text = value.strip()[:60]
    m = _HEX_RE.fullmatch(text)
    if m and (text.startswith("#") or not text.isalpha() or len(m.group(1)) == 6):
        try:
            return hx(m.group(1))
        except ValueError:
            return default
    m = _RGB_RE.match(text.lower())
    if m:
        try:
            got = _from_numbers([float(m.group(i)) for i in (1, 2, 3)])
        except ValueError:
            got = None
        return got if got is not None else default
    got = _parse_name(text)
    return got if got is not None else default
