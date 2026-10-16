"""Фоны мультика: 12 сцен (catalog.BACKGROUNDS) × 4 времени суток (catalog.TIMES), с параллаксом слоёв.

Каждый фон — 3–5 слоёв с разным параллаксом (небо 0.1, дальний план 0.3, средний 0.6, стена 0.85, земля 1.0).
Неподвижная часть слоя рисуется ОДИН раз на процесс в поверхность с полями за краями кадра (camera.layer_margin)
и потом только копируется (быстро: целый сдвиг ≈ 0.3 мс, дробный/масштаб ≈ 1 мс). Живые детали — облака,
мерцание звёзд, окна, прожекторы, волны, водоросли, светлячки, стрелки часов, огоньки — рисуются каждый кадр
поверх своего слоя и зависят только от t (кадр — чистая функция времени).

Координаты — пиксели кадра w×h в покое камеры («мир» слоя); масштаб деталей u = min(w, h) / 720.
Погоду (снег, дождь) здесь не рисуем — это эффекты particles; пасмурное небо при weather snow/rain — рисуем.
"""

from __future__ import annotations

import math
import random
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

import cairocffi as cairo

from . import catalog
from .camera import Cam, apply_cam, layer_margin
from .draw import FONT, clean_text, ellipse, fill_union, rrect, sparkle, star, text_path, wrap
from .ease import clamp, hash01, noise1, rng, smoothstep
from .model import RGB, BackgroundSpec
from .palette import INK, hx, lighten, mix, mul

Region = tuple[int, int, int, int]  # x0, y0, x1, y1 — пиксели слоя

# где начинается земля/пол (доля высоты): ступни актёров (layout.GROUND 0.86–0.95) всегда ниже
HORIZON: dict[str, float] = {
    "park": 0.70, "city": 0.74, "forest": 0.72, "beach": 0.70, "space": 0.76, "room": 0.70, "classroom": 0.70,
    "stage": 0.71, "party": 0.70, "winter": 0.72, "underwater": 0.75, "sky": 0.77,
}
OUTDOOR = frozenset({"park", "city", "forest", "beach", "winter", "sky"})
MAX_SETS = 2  # сколько фонов держать в кеше (на переходе нужны два)


def ground_line(bg: BackgroundSpec) -> float:
    """Где «земля» (доля высоты кадра) — верхний край пола/земли; ступни актёров (layout.GROUND) ниже неё."""
    return HORIZON.get(bg.preset, 0.72)


# ======================= палитры по времени суток =======================
SKY: dict[str, tuple[tuple[float, str], ...]] = {
    "day": ((0.0, "#2f8ff0"), (0.55, "#79c3ff"), (1.0, "#d8f2ff")),
    "sunset": ((0.0, "#2c1d6b"), (0.35, "#8a3a8f"), (0.68, "#ff6d5e"), (0.88, "#ffad4d"), (1.0, "#ffd27a")),
    "evening": ((0.0, "#0f1747"), (0.5, "#33348a"), (0.82, "#7a4c9c"), (1.0, "#d77c96")),
    "night": ((0.0, "#050920"), (0.6, "#0d1642"), (1.0, "#1f2d66")),
}
OVERCAST: dict[str, tuple[tuple[float, str], ...]] = {
    "day": ((0.0, "#7d90a6"), (1.0, "#cdd6df")),
    "sunset": ((0.0, "#4b3f5e"), (1.0, "#c39189")),
    "evening": ((0.0, "#20253f"), (1.0, "#5d5878")),
    "night": ((0.0, "#0a0d1b"), (1.0, "#272c42")),
}
# свет на предметах: (цвет оттенка, его доля, яркость)
LIGHT: dict[str, tuple[RGB, float, float]] = {
    "day": ((1.0, 1.0, 1.0), 0.0, 1.0),
    "sunset": ((1.0, 0.55, 0.45), 0.22, 0.92),
    "evening": ((0.38, 0.34, 0.7), 0.36, 0.74),
    "night": ((0.12, 0.17, 0.4), 0.5, 0.52),
}
INDOOR_LIGHT: dict[str, tuple[RGB, float, float]] = {
    "day": ((1.0, 1.0, 1.0), 0.0, 1.0),
    "sunset": ((1.0, 0.7, 0.5), 0.12, 0.97),
    "evening": ((1.0, 0.75, 0.5), 0.12, 0.86),
    "night": ((0.35, 0.3, 0.6), 0.22, 0.72),
}
HAZE: dict[str, str] = {"day": "#cfe8ff", "sunset": "#ffae8c", "evening": "#8c6cb3", "night": "#24315f"}
CLOUD: dict[str, tuple[str, str, str]] = {  # верх, низ, контур
    "day": ("#ffffff", "#d7e7f7", "#9fbad6"),
    "sunset": ("#ffd9c4", "#e8879f", "#a95a7c"),
    "evening": ("#b9a7da", "#6f5f9f", "#4b3f78"),
    "night": ("#3b4675", "#242c55", "#171d3d"),
}
WINDOW_LIT = (1.0, 0.85, 0.45)
CONFETTI = ("#ff3d6e", "#ffd23f", "#3ec1ff", "#7cff6b", "#b48cff", "#ff9f1c")


# ======================= сцена и слои =======================
class _S:
    """Всё, что нужно рисованию одного фона: размеры, время суток, свет, генераторы случайностей."""

    def __init__(self, bg: BackgroundSpec, w: int, h: int, seed: int):
        self.preset = bg.preset if bg.preset in catalog.BACKGROUNDS else "park"
        self.time = bg.time if bg.time in catalog.TIMES else "day"
        self.weather = bg.weather if bg.weather in catalog.WEATHER else "clear"
        self.text = bg.text if isinstance(bg.text, str) else ""
        self.accent = bg.accent
        self.w, self.h = int(w), int(h)
        self.u = min(w, h) / 720.0
        self.seed = int(seed)
        self.gy = HORIZON[self.preset] * h
        self.dark = self.time in ("evening", "night")
        self.night = self.time == "night"
        self.overcast = self.weather in ("snow", "rain") and self.preset in OUTDOOR
        self.indoor = self.preset in ("room", "classroom", "stage", "party")
        self.key = (self.preset, self.time, self.weather, self.text, self.accent, self.w, self.h, self.seed)
        self.memo: dict = {}  # спрайты и заранее посчитанные списки живых деталей (живут в кеше вместе с фоном)

    def r(self, *key: object) -> random.Random:
        return rng(self.seed, "bg", self.preset, *key)

    def lit(self, c: RGB | str, depth: float = 0.0, indoor: bool | None = None) -> RGB:
        """Цвет предмета при освещении этого времени суток; depth 0..1 — дымка дали."""
        c = hx(c) if isinstance(c, str) else c
        if depth > 0:
            c = mix(c, self.haze, depth * 0.6)
        ind = self.indoor if indoor is None else indoor
        tint, k, bright = (INDOOR_LIGHT if ind else LIGHT)[self.time]
        if self.overcast and not ind:
            c = mix(c, (0.55, 0.6, 0.66), 0.25)
            bright *= 0.9
        return mul(mix(c, tint, k), bright)

    @property
    def haze(self) -> RGB:
        return mix(hx(HAZE[self.time]), (0.6, 0.64, 0.7), 0.5) if self.overcast else hx(HAZE[self.time])

    def edge(self, c: RGB) -> RGB:
        """Мягкий контур деталей фона — темнее заливки, но не чёрный (персонажи с INK должны «выпрыгивать»)."""
        return mix(mul(c, 0.5), INK, 0.3)


@dataclass(frozen=True)
class _Layer:
    p: float  # параллакс
    static: Callable[[cairo.Context, _S, Region], None] | None = None
    anim: Callable[[cairo.Context, _S, float, Region], None] | None = None
    y0: float = -9.0  # где по высоте (доли h) есть неподвижное содержимое слоя — поверхность обрезается
    y1: float = 9.0


def _region(s: _S, layer: _Layer) -> Region:
    mx, my = layer_margin(s.w, s.h, layer.p)
    y0 = max(-my, int(math.floor(layer.y0 * s.h)) - 2)
    y1 = min(s.h + my, int(math.ceil(layer.y1 * s.h)) + 2)
    return -mx, y0, s.w + mx, max(y0 + 1, y1)


def _sets(cache: dict) -> OrderedDict:
    sets = cache.get("bg_sets")
    if not isinstance(sets, OrderedDict):
        sets = cache["bg_sets"] = OrderedDict()
    return sets


def _scene(bg: BackgroundSpec, w: int, h: int, seed: int, cache: dict) -> tuple[_S, list[_Layer], dict]:
    probe = _S(bg, w, h, seed)
    sets = _sets(cache)
    entry = sets.get(probe.key)
    if entry is None:
        entry = {"scene": probe, "layers": PRESETS[probe.preset](probe), "surf": {}}
        sets[probe.key] = entry
        while len(sets) > MAX_SETS:
            sets.popitem(last=False)
    else:
        sets.move_to_end(probe.key)
    return entry["scene"], entry["layers"], entry["surf"]


def _surface(s: _S, layer: _Layer, idx: int, store: dict) -> tuple[cairo.ImageSurface, int, int]:
    got = store.get(idx)
    if got is not None:
        return got
    x0, y0, x1, y1 = _region(s, layer)
    fmt = cairo.FORMAT_RGB24 if idx == 0 else cairo.FORMAT_ARGB32
    surf = cairo.ImageSurface(fmt, x1 - x0, y1 - y0)
    ctx = cairo.Context(surf)
    ctx.translate(-x0, -y0)
    if idx == 0:
        ctx.set_source_rgb(*s.haze)
        ctx.paint()
    assert layer.static is not None
    layer.static(ctx, s, (x0, y0, x1, y1))
    surf.flush()
    store[idx] = (surf, x0, y0)
    return store[idx]


def draw_background(ctx: cairo.Context, bg: BackgroundSpec, w: int, h: int, t: float, cam: Cam, seed: int,
                    cache: dict) -> None:
    """Весь задник целиком в кадр w×h в момент t (секунды; живые детали — функции t). Параллакс слоёв применяет
    сам (ctx — без камеры). Неподвижные слои кешируются в cache (не больше MAX_SETS фонов)."""
    s, layers, store = _scene(bg, w, h, seed, cache)
    t = t if math.isfinite(t) else 0.0
    for idx, layer in enumerate(layers):
        ctx.save()
        apply_cam(ctx, cam, w, h, layer.p)
        if layer.static is not None:
            surf, x0, y0 = _surface(s, layer, idx, store)
            ctx.set_source_surface(surf, x0, y0)
            ctx.get_source().set_filter(cairo.FILTER_BILINEAR)
            ctx.rectangle(x0, y0, surf.get_width(), surf.get_height())
            ctx.fill()
        if layer.anim is not None:
            ctx.new_path()
            layer.anim(ctx, s, t, _region(s, layer))
        ctx.restore()
    ctx.new_path()


# ======================= общие кирпичики =======================
def _vgrad(ctx: cairo.Context, x0: float, y0: float, x1: float, y1: float, stops, ya: float | None = None,
           yb: float | None = None) -> None:
    """Залить прямоугольник вертикальным градиентом; stops — ((доля, цвет), …), растянуты на [ya, yb]."""
    ya = y0 if ya is None else ya
    yb = y1 if yb is None else yb
    g = cairo.LinearGradient(0, ya, 0, max(yb, ya + 1))
    for off, c in stops:
        g.add_color_stop_rgb(off, *(hx(c) if isinstance(c, str) else c))
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
    ctx.set_source(g)
    ctx.fill()


def _grad(y0: float, y1: float, *stops) -> cairo.LinearGradient:
    g = cairo.LinearGradient(0, y0, 0, max(y1, y0 + 1))
    for off, c in stops:
        if len(c) == 4:
            g.add_color_stop_rgba(off, *c)
        else:
            g.add_color_stop_rgb(off, *c)
    return g


def _glow(ctx: cairo.Context, x: float, y: float, r: float, color: RGB, alpha: float, add: bool = False,
          sy: float = 1.0) -> None:
    """Мягкое свечение: радиальный градиент от alpha в центре к нулю на радиусе r (sy — сплющить по вертикали)."""
    if r <= 0.5 or alpha <= 0:
        return
    ctx.save()
    if add:
        ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.translate(x, y)
    ctx.scale(1.0, sy)
    g = cairo.RadialGradient(0, 0, 0, 0, 0, r)
    g.add_color_stop_rgba(0, *color, alpha)
    g.add_color_stop_rgba(0.35, *color, alpha * 0.45)
    g.add_color_stop_rgba(1, *color, 0)
    ctx.set_source(g)
    ctx.arc(0, 0, r, 0, 2 * math.pi)
    ctx.fill()
    ctx.restore()


def _sprite(s: _S, key: object, w: float, h: float, draw: Callable[[cairo.Context], None]) -> cairo.ImageSurface:
    """Спрайт w×h, нарисованный один раз (draw рисует в своих координатах 0..w, 0..h) и сохранённый в s.memo."""
    sp = s.memo.get(("sprite", key))
    if sp is None:
        sp = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, int(math.ceil(w))), max(1, int(math.ceil(h))))
        draw(cairo.Context(sp))
        sp.flush()
        s.memo[("sprite", key)] = sp
    return sp


def _blit(ctx: cairo.Context, sp: cairo.ImageSurface, x: float, y: float, alpha: float = 1.0,
          rot: float = 0.0, px: float = 0.0, py: float = 0.0) -> None:
    """Нарисовать спрайт так, чтобы его точка (px, py) попала в (x, y); rot — поворот вокруг этой точки."""
    if alpha <= 0.0:
        return
    ctx.save()
    ctx.translate(x, y)
    if rot:
        ctx.rotate(rot)
    ctx.set_source_surface(sp, -px, -py)
    ctx.get_source().set_filter(cairo.FILTER_BILINEAR)
    ctx.rectangle(-px, -py, sp.get_width(), sp.get_height())
    if alpha >= 1.0:
        ctx.fill()
    else:
        ctx.clip()
        ctx.paint_with_alpha(alpha)
    ctx.restore()


def _glow_sprite(s: _S, key: object, color: RGB, r: float, alpha: float, sy: float = 1.0) -> cairo.ImageSurface:
    """Свечение _glow готовым спрайтом (2r × 2r·sy): для живых деталей, которые двигаются каждый кадр."""
    hgt = max(2.0, 2 * r * sy)

    def draw(c: cairo.Context) -> None:
        _glow(c, r, hgt / 2, r, color, alpha, sy=sy)

    return _sprite(s, ("glow", key, round(r, 2)), 2 * r, hgt, draw)


def _beam(ctx: cairo.Context, x: float, y: float, a: float, ln: float, w0: float, w1: float, col: RGB,
          alpha: float) -> None:
    """Луч прожектора: два вложенных конуса сплошной заливкой (градиент на всю высоту кадра слишком дорог)."""
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(a)
    for k, (wk, lk) in enumerate(((1.0, 1.0), (0.55, 0.8))):
        ctx.move_to(-w0 * wk, 0)
        ctx.line_to(w0 * wk, 0)
        ctx.line_to(w1 * wk, ln * lk)
        ctx.line_to(-w1 * wk, ln * lk)
        ctx.close_path()
        ctx.set_source_rgba(*col, alpha * (1.0 if k == 0 else 0.8))
        ctx.fill()
    ctx.restore()


def _fill_edge(ctx: cairo.Context, fill, edge: RGB | None, lw: float) -> None:
    if isinstance(fill, cairo.Pattern):
        ctx.set_source(fill)
    else:
        ctx.set_source_rgb(*fill)
    if edge is None or lw <= 0:
        ctx.fill()
        return
    ctx.fill_preserve()
    ctx.set_source_rgb(*edge)
    ctx.set_line_width(lw)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


def _sky_stops(s: _S) -> tuple[tuple[float, str], ...]:
    return OVERCAST[s.time] if s.overcast else SKY[s.time]


def _paint_sky(ctx: cairo.Context, s: _S, rg: Region, horizon: float | None = None) -> None:
    x0, y0, x1, y1 = rg
    hz = s.gy if horizon is None else horizon
    _vgrad(ctx, x0, y0, x1, y1, _sky_stops(s), ya=0.0, yb=hz)


def _star_field(s: _S, rg: Region, n: int, y_max: float, key: str = "stars") -> list[tuple[float, float, float, float]]:
    """Звёзды: (x, y, радиус, фаза) — плотность n на площадь кадра."""
    x0, y0, x1, _ = rg
    area = (x1 - x0) * max(1.0, y_max - y0) / max(1.0, s.w * s.h * 0.6)
    r = s.r(key)
    out = []
    for _ in range(int(n * area)):
        out.append((r.uniform(x0, x1), r.uniform(y0, y_max), r.uniform(0.6, 1.9) * s.u, r.random()))
    return out


def _stars_static(ctx: cairo.Context, s: _S, rg: Region, n: int, y_max: float, alpha: float = 0.85) -> None:
    for x, y, rr, ph in _star_field(s, rg, n, y_max):
        ctx.arc(x, y, rr * 0.7, 0, 2 * math.pi)
        ctx.new_sub_path()
    ctx.set_source_rgba(1, 0.97, 0.88, alpha)
    ctx.fill()


def _twinkle(ctx: cairo.Context, s: _S, t: float, rg: Region, n: int, y_max: float, key: str = "twinkle",
             color: RGB = (1.0, 0.96, 0.85)) -> None:
    """Мерцающие звёздочки-искры (рисуются каждый кадр; яркость — 4 ступени, по одной заливке на ступень)."""
    mk = ("stars", key, rg, n, y_max)
    stars = s.memo.get(mk)
    if stars is None:
        stars = s.memo[mk] = _star_field(s, rg, n, y_max, key)
    buckets: list[list[tuple[int, float, float, float]]] = [[], [], [], []]
    for i, (x, y, rr, ph) in enumerate(stars):
        k = 0.5 + 0.5 * math.sin(t * (1.3 + 1.7 * ph) + ph * 40.0)
        b = min(3, int(k * k * 4))
        buckets[b].append((i, x, y, rr))
    for b, items in enumerate(buckets):
        if not items:
            continue
        k = (b + 0.5) / 4
        for i, x, y, rr in items:
            ctx.new_sub_path()
            if i % 3 == 0:
                sparkle(ctx, x, y, (2.2 + 3.4 * k) * rr)
            else:
                ctx.arc(x, y, rr * (0.6 + 0.5 * k), 0, 2 * math.pi)
        ctx.set_source_rgba(*color, 0.3 + 0.7 * k)
        ctx.fill()


def _sun(ctx: cairo.Context, s: _S, x: float, y: float, r: float) -> None:
    if s.overcast:
        _glow(ctx, x, y, r * 4, (1, 1, 1), 0.18)
        return
    if s.time == "sunset":
        _glow(ctx, x, y, r * 5.0, (1.0, 0.62, 0.35), 0.55)
        g = cairo.RadialGradient(x - r * 0.2, y - r * 0.3, r * 0.1, x, y, r)
        g.add_color_stop_rgb(0, 1.0, 0.97, 0.78)
        g.add_color_stop_rgb(1, 1.0, 0.62, 0.3)
        ctx.arc(x, y, r, 0, 2 * math.pi)
        ctx.set_source(g)
        ctx.fill()
        # полоски облаков поперёк солнца
        for i, (dy, ww) in enumerate(((0.25, 1.6), (0.52, 2.2), (-0.1, 1.2))):
            rrect(ctx, x - r * ww * (0.7 + 0.15 * i), y + dy * r, r * ww * 1.4, r * 0.11 * (1.6 - 0.3 * i),
                  r * 0.06)
        ctx.set_source_rgba(0.55, 0.22, 0.45, 0.55)
        ctx.fill()
        return
    _glow(ctx, x, y, r * 4.2, (1.0, 0.97, 0.78), 0.5)
    _glow(ctx, x, y, r * 1.8, (1.0, 0.95, 0.7), 0.6)
    g = cairo.RadialGradient(x - r * 0.25, y - r * 0.3, r * 0.1, x, y, r)
    g.add_color_stop_rgb(0, 1.0, 1.0, 0.9)
    g.add_color_stop_rgb(1, 1.0, 0.86, 0.35)
    ctx.arc(x, y, r, 0, 2 * math.pi)
    ctx.set_source(g)
    ctx.fill()


def _moon(ctx: cairo.Context, s: _S, x: float, y: float, r: float, alpha: float = 1.0) -> None:
    _glow(ctx, x, y, r * 3.6, (0.85, 0.9, 1.0), 0.28 * alpha)
    g = cairo.RadialGradient(x - r * 0.3, y - r * 0.35, r * 0.1, x, y, r)
    g.add_color_stop_rgba(0, 1.0, 0.99, 0.9, alpha)
    g.add_color_stop_rgba(1, 0.93, 0.88, 0.7, alpha)
    ctx.arc(x, y, r, 0, 2 * math.pi)
    ctx.set_source(g)
    ctx.fill()
    for dx, dy, cr in ((-0.32, -0.12, 0.2), (0.25, 0.28, 0.14), (0.18, -0.38, 0.1), (-0.1, 0.42, 0.08)):
        ctx.arc(x + dx * r, y + dy * r, cr * r, 0, 2 * math.pi)
        ctx.new_sub_path()
    ctx.set_source_rgba(0.78, 0.72, 0.58, 0.45 * alpha)
    ctx.fill()


