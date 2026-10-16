"""Кукла персонажа: скелет из позы (Pose), слои сзади вперёд, одежда, аксессуары и сама отрисовка.

Порядок слоёв (design_wow §c.2): хвост и крылья → плащ/рюкзак → дальняя нога, ближняя нога → дальняя рука (если
повёрнут) → задний слой волос и капюшон → корпус (юбка/пояс, принт, светодиоды робота, шарф) → ближние руки →
голова (уши, голова, cel-тень, мордочка, лицо, чёлка, шапки) → руки, которые у лица → значки над головой.

Единицы куклы: рост 300, (0, 0) — точка между ступнями на земле, y вниз. facing = −1 — зеркально (ctx.scale(−1, 1)),
поэтому несимметричное (пробор, хвост, козырёк) зеркалится само; надписи на одежде и значки — нет.
Дальние конечности на 18 % темнее — дешёвая и сильная глубина.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cairocffi as cairo

from ..draw import (body_grad, cel_shadow, ellipse, fill_ink, heart, hose, rrect, set_source, smooth_closed, star,
                    text_path)
from ..model import Pose
from ..palette import INK, hx, lighten, mix, mul
from . import creatures as cr
from .face import FACE_R, blend_emotion, draw_face, draw_face_over, species_of
from .hair import hair_back, hair_front, hair_top, head_accessories
from .look import Look
from .marks import draw_dust, draw_mark, draw_puff, draw_spark

CEL = cr.CEL
BACK_K = 0.82  # дальние конечности темнее
HEIGHT = 300.0
Pt = tuple[float, float]


@dataclass
class Rig:
    """Положение суставов в единицах куклы (до зеркала и масштаба)."""

    hip: Pt
    neck: Pt
    head: Pt
    shoulders: dict[int, Pt]
    hips: dict[int, Pt]
    elbows: dict[int, Pt]
    hands: dict[int, Pt]
    knees: dict[int, Pt]
    feet: dict[int, Pt]
    hand_ang: dict[int, float]
    lean: float
    yaw: float
    narrow: float
    back: int  # дальняя сторона: −1 (левая), +1 (правая) или 0 (анфас)
    head_r: float
    head_rot: float


def _dvec(a: float) -> Pt:
    return math.sin(a), math.cos(a)


def rig(look: Look, pose: Pose) -> Rig:
    """Скелет: таз, шея, голова, плечи, локти, кисти, колени, ступни."""
    b = look.build
    yaw = max(-1.0, min(1.0, pose.yaw))
    lean = pose.lean + b.lean0
    hip = (0.0, b.hip_y + pose.bob)
    ca, sa = math.cos(lean), math.sin(lean)

    def at(o: Pt, v: Pt) -> Pt:
        return o[0] + v[0] * ca - v[1] * sa, o[1] + v[0] * sa + v[1] * ca

    neck = at(hip, (0.0, -b.torso))
    head = at(neck, (yaw * 3.0, -b.neck))
    narrow = 1 - 0.35 * abs(yaw)
    shoulders = {s: at(hip, (s * b.shoulder * narrow + yaw * 6, -(b.torso - 8))) for s in (-1, 1)}
    hips = {s: (hip[0] + s * b.hip_w * narrow + yaw * 4, hip[1] - 2) for s in (-1, 1)}
    elbows, hands, hand_ang, knees, feet = {}, {}, {}, {}, {}
    for s in (-1, 1):
        a, bend = pose.arm_l if s < 0 else pose.arm_r
        d = _dvec(a)
        sh = shoulders[s]
        el = (sh[0] + b.upper_arm * d[0] * s, sh[1] + b.upper_arm * d[1])
        d2 = _dvec(a + bend)
        hand = (el[0] + b.forearm * d2[0] * s, el[1] + b.forearm * d2[1])
        elbows[s], hands[s], hand_ang[s] = el, hand, a + bend
        la, lb = pose.leg_l if s < 0 else pose.leg_r
        h0 = hips[s]
        dk = _dvec(la * s)
        kn = (h0[0] + b.thigh * dk[0], h0[1] + b.thigh * dk[1])
        df = _dvec(la * s - lb)
        knees[s], feet[s] = kn, (kn[0] + b.shin * df[0], kn[1] + b.shin * df[1])
    back = -1 if yaw > 0.15 else (1 if yaw < -0.15 else 0)
    return Rig(hip, neck, head, shoulders, hips, elbows, hands, knees, feet, hand_ang, lean, yaw, narrow, back,
               b.head_r, pose.head_tilt + lean * 0.5)


def _stroke(ctx: cairo.Context, color, width: float, alpha: float = 1.0) -> None:
    set_source(ctx, color, alpha)
    ctx.set_line_width(width)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


# ---------- кисти и ступни ----------
def _hand(ctx: cairo.Context, p: Pt, ang: float, s: int, kind: str, col, r: float, paw: bool) -> None:
    ctx.save()
    ctx.translate(*p)
    ctx.rotate(-s * ang)  # ось предплечья → вниз (+y)
    if kind == "point":
        ctx.move_to(0, 0)
        ctx.line_to(0, r * 1.5)
        _stroke(ctx, INK, r * 1.18)
        ctx.move_to(0, 0)
        ctx.line_to(0, r * 1.5)
        _stroke(ctx, col, r * 0.55)
    elif kind == "peace":
        for dx in (-0.35, 0.35):
            ctx.move_to(0, 0)
            ctx.line_to(r * dx * 1.4, r * 1.45)
            _stroke(ctx, INK, r * 1.0)
            ctx.move_to(0, 0)
            ctx.line_to(r * dx * 1.4, r * 1.45)
            _stroke(ctx, col, r * 0.45)
    ellipse(ctx, 0, 0, r, r)
    fill_ink(ctx, body_grad(0, 0, r, col), 3.5)
    if paw:
        for dx in (-0.35, 0.0, 0.35):
            ctx.move_to(r * dx, r * 0.55)
            ctx.line_to(r * dx, r * 0.95)
        _stroke(ctx, mul(col, 0.6), 1.8)
    elif kind == "open":  # большой палец
        ellipse(ctx, s * r * 0.8, -r * 0.1, r * 0.45, r * 0.36, s * 0.5)
        fill_ink(ctx, col, 3.0)
    elif kind in ("fist", "hold"):
        ctx.move_to(-r * 0.5, r * 0.25)
        ctx.curve_to(-r * 0.2, r * 0.5, r * 0.2, r * 0.5, r * 0.5, r * 0.25)
        _stroke(ctx, mul(col, 0.6), 1.8)
    ctx.restore()


def _foot(ctx: cairo.Context, look: Look, p: Pt, s: int, yaw: float, leg_a: float, dark: float) -> None:
    b = look.build
    fw, fh = b.foot
    off = s * 3 * (1 - abs(yaw)) + 7 * yaw
    ctx.save()
    ctx.translate(p[0] + off, p[1] + 2)
    ctx.rotate(-0.15 * leg_a * s)
    if look.kind == "robot":
        rrect(ctx, -fw, -fh, fw * 2, fh * 1.7, 6)
        fill_ink(ctx, body_grad(0, -fh * 0.3, fw, mul(look.shoes if look.shoes != look.color else
                                                       mul(look.color, 0.7), dark)), 3.5)
    else:
        ellipse(ctx, 0, 0, fw, fh)
        col = mul(look.shoes, dark)
        fill_ink(ctx, body_grad(0, 0, fw, col), 3.5)
        if look.kind == "human":
            ellipse(ctx, -fw * 0.25, -fh * 0.4, fw * 0.35, fh * 0.25)
            ctx.set_source_rgba(1, 1, 1, 0.45)
            ctx.fill()
            ctx.move_to(-fw * 0.95, fh * 0.15)
            ctx.curve_to(-fw * 0.4, fh * 0.55, fw * 0.4, fh * 0.55, fw * 0.95, fh * 0.15)
            _stroke(ctx, (1, 1, 1), 2.2, 0.55)
        else:
            for dx in (-0.4, 0.0, 0.4):
                ctx.move_to(fw * dx, -fh * 0.1)
                ctx.line_to(fw * dx, fh * 0.6)
            _stroke(ctx, mul(col, 0.62), 1.8)
    ctx.restore()


# ---------- конечности ----------
def _leg(ctx: cairo.Context, look: Look, pose: Pose, R: Rig, s: int, dark: bool) -> None:
    b = look.build
    k = BACK_K if dark else 1.0
    h0, kn, ft = R.hips[s], R.knees[s], R.feet[s]
    skin = look.skin
    kind = look.kind
    if kind == "robot":
        col = mul(lighten(look.color, 0.15), k)
        hose(ctx, h0, kn, ft, b.leg_w, col, ow=3.5)
        ellipse(ctx, kn[0], kn[1], 8, 8)
        fill_ink(ctx, mul(look.accent, k), 2.6)
    elif kind == "human" or look.bottom is not None:
        bottom = look.bottom
        if bottom == "pants":
            hose(ctx, h0, kn, ft, b.leg_w + 2, mul(look.bottom_color, k), ow=3.5)
        else:
            hose(ctx, h0, kn, ft, b.leg_w - 2, mul(skin, k), ow=3.5)
            if bottom == "shorts":
                hose(ctx, h0, kn, ft, b.leg_w + 4, mul(look.bottom_color, k), ow=3.5, t1=0.5)
    else:
        hose(ctx, h0, kn, ft, b.leg_w, mul(look.color, k), ow=3.8)
    la = (pose.leg_l if s < 0 else pose.leg_r)[0]
    _foot(ctx, look, ft, s, R.yaw, la, k)


def _sleeve(look: Look) -> str:
    """Какой рукав: none | short | long | rolled | puff."""
    top = look.top
    if top is None:
        return "none"
    return {"tshirt": "short", "dress": "puff", "hoodie": "long", "sweater": "long", "suit": "long",
            "shirt": "rolled"}.get(top, "short")


def _arm(ctx: cairo.Context, look: Look, pose: Pose, R: Rig, s: int, dark: bool) -> None:
    b = look.build
    k = BACK_K if dark else 1.0
    sh, el, hd = R.shoulders[s], R.elbows[s], R.hands[s]
    kind = look.kind
    paw = kind in ("creature", "monster")
    if kind == "robot":
        col = mul(lighten(look.color, 0.1), k)
        hose(ctx, sh, el, hd, b.arm_w, col, ow=3.5)
        ellipse(ctx, el[0], el[1], 7, 7)
        fill_ink(ctx, mul(look.accent, k), 2.5)
        skin = mul(look.color, 0.8 * k)
    else:
        skin = mul(look.skin, k)
        hose(ctx, sh, el, hd, b.arm_w, skin, ow=3.5 if not paw else 3.8)
        sl = _sleeve(look)
        top = mul(look.top_color, k)
        if sl == "short":
            hose(ctx, sh, el, hd, b.arm_w + 4, top, ow=3.5, t1=0.42)
        elif sl == "long":
            hose(ctx, sh, el, hd, b.arm_w + 3, top, ow=3.5, t1=0.86)
            if look.top in ("sweater", "hoodie"):
                hose(ctx, sh, el, hd, b.arm_w + 4, mul(top, 0.85), ow=3.0, t0=0.8, t1=0.88)
        elif sl == "rolled":
            hose(ctx, sh, el, hd, b.arm_w + 3, top, ow=3.5, t1=0.55)
            hose(ctx, sh, el, hd, b.arm_w + 5, lighten(top, 0.15), ow=3.0, t0=0.5, t1=0.58)
        elif sl == "puff":
            ellipse(ctx, sh[0] + s * 2, sh[1] + 3, b.arm_w * 0.85, b.arm_w * 0.75)
            fill_ink(ctx, body_grad(sh[0], sh[1], b.arm_w, top), 3.5)
    hand = pose.hand_l if s < 0 else pose.hand_r
    _hand(ctx, hd, R.hand_ang[s], s, hand, skin, b.hand_r, paw)


# ---------- корпус ----------
def _torso_path(ctx: cairo.Context, look: Look, R: Rig):
    b = look.build
    n = R.narrow
    hip = R.hip
    ca, sa = math.cos(R.lean), math.sin(R.lean)

    def at(v: Pt) -> Pt:
        return hip[0] + v[0] * ca - v[1] * sa, hip[1] + v[0] * sa + v[1] * ca

    T = b.torso
    if look.kind == "robot":
        def path() -> None:
            ctx.save()
            ctx.translate(*hip)
            ctx.rotate(R.lean)
            rrect(ctx, -(b.chest_w + 2) * n, -T - 6, 2 * (b.chest_w + 2) * n, T + 16, 18)
            ctx.restore()
        return path
    w1, w2 = b.chest_w * n + 3, b.waist_w * n + 3
    if b.body == "chunky":
        pts = [at(p) for p in ((-w2, 6), (-w2 - 4, -T * 0.35), (-w1, -T * 0.85), (-w1 + 12, -T - 4),
                               (w1 - 12, -T - 4), (w1, -T * 0.85), (w2 + 4, -T * 0.35), (w2, 6), (0, 11))]
    else:
        pts = [at(p) for p in ((-w2, 4), (-w2 - 3, -T * 0.38), (-w1, -T * 0.85), (-w1 + 10, -T - 4),
                               (w1 - 10, -T - 4), (w1, -T * 0.85), (w2 + 3, -T * 0.38), (w2, 4), (0, 9))]

    def path() -> None:
        smooth_closed(ctx, pts, 0.8)
    return path


def _skirt(ctx: cairo.Context, look: Look, pose: Pose, R: Rig, color, long: bool) -> None:
    b = look.build
    ctx.save()
    ctx.translate(*R.hip)
    ctx.rotate(R.lean)
    n = R.narrow
    sw = 1 + 0.06 * math.sin(pose.t * 7) + 0.05 * pose.hair_swing
    hem = 34 if long else 26
    top_w = (b.waist_w * n + 1)
    flare = (46 if long else 44) * (0.75 + 0.25 * n)
    ctx.move_to(-top_w, -16)
    ctx.line_to(top_w, -16)
    ctx.curve_to(flare * 0.85 * sw, 2, flare * sw, hem - 8, flare * sw + pose.hair_swing * 4, hem - 4)
    for i in range(6, -1, -1):
        xx = -flare * sw + i * (2 * flare * sw / 6) + pose.hair_swing * 4 * (i / 6)
        ctx.line_to(xx + 7.6 * sw, hem)
        ctx.line_to(xx, hem - 4)
    ctx.close_path()
    fill_ink(ctx, body_grad(0, 0, 52, color), 4.0)
    for i in (-2, 0, 2):  # складки
        ctx.move_to(i * 9 * n, -10)
        ctx.line_to(i * 15 * sw, hem - 8)
    _stroke(ctx, mul(color, 0.72), 2.0, 0.8)
    ctx.restore()


def _print(ctx: cairo.Context, look: Look, R: Rig, torso_path, facing: int) -> None:
    prt = look.top_print
    if not prt:
        return
    b = look.build
    cx, cy = _at(R, (R.yaw * 10, -b.torso * 0.56))
    acc = look.accent
    if prt == "star":
        star(ctx, cx, cy, 13)
        fill_ink(ctx, acc if acc != look.top_color else lighten(acc, 0.5), 2.5)
    elif prt == "heart":
        heart(ctx, cx, cy + 2, 13)
        fill_ink(ctx, hx("#ff3d6e") if look.top_color[0] < 0.8 or look.top_color[1] > 0.5 else (1, 1, 1), 2.5)
    elif prt == "stripes":
        ctx.save()
        torso_path()
        ctx.clip()
        ctx.translate(*R.hip)
        ctx.rotate(R.lean)
        for i in range(4):
            ctx.rectangle(-80, -b.torso * 0.85 + i * 17, 160, 7)
        set_source(ctx, lighten(look.top_color, 0.55))
        ctx.fill()
        ctx.restore()
    elif prt.startswith(("number:", "text:")):
        text = prt.split(":", 1)[1][:6]
        if not text:
            return
        size = 30 if len(text) <= 2 else max(11.0, 52.0 / len(text))
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(facing, 1)  # надпись не зеркалим
        ctx.new_path()
        text_path(ctx, text, 0, 0, size, True, "center")
        _stroke(ctx, INK, 4.0)
        text_path(ctx, text, 0, 0, size, True, "center")
        bright = sum(look.top_color) / 3 < 0.7
        set_source(ctx, (1, 1, 1) if bright else mul(look.top_color, 0.35))
        ctx.fill()
        ctx.restore()


def _at(R: Rig, v: Pt) -> Pt:
    ca, sa = math.cos(R.lean), math.sin(R.lean)
    return R.hip[0] + v[0] * ca - v[1] * sa, R.hip[1] + v[0] * sa + v[1] * ca


def _torso(ctx: cairo.Context, look: Look, pose: Pose, R: Rig, facing: int) -> None:
    b = look.build
    kind = look.kind
    path = _torso_path(ctx, look, R)
    top = look.top
    if kind == "robot":
        base = look.color
    elif top is not None:
        base = look.top_color
    elif kind == "human":
        base = look.top_color
    else:
        base = look.color
    if top == "dress" and kind == "human":
        _skirt(ctx, look, pose, R, look.top_color, True)
    path()
    fill_ink(ctx, body_grad(R.hip[0], R.hip[1] - b.torso * 0.6, b.torso * 0.9, base), 4.5)
    cel_shadow(ctx, path, base, *CEL)
    yaw = R.yaw
    n = R.narrow
    if kind == "robot":
        cx, cy = _at(R, (yaw * 8, -b.torso * 0.55))
        rrect(ctx, cx - 19 * n, cy - 14, 38 * n, 28, 7)
        fill_ink(ctx, (0.15, 0.18, 0.28), 3.0)
        for i, c in enumerate(("#ff5d73", "#ffd166", "#06d6a0")):
            on = math.sin(pose.t * 6 + i * 2) > 0
            ellipse(ctx, cx + (-10 + i * 10) * n, cy, 3.6, 3.6)
            set_source(ctx, hx(c) if on else mul(hx(c), 0.35))
            ctx.fill()
        bx, by = _at(R, (yaw * 6, -8))
        rrect(ctx, bx - 30 * n, by - 6, 60 * n, 12, 5)
        fill_ink(ctx, mul(look.color, 0.75), 3.0)
        return
    if top is None and kind in ("creature", "alien", "monster"):
        bx, by = _at(R, (yaw * 9, -b.torso * 0.42))
        ctx.save()
        path()
        ctx.clip()
        ellipse(ctx, bx, by, (b.waist_w * 0.62) * n, b.torso * 0.42)
        ctx.set_source(body_grad(bx, by, b.waist_w * 0.7, look.belly))
        ctx.fill()
        ctx.restore()
        if look.base == "dragon":  # пластины на брюхе
            for i in range(3):
                px, py = _at(R, (yaw * 9, -b.torso * (0.68 - i * 0.2)))
                ctx.move_to(px - 13 * n, py)
                ctx.curve_to(px - 5 * n, py + 4, px + 5 * n, py + 4, px + 13 * n, py)
            _stroke(ctx, mul(look.belly, 0.7), 2.4)
        return
    # одежда
    if top in ("tshirt", "sweater", "hoodie", "dress", "shirt"):
        cx, cy = _at(R, (yaw * 6, -b.torso - 2))
        ctx.move_to(cx - 13 * n, cy)
        ctx.curve_to(cx - 7 * n, cy + (9 if top != "shirt" else 4), cx + 7 * n, cy + (9 if top != "shirt" else 4),
                     cx + 13 * n, cy)
        _stroke(ctx, mul(base, 0.6), 3.0)
    if top == "shirt":
        cx, cy = _at(R, (yaw * 6, -b.torso - 1))
        for s in (-1, 1):
            ctx.move_to(cx, cy + 6)
            ctx.line_to(cx + s * 16 * n, cy - 2)
            ctx.line_to(cx + s * 12 * n, cy + 12)
            ctx.close_path()
            fill_ink(ctx, lighten(base, 0.6), 2.4)
        for i in range(3):
            px, py = _at(R, (yaw * 6, -b.torso * (0.7 - i * 0.22)))
            ellipse(ctx, px, py, 2.4, 2.4)
        set_source(ctx, mul(base, 0.55))
        ctx.fill()
    elif top == "suit":
        cx, cy = _at(R, (yaw * 6, -b.torso - 2))
        ctx.move_to(cx - 14 * n, cy)
        ctx.line_to(cx + 14 * n, cy)
        ctx.line_to(cx, cy + b.torso * 0.5)
        ctx.close_path()
        fill_ink(ctx, (0.97, 0.97, 1.0), 2.4)
        ctx.move_to(cx, cy + 4)
        ctx.line_to(cx - 5, cy + 12)
        ctx.line_to(cx, cy + b.torso * 0.42)
        ctx.line_to(cx + 5, cy + 12)
        ctx.close_path()
        fill_ink(ctx, look.accent, 2.0)
        for s in (-1, 1):
            ctx.move_to(cx + s * 14 * n, cy)
            ctx.line_to(cx + s * 6 * n, cy + b.torso * 0.5)
            ctx.line_to(cx + s * 20 * n, cy + b.torso * 0.22)
            ctx.close_path()
            fill_ink(ctx, mul(base, 0.8), 2.4)
        px, py = _at(R, (yaw * 6, -b.torso * 0.3))
        ellipse(ctx, px, py, 3, 3)
        set_source(ctx, mul(base, 0.5))
        ctx.fill()
    elif top == "hoodie":
        px, py = _at(R, (yaw * 8, -b.torso * 0.24))
        ctx.move_to(px - 20 * n, py + 8)
        ctx.line_to(px - 15 * n, py - 10)
        ctx.line_to(px + 15 * n, py - 10)
        ctx.line_to(px + 20 * n, py + 8)
        ctx.close_path()
        fill_ink(ctx, mul(base, 0.88), 2.6)
        sw = pose.hair_swing * 6
        for s in (-1, 1):
            sx, sy = _at(R, (yaw * 6 + s * 6 * n, -b.torso))
            ex, ey = sx + sw + s * 1.5, sy + 26
            ctx.move_to(sx, sy)
            ctx.curve_to(sx + sw * 0.3, sy + 10, ex, ey - 8, ex, ey)
            _stroke(ctx, (0.96, 0.96, 1.0), 2.4)
            ellipse(ctx, ex, ey + 2, 2.2, 3.2)
            set_source(ctx, (0.75, 0.75, 0.82))
            ctx.fill()
    elif top == "sweater":
        ctx.save()
        path()
        ctx.clip()
        ctx.translate(*R.hip)
        ctx.rotate(R.lean)
        ctx.rectangle(-80, -2, 160, 14)
        set_source(ctx, mul(base, 0.85))
        ctx.fill()
        for i in range(-6, 7):
            ctx.move_to(i * 7, -2)
            ctx.line_to(i * 7, 12)
        _stroke(ctx, mul(base, 0.68), 1.6)
        ctx.restore()
    if top == "dress":
        bx, by = _at(R, (yaw * 4, -12))
        rrect(ctx, bx - (b.waist_w + 2) * n, by - 5, 2 * (b.waist_w + 2) * n, 10, 5)
        fill_ink(ctx, look.accent, 3.0)
    elif kind == "human" or look.bottom is not None:
        bottom = look.bottom
        if bottom == "skirt":
            _skirt(ctx, look, pose, R, look.bottom_color, False)
        elif bottom in ("pants", "shorts"):
            ctx.save()
            ctx.translate(*R.hip)
            ctx.rotate(R.lean)
            rrect(ctx, -(b.waist_w + 1) * n, -8, 2 * (b.waist_w + 1) * n, 16, 6)
            fill_ink(ctx, mul(look.bottom_color, 0.9), 3.5)
            ctx.restore()
    _print(ctx, look, R, path, facing)


# ---------- то, что за спиной и на шее ----------
def _cape(ctx: cairo.Context, look: Look, pose: Pose, R: Rig) -> None:
    b = look.build
    col = look.accent
    sw = pose.hair_swing
    flow = 10 + 26 * abs(sw)
    l, r_ = R.shoulders[-1], R.shoulders[1]
    nx, ny = R.neck
    hem = R.hip[1] + 46
    ctx.move_to(l[0] - 2, l[1] - 4)
    ctx.curve_to(nx, ny - 6, nx, ny - 6, r_[0] + 2, r_[1] - 4)
    ctx.curve_to(r_[0] + 14, (r_[1] + hem) / 2, r_[0] + 18 - sw * 10, hem - 10, r_[0] + 24 - sw * flow, hem)
    for i in range(4, -1, -1):
        xx = l[0] - 24 - sw * flow + (r_[0] - l[0] + 48) * i / 4
        ctx.line_to(xx, hem + (7 if i % 2 else 0) + 3 * math.sin(pose.t * 5 + i))
    ctx.curve_to(l[0] - 18 - sw * 10, hem - 10, l[0] - 14, (l[1] + hem) / 2, l[0] - 2, l[1] - 4)
    ctx.close_path()
    g = cairo.LinearGradient(0, ny, 0, hem)
    g.add_color_stop_rgb(0, *mul(col, 0.65))
    g.add_color_stop_rgb(1, *mul(col, 0.95))
    fill_ink(ctx, g, 4.0)
    del b


def _cape_collar(ctx: cairo.Context, look: Look, R: Rig) -> None:
    nx, ny = R.neck
    n = R.narrow
    ellipse(ctx, nx, ny + 4, 30 * n, 9)
    fill_ink(ctx, mul(look.accent, 0.8), 3.2)


def _backpack(ctx: cairo.Context, look: Look, R: Rig, behind: bool) -> None:
    b = look.build
    col = mix(look.accent, (0.3, 0.5, 0.9), 0.3)
    if behind:
        side = -1 if R.yaw >= 0 else 1
        cx, cy = _at(R, (side * (b.chest_w * R.narrow + 6) - R.yaw * 4, -b.torso * 0.5))
        rrect(ctx, cx - 20, cy - 30, 40, 58, 14)
        fill_ink(ctx, body_grad(cx, cy - 10, 30, col), 4.0)
        rrect(ctx, cx - 14, cy, 28, 20, 7)
        fill_ink(ctx, mul(col, 0.85), 3.0)
    else:
        for s in (-1, 1):
            if R.back == s:
                continue
            sx, sy = R.shoulders[s]
            ex, ey = _at(R, (s * b.chest_w * 0.55 * R.narrow + R.yaw * 6, -b.torso * 0.25))
            ctx.move_to(sx - s * 3, sy - 2)
            ctx.curve_to(sx - s * 6, sy + 20, ex, ey - 16, ex, ey)
            _stroke(ctx, INK, 9)
            ctx.move_to(sx - s * 3, sy - 2)
            ctx.curve_to(sx - s * 6, sy + 20, ex, ey - 16, ex, ey)
            _stroke(ctx, mul(col, 0.8), 4.5)


def _scarf(ctx: cairo.Context, look: Look, pose: Pose, R: Rig) -> None:
    nx, ny = R.neck
    n = R.narrow
    col = look.accent
    sw = pose.hair_swing
    ctx.save()
    ctx.translate(nx, ny + 2)
    ctx.rotate(R.lean)
    rrect(ctx, -26 * n, -9, 52 * n, 18, 9)
    fill_ink(ctx, body_grad(0, 0, 26, col), 3.8)
    ox = 10 * n + R.yaw * 6
    ctx.move_to(ox - 6, 4)
    ctx.curve_to(ox - 8 + sw * 6, 20, ox - 4 + sw * 14, 34, ox + sw * 18, 44)
    ctx.line_to(ox + 12 + sw * 18, 42)
    ctx.curve_to(ox + 10 + sw * 12, 30, ox + 8 + sw * 4, 18, ox + 8, 4)
    ctx.close_path()
    fill_ink(ctx, body_grad(ox, 20, 20, mul(col, 0.92)), 3.5)
    for i in range(3):
        ctx.move_to(ox + 1 + i * 4 + sw * 18, 41)
        ctx.line_to(ox + 1 + i * 4 + sw * 19, 47)
    _stroke(ctx, mul(col, 0.7), 2.0)
    ctx.restore()


def _hood(ctx: cairo.Context, look: Look, R: Rig) -> None:
    nx, ny = R.neck
    col = mul(look.top_color, 0.86)
    ctx.save()
    ctx.translate(nx - R.yaw * 10, ny - 12)
    ctx.rotate(R.lean)
    ctx.move_to(-44, 10)
    ctx.curve_to(-50, -26, 50, -26, 44, 10)
    ctx.curve_to(30, 22, -30, 22, -44, 10)
    ctx.close_path()
    fill_ink(ctx, body_grad(0, -6, 46, col), 4.0)
    ctx.restore()


# ---------- голова ----------
def _head(ctx: cairo.Context, look: Look, pose: Pose, R: Rig) -> None:
    r = R.head_r
    yaw = R.yaw
    fx = yaw * r * 0.32
    kind = look.kind
    ctx.save()
    ctx.translate(*R.head)
    ctx.rotate(R.head_rot)
    path = cr.head_path_fn(ctx, look, r)
    cr.ears_back(ctx, look, pose, r, fx)
    if kind in ("human", "alien") and look.hair != "afro":  # уши человека
        for s in (-1, 1):
            if (s > 0 and yaw > 0.5) or (s < 0 and yaw < -0.5):
                continue
            ex = s * r * 0.98 * (1 - 0.25 * abs(yaw)) - yaw * 10
            ellipse(ctx, ex, 4, 11 * r / 62, 14 * r / 62)
            fill_ink(ctx, body_grad(ex, 4, 12, look.skin), 4.0)
            ellipse(ctx, ex + s * 2, 5, 4, 7)
            set_source(ctx, mul(look.skin, 0.78))
            ctx.fill()
    base = look.color if kind in ("robot",) else look.skin
    path()
    if kind == "robot":
        g = cairo.LinearGradient(-r, 0, r, 0)
        g.add_color_stop_rgb(0, *mul(base, 0.75))
        g.add_color_stop_rgb(0.3, *lighten(base, 0.45))
        g.add_color_stop_rgb(0.6, *base)
        g.add_color_stop_rgb(1, *mul(base, 0.68))
        fill_ink(ctx, g, 5.0)
    else:
        fill_ink(ctx, body_grad(-10, -15, r * 1.1, base), 5.0)
        cel_shadow(ctx, path, base, -10.0, -8.0, 0.85)
    ef = blend_emotion(pose.emotion, pose.emotion_w)
    if ef.tint is not None and ef.tint[3] > 0.01 and kind != "robot":
        ctx.save()
        path()
        ctx.clip()
        g = cairo.LinearGradient(0, -r, 0, r * 0.2)
        g.add_color_stop_rgba(0, *ef.tint[:3], ef.tint[3])
        g.add_color_stop_rgba(1, *ef.tint[:3], 0)
        ctx.set_source(g)
        ctx.paint()
        if pose.emotion == "scared":  # «полосы страха» на лбу
            for i in range(5):
                xx = -r * 0.4 + i * r * 0.2 + fx * 0.5
                ctx.move_to(xx, -r * 0.92)
                ctx.line_to(xx, -r * 0.6 + (i % 2) * 5)
            _stroke(ctx, (0.3, 0.35, 0.7), 2.4, ef.tint[3] * 2)
        ctx.restore()
    cr.muzzle(ctx, look, pose, r, fx, species_of(look).eye_y * r / 62.0, path)
    draw_face(ctx, look, pose, 0, 0, r, yaw, over=False)
    cr.ears_front(ctx, look, pose, r, fx)
    hair_front(ctx, look, pose, r, fx, path)
    head_accessories(ctx, look, pose, r, fx, _top_y(look, r))
    draw_face_over(ctx, look, pose, 0, 0, r, yaw)
    ctx.restore()


def _top_y(look: Look, r: float) -> float:
    return cr.head_top(look, r) - hair_top(look, r)


def _hand_in_face(look: Look, R: Rig, s: int) -> bool:
    hx_, hy = R.hands[s]
    cx, cy = R.head
    rx = R.head_r * look.build.head_w * 0.95
    ry = R.head_r * 0.95
    return ((hx_ - cx) / rx) ** 2 + ((hy - cy) / ry) ** 2 < 1.0


# ---------- особые тела ----------
def _ghost(ctx: cairo.Context, look: Look, pose: Pose) -> tuple[float, float, float]:
    col = look.color
    t = pose.t
    y0 = -112 + pose.bob + 6 * math.sin(t * 3)
    path = cr.ghost_body(ctx, look, pose, y0)
    if "cape" in look.accessories:
        ctx.move_to(-56, y0 - 10)
        ctx.curve_to(-80, y0 + 30, -70 - pose.hair_swing * 20, y0 + 70, -60, y0 + 80)
        ctx.line_to(60, y0 + 80)
        ctx.curve_to(70, y0 + 60, 80, y0 + 30, 56, y0 - 10)
        ctx.close_path()
        fill_ink(ctx, look.accent, 4.0)
    path()
    fill_ink(ctx, body_grad(-10, y0 - 20, 100, col), 5.0)
    cel_shadow(ctx, path, col, -12.0, -6.0, 0.85)
    for s in (-1, 1):  # ручки-«крылышки»
        a, _ = pose.arm_l if s < 0 else pose.arm_r
        lift = (a - 0.25) * 18
        ellipse(ctx, s * 74, y0 + 22 - lift + 5 * math.sin(t * 5 + s), 17, 11, s * (0.5 + a * 0.3))
        fill_ink(ctx, body_grad(s * 74, y0 + 20, 16, col), 4.0)
    if "scarf" in look.accessories:
        ellipse(ctx, 0, y0 + 46, 60, 10)
        fill_ink(ctx, look.accent, 3.5)
    draw_face(ctx, look, pose, pose.yaw * 6, y0 + 4, 60, pose.yaw)
    head_accessories(ctx, _ghost_head(look), pose, 60, pose.yaw * 19, y0 - 58)
    return 0.0, y0, 60.0


def _ghost_head(look: Look) -> Look:
    return look


def _monster(ctx: cairo.Context, look: Look, pose: Pose, R: Rig) -> None:
    b = look.build
    bx = R.hip[0]
    cy = R.hip[1] - 62
    rx, ry = 76.0 * (1 - 0.15 * abs(R.yaw)), 80.0
    for s in (-1, 1):  # ножки
        if s == R.back:
            _leg(ctx, look, pose, R, s, True)
    for s in (-1, 1):
        if s != R.back:
            _leg(ctx, look, pose, R, s, R.back != 0 and s == R.back)
    if R.back:
        _arm(ctx, look, pose, R, R.back, True)
    fx = R.yaw * FACE_R * 0.32
    ctx.save()
    ctx.translate(bx + R.yaw * 4, cy - 30)
    ctx.rotate(R.head_rot * 0.5)
    cr.ears_back(ctx, look, pose, 70, fx)
    ctx.restore()
    ctx.save()
    ctx.translate(bx, cy)
    ctx.rotate(R.lean * 0.6)
    cr.monster_body(ctx, look, pose, 0, 0, rx, ry)
    ctx.restore()
    if "scarf" in look.accessories:
        _scarf(ctx, look, pose, R)
    for s in (-1, 1):
        if s != R.back and not _hand_in_face(look, R, s):
            _arm(ctx, look, pose, R, s, False)
    ctx.save()
    ctx.translate(bx + R.yaw * 6, cy - 22)
    ctx.rotate(R.head_rot * 0.6)
    draw_face(ctx, look, pose, 0, 0, 66, R.yaw)
    head_accessories(ctx, look, pose, 66, fx, -ry - 14)
    ctx.restore()
    for s in (-1, 1):
        if s != R.back and _hand_in_face(look, R, s):
            _arm(ctx, look, pose, R, s, False)
    del b


def _toy_fallback(ctx: cairo.Context, look: Look, pose: Pose, R: Rig) -> None:
    """Запасной 2D-вид 3D-игрушки (обычно их рисует пакет 3D)."""
    col, belly = look.color, look.belly
    y0 = -100 + pose.bob
    if look.base == "snowman3d":
        for cy, rr in ((-55 + pose.bob, 60), (-150 + pose.bob, 46)):
            ellipse(ctx, 0, cy, rr, rr)
            fill_ink(ctx, body_grad(0, cy, rr, col), 4.5)
        draw_face(ctx, look, pose, 0, -215 + pose.bob, 52, R.yaw)
        return
    ellipse(ctx, 0, y0, 78, 100)
    fill_ink(ctx, body_grad(0, y0, 100, col), 5.0)
    ellipse(ctx, R.yaw * 10, y0 + 30, 52, 62)
    ctx.set_source(body_grad(0, y0 + 30, 60, belly))
    ctx.fill()
    draw_face(ctx, look, pose, R.yaw * 8, y0 - 46, 52, R.yaw)


# ---------- вся кукла ----------
def _draw_body(ctx: cairo.Context, look: Look, pose: Pose, R: Rig, facing: int) -> tuple[Pt, float]:
    """Рисует куклу в её единицах. Возвращает (центр головы, радиус головы) — для значков."""
    kind = look.kind
    if kind == "ghost":
        x, y, r = _ghost(ctx, look, pose)
        return (x, y), r
    if kind == "toy":
        _toy_fallback(ctx, look, pose, R)
        return (0.0, -200.0 + pose.bob), 52.0
    if kind == "monster":
        _monster(ctx, look, pose, R)
        return (R.hip[0] + R.yaw * 6, R.hip[1] - 84), 66.0
    acc = look.accessories
    # 1. хвост и крылья, плащ, рюкзак
    cr.wings(ctx, look, pose, R.neck, R.yaw)
    cr.tail(ctx, look, pose, R.hip, R.yaw)
    if "cape" in acc:
        _cape(ctx, look, pose, R)
    if "backpack" in acc:
        _backpack(ctx, look, R, True)
    # 2. ноги: дальняя, потом ближняя
    order = (R.back, -R.back) if R.back else (-1, 1)
    for s in order:
        _leg(ctx, look, pose, R, s, R.back != 0 and s == R.back)
    # 3. дальняя рука
    in_face = {s: _hand_in_face(look, R, s) for s in (-1, 1)}
    if R.back and not in_face[R.back]:
        _arm(ctx, look, pose, R, R.back, True)
    # 4. задний слой волос, капюшон
    if look.hair != "none" or look.top == "hoodie":
        ctx.save()
        ctx.translate(*R.head)
        ctx.rotate(R.head_rot)
        hair_back(ctx, look, pose, R.head_r, R.yaw * R.head_r * 0.32)
        ctx.restore()
    if look.top == "hoodie":
        _hood(ctx, look, R)
    # 5. корпус
    _torso(ctx, look, pose, R, facing)
    if "backpack" in acc:
        _backpack(ctx, look, R, False)
    if "scarf" in acc:
        _scarf(ctx, look, pose, R)
    if "cape" in acc:
        _cape_collar(ctx, look, R)
    # 6. ближние руки
    for s in (-1, 1):
        if s != R.back and not in_face[s]:
            _arm(ctx, look, pose, R, s, False)
    # 7. голова
    _head(ctx, look, pose, R)
    # 8. руки у лица — поверх головы
    for s in (-1, 1):
        if in_face[s]:
            _arm(ctx, look, pose, R, s, R.back != 0 and s == R.back)
    return R.head, R.head_r


def _local_marks(ctx: cairo.Context, look: Look, pose: Pose, R: Rig, facing: int) -> None:
    """Внутренние значки в пространстве куклы: пыль у ног (позади тела рисовать не нужно — она у земли)."""
    for kind, p in pose.marks:
        if kind == "_dust":
            for s in (-1, 1):
                fx_, fy_ = R.feet[s]
                draw_dust(ctx, p, fx_, 2.0 + min(0.0, -pose.bob) * 0 + 0.0, 1.0, 1)
                break


def draw_character(ctx: cairo.Context, look: Look, pose: Pose, x: float, y: float, height_px: float,
                   facing: int) -> None:
    """Нарисовать персонажа. (x, y) — пиксели точки между ступнями на ЗЕМЛЕ; height_px — рост (уже с учётом
    плана и size); прыжок/полёт — через pose.bob; pose.scale и pose.alpha учитываются. Значки над головой
    (pose.marks) рисует сама; тень на земле — нет (её рисует compose)."""
    if height_px <= 1 or not (math.isfinite(x) and math.isfinite(y) and math.isfinite(height_px)):
        return
    f = -1 if facing < 0 else 1
    scale = max(0.0, pose.scale)
    u = height_px / HEIGHT * scale  # пикселей на единицу
    alpha = max(0.0, min(1.0, pose.alpha))
    if look.kind == "ghost":
        alpha *= 0.92
    R = rig(look, pose)
    sq = max(0.5, min(1.6, pose.squash))
    head_dev: tuple[float, float] | None = None
    marks_dev: list[tuple[str, float, float, float]] = []
    if u > 0.004 and alpha > 0.004:
        ctx.save()
        ctx.translate(x, y)
        group = alpha < 0.999
        if group:
            # группа только по рамке персонажа — не по всему кадру
            ctx.rectangle(-height_px * 0.9, -height_px * 1.5, height_px * 1.8, height_px * 1.6)
            ctx.clip()
            ctx.push_group()
        ctx.scale(u * f / math.sqrt(sq), u * sq)
        hc, hr = _draw_body(ctx, look, pose, R, f)
        head_dev = ctx.user_to_device(*hc)
        for kind, p in pose.marks:
            if kind == "_spark":
                pt = ((R.hands[-1][0] + R.hands[1][0]) / 2, (R.hands[-1][1] + R.hands[1][1]) / 2)
                if abs(R.hands[-1][0] - R.hands[1][0]) > 40:
                    pt = R.hands[1] if R.hands[1][1] < R.hands[-1][1] else R.hands[-1]
                marks_dev.append(("_spark", p, *ctx.user_to_device(*pt)))
            elif kind == "_dust":
                for s in (-1, 1):
                    fx_, _ = R.feet[s]
                    marks_dev.append(("_dust", p, *ctx.user_to_device(fx_, 0.0)))
                    break
        if group:
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(alpha)
        ctx.restore()
        hr_px = hr
    else:
        hr_px = R.head_r
    # значки — в экранных координатах (не зеркалим)
    if pose.marks:
        if head_dev is None:
            ctx.save()
            ctx.translate(x, y)
            ctx.scale(height_px / HEIGHT * f, height_px / HEIGHT)
            hc = R.head if look.kind not in ("ghost", "monster", "toy") else (0.0, -170.0)
            head_dev = ctx.user_to_device(*hc)
            ctx.restore()
        hx_, hy_ = ctx.device_to_user(*head_dev)
        mu = height_px / HEIGHT * max(0.6, min(1.6, scale if scale > 0.05 else 1.0))
        body_c = ctx.device_to_user(*head_dev)
        for kind, p in pose.marks:
            if kind == "_puff":
                cx_, cy_ = x, y - height_px * 0.42 * (sq if sq else 1.0) + pose.bob * height_px / HEIGHT
                draw_puff(ctx, p, cx_, cy_, height_px / HEIGHT)
            elif not kind.startswith("_") and alpha > 0.02 and scale > 0.05:
                draw_mark(ctx, kind, p, hx_, hy_, mu, f, hr_px, pose.t)
        for kind, p, dx, dy in marks_dev:
            px, py = ctx.device_to_user(dx, dy)
            if kind == "_spark":
                draw_spark(ctx, p, px, py, height_px / HEIGHT)
            elif kind == "_dust":
                draw_dust(ctx, p, px, y, height_px / HEIGHT, f)
        del body_c


def head_anchor(look: Look, pose: Pose, x: float, y: float, height_px: float, facing: int) -> tuple[float, float]:
    """Точка чуть выше макушки (с волосами, ушами, шапкой) в пикселях — к ней тянется хвостик пузыря реплики."""
    f = -1 if facing < 0 else 1
    u = height_px / HEIGHT * max(0.05, pose.scale)
    sq = max(0.5, min(1.6, pose.squash))
    R = rig(look, pose)
    kind = look.kind
    if kind == "ghost":
        hx_, hy_ = 0.0, -112 + pose.bob + 6 * math.sin(pose.t * 3)
        top = hy_ - 70 - _hat_extra(look, 60)
    elif kind == "monster":
        hx_ = R.hip[0]
        top = R.hip[1] - 62 - 80 - 18 - max(cr.ears_top(look, 70) * 0.8, _hat_extra(look, 66))
    elif kind == "toy":
        hx_, top = 0.0, -270.0 + pose.bob
    else:
        r = R.head_r
        top_local = min(_top_y(look, r) - _hat_extra(look, r), cr.head_top(look, r) - cr.ears_top(look, r))
        ca, sa = math.cos(R.head_rot), math.sin(R.head_rot)
        hx_ = R.head[0] - top_local * sa
        top = R.head[1] + top_local * ca
    top -= 10.0
    return x + hx_ * u * f / math.sqrt(sq), y + top * u * sq


def _hat_extra(look: Look, r: float) -> float:
    acc = look.accessories
    if "wizard_hat" in acc:
        return r * 1.5
    if "party_hat" in acc:
        return 80.0
    if "crown" in acc:
        return 34.0
    if "cap" in acc:
        return r * 0.3
    if "bow" in acc:
        return 18.0
    if "headphones" in acc:
        return 10.0
    return 0.0


__all__ = ["Rig", "draw_character", "head_anchor", "rig"]
