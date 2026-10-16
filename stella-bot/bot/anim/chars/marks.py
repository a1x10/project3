"""Значки над головой (эмоциональные «знаки» манги): сердечки, капля пота, венка злости, искры, ?, !, zzz, лампочка,
ноты, звёздочки головокружения, пар, линии шока, слёзы-фонтанчики. Плюс внутренние: дымок появления/исчезновения
(_puff), искра хлопка (_spark), пыль из-под ног (_dust).

Рисуются в экранных координатах (не зеркалятся — буквы «?» и «Z» читаются правильно), положение — от центра
головы в единицах куклы × u пикселей. Прогресс p 0..1: появление с перелётом (ease_out_back), в конце — угасание.
"""

from __future__ import annotations

import math

import cairocffi as cairo

from ..draw import ellipse, fill_union, heart, set_source, sparkle, star, text_path
from ..ease import clamp, ease_out_back, smoothstep
from ..palette import INK, hx, lighten

HEART = hx("#ff3d6e")
SWEAT = hx("#8fd3ff")
ANGER = hx("#ff2e3d")
GOLD = hx("#ffd23f")


def _env(p: float, pop: float = 0.15, fade: float = 0.22) -> tuple[float, float]:
    """(масштаб появления, прозрачность угасания) для прогресса p."""
    s = ease_out_back(clamp(p / pop)) if pop > 0 else 1.0
    a = 1.0 - smoothstep((p - (1.0 - fade)) / fade) if fade > 0 else 1.0
    return max(0.0, s), clamp(a)


def _ink(ctx: cairo.Context, lw: float, alpha: float = 1.0) -> None:
    set_source(ctx, INK, alpha)
    ctx.set_line_width(lw)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()


def _glyph(ctx: cairo.Context, text: str, x: float, y: float, size: float, fill, alpha: float, rot: float = 0.0,
           lw: float = 3.0) -> None:
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(rot)
    ctx.new_path()
    text_path(ctx, text, 0, 0, size, True, "center")
    set_source(ctx, INK, alpha)
    ctx.set_line_width(lw * 2)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke_preserve()
    set_source(ctx, fill, alpha)
    ctx.fill()
    ctx.restore()


def _group_paint(ctx: cairo.Context, box: tuple[float, float, float, float], draw, alpha: float) -> None:
    """Нарисовать draw() группой с прозрачностью alpha; группа — только по рамке box (x, y, w, h)."""
    ctx.save()
    ctx.rectangle(*box)
    ctx.clip()
    ctx.push_group()
    draw()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(clamp(alpha))
    ctx.restore()


def draw_mark(ctx: cairo.Context, kind: str, p: float, cx: float, cy: float, u: float, f: int, r: float,
              t: float) -> None:
    """Один значок. (cx, cy) — центр головы в пикселях, u — пикселей на единицу, f — куда смотрит (±1),
    r — радиус головы в единицах, t — абсолютное время (для мерцания)."""
    if u <= 0 or p < 0 or p > 1:
        return
    sc, al = _env(p)
    if al <= 0.01 or sc <= 0.01:
        return
    lw = max(1.2, 2.6 * u)
    fn = _MARKS.get(kind)
    if fn is not None:
        fn(ctx, p, cx, cy, u, f, r, t, sc, al, lw)


