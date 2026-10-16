"""Детали зверушек и существ: форма головы, уши, рожки, антенны, хвосты, крылья, мордочки, пушистое тело монстра
и привидение.

Уши, рожки и антенны рисуются в пространстве головы (центр головы — начало координат, r — радиус); хвосты и
крылья — в пространстве куклы (ступни в (0, 0)), позади всего. Вторичное движение — pose.tail_swing, ear_swing,
wing_flap (их считает life.py), плюс собственная лёгкая «жизнь» от pose.t.
"""

from __future__ import annotations

import math
from typing import Callable

import cairocffi as cairo

from ..draw import body_grad, cel_shadow, ellipse, fill_ink, fill_union, rrect, set_source, smooth_closed
from ..model import Pose
from ..ease import smoothstep
from ..palette import INK, hx, lighten, mix, mul
from .look import Look

PINK = hx("#ff9eb5")
CEL = (-9.0, -6.0)  # сдвиг копии для cel-тени: тёмный серп — справа снизу (свет сверху слева)


def _stroke(ctx: cairo.Context, color, width: float, alpha: float = 1.0) -> None:
    set_source(ctx, color, alpha)
    ctx.set_line_width(width)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


# ---------- форма головы ----------
def head_path_fn(ctx: cairo.Context, look: Look, r: float) -> Callable[[], None]:
    """Функция, которая строит контур головы (центр — начало координат)."""
    w = look.build.head_w
    kind = look.kind
    if kind == "robot":
        def robot() -> None:
            rrect(ctx, -r * 1.05 * w, -r * 0.92, r * 2.1 * w, r * 1.78, r * 0.42)
        return robot
    if kind == "alien":
        pts = [(0, -r * 1.1), (r * 0.95, -r * 0.55), (r * 0.9, r * 0.25), (r * 0.35, r * 0.85),
               (-r * 0.35, r * 0.85), (-r * 0.9, r * 0.25), (-r * 0.95, -r * 0.55)]

        def alien() -> None:
            smooth_closed(ctx, pts, 0.9)
        return alien
    if kind == "creature":
        rw = r * w
        cheek = 1.2 if look.base in ("cat", "fox") else 1.12

        def mochi() -> None:
            ctx.move_to(0, -r * 0.98)
            ctx.curve_to(rw * 0.95, -r * 1.0, rw * cheek, -r * 0.12, rw * 1.06, r * 0.36)
            ctx.curve_to(rw * 0.94, r * 0.9, -rw * 0.94, r * 0.9, -rw * 1.06, r * 0.36)
            ctx.curve_to(-rw * cheek, -r * 0.12, -rw * 0.95, -r * 1.0, 0, -r * 0.98)
            ctx.close_path()
        return mochi
    pts = [(0, -r), (r * 0.82, -r * 0.62), (r * 1.02, r * 0.1), (r * 0.72, r * 0.72),
           (0, r * 0.9), (-r * 0.72, r * 0.72), (-r * 1.02, r * 0.1), (-r * 0.82, -r * 0.62)]

    def human() -> None:
        smooth_closed(ctx, pts, 0.95)
    return human


def head_top(look: Look, r: float) -> float:
    """y макушки (без волос и ушей), отрицательный."""
    if look.kind == "alien":
        return -r * 1.1
    if look.kind == "robot":
        return -r * 0.92
    return -r * 0.98


def ears_top(look: Look, r: float) -> float:
    """Насколько выше макушки торчат уши/рожки/антенны (единицы, ≥ 0)."""
    return {"dog": 0.12, "cat": 0.62, "fox": 0.8, "bunny": 1.4, "bear": 0.2, "dragon": 0.55, "alien": 0.75,
            "robot": 0.75, "monster": 0.5}.get(look.base, 0.0) * r


