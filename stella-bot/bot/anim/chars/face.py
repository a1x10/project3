"""Лицо персонажа: глаза (белок, радужка с градиентом, два блика, веко, ресницы), брови, нос, рот, румянец и все
16 эмоций. draw_face рисует лицо в круге радиуса r — тем же кодом пользуются 2D-головы и 3D-игрушки (там лицо —
«наклейка» на голову), поэтому эмоции, моргание и движение губ одинаковы у всех.

Лицо рассчитано на голову радиуса 62 единицы и масштабируется под r. Поворот yaw (−1..1) сдвигает черты на
yaw·0.32·r, дальний глаз уменьшается до 25 % — дешёвый и сильный эффект объёма.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import cairocffi as cairo

from ..draw import ellipse, fill_ink, heart, rrect, set_source, sparkle, star
from ..ease import clamp, lerp
from ..model import RGB, Pose
from ..palette import INK, hx, lighten, mix, mul
from .look import Look

FACE_R = 62.0  # радиус головы, под который нарисовано лицо
MOUTH_RED = hx("#7a1f2b")
TONGUE = hx("#ff7b8a")
LID_SHADOW = (0.55, 0.6, 0.8)


@dataclass(frozen=True)
class EmoFace:
    """Что эмоция делает с лицом (design_wow §c.4)."""

    eyes: str = "normal"  # normal | arcs (^ ^) | heart | spiral | sparkle
    lid: float = 0.0  # верхнее веко прикрыто 0..0.7
    lid_tilt: float = 0.0  # + злой наклон (к носу вниз), − грустный (наружу вниз)
    iris: float = 1.0  # размер радужки (маленькие зрачки — испуг, удивление)
    wide: float = 1.0  # распахнутые глаза
    brow: tuple[float, float] = (0.0, -2.0)  # угол (+ внутренние концы вниз) и подъём (− выше)
    brow_mode: str = "both"  # both | smug (одна бровь выше) | think
    mouth: str = "line"  # line smile open_smile laugh smirk frown wobbly grimace zigzag o yawn wavy pursed proud
    blush: float = 0.35
    hatch: bool = False  # штрихи румянца (любовь, смущение)
    tears: bool = False
    tint: tuple[float, float, float, float] | None = None  # оттенок лица (злость — красный, испуг — голубой)
    gaze: tuple[float, float] = (0.0, 0.0)  # куда смотрят глаза сами по себе


EMOTIONS: dict[str, EmoFace] = {
    "neutral": EmoFace(),
    "happy": EmoFace(brow=(0.0, -3.0), mouth="smile", blush=0.75),
    "excited": EmoFace(eyes="sparkle", brow=(0.0, -6.0), mouth="open_smile", blush=0.75, wide=1.06),
    "laugh": EmoFace(eyes="arcs", brow=(0.0, -4.0), mouth="laugh", blush=0.8),
    "love": EmoFace(eyes="heart", brow=(-0.1, -4.0), mouth="smile", blush=0.8, hatch=True),
    "smug": EmoFace(lid=0.35, brow=(0.12, 0.0), brow_mode="smug", mouth="smirk", blush=0.6, gaze=(0.25, 0.0)),
    "sad": EmoFace(lid=0.12, lid_tilt=-0.3, brow=(-0.4, 0.0), mouth="frown", blush=0.3, gaze=(0.0, 0.55)),
    "cry": EmoFace(lid=0.08, lid_tilt=-0.3, brow=(-0.45, 0.0), mouth="wobbly", blush=0.45, tears=True,
                   gaze=(0.0, 0.2)),
    "angry": EmoFace(lid=0.42, lid_tilt=0.55, brow=(0.5, 3.0), mouth="zigzag", blush=0.0,
                     tint=(1.0, 0.25, 0.2, 0.22)),
    "surprised": EmoFace(iris=0.55, wide=1.1, brow=(0.0, -10.0), mouth="o", blush=0.35),
    "scared": EmoFace(iris=0.5, wide=1.1, brow=(-0.35, -8.0), mouth="grimace", blush=0.0,
                      tint=(0.45, 0.6, 1.0, 0.28)),
    "sleepy": EmoFace(lid=0.62, brow=(0.0, 0.0), mouth="yawn", blush=0.25),
    "dizzy": EmoFace(eyes="spiral", brow=(-0.2, -3.0), mouth="wavy", blush=0.3),
    "thinking": EmoFace(brow=(0.0, -2.0), brow_mode="think", mouth="pursed", blush=0.3, gaze=(0.55, -0.65)),
    "embarrassed": EmoFace(lid=0.18, brow=(-0.22, -2.0), mouth="wavy", blush=1.0, hatch=True, gaze=(-0.6, 0.35)),
    "proud": EmoFace(lid=0.3, brow=(0.1, -4.0), mouth="proud", blush=0.5, gaze=(0.1, -0.1)),
}
_NEUTRAL = EMOTIONS["neutral"]


def blend_emotion(name: str, w: float) -> EmoFace:
    """Эмоция с силой w (0 — нейтральное лицо): числа плавно, режимы глаз и рта переключаются на w ≥ 0.35."""
    e = EMOTIONS.get(name, _NEUTRAL)
    w = clamp(w)
    if w >= 0.999:
        return e
    n = _NEUTRAL
    on = w >= 0.35
    tint = None
    if e.tint is not None:
        tint = (e.tint[0], e.tint[1], e.tint[2], e.tint[3] * w)
    return EmoFace(
        eyes=e.eyes if on else n.eyes, lid=lerp(n.lid, e.lid, w), lid_tilt=lerp(n.lid_tilt, e.lid_tilt, w),
        iris=lerp(n.iris, e.iris, w), wide=lerp(n.wide, e.wide, w),
        brow=(lerp(n.brow[0], e.brow[0], w), lerp(n.brow[1], e.brow[1], w)),
        brow_mode=e.brow_mode if on else n.brow_mode, mouth=e.mouth if on else n.mouth,
        blush=lerp(n.blush, e.blush, w), hatch=e.hatch and on, tears=e.tears and w > 0.5, tint=tint,
        gaze=(lerp(n.gaze[0], e.gaze[0], w), lerp(n.gaze[1], e.gaze[1], w)),
    )


@dataclass(frozen=True)
class Species:
    """Раскладка лица для базы (в единицах головы 62)."""

    eye_y: float = -2.0
    spacing: float = 27.0
    eye: float = 1.0
    mouth_y: float = 36.0  # от eye_y
    nose: str = "human"  # human | cat | dog | fox | bunny | bear | dragon | none | beak | carrot
    mouth_w: float = 1.0
    brows: bool = True
    whiskers: bool = False
    fangs: bool = False
    teeth: bool = False  # заячьи зубки
    eyes3: bool = False  # три глаза (инопланетянин)


SPECIES: dict[str, Species] = {
    "human": Species(),
    "cat": Species(eye_y=-6.0, spacing=29.0, eye=1.08, mouth_y=32.0, nose="cat", whiskers=True),
    "dog": Species(eye_y=-10.0, spacing=29.0, eye=1.04, mouth_y=40.0, nose="dog"),
    "fox": Species(eye_y=-8.0, spacing=29.0, eye=1.0, mouth_y=34.0, nose="fox", whiskers=True),
    "bunny": Species(eye_y=-6.0, spacing=29.0, eye=1.1, mouth_y=31.0, nose="bunny", teeth=True),
    "bear": Species(eye_y=-10.0, spacing=29.0, eye=0.95, mouth_y=40.0, nose="bear"),
    "dragon": Species(eye_y=-8.0, spacing=29.0, eye=1.05, mouth_y=36.0, nose="dragon", fangs=True),
    "monster": Species(eye_y=-4.0, spacing=28.0, eye=1.22, mouth_y=38.0, nose="none", fangs=True, mouth_w=1.2),
    "alien": Species(eye_y=4.0, spacing=28.0, eye=0.9, mouth_y=32.0, nose="none", eyes3=True),
    "ghost": Species(eye_y=-4.0, spacing=26.0, eye=1.08, mouth_y=32.0, nose="none"),
    "penguin3d": Species(eye_y=-6.0, spacing=26.0, eye=1.0, mouth_y=34.0, nose="beak", brows=True),
    "snowman3d": Species(eye_y=-8.0, spacing=24.0, eye=0.82, mouth_y=34.0, nose="carrot"),
}


def species_of(look: Look) -> Species:
    if look.base in SPECIES:
        return SPECIES[look.base]
    return SPECIES["human"]


def _brow_color(look: Look) -> RGB:
    if look.kind == "human":
        return mul(look.hair_color, 0.6) if look.hair != "none" else mul(look.skin, 0.45)
    if look.base in ("ghost",):
        return mix(INK, look.accent, 0.35)
    return mix(mul(look.color, 0.45), INK, 0.45)


def _stroke(ctx: cairo.Context, color, width: float, alpha: float = 1.0) -> None:
    set_source(ctx, color, alpha)
    ctx.set_line_width(width)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


# ---------- глаза ----------
def _eye(ctx: cairo.Context, x: float, y: float, sw: float, sh: float, look: Look, pose: Pose, side: int,
         ef: EmoFace, gaze: tuple[float, float]) -> None:
    """Большой мультяшный глаз. side: −1 левый, +1 правый (на экране, до зеркала)."""
    w, h = 15.0 * sw * ef.wide, 20.0 * sh * ef.wide
    t = pose.t
    if ef.eyes == "arcs":  # ^ ^ — смех, счастье
        ctx.move_to(x - w, y + 3)
        ctx.curve_to(x - w * 0.6, y - h * 0.85, x + w * 0.6, y - h * 0.85, x + w, y + 3)
        _stroke(ctx, INK, 5.5)
        return
    if ef.eyes == "heart":
        k = 1.0 + 0.07 * math.sin(t * 9.0)
        s = w * 1.25 * k
        heart(ctx, x, y + s * 0.15, s)
        g = cairo.LinearGradient(0, y - s, 0, y + s * 0.5)
        g.add_color_stop_rgb(0, 1.0, 0.45, 0.62)
        g.add_color_stop_rgb(1, 0.88, 0.07, 0.32)
        fill_ink(ctx, g, 3.2)
        ellipse(ctx, x - s * 0.42, y - s * 0.22, s * 0.2, s * 0.13, -0.6)
        ctx.set_source_rgba(1, 1, 1, 0.9)
        ctx.fill()
        return
    blink = clamp(pose.blink)
    lid = max(ef.lid, blink)
    tilt = ef.lid_tilt * (1.0 - blink)
    if lid > 0.9:  # закрыт: дуга вниз
        ctx.move_to(x - w, y + 1)
        ctx.curve_to(x - w * 0.5, y + h * 0.5, x + w * 0.5, y + h * 0.5, x + w, y + 1)
        _stroke(ctx, INK, 5.0)
        if look.lashes:
            ox = x + side * w * 0.95
            ctx.move_to(ox, y + 2)
            ctx.line_to(ox + side * 7, y - 3)
            _stroke(ctx, INK, 3.2)
        return
    lx, ly = gaze
    ctx.save()
    ellipse(ctx, x, y, w, h)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill_preserve()
    ctx.clip()
    # мягкая тень века сверху на белке
    ellipse(ctx, x, y - h * 0.92, w * 1.25, h * 0.55)
    ctx.set_source_rgba(*LID_SHADOW, 0.35)
    ctx.fill()
    ix, iy = x + lx * w * 0.38, y + 2 + ly * h * 0.3
    ir = w * 0.78 * ef.iris
    if ef.eyes == "spiral":
        ctx.move_to(x, y)
        for k in range(1, 26):
            a = k * 0.55 - t * 7.0
            rr = k * 0.62 * sw
            ctx.line_to(x + rr * math.cos(a), y + rr * math.sin(a) * 1.15)
        _stroke(ctx, INK, 2.8)
    else:
        eye = look.eyes
        g = cairo.LinearGradient(ix, iy - ir * 1.2, ix, iy + ir * 1.2)
        g.add_color_stop_rgb(0, *mul(eye, 0.45))
        g.add_color_stop_rgb(0.55, *eye)
        g.add_color_stop_rgb(1, *lighten(eye, 0.55))
        ellipse(ctx, ix, iy, ir, ir * 1.22)
        ctx.set_source(g)
        ctx.fill()
        ellipse(ctx, ix, iy + 1, ir * 0.5, ir * 0.62)
        ctx.set_source_rgb(0.06, 0.03, 0.1)
        ctx.fill()
        # блики: крупный сверху-слева, маленький снизу-справа (как в аниме)
        hk = 1.0 if ef.iris >= 0.8 else 1.25
        ellipse(ctx, ix - ir * 0.36, iy - ir * 0.5, ir * 0.38 * hk, ir * 0.31 * hk, -0.4)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        ellipse(ctx, ix + ir * 0.4, iy + ir * 0.52, ir * 0.16 * hk, ir * 0.16 * hk)
        ctx.fill()
        if ef.eyes == "sparkle":
            tw = 0.85 + 0.25 * math.sin(t * 10.0 + side)
            sparkle(ctx, ix + ir * 0.22, iy - ir * 0.05, ir * 0.62 * tw)
            ctx.set_source_rgb(1, 1, 1)
            ctx.fill()
    if ef.tears:  # слёзы стоят в глазах: голубая «лужица» снизу и блик
        ellipse(ctx, x, y + h * 0.95, w * 1.2, h * 0.55)
        ctx.set_source_rgba(0.55, 0.82, 1.0, 0.75)
        ctx.fill()
        ctx.move_to(x - w * 0.6, y + h * 0.5)
        ctx.curve_to(x - w * 0.2, y + h * 0.42, x + w * 0.2, y + h * 0.42, x + w * 0.6, y + h * 0.5)
        _stroke(ctx, (1, 1, 1), 2.2, 0.85)
    # веко: всё выше линии века — цвета кожи
    lid_y = y - h + 2.0 * h * lid
    di = tilt * h * 0.6  # внутренний конец (к носу) ниже при злости
    x_in, x_out = x - side * w * 1.3, x + side * w * 1.3
    y_in, y_out = lid_y + di, lid_y - di
    if lid > 0.01 or abs(tilt) > 0.01:
        ctx.move_to(x_in, y_in)
        ctx.line_to(x_out, y_out)
        ctx.line_to(x_out, y - h * 2)
        ctx.line_to(x_in, y - h * 2)
        ctx.close_path()
        set_source(ctx, mul(look.skin, 0.93))
        ctx.fill()
    ctx.restore()
    # контур белка (ниже века) и толстое верхнее веко
    ctx.save()
    if lid > 0.01 or abs(tilt) > 0.01:
        ctx.move_to(x_in, y_in)
        ctx.line_to(x_out, y_out)
        ctx.line_to(x_out, y + h * 2)
        ctx.line_to(x_in, y + h * 2)
        ctx.close_path()
        ctx.clip()
    ellipse(ctx, x, y, w, h)
    _stroke(ctx, INK, 2.6)
    ctx.restore()
    if lid > 0.01 or abs(tilt) > 0.01:
        ctx.save()
        ellipse(ctx, x, y, w + 3.5, h + 3.5)
        ctx.clip()
        mx, my = (x_in + x_out) / 2, (y_in + y_out) / 2 + 2.0
        ctx.move_to(x_in, y_in)
        ctx.curve_to(mx, my, mx, my, x_out, y_out)
        _stroke(ctx, INK, 5.5)
        ctx.restore()
        top_x, top_y = x + side * w * 0.95, y_out + (y_in - y_out) * 0.1
    else:
        ctx.move_to(x - w * 1.05, y - h * 0.55 + 2)
        ctx.curve_to(x - w * 0.6, y - h - 3, x + w * 0.6, y - h - 3, x + w * 1.05, y - h * 0.55 + 2)
        _stroke(ctx, INK, 5.5)
        top_x, top_y = x + side * w * 0.95, y - h * 0.55
    if look.lashes:
        for k in range(2):
            ctx.move_to(top_x, top_y + k * 6)
            ctx.line_to(top_x + side * 8, top_y - 6 + k * 6)
        _stroke(ctx, INK, 3.4)


# ---------- рот ----------
def _mouth(ctx: cairo.Context, look: Look, pose: Pose, ef: EmoFace, x: float, y: float, wk: float,
           sp: Species) -> None:
    o = clamp(pose.mouth_open)
    shape = pose.mouth_shape if pose.mouth_shape in ("a", "o", "e", "m") else "m"
    kind = ef.mouth
    talking = o > 0.05
    if kind == "laugh":
        o, shape = max(o, 0.85), "a"
    elif kind == "open_smile":
        o, shape = max(o, 0.55), "a" if not talking else shape
    elif kind == "o":
        o, shape = max(o, 0.6), "o"
    elif kind == "yawn":
        o, shape = max(o, 0.35), "o"
    elif kind == "wobbly":
        o = max(o, 0.62)
    if kind == "grimace" and not talking:
        _grimace(ctx, x, y, 13.0 * wk)
        return
    if talking or kind in ("laugh", "open_smile", "o", "yawn", "wobbly"):
        _open_mouth(ctx, look, pose, kind, o, shape, x, y, wk, sp)
        return
    w = 13.0 * wk
    if sp.nose == "dog" and kind in ("smile", "proud"):  # счастливый пёс показывает язык
        ctx.move_to(x - 5.5, y + 4)
        ctx.curve_to(x - 6.5, y + 15, x + 6.5, y + 15, x + 5.5, y + 4)
        ctx.close_path()
        fill_ink(ctx, TONGUE, 2.4)
        ctx.move_to(x, y + 5)
        ctx.line_to(x, y + 9)
        _stroke(ctx, mul(TONGUE, 0.7), 1.4)
    if kind == "smile":
        ctx.move_to(x - w, y - 2)
        ctx.curve_to(x - w * 0.45, y + 9, x + w * 0.45, y + 9, x + w, y - 2)
    elif kind == "proud":
        ctx.move_to(x - w * 1.05, y - 1)
        ctx.curve_to(x - w * 0.4, y + 8, x + w * 0.5, y + 8, x + w * 1.1, y - 5)
    elif kind == "frown":
        ctx.move_to(x - w * 0.8, y + 6)
        ctx.curve_to(x - w * 0.3, y - 2, x + w * 0.3, y - 2, x + w * 0.8, y + 6)
    elif kind == "smirk":
        ctx.move_to(x - w * 0.75, y + 2)
        ctx.curve_to(x - w * 0.1, y + 6, x + w * 0.6, y + 4, x + w * 1.0, y - 4)
    elif kind == "zigzag":
        ctx.move_to(x - w * 0.95, y + 4)
        ctx.line_to(x - w * 0.32, y)
        ctx.line_to(x + w * 0.32, y + 4)
        ctx.line_to(x + w * 0.95, y)
    elif kind == "wavy":
        ctx.move_to(x - w * 0.75, y + 2)
        for i in range(4):
            sgn = -1 if i % 2 == 0 else 1
            ctx.rel_curve_to(w * 0.18, sgn * 4.5, w * 0.2, sgn * 4.5, w * 0.375, 0)
    elif kind == "pursed":
        ctx.move_to(x + w * 0.05, y + 1)
        ctx.curve_to(x + w * 0.25, y - 3, x + w * 0.55, y - 2, x + w * 0.6, y + 2)
    elif sp.nose in ("cat", "fox"):  # ω
        ctx.move_to(x - w * 0.9, y - 3)
        ctx.curve_to(x - w * 0.62, y + 6, x - w * 0.08, y + 6, x, y - 2)
        ctx.curve_to(x + w * 0.08, y + 6, x + w * 0.62, y + 6, x + w * 0.9, y - 3)
    else:  # нейтральный — короткая чуть улыбающаяся линия
        ctx.move_to(x - w * 0.55, y + 1)
        ctx.curve_to(x - w * 0.2, y + 3.5, x + w * 0.2, y + 3.5, x + w * 0.55, y + 1)
    _stroke(ctx, INK, 4.0)
    if sp.fangs and kind in ("smile", "proud", "smirk", "line", "zigzag"):
        for s in (-1, 1):
            fx0 = x + s * w * 0.45
            ctx.move_to(fx0 - 3, y + 3)
            ctx.line_to(fx0, y + 10)
            ctx.line_to(fx0 + 3, y + 3)
            ctx.close_path()
            fill_ink(ctx, (1, 1, 1), 2.0)
    if sp.teeth:
        _buck_teeth(ctx, x, y + 3)


def _grimace(ctx: cairo.Context, x: float, y: float, w: float) -> None:
    """Испуганный оскал: сжатые зубы, уголки чуть вниз."""
    ctx.move_to(x - w, y + 4)
    ctx.curve_to(x - w * 0.5, y - 2, x + w * 0.5, y - 2, x + w, y + 4)
    ctx.curve_to(x + w * 0.6, y + 13, x - w * 0.6, y + 13, x - w, y + 4)
    ctx.close_path()
    fill_ink(ctx, (1, 1, 1), 3.4)
    ctx.move_to(x - w * 0.92, y + 4.5)
    ctx.curve_to(x - w * 0.4, y + 3, x + w * 0.4, y + 3, x + w * 0.92, y + 4.5)
    for i in (-2, -1, 0, 1, 2):
        ctx.move_to(x + i * w * 0.33, y + 0.5)
        ctx.line_to(x + i * w * 0.33, y + 9)
    _stroke(ctx, INK, 1.6)


def _buck_teeth(ctx: cairo.Context, x: float, y: float) -> None:
    rrect(ctx, x - 6.5, y - 1, 13, 9, 2.5)
    fill_ink(ctx, (1, 1, 1), 2.4)
    ctx.move_to(x, y)
    ctx.line_to(x, y + 7)
    _stroke(ctx, INK, 1.6)


def _open_mouth(ctx: cairo.Context, look: Look, pose: Pose, kind: str, o: float, shape: str, x: float, y: float,
                wk: float, sp: Species) -> None:
    w = {"a": 15.0, "o": 9.0, "e": 17.0, "m": 12.0}[shape] * wk
    h = 4.0 + 18.0 * o
    if kind == "laugh":
        w *= 1.35
    sad = kind in ("frown", "wobbly", "zigzag")
    happy = kind in ("smile", "open_smile", "laugh", "proud")
    if shape == "o":
        def path() -> None:
            ellipse(ctx, x, y + h * 0.35, w, h * 0.72)
    elif kind == "wobbly":  # плачущий/испуганный рот: уголки вниз, верхняя губа дрожит
        def path() -> None:
            ctx.move_to(x - w, y + h * 0.55)
            n = 4
            for i in range(1, n + 1):
                xx = x - w + 2 * w * i / n
                ym = y + h * 0.55 - h * 0.5 * math.sin(math.pi * i / n)
                ctx.curve_to(xx - w / n * 0.7, ym - 3.5, xx - w / n * 0.3, ym + 3.5, xx, ym)
            ctx.curve_to(x + w * 0.85, y + h * 1.15, x - w * 0.85, y + h * 1.15, x - w, y + h * 0.55)
            ctx.close_path()
    else:
        top = -2.0 if happy else (h * 0.25 if sad else 0.0)
        corner = -3.0 if happy else (h * 0.45 if sad else 0.0)
        bot = h * (1.15 if happy else 1.0)

        def path() -> None:
            ctx.move_to(x - w, y + corner)
            ctx.curve_to(x - w * 0.5, y + top, x + w * 0.5, y + top, x + w, y + corner)
            ctx.curve_to(x + w * 0.85, y + bot, x - w * 0.85, y + bot, x - w, y + corner)
            ctx.close_path()
    path()
    ctx.set_source_rgb(*MOUTH_RED)
    ctx.fill_preserve()
    ctx.save()
    ctx.clip()  # внутри рта: язык снизу, зубки сверху
    ellipse(ctx, x + 2, y + h * 1.12, w * 0.62, h * 0.42 + 2)
    ctx.set_source_rgb(*TONGUE)
    ctx.fill()
    if (shape in ("a", "e") and o > 0.3) or kind == "zigzag":
        ctx.rectangle(x - w, y - 8, w * 2, 8 + h * 0.14 + 1.5)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
    ctx.restore()
    path()
    _stroke(ctx, INK, 3.6)
    if sp.fangs and o > 0.15:
        for s in (-1, 1):
            fx0 = x + s * w * 0.55
            ctx.move_to(fx0 - 3, y - 0.5)
            ctx.line_to(fx0, y + 6)
            ctx.line_to(fx0 + 3, y - 0.5)
            ctx.close_path()
            fill_ink(ctx, (1, 1, 1), 1.8)
    if sp.teeth and o < 0.5:
        _buck_teeth(ctx, x, y - 1)


# ---------- нос, усы, румянец, слёзы ----------
def _nose(ctx: cairo.Context, look: Look, sp: Species, x: float, y: float, yaw: float) -> None:
    kind = sp.nose
    if kind == "human":
        ctx.move_to(x + 1 + yaw * 2, y + 17)
        ctx.curve_to(x + 4 + yaw * 3, y + 21, x + 3 + yaw * 3, y + 24, x - 1, y + 24)
        _stroke(ctx, mul(look.skin, 0.55), 2.6)
    elif kind == "cat":
        ctx.move_to(x - 5.5, y + 19)
        ctx.curve_to(x - 2, y + 17.5, x + 2, y + 17.5, x + 5.5, y + 19)
        ctx.line_to(x, y + 25)
        ctx.close_path()
        fill_ink(ctx, hx("#ff8fab"), 2.2)
    elif kind in ("dog", "bear"):
        big = 1.0 if kind == "dog" else 0.85
        ellipse(ctx, x, y + 20, 10.5 * big, 7.5 * big)
        g = cairo.RadialGradient(x - 3, y + 17, 1, x, y + 20, 11)
        g.add_color_stop_rgb(0, 0.35, 0.28, 0.4)
        g.add_color_stop_rgb(1, 0.1, 0.07, 0.13)
        fill_ink(ctx, g, 2.4)
        ellipse(ctx, x - 3.5 * big, y + 17.5, 3.6 * big, 2.2 * big, -0.3)
        ctx.set_source_rgba(1, 1, 1, 0.75)
        ctx.fill()
        ctx.move_to(x, y + 27)
        ctx.line_to(x, y + 31)
        _stroke(ctx, INK, 2.6)
    elif kind == "fox":
        ellipse(ctx, x, y + 20, 6.5, 4.6)
        fill_ink(ctx, (0.12, 0.08, 0.12), 2.0)
        ellipse(ctx, x - 2, y + 18.6, 2.0, 1.2)
        ctx.set_source_rgba(1, 1, 1, 0.7)
        ctx.fill()
    elif kind == "bunny":
        ctx.move_to(x - 4.5, y + 17)
        ctx.curve_to(x - 1.5, y + 15.5, x + 1.5, y + 15.5, x + 4.5, y + 17)
        ctx.line_to(x, y + 21.5)
        ctx.close_path()
        fill_ink(ctx, hx("#ff8fab"), 2.0)
        ctx.move_to(x, y + 21.5)
        ctx.line_to(x, y + 25)
        _stroke(ctx, INK, 2.0)
    elif kind == "dragon":
        for s in (-1, 1):
            ellipse(ctx, x + s * 8, y + 20, 3.0, 2.2, s * 0.4)
        ctx.set_source_rgb(*INK)
        ctx.fill()
    elif kind == "carrot":
        d = 1 if yaw >= 0 else -1
        ctx.move_to(x - d * 3, y + 10)
        ctx.curve_to(x + d * 14, y + 13, x + d * 30, y + 17, x + d * (34 + 6 * abs(yaw)), y + 19)
        ctx.curve_to(x + d * 22, y + 22, x + d * 8, y + 25, x - d * 3, y + 24)
        ctx.close_path()
        g = cairo.LinearGradient(0, y + 10, 0, y + 25)
        g.add_color_stop_rgb(0, *lighten(look.accent, 0.3))
        g.add_color_stop_rgb(1, *mul(look.accent, 0.85))
        fill_ink(ctx, g, 2.6)
        for k in (8, 16):
            ctx.move_to(x + d * k, y + 13 + k * 0.1)
            ctx.line_to(x + d * (k + 2), y + 17 + k * 0.1)
        _stroke(ctx, mul(look.accent, 0.6), 1.6)


def _beak(ctx: cairo.Context, look: Look, pose: Pose, x: float, y: float) -> None:
    o = clamp(pose.mouth_open)
    col = look.accent
    # нижняя половинка опускается, когда пингвин говорит
    ctx.move_to(x - 13, y + 22)
    ctx.curve_to(x - 6, y + 30 + 10 * o, x + 6, y + 30 + 10 * o, x + 13, y + 22)
    ctx.close_path()
    fill_ink(ctx, mul(col, 0.85), 2.8)
    ctx.move_to(x - 15, y + 22)
    ctx.curve_to(x - 10, y + 10, x + 10, y + 10, x + 15, y + 22)
    ctx.curve_to(x + 5, y + 25 - 2 * o, x - 5, y + 25 - 2 * o, x - 15, y + 22)
    ctx.close_path()
    g = cairo.LinearGradient(0, y + 10, 0, y + 25)
    g.add_color_stop_rgb(0, *lighten(col, 0.35))
    g.add_color_stop_rgb(1, *col)
    fill_ink(ctx, g, 2.8)
    ellipse(ctx, x - 5, y + 15, 4, 2, -0.2)
    ctx.set_source_rgba(1, 1, 1, 0.6)
    ctx.fill()


def _coal_mouth(ctx: cairo.Context, x: float, y: float, kind: str) -> None:
    curve = {"smile": 6.0, "open_smile": 7.0, "proud": 6.0, "frown": -5.0, "smirk": 3.0}.get(kind, 1.5)
    for i in range(5):
        u = (i - 2) / 2
        ellipse(ctx, x + u * 13, y + 2 + curve * (1 - u * u), 2.8, 2.8)
    ctx.set_source_rgb(0.15, 0.12, 0.18)
    ctx.fill()


def _blush(ctx: cairo.Context, x: float, y: float, amount: float, hatch: bool, kind_skin: RGB) -> None:
    if amount <= 0.02:
        return
    g = cairo.RadialGradient(x, y, 0, x, y, 15)
    g.add_color_stop_rgba(0, 1, 0.35, 0.45, 0.55 * min(1.0, amount))
    g.add_color_stop_rgba(1, 1, 0.35, 0.45, 0)
    ctx.set_source(g)
    ellipse(ctx, x, y, 16, 10)
    ctx.fill()
    if hatch:
        for k in range(3):
            ctx.move_to(x - 7 + k * 6, y + 3)
            ctx.line_to(x - 3 + k * 6, y - 4)
        _stroke(ctx, (0.85, 0.2, 0.3), 2.0, 0.8)


def _tears(ctx: cairo.Context, x: float, y: float, side: int, t: float, w: float) -> None:
    """Ручьи слёз от нижнего века вниз по щеке (полупрозрачные, с бликом) и капли."""
    x0 = x + side * w * 0.55
    wob = 2.0 * math.sin(t * 9.0 + side)
    ctx.move_to(x0 - 3.5, y + 12)
    ctx.curve_to(x0 - 5 + side * 2, y + 28, x0 + side * 4 + wob, y + 44, x0 + side * 6 + wob, y + 58)
    ctx.line_to(x0 + side * 6 + 9 + wob, y + 58)
    ctx.curve_to(x0 + side * 4 + 9 + wob, y + 44, x0 + 6 + side * 2, y + 28, x0 + 4.5, y + 12)
    ctx.close_path()
    g = cairo.LinearGradient(0, y + 10, 0, y + 60)
    g.add_color_stop_rgba(0, 0.6, 0.86, 1.0, 0.95)
    g.add_color_stop_rgba(1, 0.5, 0.8, 1.0, 0.0)
    ctx.set_source(g)
    ctx.fill()
    ctx.move_to(x0 - 1, y + 16)
    ctx.curve_to(x0 - 2, y + 26, x0 + side * 2 + wob * 0.5, y + 36, x0 + side * 3 + wob * 0.5, y + 44)
    _stroke(ctx, (1, 1, 1), 1.8, 0.6)
    # капли падают с подбородка
    for k in range(2):
        ph = (t * 1.6 + k * 0.5 + (0.25 if side > 0 else 0)) % 1.0
        dy = y + 56 + ph * 26
        r = 3.6 * (1 - ph * 0.4)
        ctx.move_to(x0 + side * 9 + 4, dy - r * 1.8)
        ctx.curve_to(x0 + side * 9 + 4 + r, dy - r * 0.2, x0 + side * 9 + 4 + r, dy + r,
                     x0 + side * 9 + 4, dy + r)
        ctx.curve_to(x0 + side * 9 + 4 - r, dy + r, x0 + side * 9 + 4 - r, dy - r * 0.2,
                     x0 + side * 9 + 4, dy - r * 1.8)
        ctx.close_path()
        ctx.set_source_rgba(0.55, 0.84, 1.0, 0.9 * (1 - ph))
        ctx.fill()


# ---------- брови ----------
def _brows(ctx: cairo.Context, look: Look, ef: EmoFace, fx: float, fy: float, spacing: float, eye_y: float,
           sizes: dict[int, float], t: float) -> None:
    ang0, lift = ef.brow
    col = _brow_color(look)
    # брови поверх тёмной чёлки — с тонкой светлой каймой цвета кожи, чтобы читались
    halo = 9.5 if look.kind == "human" and look.hair not in ("none",) else 0.0
    for s in (-1, 1):
        bx, by = fx + s * spacing, fy + eye_y - (26.5 if look.kind == "human" else 31) * sizes[s] + lift
        ang = ang0 * s
        if ef.brow_mode == "smug" and s > 0:
            ang, by = -0.28, by - 6
        elif ef.brow_mode == "think" and s > 0:
            ang, by = -0.18 + 0.05 * math.sin(t * 2.0), by - 7
        elif ef.brow_mode == "think":
            ang, by = 0.15, by + 1
        for width, c in ((halo, look.skin), (6.0, col)):
            if width <= 0:
                continue
            ctx.save()
            ctx.translate(bx, by)
            ctx.rotate(ang)
            ctx.scale(sizes[s], 1)
            ctx.move_to(-11, 2)
            ctx.curve_to(-5, -4, 5, -4, 11, 1)
            ctx.restore()
            _stroke(ctx, c, width)


# ---------- лицо робота: экран ----------
def _screen_face(ctx: cairo.Context, look: Look, pose: Pose, ef: EmoFace, emotion: str, fx: float, fy: float,
                 gaze: tuple[float, float]) -> None:
    r = FACE_R
    t = pose.t
    rrect(ctx, -r * 0.82 + fx * 0.5, -r * 0.62 + fy, r * 1.64, r * 1.2, 18)
    g = cairo.LinearGradient(0, -r * 0.6, 0, r * 0.6)
    g.add_color_stop_rgb(0, 0.08, 0.12, 0.25)
    g.add_color_stop_rgb(1, 0.02, 0.04, 0.1)
    fill_ink(ctx, g, 4.0)
    # блик стекла
    ctx.move_to(-r * 0.7 + fx * 0.5, -r * 0.5 + fy)
    ctx.line_to(-r * 0.32 + fx * 0.5, -r * 0.5 + fy)
    ctx.line_to(-r * 0.55 + fx * 0.5, -r * 0.12 + fy)
    ctx.close_path()
    ctx.set_source_rgba(1, 1, 1, 0.1)
    ctx.fill()
    glow = look.eyes
    if emotion == "angry":
        glow = (1.0, 0.32, 0.3)
    elif emotion == "love":
        glow = (1.0, 0.42, 0.68)
    elif emotion in ("sad", "cry"):
        glow = mix(look.eyes, (0.35, 0.5, 1.0), 0.5)
    bright = lighten(glow, 0.45)
    lx = gaze[0] * 5
    blink = clamp(pose.blink)
    for s in (-1, 1):
        x, y = fx + s * 24, fy - 8
        gg = cairo.RadialGradient(x, y, 0, x, y, 28)
        gg.add_color_stop_rgba(0, *glow, 0.45)
        gg.add_color_stop_rgba(1, *glow, 0)
        ctx.set_source(gg)
        ctx.arc(x, y, 28, 0, 2 * math.pi)
        ctx.fill()
        set_source(ctx, bright)
        mode = ef.eyes
        if mode == "heart":
            heart(ctx, x, y + 3, 12 * (1 + 0.06 * math.sin(t * 9)))
            ctx.fill()
        elif mode == "arcs" or emotion in ("happy", "proud") or blink > 0.85:
            ctx.move_to(x - 11, y + 5)
            ctx.curve_to(x - 6, y - 9, x + 6, y - 9, x + 11, y + 5)
            _stroke(ctx, bright, 6.0)
        elif mode == "spiral":
            ctx.move_to(x, y)
            for k in range(1, 18):
                a = k * 0.7 - t * 7
                ctx.line_to(x + k * 0.75 * math.cos(a), y + k * 0.75 * math.sin(a))
            _stroke(ctx, bright, 3.0)
        elif mode == "sparkle":
            star(ctx, x, y, 13 * (0.9 + 0.15 * math.sin(t * 10 + s)), 4, 0.35)
            ctx.fill()
        else:
            hh = 26 * (1 - max(ef.lid, blink) * 0.85)
            ww = 18 * ef.iris if ef.iris < 0.9 else 18
            if ef.iris < 0.9:
                hh = min(hh, 18)
            yy = y + 13 - hh
            if abs(ef.lid_tilt) > 0.05:
                d = ef.lid_tilt * 8 * s
                ctx.move_to(x - ww / 2 + lx, yy - d)
                ctx.line_to(x + ww / 2 + lx, yy + d)
                ctx.line_to(x + ww / 2 + lx, y + 13)
                ctx.line_to(x - ww / 2 + lx, y + 13)
                ctx.close_path()
            else:
                rrect(ctx, x - ww / 2 + lx, yy, ww, hh, min(8, hh / 2))
            ctx.fill()
    # рот-эквалайзер
    n = 7
    o = clamp(pose.mouth_open)
    mk = ef.mouth
    for i in range(n):
        u = i / (n - 1)
        if o > 0.05:
            hh = 3 + 14 * o * abs(math.sin(t * 17 + i * 1.7))
            off = 0.0
        elif mk in ("smile", "open_smile", "laugh", "proud"):
            hh, off = 3.5, 7 * math.sin(math.pi * u) - 4
        elif mk in ("frown", "wobbly"):
            hh, off = 3.5, -7 * math.sin(math.pi * u) + 3
        elif mk in ("o", "yawn"):
            hh, off = (10 if 1 <= i <= 5 else 3) * (0.8 if mk == "yawn" else 1), 0.0
        elif mk == "zigzag":
            hh, off = 3.5, (3 if i % 2 else -3)
        else:
            hh, off = 3.5, 0.0
        rrect(ctx, fx - 22 + i * 7, fy + 28 - hh / 2 + off, 4.5, hh, 2)
    set_source(ctx, lighten(glow, 0.3))
    ctx.fill()
    if ef.blush > 0.55:  # пиксельный румянец
        for s in (-1, 1):
            for k in range(3):
                rrect(ctx, fx + s * 40 - 7 + k * 5, fy + 12, 3.5, 3.5, 1)
        ctx.set_source_rgba(1, 0.45, 0.6, 0.85)
        ctx.fill()
    if ef.tears:
        for s in (-1, 1):
            ph = (t * 1.5 + (0.5 if s > 0 else 0)) % 1
            rrect(ctx, fx + s * 24 - 2, fy + 8 + ph * 20, 4, 6, 2)
        ctx.set_source_rgba(0.5, 0.8, 1, 0.9)
        ctx.fill()


# ---------- аксессуары на лице ----------
def _face_accessories(ctx: cairo.Context, look: Look, fx: float, fy: float, eye_y: float, spacing: float,
                      sizes: dict[int, float], mouth_y: float) -> None:
    acc = look.accessories
    if "glasses" in acc or "sunglasses" in acc:
        sun = "sunglasses" in acc
        for s in (-1, 1):
            ex = fx + s * spacing
            rx, ry = 19 * sizes[s], (16 if sun else 18)
            if sun:
                rrect(ctx, ex - rx, fy + eye_y - ry + 2, rx * 2, ry * 1.8, 9)
                g = cairo.LinearGradient(0, fy + eye_y - ry, 0, fy + eye_y + ry)
                g.add_color_stop_rgb(0, 0.28, 0.22, 0.42)
                g.add_color_stop_rgb(1, 0.05, 0.03, 0.1)
                fill_ink(ctx, g, 4.0)
                ctx.move_to(ex - rx * 0.5, fy + eye_y - ry * 0.4)
                ctx.line_to(ex - rx * 0.05, fy + eye_y + ry * 0.4)
                _stroke(ctx, (1, 1, 1), 3.2, 0.65)
            else:
                ellipse(ctx, ex, fy + eye_y, rx, ry)
                ctx.set_source_rgba(0.7, 0.9, 1, 0.18)
                ctx.fill_preserve()
                _stroke(ctx, INK, 4.2)
                ctx.move_to(ex - rx * 0.55, fy + eye_y - ry * 0.45)
                ctx.curve_to(ex - rx * 0.3, fy + eye_y - ry * 0.75, ex, fy + eye_y - ry * 0.8,
                             ex + rx * 0.1, fy + eye_y - ry * 0.75)
                _stroke(ctx, (1, 1, 1), 2.4, 0.7)
        ctx.move_to(fx - spacing + 18 * sizes[-1], fy + eye_y - 3)
        ctx.curve_to(fx - 4, fy + eye_y - 9, fx + 4, fy + eye_y - 9, fx + spacing - 18 * sizes[1], fy + eye_y - 3)
        _stroke(ctx, INK, 4.0)
    if "mustache" in acc:
        my = fy + eye_y + mouth_y - 9
        for s in (-1, 1):
            ctx.move_to(fx, my - 2)
            ctx.curve_to(fx + s * 10, my - 9, fx + s * 20, my - 6, fx + s * 25, my + 2)
            ctx.curve_to(fx + s * 20, my + 1, fx + s * 13, my + 6, fx, my + 3)
            ctx.close_path()
            col = look.hair_color if look.kind == "human" else mul(look.color, 0.45)
            fill_ink(ctx, col, 2.6)


# ---------- всё лицо ----------
@dataclass(frozen=True)
class _Layout:
    ef: EmoFace
    sp: Species
    gaze: tuple[float, float]
    fx: float
    fy: float
    eye_y: float
    spacing: float
    sizes: dict[int, float]


def _layout(look: Look, pose: Pose, yaw: float) -> _Layout:
    ef = blend_emotion(pose.emotion, pose.emotion_w)
    sp = species_of(look)
    lx, ly = pose.look
    gaze = (clamp(lx + ef.gaze[0], -1.0, 1.0), clamp(ly + ef.gaze[1], -1.0, 1.0))
    # голова следует за взглядом на 30 %: черты чуть сдвигаются туда же
    fx = yaw * FACE_R * 0.32 + gaze[0] * 3.5
    fy = gaze[1] * 3.0
    spacing = sp.spacing * (1 - 0.18 * abs(yaw))
    sizes = {-1: 1 - 0.25 * max(0.0, yaw), 1: 1 - 0.25 * max(0.0, -yaw)}
    return _Layout(ef, sp, gaze, fx, fy, sp.eye_y, spacing, sizes)


def draw_face(ctx: cairo.Context, look: Look, pose: Pose, cx: float, cy: float, r: float, yaw: float,
              *, over: bool = True) -> None:
    """Лицо (глаза, брови, нос, рот, румянец, слёзы, очки/усы) в круге радиуса r с центром (cx, cy).

    yaw −1..1 — поворот головы (черты смещаются, дальний глаз меньше). Эмоция — pose.emotion с силой
    pose.emotion_w; моргание pose.blink, рот pose.mouth_open/mouth_shape, взгляд pose.look.
    over=False — без бровей и очков: их 2D-голова рисует поверх чёлки (draw_face_over)."""
    if r <= 0.5:
        return
    yaw = clamp(yaw, -1.0, 1.0)
    L = _layout(look, pose, yaw)
    ef, sp, fx, fy = L.ef, L.sp, L.fx, L.fy
    ctx.save()
    ctx.translate(cx, cy)
    k = r / FACE_R
    ctx.scale(k, k)
    if look.base in ("robot", "robot3d"):
        _screen_face(ctx, look, pose, ef, pose.emotion if pose.emotion_w >= 0.35 else "neutral", fx, fy, L.gaze)
        if over:
            _face_accessories(ctx, look, fx, fy, -8, 24, {-1: 1.0, 1: 1.0}, 36)
        ctx.restore()
        return
    eye_y, spacing, sizes = L.eye_y, L.spacing, L.sizes
    squeeze = 1 - 0.1 * abs(yaw)
    # глаза
    if sp.eyes3:
        for dx, dy, s in ((-spacing, 0, 0.92), (spacing, 0, 0.92), (0, -31, 0.68)):
            side = -1 if dx < 0 else 1
            sz = s * (sizes[side] if dx else 1.0)
            _eye(ctx, fx + dx, fy + eye_y + dy, sz * squeeze * sp.eye, sz * sp.eye, look, pose, side, ef, L.gaze)
    else:
        for s in (-1, 1):
            sz = sizes[s] * sp.eye
            _eye(ctx, fx + s * spacing, fy + eye_y, sz * squeeze, sz, look, pose, s, ef, L.gaze)
    # румянец
    for s in (-1, 1):
        if sizes[s] < 0.8 and abs(yaw) > 0.7:
            continue
        _blush(ctx, fx + s * (spacing + 17) * (0.85 + 0.15 * sizes[s]), fy + eye_y + 24, ef.blush, ef.hatch,
               look.skin)
    # нос, рот
    nx = fx * 1.08
    mouth_x = fx * 1.05
    mouth_y = fy + eye_y + sp.mouth_y
    if sp.nose == "beak":
        _beak(ctx, look, pose, nx, fy + eye_y)
    else:
        _nose(ctx, look, sp, nx, fy + eye_y, yaw)
        if sp.nose == "carrot" and pose.mouth_open < 0.05 and ef.mouth not in ("laugh", "o", "yawn", "wobbly"):
            _coal_mouth(ctx, mouth_x, mouth_y, ef.mouth)
        else:
            _mouth(ctx, look, pose, ef, mouth_x, mouth_y, sp.mouth_w * (1 - 0.2 * abs(yaw)), sp)
    if sp.whiskers:
        for s in (-1, 1):
            if sizes[s] < 0.8:
                continue
            for kk in (-1, 0, 1):
                ctx.move_to(fx + s * 24, fy + eye_y + 27 + kk * 5)
                ctx.line_to(fx + s * (50 + 3 * abs(kk)), fy + eye_y + 22 + kk * 9)
        _stroke(ctx, INK, 1.8, 0.75)
    if ef.tears:
        for s in (-1, 1):
            _tears(ctx, fx + s * spacing, fy + eye_y, s, pose.t, 15 * sizes[s])
    if over:
        _over(ctx, look, pose, L)
    ctx.restore()


def _over(ctx: cairo.Context, look: Look, pose: Pose, L: _Layout) -> None:
    if L.sp.brows:
        ef = L.ef if not L.sp.eyes3 else replace(L.ef, brow=(L.ef.brow[0], L.ef.brow[1] - 2))
        _brows(ctx, look, ef, L.fx, L.fy, L.spacing, L.eye_y, L.sizes, pose.t)
    _face_accessories(ctx, look, L.fx, L.fy, L.eye_y, L.spacing, L.sizes, L.sp.mouth_y)


def draw_face_over(ctx: cairo.Context, look: Look, pose: Pose, cx: float, cy: float, r: float, yaw: float) -> None:
    """Брови, очки и усы поверх чёлки (как в аниме — брови видны сквозь волосы)."""
    if r <= 0.5 or look.base in ("robot", "robot3d"):
        if r > 0.5:
            yaw = clamp(yaw, -1.0, 1.0)
            L = _layout(look, pose, yaw)
            ctx.save()
            ctx.translate(cx, cy)
            ctx.scale(r / FACE_R, r / FACE_R)
            _face_accessories(ctx, look, L.fx, L.fy, -8, 24, {-1: 1.0, 1: 1.0}, 36)
            ctx.restore()
        return
    yaw = clamp(yaw, -1.0, 1.0)
    L = _layout(look, pose, yaw)
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(r / FACE_R, r / FACE_R)
    _over(ctx, look, pose, L)
    ctx.restore()


__all__ = ["EMOTIONS", "EmoFace", "FACE_R", "blend_emotion", "draw_face", "draw_face_over", "species_of"]