def _hearts(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    for i in range(3):
        q = clamp(p * 1.25 - i * 0.12)
        if q <= 0:
            continue
        x = cx + f * (r * 0.75 + 10 * math.sin(q * 7 + i * 2) + i * 14 - 8) * u
        y = cy + (-r * 0.85 - q * 70 - i * 6) * u
        s = (9 + 3 * (i % 2)) * u * ease_out_back(clamp(q / 0.25))
        a = al * (1 - smoothstep((q - 0.7) / 0.3))
        if a <= 0.02:
            continue
        heart(ctx, x, y, s)
        set_source(ctx, HEART, a)
        ctx.fill_preserve()
        _ink(ctx, lw * 0.8, a)
        ellipse(ctx, x - s * 0.4, y - s * 0.28, s * 0.18, s * 0.12, -0.6)
        ctx.set_source_rgba(1, 1, 1, 0.85 * a)
        ctx.fill()


def _sweat(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    x = cx + f * r * 0.92 * u
    y = cy + (-r * 0.55 + 14 * smoothstep(p)) * u
    s = 13 * u * sc
    ctx.move_to(x, y - s * 1.6)
    ctx.curve_to(x + s * 0.9, y - s * 0.3, x + s, y + s * 0.8, x, y + s)
    ctx.curve_to(x - s, y + s * 0.8, x - s * 0.9, y - s * 0.3, x, y - s * 1.6)
    ctx.close_path()
    g = cairo.LinearGradient(x, y - s * 1.6, x, y + s)
    g.add_color_stop_rgba(0, *lighten(SWEAT, 0.5), al)
    g.add_color_stop_rgba(1, *SWEAT, al)
    ctx.set_source(g)
    ctx.fill_preserve()
    _ink(ctx, lw, al)
    ellipse(ctx, x - s * 0.35, y + s * 0.1, s * 0.18, s * 0.32, 0.3)
    ctx.set_source_rgba(1, 1, 1, 0.85 * al)
    ctx.fill()


def _anger(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    x = cx + f * r * 0.78 * u
    y = cy - r * 0.92 * u
    s = u * sc * (1 + 0.15 * math.sin(t * 12))
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    for k in range(4):
        ctx.save()
        ctx.rotate(k * math.pi / 2 + 0.3)
        ctx.move_to(5, -17)
        ctx.curve_to(5, -6, 6, -5, 17, -5)
        ctx.restore()
    ctx.restore()
    set_source(ctx, INK, al)
    ctx.set_line_width(lw * 3.2)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke_preserve()
    set_source(ctx, ANGER, al)
    ctx.set_line_width(lw * 1.6)
    ctx.stroke()


def _sparkles(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    pts = ((0.95, -0.95, 13), (-0.85, -1.05, 10), (1.25, -0.35, 8), (0.35, -1.35, 9))
    for i, (dx, dy, s0) in enumerate(pts):
        tw = 0.65 + 0.35 * math.sin(t * 9 + i * 1.9)
        s = s0 * u * sc * tw
        x, y = cx + f * dx * r * u, cy + dy * r * u
        sparkle(ctx, x, y, s)
        set_source(ctx, lighten(GOLD, 0.35), al)
        ctx.fill_preserve()
        _ink(ctx, lw * 0.6, al * 0.9)


def _question(ctx, p, cx, cy, u, f, r, t, sc, al, lw, text="?", fill=(1.0, 0.82, 0.25)):
    x = cx + f * r * 0.95 * u
    y = cy - r * 1.2 * u
    wob = 0.18 * math.sin(t * 5) * (1 - p * 0.5)
    _glyph(ctx, text, x, y, 42 * u * sc, fill, al, f * 0.15 + wob, lw * 1.1)


def _exclaim(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    _question(ctx, p, cx, cy, u, f, r, t, sc, al, lw, text="!", fill=(1.0, 0.3, 0.3))


def _zzz(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    for i in range(3):
        q = (t * 0.45 + i / 3) % 1.0
        x = cx + f * (r * 0.75 + q * 40 + 6 * math.sin(q * 6)) * u
        y = cy + (-r * 0.9 - q * 55) * u
        a = al * smoothstep(q / 0.2) * (1 - smoothstep((q - 0.7) / 0.3))
        if a > 0.02:
            _glyph(ctx, "Z", x, y, (16 + 14 * q) * u, (0.75, 0.82, 1.0), a, f * 0.25, lw * 0.9)


def _idea(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    x, y = cx + f * 0.15 * r * u, cy - r * 1.55 * u
    s = u * sc
    glow = 0.75 + 0.25 * math.sin(t * 8)
    g = cairo.RadialGradient(x, y, 0, x, y, 34 * s)
    g.add_color_stop_rgba(0, 1, 0.95, 0.5, 0.6 * al * glow)
    g.add_color_stop_rgba(1, 1, 0.95, 0.5, 0)
    ctx.set_source(g)
    ctx.arc(x, y, 34 * s, 0, 2 * math.pi)
    ctx.fill()
    for k in range(7):
        a = -math.pi + k * math.pi / 6
        ctx.move_to(x + math.cos(a) * 20 * s, y + math.sin(a) * 20 * s)
        ctx.line_to(x + math.cos(a) * (27 + 3 * glow) * s, y + math.sin(a) * (27 + 3 * glow) * s)
    set_source(ctx, GOLD, al)
    ctx.set_line_width(3 * s)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    ctx.move_to(x - 7 * s, y + 9 * s)
    ctx.curve_to(x - 16 * s, y, x - 15 * s, y - 16 * s, x, y - 16 * s)
    ctx.curve_to(x + 15 * s, y - 16 * s, x + 16 * s, y, x + 7 * s, y + 9 * s)
    ctx.close_path()
    gg = cairo.RadialGradient(x - 4 * s, y - 8 * s, 1, x, y - 4 * s, 16 * s)
    gg.add_color_stop_rgba(0, 1, 1, 0.9, al)
    gg.add_color_stop_rgba(1, 1, 0.85, 0.25, al)
    ctx.set_source(gg)
    ctx.fill_preserve()
    _ink(ctx, lw, al)
    ctx.rectangle(x - 7 * s, y + 9 * s, 14 * s, 8 * s)
    set_source(ctx, (0.7, 0.72, 0.82), al)
    ctx.fill_preserve()
    _ink(ctx, lw * 0.8, al)


def _music(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    for i, ch in enumerate(("♪", "♫", "♪")):
        q = (t * 0.5 + i / 3) % 1.0
        x = cx + f * (r * 0.7 + i * 16 + 10 * math.sin(q * 6 + i)) * u
        y = cy + (-r * 0.8 - q * 60) * u
        a = al * smoothstep(q / 0.2) * (1 - smoothstep((q - 0.7) / 0.3))
        if a > 0.02:
            col = ((1.0, 0.45, 0.7), (0.45, 0.75, 1.0), (1.0, 0.82, 0.3))[i]
            _glyph(ctx, ch, x, y, 26 * u, col, a, 0.2 * math.sin(t * 4 + i), lw * 0.8)


def _dizzy(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    for i in range(3):
        a = t * 4.5 + i * 2 * math.pi / 3
        depth = 0.5 + 0.5 * math.sin(a)
        x = cx + math.cos(a) * r * 0.95 * u
        y = cy + (-r * 0.95 + math.sin(a) * r * 0.22) * u
        s = (7 + 4 * depth) * u * sc
        star(ctx, x, y, s, 5, 0.48, a)
        set_source(ctx, GOLD, al * (0.55 + 0.45 * depth))
        ctx.fill_preserve()
        _ink(ctx, lw * 0.7, al * (0.55 + 0.45 * depth))


def _steam(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    for s in (-1, 1):
        q = (t * 1.3 + (0.5 if s > 0 else 0.0)) % 1.0
        x = cx + s * r * 0.7 * u + s * q * 18 * u
        y = cy + (-r * 1.0 - q * 30) * u
        rr = (6 + 8 * q) * u * sc
        a = al * (1 - q * 0.8)

        def puffs(x: float = x, y: float = y, rr: float = rr, s: int = s) -> None:
            for k in range(3):
                ctx.new_sub_path()
                ctx.arc(x + s * k * rr * 0.7, y - k * rr * 0.6, rr * (1 - k * 0.15), 0, 2 * math.pi)
        box = (x - rr * 2 - lw, y - rr * 3 - lw, rr * 4 + 2 * lw + rr * 2, rr * 5 + 2 * lw)
        _group_paint(ctx, box, lambda puffs=puffs, lw=lw: fill_union(ctx, puffs, (0.96, 0.96, 1.0), lw * 0.7), a)


def _shock(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    for k in range(9):
        a = -math.pi + k * math.pi / 8
        r0 = r * (1.15 + 0.06 * math.sin(t * 20 + k)) * u
        r1 = r0 + 22 * u * sc
        ctx.move_to(cx + math.cos(a) * r0, cy - r * 0.25 * u + math.sin(a) * r0)
        ctx.line_to(cx + math.cos(a) * r1, cy - r * 0.25 * u + math.sin(a) * r1)
    _ink(ctx, lw * 1.3, al)


def _tears_mark(ctx, p, cx, cy, u, f, r, t, sc, al, lw):
    for s in (-1, 1):
        for k in range(4):
            q = (t * 1.8 + k / 4) % 1.0
            x = cx + s * (r * 0.5 + q * 38) * u
            y = cy + (-4 - 30 * q + 60 * q * q) * u
            rr = 4.5 * u * (1 - 0.4 * q)
            ellipse(ctx, x, y, rr, rr * 1.25)
            set_source(ctx, SWEAT, al * (1 - q))
            ctx.fill()


_MARKS = {
    "hearts": _hearts, "sweat": _sweat, "anger": _anger, "sparkles": _sparkles, "question": _question,
    "exclaim": _exclaim, "zzz": _zzz, "idea": _idea, "music": _music, "dizzy": _dizzy, "steam": _steam,
    "shock": _shock, "tears": _tears_mark,
}


# ---------- внутренние значки (их ставят действия) ----------
def draw_puff(ctx: cairo.Context, p: float, cx: float, cy: float, u: float, seed: float = 0.0) -> None:
    """Облачко дыма (появление/исчезновение): пуфы разлетаются и тают. (cx, cy) — центр тела."""
    if p <= 0 or p >= 1:
        return
    grow = ease_out_back(clamp(p / 0.35))
    a = 1.0 - smoothstep((p - 0.22) / 0.33)
    if a <= 0.01:
        return
    lw = max(1.2, 2.6 * u)

    def puffs() -> None:
        for i in range(9):
            ang = 2 * math.pi * i / 9 + seed
            d = (40 + 55 * p) * u
            rr = (30 - 8 * (i % 3)) * u * grow * (1 - 0.8 * p)
            ctx.new_sub_path()
            ctx.arc(cx + math.cos(ang) * d, cy + math.sin(ang) * d * 0.8, max(0.5, rr), 0, 2 * math.pi)
        ctx.new_sub_path()
        ctx.arc(cx, cy, max(0.5, 52 * u * grow * (1 - 0.6 * p)), 0, 2 * math.pi)
    ext = (140 + 100 * p) * u
    _group_paint(ctx, (cx - ext, cy - ext, ext * 2, ext * 2), lambda: fill_union(ctx, puffs, (0.93, 0.91, 1.0), lw), a)
    if p < 0.5:
        for i in range(5):
            ang = 2 * math.pi * i / 5 + 0.4 + seed
            d = (70 + 90 * p) * u
            sparkle(ctx, cx + math.cos(ang) * d, cy + math.sin(ang) * d * 0.8, 9 * u * (1 - p * 1.6))
        set_source(ctx, GOLD, 1 - p * 2)
        ctx.fill()


def draw_spark(ctx: cairo.Context, p: float, x: float, y: float, u: float) -> None:
    """Искра в точке касания (хлопок, «дай пять»)."""
    if p <= 0 or p >= 1:
        return
    s = ease_out_back(clamp(p / 0.4)) * (1 - p * 0.3)
    a = 1 - smoothstep((p - 0.4) / 0.6)
    star(ctx, x, y, 22 * u * s, 8, 0.42, p * 0.8)
    set_source(ctx, (1.0, 0.97, 0.7), a)
    ctx.fill_preserve()
    set_source(ctx, GOLD, a)
    ctx.set_line_width(max(1.0, 2.2 * u))
    ctx.stroke()
    for k in range(6):
        ang = k * math.pi / 3 + 0.3
        r0, r1 = 26 * u * s, (34 + 16 * p) * u * s
        ctx.move_to(x + math.cos(ang) * r0, y + math.sin(ang) * r0)
        ctx.line_to(x + math.cos(ang) * r1, y + math.sin(ang) * r1)
    set_source(ctx, INK, a)
    ctx.set_line_width(max(1.0, 2.6 * u))
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()


def draw_dust(ctx: cairo.Context, p: float, x: float, y: float, u: float, f: int) -> None:
    """Облачко пыли у ступни (бег, топот, приземление). y — земля."""
    if p <= 0 or p >= 1:
        return
    a = (1 - p) * 0.85
    lw = max(1.0, 2.0 * u)

    def puffs() -> None:
        for i in range(4):
            dx = (-f) * (8 + i * 11 + 26 * p) * u
            rr = (7 + 3 * i) * u * (0.6 + 0.6 * p)
            ctx.new_sub_path()
            ctx.arc(x + dx, y - rr * 0.7 - i * 2 * u, rr, 0, 2 * math.pi)
    ext = 90 * u
    _group_paint(ctx, (x - ext, y - ext, ext * 2, ext * 1.2), lambda: fill_union(ctx, puffs, (0.93, 0.9, 0.86), lw), a)


MARK_KINDS = tuple(_MARKS)
__all__ = ["MARK_KINDS", "draw_dust", "draw_mark", "draw_puff", "draw_spark"]
