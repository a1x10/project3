"""2D-предметы мультика (catalog.PROPS_2D): стол, стул, табличка, дерево, куст, цветок, мяч, книга, телефон, пицца,
мороженое, чашка, гитара, микрофон, зонт, машинка, домик и SVG-рисунок модели (готовый PNG-спрайт).

Стиль — как у персонажей: единая обводка INK, объём (свет сверху-слева), двухтоновая тень, сочные цвета.
Каждый предмет рисуется в своей коробке «100 единиц высоты» (y от −50 до +50, центр — (0, 0)) и масштабируется
до size_px. У предметов есть собственная «жизнь» (пар над чашкой, колёса машинки, дым из трубы, экран телефона)
и анимации из catalog.PROP_ANIMS (spin, float, bounce, pulse, wobble, swing) — те же, что у 3D-предметов.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Callable

import cairocffi as cairo

from . import catalog
from .draw import (body_grad, cel_shadow, clean_text, ellipse, fill_ink, fill_union, heart, paint_sprite, rrect,
                   sparkle, sprite_from_png, star, text_path, wrap)
from .ease import hash01
from .model import RGB, AnimError, PropSpec
from .palette import INK, hx, lighten, mix, mul

DEFAULT_COLOR: dict[str, str] = {
    "table": "#c8864f", "chair": "#ef6f5e", "sign": "#ffe7b0", "tree": "#5cc062", "bush": "#4caf50",
    "flower": "#ff6fa5", "ball": "#ff4d5a", "book": "#3e7bfa", "phone": "#2f3352", "pizza": "#f2b25c",
    "ice_cream": "#ff9ec7", "cup": "#ff7f6b", "guitar": "#e8913a", "microphone": "#4b4f63", "umbrella": "#ff4d6d",
    "car": "#ff5a5f", "house": "#ffcf8a",
}
# ширина предмета относительно высоты (для раскладки и тестов)
ASPECT: dict[str, float] = {
    "table": 1.6, "chair": 0.75, "sign": 1.5, "tree": 0.85, "bush": 1.5, "flower": 0.6, "ball": 1.0, "book": 1.5,
    "phone": 0.55, "pizza": 0.9, "ice_cream": 0.55, "cup": 1.05, "guitar": 0.45, "microphone": 0.42,
    "umbrella": 1.2, "car": 1.9, "house": 1.0, "svg": 1.0,
}


@dataclass
class Motion:
    """Движение предмета (единицы коробки 100): сдвиг, поворот вокруг опоры, масштаб; back — видна изнанка."""

    dy: float = 0.0
    rot: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    pivot: float = 0.0  # y опоры: +50 — низ, −50 — верх
    back: bool = False


def motion(anim: str, t: float, phase: float) -> Motion:
    """Анимация предмета (чистая функция времени) — как у 3D-предметов (three.props3d.prop_motion)."""
    tp = t + phase
    tau = 2 * math.pi
    if anim == "spin":  # поворот вокруг вертикали: ширина — |cos|, на изнанке зеркально
        c = math.cos(tp * tau / 2.6)
        return Motion(sx=math.copysign(max(0.04, abs(c)), c), back=c < 0)
    if anim == "float":
        return Motion(dy=-8.0 * math.sin(tp * tau / 2.2), rot=0.05 * math.sin(tp * tau / 3.1))
    if anim == "bounce":
        p = (tp / 0.9) % 1.0
        hgt = 4 * p * (1 - p)
        c = max(0.0, 1.0 - min(p, 1 - p) / 0.1)  # у земли — сплющивание
        sy = 1.0 - 0.22 * c + 0.06 * hgt
        return Motion(dy=-32.0 * hgt, sx=1.0 / math.sqrt(sy), sy=sy, pivot=50.0)
    if anim == "pulse":
        k = 1.0 + 0.1 * max(0.0, math.sin(tp * tau / 0.9)) ** 6
        return Motion(sx=k, sy=k)
    if anim == "wobble":
        return Motion(rot=0.2 * math.sin(tp * tau / 1.1), pivot=50.0)
    if anim == "swing":
        return Motion(rot=0.38 * math.sin(tp * tau / 1.6), pivot=-50.0)
    return Motion()


@dataclass
class _P:
    """Что знает функция рисования предмета: цвет, время, толщина обводки в единицах коробки, текст."""

    col: RGB
    t: float
    lw: float
    text: str
    back: bool
    seed: int
    custom: bool  # цвет задан моделью
    anim: str = "none"


def draw_prop2d(ctx: cairo.Context, prop: PropSpec, t: float, x: float, y: float, size_px: float,
                cache: dict) -> None:
    """2D-предмет prop.kind (из PROPS_2D) с центром (x, y) и высотой size_px в момент t. kind=svg — спрайт из
    prop.svg_png (кешируется в cache). Неизвестный вид или испорченная картинка — ничего не рисует."""
    kind = prop.kind
    if kind not in catalog.PROPS_2D or not all(map(math.isfinite, (x, y, size_px, t))) or size_px < 2:
        return
    phase = hash01(0, "prop", prop.id) * 7.0
    mo = motion(prop.anim, t, phase) if not (kind == "ball" and prop.anim == "spin") else Motion()  # мяч катится
    k = size_px / 100.0
    ctx.save()
    ctx.new_path()
    ctx.translate(x, y + mo.dy * k)
    if mo.pivot:
        ctx.translate(0, mo.pivot * k)
    if mo.rot:
        ctx.rotate(mo.rot)
    if mo.sx != 1.0 or mo.sy != 1.0:
        ctx.scale(mo.sx, mo.sy)
    if mo.pivot:
        ctx.translate(0, -mo.pivot * k)
    if kind == "svg":
        _svg(ctx, prop, size_px, cache)
        ctx.restore()
        return
    ctx.scale(k, k)
    lw_px = min(5.0, max(2.0, 1.4 + 0.022 * size_px))
    col = prop.color if prop.color is not None else hx(DEFAULT_COLOR[kind])
    text, _ = clean_text(prop.text or "", 24)
    p = _P(col, t + phase, lw_px / k, text, mo.back, int(hash01(0, "pseed", prop.id) * 1e6), prop.color is not None,
           prop.anim)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    DRAW[kind](ctx, p)
    ctx.restore()
    ctx.new_path()


def _svg(ctx: cairo.Context, prop: PropSpec, size_px: float, cache: dict) -> None:
    png = prop.svg_png
    if not png:
        return
    key = ("svg", hashlib.sha1(png).hexdigest())
    if key not in cache:
        try:
            cache[key] = sprite_from_png(png, 512)
        except AnimError:
            cache[key] = None
    sprite = cache[key]
    if sprite is None:
        return
    sw, sh = sprite.get_width(), sprite.get_height()
    h = size_px
    w = size_px * sw / max(1, sh)
    paint_sprite(ctx, sprite, 0.0, 0.0, w, h)


# ======================= помощники =======================
def _ink(ctx: cairo.Context, fill, lw: float) -> None:
    fill_ink(ctx, fill, lw)


def _lin(y0: float, y1: float, top: RGB, bot: RGB) -> cairo.LinearGradient:
    g = cairo.LinearGradient(0, y0, 0, y1)
    g.add_color_stop_rgb(0, *top)
    g.add_color_stop_rgb(1, *bot)
    return g


def _hlin(x0: float, x1: float, a: RGB, b: RGB) -> cairo.LinearGradient:
    g = cairo.LinearGradient(x0, 0, x1, 0)
    g.add_color_stop_rgb(0, *a)
    g.add_color_stop_rgb(1, *b)
    return g


def _shine(ctx: cairo.Context, x: float, y: float, rx: float, ry: float, rot: float = -0.5, a: float = 0.75) -> None:
    ellipse(ctx, x, y, rx, ry, rot)
    ctx.set_source_rgba(1, 1, 1, a)
    ctx.fill()


def _shade(ctx: cairo.Context, path: Callable[[], None], base: RGB, dx: float = 7.0, dy: float = 5.0) -> None:
    cel_shadow(ctx, path, base, dx, dy)


# ======================= предметы =======================
def _table(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    for lx in (-62, 52):
        def leg(lx: float = lx) -> None:
            rrect(ctx, lx, -18, 10, 66, 4)
        leg()
        _ink(ctx, _hlin(lx, lx + 10, lighten(c, 0.1), mul(c, 0.75)), lw)
    # столешница: верхняя грань и торец
    ctx.move_to(-72, -30)
    ctx.line_to(72, -30)
    ctx.line_to(80, -20)
    ctx.line_to(-80, -20)
    ctx.close_path()
    _ink(ctx, lighten(c, 0.22), lw)

    def front() -> None:
        rrect(ctx, -80, -21, 160, 14, 4)

    front()
    _ink(ctx, _lin(-21, -7, c, mul(c, 0.8)), lw)
    ctx.move_to(-70, -26)
    ctx.line_to(70, -26)
    ctx.set_source_rgba(1, 1, 1, 0.35)
    ctx.set_line_width(lw * 0.8)
    ctx.stroke()


def _chair(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    for lx, top in ((-26, 8), (20, 8)):
        rrect(ctx, lx, top, 8, 42, 3)
        _ink(ctx, mul(c, 0.72), lw)

    def back() -> None:
        rrect(ctx, -28, -50, 56, 54, 12)

    back()
    _ink(ctx, body_grad(-10, -30, 40, c), lw)
    _shade(ctx, back, c)
    for sx in (-14, 0, 14):
        rrect(ctx, sx - 3, -38, 6, 30, 3)
    ctx.set_source_rgba(*mul(c, 0.7), 0.6)
    ctx.fill()

    def seat() -> None:
        rrect(ctx, -34, 0, 68, 14, 6)

    seat()
    _ink(ctx, _lin(0, 14, lighten(c, 0.2), mul(c, 0.85)), lw)


def _sign(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    wood = hx("#a86a3f")
    rrect(ctx, -5, -6, 10, 56, 3)
    _ink(ctx, _hlin(-5, 5, lighten(wood, 0.15), mul(wood, 0.75)), lw)

    def board() -> None:
        rrect(ctx, -72, -48, 144, 58, 10)

    board()
    _ink(ctx, mul(wood, 0.95), lw)
    rrect(ctx, -64, -41, 128, 44, 6)
    ctx.set_source(_lin(-41, 3, lighten(c, 0.12), mul(c, 0.92)))
    ctx.fill()
    for nx in (-58, 58):
        ctx.arc(nx, -43, 2.4, 0, 2 * math.pi)
        ctx.set_source_rgb(*mul(wood, 0.5))
        ctx.fill()
    if p.back or not p.text:
        if not p.text:  # пустая табличка — нарисованное сердечко
            heart(ctx, 0, -14, 14)
            _ink(ctx, hx("#ff4d6d"), lw * 0.8)
        return
    ink = INK if sum(c) > 1.2 else (1.0, 1.0, 1.0)
    size = 22.0
    while True:
        lines = wrap(ctx, p.text, size, 118, bold=True, max_lines=2)
        hgt = len(lines) * size * 1.15
        if (hgt <= 40 and not lines[-1].endswith("…")) or size <= 9:
            break
        size *= 0.9
    y0 = -19 - (len(lines) - 1) * size * 1.15 / 2
    for i, line in enumerate(lines):
        ctx.new_path()
        text_path(ctx, line, 0, y0 + i * size * 1.15, size, True)
        ctx.set_source_rgb(*ink)
        ctx.fill()


def _tree(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    trunk = hx("#8a5a3c")
    ctx.move_to(-9, 50)
    ctx.curve_to(-7, 30, -8, 10, -6, -4)
    ctx.line_to(6, -4)
    ctx.curve_to(8, 10, 7, 30, 9, 50)
    ctx.close_path()
    _ink(ctx, _hlin(-9, 9, lighten(trunk, 0.15), mul(trunk, 0.75)), lw)
    sway = 2.5 * math.sin(p.t * 1.3)
    lobes = ((0, -20, 30), (-24, -14, 20), (24, -14, 20), (-15, -36, 19), (15, -36, 19), (0, -42, 18),
             (-28, 2, 15), (28, 2, 15), (0, 0, 22))

    def canopy() -> None:
        for dx, dy, r in lobes:
            ctx.new_sub_path()
            ctx.arc(dx + sway * (1 - dy / 60), dy, r, 0, 2 * math.pi)

    # контур объединения, потом крона цветом тени, поверх — освещённая крона, сдвинутая к свету (в клипе)
    canopy()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(lw * 2)
    ctx.stroke()
    canopy()
    ctx.set_source_rgb(*mul(c, 0.74))
    ctx.fill_preserve()
    ctx.save()
    ctx.clip()
    ctx.translate(-7, -6)
    canopy()
    ctx.set_source(body_grad(-10 + sway, -30, 44, c))
    ctx.fill()
    ctx.restore()
    for dx, dy, r in ((-14, -34, 4), (4, -44, 3), (-24, -18, 3)):
        ctx.arc(dx + sway, dy, r, 0, 2 * math.pi)
        ctx.new_sub_path()
    ctx.set_source_rgba(1, 1, 1, 0.45)
    ctx.fill()
    if not p.custom:  # яблочки
        for dx, dy in ((-18, -6), (14, -24), (20, 4), (-4, -30)):
            ctx.new_sub_path()
            ctx.arc(dx + sway, dy, 4.2, 0, 2 * math.pi)
        _ink(ctx, hx("#ff4d5a"), lw * 0.6)


def _bush(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    lobes = ((-48, 18, 26), (-22, 0, 32), (12, -6, 34), (44, 14, 28), (0, 22, 30), (-40, 34, 18), (40, 34, 18))
    sway = 1.5 * math.sin(p.t * 1.1)

    def path() -> None:
        for dx, dy, r in lobes:
            ctx.new_sub_path()
            ctx.arc(dx + sway * (1 - dy / 50), dy, r, 0, 2 * math.pi)

    ctx.save()
    ctx.rectangle(-90, -60, 180, 110)
    ctx.clip()
    fill_union(ctx, path, body_grad(-10, -10, 60, c), lw)
    ctx.restore()
    flower = hx("#ffffff") if p.custom else hx("#ff8fb1")
    for dx, dy in ((-30, 6), (6, -16), (34, 10), (-8, 24), (20, 28)):
        for i in range(5):
            a = i * 2 * math.pi / 5
            ctx.new_sub_path()
            ctx.arc(dx + math.cos(a) * 3.6, dy + math.sin(a) * 3.6, 3.0, 0, 2 * math.pi)
    ctx.set_source_rgb(*flower)
    ctx.fill()
    for dx, dy in ((-30, 6), (6, -16), (34, 10), (-8, 24), (20, 28)):
        ctx.new_sub_path()
        ctx.arc(dx, dy, 2.2, 0, 2 * math.pi)
    ctx.set_source_rgb(1.0, 0.85, 0.25)
    ctx.fill()


def _flower(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    sway = 0.08 * math.sin(p.t * 1.6)
    stem = hx("#3fae55")
    ctx.save()
    ctx.translate(0, 50)
    ctx.rotate(sway)
    ctx.move_to(0, 0)
    ctx.curve_to(-4, -30, 4, -55, 0, -72)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(7 + lw * 2)
    ctx.stroke()
    ctx.move_to(0, 0)
    ctx.curve_to(-4, -30, 4, -55, 0, -72)
    ctx.set_source_rgb(*stem)
    ctx.set_line_width(7)
    ctx.stroke()
    for side, yy in ((-1, -22), (1, -36)):
        ctx.move_to(0, yy)
        ctx.curve_to(side * 10, yy - 14, side * 24, yy - 10, side * 26, yy - 2)
        ctx.curve_to(side * 18, yy + 4, side * 8, yy + 4, 0, yy)
        ctx.close_path()
        _ink(ctx, _lin(yy - 14, yy + 4, lighten(stem, 0.2), mul(stem, 0.85)), lw)
    hx_, hy = 0, -76
    for i in range(6):
        a = i * math.pi / 3 + 0.3 * math.sin(p.t * 0.7)
        ellipse(ctx, hx_ + math.cos(a) * 13, hy + math.sin(a) * 13, 11, 8, a)
    _ink(ctx, body_grad(hx_ - 6, hy - 8, 26, c), lw)
    ctx.arc(hx_, hy, 9, 0, 2 * math.pi)
    _ink(ctx, body_grad(hx_ - 3, hy - 3, 10, hx("#ffd23f")), lw)
    ctx.restore()


def _ball(ctx: cairo.Context, p: _P) -> None:
    """Пляжный мяч: 6 долек-меридианов; при anim=spin он вертится (дольки бегут), иначе стоит."""
    c = p.col
    lw = p.lw
    r = 46
    colors = (c, hx("#ffffff"), hx("#3ec1ff"), hx("#ffffff"), hx("#ffd23f"), hx("#ffffff"))
    roll = p.t * 2.4 if p.anim == "spin" else 0.35
    tilt = -0.35
    ctx.save()
    ctx.rotate(tilt)
    ctx.arc(0, 0, r, 0, 2 * math.pi)
    ctx.set_source_rgb(*colors[1])
    ctx.fill()
    steps = 14
    for i in range(6):
        a0 = roll + i * math.pi / 3
        a1 = a0 + math.pi / 3
        # видимая часть дольки: долготы, обращённые к зрителю (cos > 0)
        lo, hi = _visible(a0, a1)
        if lo is None:
            continue
        xa, xb = r * math.sin(lo), r * math.sin(hi)
        for j in range(steps + 1):
            lat = -math.pi / 2 + math.pi * j / steps
            (ctx.move_to if j == 0 else ctx.line_to)(xa * math.cos(lat), r * math.sin(lat))
        for j in range(steps, -1, -1):
            lat = -math.pi / 2 + math.pi * j / steps
            ctx.line_to(xb * math.cos(lat), r * math.sin(lat))
        ctx.close_path()
        ctx.set_source_rgb(*colors[i])
        ctx.fill()
    g = cairo.RadialGradient(-r * 0.35, -r * 0.4, r * 0.1, 0, 0, r * 1.05)
    g.add_color_stop_rgba(0, 1, 1, 1, 0.3)
    g.add_color_stop_rgba(0.6, 1, 1, 1, 0.0)
    g.add_color_stop_rgba(1, 0.12, 0.06, 0.25, 0.4)
    ctx.arc(0, 0, r, 0, 2 * math.pi)
    ctx.set_source(g)
    ctx.fill()
    ctx.arc(0, 0, r, 0, 2 * math.pi)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(lw)
    ctx.stroke()
    ellipse(ctx, 0, -r + 5, 7, 3.5)
    fill_ink(ctx, hx("#ffffff"), lw * 0.6)
    ctx.restore()
    _shine(ctx, -r * 0.42, -r * 0.42, r * 0.16, r * 0.1)


def _visible(a0: float, a1: float) -> tuple[float | None, float]:
    """Пересечение отрезка долгот [a0, a1] с видимой половиной (−π/2..π/2 по модулю 2π)."""
    base = math.floor((a0 + math.pi / 2) / (2 * math.pi)) * 2 * math.pi
    a0, a1 = a0 - base, a1 - base
    lo, hi = max(a0, -math.pi / 2), min(a1, math.pi / 2)
    if hi > lo:
        return lo, hi
    lo, hi = max(a0 - 2 * math.pi, -math.pi / 2), min(a1 - 2 * math.pi, math.pi / 2)
    if hi > lo:
        return lo, hi
    return None, 0.0


def _book(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    # обложка под страницами
    ctx.move_to(-74, -30)
    ctx.curve_to(-40, -40, -10, -36, 0, -28)
    ctx.curve_to(10, -36, 40, -40, 74, -30)
    ctx.line_to(74, 34)
    ctx.curve_to(40, 26, 10, 30, 0, 38)
    ctx.curve_to(-10, 30, -40, 26, -74, 34)
    ctx.close_path()
    _ink(ctx, _lin(-40, 38, lighten(c, 0.15), mul(c, 0.8)), lw)
    page = hx("#fffaf0")
    for side in (-1, 1):
        ctx.move_to(0, -24)
        ctx.curve_to(side * 12, -33, side * 40, -36, side * 68, -26)
        ctx.line_to(side * 68, 28)
        ctx.curve_to(side * 40, 20, side * 12, 23, 0, 32)
        ctx.close_path()
        _ink(ctx, _hlin(0, side * 68, mul(page, 0.88), page), lw)
        for j in range(5):
            yy = -16 + j * 9
            ctx.move_to(side * 12, yy - 2)
            ctx.curve_to(side * 30, yy - 6, side * 46, yy - 6, side * 60, yy - 3)
        ctx.set_source_rgba(*mul(c, 0.6), 0.45)
        ctx.set_line_width(2.4)
        ctx.stroke()
    # страница перелистывается раз в 2.5 с
    ph = (p.t % 2.5) / 0.6
    if ph < 1.0:
        sx = math.cos(ph * math.pi)
        ctx.save()
        ctx.scale(sx if abs(sx) > 0.03 else 0.03, 1)
        ctx.move_to(0, -24)
        ctx.curve_to(12, -36 + 8 * ph, 40, -40 + 8 * ph, 66, -30)
        ctx.line_to(66, 26)
        ctx.curve_to(40, 18, 12, 21, 0, 32)
        ctx.close_path()
        ctx.restore()
        _ink(ctx, mul(page, 0.95 - 0.1 * abs(sx)), lw)
    ctx.move_to(0, -24)
    ctx.line_to(0, 32)
    ctx.set_source_rgba(*INK, 0.6)
    ctx.set_line_width(lw * 0.6)
    ctx.stroke()


def _phone(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw

    def body() -> None:
        rrect(ctx, -26, -50, 52, 100, 10)

    body()
    _ink(ctx, _hlin(-26, 26, lighten(c, 0.25), mul(c, 0.85)), lw)
    rrect(ctx, -21, -40, 42, 78, 4)
    glow = 0.5 + 0.5 * math.sin(p.t * 2.0)
    g = _lin(-40, 38, hx("#7fd8ff"), hx("#b48cff"))
    ctx.set_source(g)
    ctx.fill()
    if not p.back:
        # на экране — сообщение с сердечком, сердце «бьётся»
        rrect(ctx, -16, -30, 26, 14, 5)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        rrect(ctx, -8, -10, 24, 14, 5)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        k = 1.0 + 0.12 * max(0.0, math.sin(p.t * 7)) ** 4
        heart(ctx, 0, 20, 8 * k)
        ctx.set_source_rgb(1.0, 0.3, 0.45)
        ctx.fill()
        sparkle(ctx, 13, 12, 4 + 2 * glow)
        ctx.set_source_rgba(1, 1, 1, 0.6 + 0.4 * glow)
        ctx.fill()
    rrect(ctx, -6, -46, 12, 3, 1.5)
    ctx.set_source_rgba(1, 1, 1, 0.4)
    ctx.fill()
    ctx.move_to(-18, -36)
    ctx.line_to(-6, -36)
    ctx.line_to(-18, -14)
    ctx.close_path()
    ctx.set_source_rgba(1, 1, 1, 0.3)
    ctx.fill()


def _pizza(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    cheese = hx("#ffd54a")

    def slice_() -> None:
        ctx.move_to(0, 48)
        ctx.line_to(-38, -30)
        ctx.curve_to(-20, -40, 20, -40, 38, -30)
        ctx.close_path()

    slice_()
    _ink(ctx, _lin(-38, 48, lighten(cheese, 0.2), cheese), lw)
    # капли сыра
    ctx.move_to(-30, -14)
    ctx.curve_to(-32, -4, -26, -2, -24, -10)
    ctx.move_to(22, -6)
    ctx.curve_to(20, 6, 26, 8, 27, -4)
    ctx.set_source_rgb(*cheese)
    ctx.set_line_width(5)
    ctx.stroke()
    # корочка
    ctx.move_to(-42, -30)
    ctx.curve_to(-22, -46, 22, -46, 42, -30)
    ctx.curve_to(40, -40, 22, -52, 0, -52)
    ctx.curve_to(-22, -52, -40, -40, -42, -30)
    ctx.close_path()
    _ink(ctx, _lin(-52, -30, lighten(c, 0.15), mul(c, 0.82)), lw)
    pep = hx("#d8343f")
    for px, py, r in ((-14, -16, 8), (10, -20, 7), (0, 6, 7), (-6, 26, 5), (16, 0, 5)):
        ctx.new_sub_path()
        ctx.arc(px, py, r, 0, 2 * math.pi)
    _ink(ctx, pep, lw * 0.7)
    for px, py in ((-16, -18), (8, -22), (-2, 4)):
        ctx.new_sub_path()
        ctx.arc(px, py, 2.0, 0, 2 * math.pi)
    ctx.set_source_rgba(1, 1, 1, 0.5)
    ctx.fill()
    for px, py in ((-20, 0), (14, 16), (2, -30)):
        ellipse(ctx, px, py, 4, 2, 0.6)
        ctx.set_source_rgb(*hx("#3fae55"))
        ctx.fill()


def _ice_cream(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    cone = hx("#e8a85c")

    def cone_path() -> None:
        ctx.move_to(-20, -4)
        ctx.line_to(20, -4)
        ctx.line_to(0, 50)
        ctx.close_path()

    cone_path()
    _ink(ctx, _hlin(-20, 20, lighten(cone, 0.15), mul(cone, 0.85)), lw)
    ctx.save()
    cone_path()
    ctx.clip()
    for i in range(-4, 5):
        ctx.move_to(i * 10 - 30, -10)
        ctx.line_to(i * 10 + 30, 50)
        ctx.move_to(i * 10 + 30, -10)
        ctx.line_to(i * 10 - 30, 50)
    ctx.set_source_rgba(*mul(cone, 0.65), 0.7)
    ctx.set_line_width(2)
    ctx.stroke()
    ctx.restore()
    second = mix(c, hx("#fff3d6"), 0.6) if p.custom else hx("#fff3d6")
    for (cx, cy, r), col in (((0, -10, 22), second), ((0, -32, 19), c)):
        ctx.move_to(cx - r, cy + 4)
        ctx.curve_to(cx - r - 2, cy - r * 1.3, cx + r + 2, cy - r * 1.3, cx + r, cy + 4)
        # волнистый низ с каплей
        ctx.curve_to(cx + r * 0.7, cy + 10, cx + r * 0.4, cy + 2, cx + r * 0.2, cy + 6)
        ctx.curve_to(cx, cy + 14 + 2 * math.sin(p.t * 1.5), cx - r * 0.3, cy + 4, cx - r * 0.5, cy + 8)
        ctx.curve_to(cx - r * 0.7, cy + 10, cx - r * 0.9, cy + 4, cx - r, cy + 4)
        ctx.close_path()
        _ink(ctx, body_grad(cx - 6, cy - 8, r * 1.2, col), lw)
    ctx.arc(4, -52, 6, 0, 2 * math.pi)
    _ink(ctx, body_grad(2, -54, 6, hx("#e8243a")), lw * 0.8)
    ctx.move_to(5, -57)
    ctx.curve_to(6, -62, 10, -64, 13, -64)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(lw * 0.7)
    ctx.stroke()
    for i in range(7):
        a = hash01(p.seed, "spr", i) * math.pi * 2
        rx, ry = math.cos(a) * 12, -32 + math.sin(a) * 9
        ctx.save()
        ctx.translate(rx, ry)
        ctx.rotate(a)
        rrect(ctx, -3, -1, 6, 2.2, 1)
        ctx.restore()
        ctx.set_source_rgb(*hx(("#3ec1ff", "#ffd23f", "#7cd67c", "#ffffff")[i % 4]))
        ctx.fill()
    _shine(ctx, -9, -40, 4, 2.5)


def _cup(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    # пар поднимается
    for i in range(3):
        ph = (p.t * 0.5 + i / 3) % 1.0
        x0 = -14 + i * 14
        y0 = -24 - ph * 30
        a = math.sin(math.pi * ph) * 0.6
        ctx.move_to(x0, y0)
        ctx.curve_to(x0 - 6, y0 - 6, x0 + 6, y0 - 10, x0, y0 - 16)
        ctx.set_source_rgba(1, 1, 1, a)
        ctx.set_line_width(4)
        ctx.stroke()
    ctx.arc(30, 6, 13, -math.pi / 2, math.pi / 2)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(9 + 2 * lw)
    ctx.stroke()
    ctx.arc(30, 6, 13, -math.pi / 2, math.pi / 2)
    ctx.set_source_rgb(*c)
    ctx.set_line_width(9)
    ctx.stroke()

    def body() -> None:
        ctx.move_to(-32, -20)
        ctx.line_to(32, -20)
        ctx.line_to(28, 38)
        ctx.curve_to(26, 46, 20, 48, 14, 48)
        ctx.line_to(-14, 48)
        ctx.curve_to(-20, 48, -26, 46, -28, 38)
        ctx.close_path()

    body()
    _ink(ctx, _hlin(-32, 32, lighten(c, 0.2), mul(c, 0.8)), lw)
    _shade(ctx, body, c)
    ellipse(ctx, 0, -20, 32, 7)
    _ink(ctx, mul(c, 0.9), lw)
    ellipse(ctx, 0, -19, 27, 4.5)
    ctx.set_source_rgb(*hx("#7a4a2a"))
    ctx.fill()
    if not p.back:
        heart(ctx, 0, 16, 10)
        ctx.set_source_rgba(1, 1, 1, 0.85)
        ctx.fill()
    rrect(ctx, -24, -10, 6, 34, 3)
    ctx.set_source_rgba(1, 1, 1, 0.35)
    ctx.fill()


def _guitar(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    neck = hx("#7a4a2a")
    rrect(ctx, -5, -50, 10, 60, 3)
    _ink(ctx, neck, lw)
    rrect(ctx, -8, -54, 16, 12, 4)
    _ink(ctx, mul(neck, 0.8), lw)
    for side in (-1, 1):
        for j in range(2):
            ctx.new_sub_path()
            ctx.arc(side * 10, -51 + j * 6, 2.5, 0, 2 * math.pi)
    _ink(ctx, hx("#d9d9e6"), lw * 0.5)

    def body() -> None:
        ctx.new_sub_path()
        ctx.arc(0, 4, 15, 0, 2 * math.pi)
        ctx.new_sub_path()
        ctx.arc(0, 30, 21, 0, 2 * math.pi)

    fill_union(ctx, body, body_grad(-6, 10, 30, c), lw)
    ctx.arc(0, 18, 7, 0, 2 * math.pi)
    _ink(ctx, hx("#3a2418"), lw * 0.6)
    rrect(ctx, -9, 33, 18, 5, 2)
    _ink(ctx, mul(neck, 0.9), lw * 0.6)
    vib = 0.6 * math.sin(p.t * 60) if (p.t % 1.5) < 0.4 else 0.0
    for i in range(4):
        sx = -3 + i * 2
        ctx.move_to(sx, -44)
        ctx.curve_to(sx + vib, -10, sx - vib, 20, sx, 34)
    ctx.set_source_rgba(1, 1, 1, 0.8)
    ctx.set_line_width(0.9)
    ctx.stroke()
    _shine(ctx, -10, 22, 3, 6, 0.3, 0.5)


def _microphone(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    ctx.move_to(-9, -16)
    ctx.line_to(9, -16)
    ctx.line_to(6, 48)
    ctx.curve_to(4, 52, -4, 52, -6, 48)
    ctx.close_path()
    _ink(ctx, _hlin(-9, 9, lighten(c, 0.35), mul(c, 0.8)), lw)
    rrect(ctx, -11, -20, 22, 8, 3)
    _ink(ctx, hx("#d9b84a"), lw * 0.8)
    grille = hx("#c9ced9")
    ctx.arc(0, -34, 17, 0, 2 * math.pi)
    _ink(ctx, body_grad(-5, -40, 18, grille), lw)
    ctx.save()
    ctx.arc(0, -34, 16, 0, 2 * math.pi)
    ctx.clip()
    for i in range(-4, 5):
        ctx.move_to(i * 5 - 20, -54)
        ctx.line_to(i * 5 + 20, -14)
        ctx.move_to(i * 5 + 20, -54)
        ctx.line_to(i * 5 - 20, -14)
    ctx.set_source_rgba(*mul(grille, 0.6), 0.6)
    ctx.set_line_width(1.2)
    ctx.stroke()
    ctx.restore()
    _shine(ctx, -7, -41, 4, 2.6)
    k = 0.5 + 0.5 * math.sin(p.t * 6)
    ctx.arc(0, 8, 2.6, 0, 2 * math.pi)
    ctx.set_source_rgb(*mix((0.5, 0.1, 0.1), (1.0, 0.25, 0.3), k))
    ctx.fill()


def _umbrella(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    ctx.move_to(0, -30)
    ctx.line_to(0, 36)
    ctx.arc_negative(-8, 36, 8, 0, math.pi)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(5 + 2 * lw)
    ctx.stroke()
    ctx.move_to(0, -30)
    ctx.line_to(0, 36)
    ctx.arc_negative(-8, 36, 8, 0, math.pi)
    ctx.set_source_rgb(*hx("#8a5a3c"))
    ctx.set_line_width(5)
    ctx.stroke()
    n = 6
    r = 58

    def canopy() -> None:
        ctx.move_to(-r, -8)
        ctx.curve_to(-r, -48, r, -48, r, -8)
        for i in range(n, 0, -1):
            xa = -r + 2 * r * i / n
            xb = -r + 2 * r * (i - 1) / n
            ctx.curve_to(xa - (xa - xb) * 0.2, -16, xb + (xa - xb) * 0.2, -16, xb, -8)
        ctx.close_path()

    canopy()
    _ink(ctx, c, lw)
    ctx.save()
    canopy()
    ctx.clip()
    for i in range(n):
        if i % 2:
            xa = -r + 2 * r * i / n
            xb = -r + 2 * r * (i + 1) / n
            ctx.move_to(0, -44)
            ctx.line_to(xa, -6)
            ctx.line_to(xb, -6)
            ctx.close_path()
    ctx.set_source_rgba(1, 1, 1, 0.85)
    ctx.fill()
    g = _lin(-44, -6, (1, 1, 1), (0, 0, 0))
    ctx.set_source(g)
    ctx.paint_with_alpha(0.12)
    ctx.restore()
    canopy()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(lw)
    ctx.stroke()
    ctx.arc(0, -46, 4, 0, 2 * math.pi)
    _ink(ctx, mul(c, 0.8), lw * 0.7)


def _car(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    bob = 1.2 * math.sin(p.t * 9)
    # выхлоп
    for i in range(3):
        ph = (p.t * 1.2 + i / 3) % 1.0
        ctx.arc(-98 - ph * 30, 22 - ph * 12, 4 + ph * 9, 0, 2 * math.pi)
        ctx.set_source_rgba(0.85, 0.85, 0.9, 0.6 * (1 - ph))
        ctx.fill()
    ctx.save()
    ctx.translate(0, bob)

    def body() -> None:
        ctx.move_to(-92, 26)
        ctx.line_to(-92, 4)
        ctx.curve_to(-92, -6, -84, -10, -70, -12)
        ctx.line_to(-46, -14)
        ctx.curve_to(-36, -40, -24, -44, 0, -44)
        ctx.curve_to(26, -44, 36, -40, 48, -14)
        ctx.line_to(76, -10)
        ctx.curve_to(90, -8, 94, 0, 94, 10)
        ctx.line_to(94, 26)
        ctx.close_path()

    body()
    _ink(ctx, _lin(-44, 26, lighten(c, 0.2), mul(c, 0.82)), lw)
    _shade(ctx, body, c, 8, 6)
    glass = hx("#bfe9ff")
    for xa, xb in ((-38, -4), (4, 40)):
        ctx.move_to(xa, -14)
        ctx.curve_to(xa + (6 if xa < 0 else 0), -34, xb - 10, -36, xb - (8 if xb > 0 else 0), -36)
        ctx.line_to(xb, -36)
        ctx.curve_to(xb + (4 if xb > 0 else 0), -30, xb + (6 if xb > 0 else 0), -20, xb + (8 if xb > 0 else 0), -14)
        ctx.close_path()
        _ink(ctx, _lin(-36, -14, glass, mul(glass, 0.85)), lw * 0.8)
    ctx.move_to(-28, -30)
    ctx.line_to(-20, -20)
    ctx.set_source_rgba(1, 1, 1, 0.8)
    ctx.set_line_width(3)
    ctx.stroke()
    ellipse(ctx, 86, 0, 7, 5)
    _ink(ctx, hx("#fff3a0"), lw * 0.7)
    rrect(ctx, -94, 2, 8, 8, 2)
    _ink(ctx, hx("#ff3b3b"), lw * 0.7)
    rrect(ctx, -8, -6, 14, 4, 2)
    ctx.set_source_rgba(*INK, 0.7)
    ctx.fill()
    ctx.restore()
    spin = p.t * 6.0
    for wx in (-56, 56):
        ctx.arc(wx, 28, 19, 0, 2 * math.pi)
        _ink(ctx, hx("#2b2840"), lw)
        ctx.arc(wx, 28, 9, 0, 2 * math.pi)
        _ink(ctx, hx("#c9ced9"), lw * 0.7)
        for k in range(4):
            a = spin + k * math.pi / 2
            ctx.move_to(wx, 28)
            ctx.line_to(wx + math.cos(a) * 9, 28 + math.sin(a) * 9)
        ctx.set_source_rgb(*mul(hx("#c9ced9"), 0.6))
        ctx.set_line_width(2)
        ctx.stroke()


def _house(ctx: cairo.Context, p: _P) -> None:
    c = p.col
    lw = p.lw
    roof = hx("#d9534f") if not p.custom else mul(c, 0.6)
    # дым из трубы
    for i in range(4):
        ph = (p.t * 0.4 + i / 4) % 1.0
        ctx.arc(26 + ph * 10 + 2 * math.sin(p.t + i), -52 - ph * 30, 4 + ph * 8, 0, 2 * math.pi)
        ctx.set_source_rgba(0.9, 0.9, 0.95, 0.75 * (1 - ph))
        ctx.fill()
    rrect(ctx, 20, -50, 12, 22, 2)
    _ink(ctx, hx("#a35a4a"), lw)

    def walls() -> None:
        ctx.rectangle(-40, -14, 80, 64)

    walls()
    _ink(ctx, _lin(-14, 50, lighten(c, 0.12), mul(c, 0.85)), lw)
    _shade(ctx, walls, c)
    ctx.move_to(-50, -10)
    ctx.line_to(0, -48)
    ctx.line_to(50, -10)
    ctx.close_path()
    _ink(ctx, _lin(-48, -10, lighten(roof, 0.15), mul(roof, 0.85)), lw)
    rrect(ctx, -10, 14, 22, 36, 4)
    _ink(ctx, hx("#8a5a3c"), lw)
    ctx.arc(7, 32, 2, 0, 2 * math.pi)
    ctx.set_source_rgb(*hx("#ffd23f"))
    ctx.fill()
    glow = 0.5 + 0.5 * math.sin(p.t * 1.7)
    for wx in (-30, 20):
        rrect(ctx, wx, 0, 14, 14, 2)
        _ink(ctx, mix(hx("#ffe28a"), hx("#fff6c8"), glow), lw * 0.8)
        ctx.move_to(wx + 7, 0)
        ctx.line_to(wx + 7, 14)
        ctx.move_to(wx, 7)
        ctx.line_to(wx + 14, 7)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(lw * 0.6)
        ctx.stroke()
    ctx.arc(0, -26, 7, 0, 2 * math.pi)
    _ink(ctx, hx("#bfe9ff"), lw * 0.8)
    if not p.custom:
        star(ctx, 0, -26, 4, 5, 0.45)
        ctx.set_source_rgb(*hx("#ffd23f"))
        ctx.fill()


DRAW: dict[str, Callable[[cairo.Context, _P], None]] = {
    "table": _table, "chair": _chair, "sign": _sign, "tree": _tree, "bush": _bush, "flower": _flower, "ball": _ball,
    "book": _book, "phone": _phone, "pizza": _pizza, "ice_cream": _ice_cream, "cup": _cup, "guitar": _guitar,
    "microphone": _microphone, "umbrella": _umbrella, "car": _car, "house": _house,
}