# ---------- уши, рожки, антенны ----------
def ears_back(ctx: cairo.Context, look: Look, pose: Pose, r: float, fx: float) -> None:
    """То, что за головой: острые/длинные/круглые уши, рожки, антенны."""
    base = look.base
    t = pose.t
    col = look.color
    yaw = pose.yaw
    es = pose.ear_swing
    if base in ("cat", "fox"):
        big = 1.25 if base == "fox" else 1.0
        for s in (-1, 1):
            if (s < 0 and yaw > 0.7) or (s > 0 and yaw < -0.7):
                continue
            tw = 0.06 * math.sin(t * 2 + s) + es * 0.18 * s
            twitch = 0.12 * max(0.0, math.sin(t * 0.9 + s * 2.1)) ** 30
            ctx.save()
            ctx.translate(s * r * 0.6 + fx * 0.25, -r * 0.62)
            ctx.rotate(s * 0.32 + tw + s * twitch)
            ctx.scale(s * big, big)
            ctx.move_to(-22, 14)
            ctx.curve_to(-18, -16, -8, -40, 2, -48)
            ctx.curve_to(12, -38, 22, -14, 26, 14)
            ctx.close_path()
            fill_ink(ctx, body_grad(0, -10, 32, col), 4.5)
            ctx.move_to(-11, 8)
            ctx.curve_to(-8, -12, -2, -26, 2, -33)
            ctx.curve_to(7, -24, 11, -10, 13, 8)
            ctx.close_path()
            set_source(ctx, PINK if base == "cat" else look.belly)
            ctx.fill()
            if base == "fox":  # тёмные кончики
                ctx.save()
                ctx.move_to(-22, 14)
                ctx.curve_to(-18, -16, -8, -40, 2, -48)
                ctx.curve_to(12, -38, 22, -14, 26, 14)
                ctx.close_path()
                ctx.clip()
                ctx.move_to(-30, -26)
                ctx.line_to(30, -22)
                ctx.line_to(30, -60)
                ctx.line_to(-30, -60)
                ctx.close_path()
                set_source(ctx, look.accent)
                ctx.fill()
                ctx.restore()
                ctx.move_to(-22, 14)
                ctx.curve_to(-18, -16, -8, -40, 2, -48)
                ctx.curve_to(12, -38, 22, -14, 26, 14)
                _stroke(ctx, INK, 4.5)
            ctx.restore()
    elif base == "bunny":
        for s in (-1, 1):
            ctx.save()
            ctx.translate(s * r * 0.36 + fx * 0.3, -r * 0.78)
            ctx.rotate(s * (0.16 + 0.04 * math.sin(t * 1.7 + s)) + es * 0.2)
            bend = s * 0.12 + es * 0.7 + 0.08 * math.sin(t * 2.3 + s)
            _bunny_ear(ctx, r, bend, col, look.accent)
            ctx.restore()
    elif base == "bear":
        for s in (-1, 1):
            if (s < 0 and yaw > 0.7) or (s > 0 and yaw < -0.7):
                continue
            x, y = s * r * 0.78 + fx * 0.25, -r * 0.72
            ellipse(ctx, x, y, r * 0.34, r * 0.32)
            fill_ink(ctx, body_grad(x, y, r * 0.34, col), 4.5)
            ellipse(ctx, x, y + 2, r * 0.17, r * 0.16)
            set_source(ctx, look.belly)
            ctx.fill()
    elif base in ("dragon", "monster"):
        for s in (-1, 1):
            ctx.save()
            ctx.translate(s * r * (0.5 if base == "dragon" else 0.55) + fx * 0.3, -r * 0.8)
            ctx.rotate(s * 0.3)
            ctx.scale(s, 1)
            h = 1.0 if base == "dragon" else 0.75
            ctx.move_to(-10, 8)
            ctx.curve_to(-9, -16 * h, 4, -32 * h, 14, -40 * h)
            ctx.curve_to(9, -24 * h, 10, -8, 11, 8)
            ctx.close_path()
            fill_ink(ctx, body_grad(0, -10, 25, look.accent), 4.0)
            ctx.restore()
    elif base in ("alien", "robot"):
        for s in (-1, 1) if base == "alien" else (1,):
            bx = s * 22 + fx * 0.4 if base == "alien" else fx * 0.5
            wob = math.sin(t * 5 + s) * 5 + es * 10
            y0 = -r * (0.78 if base == "robot" else 0.82)
            tip = (bx + s * 16 + wob, y0 - r * 0.72)
            ctx.move_to(bx, y0)
            ctx.curve_to(bx + s * 6, y0 - r * 0.35, bx + s * 14 + wob, y0 - r * 0.55, *tip)
            _stroke(ctx, INK, 9)
            ctx.move_to(bx, y0)
            ctx.curve_to(bx + s * 6, y0 - r * 0.35, bx + s * 14 + wob, y0 - r * 0.55, *tip)
            _stroke(ctx, mul(col, 0.85) if base == "alien" else (0.7, 0.75, 0.85), 4)
            glow = 0.6 + 0.4 * math.sin(t * 8 + s)
            tipc = look.accent
            gg = cairo.RadialGradient(*tip, 0, *tip, 22)
            gg.add_color_stop_rgba(0, *tipc, 0.65 * glow)
            gg.add_color_stop_rgba(1, *tipc, 0)
            ctx.set_source(gg)
            ctx.arc(*tip, 22, 0, 2 * math.pi)
            ctx.fill()
            ellipse(ctx, *tip, 8, 8)
            fill_ink(ctx, body_grad(tip[0], tip[1], 8, tipc), 3)
        if base == "robot":  # «уши»-болты
            for s in (-1, 1):
                if (s < 0 and yaw > 0.6) or (s > 0 and yaw < -0.6):
                    continue
                x = s * r * 1.08 * look.build.head_w - fx * 0.2
                rrect(ctx, x - 9, -16, 18, 32, 6)
                fill_ink(ctx, body_grad(x, 0, 16, mul(col, 0.85)), 3.5)