def _sky_body(ctx: cairo.Context, s: _S, x: float, y: float, r: float) -> None:
    """Солнце днём, большое низкое — на закате, луна вечером (бледная) и ночью."""
    if s.time == "day":
        _sun(ctx, s, x, y, r)
    elif s.time == "sunset":
        _sun(ctx, s, x, s.gy - r * 0.55, r * 1.5)
    elif s.time == "evening":
        if not s.overcast:
            _moon(ctx, s, x, y + r * 0.8, r * 0.75, 0.75)
    elif not s.overcast:
        _moon(ctx, s, x, y, r * 0.85)


def _cloud_puffs(r: random.Random, n: int) -> list[tuple[float, float, float]]:
    """Форма облака: круги (dx, dy, радиус) в долях размера; низ плоский."""
    puffs = []
    for i in range(n):
        f = i / max(1, n - 1)
        dx = (f - 0.5) * 2.0
        rr = 0.32 + 0.3 * math.sin(math.pi * f) + r.uniform(-0.05, 0.08)
        puffs.append((dx * 0.85, -rr * 0.55 + r.uniform(-0.05, 0.05), rr))
    return puffs


def _cloud(ctx: cairo.Context, s: _S, x: float, y: float, size: float, puffs, alpha: float = 1.0,
           colors: tuple[str, str, str] | None = None, lw: float | None = None) -> None:
    top, bot, edge = (hx(c) for c in (colors or CLOUD[s.time]))
    if s.overcast:
        top, bot, edge = (mix(c, (0.62, 0.66, 0.72), 0.45) for c in (top, bot, edge))

    def path() -> None:
        for dx, dy, rr in puffs:
            ctx.new_sub_path()
            ctx.arc(x + dx * size, y + dy * size, rr * size, 0, 2 * math.pi)
        rrect(ctx, x - size * 0.95, y - size * 0.3, size * 1.9, size * 0.42, size * 0.2)

    g = _grad(y - size * 0.9, y + size * 0.12, (0, (*top, alpha)), (0.55, (*top, alpha)), (1, (*bot, alpha)))
    if alpha >= 0.999:
        fill_union(ctx, path, g, (lw if lw is not None else 1.6 * s.u), edge)
    else:
        ctx.push_group()
        fill_union(ctx, path, _grad(y - size, y + size * 0.12, (0, top), (0.55, top), (1, bot)),
                   (lw if lw is not None else 1.6 * s.u), edge)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(alpha)


def _cloud_sprite(s: _S, key: object, size: float, puffs, alpha: float = 1.0,
                  colors: tuple[str, str, str] | None = None) -> tuple[cairo.ImageSurface, float, float]:
    """Облако как спрайт: (поверхность, x и y точки привязки внутри неё)."""
    ox, oy = math.ceil(size * 1.3 + 6 * s.u), math.ceil(size * 1.2 + 6 * s.u)

    def draw(c: cairo.Context) -> None:
        _cloud(c, s, ox, oy, size, puffs, alpha, colors)

    return _sprite(s, ("cloud", key, round(size, 3)), ox * 2, oy + size * 0.5 + 8 * s.u, draw), ox, oy


def _clouds_anim(n: int = 4, y_lo: float = 0.07, y_hi: float = 0.33, size: tuple[float, float] = (55, 95),
                 speed: tuple[float, float] = (5, 12)) -> Callable[[cairo.Context, _S, float, Region], None]:
    """Облака, которые медленно плывут (их форма и места — от seed; рисуются готовыми спрайтами)."""

    def anim(ctx: cairo.Context, s: _S, t: float, rg: Region) -> None:
        x0, _, x1, _ = rg
        mk = ("clouds", n, y_lo, y_hi, rg)
        clouds = s.memo.get(mk)
        if clouds is None:
            r = s.r("clouds")
            span = (x1 - x0) + 400 * s.u
            k = max(1, round(n * (x1 - x0) / max(1, s.w * 1.4)))
            clouds = []
            for i in range(k):
                sz = r.uniform(*size) * s.u
                sp = r.uniform(*speed) * s.u
                y = s.h * r.uniform(y_lo, y_hi) if s.h <= s.w * 1.2 else s.h * r.uniform(y_lo, y_hi * 0.8)
                base = (i + r.uniform(0.1, 0.9)) * span / k
                sprite = _cloud_sprite(s, (mk, i), sz, _cloud_puffs(r, r.randint(4, 6)), 0.8 if s.night else 1.0)
                clouds.append((base, sp, y, sprite, span))
            s.memo[mk] = clouds
        for base, sp, y, (sprite, ox, oy), span in clouds:
            x = x0 - 200 * s.u + (base + sp * t) % span
            _blit(ctx, sprite, x, y, px=ox, py=oy)

    return anim


def _hill_path(ctx: cairo.Context, s: _S, rg: Region, base: float, amp: float, lam: float, ph: float,
               bottom: float) -> list[tuple[float, float]]:
    x0, _, x1, _ = rg
    step = max(6.0, 14 * s.u)
    pts = []
    x = x0 - step
    while x <= x1 + step:
        v = 0.6 * math.sin(x / lam + ph) + 0.4 * math.sin(x / (lam * 0.47) + ph * 2.3)
        pts.append((x, base - amp * (0.55 + 0.45 * v)))
        x += step
    ctx.move_to(pts[0][0], bottom)
    for p in pts:
        ctx.line_to(*p)
    ctx.line_to(pts[-1][0], bottom)
    ctx.close_path()
    return pts


def _hills(ctx: cairo.Context, s: _S, rg: Region, base: float, amp: float, lam: float, ph: float, top: RGB,
           bottom: RGB, edge: RGB | None = None, lw: float = 0.0) -> list[tuple[float, float]]:
    yb = rg[3] + 4
    pts = _hill_path(ctx, s, rg, base, amp, lam, ph, yb)
    ctx.set_source(_grad(base - amp, base + (yb - base) * 0.4, (0, top), (1, bottom)))
    ctx.fill()
    if edge is not None and lw > 0:
        ctx.move_to(*pts[0])
        for p in pts[1:]:
            ctx.line_to(*p)
        ctx.set_source_rgb(*edge)
        ctx.set_line_width(lw)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()
    return pts


def _xs(s: _S, rg: Region, key: str, step: tuple[float, float], avoid: tuple[float, float] | None = None,
        pad: float = 120.0) -> list[float]:
    """Места по x через случайный шаг (детерминированно); avoid — полоса (доли w), куда не ставить."""
    x0, _, x1, _ = rg
    r = s.r("xs", key)
    out = []
    x = x0 - pad * s.u + r.uniform(0, step[1]) * s.u
    while x < x1 + pad * s.u:
        if avoid is None or not (avoid[0] * s.w < x < avoid[1] * s.w):
            out.append(x)
        x += r.uniform(*step) * s.u
    return out


# ----- деревья, кусты, цветы -----
def _canopy_path(ctx: cairo.Context, x: float, y: float, rr: float, lobes) -> None:
    for dx, dy, k in lobes:
        ctx.new_sub_path()
        ctx.arc(x + dx * rr, y + dy * rr, k * rr, 0, 2 * math.pi)


def _lobes(r: random.Random, n: int = 6) -> list[tuple[float, float, float]]:
    out = [(0.0, 0.0, 0.62)]
    for i in range(n):
        a = math.pi * (1.05 + 0.9 * i / max(1, n - 1))  # дуга сверху
        out.append((math.cos(a) * 0.48, math.sin(a) * 0.42 + 0.05, r.uniform(0.38, 0.5)))
    out.append((-0.42, 0.25, 0.4))
    out.append((0.42, 0.25, 0.4))
    return out


def _round_tree(ctx: cairo.Context, s: _S, x: float, gy: float, size: float, leaf: RGB, trunk: RGB,
                lobes, depth: float = 0.0, sway: float = 0.0, lw: float | None = None) -> None:
    lw = (2.4 * s.u) if lw is None else lw
    leaf_c, trunk_c = s.lit(leaf, depth), s.lit(trunk, depth)
    th = size * 0.55
    tw = size * 0.13
    ctx.move_to(x - tw * 0.6, gy)
    ctx.line_to(x - tw * 0.4, gy - th)
    ctx.line_to(x + tw * 0.4, gy - th)
    ctx.line_to(x + tw * 0.6, gy)
    ctx.close_path()
    _fill_edge(ctx, trunk_c, s.edge(trunk_c), lw)
    cx, cy, rr = x + sway * size * 0.08, gy - th - size * 0.28, size * 0.5
    g = cairo.RadialGradient(cx - rr * 0.35, cy - rr * 0.45, rr * 0.1, cx, cy, rr * 1.3)
    g.add_color_stop_rgb(0, *lighten(leaf_c, 0.3))
    g.add_color_stop_rgb(0.6, *leaf_c)
    g.add_color_stop_rgb(1, *mul(leaf_c, 0.72))
    fill_union(ctx, lambda: _canopy_path(ctx, cx, cy, rr, lobes), g, lw * 0.5, s.edge(leaf_c))
    # тень снизу-справа (кроны-объединения: вычитаем сдвинутую копию через группу) и блики
    _union_shadow(ctx, lambda dx, dy: _canopy_path(ctx, cx + dx, cy + dy, rr, lobes), -rr * 0.18, -rr * 0.22,
                  (*mul(leaf_c, 0.7), 0.5), (cx - rr * 2, cy - rr * 2, rr * 4, rr * 4))
    for dx, dy, k in ((-0.38, -0.3, 0.12), (-0.08, -0.52, 0.09), (0.25, -0.35, 0.07)):
        ctx.arc(cx + dx * rr, cy + dy * rr, k * rr, 0, 2 * math.pi)
        ctx.new_sub_path()
    ctx.set_source_rgba(*lighten(leaf_c, 0.45), 0.55)
    ctx.fill()


def _union_shadow(ctx: cairo.Context, path: Callable[[float, float], None], dx: float, dy: float,
                  rgba: tuple[float, float, float, float], box: tuple[float, float, float, float]) -> None:
    """Cel-тень фигуры-объединения (path(0, 0)): внутри фигуры, но вне её копии, сдвинутой на (dx, dy)."""
    ctx.save()
    path(0.0, 0.0)
    ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
    ctx.clip()
    ctx.push_group()
    ctx.rectangle(*box)
    ctx.set_source_rgba(*rgba)
    ctx.fill()
    ctx.set_operator(cairo.OPERATOR_CLEAR)
    path(dx, dy)
    ctx.fill()
    ctx.pop_group_to_source()
    ctx.paint()
    ctx.restore()


def _pine(ctx: cairo.Context, s: _S, x: float, gy: float, size: float, color: RGB, depth: float = 0.0,
          snow: bool = False, lw: float | None = None, sway: float = 0.0) -> None:
    lw = (2.2 * s.u) if lw is None else lw
    c = s.lit(color, depth)
    trunk = s.lit((0.45, 0.28, 0.18), depth)
    ctx.rectangle(x - size * 0.05, gy - size * 0.18, size * 0.1, size * 0.18)
    _fill_edge(ctx, trunk, s.edge(trunk) if lw else None, lw)
    tiers = 4
    for i in range(tiers):
        f = i / (tiers - 1)
        wid = size * (0.36 - 0.2 * f)
        yb = gy - size * (0.12 + 0.22 * i)
        yt = yb - size * (0.42 - 0.05 * i)
        sw = sway * size * 0.03 * (i + 1)
        ctx.move_to(x + sw, yt)
        ctx.curve_to(x + sw + wid * 0.3, yt + (yb - yt) * 0.3, x + wid * 0.8, yb - size * 0.05, x + wid, yb)
        ctx.curve_to(x + wid * 0.5, yb + size * 0.04, x - wid * 0.5, yb + size * 0.04, x - wid, yb)
        ctx.curve_to(x - wid * 0.8, yb - size * 0.05, x + sw - wid * 0.3, yt + (yb - yt) * 0.3, x + sw, yt)
        ctx.close_path()
        g = _grad(yt, yb, (0, lighten(c, 0.18)), (1, mul(c, 0.8)))
        _fill_edge(ctx, g, s.edge(c) if lw else None, lw)
        if snow:
            ctx.move_to(x + sw, yt)
            ctx.curve_to(x + sw + wid * 0.25, yt + (yb - yt) * 0.25, x + wid * 0.55, yt + (yb - yt) * 0.5,
                         x + wid * 0.62, yt + (yb - yt) * 0.6)
            for j in range(4, -5, -1):
                xx = x + wid * 0.62 * j / 4
                ctx.line_to(xx, yt + (yb - yt) * (0.6 - 0.12 * (j % 2)))
            ctx.curve_to(x - wid * 0.55, yt + (yb - yt) * 0.5, x + sw - wid * 0.25, yt + (yb - yt) * 0.25,
                         x + sw, yt)
            ctx.close_path()
            sc = s.lit((0.97, 0.98, 1.0), depth)
            _fill_edge(ctx, sc, s.edge(mul(sc, 0.8)) if lw else None, lw * 0.7)


def _bush(ctx: cairo.Context, s: _S, x: float, gy: float, size: float, color: RGB, depth: float = 0.0,
          lw: float | None = None, berries: bool = False) -> None:
    lw = (2.0 * s.u) if lw is None else lw
    c = s.lit(color, depth)
    lobes = ((-0.55, -0.3, 0.42), (0.0, -0.5, 0.52), (0.55, -0.32, 0.44), (-0.25, -0.2, 0.4), (0.3, -0.2, 0.4))

    def path() -> None:
        for dx, dy, k in lobes:
            ctx.new_sub_path()
            ctx.arc(x + dx * size, gy + dy * size, k * size, 0, 2 * math.pi)
        ctx.rectangle(x - size * 0.9, gy - size * 0.3, size * 1.8, size * 0.3)

    ctx.save()
    ctx.rectangle(x - size * 2, gy - size * 2, size * 4, size * 2)
    ctx.clip()
    g = _grad(gy - size, gy, (0, lighten(c, 0.22)), (1, mul(c, 0.78)))
    fill_union(ctx, path, g, lw * 0.5, s.edge(c))
    ctx.restore()
    if berries:
        r = random.Random(int(x * 13) & 0xFFFF)
        for _ in range(5):
            ctx.arc(x + r.uniform(-0.6, 0.6) * size, gy - r.uniform(0.2, 0.75) * size, size * 0.07, 0, 2 * math.pi)
            ctx.new_sub_path()
        ctx.set_source_rgb(*s.lit((0.95, 0.25, 0.35), depth))
        ctx.fill()


def _flower(ctx: cairo.Context, s: _S, x: float, y: float, size: float, petal: RGB, sway: float = 0.0,
            lw: float | None = None) -> None:
    lw = (1.6 * s.u) if lw is None else lw
    hx_, hy = x + sway * size * 1.2, y - size * 2.2
    ctx.move_to(x, y)
    ctx.curve_to(x, y - size, hx_, hy + size, hx_, hy)
    ctx.set_source_rgb(*s.lit((0.25, 0.6, 0.3)))
    ctx.set_line_width(max(1.0, size * 0.22))
    ctx.stroke()
    pc = s.lit(petal)
    for i in range(5):
        a = i * 2 * math.pi / 5 + sway * 0.5
        ctx.new_sub_path()
        ctx.arc(hx_ + math.cos(a) * size * 0.55, hy + math.sin(a) * size * 0.55, size * 0.45, 0, 2 * math.pi)
    _fill_edge(ctx, pc, s.edge(pc), lw * 0.6)
    ctx.arc(hx_, hy, size * 0.3, 0, 2 * math.pi)
    _fill_edge(ctx, s.lit((1.0, 0.85, 0.25)), None, 0)


def _tufts(ctx: cairo.Context, s: _S, rg: Region, y0: float, y1: float, n: int, color: RGB, key: str) -> None:
    """Пучки травы на земле (дальше — мельче)."""
    x0, _, x1, _ = rg
    r = s.r("tufts", key)
    cnt = int(n * (x1 - x0) / max(1, s.w))
    for _ in range(cnt):
        x, y = r.uniform(x0, x1), r.uniform(y0, y1)
        k = (0.5 + 0.8 * (y - y0) / max(1.0, y1 - y0)) * s.u * r.uniform(0.7, 1.2)
        for j in (-1, 0, 1):
            ctx.move_to(x + j * 3 * k, y)
            ctx.curve_to(x + j * 4 * k, y - 5 * k, x + j * 7 * k, y - 9 * k, x + j * 9 * k, y - (12 - 3 * abs(j)) * k)
            ctx.curve_to(x + j * 5 * k, y - 6 * k, x + j * 3 * k, y - 3 * k, x + j * 3 * k + 2 * k, y)
            ctx.close_path()
    ctx.set_source_rgb(*color)
    ctx.fill()


def _dots(ctx: cairo.Context, s: _S, rg: Region, y0: float, y1: float, n: int, colors, key: str,
          rmin: float = 2.0, rmax: float = 4.5) -> None:
    x0, _, x1, _ = rg
    r = s.r("dots", key)
    cnt = int(n * (x1 - x0) / max(1, s.w))
    for _ in range(cnt):
        x, y = r.uniform(x0, x1), r.uniform(y0, y1)
        k = 0.6 + 0.6 * (y - y0) / max(1.0, y1 - y0)
        ctx.arc(x, y, r.uniform(rmin, rmax) * s.u * k, 0, 2 * math.pi)
        ctx.set_source_rgb(*r.choice(colors))
        ctx.fill()


def _fireflies(ctx: cairo.Context, s: _S, t: float, rg: Region, n: int, y0: float, y1: float) -> None:
    """Светлячки: тёплые огоньки бродят по шуму и мигают (спрайт-свечение, аддитивно)."""
    x0, _, x1, _ = rg
    mk = ("fireflies", rg, n, y0, y1)
    flies = s.memo.get(mk)
    if flies is None:
        cnt = int(n * (x1 - x0) / max(1, s.w))
        flies = s.memo[mk] = [(x0 + (x1 - x0) * hash01(s.seed, "ff", i), y0 + (y1 - y0) * hash01(s.seed, "ffy", i),
                               1.6 + 0.9 * hash01(s.seed, "ffp", i)) for i in range(cnt)]
    rad = 11 * s.u

    def draw(c: cairo.Context) -> None:
        g = cairo.RadialGradient(rad, rad, 0, rad, rad, rad)
        g.add_color_stop_rgba(0, 1.0, 0.95, 0.5, 0.95)
        g.add_color_stop_rgba(0.25, 0.8, 1.0, 0.35, 0.45)
        g.add_color_stop_rgba(1, 0.5, 1.0, 0.2, 0)
        c.set_source(g)
        c.paint()

    sp = _sprite(s, "firefly", rad * 2, rad * 2, draw)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for i, (bx, by, fr) in enumerate(flies):
        k = smoothstep(0.5 + 0.5 * math.sin(t * fr + i * 2.1))
        if k < 0.05:
            continue
        x = bx + 40 * s.u * noise1(t * 0.35 + i * 7.1, s.seed + i)
        y = by + 26 * s.u * noise1(t * 0.3 + i * 3.7, s.seed + 99 + i)
        _blit(ctx, sp, x, y, k, px=rad, py=rad)
    ctx.restore()


def _plant_sprite(s: _S, key: object, size: float, col: RGB, kind: str) -> tuple[cairo.ImageSurface, float, float]:
    """Цветок или папоротник спрайтом (основание стебля — точка привязки, вокруг неё он качается)."""
    if kind == "flower":
        w, h = size * 3.2, size * 3.8
        px, py = w / 2, h - size * 0.3

        def draw(c: cairo.Context) -> None:
            _flower(c, s, px, py, size, col)
    else:
        w, h = size * 2.4, size * 1.35
        px, py = w / 2, h - size * 0.15

        def draw(c: cairo.Context) -> None:
            _fern(c, s, px, py, size, 0.0)
    return _sprite(s, key, w, h, draw), px, py


