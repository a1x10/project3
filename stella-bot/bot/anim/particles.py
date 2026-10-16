"""Эффекты-частицы мультика (catalog.EFFECTS): конфетти, снег, дождь, сердечки, звёзды, искры, огонь, дым, «пуф»,
салют, шарики, пузыри, листья, монетки, ноты и вспышка.

Частицы без состояния: положение каждой — чистая функция (seed эффекта, номер частицы, t − t0) — баллистика с
аналитическим сопротивлением воздуха x(τ) = x0 + v0·(1 − e^(−kτ))/k + g·(τ − (1 − e^(−kτ))/k)/k. Поэтому кадр можно
рисовать в любом порядке. Параметры частиц считаются один раз на эффект (кеш). Одинаковые по цвету частицы
заливаются одним путём — так 300 частиц стоят ≈ 2–4 мс.

Видимых частиц в кадре не больше catalog.MAX_PARTICLES (300): draw_effect рисует не больше budget и возвращает,
сколько нарисовал; draw_effects делит лимит между всеми эффектами кадра.
"""

from __future__ import annotations

import functools
import math
import random
from dataclasses import dataclass
from typing import Callable, Iterable

import cairocffi as cairo

from . import catalog
from .camera import Cam, apply_cam, layer_margin, view_rect
from .draw import ellipse, heart, sparkle, star
from .ease import clamp, ease, ease_out_back, noise1, rng, smoothstep
from .model import RGB, PlannedEffect
from .palette import INK, hx, lighten, mix, mul

AMOUNT_K = {"few": 0.5, "normal": 1.0, "lots": 1.8}
BASE_COUNT: dict[str, int] = {
    "confetti": 110, "snow": 130, "rain": 150, "hearts": 22, "stars": 16, "sparkles": 26, "fire": 34, "smoke": 12,
    "poof": 16, "fireworks": 4, "balloons": 10, "bubbles": 26, "leaves": 26, "coins": 26, "music": 12, "flash": 0,
}
SPARKS = 34  # искр в одном залпе салюта
CONFETTI_COLORS = tuple(hx(c) for c in ("#ff3d6e", "#ffd23f", "#3ec1ff", "#7cff6b", "#b48cff", "#ffffff", "#ff9f1c"))
BRIGHT = tuple(hx(c) for c in ("#ff3d6e", "#ffd23f", "#3ec1ff", "#7cff6b", "#c58cff", "#ff9f1c", "#ffffff"))
PARALLAX: dict[str, float] = {"fireworks": 0.5}  # остальное — 1.0 (у актёров) или 1.15 (передний план)
AMBIENT = frozenset({"snow", "rain", "leaves", "bubbles"})  # «погода»: экран сразу заполнен


@dataclass
class _E:
    """Всё про эффект в этот кадр."""

    kind: str
    seed: int
    t0: float
    t1: float
    tau: float  # секунды от начала эффекта
    w: int
    h: int
    u: float
    ex: float | None  # точка эффекта в пикселях (None — по всему кадру)
    ey: float | None
    n: int  # сколько частиц у эффекта
    alpha: float  # общая прозрачность (появление/исчезание)
    cam: Cam

    @property
    def dur(self) -> float:
        return max(0.05, self.t1 - self.t0)


def particle_count(eff: PlannedEffect, w: int = 720, h: int = 720) -> int:
    """Сколько частиц у эффекта (для лимита кадра и оценки стоимости)."""
    if eff.kind not in BASE_COUNT:
        return 0
    k = AMOUNT_K.get(eff.amount, 1.0)
    n = BASE_COUNT[eff.kind]
    if eff.kind == "fireworks":
        return int(round(max(1, n * k))) * SPARKS
    return min(catalog.MAX_PARTICLES, int(round(n * k)))


def active(eff: PlannedEffect, t: float) -> bool:
    return eff.kind in BASE_COUNT and eff.t0 <= t <= eff.t1 and math.isfinite(t)


def draw_effects(ctx: cairo.Context, effects: Iterable[PlannedEffect], t: float, w: int, h: int, cam: Cam,
                 budget: int = catalog.MAX_PARTICLES) -> int:
    """Все эффекты кадра с общим лимитом частиц: если вместе их больше budget, каждый получает долю."""
    live = [e for e in effects if active(e, t)]
    want = [particle_count(e, w, h) for e in live]
    total = sum(want)
    k = 1.0 if total <= budget else budget / total
    drawn = 0
    for e, n in zip(live, want, strict=True):
        share = int(n * k)
        drawn += draw_effect(ctx, e, t, w, h, cam, budget=max(0, min(share, budget - drawn)))
    return drawn


def draw_effect(ctx: cairo.Context, eff: PlannedEffect, t: float, w: int, h: int, cam: Cam,
                budget: int = catalog.MAX_PARTICLES) -> int:
    """Эффект eff в момент t (секунды ролика) на кадре w×h; камеру (параллакс) применяет сам — ctx без камеры.
    Рисует не больше budget частиц (и не больше MAX_PARTICLES); возвращает, сколько нарисовал. flash — белая
    вспышка на весь кадр (частицей не считается)."""
    if not active(eff, t):
        return 0
    kind = eff.kind
    tau = t - eff.t0
    u = min(w, h) / 720.0
    budget = max(0, min(int(budget), catalog.MAX_PARTICLES))
    n = min(particle_count(eff, w, h), budget)
    fade_out = smoothstep(clamp((eff.t1 - t) / 0.45)) if eff.t1 - eff.t0 > 0.9 else 1.0
    fade_in = 1.0 if kind not in AMBIENT else smoothstep(clamp(tau / 0.25))
    ex = None if eff.x is None or not math.isfinite(eff.x) else clamp(eff.x, -0.2, 1.2) * w
    ey = None if eff.y is None or not math.isfinite(eff.y) else clamp(eff.y, -0.2, 1.2) * h
    e = _E(kind, int(eff.seed), eff.t0, eff.t1, tau, w, h, u, ex, ey, n, fade_out * fade_in, cam)
    ctx.save()
    ctx.new_path()
    try:
        drawn = KINDS[kind](ctx, e)
    finally:
        ctx.restore()
        ctx.new_path()
    return min(drawn, budget)