def _bunny_ear(ctx: cairo.Context, r: float, bend: float, col, inner) -> None:
    """Длинное заячье ухо одним контуром: прямое у основания, кончик гнётся на bend радиан."""
    n = 8
    length = r * 1.6
    ds = length / n
    x = y = a = 0.0
    left, right = [], []
    for i in range(n + 1):
        u = i / n
        w = r * 0.28 * (0.62 + 0.38 * math.sin(math.pi * min(u, 0.92)))
        nx, ny = math.cos(a), math.sin(a)
        if i < n:
            left.append((x - nx * w, y - ny * w))
            right.append((x + nx * w, y + ny * w))
        else:
            tip = (x, y)
        a = bend * smoothstep((u - 0.35) / 0.65)
        x += math.sin(a) * ds
        y -= math.cos(a) * ds
    outer = left + [tip] + right[::-1]

    def path() -> None:
        smooth_closed(ctx, outer, 0.6)
    path()
    fill_ink(ctx, body_grad(0, -length * 0.5, r * 0.6, col), 4.5)
    cel_shadow(ctx, path, col, *CEL)
    inner_pts = [(px * 0.5 + qx * 0.5 + (px - qx) * 0.22, py * 0.5 + qy * 0.5 + (py - qy) * 0.22)
                 for (px, py), (qx, qy) in zip(left[1:], right[1:], strict=True)]
    inner_pts2 = [(px * 0.5 + qx * 0.5 - (px - qx) * 0.22, py * 0.5 + qy * 0.5 - (py - qy) * 0.22)
                  for (px, py), (qx, qy) in zip(left[1:], right[1:], strict=True)]
    tip_in = (inner_pts[-1][0] * 0.5 + tip[0] * 0.5, inner_pts[-1][1] * 0.5 + tip[1] * 0.5)
    smooth_closed(ctx, inner_pts + [tip_in] + inner_pts2[::-1], 0.6)
    set_source(ctx, inner)
    ctx.fill()


def ears_front(ctx: cairo.Context, look: Look, pose: Pose, r: float, fx: float) -> None:
    """Висячие уши собаки — поверх головы по бокам."""
    if look.base != "dog":
        return
    yaw = pose.yaw
    for s in (-1, 1):
        if (s < 0 and yaw > 0.75) or (s > 0 and yaw < -0.75):
            continue
        flop = pose.ear_swing * 0.35 + 0.05 * math.sin(pose.t * 2.2 + s)
        ctx.save()
        ctx.translate(s * r * 0.7 * look.build.head_w - fx * 0.15, -r * 0.72)
        ctx.rotate(s * (0.08 + flop))
        ctx.scale(s * r / 66.0, r / 66.0)
        ctx.move_to(-12, 2)
        ctx.curve_to(12, -16, 36, -6, 38, 28)
        ctx.curve_to(40, 56, 32, 78, 17, 82)
        ctx.curve_to(2, 86, -6, 72, -4, 52)
        ctx.curve_to(-2, 32, -14, 16, -12, 2)
        ctx.close_path()
        fill_ink(ctx, body_grad(8, 20, 40, look.accent), 4.5)
        ctx.restore()