def _lamp_post(ctx: cairo.Context, s: _S, x: float, gy: float, size: float, depth: float = 0.0) -> None:
    c = s.lit((0.25, 0.27, 0.35), depth)
    lw = 2.0 * s.u
    ctx.rectangle(x - size * 0.025, gy - size, size * 0.05, size)
    _fill_edge(ctx, c, s.edge(c), lw)
    rrect(ctx, x - size * 0.07, gy - size * 0.04, size * 0.14, size * 0.04, size * 0.01)
    _fill_edge(ctx, c, s.edge(c), lw)
    ly = gy - size * 1.05
    ctx.move_to(x - size * 0.09, ly + size * 0.06)
    ctx.line_to(x - size * 0.06, ly - size * 0.08)
    ctx.line_to(x + size * 0.06, ly - size * 0.08)
    ctx.line_to(x + size * 0.09, ly + size * 0.06)
    ctx.close_path()
    on = s.dark or s.overcast
    lamp = (1.0, 0.9, 0.55) if on else s.lit((0.85, 0.92, 0.98), depth)
    _fill_edge(ctx, lamp, s.edge(c), lw)
    ctx.move_to(x - size * 0.11, ly - size * 0.08)
    ctx.line_to(x, ly - size * 0.16)
    ctx.line_to(x + size * 0.11, ly - size * 0.08)
    ctx.close_path()
    _fill_edge(ctx, c, s.edge(c), lw)
    if on:
        _glow(ctx, x, ly, size * 0.5, (1.0, 0.85, 0.5), 0.55 if s.night else 0.4, add=True)
        _glow(ctx, x, gy, size * 0.45, (1.0, 0.8, 0.45), 0.3, add=True, sy=0.25)


def _bird(ctx: cairo.Context, x: float, y: float, size: float, flap: float, color: RGB) -> None:
    k = 0.35 * math.sin(flap)
    ctx.move_to(x - size, y - size * (0.15 + k))
    ctx.curve_to(x - size * 0.6, y - size * (0.45 + k), x - size * 0.2, y - size * 0.25, x, y)
    ctx.curve_to(x + size * 0.2, y - size * 0.25, x + size * 0.6, y - size * (0.45 + k), x + size, y - size * (0.15 + k))
    ctx.set_source_rgb(*color)
    ctx.set_line_width(max(1.2, size * 0.16))
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


def _birds_anim(n: int, y_lo: float, y_hi: float, color: str = "#3b3355"):
    def anim(ctx: cairo.Context, s: _S, t: float, rg: Region) -> None:
        if s.night:
            return
        x0, _, x1, _ = rg
        span = x1 - x0 + 200 * s.u
        r = s.r("birds")
        col = s.lit(color)
        for i in range(n):
            sp = r.uniform(22, 40) * s.u
            ph = r.random()
            y = s.h * r.uniform(y_lo, y_hi) + 8 * s.u * math.sin(t * 0.8 + i)
            x = x0 - 100 * s.u + (ph * span + sp * t) % span
            _bird(ctx, x, y, r.uniform(7, 11) * s.u, t * 9 + i * 1.7, col)

    return anim


def _window_view(ctx: cairo.Context, s: _S, x: float, y: float, w: float, h: float) -> None:
    """Вид из окна: небо этого времени суток, облака/луна, далёкие деревья; погода — капли или снежинки."""
    ctx.save()
    ctx.rectangle(x, y, w, h)
    ctx.clip()
    stops = OVERCAST[s.time] if s.weather in ("rain", "snow") else SKY[s.time]
    _vgrad(ctx, x, y, x + w, y + h, stops)
    u = s.u
    if s.time in ("evening", "night") and s.weather == "clear":
        r = s.r("winstars")
        for _ in range(int(w * h / (900 * u * u))):
            ctx.arc(r.uniform(x, x + w), r.uniform(y, y + h * 0.7), r.uniform(0.6, 1.4) * u, 0, 2 * math.pi)
            ctx.new_sub_path()
        ctx.set_source_rgba(1, 1, 0.9, 0.9)
        ctx.fill()
        _moon(ctx, s, x + w * 0.7, y + h * 0.28, min(w, h) * 0.12, 0.9)
    elif s.time == "sunset" and s.weather == "clear":
        _sun(ctx, s, x + w * 0.65, y + h * 0.72, min(w, h) * 0.16)
    elif s.weather == "clear":
        _sun(ctx, s, x + w * 0.75, y + h * 0.22, min(w, h) * 0.09)
        _cloud(ctx, s, x + w * 0.3, y + h * 0.35, min(w, h) * 0.16, _cloud_puffs(s.r("wincl"), 5))
    # далёкие крыши/деревья
    rr = s.r("winskyline")
    xx = x - 10 * u
    while xx < x + w:
        bw = rr.uniform(0.12, 0.3) * w
        bh = rr.uniform(0.1, 0.32) * h
        if rr.random() < 0.5:
            ctx.rectangle(xx, y + h - bh, bw, bh + 2)
        else:
            ctx.new_sub_path()
            ctx.arc(xx + bw / 2, y + h - bh * 0.6, bw * 0.55, 0, 2 * math.pi)
        xx += bw * 0.9
    ctx.set_source_rgb(*s.lit((0.45, 0.6, 0.55), 0.6, indoor=False))
    ctx.fill()
    if s.weather == "rain":
        r = s.r("rainglass")
        for _ in range(int(w * h / (700 * u * u))):
            px, py = r.uniform(x, x + w), r.uniform(y, y + h)
            ln = r.uniform(4, 12) * u
            ctx.move_to(px, py)
            ctx.line_to(px - ln * 0.15, py + ln)
        ctx.set_source_rgba(0.85, 0.92, 1.0, 0.55)
        ctx.set_line_width(1.4 * u)
        ctx.stroke()
    elif s.weather == "snow":
        r = s.r("snowglass")
        for _ in range(int(w * h / (500 * u * u))):
            ctx.arc(r.uniform(x, x + w), r.uniform(y, y + h), r.uniform(1, 2.4) * u, 0, 2 * math.pi)
            ctx.new_sub_path()
        ctx.set_source_rgba(1, 1, 1, 0.9)
        ctx.fill()
    ctx.restore()


def _accent(s: _S, default: str) -> RGB:
    return s.accent if s.accent is not None else hx(default)