# ======================= общее =======================
def _cam(ctx: cairo.Context, e: _E, p: float) -> None:
    ctx.identity_matrix()
    apply_cam(ctx, e.cam, e.w, e.h, p)


def _span(e: _E, p: float) -> tuple[float, float, float, float]:
    """Мировая область слоя с параллаксом p, где живут частицы «по всему кадру» (с полями под камеру)."""
    mx, my = layer_margin(e.w, e.h, p)
    return -mx, -my, e.w + mx, e.h + my


def _visible(e: _E, p: float, pad: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = view_rect(e.cam, e.w, e.h, p)
    return x0 - pad, y0 - pad, x1 + pad, y1 + pad


@functools.lru_cache(maxsize=64)
def _params(kind: str, seed: int, n: int, salt: int = 0) -> tuple[tuple[float, ...], ...]:
    """n наборов из 8 случайных чисел 0..1 на частицу — один раз на эффект (детерминированно от seed)."""
    r: random.Random = rng(seed, "particles", kind, salt)
    return tuple(tuple(r.random() for _ in range(8)) for _ in range(n))


def _drag(v0: float, g: float, k: float, tau: float) -> float:
    """Смещение за τ при начальной скорости v0, ускорении g и сопротивлении k (аналитически)."""
    e = (1.0 - math.exp(-k * tau)) / k
    return v0 * e + g * (tau - e) / k


def _quad(ctx: cairo.Context, x: float, y: float, hw: float, hh: float, rot: float, sx: float) -> None:
    """Прямоугольник (полуразмеры hw×hh), сжатый по x на sx и повёрнутый на rot, — в текущий путь."""
    c, s = math.cos(rot), math.sin(rot)
    ax, ay = hw * sx * c, hw * sx * s
    bx, by = -hh * s, hh * c
    ctx.move_to(x - ax - bx, y - ay - by)
    ctx.line_to(x + ax - bx, y + ay - by)
    ctx.line_to(x + ax + bx, y + ay + by)
    ctx.line_to(x - ax + bx, y - ay + by)
    ctx.close_path()


def _ink_fill(ctx: cairo.Context, fill: RGB, alpha: float, lw: float, ink: RGB = INK) -> None:
    ctx.set_source_rgba(*fill, alpha)
    if lw > 0:
        ctx.fill_preserve()
        ctx.set_source_rgba(*ink, alpha)
        ctx.set_line_width(lw)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()
    else:
        ctx.fill()


def _life(age: float, life: float, fade_in: float = 0.12, fade_out: float = 0.3) -> float:
    """Прозрачность частицы по её возрасту: быстро появляется, к концу жизни тает."""
    if age < 0 or age > life:
        return 0.0
    a = smoothstep(clamp(age / max(1e-3, fade_in)))
    return a * smoothstep(clamp((life - age) / max(1e-3, life * fade_out)))


# ======================= конфетти =======================
def _confetti(ctx: cairo.Context, e: _E) -> int:
    """Бумажки переворачиваются в 3D (ширина — |cos|, яркость — за переворотом) и звёздочки. Без точки — две
    хлопушки из нижних углов и мягкий дождь сверху; с точкой — залп вверх из неё."""
    u = e.u
    ps = _params("confetti", e.seed, e.n)
    p = 1.0 if e.ex is not None else 1.15
    _cam(ctx, e, p)
    x0v, y0v, x1v, y1v = _visible(e, p, 30 * u)
    sx0, _, sx1, _ = _span(e, p)
    buckets: dict[tuple[int, int, bool], list[tuple[float, float, float, float, float]]] = {}
    drawn = 0
    g, k = 330.0 * u, 2.6  # падают медленно, как бумага (предельная скорость g/k ≈ 130 пикс/с)
    for i, q in enumerate(ps):
        if e.ex is not None or i % 2 == 0:  # залп
            if e.ex is not None:
                ox, oy = e.ex, (e.ey if e.ey is not None else e.h * 0.45)
                a = -math.pi / 2 + (q[0] - 0.5) * 2.4
                sp = (420 + 520 * q[1]) * u
            else:
                left = (i // 2) % 2 == 0
                ox, oy = (e.w * (0.02 if left else 0.98), e.h * 1.02)
                a = -math.pi / 2 + (0.35 + 0.35 * q[0]) * (1 if left else -1)
                sp = (1150 + 900 * q[1]) * u
            age = e.tau - q[7] * 0.12
            if age < 0:
                continue
            x = ox + _drag(math.cos(a) * sp, 0.0, k, age) + 26 * u * math.sin(age * (2 + 2 * q[2]) + q[3] * 6) * \
                min(1.0, age)
            y = oy + _drag(math.sin(a) * sp, g, k, age)
            alpha = smoothstep(clamp((4.2 - age) / 0.8))
        else:  # дождь сверху
            life = 6.0
            start = q[7] * max(0.1, e.dur - 1.0)
            age = e.tau - start
            if age < 0:
                continue
            x = sx0 + (sx1 - sx0) * q[0] + 30 * u * math.sin(age * (1.5 + q[2]) + q[3] * 6)
            y = -40 * u + (90 + 70 * q[1]) * u * age
            alpha = 1.0 if age < life else 0.0
        if alpha <= 0.02 or not (x0v < x < x1v and y0v < y < y1v):
            continue
        spin = age * (5 + 7 * q[4]) + q[5] * 6.3
        flip = math.cos(spin)
        shade = min(2, int(abs(flip) * 3))
        ci = int(q[6] * len(CONFETTI_COLORS)) % len(CONFETTI_COLORS)
        is_star = q[5] > 0.82
        buckets.setdefault((ci, shade, is_star), []).append((x, y, q[3] * 6.3 + age * (1 + 2 * q[2]), flip, alpha))
        drawn += 1
    for (ci, shade, is_star), items in buckets.items():
        col = mul(CONFETTI_COLORS[ci], 0.62 + 0.19 * shade)
        alpha = max(it[4] for it in items) * e.alpha
        for x, y, rot, flip, _a in items:
            if is_star:
                ctx.save()
                ctx.translate(x, y)
                ctx.scale(max(0.15, abs(flip)), 1.0)
                star(ctx, 0, 0, 9 * u, 5, 0.45, rot)
                ctx.restore()
            else:
                _quad(ctx, x, y, 6.5 * u, 10 * u, rot, max(0.08, abs(flip)))
        ctx.set_source_rgba(*col, alpha)
        ctx.fill()
    return drawn


# ======================= снег и дождь =======================
def _snow(ctx: cairo.Context, e: _E) -> int:
    """Снег в два слоя глубины: дальний мелкий и медленный (параллакс 0.6), ближний крупный (1.15)."""
    u = e.u
    ps = _params("snow", e.seed, e.n)
    drawn = 0
    for layer, (p, rmin, rmax, vmin, vmax, a) in enumerate(((0.6, 1.6, 3.0, 35, 60, 0.75), (1.15, 4.0, 7.5, 70, 120, 0.95))):
        _cam(ctx, e, p)
        x0, y0, x1, y1 = _span(e, p)
        vx0, vy0, vx1, vy1 = _visible(e, p, 10 * u)
        hspan = y1 - y0 + 20 * u
        for i, q in enumerate(ps):
            if (i % 5 < 3) != (layer == 0):
                continue
            v = (vmin + (vmax - vmin) * q[1]) * u
            y = y0 - 10 * u + (q[2] * hspan + v * (e.tau + 50.0)) % hspan
            x = x0 + (x1 - x0) * q[0] + 24 * u * math.sin(e.tau * (0.6 + 0.8 * q[3]) + q[4] * 6.3) \
                + 10 * u * noise1(e.tau * 0.4 + i, e.seed)
            if not (vx0 < x < vx1 and vy0 < y < vy1):
                continue
            ctx.new_sub_path()
            ctx.arc(x, y, (rmin + (rmax - rmin) * q[5]) * u, 0, 2 * math.pi)
            drawn += 1
        ctx.set_source_rgba(1, 1, 1, a * e.alpha)
        ctx.fill()
    return drawn


def _rain(ctx: cairo.Context, e: _E) -> int:
    """Косые струи (ближние толще) и кольца брызг там, где капля упала на землю."""
    u = e.u
    ps = _params("rain", e.seed, e.n)
    drawn = 0
    wind = -0.18
    rings: list[tuple[float, float, float]] = []
    for layer, (p, vmin, vmax, ln, lw, a) in enumerate(((0.6, 700, 900, 22, 1.4, 0.35), (1.15, 1000, 1300, 38, 2.2, 0.5))):
        _cam(ctx, e, p)
        x0, y0, x1, y1 = _span(e, p)
        vx0, vy0, vx1, vy1 = _visible(e, p, 40 * u)
        for i, q in enumerate(ps):
            if (i % 2 == 0) != (layer == 0):
                continue
            v = (vmin + (vmax - vmin) * q[1]) * u
            hit = e.h * (0.86 + 0.13 * q[3]) if layer == 1 else e.h * (0.8 + 0.08 * q[3])
            top = y0 - 60 * u
            fall = (hit - top) / v
            cyc = fall + 0.3
            age = (e.tau + q[2] * cyc * 7.0) % cyc
            xb = x0 + (x1 - x0) * q[0]
            if age < fall:
                y = top + v * age
                x = xb + wind * (y - top)
                if not (vx0 < x < vx1 and vy0 < y < vy1):
                    continue
                ctx.move_to(x, y)
                ctx.line_to(x - wind * ln * u * 0.9, y - ln * u)
                drawn += 1
            elif layer == 1:
                x = xb + wind * (hit - top)
                if vx0 < x < vx1:
                    rings.append((x, hit, (age - fall) / 0.3))
                    drawn += 1
        ctx.set_source_rgba(0.82, 0.9, 1.0, a * e.alpha)
        ctx.set_line_width(lw * u)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
    if rings:
        _cam(ctx, e, 1.0)
        for x, y, k in rings:
            ellipse(ctx, x, y, (3 + 14 * k) * u, (1 + 4 * k) * u)
            ctx.set_source_rgba(0.85, 0.92, 1.0, 0.7 * (1 - k) * e.alpha)
            ctx.set_line_width(1.6 * u)
            ctx.stroke()
    return drawn


# ======================= сердечки, звёзды, искры =======================
def _source(e: _E, default_y: float) -> tuple[float, float, bool]:
    if e.ex is not None:
        return e.ex, (e.ey if e.ey is not None else e.h * default_y), True
    return e.w * 0.5, (e.ey if e.ey is not None else e.h * default_y), False


def _stream(e: _E, q: tuple[float, ...], life: float) -> float:
    """Возраст частицы непрерывного потока: рождаются равномерно по всей длительности эффекта."""
    span = max(0.2, e.dur - life * 0.6)
    return e.tau - q[7] * span


def _hearts(ctx: cairo.Context, e: _E) -> int:
    u = e.u
    ps = _params("hearts", e.seed, e.n)
    _cam(ctx, e, 1.0)
    sx, sy, point = _source(e, 0.62)
    cols = (hx("#ff4d7e"), hx("#ff8fb1"), hx("#e8243a"))
    groups: dict[int, list] = {}
    drawn = 0
    for q in ps:
        life = 1.6 + 0.8 * q[6]
        age = _stream(e, q, life)
        a = _life(age, life)
        if a <= 0.02:
            continue
        x0 = sx + (q[0] - 0.5) * (90 * u if point else e.w * 0.9)
        y0 = sy if point else e.h * (0.75 + 0.2 * q[1])
        x = x0 + 22 * u * math.sin(age * (2 + q[2]) + q[3] * 6)
        y = y0 - (110 + 120 * q[1]) * u * age
        s = (17 + 13 * q[4]) * u * ease_out_back(clamp(age / 0.25))
        groups.setdefault(int(q[5] * 3) % 3, []).append((x, y, s, a, 0.2 * math.sin(age * 3 + q[3] * 6)))
        drawn += 1
    for ci, items in groups.items():
        alpha = e.alpha * max(it[3] for it in items)
        for x, y, s, _a, rot in items:
            ctx.save()
            ctx.translate(x, y)
            ctx.rotate(rot)
            heart(ctx, 0, 0, s)
            ctx.restore()
        _ink_fill(ctx, cols[ci], alpha, 2.6 * u)
        for x, y, s, _a, rot in items:
            ctx.new_sub_path()
            ctx.arc(x - s * 0.42, y - s * 0.52, s * 0.15, 0, 2 * math.pi)
        ctx.set_source_rgba(1, 1, 1, 0.75 * alpha)
        ctx.fill()
    return drawn


def _stars(ctx: cairo.Context, e: _E) -> int:
    """Золотые звёздочки вспыхивают вокруг точки (или по верху кадра), вертятся и гаснут."""
    u = e.u
    ps = _params("stars", e.seed, e.n)
    _cam(ctx, e, 1.0)
    sx, sy, point = _source(e, 0.4)
    items = []
    for q in ps:
        life = 0.9 + 0.6 * q[6]
        span = max(0.3, e.dur - life * 0.5)
        age = (e.tau - q[7] * span)
        if age < 0 or age > life:
            continue
        k = math.sin(math.pi * clamp(age / life)) ** 0.7
        if point:
            a = q[0] * 2 * math.pi
            rr = (60 + 140 * q[1]) * u
            x, y = sx + math.cos(a) * rr, sy + math.sin(a) * rr * 0.7 - 30 * u * age
        else:
            x, y = e.w * (0.06 + 0.88 * q[0]), e.h * (0.08 + 0.6 * q[1])
        items.append((x, y, (15 + 13 * q[4]) * u * k, age * 2.5 + q[5] * 6, k))
    gold = hx("#ffd23f")
    for x, y, r, rot, _k in items:
        star(ctx, x, y, r, 5, 0.45, rot)
    if items:
        _ink_fill(ctx, gold, e.alpha, 2.6 * u)
        for x, y, r, rot, _k in items:
            ctx.new_sub_path()
            ctx.arc(x - r * 0.2, y - r * 0.25, r * 0.16, 0, 2 * math.pi)
        ctx.set_source_rgba(1, 1, 1, 0.8 * e.alpha)
        ctx.fill()
    return len(items)


def _sparkles(ctx: cairo.Context, e: _E) -> int:
    """Четырёхлучевые искорки: пульсируют, вокруг точки или по кадру; белые, жёлтые и голубые."""
    u = e.u
    ps = _params("sparkles", e.seed, e.n)
    _cam(ctx, e, 1.0)
    sx, sy, point = _source(e, 0.45)
    cols = ((1.0, 1.0, 1.0), (1.0, 0.92, 0.5), (0.6, 0.95, 1.0))
    groups: dict[int, list] = {}
    for q in ps:
        life = 0.6 + 0.5 * q[6]
        cyc = life + 0.3 * q[5]
        age = (e.tau + q[7] * cyc) % cyc
        if age > life:
            continue
        k = math.sin(math.pi * age / life)
        if point:
            a = q[0] * 2 * math.pi
            rr = (30 + 120 * q[1]) * u
            x, y = sx + math.cos(a) * rr, sy + math.sin(a) * rr * 0.8
        else:
            x, y = e.w * (0.05 + 0.9 * q[0]), e.h * (0.05 + 0.75 * q[1])
        groups.setdefault(int(q[4] * 3) % 3, []).append((x, y, (10 + 18 * q[3]) * u * k))
    drawn = 0
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for ci, items in groups.items():
        for x, y, r in items:
            ctx.new_sub_path()
            ctx.arc(x, y, r * 0.9, 0, 2 * math.pi)
        ctx.set_source_rgba(*cols[ci], 0.18 * e.alpha)
        ctx.fill()
    ctx.restore()
    for ci, items in groups.items():
        for x, y, r in items:
            ctx.new_sub_path()
            sparkle(ctx, x, y, r)
            drawn += 1
        ctx.set_source_rgba(*cols[ci], 0.95 * e.alpha)
        ctx.fill()
    return drawn


# ======================= огонь, дым, пуф =======================
def _fire(ctx: cairo.Context, e: _E) -> int:
    """Языки пламени (капли, аддитивно, мерцают по шуму) и искры-угольки над ними."""
    u = e.u
    ps = _params("fire", e.seed, e.n)
    _cam(ctx, e, 1.0)
    sx = e.ex if e.ex is not None else e.w * 0.5
    sy = e.ey if e.ey is not None else e.h * 0.93
    grow = smoothstep(clamp(e.tau / 0.3)) * e.alpha
    if grow <= 0.01:
        return 0
    wbase = 70 * u
    # свечение у основания
    g = cairo.RadialGradient(sx, sy - 20 * u, 0, sx, sy - 20 * u, 150 * u)
    g.add_color_stop_rgba(0, 1.0, 0.6, 0.2, 0.45 * grow)
    g.add_color_stop_rgba(1, 1.0, 0.4, 0.1, 0)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.set_source(g)
    ctx.arc(sx, sy - 20 * u, 150 * u, 0, 2 * math.pi)
    ctx.fill()
    layers: list[list[tuple[float, float, float, float]]] = [[], [], []]
    drawn = 0
    n_flames = int(len(ps) * 0.7)
    for i, q in enumerate(ps[:n_flames]):
        life = 0.55 + 0.35 * q[6]
        age = (e.tau + q[7] * life) % life
        f = age / life
        x = sx + (q[0] - 0.5) * wbase * (1.0 - 0.6 * f) + 10 * u * noise1(e.tau * 3 + i, e.seed)
        y = sy - (10 + 150 * q[1]) * u * f - 6 * u
        s = (26 + 18 * q[2]) * u * (1.0 - 0.75 * f) * grow
        layers[min(2, int(f * 3))].append((x, y, s, 0.15 * noise1(e.tau * 4 + i * 1.3, e.seed + 7)))
        drawn += 1
    cols = ((1.0, 0.95, 0.55), (1.0, 0.62, 0.18), (0.95, 0.25, 0.12))
    for li in (2, 1, 0):
        for x, y, s, lean in layers[li]:
            ctx.move_to(x + lean * s, y - s * 1.6)
            ctx.curve_to(x + s * 0.7, y - s * 0.5, x + s * 0.8, y + s * 0.6, x, y + s * 0.7)
            ctx.curve_to(x - s * 0.8, y + s * 0.6, x - s * 0.7, y - s * 0.5, x + lean * s, y - s * 1.6)
            ctx.close_path()
        ctx.set_source_rgba(*cols[li], 0.55 * grow)
        ctx.fill()
    # угольки
    for i, q in enumerate(ps[n_flames:]):
        life = 1.0 + 0.6 * q[6]
        age = (e.tau + q[7] * life) % life
        x = sx + (q[0] - 0.5) * wbase + 30 * u * math.sin(age * 4 + q[3] * 6)
        y = sy - 40 * u - (140 + 120 * q[1]) * u * age
        ctx.new_sub_path()
        ctx.arc(x, y, (1.5 + 1.5 * q[2]) * u, 0, 2 * math.pi)
        drawn += 1
    ctx.set_source_rgba(1.0, 0.75, 0.3, 0.9 * grow)
    ctx.fill()
    ctx.restore()
    return drawn


def _puffs(ctx: cairo.Context, e: _E, puffs: list[tuple[float, float, float]], alpha: float, fill: RGB,
           edge: RGB) -> None:
    """Клубы с общим контуром (объединение) и общей прозрачностью — через группу в рамке клубов."""
    if not puffs or alpha <= 0.01:
        return
    x0 = min(x - r for x, y, r in puffs) - 6 * e.u
    y0 = min(y - r for x, y, r in puffs) - 6 * e.u
    x1 = max(x + r for x, y, r in puffs) + 6 * e.u
    y1 = max(y + r for x, y, r in puffs) + 6 * e.u
    ctx.save()
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
    ctx.clip()
    ctx.push_group()

    def path() -> None:
        for x, y, r in puffs:
            ctx.new_sub_path()
            ctx.arc(x, y, r, 0, 2 * math.pi)

    path()
    ctx.set_source_rgb(*edge)
    ctx.set_line_width(4.0 * e.u)
    ctx.stroke()
    path()
    g = cairo.LinearGradient(0, y0, 0, y1)
    g.add_color_stop_rgb(0, *lighten(fill, 0.3))
    g.add_color_stop_rgb(1, *mul(fill, 0.85))
    ctx.set_source(g)
    ctx.fill()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(alpha)
    ctx.restore()


def _smoke(ctx: cairo.Context, e: _E) -> int:
    u = e.u
    ps = _params("smoke", e.seed, e.n)
    _cam(ctx, e, 1.0)
    sx = e.ex if e.ex is not None else e.w * 0.5
    sy = e.ey if e.ey is not None else e.h * 0.85
    buckets: list[list[tuple[float, float, float]]] = [[], [], []]
    for i, q in enumerate(ps):
        life = 2.0 + 0.8 * q[6]
        age = (e.tau + q[7] * life) % life if e.tau > q[7] * life * 0.3 else -1
        if age < 0:
            continue
        f = age / life
        x = sx + (q[0] - 0.5) * 40 * u + 60 * u * f * (q[2] - 0.3) + 12 * u * math.sin(age * 1.5 + i)
        y = sy - (60 + 180 * q[1]) * u * f
        r = (24 + 20 * q[3]) * u * (0.55 + 1.3 * f)
        buckets[min(2, int(f * 3))].append((x, y, r))
    for b, puffs in enumerate(buckets):
        _puffs(ctx, e, puffs, (0.92 - 0.3 * b) * e.alpha, hx("#cfcbdd"), hx("#7f7a98"))
    return sum(len(b) for b in buckets)


def _poof(ctx: cairo.Context, e: _E) -> int:
    """«Пуф»: белые клубы разлетаются из точки и тают, в центре вспыхивает звезда, искорки разлетаются."""
    u = e.u
    ps = _params("poof", e.seed, e.n)
    _cam(ctx, e, 1.0)
    sx = e.ex if e.ex is not None else e.w * 0.5
    sy = e.ey if e.ey is not None else e.h * 0.62
    dur = min(0.9, e.dur)
    f = clamp(e.tau / dur)
    puffs = []
    n_puff = int(len(ps) * 0.6)
    for q in ps[:n_puff]:
        a = q[0] * 2 * math.pi
        dist = (50 + 90 * q[1]) * u * ease("out", f)
        r = (30 + 22 * q[2]) * u * (0.6 + 0.8 * math.sin(math.pi * min(1.0, f * 1.1 + 0.05)))
        puffs.append((sx + math.cos(a) * dist, sy + math.sin(a) * dist * 0.75 - 20 * u * f, max(0.0, r)))
    _puffs(ctx, e, puffs, e.alpha * (1.0 - smoothstep(clamp((f - 0.45) / 0.55))), hx("#ffffff"), hx("#9a95b5"))
    k = math.sin(math.pi * clamp(f / 0.5))
    if k > 0.01:
        star(ctx, sx, sy, 34 * u * k, 4, 0.3, f * 2)
        _ink_fill(ctx, hx("#fff3a0"), e.alpha, 2.0 * u)
    for q in ps[n_puff:]:
        a = q[0] * 2 * math.pi
        dist = (60 + 110 * q[1]) * u * ease("out", f)
        ctx.new_sub_path()
        sparkle(ctx, sx + math.cos(a) * dist, sy + math.sin(a) * dist, (5 + 6 * q[2]) * u * (1 - f))
    ctx.set_source_rgba(1, 0.95, 0.6, e.alpha)
    ctx.fill()
    return len(ps)


# ======================= салют =======================
def _fireworks(ctx: cairo.Context, e: _E) -> int:
    """Ракеты взлетают с хвостом и раскрываются шаром искр с затухающими следами и вспышкой (аддитивно)."""
    u = e.u
    n_rockets = max(1, e.n // SPARKS) if e.n >= SPARKS else 1
    sparks = max(4, min(SPARKS, e.n // n_rockets)) if e.n else 0
    if sparks == 0:
        return 0
    rockets = _params("fireworks", e.seed, n_rockets)
    _cam(ctx, e, PARALLAX["fireworks"])
    ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    drawn = 0
    span = max(0.5, e.dur - 1.6)
    for ri, q in enumerate(rockets):
        launch = (ri / max(1, n_rockets)) * span + q[7] * 0.3
        age = e.tau - launch
        if age < 0:
            continue
        if e.ex is not None:
            bx = e.ex + (q[0] - 0.5) * e.w * 0.3
        else:
            bx = e.w * (0.15 + 0.7 * q[0])
        by = e.h * (0.12 + 0.25 * q[1]) if e.ey is None else e.ey
        col = BRIGHT[int(q[2] * len(BRIGHT)) % len(BRIGHT)]
        rise = 0.7
        if age < rise:  # ракета летит вверх
            f = ease("out", age / rise)
            y = e.h * 1.02 + (by - e.h * 1.02) * f
            x = bx + 8 * u * math.sin(age * 20)
            ctx.move_to(x, y)
            ctx.line_to(x, y + 40 * u * (1 - f) + 6 * u)
            ctx.set_source_rgba(1.0, 0.9, 0.6, 0.8 * e.alpha)
            ctx.set_line_width(3 * u)
            ctx.stroke()
            drawn += 1
            continue
        b = age - rise
        if b > 1.8:
            continue
        if b < 0.18:  # вспышка
            g = cairo.RadialGradient(bx, by, 0, bx, by, 120 * u)
            g.add_color_stop_rgba(0, *mix(col, (1, 1, 1), 0.6), 0.6 * (1 - b / 0.18) * e.alpha)
            g.add_color_stop_rgba(1, *col, 0)
            ctx.set_source(g)
            ctx.arc(bx, by, 120 * u, 0, 2 * math.pi)
            ctx.fill()
        fade = 1.0 - smoothstep(clamp((b - 0.9) / 0.9))
        crackle = 0.6 + 0.4 * math.sin(b * 40 + ri) if b > 1.0 else 1.0
        sp_ps = _params("spark", e.seed, sparks, ri)
        speed = (260 + 160 * q[3]) * u
        k, g_ = 2.4, 160.0 * u
        for j, s in enumerate(sp_ps):
            a = (j + 0.3 * s[0]) / sparks * 2 * math.pi
            v = speed * (0.75 + 0.25 * s[1])
            pts = []
            for dt in (0.0, 0.07, 0.14):
                tt = max(0.0, b - dt)
                pts.append((bx + _drag(math.cos(a) * v, 0.0, k, tt), by + _drag(math.sin(a) * v, g_, k, tt)))
            ctx.move_to(*pts[2])
            ctx.line_to(*pts[1])
            ctx.line_to(*pts[0])
            drawn += 1
        ctx.set_source_rgba(*col, 0.9 * fade * crackle * e.alpha)
        ctx.set_line_width(3.2 * u)
        ctx.stroke()
        for j, s in enumerate(sp_ps):
            if j % 3:
                continue
            a = (j + 0.3 * s[0]) / sparks * 2 * math.pi
            v = speed * (0.75 + 0.25 * s[1])
            ctx.new_sub_path()
            ctx.arc(bx + _drag(math.cos(a) * v, 0.0, k, b), by + _drag(math.sin(a) * v, g_, k, b), 2.6 * u, 0,
                    2 * math.pi)
        ctx.set_source_rgba(1, 1, 1, 0.8 * fade * crackle * e.alpha)
        ctx.fill()
    return drawn


# ======================= шарики, пузыри, листья, монетки, ноты =======================
def _balloons(ctx: cairo.Context, e: _E) -> int:
    u = e.u
    ps = _params("balloons", e.seed, e.n)
    p = 1.0 if e.ex is not None else 1.15
    _cam(ctx, e, p)
    groups: dict[int, list] = {}
    strings = []
    for i, q in enumerate(ps):
        life = 3.2 + 1.2 * q[6]
        start = q[7] * max(0.1, min(e.dur * 0.55, e.dur - 1.5))
        age = e.tau - start
        if age < 0 or age > life:
            continue
        if e.ex is not None:
            x0 = e.ex + (q[0] - 0.5) * 160 * u
        else:
            x0 = e.w * (0.04 + 0.92 * q[0])
        y = e.h * 1.15 - (e.h * 1.4 / life) * age * (0.8 + 0.3 * q[1])
        x = x0 + 26 * u * math.sin(age * (1.0 + 0.6 * q[2]) + q[3] * 6)
        r = (30 + 14 * q[4]) * u
        groups.setdefault(int(q[5] * len(CONFETTI_COLORS[:5])) % 5, []).append((x, y, r))
        strings.append((x, y + r * 1.12, age, i))
    for x, y, age, i in strings:
        ctx.move_to(x, y)
        ctx.curve_to(x + 8 * u * math.sin(age * 3 + i), y + 30 * u, x - 8 * u * math.sin(age * 2 + i), y + 60 * u,
                     x + 4 * u * math.sin(age * 2.5), y + 90 * u)
    ctx.set_source_rgba(*INK, 0.6 * e.alpha)
    ctx.set_line_width(1.4 * u)
    ctx.stroke()
    for ci, items in groups.items():
        col = CONFETTI_COLORS[ci]
        for x, y, r in items:
            ellipse(ctx, x, y, r * 0.86, r)
            ctx.move_to(x - r * 0.14, y + r * 1.12)
            ctx.line_to(x + r * 0.14, y + r * 1.12)
            ctx.line_to(x, y + r * 0.95)
            ctx.close_path()
        _ink_fill(ctx, col, e.alpha, 2.2 * u)
        for x, y, r in items:
            ctx.new_sub_path()
            ellipse(ctx, x - r * 0.33, y - r * 0.4, r * 0.13, r * 0.24, -0.5)
        ctx.set_source_rgba(1, 1, 1, 0.7 * e.alpha)
        ctx.fill()
    return len(strings)


def _bubbles(ctx: cairo.Context, e: _E) -> int:
    u = e.u
    ps = _params("bubbles", e.seed, e.n)
    p = 1.0 if e.ex is not None else 1.15
    _cam(ctx, e, p)
    items = []
    pops = []
    for i, q in enumerate(ps):
        life = 2.2 + 1.6 * q[6]
        cyc = life + 0.15
        age = (e.tau + q[7] * cyc * 3) % cyc
        if e.ex is not None:
            x0, y0 = e.ex + (q[0] - 0.5) * 80 * u, (e.ey if e.ey is not None else e.h * 0.8)
        else:
            x0, y0 = e.w * (0.03 + 0.94 * q[0]), e.h * (1.05 - 0.2 * q[1])
        r = (10 + 18 * q[2]) * u
        if age > life:  # лопнул
            yy = y0 - (90 + 70 * q[3]) * u * life
            pops.append((x0 + 18 * u * math.sin(life * 2 + i), yy, r, (age - life) / 0.15))
            continue
        x = x0 + 18 * u * math.sin(age * 2 + i) + 6 * u * math.sin(age * 5.3 + i)
        y = y0 - (90 + 70 * q[3]) * u * age
        wob = 1.0 + 0.06 * math.sin(age * 9 + i)
        items.append((x, y, r * wob, r / wob))
    for x, y, rx, ry in items:
        ellipse(ctx, x, y, rx, ry)
    ctx.set_source_rgba(0.75, 0.95, 1.0, 0.2 * e.alpha)
    ctx.fill()
    for x, y, rx, ry in items:
        ellipse(ctx, x, y, rx, ry)
    ctx.set_source_rgba(1, 1, 1, 0.85 * e.alpha)
    ctx.set_line_width(1.6 * u)
    ctx.stroke()
    for x, y, rx, ry in items:
        ctx.new_sub_path()
        ctx.arc(x, y, rx * 0.7, math.pi * 1.1, math.pi * 1.45)
    ctx.set_line_width(2.2 * u)
    ctx.stroke()
    for x, y, r, k in pops:
        for j in range(6):
            a = j * math.pi / 3
            ctx.move_to(x + math.cos(a) * r * (0.6 + 0.6 * k), y + math.sin(a) * r * (0.6 + 0.6 * k))
            ctx.line_to(x + math.cos(a) * r * (0.9 + 0.8 * k), y + math.sin(a) * r * (0.9 + 0.8 * k))
    if pops:
        ctx.set_source_rgba(1, 1, 1, 0.8 * e.alpha)
        ctx.set_line_width(1.6 * u)
        ctx.stroke()
    return len(items) + len(pops)


def _leaf_path(ctx: cairo.Context, x: float, y: float, s: float, rot: float, sx: float) -> None:
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(rot)
    ctx.scale(max(0.12, abs(sx)), 1.0)
    ctx.move_to(0, -s)
    ctx.curve_to(s * 0.7, -s * 0.5, s * 0.6, s * 0.5, 0, s)
    ctx.curve_to(-s * 0.6, s * 0.5, -s * 0.7, -s * 0.5, 0, -s)
    ctx.close_path()
    ctx.restore()


def _leaves(ctx: cairo.Context, e: _E) -> int:
    u = e.u
    ps = _params("leaves", e.seed, e.n)
    p = 1.15
    _cam(ctx, e, p)
    x0, y0, x1, y1 = _span(e, p)
    vx0, vy0, vx1, vy1 = _visible(e, p, 20 * u)
    cols = tuple(hx(c) for c in ("#ff9f1c", "#e8582f", "#ffd23f", "#c0392b", "#8bc34a"))
    groups: dict[int, list] = {}
    hspan = y1 - y0 + 40 * u
    for i, q in enumerate(ps):
        v = (45 + 35 * q[1]) * u
        y = y0 - 20 * u + (q[2] * hspan + v * (e.tau + 20.0)) % hspan
        sw = math.sin(e.tau * (1.2 + 0.6 * q[3]) + q[4] * 6.3)
        x = x0 + (x1 - x0) * q[0] + 50 * u * sw
        if not (vx0 < x < vx1 and vy0 < y < vy1):
            continue
        rot = 0.7 * sw + q[5] * 6.3
        flip = math.cos(e.tau * (2 + 2 * q[6]) + q[7] * 6.3)
        groups.setdefault(int(q[3] * len(cols)) % len(cols), []).append((x, y, (15 + 9 * q[5]) * u, rot, flip))
    drawn = 0
    for ci, items in groups.items():
        for x, y, s, rot, flip in items:
            _leaf_path(ctx, x, y, s, rot, flip)
            drawn += 1
        _ink_fill(ctx, cols[ci], e.alpha, 1.6 * u, mul(cols[ci], 0.45))
        for x, y, s, rot, flip in items:
            ca, sa = math.cos(rot), math.sin(rot)
            ctx.move_to(x - sa * s * 0.8, y + ca * s * 0.8)
            ctx.line_to(x + sa * s * 0.8, y - ca * s * 0.8)
        ctx.set_source_rgba(*mul(cols[ci], 0.55), 0.8 * e.alpha)
        ctx.set_line_width(1.2 * u)
        ctx.stroke()
    return drawn


def _coins(ctx: cairo.Context, e: _E) -> int:
    """Монетки вертятся (3D-переворот: ширина — |cos|) и падают; из точки — фонтаном вверх, без точки — дождём."""
    u = e.u
    ps = _params("coins", e.seed, e.n)
    p = 1.0 if e.ex is not None else 1.15
    _cam(ctx, e, p)
    gold = hx("#ffc93c")
    edge = hx("#c98a12")
    items = []
    for i, q in enumerate(ps):
        if e.ex is not None:
            age = e.tau - q[7] * min(1.0, e.dur * 0.4)
            if age < 0:
                continue
            a = -math.pi / 2 + (q[0] - 0.5) * 1.4
            sp = (480 + 300 * q[1]) * u
            x = e.ex + _drag(math.cos(a) * sp, 0.0, 1.2, age)
            y = (e.ey if e.ey is not None else e.h * 0.6) + _drag(math.sin(a) * sp, 1300 * u, 1.2, age)
            if y > e.h * 1.1:
                continue
        else:
            life = 2.4
            age = (e.tau + q[7] * life * 2) % life
            x = e.w * (0.04 + 0.92 * q[0])
            y = -30 * u + (e.h * 1.1 + 60 * u) * (age / life) ** 1.3
        spin = math.cos(age * (6 + 5 * q[2]) + q[3] * 6.3)
        items.append((x, y, (16 + 6 * q[4]) * u, spin))
    for x, y, r, sp in items:
        ellipse(ctx, x + r * 0.12 * (1 if sp > 0 else -1), y, r * max(0.12, abs(sp)), r)
    _ink_fill(ctx, edge, e.alpha, 1.8 * u)
    for x, y, r, sp in items:
        ellipse(ctx, x, y, r * max(0.08, abs(sp)) * 0.86, r * 0.86)
    ctx.set_source_rgba(*gold, e.alpha)
    ctx.fill()
    for x, y, r, sp in items:
        if abs(sp) > 0.35:
            ctx.save()
            ctx.translate(x, y)
            ctx.scale(abs(sp), 1.0)
            star(ctx, 0, 0, r * 0.45, 5, 0.45)
            ctx.restore()
    ctx.set_source_rgba(*mul(edge, 1.05), 0.9 * e.alpha)
    ctx.fill()
    for x, y, r, sp in items:
        if sp > 0.8:
            ctx.new_sub_path()
            sparkle(ctx, x - r * 0.4, y - r * 0.5, r * 0.6)
    ctx.set_source_rgba(1, 1, 1, 0.9 * e.alpha)
    ctx.fill()
    return len(items)


def _note_path(ctx: cairo.Context, x: float, y: float, s: float, double: bool) -> None:
    """Нота ♪ (головка, штиль, флажок) или ♫ (две головки с ребром) — контуром, без шрифта."""
    heads = ((x, y), (x + s * 1.3, y - s * 0.3)) if double else ((x, y),)
    for hx_, hy in heads:
        ellipse(ctx, hx_, hy, s * 0.55, s * 0.4, -0.4)
        ctx.new_sub_path()
        ctx.rectangle(hx_ + s * 0.38, hy - s * 2.0, s * 0.18, s * 2.0)
    if double:
        x2 = x + s * 1.3
        ctx.move_to(x + s * 0.38, y - s * 2.0)
        ctx.line_to(x2 + s * 0.56, y - s * 2.3)
        ctx.line_to(x2 + s * 0.56, y - s * 1.9)
        ctx.line_to(x + s * 0.38, y - s * 1.6)
        ctx.close_path()
    else:
        ctx.move_to(x + s * 0.4, y - s * 2.0)
        ctx.curve_to(x + s * 0.9, y - s * 1.6, x + s * 1.2, y - s * 1.3, x + s * 0.9, y - s * 0.8)
        ctx.curve_to(x + s * 1.0, y - s * 1.3, x + s * 0.8, y - s * 1.5, x + s * 0.5, y - s * 1.6)
        ctx.close_path()


def _music(ctx: cairo.Context, e: _E) -> int:
    u = e.u
    ps = _params("music", e.seed, e.n)
    _cam(ctx, e, 1.0)
    sx, sy, point = _source(e, 0.55)
    cols = tuple(hx(c) for c in ("#ff5fa2", "#3ec1ff", "#b48cff", "#ffd23f"))
    groups: dict[int, list] = {}
    for q in ps:
        life = 1.8 + 0.6 * q[6]
        age = _stream(e, q, life)
        a = _life(age, life)
        if a <= 0.02:
            continue
        x0 = sx + (q[0] - 0.5) * (70 * u if point else e.w * 0.85)
        y0 = sy if point else e.h * (0.6 + 0.3 * q[1])
        x = x0 + 30 * u * math.sin(age * 2.2 + q[3] * 6) + (q[0] - 0.5) * 60 * u * age
        y = y0 - (80 + 70 * q[1]) * u * age
        s = (16 + 7 * q[4]) * u * ease_out_back(clamp(age / 0.25))
        groups.setdefault(int(q[5] * len(cols)) % len(cols), []).append((x, y, s, q[2] > 0.5, 0.25 * math.sin(age * 3)))
    drawn = 0
    for ci, items in groups.items():
        for x, y, s, double, rot in items:
            ctx.save()
            ctx.translate(x, y)
            ctx.rotate(rot)
            _note_path(ctx, 0, 0, s, double)
            ctx.restore()
            drawn += 1
        ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
        _ink_fill(ctx, cols[ci], e.alpha, 2.4 * u)
    return drawn


def _flash(ctx: cairo.Context, e: _E) -> int:
    """Белая вспышка на весь кадр: резко вспыхивает (0.05 с) и гаснет к концу эффекта."""
    dur = min(e.dur, 1.2)
    f = e.tau / max(0.05, dur)
    a = smoothstep(clamp(e.tau / 0.05)) * (1.0 - ease("out", clamp((f - 0.08) / 0.92)))
    if a <= 0.0:
        return 0
    ctx.identity_matrix()
    ctx.set_source_rgba(1, 1, 1, 0.92 * a)
    ctx.paint()
    return 0


KINDS: dict[str, Callable[[cairo.Context, _E], int]] = {
    "confetti": _confetti, "snow": _snow, "rain": _rain, "hearts": _hearts, "stars": _stars, "sparkles": _sparkles,
    "fire": _fire, "smoke": _smoke, "poof": _poof, "fireworks": _fireworks, "balloons": _balloons,
    "bubbles": _bubbles, "leaves": _leaves, "coins": _coins, "music": _music, "flash": _flash,
}


def window_of(eff: PlannedEffect) -> tuple[float, float]:
    """Когда эффект виден (секунды ролика) — для тестов и оценки стоимости."""
    return eff.t0, eff.t1