def muzzle(ctx: cairo.Context, look: Look, pose: Pose, r: float, fx: float, eye_y: float,
           head_path: Callable[[], None]) -> None:
    """Светлая мордочка, щёки, полоски — на голове, обрезано по её контуру."""
    base = look.base
    light = look.belly
    if base not in ("cat", "dog", "fox", "bunny", "bear", "dragon"):
        return
    k = r / 62.0
    ctx.save()
    head_path()
    ctx.clip()
    mx = fx * 1.05
    if base == "fox":
        y = eye_y * k
        ctx.move_to(mx - r * 1.2, y + 4 * k)
        ctx.curve_to(mx - r * 0.75, y - 8 * k, mx - r * 0.3, y + 16 * k, mx, y + 26 * k)
        ctx.curve_to(mx + r * 0.3, y + 16 * k, mx + r * 0.75, y - 8 * k, mx + r * 1.2, y + 4 * k)
        ctx.line_to(mx + r * 1.2, r * 1.2)
        ctx.line_to(mx - r * 1.2, r * 1.2)
        ctx.close_path()
        set_source(ctx, light)
        ctx.fill()
    elif base in ("dog", "bear"):
        y = (eye_y + 30) * k
        ellipse(ctx, mx, y, r * 0.48, r * 0.36)
        ctx.set_source(body_grad(mx, y, r * 0.48, light))
        ctx.fill()
    elif base in ("cat", "bunny"):
        y = (eye_y + 31) * k
        for s in (-1, 1):
            ellipse(ctx, mx + s * r * 0.17, y, r * 0.24, r * 0.19)
        set_source(ctx, light)
        ctx.fill()
        if base == "cat" and look.color[0] > look.color[2] + 0.1:  # полоски рыжего кота
            for i in (-1, 0, 1):
                xx = fx * 0.4 + i * r * 0.28
                ctx.move_to(xx - 6 * k, -r * 0.99)
                ctx.line_to(xx, -r * 0.66 - (6 * k if i == 0 else 0))
                ctx.line_to(xx + 6 * k, -r * 0.99)
                ctx.close_path()
            set_source(ctx, mul(look.color, 0.75))
            ctx.fill()
    elif base == "dragon":
        for px, py, pr in ((-0.45, -0.7, 0.11), (-0.2, -0.85, 0.08), (0.4, -0.75, 0.1)):
            ellipse(ctx, px * r + fx * 0.3, py * r, pr * r, pr * r * 0.8)
        set_source(ctx, look.accent, 0.8)
        ctx.fill()
    ctx.restore()