# ======================= park =======================
def _park(s: _S) -> list[_Layer]:
    def sky(ctx, s, rg):
        _paint_sky(ctx, s, rg)
        if s.dark:
            _stars_static(ctx, s, rg, 70 if s.night else 25, s.gy * 0.8)
        _sky_body(ctx, s, s.w * 0.78, s.h * 0.17, 44 * s.u)

    def sky_anim(ctx, s, t, rg):
        if s.dark and not s.overcast:
            _twinkle(ctx, s, t, rg, 14 if s.night else 6, s.gy * 0.7)
        _clouds_anim(3)(ctx, s, t, rg)

    def far(ctx, s, rg):
        u = s.u
        _hills(ctx, s, rg, s.gy - 70 * u, 70 * u, 160 * u, 1.3, s.lit("#8fcf9a", 0.7), s.lit("#77b98a", 0.6))
        pts = _hills(ctx, s, rg, s.gy - 18 * u, 46 * u, 120 * u, 4.1, s.lit("#7ccf7a", 0.35),
                     s.lit("#5fb466", 0.3), s.edge(s.lit("#5fb466", 0.3)), 1.4 * u)
        r = s.r("fartrees")
        for i in range(0, len(pts), 3):
            if r.random() < 0.45:
                x, y = pts[i]
                rr = r.uniform(9, 15) * u
                ctx.rectangle(x - 1.2 * u, y - rr * 0.4, 2.4 * u, rr * 1.2)
                ctx.set_source_rgb(*s.lit("#6b4a3a", 0.5))
                ctx.fill()
                for dx, dy, k in ((0, -0.9, 0.8), (-0.5, -0.5, 0.6), (0.5, -0.5, 0.6)):
                    ctx.new_sub_path()
                    ctx.arc(x + dx * rr, y + dy * rr, k * rr, 0, 2 * math.pi)
                ctx.set_source_rgb(*s.lit("#4fa25f", 0.45))
                ctx.fill()

    def mid(ctx, s, rg):
        u = s.u
        r = s.r("parktrees")
        for x in _xs(s, rg, "trees", (150, 250), avoid=(0.3, 0.7)):
            leaf = r.choice(("#5cc062", "#4fb35a", "#7ccf5a", "#3fa85c"))
            _round_tree(ctx, s, x, s.gy + 4 * u, r.uniform(150, 210) * u, hx(leaf), hx("#8a5a3c"),
                        _lobes(r, r.randint(5, 7)), depth=0.12)
        for x in _xs(s, rg, "bushes", (110, 200)):
            _bush(ctx, s, x, s.gy + 8 * u, r.uniform(26, 40) * u, hx("#4caf50"), 0.1, berries=r.random() < 0.3)
        lx = s.w * 0.66
        _lamp_post(ctx, s, lx, s.gy + 6 * u, 170 * u, 0.05)
        # скамейка
        bx, by = s.w * 0.27, s.gy + 6 * u
        wood = s.lit("#c27a45", 0.05)
        for dy in (-34, -22):
            rrect(ctx, bx - 52 * u, by + dy * u, 104 * u, 9 * u, 3 * u)
            _fill_edge(ctx, wood, s.edge(wood), 1.8 * u)
        rrect(ctx, bx - 56 * u, by - 12 * u, 112 * u, 8 * u, 3 * u)
        _fill_edge(ctx, wood, s.edge(wood), 1.8 * u)
        metal = s.lit("#4b4f63", 0.05)
        for dx in (-44, 40):
            ctx.rectangle(bx + dx * u, by - 36 * u, 5 * u, 36 * u)
            _fill_edge(ctx, metal, s.edge(metal), 1.6 * u)

    def ground(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        _vgrad(ctx, x0, s.gy, x1, y1, ((0, s.lit("#8edc6e")), (0.35, s.lit("#6cc65a")), (1, s.lit("#4fa649"))),
               ya=s.gy, yb=s.h)
        # дорожка в перспективе
        cx = s.w * 0.5
        ctx.move_to(cx - 30 * u, s.gy)
        ctx.curve_to(cx - 60 * u, s.gy + (s.h - s.gy) * 0.4, cx - 220 * u, s.h * 0.95, cx - 300 * u, y1)
        ctx.line_to(cx + 330 * u, y1)
        ctx.curve_to(cx + 250 * u, s.h * 0.95, cx + 80 * u, s.gy + (s.h - s.gy) * 0.4, cx + 30 * u, s.gy)
        ctx.close_path()
        path_c = s.lit("#f1d9a0")
        ctx.set_source(_grad(s.gy, s.h, (0, mix(path_c, s.lit("#8edc6e"), 0.35)), (1, path_c)))
        ctx.fill_preserve()
        ctx.set_source_rgba(*s.edge(path_c), 0.35)
        ctx.set_line_width(2 * u)
        ctx.stroke()
        ctx.rectangle(x0, s.gy - 1, x1 - x0, 3 * u)
        ctx.set_source_rgba(*lighten(s.lit("#8edc6e"), 0.3), 0.8)
        ctx.fill()
        _tufts(ctx, s, rg, s.gy + 10 * u, y1, 70, s.lit("#3f9a45"), "g")
        _dots(ctx, s, rg, s.gy + 12 * u, y1, 40,
              [s.lit(c) for c in ("#ffffff", "#ffe066", "#ff8fb1", "#b48cff")], "fl", 2.0, 4.0)

    def ground_anim(ctx, s, t, rg):
        mk = ("swayflowers", rg)
        flowers = s.memo.get(mk)
        if flowers is None:
            x0, _, x1, _ = rg
            r = s.r("swayflowers")
            cnt = int(7 * (x1 - x0) / s.w)
            flowers = []
            for i in range(cnt):
                x = x0 + (i + r.uniform(0.2, 0.8)) * (x1 - x0) / max(1, cnt)
                y = s.h * r.uniform(0.955, 1.0)
                col = hx(r.choice(("#ff6fa5", "#ffd23f", "#ffffff", "#b48cff", "#ff8a5c")))
                flowers.append((x, y) + _plant_sprite(s, ("flower", i, rg), r.uniform(7, 10) * s.u, col, "flower"))
            s.memo[mk] = flowers
        for i, (x, y, sp, px, py) in enumerate(flowers):
            _blit(ctx, sp, x, y, rot=0.1 * math.sin(t * 1.7 + i * 1.3), px=px, py=py)
        if s.dark:
            _fireflies(ctx, s, t, rg, 12 if s.night else 6, s.gy - 120 * s.u, s.h * 0.92)

    return [_Layer(0.1, sky, sky_anim), _Layer(0.3, far, None, 0.4, 9), _Layer(0.6, mid, None, 0.3, 9),
            _Layer(1.0, ground, ground_anim, HORIZON["park"] - 0.01, 9)]


# ======================= city =======================
def _buildings(s: _S, rg: Region, key: str, hmin: float, hmax: float, wmin: float, wmax: float):
    x0, _, x1, _ = rg
    r = s.r("bld", key)
    out = []
    x = x0 - 60 * s.u
    while x < x1 + 60 * s.u:
        bw = r.uniform(wmin, wmax) * s.u
        bh = r.uniform(hmin, hmax) * s.u * (0.85 + 0.3 * min(1.6, s.h / s.w) / 1.6)
        out.append((x, bw, bh, r.random(), r.randint(0, 3), r.random()))
        x += bw + r.uniform(-4, 14) * s.u
    return out


_FACADES = ("#e8a27c", "#f2c46d", "#9fb8e0", "#c99be0", "#8fd0c0", "#f08f8f", "#b0c4d6", "#e6b8a2")


def _city(s: _S) -> list[_Layer]:
    def sky(ctx, s, rg):
        _paint_sky(ctx, s, rg)
        if s.dark:
            _stars_static(ctx, s, rg, 50 if s.night else 18, s.gy * 0.5)
        _sky_body(ctx, s, s.w * 0.68, s.h * 0.16, 46 * s.u)

    def sky_anim(ctx, s, t, rg):
        if s.dark and not s.overcast:
            _twinkle(ctx, s, t, rg, 10, s.gy * 0.45)
        _clouds_anim(3, 0.06, 0.24)(ctx, s, t, rg)

    def far(ctx, s, rg):
        u = s.u
        col = s.lit("#8a7fb0", 0.65)
        for x, bw, bh, a, roof, _ in _buildings(s, rg, "far", 150, 300, 50, 110):
            ctx.rectangle(x, s.gy - bh, bw, bh + 4)
            if roof == 1:
                ctx.rectangle(x + bw * 0.45, s.gy - bh - 26 * u, 3 * u, 26 * u)
            elif roof == 2:
                ctx.rectangle(x + bw * 0.2, s.gy - bh - 12 * u, bw * 0.6, 12 * u)
        ctx.set_source_rgb(*col)
        ctx.fill()
        if s.dark:
            r = s.r("farwin")
            for x, bw, bh, *_ in _buildings(s, rg, "far", 150, 300, 50, 110):
                for j in range(int(bh / (22 * u))):
                    for k in range(int(bw / (16 * u))):
                        if r.random() < 0.25:
                            ctx.rectangle(x + 5 * u + k * 16 * u, s.gy - bh + 8 * u + j * 22 * u, 6 * u, 9 * u)
            ctx.set_source_rgba(*WINDOW_LIT, 0.55)
            ctx.fill()

    def mid_buildings(s):
        return _buildings(s, (int(-layer_margin(s.w, s.h, 0.6)[0]), 0,
                              s.w + layer_margin(s.w, s.h, 0.6)[0], s.h), "mid", 170, 330, 80, 150)

    def window_grid(s, x, bw, bh):
        u = s.u
        cols = max(1, int((bw - 14 * u) // (24 * u)))
        rows = max(1, int((bh - 40 * u) // (34 * u)))
        gx = (bw - cols * 24 * u) / 2 + 5 * u
        for j in range(rows):
            for k in range(cols):
                yield j, k, x + gx + k * 24 * u, s.gy - bh + 16 * u + j * 34 * u

    def mid(ctx, s, rg):
        u = s.u
        r = s.r("midwin")
        for i, (x, bw, bh, a, roof, tone) in enumerate(mid_buildings(s)):
            base = s.lit(_FACADES[int(tone * len(_FACADES)) % len(_FACADES)], 0.25)
            ctx.rectangle(x, s.gy - bh, bw, bh + 6 * u)
            g = _grad(s.gy - bh, s.gy, (0, lighten(base, 0.12)), (1, mul(base, 0.82)))
            _fill_edge(ctx, g, s.edge(base), 2.0 * u)
            # карниз и крыша
            rrect(ctx, x - 4 * u, s.gy - bh - 8 * u, bw + 8 * u, 10 * u, 3 * u)
            _fill_edge(ctx, mul(base, 0.75), s.edge(base), 1.8 * u)
            if roof == 1:
                ax = x + bw * 0.7
                ctx.rectangle(ax, s.gy - bh - 44 * u, 3 * u, 36 * u)
                ctx.set_source_rgb(*s.edge(base))
                ctx.fill()
                ctx.arc(ax + 1.5 * u, s.gy - bh - 46 * u, 4 * u, 0, 2 * math.pi)
                ctx.set_source_rgb(*((1, 0.3, 0.3) if s.dark else s.lit("#ff6b6b")))
                ctx.fill()
            elif roof == 2:
                tx, tw = x + bw * 0.15, bw * 0.3
                ctx.rectangle(tx, s.gy - bh - 34 * u, tw, 26 * u)
                _fill_edge(ctx, s.lit("#a0704f", 0.2), s.edge(base), 1.6 * u)
                ctx.move_to(tx - 3 * u, s.gy - bh - 34 * u)
                ctx.line_to(tx + tw / 2, s.gy - bh - 48 * u)
                ctx.line_to(tx + tw + 3 * u, s.gy - bh - 34 * u)
                ctx.close_path()
                _fill_edge(ctx, s.lit("#7a5038", 0.2), s.edge(base), 1.6 * u)
            # окна: днём — стекло с бликом, вечером/ночью — часть горит всегда (остальные мигают в anim)
            glass = s.lit("#bfe3ff", 0.15) if not s.dark else mul(s.lit("#3a4a7a", 0.1), 0.9)
            for j, k, wx, wy in window_grid(s, x, bw, bh):
                rrect(ctx, wx, wy, 14 * u, 20 * u, 2 * u)
            _fill_edge(ctx, glass, s.edge(base), 1.4 * u)
            if s.dark:
                for j, k, wx, wy in window_grid(s, x, bw, bh):
                    if r.random() < 0.35:
                        rrect(ctx, wx, wy, 14 * u, 20 * u, 2 * u)
                ctx.set_source_rgb(*WINDOW_LIT)
                ctx.fill()
            else:
                for j, k, wx, wy in window_grid(s, x, bw, bh):
                    ctx.move_to(wx + 3 * u, wy + 14 * u)
                    ctx.line_to(wx + 9 * u, wy + 4 * u)
                ctx.set_source_rgba(1, 1, 1, 0.55)
                ctx.set_line_width(2 * u)
                ctx.stroke()
            # дверь у части домов
            if a < 0.45:
                dx = x + bw * 0.5 - 12 * u
                rrect(ctx, dx, s.gy - 34 * u, 24 * u, 36 * u, 5 * u)
                _fill_edge(ctx, s.lit("#7a4a35", 0.1), s.edge(base), 1.6 * u)

    def mid_anim(ctx, s, t, rg):
        if not s.dark:
            return
        u = s.u
        wins = s.memo.get("citywins")
        if wins is None:
            wins = []
            for i, (x, bw, bh, *_rest) in enumerate(mid_buildings(s)):
                for j, k, wx, wy in window_grid(s, x, bw, bh):
                    ph = hash01(s.seed, "win", i, j, k)
                    if ph >= 0.82:
                        wins.append((wx, wy, ph))
            s.memo["citywins"] = wins
        for wx, wy, ph in wins:
            # окно загорается и гаснет по своему расписанию
            if (t * 0.18 + ph * 7.0) % 1.0 < 0.55:
                rrect(ctx, wx, wy, 14 * u, 20 * u, 2 * u)
        ctx.set_source_rgb(*mul(WINDOW_LIT, 0.95))
        ctx.fill()

    def ground(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        road_y = s.gy + 8 * u
        sw_y = s.gy + 44 * u
        _vgrad(ctx, x0, s.gy, x1, road_y, ((0, s.lit("#b8b2c4")), (1, s.lit("#a49db3"))))
        _vgrad(ctx, x0, road_y, x1, sw_y, ((0, s.lit("#4a4560")), (1, s.lit("#3c3752"))))
        for i in range(int((x0 - 200 * u) // (90 * u)), int(x1 // (90 * u)) + 2):
            ctx.rectangle(i * 90 * u, road_y + 16 * u, 46 * u, 4 * u)
        ctx.set_source_rgba(1, 0.95, 0.7, 0.7)
        ctx.fill()
        ctx.rectangle(x0, sw_y, x1 - x0, 7 * u)
        ctx.set_source_rgb(*s.lit("#d9d3e3"))
        ctx.fill()
        _vgrad(ctx, x0, sw_y + 7 * u, x1, y1, ((0, s.lit("#c9c2d6")), (1, s.lit("#a69fb8"))), ya=sw_y, yb=s.h)
        # плитки тротуара в перспективе
        vx, vy = s.w * 0.5, s.gy - 260 * u
        ctx.set_source_rgba(*s.edge(s.lit("#a69fb8")), 0.35)
        ctx.set_line_width(1.4 * u)
        for i in range(-30, 31):
            bx = s.w * 0.5 + i * 70 * u
            ty = sw_y + 7 * u
            k = (ty - vy) / (y1 - vy)
            ctx.move_to(vx + (bx - vx) * k, ty)
            ctx.line_to(bx, y1)
        yy = sw_y + 7 * u
        step = 14 * u
        while yy < y1:
            ctx.move_to(x0, yy)
            ctx.line_to(x1, yy)
            step *= 1.35
            yy += step
        ctx.stroke()
        for x in _xs(s, rg, "lamps", (300, 420), pad=200):
            _lamp_post(ctx, s, x, sw_y + 4 * u, 190 * u)

    def ground_anim(ctx, s, t, rg):
        # машинки иногда проезжают по дороге за актёрами
        u = s.u
        road_y = s.gy + 8 * u
        x0, _, x1, _ = rg
        span = x1 - x0 + 300 * u
        for i in range(2):
            period = 7.0 + 3.0 * i
            ph = hash01(s.seed, "car", i)
            tt = (t + ph * period) % period
            sp = (span / 3.2) * (1 if i == 0 else -1)
            x = (x0 - 150 * u + tt * sp) if sp > 0 else (x1 + 150 * u + tt * sp)
            if x < x0 - 150 * u or x > x1 + 150 * u:
                continue
            col = s.lit(("#ff5a5f", "#3ec1ff", "#ffd23f")[int(ph * 3) % 3])
            _mini_car(ctx, s, x, road_y + 14 * u, 30 * u, col, -1 if sp < 0 else 1, t)

    return [_Layer(0.1, sky, sky_anim), _Layer(0.3, far, None, 0.2, 9), _Layer(0.6, mid, mid_anim, 0.1, 9),
            _Layer(1.0, ground, ground_anim, HORIZON["city"] - 0.01, 9)]


def _mini_car(ctx: cairo.Context, s: _S, x: float, y: float, size: float, col: RGB, d: int, t: float) -> None:
    u = s.u
    lw = 1.6 * u
    ink = s.edge(col)
    rrect(ctx, x - size * 1.1, y - size * 0.55, size * 2.2, size * 0.5, size * 0.18)
    _fill_edge(ctx, col, ink, lw)
    ctx.move_to(x - size * 0.6, y - size * 0.5)
    ctx.curve_to(x - size * 0.45, y - size * 1.0, x + size * 0.45, y - size * 1.0, x + size * 0.65, y - size * 0.5)
    ctx.close_path()
    _fill_edge(ctx, col, ink, lw)
    ctx.move_to(x - size * 0.45, y - size * 0.55)
    ctx.curve_to(x - size * 0.35, y - size * 0.86, x + size * 0.35, y - size * 0.86, x + size * 0.5, y - size * 0.55)
    ctx.close_path()
    ctx.set_source_rgb(*((1, 0.9, 0.6) if s.dark else s.lit("#cfeaff")))
    ctx.fill()
    for wx in (-0.62, 0.62):
        ctx.arc(x + wx * size, y - size * 0.05, size * 0.22, 0, 2 * math.pi)
        _fill_edge(ctx, s.lit("#2b2840"), ink, lw)
    if s.dark:
        _glow(ctx, x + d * size * 1.15, y - size * 0.32, size * 0.9, (1.0, 0.9, 0.6), 0.5, add=True, sy=0.5)


# ======================= forest =======================
def _forest(s: _S) -> list[_Layer]:
    def sky(ctx, s, rg):
        _paint_sky(ctx, s, rg, s.gy * 0.75)
        if s.dark:
            _stars_static(ctx, s, rg, 60 if s.night else 20, s.gy * 0.5)
        _sky_body(ctx, s, s.w * 0.3, s.h * 0.15, 40 * s.u)

    def sky_anim(ctx, s, t, rg):
        if s.dark and not s.overcast:
            _twinkle(ctx, s, t, rg, 10, s.gy * 0.4)
        _clouds_anim(2, 0.05, 0.18)(ctx, s, t, rg)

    def far(ctx, s, rg):
        u = s.u
        _hills(ctx, s, rg, s.gy - 40 * u, 50 * u, 200 * u, 0.7, s.lit("#6fae8c", 0.7), s.lit("#5b9a7a", 0.6))
        r = s.r("farpines")
        for row, (dep, yoff, hs) in enumerate(((0.75, -40, (110, 170)), (0.55, -10, (140, 210)))):
            for x in _xs(s, rg, f"fp{row}", (34, 60), pad=60):
                _pine(ctx, s, x, s.gy + yoff * u, r.uniform(*hs) * u, hx("#2f8a5a"), depth=dep, lw=0)

    def mid(ctx, s, rg):
        u = s.u
        r = s.r("forestmid")
        for x in _xs(s, rg, "mp", (70, 140), avoid=(0.36, 0.64)):
            if r.random() < 0.55:
                _pine(ctx, s, x, s.gy + 10 * u, r.uniform(230, 330) * u, hx(r.choice(("#2e8b57", "#24804f"))),
                      depth=0.15)
            else:
                _round_tree(ctx, s, x, s.gy + 10 * u, r.uniform(190, 250) * u,
                            hx(r.choice(("#3fa65a", "#5bb85a", "#2f9a55"))), hx("#7a4f35"),
                            _lobes(r, r.randint(5, 7)), depth=0.15)
        for x in _xs(s, rg, "mb", (90, 160)):
            _bush(ctx, s, x, s.gy + 14 * u, r.uniform(24, 36) * u, hx("#3c9c4c"), 0.1, berries=r.random() < 0.4)
        if s.time in ("day", "sunset") and not s.overcast:
            # косые лучи света между деревьями
            col = (1.0, 0.95, 0.7) if s.time == "day" else (1.0, 0.7, 0.45)
            ctx.save()
            ctx.set_operator(cairo.OPERATOR_ADD)
            for i in range(4):
                x = s.w * (0.12 + 0.25 * i)
                a = 0.08 + 0.03 * (i % 2)
                ctx.move_to(x - 30 * u, -40 * u)
                ctx.line_to(x + 40 * u, -40 * u)
                ctx.line_to(x + 160 * u, s.gy + 20 * u)
                ctx.line_to(x + 60 * u, s.gy + 20 * u)
                ctx.close_path()
                ctx.set_source(_grad(-40 * u, s.gy, (0, (*col, a)), (1, (*col, 0.0))))
                ctx.fill()
            ctx.restore()

    def mid_anim(ctx, s, t, rg):
        if s.time in ("day", "sunset") and not s.overcast:
            # пылинки в лучах света медленно плывут
            u = s.u
            for i in range(14):
                f = hash01(s.seed, "mote", i)
                x = s.w * (0.12 + 0.25 * (i % 4)) + 60 * u * f + 40 * u * noise1(t * 0.2 + i, s.seed)
                y = s.gy * (0.25 + 0.7 * hash01(s.seed, "motey", i)) + 30 * u * noise1(t * 0.15 + i * 3, s.seed + 1)
                k = 0.5 + 0.5 * math.sin(t * 1.3 + i * 2.0)
                ctx.new_sub_path()
                ctx.arc(x, y, (1.2 + 1.2 * k) * u, 0, 2 * math.pi)
            ctx.set_source_rgba(1.0, 0.97, 0.8, 0.7)
            ctx.fill()

    def ground(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        _vgrad(ctx, x0, s.gy, x1, y1, ((0, s.lit("#6fbf5a")), (0.5, s.lit("#559e48")), (1, s.lit("#3f8240"))),
               ya=s.gy, yb=s.h)
        ctx.rectangle(x0, s.gy - 1, x1 - x0, 3 * u)
        ctx.set_source_rgba(*lighten(s.lit("#6fbf5a"), 0.25), 0.8)
        ctx.fill()
        _tufts(ctx, s, rg, s.gy + 8 * u, y1, 90, s.lit("#2f7a35"), "fg")
        _dots(ctx, s, rg, s.gy + 10 * u, y1, 25, [s.lit(c) for c in ("#fff6d0", "#ffd23f", "#b48cff")], "ff")
        r = s.r("mush")
        for x in _xs(s, rg, "mush", (160, 300), avoid=(0.3, 0.7)):
            y = s.h * r.uniform(0.78, 0.86)
            _mushroom(ctx, s, x, y, r.uniform(10, 16) * u)
        for x in _xs(s, rg, "logs", (500, 800), avoid=(0.25, 0.75)):
            _log(ctx, s, x, s.h * r.uniform(0.8, 0.84), r.uniform(50, 70) * u)

    def ground_anim(ctx, s, t, rg):
        x0, _, x1, _ = rg
        ferns = s.memo.get(("ferns", rg))
        if ferns is None:
            r = s.r("ferns")
            cnt = int(5 * (x1 - x0) / s.w)
            ferns = s.memo[("ferns", rg)] = [
                (x0 + (i + r.uniform(0.2, 0.8)) * (x1 - x0) / max(1, cnt), s.h * r.uniform(0.97, 1.02),
                 r.uniform(40, 60) * s.u) for i in range(cnt)]
        for i, (x, y, size) in enumerate(ferns):
            _fern(ctx, s, x, y, size, math.sin(t * 1.3 + i * 1.7))
        if s.dark:
            _fireflies(ctx, s, t, rg, 22 if s.night else 10, s.gy - 160 * s.u, s.h * 0.93)

    return [_Layer(0.1, sky, sky_anim), _Layer(0.3, far, None, 0.2, 9), _Layer(0.6, mid, mid_anim, 0.0, 9),
            _Layer(1.0, ground, ground_anim, HORIZON["forest"] - 0.01, 9)]


def _mushroom(ctx: cairo.Context, s: _S, x: float, y: float, size: float) -> None:
    lw = 1.6 * s.u
    stem = s.lit("#fff1d6")
    rrect(ctx, x - size * 0.3, y - size * 0.9, size * 0.6, size * 0.9, size * 0.2)
    _fill_edge(ctx, stem, s.edge(stem), lw)
    cap = s.lit("#ff4d5a")
    ctx.move_to(x - size * 0.95, y - size * 0.8)
    ctx.curve_to(x - size * 0.9, y - size * 1.7, x + size * 0.9, y - size * 1.7, x + size * 0.95, y - size * 0.8)
    ctx.close_path()
    _fill_edge(ctx, cap, s.edge(cap), lw)
    for dx, dy, k in ((-0.45, -1.05, 0.16), (0.1, -1.3, 0.14), (0.5, -1.0, 0.12)):
        ctx.arc(x + dx * size, y + dy * size, k * size, 0, 2 * math.pi)
        ctx.new_sub_path()
    ctx.set_source_rgb(*s.lit("#ffffff"))
    ctx.fill()


def _log(ctx: cairo.Context, s: _S, x: float, y: float, size: float) -> None:
    lw = 1.8 * s.u
    bark = s.lit("#8a5a3c")
    rrect(ctx, x - size, y - size * 0.36, size * 2, size * 0.36, size * 0.18)
    _fill_edge(ctx, _grad(y - size * 0.36, y, (0, lighten(bark, 0.15)), (1, mul(bark, 0.8))), s.edge(bark), lw)
    ellipse(ctx, x + size * 0.95, y - size * 0.18, size * 0.1, size * 0.18)
    _fill_edge(ctx, s.lit("#e8c48f"), s.edge(bark), lw)
    ellipse(ctx, x + size * 0.95, y - size * 0.18, size * 0.04, size * 0.08)
    ctx.set_source_rgb(*s.edge(bark))
    ctx.set_line_width(lw * 0.6)
    ctx.stroke()


def _fern(ctx: cairo.Context, s: _S, x: float, y: float, size: float, sway: float) -> None:
    col = s.lit("#2f8f45")
    ctx.save()
    for k in (-1, 1):
        for j in range(3):
            a = -math.pi / 2 + k * (0.35 + 0.35 * j) + sway * 0.08
            ln = size * (1.0 - 0.18 * j)
            ex, ey = x + math.cos(a) * ln, y + math.sin(a) * ln
            mx, my = x + math.cos(a - k * 0.25) * ln * 0.5, y + math.sin(a - k * 0.25) * ln * 0.5
            ctx.move_to(x, y)
            ctx.curve_to(mx - 6 * s.u, my, ex, ey + 4 * s.u, ex, ey)
            ctx.curve_to(ex + 2 * s.u, ey + 6 * s.u, mx + 8 * s.u, my + 6 * s.u, x + 4 * s.u * k, y)
            ctx.close_path()
    _fill_edge(ctx, col, s.edge(col), 1.4 * s.u)
    ctx.restore()


# ======================= beach =======================
def _beach(s: _S) -> list[_Layer]:
    sea_y = s.gy - 0.17 * s.h if s.h <= s.w * 1.2 else s.gy - 0.12 * s.h

    def sky(ctx, s, rg):
        _paint_sky(ctx, s, rg, sea_y)
        if s.dark:
            _stars_static(ctx, s, rg, 60 if s.night else 20, sea_y * 0.85)
        _sky_body(ctx, s, s.w * 0.72, s.h * 0.15, 46 * s.u)

    def sky_anim(ctx, s, t, rg):
        if s.dark and not s.overcast:
            _twinkle(ctx, s, t, rg, 12, sea_y * 0.8)
        _clouds_anim(3, 0.06, 0.26)(ctx, s, t, rg)
        _birds_anim(4, 0.12, 0.3, "#4a4466")(ctx, s, t, rg)

    def sea(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        deep, near = s.lit("#1f6fd1", 0.25, False), s.lit("#3fd0d8", 0.0, False)
        _vgrad(ctx, x0, sea_y, x1, y1, ((0, deep), (0.6, mix(deep, near, 0.7)), (1, near)), ya=sea_y, yb=s.gy)
        ctx.rectangle(x0, sea_y - 1, x1 - x0, 2 * u)
        ctx.set_source_rgba(*lighten(deep, 0.4), 0.8)
        ctx.fill()
        if s.time == "sunset" and not s.overcast:
            sx = s.w * 0.72
            for i in range(9):
                yy = sea_y + 6 * u + i * 8 * u
                ww = (60 - 5 * i) * u
                rrect(ctx, sx - ww / 2 + (i % 2) * 8 * u, yy, ww, 3 * u, 1.5 * u)
            ctx.set_source_rgba(1, 0.85, 0.5, 0.65)
            ctx.fill()
        elif s.dark and not s.overcast:
            sx = s.w * 0.72
            for i in range(8):
                yy = sea_y + 6 * u + i * 9 * u
                ww = (40 - 3 * i) * u
                rrect(ctx, sx - ww / 2 + (i % 2) * 6 * u, yy, ww, 2.5 * u, 1.2 * u)
            ctx.set_source_rgba(0.9, 0.92, 1.0, 0.45)
            ctx.fill()
        # далёкий остров с пальмой
        ix = s.w * 0.18
        island = s.lit("#4f9a6a", 0.7, False)
        ellipse(ctx, ix, sea_y + 2 * u, 70 * u, 16 * u)
        ctx.set_source_rgb(*island)
        ctx.fill()
        ctx.move_to(ix + 8 * u, sea_y - 8 * u)
        ctx.curve_to(ix + 10 * u, sea_y - 30 * u, ix + 14 * u, sea_y - 44 * u, ix + 20 * u, sea_y - 52 * u)
        ctx.set_line_width(3 * u)
        ctx.set_source_rgb(*island)
        ctx.stroke()
        for a in (-2.6, -1.9, -1.2, -0.5):
            ctx.move_to(ix + 20 * u, sea_y - 52 * u)
            ctx.line_to(ix + 20 * u + math.cos(a) * 22 * u, sea_y - 52 * u + math.sin(a) * 12 * u + 8 * u)
        ctx.set_line_width(4 * u)
        ctx.stroke()

    def sea_anim(ctx, s, t, rg):
        x0, _, x1, _ = rg
        u = s.u
        # бегущие гребешки волн
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        for row in range(5):
            f = (row + 1) / 6.0
            yy = sea_y + (s.gy - sea_y) * f
            sp = (8 + 10 * f) * u
            gap = (70 + 60 * f) * u
            ln = (14 + 26 * f) * u
            off = (t * sp + row * 37 * u) % gap
            x = x0 - gap + off
            k = 0
            while x < x1 + gap:
                ph = hash01(s.seed, "wave", row, k % 17)
                yo = 3 * u * math.sin(t * 1.4 + k + row)
                ctx.move_to(x, yy + yo)
                ctx.curve_to(x + ln * 0.3, yy + yo - 3 * u * f, x + ln * 0.7, yy + yo - 3 * u * f, x + ln, yy + yo)
                x += gap * (0.7 + 0.6 * ph)
                k += 1
            ctx.set_source_rgba(1, 1, 1, 0.35 + 0.35 * f)
            ctx.set_line_width((1.4 + 1.6 * f) * u)
            ctx.stroke()
        # парусник
        bx = x0 + ((t * 9 * u + hash01(s.seed, "boat") * (x1 - x0)) % (x1 - x0))
        by = sea_y + (s.gy - sea_y) * 0.25 + 2 * u * math.sin(t * 1.5)
        hull = s.lit("#ffffff", 0.3, False)
        ctx.move_to(bx - 22 * u, by - 6 * u)
        ctx.line_to(bx + 22 * u, by - 6 * u)
        ctx.line_to(bx + 15 * u, by + 3 * u)
        ctx.line_to(bx - 15 * u, by + 3 * u)
        ctx.close_path()
        _fill_edge(ctx, s.lit("#e8584f", 0.3, False), s.edge(hull), 1.4 * u)
        ctx.move_to(bx, by - 8 * u)
        ctx.line_to(bx, by - 44 * u)
        ctx.line_to(bx + 22 * u, by - 10 * u)
        ctx.close_path()
        _fill_edge(ctx, hull, s.edge(hull), 1.4 * u)
        ctx.move_to(bx - 2 * u, by - 40 * u)
        ctx.line_to(bx - 2 * u, by - 10 * u)
        ctx.line_to(bx - 18 * u, by - 10 * u)
        ctx.close_path()
        _fill_edge(ctx, s.lit("#ffd23f", 0.3, False), s.edge(hull), 1.4 * u)

    def ground(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        sand = s.lit("#f5d9a0", 0.0, False)
        ctx.move_to(x0, y1)
        ctx.line_to(x0, s.gy)
        x = x0
        while x <= x1 + 20 * u:
            ctx.line_to(x, s.gy + 6 * u * math.sin(x / (90 * u)) + 4 * u * math.sin(x / (37 * u)))
            x += 16 * u
        ctx.line_to(x1, y1)
        ctx.close_path()
        ctx.set_source(_grad(s.gy, s.h, (0, mix(sand, s.lit("#c9a46e", 0, False), 0.5)), (0.15, sand),
                             (1, mul(sand, 0.9))))
        ctx.fill()
        r = s.r("shells")
        for _ in range(int(14 * (x1 - x0) / s.w)):
            sx, sy = r.uniform(x0, x1), s.h * r.uniform(0.78, 1.0)
            if r.random() < 0.3:
                star(ctx, sx, sy, 9 * u, 5, 0.5, r.uniform(0, 6))
                _fill_edge(ctx, s.lit("#ff8a5c", 0, False), s.edge(s.lit("#ff8a5c", 0, False)), 1.4 * u)
            else:
                ellipse(ctx, sx, sy, 6 * u, 4.5 * u, r.uniform(-0.5, 0.5))
                _fill_edge(ctx, s.lit(r.choice(("#fff1e6", "#ffd1dc", "#e8d6ff")), 0, False),
                           s.edge(s.lit("#d8b890", 0, False)), 1.2 * u)
        _dots(ctx, s, rg, s.gy + 12 * u, y1, 60, [mul(sand, 0.85), lighten(sand, 0.3)], "sand", 1.0, 2.0)

    def ground_anim(ctx, s, t, rg):
        x0, _, x1, _ = rg
        u = s.u
        # пена набегает и откатывается
        k = 0.5 + 0.5 * math.sin(t * 0.9)
        foam_y = s.gy + (4 + 10 * k) * u
        ctx.move_to(x0, s.gy - 2 * u)
        x = x0
        pts = []
        while x <= x1 + 16 * u:
            pts.append((x, foam_y + 5 * u * math.sin(x / (40 * u) + t * 0.8)))
            x += 16 * u
        for p in pts:
            ctx.line_to(*p)
        ctx.line_to(x1, s.gy - 2 * u)
        ctx.close_path()
        ctx.set_source_rgba(0.55, 0.85, 0.95, 0.55)
        ctx.fill()
        ctx.move_to(*pts[0])
        for p in pts[1:]:
            ctx.line_to(*p)
        ctx.set_source_rgba(1, 1, 1, 0.9)
        ctx.set_line_width(4 * u)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()

    def palm_anim(ctx, s, t, rg):
        for i, (fx, sz, lean) in enumerate(((0.1, 1.0, 1), (0.92, 0.85, -1))):
            _palm(ctx, s, s.w * fx, s.gy + 30 * s.u, 300 * s.u * sz, lean, t + i * 1.3, key=i)

    return [_Layer(0.1, sky, sky_anim), _Layer(0.3, sea, sea_anim, sea_y / s.h - 0.02, 9),
            _Layer(1.0, ground, ground_anim, HORIZON["beach"] - 0.02, 9), _Layer(1.0, None, palm_anim)]


def _palm(ctx: cairo.Context, s: _S, x: float, gy: float, size: float, lean: int, t: float, key: object = 0) -> None:
    """Пальма: ствол — неподвижный спрайт, крона рисуется каждый кадр (листья качаются)."""
    tx, ty = x + lean * size * 0.28, gy - size
    pad = size * 0.1
    trunk_w, trunk_h = size * 0.5, size * 1.1
    tox, toy = trunk_w / 2 - lean * size * 0.14, trunk_h - pad * 0.5

    def draw_trunk(c: cairo.Context) -> None:
        _palm_trunk(c, s, tox, toy, size, lean)

    trunk = _sprite(s, ("palm_trunk", key, round(size, 2), lean), trunk_w, trunk_h, draw_trunk)
    _blit(ctx, trunk, x, gy, px=tox, py=toy)
    _palm_crown(ctx, s, tx, ty, size, t)


def _palm_trunk(ctx: cairo.Context, s: _S, x: float, gy: float, size: float, lean: int) -> None:
    lw = 2.2 * s.u
    trunk = s.lit("#c8925a", 0, False)
    segs = 7
    pts = [(x + lean * size * 0.28 * (i / segs) ** 2, gy - size * i / segs) for i in range(segs + 1)]
    for i in range(segs):
        (ax, ay), (bx, by) = pts[i], pts[i + 1]
        wd = size * (0.065 - 0.02 * i / segs)
        ctx.move_to(ax - wd, ay)
        ctx.line_to(bx - wd * 0.9, by)
        ctx.line_to(bx + wd * 0.9, by)
        ctx.line_to(ax + wd, ay)
        ctx.close_path()
        _fill_edge(ctx, trunk if i % 2 else mul(trunk, 0.9), s.edge(trunk), lw * 0.8)


def _palm_crown(ctx: cairo.Context, s: _S, tx: float, ty: float, size: float, t: float = 0.0) -> None:
    """Крона пальмы: листья качаются каждый своим темпом (сплошная заливка — дёшево каждый кадр)."""
    lw = 2.2 * s.u
    leaf = s.lit("#3fae55", 0, False)
    trunk = s.lit("#c8925a", 0, False)
    ribs = []
    for j, base_a in enumerate((-2.9, -2.35, -1.75, -1.2, -0.6, -0.15)):
        a = base_a + 0.06 * math.sin(t * 1.4 + j * 0.9)
        ln = size * (0.55 + 0.1 * math.sin(j * 2.3))
        droop = size * 0.22
        ex, ey = tx + math.cos(a) * ln, ty + math.sin(a) * ln * 0.55 + droop
        mx_, my_ = tx + math.cos(a) * ln * 0.5, ty + math.sin(a) * ln * 0.5 - size * 0.06
        nx, ny = -math.sin(a), math.cos(a)
        wd = size * 0.07
        ctx.move_to(tx, ty)
        ctx.curve_to(mx_ + nx * wd, my_ + ny * wd - wd, ex + nx * wd * 0.3, ey, ex, ey)
        ctx.curve_to(ex - nx * wd * 0.3, ey + wd * 0.4, mx_ - nx * wd, my_ - ny * wd + wd, tx, ty)
        ctx.close_path()
        ribs.append((mx_, my_, ex, ey))
    _fill_edge(ctx, leaf, s.edge(leaf), lw)
    for mx_, my_, ex, ey in ribs:
        ctx.move_to(tx, ty)
        ctx.curve_to(mx_, my_, mx_, my_, ex, ey)
    ctx.set_source_rgba(*lighten(leaf, 0.35), 0.8)
    ctx.set_line_width(1.6 * s.u)
    ctx.stroke()
    for dx in (-0.04, 0.03):
        ctx.new_sub_path()
        ctx.arc(tx + dx * size, ty + size * 0.03, size * 0.035, 0, 2 * math.pi)
    _fill_edge(ctx, s.lit("#7a4a2a", 0, False), s.edge(trunk), lw * 0.7)


# ======================= space =======================
_SPACE = {  # верх, низ, туманность 1, туманность 2, поверхность
    "day": ("#0d0b3a", "#3a1f7a", "#ff5fd2", "#3ec1ff", "#b9a8d9"),
    "sunset": ("#1a0730", "#6b1d5e", "#ff7a45", "#ff3d8a", "#d0a0a8"),
    "evening": ("#06102e", "#123a5e", "#2ee6c8", "#5a7dff", "#9fb3c8"),
    "night": ("#030414", "#151034", "#7a4dff", "#2b5dff", "#8f86b0"),
}


def _space(s: _S) -> list[_Layer]:
    top, bot, n1, n2, surf = _SPACE[s.time]

    def sky(ctx, s, rg):
        x0, y0, x1, y1 = rg
        _vgrad(ctx, x0, y0, x1, y1, ((0, top), (1, bot)), ya=0, yb=s.gy)
        u = s.u
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        r = s.r("nebula")
        for col, n in ((hx(n1), 4), (hx(n2), 4)):
            for _ in range(n):
                _glow(ctx, r.uniform(x0, x1), r.uniform(0, s.gy * 0.8), r.uniform(120, 260) * u, col,
                      r.uniform(0.12, 0.22), sy=r.uniform(0.4, 0.8))
        ctx.restore()
        _stars_static(ctx, s, rg, 260, s.gy, 0.9)

    def sky_anim(ctx, s, t, rg):
        _twinkle(ctx, s, t, rg, 40, s.gy * 0.95)
        # падающая звезда раз в ~3 с
        x0, _, x1, _ = rg
        period = 3.2
        k = int(t // period)
        tt = t - k * period
        if tt < 0.7:
            sx = x0 + (x1 - x0) * hash01(s.seed, "shoot", k)
            sy = s.h * (0.05 + 0.25 * hash01(s.seed, "shooty", k))
            p = tt / 0.7
            hx_, hy = sx + 260 * s.u * p, sy + 120 * s.u * p
            g = cairo.LinearGradient(hx_ - 90 * s.u, hy - 42 * s.u, hx_, hy)
            g.add_color_stop_rgba(0, 1, 1, 1, 0)
            g.add_color_stop_rgba(1, 1, 1, 1, 0.9 * math.sin(math.pi * p))
            ctx.move_to(hx_ - 90 * s.u, hy - 42 * s.u)
            ctx.line_to(hx_, hy)
            ctx.set_source(g)
            ctx.set_line_width(2.5 * s.u)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.stroke()

    def planets(ctx, s, rg):
        u = s.u
        _planet(ctx, s, s.w * 0.78, s.h * 0.2, 70 * u, hx("#ff9f6b") if s.time != "evening" else hx("#7fd8ff"),
                ring=True)
        _planet(ctx, s, s.w * 0.15, s.h * 0.12, 26 * u, hx("#5ad1a0"), ring=False)
        _planet(ctx, s, s.w * 0.38, s.h * 0.32, 12 * u, hx("#ffd23f"), ring=False)

    def mid(ctx, s, rg):
        u = s.u
        c = s.lit(surf, 0.0, True)
        _hills(ctx, s, rg, s.gy - 10 * u, 34 * u, 140 * u, 2.0, mul(c, 0.75), mul(c, 0.65), s.edge(mul(c, 0.7)),
               1.6 * u)

    def ground(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        c = hx(surf)
        _hills(ctx, s, rg, s.gy + 14 * u, 16 * u, 90 * u, 0.3, lighten(c, 0.1), mul(c, 0.7), s.edge(c), 2 * u)
        r = s.r("craters")
        for _ in range(int(10 * (x1 - x0) / s.w)):
            cx, cy = r.uniform(x0, x1), s.h * r.uniform(0.8, 1.0)
            rx = r.uniform(18, 46) * u * (0.6 + 0.6 * (cy / s.h - 0.78) / 0.22)
            ellipse(ctx, cx, cy, rx, rx * 0.32)
            _fill_edge(ctx, mul(c, 0.78), s.edge(c), 1.6 * u)
            ellipse(ctx, cx, cy + rx * 0.06, rx * 0.8, rx * 0.22)
            ctx.set_source_rgba(*mul(c, 0.62), 0.9)
            ctx.fill()
        _dots(ctx, s, rg, s.gy + 20 * u, y1, 40, [mul(c, 0.85), lighten(c, 0.2)], "dust", 1.5, 3.5)

    return [_Layer(0.1, sky, sky_anim), _Layer(0.3, planets, None, -1, 0.5), _Layer(0.6, mid, None, 0.5, 9),
            _Layer(1.0, ground, None, HORIZON["space"] - 0.02, 9)]


def _planet(ctx: cairo.Context, s: _S, x: float, y: float, r: float, col: RGB, ring: bool) -> None:
    u = s.u
    lw = 2.2 * u
    ink = s.edge(col)
    if ring:
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(-0.35)
        ctx.scale(1, 0.28)
        ctx.arc(0, 0, r * 1.75, math.pi, 2 * math.pi)
        ctx.arc_negative(0, 0, r * 1.35, 2 * math.pi, math.pi)
        ctx.close_path()
        ctx.restore()
        _fill_edge(ctx, lighten(col, 0.35), ink, lw)
    g = cairo.RadialGradient(x - r * 0.35, y - r * 0.4, r * 0.1, x, y, r * 1.1)
    g.add_color_stop_rgb(0, *lighten(col, 0.4))
    g.add_color_stop_rgb(0.6, *col)
    g.add_color_stop_rgb(1, *mul(col, 0.6))
    ctx.arc(x, y, r, 0, 2 * math.pi)
    _fill_edge(ctx, g, ink, lw)
    ctx.save()
    ctx.arc(x, y, r, 0, 2 * math.pi)
    ctx.clip()
    for k in (-0.35, 0.1, 0.45):
        ctx.rectangle(x - r, y + k * r, r * 2, r * 0.12)
    ctx.set_source_rgba(*mul(col, 0.8), 0.6)
    ctx.fill()
    ctx.restore()
    if ring:
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(-0.35)
        ctx.scale(1, 0.28)
        ctx.arc(0, 0, r * 1.75, 0, math.pi)
        ctx.arc_negative(0, 0, r * 1.35, math.pi, 0)
        ctx.close_path()
        ctx.restore()
        _fill_edge(ctx, lighten(col, 0.35), ink, lw)


# ======================= room =======================
def _room(s: _S) -> list[_Layer]:
    wall = _accent(s, "#ffd8c2")
    win = (s.w * 0.08, s.h * 0.2, min(s.w * 0.3, 260 * s.u), min(s.h * 0.32, 230 * s.u))

    def view(ctx, s, rg):
        x0, y0, x1, y1 = rg
        _vgrad(ctx, x0, y0, x1, y1, SKY[s.time])
        wx, wy, ww, wh = win
        _window_view(ctx, s, wx - 40 * s.u, wy - 20 * s.u, ww + 80 * s.u, wh + 40 * s.u)

    def wall_layer(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        c = s.lit(wall)
        ctx.rectangle(x0, y0, x1 - x0, s.gy - y0)
        wx, wy, ww, wh = win
        ctx.rectangle(wx + ww, wy, -ww, wh)  # дыра-окно (обратный обход)
        ctx.set_source(_grad(0, s.gy, (0, lighten(c, 0.08)), (1, mul(c, 0.9))))
        ctx.fill()
        # обои: вертикальные полоски с цветочками
        ctx.save()
        ctx.rectangle(x0, y0, x1 - x0, s.gy - y0)
        ctx.rectangle(wx + ww, wy, -ww, wh)
        ctx.clip()
        i0 = int((x0 // (48 * u)) - 1)
        for i in range(i0, i0 + int((x1 - x0) / (48 * u)) + 3):
            ctx.rectangle(i * 48 * u, y0, 18 * u, s.gy - y0)
        ctx.set_source_rgba(*mul(c, 0.93), 1)
        ctx.fill()
        for i in range(i0, i0 + int((x1 - x0) / (48 * u)) + 3):
            for j in range(int(s.gy / (60 * u)) + 1):
                cx, cy = i * 48 * u + 33 * u, j * 60 * u + (30 * u if i % 2 else 0)
                sparkle(ctx, cx, cy, 5 * u)
        ctx.set_source_rgba(*lighten(c, 0.35), 0.8)
        ctx.fill()
        ctx.restore()
        # рама окна, подоконник, шторы
        frame = s.lit("#ffffff")
        ctx.rectangle(wx, wy, ww, wh)
        ctx.set_line_width(10 * u)
        ctx.set_source_rgb(*frame)
        ctx.stroke_preserve()
        ctx.set_line_width(2 * u)
        ctx.set_source_rgb(*s.edge(c))
        ctx.stroke()
        ctx.move_to(wx + ww / 2, wy)
        ctx.line_to(wx + ww / 2, wy + wh)
        ctx.move_to(wx, wy + wh * 0.45)
        ctx.line_to(wx + ww, wy + wh * 0.45)
        ctx.set_line_width(7 * u)
        ctx.set_source_rgb(*frame)
        ctx.stroke()
        rrect(ctx, wx - 18 * u, wy + wh, ww + 36 * u, 12 * u, 4 * u)
        _fill_edge(ctx, frame, s.edge(c), 2 * u)
        # картинка в рамке и полка с книгами
        px, py = s.w * 0.6, s.h * 0.2
        rrect(ctx, px, py, 110 * u, 84 * u, 6 * u)
        _fill_edge(ctx, s.lit("#c27a45"), s.edge(c), 2.2 * u)
        ctx.rectangle(px + 10 * u, py + 10 * u, 90 * u, 64 * u)
        ctx.set_source_rgb(*s.lit("#bfe9ff"))
        ctx.fill()
        _hills_mini(ctx, s, px + 10 * u, py + 10 * u, 90 * u, 64 * u)
        sx, sy = s.w * 0.56, s.h * 0.5
        rrect(ctx, sx, sy, 170 * u, 10 * u, 3 * u)
        _fill_edge(ctx, s.lit("#a86a3f"), s.edge(c), 2 * u)
        r = s.r("books")
        bx = sx + 10 * u
        for _ in range(6):
            bw_, bh_ = r.uniform(12, 18) * u, r.uniform(38, 52) * u
            rrect(ctx, bx, sy - bh_, bw_, bh_, 2 * u)
            col = s.lit(r.choice(("#ff6b6b", "#3ec1ff", "#ffd23f", "#7cd67c", "#b48cff")))
            _fill_edge(ctx, col, s.edge(col), 1.6 * u)
            bx += bw_ + 2 * u
        # горшок с цветком на полке
        _pot_plant(ctx, s, sx + 140 * u, sy, 28 * u)
        # плинтус
        ctx.rectangle(x0, s.gy - 14 * u, x1 - x0, 14 * u)
        _fill_edge(ctx, s.lit("#ffffff"), s.edge(c), 1.6 * u)
        # торшер справа
        lx = s.w * 0.9
        ctx.rectangle(lx - 3 * u, s.gy - 210 * u, 6 * u, 210 * u)
        _fill_edge(ctx, s.lit("#5a4a6a"), s.edge(c), 1.6 * u)
        ctx.move_to(lx - 40 * u, s.gy - 200 * u)
        ctx.line_to(lx - 26 * u, s.gy - 250 * u)
        ctx.line_to(lx + 26 * u, s.gy - 250 * u)
        ctx.line_to(lx + 40 * u, s.gy - 200 * u)
        ctx.close_path()
        shade = (1.0, 0.9, 0.6) if s.dark else s.lit("#fff1b8")
        _fill_edge(ctx, shade, s.edge(c), 2 * u)
        if s.dark:
            _glow(ctx, lx, s.gy - 220 * u, 260 * u, (1.0, 0.8, 0.45), 0.35, add=True)
            _glow(ctx, lx, s.gy - 200 * u, 120 * u, (1.0, 0.9, 0.6), 0.3, add=True)

    def floor(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        wood = s.lit("#d9a066")
        _vgrad(ctx, x0, s.gy, x1, y1, ((0, mul(wood, 0.85)), (1, wood)), ya=s.gy, yb=s.h)
        vx, vy = s.w * 0.5, s.gy - 420 * u
        ctx.set_source_rgba(*s.edge(wood), 0.45)
        ctx.set_line_width(1.6 * u)
        for i in range(-40, 41):
            bx = s.w * 0.5 + i * 64 * u
            k = (s.gy - vy) / (y1 - vy)
            ctx.move_to(vx + (bx - vx) * k, s.gy)
            ctx.line_to(bx, y1)
        ctx.stroke()
        # ковёр
        rc = s.lit(mix(_accent(s, "#ff7eb6"), hx("#b48cff"), 0.4))
        ellipse(ctx, s.w * 0.5, s.h * 0.89, s.w * 0.36, (s.h - s.gy) * 0.3)
        _fill_edge(ctx, rc, s.edge(rc), 2.4 * u)
        ellipse(ctx, s.w * 0.5, s.h * 0.89, s.w * 0.3, (s.h - s.gy) * 0.22)
        ctx.set_source_rgba(*lighten(rc, 0.3), 0.9)
        ctx.set_line_width(4 * u)
        ctx.stroke()
        if s.dark:
            _glow(ctx, s.w * 0.9, s.gy + 20 * u, 240 * u, (1.0, 0.8, 0.45), 0.25, add=True, sy=0.3)

    def wall_anim(ctx, s, t, rg):
        # шторы чуть колышутся
        u = s.u
        wx, wy, ww, wh = win
        cc = s.lit(mix(_accent(s, "#ff7eb6"), hx("#ffffff"), 0.2))
        for side in (-1, 1):
            ex = wx if side < 0 else wx + ww
            sw = 6 * u * math.sin(t * 0.9 + side)
            ctx.move_to(ex - side * 6 * u, wy - 16 * u)
            ctx.line_to(ex + side * 40 * u, wy - 16 * u)
            ctx.curve_to(ex + side * 26 * u + sw, wy + wh * 0.4, ex + side * 46 * u + sw, wy + wh * 0.8,
                         ex + side * 30 * u + sw, wy + wh + 30 * u)
            ctx.line_to(ex - side * 22 * u + sw, wy + wh + 30 * u)
            ctx.curve_to(ex - side * 10 * u, wy + wh * 0.6, ex - side * 18 * u, wy + wh * 0.2,
                         ex - side * 6 * u, wy - 16 * u)
            ctx.close_path()
            _fill_edge(ctx, cc, s.edge(cc), 2 * u)
        rrect(ctx, wx - 50 * u, wy - 24 * u, ww + 100 * u, 8 * u, 4 * u)
        _fill_edge(ctx, s.lit("#a86a3f"), s.edge(cc), 1.6 * u)

    return [_Layer(0.3, view, None), _Layer(0.85, wall_layer, wall_anim, -9, HORIZON["room"] + 0.01),
            _Layer(1.0, floor, None, HORIZON["room"] - 0.02, 9)]


def _hills_mini(ctx: cairo.Context, s: _S, x: float, y: float, w: float, h: float) -> None:
    ctx.save()
    ctx.rectangle(x, y, w, h)
    ctx.clip()
    ctx.move_to(x, y + h)
    ctx.curve_to(x + w * 0.3, y + h * 0.4, x + w * 0.6, y + h * 0.5, x + w, y + h * 0.6)
    ctx.line_to(x + w, y + h)
    ctx.close_path()
    ctx.set_source_rgb(*s.lit("#7cd67c"))
    ctx.fill()
    ctx.arc(x + w * 0.75, y + h * 0.3, h * 0.12, 0, 2 * math.pi)
    ctx.set_source_rgb(*s.lit("#ffd23f"))
    ctx.fill()
    ctx.restore()


def _pot_plant(ctx: cairo.Context, s: _S, x: float, y: float, size: float) -> None:
    u = s.u
    pot = s.lit("#e2725b")
    ctx.move_to(x - size * 0.45, y - size * 0.7)
    ctx.line_to(x + size * 0.45, y - size * 0.7)
    ctx.line_to(x + size * 0.32, y)
    ctx.line_to(x - size * 0.32, y)
    ctx.close_path()
    _fill_edge(ctx, pot, s.edge(pot), 1.6 * u)
    leaf = s.lit("#4caf50")
    for a in (-2.4, -1.9, -1.57, -1.2, -0.7):
        ex, ey = x + math.cos(a) * size, y - size * 0.7 + math.sin(a) * size
        ctx.move_to(x, y - size * 0.7)
        ctx.curve_to(x + math.cos(a - 0.3) * size * 0.5, y - size * 0.7 + math.sin(a - 0.3) * size * 0.5, ex, ey,
                     ex, ey)
        ctx.curve_to(ex, ey, x + math.cos(a + 0.3) * size * 0.5, y - size * 0.7 + math.sin(a + 0.3) * size * 0.5,
                     x, y - size * 0.7)
        ctx.close_path()
    _fill_edge(ctx, leaf, s.edge(leaf), 1.4 * u)


# ======================= classroom =======================
def _classroom(s: _S) -> list[_Layer]:
    wall = _accent(s, "#cfe8c8")
    fmt_tall = s.h > s.w * 1.2
    win = (s.w * 0.04, s.h * 0.2, min(s.w * 0.18, 150 * s.u), min(s.h * 0.3, 210 * s.u))
    if fmt_tall:
        board = (s.w * 0.08, s.h * 0.25, s.w * 0.84, s.h * 0.2)
        win = (s.w * 0.05, s.h * 0.08, s.w * 0.25, s.h * 0.12)
    else:
        bx0 = win[0] + win[2] + 34 * s.u
        board = (bx0, s.h * 0.24, min(s.w * 0.94 - bx0, 620 * s.u), s.h * 0.27)
    clock = (s.w * 0.86 if not fmt_tall else s.w * 0.82, s.h * 0.12 if not fmt_tall else s.h * 0.13, 30 * s.u)

    def view(ctx, s, rg):
        x0, y0, x1, y1 = rg
        _vgrad(ctx, x0, y0, x1, y1, SKY[s.time])
        wx, wy, ww, wh = win
        _window_view(ctx, s, wx - 40 * s.u, wy - 20 * s.u, ww + 80 * s.u, wh + 40 * s.u)

    def wall_layer(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        c = s.lit(wall)
        wx, wy, ww, wh = win
        ctx.rectangle(x0, y0, x1 - x0, s.gy - y0)
        ctx.rectangle(wx + ww, wy, -ww, wh)
        ctx.set_source(_grad(0, s.gy, (0, lighten(c, 0.06)), (1, mul(c, 0.92))))
        ctx.fill()
        # нижняя панель стены
        ctx.rectangle(x0, s.gy - 70 * u, x1 - x0, 70 * u)
        _fill_edge(ctx, mul(c, 0.86), None, 0)
        ctx.rectangle(x0, s.gy - 72 * u, x1 - x0, 5 * u)
        ctx.set_source_rgb(*s.lit("#ffffff"))
        ctx.fill()
        frame = s.lit("#ffffff")
        ctx.rectangle(wx, wy, ww, wh)
        ctx.set_line_width(10 * u)
        ctx.set_source_rgb(*frame)
        ctx.stroke_preserve()
        ctx.set_line_width(2 * u)
        ctx.set_source_rgb(*s.edge(c))
        ctx.stroke()
        ctx.move_to(wx + ww / 2, wy)
        ctx.line_to(wx + ww / 2, wy + wh)
        ctx.set_line_width(6 * u)
        ctx.set_source_rgb(*frame)
        ctx.stroke()
        # доска
        bx, by, bw, bh = board
        rrect(ctx, bx - 12 * u, by - 12 * u, bw + 24 * u, bh + 24 * u, 8 * u)
        _fill_edge(ctx, s.lit("#b07a4a"), s.edge(c), 2.4 * u)
        rrect(ctx, bx, by, bw, bh, 4 * u)
        bc = s.lit("#2f5d4a")
        g = cairo.RadialGradient(bx + bw * 0.4, by + bh * 0.3, 10 * u, bx + bw / 2, by + bh / 2, bw * 0.7)
        g.add_color_stop_rgb(0, *lighten(bc, 0.12))
        g.add_color_stop_rgb(1, *mul(bc, 0.85))
        _fill_edge(ctx, g, s.edge(bc), 2 * u)
        # меловые разводы
        r = s.r("smudge")
        for _ in range(5):
            ex, ey = r.uniform(bx + 30 * u, bx + bw - 30 * u), r.uniform(by + 20 * u, by + bh - 20 * u)
            ellipse(ctx, ex, ey, r.uniform(30, 60) * u, r.uniform(8, 16) * u, r.uniform(-0.3, 0.3))
            ctx.set_source_rgba(1, 1, 1, 0.05)
            ctx.fill()
        rrect(ctx, bx + bw * 0.1, by + bh + 10 * u, bw * 0.8, 8 * u, 3 * u)
        _fill_edge(ctx, s.lit("#9a6a40"), s.edge(c), 1.6 * u)
        for k, col in enumerate(("#ffffff", "#ffd23f", "#ff8fb1")):
            rrect(ctx, bx + bw * 0.2 + k * 26 * u, by + bh + 4 * u, 18 * u, 6 * u, 3 * u)
            ctx.set_source_rgb(*s.lit(col))
            ctx.fill()
        _chalk(ctx, s, board)
        # азбука над доской
        letters = "АБВГДЕЁЖЗИК"
        n = max(3, min(len(letters), int(bw / (46 * u))))
        cw = bw / n
        cy = by - 12 * u - 50 * u if not fmt_tall else by - 60 * u
        for i in range(n):
            col = s.lit(CONFETTI[i % len(CONFETTI)])
            rrect(ctx, bx + i * cw + 4 * u, cy, cw - 8 * u, 38 * u, 6 * u)
            _fill_edge(ctx, lighten(col, 0.55), s.edge(col), 1.6 * u)
            ctx.new_path()
            text_path(ctx, letters[i], bx + i * cw + cw / 2, cy + 19 * u, 24 * u, True)
            ctx.set_source_rgb(*mul(col, 0.8))
            ctx.fill()
        # часы (стрелки — в anim)
        cx, cy, cr = clock
        ctx.arc(cx, cy, cr, 0, 2 * math.pi)
        _fill_edge(ctx, s.lit("#ffffff"), s.edge(c), 3 * u)
        for i in range(12):
            a = i * math.pi / 6
            ctx.move_to(cx + math.cos(a) * cr * 0.78, cy + math.sin(a) * cr * 0.78)
            ctx.line_to(cx + math.cos(a) * cr * 0.9, cy + math.sin(a) * cr * 0.9)
        ctx.set_source_rgb(*s.edge(c))
        ctx.set_line_width(2 * u)
        ctx.stroke()
        # парты у стены
        for x in _xs(s, rg, "desks", (150, 190), pad=100):
            _desk(ctx, s, x, s.gy + 4 * u, 90 * u)

    def wall_anim(ctx, s, t, rg):
        cx, cy, cr = clock
        u = s.u
        sec = (t * 1.0) % 60
        mins = 10 + t / 60.0
        for a, ln, wd, col in ((mins / 60 * 2 * math.pi - math.pi / 2, 0.62, 3.2, INK),
                               (((10 + mins / 60) / 12) * 2 * math.pi - math.pi / 2, 0.42, 4.0, INK),
                               (sec / 60 * 2 * math.pi - math.pi / 2, 0.75, 1.4, (0.9, 0.2, 0.25))):
            ctx.move_to(cx, cy)
            ctx.line_to(cx + math.cos(a) * cr * ln, cy + math.sin(a) * cr * ln)
            ctx.set_source_rgb(*col)
            ctx.set_line_width(wd * u)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.stroke()
        ctx.arc(cx, cy, 3 * u, 0, 2 * math.pi)
        ctx.set_source_rgb(*INK)
        ctx.fill()

    def floor(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        a, b = s.lit("#e9dcc4"), s.lit("#d7c6a8")
        _vgrad(ctx, x0, s.gy, x1, y1, ((0, mul(a, 0.9)), (1, a)), ya=s.gy, yb=s.h)
        vx, vy = s.w * 0.5, s.gy - 380 * u
        rows = [s.gy]
        step = 16 * u
        while rows[-1] < y1:
            rows.append(rows[-1] + step)
            step *= 1.32
        for ri in range(len(rows) - 1):
            ya, yb = rows[ri], rows[ri + 1]
            for i in range(-40, 41):
                if (i + ri) % 2:
                    continue
                xb0, xb1 = s.w * 0.5 + i * 70 * u, s.w * 0.5 + (i + 1) * 70 * u
                ka, kb = (ya - vy) / (s.h - vy), (yb - vy) / (s.h - vy)
                ctx.move_to(vx + (xb0 - vx) * ka, ya)
                ctx.line_to(vx + (xb1 - vx) * ka, ya)
                ctx.line_to(vx + (xb1 - vx) * kb, yb)
                ctx.line_to(vx + (xb0 - vx) * kb, yb)
                ctx.close_path()
        ctx.set_source_rgba(*b, 0.8)
        ctx.fill()

    return [_Layer(0.3, view, None), _Layer(0.85, wall_layer, wall_anim, -9, HORIZON["classroom"] + 0.01),
            _Layer(1.0, floor, None, HORIZON["classroom"] - 0.02, 9)]


def _chalk(ctx: cairo.Context, s: _S, board: tuple[float, float, float, float]) -> None:
    """Надпись мелом на доске: background.text (или пример по умолчанию), шрифт с неровной обводкой."""
    bx, by, bw, bh = board
    u = s.u
    text, _ = clean_text(s.text, 60)
    pad = 18 * u
    maxw = bw - 2 * pad
    if not text:
        text = "2 + 2 = 4"
        size = min(bh * 0.32, 44 * u)
        lines = [text]
        # рисунок мелом: солнышко
        sx, sy, sr = bx + bw * 0.82, by + bh * 0.5, min(bh * 0.18, 26 * u)
        ctx.arc(sx, sy, sr, 0, 2 * math.pi)
        for i in range(8):
            a = i * math.pi / 4
            ctx.move_to(sx + math.cos(a) * sr * 1.3, sy + math.sin(a) * sr * 1.3)
            ctx.line_to(sx + math.cos(a) * sr * 1.8, sy + math.sin(a) * sr * 1.8)
        ctx.set_source_rgba(1.0, 0.92, 0.55, 0.8)
        ctx.set_line_width(2.4 * u)
        ctx.stroke()
        cx = bx + bw * 0.4
    else:
        size = min(bh * 0.3, 44 * u)
        while True:
            lines = wrap(ctx, text, size, maxw, bold=False, max_lines=3)
            fits = len(lines) * size * 1.25 <= bh - 2 * pad * 0.6
            if fits and not (lines and lines[-1].endswith("…") and size > 16 * u):
                break
            if size <= 14 * u:
                lines = wrap(ctx, text, size, maxw, bold=False, max_lines=max(1, int((bh - pad) / (size * 1.25))))
                break
            size *= 0.9
        cx = bx + bw / 2
    total = len(lines) * size * 1.25
    y = by + bh / 2 - total / 2 + size * 0.62
    ctx.save()
    for i, line in enumerate(lines):
        ctx.new_path()
        text_path(ctx, line, cx, y + i * size * 1.25, size, bold=False)
        ctx.set_source_rgba(0.97, 0.97, 0.92, 0.88)
        ctx.fill_preserve()
        ctx.set_source_rgba(0.97, 0.97, 0.92, 0.3)
        ctx.set_line_width(1.6 * u)
        ctx.stroke()
        ctx.new_path()
        text_path(ctx, line, cx + 0.9 * u, y + i * size * 1.25 - 0.7 * u, size, bold=False)
        ctx.set_source_rgba(1, 1, 1, 0.22)
        ctx.fill()
    ctx.restore()


def _desk(ctx: cairo.Context, s: _S, x: float, gy: float, size: float) -> None:
    u = s.u
    wood = s.lit("#d9a066")
    metal = s.lit("#6c7a96")
    for dx in (-0.4, 0.4):
        ctx.rectangle(x + dx * size - 2 * u, gy - size * 0.45, 4 * u, size * 0.45)
    _fill_edge(ctx, metal, s.edge(metal), 1.4 * u)
    rrect(ctx, x - size * 0.5, gy - size * 0.52, size, size * 0.1, 3 * u)
    _fill_edge(ctx, wood, s.edge(wood), 1.8 * u)


# ======================= stage =======================
def _stage(s: _S) -> list[_Layer]:
    curtain = _accent(s, "#c8243a")
    bright = {"day": 1.0, "sunset": 0.92, "evening": 0.82, "night": 0.7}[s.time]

    def back(ctx, s, rg):
        x0, y0, x1, y1 = rg
        top = mul(hx("#1a0b3d"), bright)
        mid = mul(hx("#4b1d78"), bright)
        _vgrad(ctx, x0, y0, x1, y1, ((0, top), (0.8, mid), (1, mul(mid, 0.8))), ya=0, yb=s.gy)
        u = s.u
        # большая звезда-логотип на заднике
        star(ctx, s.w * 0.5, s.h * 0.36, 70 * u, 5, 0.45)
        ctx.set_source_rgba(1, 0.85, 0.4, 0.12)
        ctx.fill()
        _stars_static(ctx, s, rg, 50, s.gy * 0.9, 0.45)

    def back_anim(ctx, s, t, rg):
        _twinkle(ctx, s, t, rg, 18, s.gy * 0.9, "bulbs", (1.0, 0.9, 0.7))

    def curtains(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        c = s.lit(curtain)
        # боковые кулисы со складками
        for side in (-1, 1):
            edge_x = s.w * (0.16 if side < 0 else 0.84)
            outer = x0 if side < 0 else x1
            ctx.move_to(outer, y0)
            ctx.line_to(edge_x + side * 10 * u, y0)
            ctx.curve_to(edge_x - side * 6 * u, s.h * 0.35, edge_x + side * 30 * u, s.gy * 0.8,
                         edge_x - side * 18 * u, s.gy + 6 * u)
            ctx.line_to(outer, s.gy + 6 * u)
            ctx.close_path()
            g = cairo.LinearGradient(min(outer, edge_x), 0, max(outer, edge_x), 0)
            n = max(4, int(abs(edge_x - outer) / (34 * u)))
            for k in range(n + 1):
                f = k / n
                g.add_color_stop_rgb(f, *(lighten(c, 0.15) if k % 2 else mul(c, 0.62)))
            _fill_edge(ctx, g, s.edge(c), 2.4 * u)
        # ламбрекен с фестонами и золотой бахромой
        vy = s.h * 0.1
        ctx.move_to(x0, y0)
        ctx.line_to(x1, y0)
        ctx.line_to(x1, vy)
        sw = 80 * u
        xx = x1
        while xx > x0:
            ctx.curve_to(xx - sw * 0.2, vy + 34 * u, xx - sw * 0.8, vy + 34 * u, xx - sw, vy)
            xx -= sw
        ctx.close_path()
        g = _grad(y0, vy + 30 * u, (0, mul(c, 0.7)), (1, lighten(c, 0.1)))
        _fill_edge(ctx, g, s.edge(c), 2.4 * u)
        xx = x1
        while xx > x0:
            ctx.move_to(xx, vy)
            ctx.curve_to(xx - sw * 0.2, vy + 34 * u, xx - sw * 0.8, vy + 34 * u, xx - sw, vy)
            xx -= sw
        ctx.set_source_rgb(*s.lit("#ffcc33"))
        ctx.set_line_width(5 * u)
        ctx.stroke()
        if s.text.strip():
            _marquee(ctx, s, s.text)

    def curtains_anim(ctx, s, t, rg):
        if not s.text.strip():
            return
        # лампочки вокруг табло бегут огоньком
        bx, by, bw, bh = _marquee_box(ctx, s, s.text)
        u = s.u
        n = max(8, int((bw + bh) * 2 / (22 * u)))
        for i in range(n):
            f = i / n
            per = 2 * (bw + bh)
            d = f * per
            if d < bw:
                px, py = bx + d, by
            elif d < bw + bh:
                px, py = bx + bw, by + d - bw
            elif d < 2 * bw + bh:
                px, py = bx + bw - (d - bw - bh), by + bh
            else:
                px, py = bx, by + bh - (d - 2 * bw - bh)
            on = (i + int(t * 8)) % 3 == 0
            ctx.arc(px, py, 3.6 * u, 0, 2 * math.pi)
            ctx.set_source_rgb(*((1.0, 0.95, 0.6) if on else (0.6, 0.45, 0.2)))
            ctx.fill()

    def floor(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        wood = mul(s.lit("#b8743e"), bright)
        _vgrad(ctx, x0, s.gy, x1, y1, ((0, mul(wood, 0.75)), (1, wood)), ya=s.gy, yb=s.h)
        vx, vy = s.w * 0.5, s.gy - 500 * u
        ctx.set_source_rgba(*s.edge(wood), 0.5)
        ctx.set_line_width(1.6 * u)
        for i in range(-40, 41):
            bx = s.w * 0.5 + i * 58 * u
            k = (s.gy - vy) / (y1 - vy)
            ctx.move_to(vx + (bx - vx) * k, s.gy)
            ctx.line_to(bx, y1)
        ctx.stroke()
        ctx.rectangle(x0, s.gy - 3 * u, x1 - x0, 6 * u)
        ctx.set_source_rgb(*mul(wood, 0.6))
        ctx.fill()

    def floor_anim(ctx, s, t, rg):
        u = s.u
        # прожекторы (аддитивно), качаются; пятна света на полу
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        cols = ((1.0, 0.3, 0.7), (0.4, 0.6, 1.0), (1.0, 0.8, 0.3))
        k_amp = 0.2 if s.dark else 0.15
        ln = s.gy * 1.25
        for k, (fx, col) in enumerate(zip((0.18, 0.5, 0.82), cols, strict=True)):
            x0 = s.w * fx
            a = 0.33 * math.sin(t * 1.1 + k * 2.1)
            _beam(ctx, x0, -30 * u, a, ln, 10 * u, 150 * u, col, k_amp)
            fx_ = x0 - math.sin(a) * (ln - 30 * u) * 0.95
            pool = _glow_sprite(s, ("pool", k), col, 170 * u, 0.32, 0.22)
            _blit(ctx, pool, fx_, s.gy + (s.h - s.gy) * 0.45, px=pool.get_width() / 2, py=pool.get_height() / 2)
        ctx.restore()
        # зрители — силуэты голов покачиваются у нижнего края
        x0r, _, x1r, _ = rg
        r = s.r("crowd")
        n = int((x1r - x0r) / (44 * u)) + 2
        crowd = mul(hx("#120626"), 1.0)
        for i in range(n):
            cx = x0r + i * 44 * u + r.uniform(-8, 8) * u
            hr = r.uniform(20, 27) * u
            bob = 5 * u * abs(math.sin(t * (2.2 + r.uniform(0, 1.2)) + i * 0.7))
            cy = s.h + hr * 0.25 - bob
            ctx.new_sub_path()
            ctx.arc(cx, cy, hr, 0, 2 * math.pi)
            ellipse(ctx, cx, cy + hr * 1.6, hr * 1.5, hr * 1.0)
            if r.random() < 0.25:  # поднятая рука
                ctx.new_sub_path()
                ctx.arc(cx + hr * 0.9, cy - hr * 1.3 - bob, hr * 0.3, 0, 2 * math.pi)
                ctx.rectangle(cx + hr * 0.75, cy - hr * 1.3 - bob, hr * 0.3, hr * 1.4)
        ctx.set_source_rgb(*crowd)
        ctx.fill()

    return [_Layer(0.3, back, back_anim), _Layer(0.85, curtains, curtains_anim, -9, HORIZON["stage"] + 0.02),
            _Layer(1.0, floor, floor_anim, HORIZON["stage"] - 0.02, 9)]


def _marquee_box(ctx: cairo.Context, s: _S, text: str) -> tuple[float, float, float, float]:
    u = s.u
    clean, _ = clean_text(text, 30)
    size = 30 * u
    ctx.save()
    ctx.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)
    tw = ctx.text_extents(clean)[4] if clean else 0
    ctx.restore()
    tw = min(tw, s.w * 0.6)
    bw, bh = tw + 50 * u, 52 * u
    return s.w / 2 - bw / 2, s.h * 0.16, bw, bh


def _marquee(ctx: cairo.Context, s: _S, text: str) -> None:
    u = s.u
    clean, _ = clean_text(text, 30)
    bx, by, bw, bh = _marquee_box(ctx, s, text)
    rrect(ctx, bx, by, bw, bh, 10 * u)
    _fill_edge(ctx, _grad(by, by + bh, (0, hx("#3a1460")), (1, hx("#1c0838"))), hx("#ffcc33"), 4 * u)
    size = 30 * u
    ctx.save()
    ctx.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)
    tw = ctx.text_extents(clean)[4] if clean else 1
    k = min(1.0, (bw - 30 * u) / max(1.0, tw))
    ctx.restore()
    ctx.new_path()
    text_path(ctx, clean, s.w / 2, by + bh / 2, size * k, True)
    ctx.set_source_rgb(1.0, 0.86, 0.35)
    ctx.fill()


# ======================= party =======================
def _ihash(*k: int) -> float:
    """Быстрый целочисленный хэш → 0..1 (для того, что считается каждый кадр: плитки, огоньки)."""
    h = 0x9E3779B9
    for v in k:
        h = ((h ^ (v & 0xFFFFFFFF)) * 0x85EBCA6B) & 0xFFFFFFFF
        h ^= h >> 13
        h = (h * 0xC2B2AE35) & 0xFFFFFFFF
        h ^= h >> 16
    return h / 4294967296.0


def _party(s: _S) -> list[_Layer]:
    base_wall = _accent(s, "#ffc2df")
    dim = {"day": 0.0, "sunset": 0.2, "evening": 0.45, "night": 0.62}[s.time]
    wall = mix(base_wall, hx("#3a1d5e"), dim)
    ball = (s.w * 0.76, s.h * 0.21, 44 * s.u)

    def wall_layer(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        c = s.lit(wall)
        ctx.rectangle(x0, y0, x1 - x0, s.gy - y0)
        ctx.set_source(_grad(0, s.gy, (0, lighten(c, 0.06)), (1, mul(c, 0.82))))
        ctx.fill()
        # широкие полосы обоев
        i0 = int(x0 // (90 * u)) - 1
        for i in range(i0, i0 + int((x1 - x0) / (90 * u)) + 3):
            ctx.rectangle(i * 90 * u, y0, 45 * u, s.gy - y0)
        ctx.set_source_rgba(*lighten(c, 0.12), 0.5)
        ctx.fill()
        r = s.r("partywall")
        for _ in range(int(40 * (x1 - x0) / s.w)):
            px, py = r.uniform(x0, x1), r.uniform(y0, s.gy - 20 * u)
            col = s.lit(r.choice(CONFETTI))
            if r.random() < 0.5:
                ctx.arc(px, py, r.uniform(3, 6) * u, 0, 2 * math.pi)
            else:
                star(ctx, px, py, r.uniform(5, 8) * u, 5, 0.5, r.uniform(0, 6))
            ctx.set_source_rgba(*col, 0.4)
            ctx.fill()
        # серпантин свисает с потолка
        for x in _xs(s, rg, "streamers", (110, 190)):
            col = s.lit(r.choice(CONFETTI))
            ln = r.uniform(0.18, 0.34) * s.h
            ctx.move_to(x, y0)
            yy = 0.0
            k = 0
            while yy < ln:
                yy += 16 * u
                ctx.line_to(x + (7 if k % 2 else -7) * u, yy)
                k += 1
            ctx.set_source_rgb(*col)
            ctx.set_line_width(4 * u)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke()
        ctx.rectangle(x0, s.gy - 14 * u, x1 - x0, 14 * u)
        _fill_edge(ctx, s.lit("#ffffff"), s.edge(c), 1.6 * u)
        bx, by, br = ball
        ctx.move_to(bx, y0)
        ctx.line_to(bx, by - br)
        ctx.set_source_rgb(*s.edge(c))
        ctx.set_line_width(2 * u)
        ctx.stroke()

    def wall_anim(ctx, s, t, rg):
        u = s.u
        x0, _, x1, _ = rg
        # пятна света от диско-шара бегут по стене (аддитивно; по одной заливке на цвет)
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        n = int(18 * (x1 - x0) / s.w)
        amp = 0.25 + 0.3 * dim
        for ci, col in enumerate(CONFETTI):
            for i in range(ci, n, len(CONFETTI)):
                px = x0 + ((_ihash(s.seed, i, 1) * (x1 - x0) + t * 70 * u) % (x1 - x0))
                py = s.gy * (0.1 + 0.8 * _ihash(s.seed, i, 2)) + 10 * u * math.sin(t * 2 + i)
                ctx.new_sub_path()
                ellipse(ctx, px, py, 10 * u, 7 * u)
            ctx.set_source_rgba(*hx(col), amp)
            ctx.fill()
        ctx.restore()
        text, _ = clean_text(s.text, 24)
        _bunting(ctx, s, t, rg, [ch for ch in text.upper()] if text.strip() else [])
        _balloon_cluster(ctx, s, t, s.w * 0.08, s.h * 0.38, 1)
        _balloon_cluster(ctx, s, t, s.w * 0.92, s.h * 0.36, -1)
        bx, by, br = ball
        _disco(ctx, s, bx, by, br, t)

    def floor_tiles(s):
        tiles = s.memo.get("tiles")
        if tiles is None:
            u = s.u
            vx, vy = s.w * 0.5, s.gy - 400 * u
            mx = layer_margin(s.w, s.h, 1.0)[0]
            rows = [s.gy]
            step = 18 * u
            while rows[-1] < s.h * 1.3:
                rows.append(rows[-1] + step)
                step *= 1.3
            tiles = []
            for ri in range(len(rows) - 1):
                ya, yb = rows[ri], rows[ri + 1]
                ka, kb = (ya - vy) / (s.h - vy), (yb - vy) / (s.h - vy)
                for i in range(-24, 25):
                    xb0, xb1 = s.w * 0.5 + i * 80 * u, s.w * 0.5 + (i + 1) * 80 * u
                    quad = ((vx + (xb0 - vx) * ka, ya), (vx + (xb1 - vx) * ka, ya), (vx + (xb1 - vx) * kb, yb),
                            (vx + (xb0 - vx) * kb, yb))
                    if max(q[0] for q in quad) < -mx or min(q[0] for q in quad) > s.w + mx:
                        continue
                    tiles.append((ri, i, quad))
            s.memo["tiles"] = tiles
        return tiles

    def floor(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        base = s.lit("#2a1f48")
        _vgrad(ctx, x0, s.gy, x1, y1, ((0, mul(base, 0.8)), (1, base)), ya=s.gy, yb=s.h)
        for ri, i, quad in floor_tiles(s):
            col = hx(CONFETTI[(i * 3 + ri * 5) % len(CONFETTI)])
            ctx.move_to(*quad[0])
            for q in quad[1:]:
                ctx.line_to(*q)
            ctx.close_path()
            ctx.set_source_rgba(*mul(col, 0.35), 0.55)
            ctx.fill_preserve()
            ctx.set_source_rgba(0.06, 0.03, 0.12, 0.7)
            ctx.set_line_width(1.6 * u)
            ctx.stroke()

    def floor_anim(ctx, s, t, rg):
        beat = int(t * 2.5)
        x0, _, x1, _ = rg
        lit: dict[int, list] = {}
        for ri, i, quad in floor_tiles(s):
            if _ihash(s.seed, ri, i, beat) < 0.22:
                lit.setdefault((i * 3 + ri * 5 + beat) % len(CONFETTI), []).append(quad)
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        for ci, quads in lit.items():
            for quad in quads:
                ctx.move_to(*quad[0])
                for q in quad[1:]:
                    ctx.line_to(*q)
                ctx.close_path()
            ctx.set_source_rgba(*hx(CONFETTI[ci]), 0.55)
            ctx.fill()
        ctx.restore()

    return [_Layer(0.85, wall_layer, wall_anim, -9, HORIZON["party"] + 0.01),
            _Layer(1.0, floor, floor_anim, HORIZON["party"] - 0.02, 9)]


def _bunting(ctx: cairo.Context, s: _S, t: float, rg: Region, letters: list[str]) -> None:
    """Гирлянда флажков: провисает и чуть качается; с буквами background.text, если она есть."""
    u = s.u
    x0, _, x1, _ = rg
    yb = s.h * 0.05
    if letters:
        n = len(letters)
        fw = min(52 * u, s.w * 0.84 / n)
        xa, xb = s.w / 2 - fw * n / 2 - fw * 1.2, s.w / 2 + fw * n / 2 + fw * 1.2
        xs = [s.w / 2 - fw * n / 2 + fw * (i + 0.5) for i in range(n)]
    else:
        fw = 46 * u
        xa, xb = x0, x1
        xs = [xa + fw * (i + 0.5) for i in range(int((xb - xa) / fw))]
    sag = (34 + 6 * math.sin(t * 1.2)) * u
    ctx.move_to(xa, yb)
    ctx.curve_to(xa + (xb - xa) * 0.3, yb + sag * 1.33, xb - (xb - xa) * 0.3, yb + sag * 1.33, xb, yb)
    ctx.set_source_rgb(*s.edge(s.lit("#ffffff")))
    ctx.set_line_width(2 * u)
    ctx.stroke()
    fh = fw * (1.15 if letters else 0.95)
    groups: dict[int, list[tuple[float, float, float]]] = {}
    for i, fx in enumerate(xs):
        f = (fx - xa) / max(1.0, xb - xa)
        fy = yb + sag * 4 * f * (1 - f)
        groups.setdefault(i % len(CONFETTI), []).append((fx, fy, 0.06 * math.sin(t * 2.0 + i * 0.8)))
    for ci, items in groups.items():
        col = s.lit(CONFETTI[ci])
        for fx, fy, a in items:
            ca, sa = math.cos(a), math.sin(a)
            for k, (px, py) in enumerate(((-fw * 0.46, 0.0), (fw * 0.46, 0.0), (0.0, fh))):
                (ctx.move_to if k == 0 else ctx.line_to)(fx + px * ca - py * sa, fy + px * sa + py * ca)
            ctx.close_path()
        _fill_edge(ctx, col, s.edge(col), 1.6 * u)
    if letters:
        for i, fx in enumerate(xs):
            if not letters[i].strip():
                continue
            f = (fx - xa) / max(1.0, xb - xa)
            fy = yb + sag * 4 * f * (1 - f)
            a = 0.06 * math.sin(t * 2.0 + i * 0.8)
            ctx.save()
            ctx.translate(fx, fy)
            ctx.rotate(a)
            ctx.new_path()
            text_path(ctx, letters[i], 0, fh * 0.33, fw * 0.5, True)
            ctx.set_source_rgb(1, 1, 1)
            ctx.fill_preserve()
            ctx.set_source_rgba(*INK, 0.5)
            ctx.set_line_width(1.0 * u)
            ctx.stroke()
            ctx.restore()


def _balloon_sprite(s: _S, key: object, r: float, col: RGB) -> tuple[cairo.ImageSurface, float, float]:
    w, h = r * 2.2, r * 2.6
    px, py = w / 2, r * 1.15

    def draw(c: cairo.Context) -> None:
        x, y = px, py
        ellipse(c, x, y, r * 0.86, r)
        g = cairo.RadialGradient(x - r * 0.3, y - r * 0.4, r * 0.1, x, y, r * 1.1)
        g.add_color_stop_rgb(0, *lighten(col, 0.45))
        g.add_color_stop_rgb(0.6, *col)
        g.add_color_stop_rgb(1, *mul(col, 0.7))
        _fill_edge(c, g, s.edge(col), 2 * s.u)
        c.move_to(x - r * 0.15, y + r * 1.12)
        c.line_to(x + r * 0.15, y + r * 1.12)
        c.line_to(x, y + r * 0.96)
        c.close_path()
        _fill_edge(c, col, s.edge(col), 1.4 * s.u)
        ellipse(c, x - r * 0.35, y - r * 0.4, r * 0.14, r * 0.24, -0.5)
        c.set_source_rgba(1, 1, 1, 0.7)
        c.fill()

    return _sprite(s, ("balloon", key), w, h, draw), px, py


def _balloon_cluster(ctx: cairo.Context, s: _S, t: float, ax: float, ay: float, side: int) -> None:
    """Три шарика, привязанные к одной точке у пола, покачиваются."""
    u = s.u
    tie = (ax, s.gy - 16 * u)
    items = []
    for j in range(3):
        bx = ax + (j - 1) * 34 * u * side + 4 * u * math.sin(t * 1.1 + j)
        by = ay + (abs(j - 1) * 0.05 - 0.02) * s.h + 7 * u * math.sin(t * 1.3 + j * 1.7 + side)
        col = s.lit(CONFETTI[(j * 2 + (side > 0)) % len(CONFETTI)])
        items.append((bx, by, col, j))
    for bx, by, col, j in items:
        ctx.move_to(bx, by + 46 * u)
        ctx.curve_to(bx + 6 * u * math.sin(t * 2 + j), by + 90 * u, tie[0], tie[1] - 60 * u, *tie)
    ctx.set_source_rgba(*s.edge(s.lit("#ffffff")), 0.8)
    ctx.set_line_width(1.4 * u)
    ctx.stroke()
    for bx, by, col, j in items:
        sp, px, py = _balloon_sprite(s, (side, j), 40 * u, col)
        _blit(ctx, sp, bx, by, px=px, py=py)


def _disco(ctx: cairo.Context, s: _S, x: float, y: float, r: float, t: float) -> None:
    """2D диско-шар: грани переливаются при вращении (4 ступени яркости — 4 заливки), блики-искры."""
    u = s.u
    glow = _glow_sprite(s, "disco", (0.8, 0.85, 1.0), r * 2.6, 0.3)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    _blit(ctx, glow, x, y, px=r * 2.6, py=r * 2.6)
    ctx.restore()

    def base(c: cairo.Context) -> None:
        c.arc(r + 3 * u, r + 3 * u, r, 0, 2 * math.pi)
        g = cairo.RadialGradient(r * 0.7 + 3 * u, r * 0.65 + 3 * u, r * 0.1, r + 3 * u, r + 3 * u, r)
        g.add_color_stop_rgb(0, 0.85, 0.87, 0.95)
        g.add_color_stop_rgb(1, 0.35, 0.37, 0.5)
        _fill_edge(c, g, INK, 2.4 * u)

    sp = _sprite(s, ("discobase", round(r, 2)), 2 * r + 6 * u, 2 * r + 6 * u, base)
    _blit(ctx, sp, x, y, px=r + 3 * u, py=r + 3 * u)
    buckets: list[list[tuple[float, float, float, float]]] = [[], [], [], []]
    rows = 8
    for j in range(rows):
        lat = -math.pi / 2 + (j + 0.5) * math.pi / rows
        yy = y + math.sin(lat) * r * 0.94
        ring = math.cos(lat) * r * 0.94
        n = max(4, int(14 * math.cos(lat)) + 2)
        chh = math.pi * r / rows * 0.4
        for k in range(n):
            lon = (k / n) * 2 * math.pi + t * 1.2
            c = math.cos(lon)
            if c < 0.08:
                continue
            xx = x + math.sin(lon) * ring
            cw = (2 * math.pi * ring / n) * c * 0.4
            v = _ihash(s.seed, j, k)
            bright = max(0.0, math.sin(lon * 2 + v * 6 + t * 3))
            buckets[min(3, int(bright * 4))].append((xx - cw, yy - chh, cw * 2, chh * 2))
    for b, rects in enumerate(buckets):
        for rx, ry, rw, rh in rects:
            ctx.rectangle(rx, ry, rw, rh)
        ctx.set_source_rgba(*mix((0.55, 0.6, 0.82), (1, 1, 1), (b + 0.5) / 4), 0.9)
        ctx.fill()
    for i in range(3):
        a = t * 2 + i * 2.1
        k = 0.5 + 0.5 * math.sin(t * 5 + i * 1.7)
        ctx.new_sub_path()
        sparkle(ctx, x + math.cos(a) * r * 0.6, y + math.sin(a) * r * 0.5, (7 + 9 * k) * u)
    ctx.set_source_rgba(1, 1, 1, 0.85)
    ctx.fill()


# ======================= winter =======================
def _winter(s: _S) -> list[_Layer]:
    house = (s.w * 0.72, s.gy + 6 * s.u, 120 * s.u)

    def sky(ctx, s, rg):
        stops = {"day": ((0, "#7fb6ef"), (0.6, "#bfe0ff"), (1, "#eef7ff"))}.get(s.time, SKY[s.time])
        x0, y0, x1, y1 = rg
        _vgrad(ctx, x0, y0, x1, y1, OVERCAST[s.time] if s.overcast else stops, ya=0, yb=s.gy)
        if s.dark:
            _stars_static(ctx, s, rg, 80 if s.night else 25, s.gy * 0.8)
        _sky_body(ctx, s, s.w * 0.22, s.h * 0.15, 40 * s.u)

    def sky_anim(ctx, s, t, rg):
        if s.night and not s.overcast:
            _aurora(ctx, s, t, rg)
        if s.dark and not s.overcast:
            _twinkle(ctx, s, t, rg, 14, s.gy * 0.7)
        if not s.dark:
            _clouds_anim(2, 0.06, 0.2)(ctx, s, t, rg)

    def far(ctx, s, rg):
        u = s.u
        x0, y0, x1, y1 = rg
        r = s.r("mountains")
        x = x0 - 100 * u
        peaks = []
        while x < x1 + 100 * u:
            peaks.append((x, r.uniform(150, 260) * u, r.uniform(130, 220) * u))
            x += r.uniform(140, 230) * u
        rock = s.lit("#8fa6c8", 0.55)
        snow = s.lit("#f4f8ff", 0.35)
        for px, ph, pw in peaks:
            base = s.gy + 10 * u
            ctx.move_to(px - pw, base)
            ctx.line_to(px, base - ph)
            ctx.line_to(px + pw, base)
            ctx.close_path()
            ctx.set_source(_grad(base - ph, base, (0, lighten(rock, 0.1)), (1, mul(rock, 0.85))))
            ctx.fill()
            ctx.move_to(px - pw * 0.32, base - ph * 0.68)
            ctx.line_to(px, base - ph)
            ctx.line_to(px + pw * 0.32, base - ph * 0.68)
            for j in range(4):
                ctx.line_to(px + pw * (0.24 - 0.16 * j), base - ph * (0.6 + 0.06 * (j % 2)))
            ctx.close_path()
            ctx.set_source_rgb(*snow)
            ctx.fill()
        _hills(ctx, s, rg, s.gy - 10 * u, 40 * u, 170 * u, 2.2, s.lit("#e8f1ff", 0.3), s.lit("#cfe0f7", 0.3))

    def mid(ctx, s, rg):
        u = s.u
        r = s.r("wpines")
        hx_, hy, hs = house
        for x in _xs(s, rg, "wp", (80, 160), avoid=(0.32, 0.86)):
            _pine(ctx, s, x, s.gy + 12 * u, r.uniform(180, 260) * u, hx("#2e7d5b"), 0.15, snow=True)
        _house(ctx, s, hx_, hy, hs)
        _pine(ctx, s, hx_ + hs * 1.1, s.gy + 14 * u, 200 * u, hx("#2e7d5b"), 0.1, snow=True)

    def mid_anim(ctx, s, t, rg):
        hx_, hy, hs = house
        _chimney_smoke(ctx, s, hx_ + hs * 0.38, hy - hs * 1.33, hs * 0.16, t)

    def ground(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        snow = s.lit("#f7fbff")
        shade = s.lit("#cfdcf5")
        _vgrad(ctx, x0, s.gy, x1, y1, ((0, shade), (0.3, snow), (1, mix(snow, shade, 0.4))), ya=s.gy, yb=s.h)
        r = s.r("drifts")
        for _ in range(int(7 * (x1 - x0) / s.w)):
            cx, cy = r.uniform(x0, x1), s.h * r.uniform(0.76, 1.0)
            ellipse(ctx, cx, cy, r.uniform(60, 140) * u, r.uniform(8, 16) * u)
            ctx.set_source_rgba(*shade, 0.6)
            ctx.fill()
        for x in _xs(s, rg, "wbush", (160, 280), avoid=(0.25, 0.75)):
            _bush(ctx, s, x, s.gy + 20 * u, 30 * u, hx("#3f8f5f"), 0.05)
            for dx, dy, k in ((-0.5, -0.62, 0.32), (0.05, -0.85, 0.36), (0.55, -0.6, 0.3)):
                ellipse(ctx, x + dx * 30 * u, s.gy + 20 * u + dy * 30 * u, k * 34 * u, k * 18 * u)
            ctx.set_source_rgb(*snow)
            ctx.fill()
        # заборчик
        fy = s.gy + 30 * u
        wood = s.lit("#b07a4a")
        for x in _xs(s, (x0, 0, int(s.w * 0.3), 0), "fence", (26, 26), pad=0):
            rrect(ctx, x, fy - 44 * u, 12 * u, 44 * u, 3 * u)
            _fill_edge(ctx, wood, s.edge(wood), 1.4 * u)
            ellipse(ctx, x + 6 * u, fy - 44 * u, 8 * u, 4 * u)
            ctx.set_source_rgb(*snow)
            ctx.fill()

    def ground_anim(ctx, s, t, rg):
        # искорки на снегу
        _twinkle(ctx, s, t, (rg[0], int(s.gy + 10 * s.u), rg[2], rg[3]), 20, s.h, "snowglint", (1, 1, 1))

    return [_Layer(0.1, sky, sky_anim), _Layer(0.3, far, None, 0.2, 9), _Layer(0.6, mid, mid_anim, 0.1, 9),
            _Layer(1.0, ground, ground_anim, HORIZON["winter"] - 0.01, 9)]


def _house(ctx: cairo.Context, s: _S, x: float, gy: float, size: float) -> None:
    """Домик со снегом на крыше и тёплым окном (вечером/ночью светится)."""
    u = s.u
    lw = 2.2 * u
    wall = s.lit("#e2896b", 0.1)
    roof = s.lit("#8a4a6b", 0.1)
    snow = s.lit("#f7fbff", 0.05)
    w = size
    ctx.rectangle(x - w * 0.5, gy - w * 0.75, w, w * 0.75)
    _fill_edge(ctx, _grad(gy - w * 0.75, gy, (0, lighten(wall, 0.1)), (1, mul(wall, 0.85))), s.edge(wall), lw)
    ctx.rectangle(x + w * 0.28, gy - w * 1.33, w * 0.16, w * 0.4)
    _fill_edge(ctx, s.lit("#a35a4a", 0.1), s.edge(wall), lw)
    ctx.move_to(x - w * 0.65, gy - w * 0.72)
    ctx.line_to(x, gy - w * 1.25)
    ctx.line_to(x + w * 0.65, gy - w * 0.72)
    ctx.close_path()
    _fill_edge(ctx, roof, s.edge(roof), lw)
    ctx.move_to(x - w * 0.7, gy - w * 0.68)
    ctx.line_to(x, gy - w * 1.3)
    ctx.line_to(x + w * 0.7, gy - w * 0.68)
    ctx.curve_to(x + w * 0.6, gy - w * 0.62, x + w * 0.5, gy - w * 0.78, x + w * 0.4, gy - w * 0.75)
    ctx.curve_to(x + w * 0.2, gy - w * 0.95, x - w * 0.3, gy - w * 0.72, x - w * 0.45, gy - w * 0.8)
    ctx.curve_to(x - w * 0.55, gy - w * 0.66, x - w * 0.65, gy - w * 0.62, x - w * 0.7, gy - w * 0.68)
    ctx.close_path()
    _fill_edge(ctx, snow, s.edge(mul(snow, 0.8)), lw * 0.8)
    lit = s.dark or s.overcast or s.time == "sunset"
    wcol = (1.0, 0.82, 0.4) if lit else s.lit("#bfe3ff", 0.1)
    ctx.rectangle(x - w * 0.32, gy - w * 0.55, w * 0.24, w * 0.22)
    _fill_edge(ctx, wcol, s.edge(wall), lw)
    rrect(ctx, x + w * 0.08, gy - w * 0.48, w * 0.22, w * 0.48, 3 * u)
    _fill_edge(ctx, s.lit("#7a4a35", 0.1), s.edge(wall), lw)
    if lit:
        _glow(ctx, x - w * 0.2, gy - w * 0.44, w * 0.55, (1.0, 0.75, 0.35), 0.45 if s.dark else 0.25, add=True)
        _glow(ctx, x - w * 0.2, gy + w * 0.08, w * 0.5, (1.0, 0.75, 0.35), 0.25, add=True, sy=0.25)


def _chimney_smoke(ctx: cairo.Context, s: _S, x: float, y: float, size: float, t: float) -> None:
    col = (0.95, 0.95, 1.0) if not s.dark else (0.6, 0.62, 0.75)
    for i in range(5):
        ph = (t * 0.35 + i / 5.0) % 1.0
        px = x + 30 * s.u * ph + 6 * s.u * math.sin(t * 1.3 + i)
        py = y - 120 * s.u * ph
        r = size * (0.6 + 1.4 * ph)
        a = 0.75 * (1 - ph) * min(1.0, ph * 6)
        ctx.arc(px, py, r, 0, 2 * math.pi)
        ctx.set_source_rgba(*col, a)
        ctx.fill()


def _aurora(ctx: cairo.Context, s: _S, t: float, rg: Region) -> None:
    x0, _, x1, _ = rg
    u = s.u
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for band, (col, yy, amp) in enumerate((((0.2, 1.0, 0.6), 0.16, 24), ((0.5, 0.4, 1.0), 0.24, 30))):
        step = 24 * u
        x = x0
        pts = []
        while x <= x1 + step:
            y = s.h * yy + amp * u * math.sin(x / (160 * u) + t * 0.4 + band) + 12 * u * math.sin(x / (53 * u) - t)
            pts.append((x, y))
            x += step
        hgt = 90 * u
        for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:], strict=True):
            ctx.move_to(ax, ay)
            ctx.line_to(bx, by)
            ctx.line_to(bx, by + hgt)
            ctx.line_to(ax, ay + hgt)
            ctx.close_path()
        g = _grad(s.h * yy - amp * u, s.h * yy + hgt, (0, (*col, 0.0)), (0.35, (*col, 0.22)), (1, (*col, 0.0)))
        ctx.set_source(g)
        ctx.fill()
    ctx.restore()


# ======================= underwater =======================
_WATER = {
    "day": ("#7fe0f0", "#1d8fc9", "#0b4f8a"),
    "sunset": ("#8fd0e8", "#2f6fb5", "#1d3a7a"),
    "evening": ("#3f8fb8", "#1a4f8a", "#0d2a5a"),
    "night": ("#1f5a8a", "#0d2f5a", "#051836"),
}


def _underwater(s: _S) -> list[_Layer]:
    top, mid_c, deep = (hx(c) for c in _WATER[s.time])

    def water(ctx, s, rg):
        x0, y0, x1, y1 = rg
        _vgrad(ctx, x0, y0, x1, y1, ((0, top), (0.45, mid_c), (1, deep)), ya=0, yb=s.gy)

    def water_anim(ctx, s, t, rg):
        x0, _, x1, _ = rg
        u = s.u
        # блики поверхности
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        step = 20 * u
        x = x0
        ctx.move_to(x0, -40 * u)
        while x <= x1 + step:
            ctx.line_to(x, s.h * 0.03 + 6 * u * math.sin(x / (50 * u) + t * 1.4) + 4 * u * math.sin(x / (21 * u) - t))
            x += step
        ctx.line_to(x1, -40 * u)
        ctx.close_path()
        ctx.set_source_rgba(0.7, 1.0, 1.0, 0.25)
        ctx.fill()
        # лучи света качаются (сплошные полупрозрачные конусы — градиент на всю высоту слишком дорог)
        ld = 0.06 if not s.dark else 0.03
        for i in range(5):
            bx = x0 + (x1 - x0) * (i + 0.5) / 5 + 40 * u * math.sin(t * 0.3 + i)
            a = ld * (0.6 + 0.4 * math.sin(t * 0.8 + i * 1.7))
            _beam(ctx, bx, -10 * u, -0.22 + 0.05 * math.sin(t * 0.4 + i), s.gy * 1.1, 22 * u, 70 * u,
                  (0.8, 1.0, 1.0), a)
        ctx.restore()
        # стайка рыбок-силуэтов
        span = x1 - x0 + 300 * u
        fx = x1 + 150 * u - ((t * 30 * u + hash01(s.seed, "school") * span) % span)
        fy = s.h * 0.3
        sil = mix(mid_c, deep, 0.5)
        for j in range(9):
            px = fx + (j % 3) * 26 * u + (j // 3) * 14 * u
            py = fy + (j // 3) * 16 * u + 4 * u * math.sin(t * 3 + j)
            ellipse(ctx, px, py, 9 * u, 4.5 * u)
            ctx.move_to(px + 7 * u, py)
            ctx.line_to(px + 15 * u, py - 5 * u)
            ctx.line_to(px + 15 * u, py + 5 * u)
            ctx.close_path()
        ctx.set_source_rgba(*sil, 0.7)
        ctx.fill()

    def reef(ctx, s, rg):
        u = s.u
        x0, y0, x1, y1 = rg
        rock = mix(mid_c, deep, 0.5)
        _hills(ctx, s, rg, s.gy - 30 * u, 70 * u, 120 * u, 0.8, lighten(rock, 0.05), mul(rock, 0.9))
        r = s.r("farcoral")
        for x in _xs(s, rg, "fc", (60, 120)):
            _coral(ctx, s, x, s.gy - 10 * u, r.uniform(40, 70) * u, mix(rock, hx("#ff8fb1"), 0.3), r, lw=0)

    def mid(ctx, s, rg):
        u = s.u
        r = s.r("coral")
        for x in _xs(s, rg, "mc", (130, 220), avoid=(0.3, 0.7)):
            col = hx(r.choice(("#ff7eb6", "#ff9f1c", "#b48cff", "#ff5a5f")))
            if r.random() < 0.6:
                _coral(ctx, s, x, s.gy + 14 * u, r.uniform(70, 110) * u, s.lit(col, 0.0, True), r)
            else:
                _brain_coral(ctx, s, x, s.gy + 14 * u, r.uniform(30, 44) * u, s.lit(col, 0.0, True))

    def mid_anim(ctx, s, t, rg):
        u = s.u
        r = s.r("seaweed")
        for x in _xs(s, rg, "sw", (90, 170)):
            hgt = r.uniform(150, 260) * u
            _seaweed(ctx, s, x, s.gy + 16 * u, hgt, t, r.random() * 6)
        # рыбки
        x0, _, x1, _ = rg
        span = x1 - x0 + 200 * u
        for i in range(3):
            d = 1 if i % 2 else -1
            sp = (40 + 20 * i) * u
            ph = hash01(s.seed, "fish", i)
            x = (x0 - 100 * u + (ph * span + sp * t) % span) if d > 0 else (x1 + 100 * u - (ph * span + sp * t) % span)
            y = s.h * (0.35 + 0.12 * i) + 10 * u * math.sin(t * 1.5 + i)
            col = s.lit(("#ffb347", "#ff6b6b", "#ffd23f")[i], 0.0, True)
            _fish(ctx, s, x, y, (18 + 4 * i) * u, col, d, t)
        if s.dark:
            _fireflies(ctx, s, t, rg, 14, s.h * 0.1, s.gy)

    def floor(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        sand = s.lit("#f2d6a2", 0.0, True)
        sand = mix(sand, mid_c, 0.25)
        _hills(ctx, s, rg, s.gy + 8 * u, 14 * u, 130 * u, 1.1, lighten(sand, 0.08), mul(sand, 0.8),
               s.edge(sand), 1.6 * u)
        r = s.r("ripples")
        for _ in range(int(16 * (x1 - x0) / s.w)):
            cx, cy = r.uniform(x0, x1), s.h * r.uniform(0.8, 1.0)
            ctx.move_to(cx - 30 * u, cy)
            ctx.curve_to(cx - 10 * u, cy - 6 * u, cx + 10 * u, cy - 6 * u, cx + 30 * u, cy)
        ctx.set_source_rgba(*mul(sand, 0.8), 0.7)
        ctx.set_line_width(2 * u)
        ctx.stroke()
        for _ in range(int(7 * (x1 - x0) / s.w)):
            sx, sy = r.uniform(x0, x1), s.h * r.uniform(0.82, 1.0)
            if r.random() < 0.4:
                star(ctx, sx, sy, 11 * u, 5, 0.5, r.uniform(0, 6))
                col = s.lit("#ff8a5c", 0.0, True)
                _fill_edge(ctx, col, s.edge(col), 1.4 * u)
            else:
                ellipse(ctx, sx, sy, 14 * u, 9 * u)
                col = s.lit("#8a8fa8", 0.0, True)
                _fill_edge(ctx, col, s.edge(col), 1.6 * u)

    def floor_anim(ctx, s, t, rg):
        x0, _, x1, _ = rg
        u = s.u
        # пузырьки поднимаются из пары мест
        for src in range(int(3 * (x1 - x0) / s.w) + 1):
            bx = x0 + (x1 - x0) * hash01(s.seed, "bsrc", src)
            for k in range(6):
                ph = (t * 0.25 + k / 6.0 + hash01(s.seed, "bph", src)) % 1.0
                y = s.h * 0.92 - ph * s.h * 0.85
                x = bx + 8 * u * math.sin(t * 2 + k + ph * 6)
                rr = (3 + 4 * hash01(s.seed, "br", src, k)) * u * (0.6 + ph)
                ctx.arc(x, y, rr, 0, 2 * math.pi)
                ctx.set_source_rgba(0.85, 1, 1, 0.25)
                ctx.fill_preserve()
                ctx.set_source_rgba(1, 1, 1, 0.75)
                ctx.set_line_width(1.2 * u)
                ctx.stroke()

    return [_Layer(0.1, water, water_anim), _Layer(0.3, reef, None, 0.3, 9), _Layer(0.6, mid, mid_anim, 0.3, 9),
            _Layer(1.0, floor, floor_anim, HORIZON["underwater"] - 0.03, 9)]


def _coral(ctx: cairo.Context, s: _S, x: float, gy: float, size: float, col: RGB, r: random.Random,
           lw: float | None = None) -> None:
    lw = (2.0 * s.u) if lw is None else lw

    def branch(px: float, py: float, a: float, ln: float, depth: int) -> None:
        ex, ey = px + math.cos(a) * ln, py + math.sin(a) * ln
        ctx.move_to(px, py)
        ctx.line_to(ex, ey)
        if depth > 0:
            branch(ex, ey, a - r.uniform(0.3, 0.6), ln * 0.7, depth - 1)
            branch(ex, ey, a + r.uniform(0.3, 0.6), ln * 0.7, depth - 1)

    branch(x, gy, -math.pi / 2, size * 0.45, 3)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    if lw > 0:
        path = ctx.copy_path()
        ctx.set_source_rgb(*s.edge(col))
        ctx.set_line_width(size * 0.13 + lw * 2)
        ctx.stroke()
        ctx.append_path(path)
    ctx.set_source_rgb(*col)
    ctx.set_line_width(size * 0.13)
    ctx.stroke()


def _brain_coral(ctx: cairo.Context, s: _S, x: float, gy: float, size: float, col: RGB) -> None:
    ctx.move_to(x - size, gy)
    ctx.curve_to(x - size, gy - size * 1.3, x + size, gy - size * 1.3, x + size, gy)
    ctx.close_path()
    _fill_edge(ctx, _grad(gy - size, gy, (0, lighten(col, 0.2)), (1, mul(col, 0.8))), s.edge(col), 2 * s.u)
    for k in range(3):
        f = 0.3 + 0.25 * k
        ctx.move_to(x - size * (1 - f) * 0.9, gy - size * 0.1)
        ctx.curve_to(x - size * (1 - f) * 0.5, gy - size * (1.1 - f), x + size * (1 - f) * 0.5, gy - size * (1.1 - f),
                     x + size * (1 - f) * 0.9, gy - size * 0.1)
    ctx.set_source_rgba(*mul(col, 0.7), 0.8)
    ctx.set_line_width(2 * s.u)
    ctx.stroke()


def _seaweed(ctx: cairo.Context, s: _S, x: float, gy: float, hgt: float, t: float, ph: float) -> None:
    u = s.u
    col = s.lit("#2fae6a", 0.0, True)
    n = 10
    left, right = [], []
    for i in range(n + 1):
        f = i / n
        sway = 18 * u * f * f * math.sin(t * 1.2 + ph - f * 2.2)
        cx = x + sway
        cy = gy - hgt * f
        wd = 9 * u * (1 - 0.7 * f)
        left.append((cx - wd, cy))
        right.append((cx + wd, cy))
    ctx.move_to(*left[0])
    for p in left[1:]:
        ctx.line_to(*p)
    for p in reversed(right):
        ctx.line_to(*p)
    ctx.close_path()
    _fill_edge(ctx, col, s.edge(col), 1.6 * u)


def _fish(ctx: cairo.Context, s: _S, x: float, y: float, size: float, col: RGB, d: int, t: float) -> None:
    u = s.u
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(d, 1)
    wag = 0.25 * math.sin(t * 8)
    ctx.move_to(-size * 0.8, 0)
    ctx.line_to(-size * 1.35, -size * (0.45 + wag))
    ctx.line_to(-size * 1.35, size * (0.45 - wag))
    ctx.close_path()
    _fill_edge(ctx, mul(col, 0.9), s.edge(col), 1.6 * u)
    ellipse(ctx, 0, 0, size, size * 0.6)
    _fill_edge(ctx, _grad(-size * 0.6, size * 0.6, (0, lighten(col, 0.25)), (1, mul(col, 0.85))), s.edge(col),
               1.8 * u)
    ctx.arc(size * 0.45, -size * 0.12, size * 0.16, 0, 2 * math.pi)
    _fill_edge(ctx, (1, 1, 1), INK, 1.2 * u)
    ctx.arc(size * 0.5, -size * 0.12, size * 0.08, 0, 2 * math.pi)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.restore()


# ======================= sky =======================
def _sky(s: _S) -> list[_Layer]:
    def sky(ctx, s, rg):
        _paint_sky(ctx, s, rg)
        if s.dark:
            _stars_static(ctx, s, rg, 90 if s.night else 30, s.gy)
        _sky_body(ctx, s, s.w * 0.8, s.h * 0.18, 48 * s.u)

    def sky_anim(ctx, s, t, rg):
        if s.dark and not s.overcast:
            _twinkle(ctx, s, t, rg, 20, s.gy * 0.9)
        _birds_anim(5, 0.15, 0.35)(ctx, s, t, rg)

    def far(ctx, s, rg):
        u = s.u
        if s.time in ("day", "sunset") and not s.overcast:
            # радуга
            cx, cy, r0 = s.w * 0.35, s.gy + 40 * u, 330 * u
            for k, col in enumerate(("#ff5a5f", "#ff9f1c", "#ffd23f", "#7cd67c", "#3ec1ff", "#7a6cff", "#c06cff")):
                ctx.arc(cx, cy, r0 - k * 12 * u, math.pi, 2 * math.pi)
                ctx.set_source_rgba(*hx(col), 0.45 if s.time == "day" else 0.3)
                ctx.set_line_width(12 * u)
                ctx.stroke()
        r = s.r("farclouds")
        x0, _, x1, _ = rg
        x = x0
        while x < x1:
            _cloud(ctx, s, x, s.gy - r.uniform(20, 60) * u, r.uniform(90, 140) * u, _cloud_puffs(r, 6), 0.85,
                   lw=0.0)
            x += r.uniform(160, 240) * u

    def mid_anim(ctx, s, t, rg):
        x0, _, x1, _ = rg
        u = s.u
        span = x1 - x0 + 400 * u
        clouds = s.memo.get("midclouds")
        if clouds is None:
            r = s.r("midclouds")
            clouds = []
            for i in range(int(3 * (x1 - x0) / s.w) + 1):
                sz = r.uniform(60, 90) * u
                clouds.append((s.h * r.uniform(0.35, 0.55), r.random() * span, r.uniform(8, 16) * u,
                               _cloud_sprite(s, ("mid", i), sz, _cloud_puffs(r, 5))))
            s.memo["midclouds"] = clouds
        for i, (y, base, sp, (sprite, ox, oy)) in enumerate(clouds):
            x = x0 - 200 * u + (base + t * sp) % span
            _blit(ctx, sprite, x, y + 6 * u * math.sin(t * 0.6 + i), px=ox, py=oy)

    def ground(ctx, s, rg):
        x0, y0, x1, y1 = rg
        u = s.u
        r = s.r("cloudfloor")
        top, bot, edge = (hx(c) for c in CLOUD[s.time])
        if s.night:
            top, bot = mix(top, (0.6, 0.65, 0.9), 0.35), mix(bot, (0.4, 0.45, 0.7), 0.3)
        puffs = []
        x = x0 - 60 * u
        while x < x1 + 60 * u:
            puffs.append((x, s.gy + r.uniform(-6, 14) * u, r.uniform(50, 85) * u))
            x += r.uniform(50, 80) * u

        def path() -> None:
            for px, py, pr in puffs:
                ctx.new_sub_path()
                ctx.arc(px, py + pr * 0.4, pr, 0, 2 * math.pi)
            ctx.rectangle(x0 - 80 * u, s.gy + 40 * u, x1 - x0 + 160 * u, y1 - s.gy)

        fill_union(ctx, path, _grad(s.gy - 60 * u, s.h, (0, top), (0.5, mix(top, bot, 0.4)), (1, bot)), 2 * u, edge)
        for _ in range(int(20 * (x1 - x0) / s.w)):
            px, py = r.uniform(x0, x1), r.uniform(s.gy + 50 * u, y1)
            ellipse(ctx, px, py, r.uniform(30, 70) * u, r.uniform(6, 12) * u)
            ctx.set_source_rgba(*bot, 0.35)
            ctx.fill()

    def ground_anim(ctx, s, t, rg):
        _twinkle(ctx, s, t, (rg[0], int(s.gy), rg[2], rg[3]), 8, s.h * 0.98, "cloudspark", (1, 1, 1))

    return [_Layer(0.1, sky, sky_anim), _Layer(0.3, far, None, 0.1, 9), _Layer(0.6, None, mid_anim),
            _Layer(1.0, ground, ground_anim, HORIZON["sky"] - 0.12, 9)]


PRESETS: dict[str, Callable[[_S], list[_Layer]]] = {
    "park": _park, "city": _city, "forest": _forest, "beach": _beach, "space": _space, "room": _room,
    "classroom": _classroom, "stage": _stage, "party": _party, "winter": _winter, "underwater": _underwater,
    "sky": _sky,
}


def layer_count(bg: BackgroundSpec) -> int:
    """Сколько слоёв у фона (для оценки стоимости кадра)."""
    return len(PRESETS.get(bg.preset, _park)(_S(bg, 16, 16, 0)))


def clamp_unit(v: float) -> float:
    return clamp(v)