# ---------- хвосты и крылья (пространство куклы) ----------
def tail(ctx: cairo.Context, look: Look, pose: Pose, hip: tuple[float, float], yaw: float) -> None:
    """Хвост позади всего. hip — точка таза."""
    base = look.base
    t = pose.t
    sw = pose.tail_swing
    col = look.color
    x0, y0 = hip[0] - 26 - yaw * 10, hip[1] + 4
    if base == "cat":
        pts = [(x0, y0)]
        a = math.pi * 0.98
        x, y = x0, y0
        for i in range(7):
            a += -0.2 + 0.13 * sw * (i + 1) / 3 + 0.05 * math.sin(t * 2.4 - i * 0.6)
            x += 13 * math.cos(a)
            y += 13 * math.sin(a) - 4.5
            pts.append((x, y))
        for w, c in ((19, INK), (11, col)):
            ctx.move_to(*pts[0])
            for i in range(1, len(pts) - 1):
                m = ((pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2)
                ctx.curve_to(*pts[i], *pts[i], *m)
            ctx.line_to(*pts[-1])
            _stroke(ctx, c, w)
        ellipse(ctx, *pts[-1], 5.5, 5.5)
        set_source(ctx, lighten(col, 0.55))
        ctx.fill()
    elif base == "dog":
        ang = -0.9 + sw * 0.6
        ctx.save()
        ctx.translate(x0 + 6, y0 - 6)
        ctx.rotate(ang)
        ctx.move_to(0, 6)
        ctx.curve_to(-26, 4, -40, -10, -38, -30)
        ctx.curve_to(-30, -18, -16, -10, 2, -6)
        ctx.close_path()
        fill_ink(ctx, body_grad(-20, -10, 24, col), 4.0)
        ctx.restore()
    elif base == "fox":
        ctx.save()
        ctx.translate(x0 + 4, y0 - 4)
        ctx.rotate(-0.2 + sw * 0.35 + 0.06 * math.sin(t * 2.0))

        def bushy() -> None:
            ctx.move_to(0, 6)
            ctx.curve_to(-46, 18, -84, -6, -78, -58)
            ctx.curve_to(-64, -40, -30, -26, 4, -14)
            ctx.close_path()
        bushy()
        fill_ink(ctx, body_grad(-40, -20, 50, col), 4.5)
        cel_shadow(ctx, bushy, col, *CEL)
        ctx.save()
        bushy()
        ctx.clip()
        ellipse(ctx, -80, -52, 22, 18, 0.4)
        set_source(ctx, look.belly)
        ctx.fill()
        ctx.restore()
        bushy()
        _stroke(ctx, INK, 4.5)
        ctx.restore()
    elif base in ("bunny", "bear"):
        rr = 15 if base == "bunny" else 11
        x, y = x0 + 8 + sw * 3, y0 - 6
        if base == "bunny":
            def puff() -> None:
                for i in range(6):
                    a = 2 * math.pi * i / 6 + 0.3
                    ctx.new_sub_path()
                    ctx.arc(x + rr * 0.55 * math.cos(a), y + rr * 0.55 * math.sin(a), rr * 0.6, 0, 2 * math.pi)
            fill_union(ctx, puff, body_grad(x, y, rr, look.belly), 3.5)
        else:
            ellipse(ctx, x, y, rr, rr)
            fill_ink(ctx, body_grad(x, y, rr, col), 4.0)
    elif base == "dragon":
        pts = []
        for i in range(8):
            u = i / 7
            a = math.pi * (0.96 - 0.25 * u) + sw * 0.4 * u + 0.12 * math.sin(t * 2 - u * 3) * u
            rr = 16 + 72 * u
            pts.append((x0 + 10 + rr * math.cos(a) * 1.05, y0 + 10 - rr * math.sin(a) * 0.4 + 40 * u * u - 6))
        for w, c in ((22, INK), (13, col)):
            ctx.move_to(*pts[0])
            for i in range(1, len(pts) - 1):
                m = ((pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2)
                ctx.curve_to(*pts[i], *pts[i], *m)
            ctx.line_to(*pts[-1])
            _stroke(ctx, c, w)
        tx, ty = pts[-1]
        px, py = pts[-2]
        ang = math.atan2(ty - py, tx - px)
        ctx.save()
        ctx.translate(tx, ty)
        ctx.rotate(ang)
        ctx.move_to(-4, -11)
        ctx.line_to(16, 0)
        ctx.line_to(-4, 11)
        ctx.close_path()
        fill_ink(ctx, look.accent, 3.0)
        ctx.restore()
        for i in (2, 4):  # шипы
            x, y = pts[i]
            ctx.move_to(x - 6, y - 5)
            ctx.line_to(x, y - 15)
            ctx.line_to(x + 6, y - 5)
            ctx.close_path()
            fill_ink(ctx, look.accent, 2.6)


def wings(ctx: cairo.Context, look: Look, pose: Pose, neck: tuple[float, float], yaw: float) -> None:
    """Крылья дракона за спиной; pose.wing_flap −1..1 — фаза взмаха."""
    if look.base != "dragon":
        return
    col = mul(look.color, 0.85)
    flap = 0.38 * pose.wing_flap + 0.06 * math.sin(pose.t * 2.0)
    for s in (1, -1):
        ctx.save()
        ctx.translate(neck[0] - 4 - yaw * 8, neck[1] + 26)
        far = (s < 0) == (yaw >= 0)
        sc = 0.82 if far else 1.0
        ctx.scale(s * sc * (1 - 0.25 * abs(yaw) if far else 1.0), sc)
        ctx.rotate(-0.25 - flap)
        ctx.move_to(0, 0)
        ctx.curve_to(-26, -48, -64, -62, -96, -46)
        ctx.curve_to(-82, -34, -80, -22, -84, -10)
        ctx.curve_to(-68, -18, -58, -8, -54, 4)
        ctx.curve_to(-40, -4, -26, 2, 0, 14)
        ctx.close_path()
        g = cairo.LinearGradient(0, 0, -90, -50)
        g.add_color_stop_rgb(0, *col)
        g.add_color_stop_rgb(1, *mix(look.accent, col, 0.35))
        fill_ink(ctx, g, 3.8)
        ctx.move_to(-6, 4)
        ctx.line_to(-88, -40)
        ctx.move_to(-10, 6)
        ctx.line_to(-80, -12)
        ctx.move_to(-12, 8)
        ctx.line_to(-56, 2)
        _stroke(ctx, mul(col, 0.7), 2.2)
        ctx.restore()


# ---------- пушистый монстр и привидение ----------
def monster_body(ctx: cairo.Context, look: Look, pose: Pose, cx: float, cy: float, rx: float, ry: float) -> None:
    """Пушистое тело-голова монстра: объединённый контур из «пуфов» меха + брюшко с пятнышками."""
    col = look.color
    t = pose.t
    n = 22

    def fur() -> None:
        for i in range(n):
            a = 2 * math.pi * i / n
            rip = 1.0 + 0.03 * math.sin(t * 3 + i * 1.7)
            ctx.new_sub_path()
            ctx.arc(cx + rx * 0.93 * math.cos(a) * rip, cy + ry * 0.93 * math.sin(a) * rip, 15, 0, 2 * math.pi)
        ctx.new_sub_path()
        ellipse(ctx, cx, cy, rx * 0.95, ry * 0.95)
    fill_union(ctx, fur, body_grad(cx, cy - ry * 0.2, max(rx, ry) * 1.05, col), 4.5)

    def body_el() -> None:
        ellipse(ctx, cx, cy, rx * 1.02, ry * 1.02)
    cel_shadow(ctx, body_el, col, -12.0, -8.0, 0.82)
    ellipse(ctx, cx + pose.yaw * 10, cy + ry * 0.42, rx * 0.56, ry * 0.42)
    ctx.set_source(body_grad(cx, cy + ry * 0.4, rx * 0.6, look.belly))
    ctx.fill()
    for i in range(7):
        a = i * 2.4
        rr = rx * (0.25 + 0.08 * (i % 3))
        ellipse(ctx, cx + rr * math.cos(a) * 1.6, cy - ry * 0.55 + rr * 0.4 * math.sin(a), 4 + i % 3, 4 + i % 3)
    ctx.set_source_rgba(1, 1, 1, 0.28)
    ctx.fill()


def ghost_body(ctx: cairo.Context, look: Look, pose: Pose, y0: float) -> Callable[[], None]:
    """Привидение: купол с волнистым подолом. Возвращает функцию контура (для тени и лица)."""
    t = pose.t

    def path() -> None:
        ctx.move_to(-70, y0 + 40)
        ctx.curve_to(-75, y0 - 70, 75, y0 - 70, 70, y0 + 40)
        n = 5
        for i in range(n):
            xa = 70 - (i + 1) * 140 / n
            wob = 10 * math.sin(t * 6 + i * 1.3)
            ctx.curve_to(70 - i * 140 / n - 8, y0 + 75 + wob, xa + 12, y0 + 75 - wob, xa, y0 + 52 + wob * 0.5)
        ctx.close_path()
    return path


__all__ = ["CEL", "ears_back", "ears_front", "ears_top", "ghost_body", "head_path_fn", "head_top",
           "monster_body", "muzzle", "tail", "wings"]
