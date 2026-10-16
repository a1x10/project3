"""Причёски и то, что носят на голове.

Волосы — два слоя: задний (длинные, хвостики, хвост, афро, каре, кудри — рисуется до корпуса) и передний (шапочка
волос с чёлкой; чёлка отбрасывает тень на лоб, сверху — глянцевый блик-«нимб»). Афро и кудри — объединённым
контуром (fill_union): сначала толстая обводка всех «пуфов», потом заливка — без внутренних швов.

Всё рисуется в пространстве головы: начало координат — центр головы, r — её радиус, fx — сдвиг черт лица при
повороте (yaw·0.32·r). Задний слой сдвигается в обратную сторону — так голова кажется объёмной.
"""

from __future__ import annotations

import math
from typing import Callable

import cairocffi as cairo

from ..draw import body_grad, ellipse, fill_ink, fill_union, rrect, set_source, star
from ..model import Pose
from ..palette import INK, lighten, mix, mul
from .look import Look

BACK_STYLES = frozenset({"long", "twintails", "ponytail", "afro", "bob", "curly"})
# сколько волосы добавляют над макушкой (доля r) — для шапок и точки над головой
HAIR_TOP = {"short": 0.16, "spiky": 0.42, "bob": 0.18, "long": 0.18, "ponytail": 0.14, "twintails": 0.18,
            "bun": 0.62, "afro": 0.95, "curly": 0.3, "none": 0.0}


def hair_top(look: Look, r: float) -> float:
    """Высота волос над макушкой в единицах (0 у лысых и зверей)."""
    if look.kind != "human" and look.base != "alien":
        return 0.0
    return HAIR_TOP.get(look.hair, 0.15) * r


def _stroke(ctx: cairo.Context, color, width: float, alpha: float = 1.0) -> None:
    set_source(ctx, color, alpha)
    ctx.set_line_width(width)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


def _shine(ctx: cairo.Context, path: Callable[[], None], r: float, fx: float) -> None:
    """Глянцевый блик-«нимб» на волосах (аниме), обрезанный по форме причёски."""
    ctx.save()
    path()
    ctx.clip()
    ctx.new_path()
    ctx.arc(fx * 0.3, -r * 0.15, r * 0.82, math.pi * 1.15, math.pi * 1.55)
    _stroke(ctx, (1, 1, 1), r * 0.1, 0.35)
    ctx.restore()


# ---------- задний слой ----------
def hair_back(ctx: cairo.Context, look: Look, pose: Pose, r: float, fx: float) -> None:
    """Задняя часть причёски (до корпуса). Начало координат — центр головы."""
    st = look.hair
    if st not in BACK_STYLES or look.kind not in ("human", "alien"):
        return
    hair = look.hair_color
    sw = pose.hair_swing
    t = pose.t
    bx = -fx * 0.3  # затылок уходит в другую сторону при повороте
    k = r / 62.0
    if st == "long":
        def long_path() -> None:
            ctx.move_to(bx - 60 * k, -10 * k)
            ctx.curve_to(bx - (76 + sw * 6) * k, 55 * k, bx + (-62 + sw * 16) * k, 100 * k, bx + (-38 + sw * 22) * k,
                         112 * k)
            ctx.curve_to(bx + (-12 + sw * 22) * k, 118 * k, bx + (12 + sw * 22) * k, 118 * k, bx + (38 + sw * 22) * k,
                         112 * k)
            ctx.curve_to(bx + (62 + sw * 16) * k, 100 * k, bx + (76 - sw * 6) * k, 55 * k, bx + 60 * k, -10 * k)
            ctx.close_path()
        long_path()
        fill_ink(ctx, body_grad(bx, 30 * k, 90 * k, mul(hair, 0.86)), 4.0)
        for s in (-1, 1):  # пряди
            ctx.move_to(bx + s * 30 * k, 40 * k)
            ctx.curve_to(bx + (s * 34 + sw * 8) * k, 70 * k, bx + (s * 30 + sw * 14) * k, 92 * k,
                         bx + (s * 26 + sw * 18) * k, 104 * k)
        _stroke(ctx, mul(hair, 0.62), 2.4)
    elif st == "twintails":
        for s in (-1, 1):
            ox, oy = bx + s * 56 * k, -30 * k
            sws = (sw * 14 + math.sin(t * 4 + s) * 3) * k

            def tail(ox: float = ox, oy: float = oy, s: int = s, sws: float = sws) -> None:
                ctx.move_to(ox, oy)
                ctx.curve_to(ox + s * 56 * k, oy + 4 * k, ox + s * 64 * k + sws, oy + 84 * k, ox + s * 22 * k + sws * 1.4,
                             oy + 132 * k)
                ctx.curve_to(ox + s * 22 * k + sws, oy + 88 * k, ox - s * 4 * k, oy + 44 * k, ox - s * 10 * k,
                             oy + 16 * k)
                ctx.close_path()
            tail()
            fill_ink(ctx, body_grad(ox + s * 25 * k, oy + 50 * k, 72 * k, hair), 4.0)
            ctx.move_to(ox + s * 13 * k, oy + 14 * k)
            ctx.curve_to(ox + s * 33 * k, oy + 30 * k, ox + s * 35 * k + sws, oy + 70 * k, ox + s * 23 * k + sws,
                         oy + 96 * k)
            _stroke(ctx, (1, 1, 1), 3.0 * k, 0.35)
            # резинка у основания хвостика
            ellipse(ctx, ox + s * 6 * k, oy + 4 * k, 9 * k, 7 * k, s * 0.5)
            fill_ink(ctx, look.accent, 3.0)
    elif st == "ponytail":
        ox, oy = bx - 46 * k, -46 * k
        sws = (sw * 18 + math.sin(t * 4) * 4) * k
        ctx.move_to(ox + 10 * k, oy)
        ctx.curve_to(ox - 46 * k, oy - 8 * k, ox - 56 * k + sws, oy + 64 * k, ox - 30 * k + sws * 1.5, oy + 108 * k)
        ctx.curve_to(ox - 22 * k + sws, oy + 66 * k, ox - 8 * k, oy + 32 * k, ox + 16 * k, oy + 22 * k)
        ctx.close_path()
        fill_ink(ctx, body_grad(ox - 20 * k, oy + 40 * k, 62 * k, hair), 4.0)
        ctx.move_to(ox - 12 * k, oy + 12 * k)
        ctx.curve_to(ox - 34 * k, oy + 30 * k, ox - 36 * k + sws, oy + 60 * k, ox - 28 * k + sws, oy + 84 * k)
        _stroke(ctx, (1, 1, 1), 2.6 * k, 0.3)
        ellipse(ctx, ox + 2 * k, oy + 8 * k, 9 * k, 7 * k, -0.6)
        fill_ink(ctx, look.accent, 3.0)
    elif st == "afro":
        def puffs() -> None:
            for i in range(14):
                a = 2 * math.pi * i / 14
                ctx.new_sub_path()
                ctx.arc(bx + 74 * k * math.cos(a), -18 * k + 70 * k * math.sin(a), 30 * k, 0, 2 * math.pi)
            ctx.new_sub_path()
            ctx.arc(bx, -18 * k, 80 * k, 0, 2 * math.pi)
        fill_union(ctx, puffs, body_grad(bx, -34 * k, 112 * k, hair), 4.5)
    elif st == "bob":
        ctx.move_to(bx - 66 * k, -20 * k)
        ctx.curve_to(bx - 74 * k, 20 * k, bx - (70 + sw * 4) * k, 46 * k, bx - (58 + sw * 6) * k, 54 * k)
        ctx.line_to(bx + (58 - sw * 6) * k, 54 * k)
        ctx.curve_to(bx + (70 - sw * 4) * k, 46 * k, bx + 74 * k, 20 * k, bx + 66 * k, -20 * k)
        ctx.close_path()
        fill_ink(ctx, body_grad(bx, 10 * k, 80 * k, mul(hair, 0.86)), 4.0)
    elif st == "curly":
        def curls() -> None:
            for i in range(11):
                a = math.pi * (0.85 + 1.3 * i / 10)
                ctx.new_sub_path()
                ctx.arc(bx + 64 * k * math.cos(a), -10 * k + 60 * k * math.sin(a), 22 * k, 0, 2 * math.pi)
            for s in (-1, 1):
                for j in range(2):
                    ctx.new_sub_path()
                    ctx.arc(bx + s * (60 - j * 4) * k, (18 + j * 22) * k, 18 * k, 0, 2 * math.pi)
        fill_union(ctx, curls, body_grad(bx, -20 * k, 95 * k, mul(hair, 0.9)), 4.2)


# ---------- передний слой ----------
def _cap_path(ctx: cairo.Context, st: str, r: float, fx: float, capped: bool = False) -> None:
    """Шапочка волос с чёлкой (только путь). capped — под кепкой: шипы не торчат сквозь неё."""
    if st == "spiky":
        f = fx * 0.4
        pts = [(-r * 1.05, r * 0.05), (-r * 1.12, -r * 0.55), (-r * 0.95, -r * 0.7), (-r * 1.05, -r * 1.05),
               (-r * 0.55, -r * 0.95), (-r * 0.45, -r * 1.35), (-r * 0.1, -r * 1.02), (r * 0.15, -r * 1.42),
               (r * 0.4, -r * 1.0), (r * 0.85, -r * 1.2), (r * 0.82, -r * 0.75), (r * 1.15, -r * 0.6),
               (r * 1.05, r * 0.05), (r * 0.8 + f, -r * 0.3), (r * 0.5 + f, -r * 0.2), (r * 0.25 + f, -r * 0.42),
               (f - r * 0.05, -r * 0.18), (-r * 0.25 + f, -r * 0.42), (-r * 0.55 + f, -r * 0.2),
               (-r * 0.8 + f, -r * 0.4)]
        if capped:
            pts = [(x, max(y, -r * 0.95) if y < -r * 0.75 else y) for x, y in pts]
        ctx.move_to(*pts[0])
        for p in pts[1:]:
            ctx.line_to(*p)
        ctx.close_path()
        return
    low = st in ("bob", "long", "twintails")
    side_y = r * (0.36 if st == "bob" else 0.25 if low else -0.05)
    ctx.move_to(-r * 1.07, side_y)
    ctx.curve_to(-r * 1.26, -r * 0.9, -r * 0.5, -r * 1.32, r * 0.1, -r * 1.19)
    ctx.curve_to(r * 0.85, -r * 1.12, r * 1.26, -r * 0.6, r * 1.07, side_y)
    f = fx * 0.6
    if st == "bob":  # ровная чёлка
        ctx.curve_to(r * 1.02, -r * 0.05, r * 0.9, -r * 0.25, r * 0.78 + f * 0.3, -r * 0.3)
        for i in range(6, -1, -1):
            xx = -r * 0.78 + i * (1.56 * r / 6) + f * 0.3
            ctx.line_to(xx, -r * 0.3 + (r * 0.035 if i % 2 else 0))
        ctx.curve_to(-r * 0.9, -r * 0.25, -r * 1.02, -r * 0.05, -r * 1.07, side_y)
    elif st == "long":  # прямой пробор, чёлка-«шторка»
        ctx.curve_to(r * 1.0, -r * 0.1, r * 0.75, -r * 0.42, r * 0.45 + f, -r * 0.55)
        ctx.curve_to(r * 0.25 + f, -r * 0.62, r * 0.12 + f, -r * 0.8, f, -r * 0.92)
        ctx.curve_to(-r * 0.12 + f, -r * 0.8, -r * 0.25 + f, -r * 0.62, -r * 0.45 + f, -r * 0.55)
        ctx.curve_to(-r * 0.75, -r * 0.42, -r * 1.0, -r * 0.1, -r * 1.07, side_y)
    elif st in ("ponytail", "bun"):  # зачёсаны назад, косая чёлка
        ctx.curve_to(r * 1.0, -r * 0.3, r * 0.75, -r * 0.62, r * 0.4 + f, -r * 0.7)
        ctx.curve_to(r * 0.1 + f, -r * 0.62, -r * 0.3 + f, -r * 0.35, -r * 0.62 + f, -r * 0.28)
        ctx.curve_to(-r * 0.8, -r * 0.3, -r * 0.98, -r * 0.2, -r * 1.07, side_y)
    else:  # short, twintails, curly — чёлка зубчиками
        n = 5
        for i in range(n, -1, -1):
            xx = -r * 0.95 + i * (1.9 * r / n) + f
            yy = -r * 0.3 - (0.12 * r if i % 2 else 0)
            ctx.curve_to(xx + r * 0.1, yy - r * 0.15, xx + r * 0.12, yy - r * 0.05, xx, yy + r * 0.05)
    ctx.close_path()


def hair_front(ctx: cairo.Context, look: Look, pose: Pose, r: float, fx: float,
               head_path: Callable[[], None]) -> None:
    """Передняя часть причёски: шапочка волос, чёлка с тенью на лбу и бликом."""
    st = look.hair
    if look.kind not in ("human", "alien") or st == "none":
        return
    hair = look.hair_color
    if st == "afro":
        ctx.save()
        head_path()
        ctx.clip()
        ctx.rectangle(-2 * r, -2 * r, 4 * r, 1.4 * r)
        set_source(ctx, hair)
        ctx.fill()
        ctx.restore()

        def fringe() -> None:
            for i in range(7):
                ctx.new_sub_path()
                ctx.arc(-r * 0.9 + i * r * 0.3 + fx * 0.4, -r * 0.62 - (r * 0.1 if i % 2 else 0), r * 0.24, 0,
                        2 * math.pi)
        fill_union(ctx, fringe, body_grad(-r * 0.2, -r * 0.8, r * 1.3, hair), 4.5)
        return
    if st == "curly":
        def curly() -> None:
            for i in range(9):
                a = math.pi * (1.0 + i / 8)
                ctx.new_sub_path()
                ctx.arc(r * 0.86 * math.cos(a) + fx * 0.15, -r * 0.2 + r * 0.86 * math.sin(a), r * 0.3, 0,
                        2 * math.pi)
            for i in range(4):
                ctx.new_sub_path()
                ctx.arc(-r * 0.5 + i * r * 0.33 + fx * 0.5, -r * 0.5 + (r * 0.06 if i % 2 else 0), r * 0.2, 0,
                        2 * math.pi)
        ctx.save()
        head_path()
        ctx.clip()
        ctx.translate(2, 9)
        curly()
        ctx.set_source_rgba(*mul(look.skin, 0.75), 0.6)
        ctx.fill()
        ctx.restore()
        fill_union(ctx, curly, body_grad(-r * 0.2, -r * 0.8, r * 1.3, hair), 4.5)
        return

    capped = "cap" in look.accessories

    def path() -> None:
        _cap_path(ctx, st, r, fx, capped)

    # тень от чёлки на лбу
    ctx.save()
    head_path()
    ctx.clip()
    ctx.translate(2, 9)
    path()
    ctx.set_source_rgba(*mul(look.skin, 0.75), 0.6)
    ctx.fill()
    ctx.restore()
    path()
    ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
    fill_ink(ctx, body_grad(-r * 0.2, -r * 0.8, r * 1.3, hair), 5.0)
    _shine(ctx, path, r, fx)
    if st == "long":  # пробор
        ctx.move_to(fx * 0.6, -r * 0.92)
        ctx.curve_to(fx * 0.5, -r * 1.05, fx * 0.3, -r * 1.12, fx * 0.1, -r * 1.18)
        _stroke(ctx, mul(hair, 0.6), 2.4)
    if st == "bun":
        ellipse(ctx, -fx * 0.2, -r * 1.22, r * 0.4, r * 0.34)
        fill_ink(ctx, body_grad(-fx * 0.2, -r * 1.22, r * 0.42, hair), 4.5)
        ctx.move_to(-fx * 0.2 - r * 0.25, -r * 1.12)
        ctx.curve_to(-fx * 0.2 - r * 0.1, -r * 1.3, -fx * 0.2 + r * 0.15, -r * 1.32, -fx * 0.2 + r * 0.25, -r * 1.2)
        _stroke(ctx, mul(hair, 0.6), 2.2)
        ellipse(ctx, -fx * 0.2, -r * 0.94, r * 0.26, r * 0.07)
        fill_ink(ctx, look.accent, 2.8)


# ---------- то, что носят на голове ----------
def head_accessories(ctx: cairo.Context, look: Look, pose: Pose, r: float, fx: float, top: float) -> None:
    """Шапки, корона, бантик, наушники, заколки. top — y макушки с волосами (отрицательный)."""
    acc = look.accessories
    t = pose.t
    accent = look.accent
    creature = look.kind not in ("human", "alien")
    if "headphones" in acc:
        rr = r * 1.08 if look.hair != "afro" else r * 1.25
        cy = -r * 0.05
        ctx.arc(0, cy, rr, math.pi * 1.05, math.pi * 1.95)
        _stroke(ctx, INK, 13)
        ctx.arc(0, cy, rr, math.pi * 1.05, math.pi * 1.95)
        _stroke(ctx, accent, 7)
        for s in (-1, 1):
            if (s > 0 and pose.yaw > 0.55) or (s < 0 and pose.yaw < -0.55):
                continue
            x = s * r * 1.02 * (1 - 0.2 * abs(pose.yaw)) - fx * 0.3
            rrect(ctx, x - 13, -18, 26, 40, 11)
            fill_ink(ctx, body_grad(x, 0, 25, accent), 4.0)
            ellipse(ctx, x, 2, 6, 11)
            ctx.set_source_rgba(1, 1, 1, 0.25)
            ctx.fill()
    if "cap" in acc:
        base_y = -r * 0.5
        ctrl = -r * 1.5 if look.hair not in ("afro", "bun") else min(top, -r * 1.0) - r * 0.45
        peak = base_y + 0.75 * (ctrl - base_y)

        def dome() -> None:
            ctx.move_to(-r * 1.04, base_y)
            ctx.curve_to(-r * 1.08, ctrl, r * 1.08, ctrl, r * 1.04, base_y)
            ctx.close_path()
        dome()
        fill_ink(ctx, body_grad(0, -r * 0.9, r, accent), 5.0)
        ctx.save()
        dome()
        ctx.clip()
        ctx.move_to(fx * 0.3, peak)
        ctx.curve_to(fx * 0.3 - r * 0.12, peak + r * 0.3, fx * 0.3 - r * 0.08, base_y - r * 0.2, fx * 0.3, base_y)
        _stroke(ctx, mul(accent, 0.7), 2.4)
        ctx.restore()
        ctx.move_to(r * 0.4 + fx * 0.5, base_y - r * 0.07)
        ctx.curve_to(r * 1.0 + fx * 0.3, base_y - r * 0.2, r * 1.5, base_y - r * 0.1, r * 1.55, base_y + r * 0.05)
        ctx.curve_to(r * 1.2, base_y + r * 0.13, r * 0.8, base_y + r * 0.1, r * 0.3 + fx * 0.5, base_y + r * 0.05)
        ctx.close_path()
        fill_ink(ctx, mul(accent, 0.8), 4.5)
        ellipse(ctx, fx * 0.3, peak + 1, 7, 4.5)
        fill_ink(ctx, mul(accent, 0.7), 3.0)
    if "star_clips" in acc and look.kind == "human":
        for s, (dx, dy) in ((-1, (-r * 0.72, -r * 0.62)), (1, (r * 0.74, -r * 0.6))):
            ctx.save()
            ctx.translate(dx + fx * 0.25, dy)
            ctx.rotate(0.2 * s + 0.15 * math.sin(t * 3 + s) + pose.hair_swing * 0.2)
            star(ctx, 0, 0, 16)
            fill_ink(ctx, body_grad(0, 0, 16, accent), 3.5)
            ctx.restore()
    elif "star_clips" in acc:
        ctx.save()
        ctx.translate(r * 0.55, -r * 0.82)
        ctx.rotate(0.3 + 0.12 * math.sin(t * 3))
        star(ctx, 0, 0, 15)
        fill_ink(ctx, body_grad(0, 0, 15, accent), 3.5)
        ctx.restore()
    if "bow" in acc:
        ctx.save()
        if creature:
            ctx.translate(r * 0.42 + fx * 0.2, -r * 0.95)
        else:
            ctx.translate(r * 0.55 + fx * 0.2, min(-r * 0.92, top + r * 0.12))
        ctx.rotate(0.3 + 0.08 * math.sin(t * 3) + pose.hair_swing * 0.15)
        bow_col = accent if not creature else mix(accent, (1.0, 0.3, 0.45), 0.3)
        for s in (-1, 1):
            ctx.move_to(0, 0)
            ctx.curve_to(s * 20, -22, s * 34, -10, s * 30, 6)
            ctx.curve_to(s * 24, 16, s * 10, 10, 0, 0)
            fill_ink(ctx, body_grad(s * 18, 0, 25, bow_col), 3.5)
        ellipse(ctx, 0, 0, 7, 7)
        fill_ink(ctx, mul(bow_col, 0.8), 3.0)
        ctx.restore()
    if "crown" in acc:
        ctx.save()
        ctx.translate(fx * 0.3, top - 2)
        ctx.move_to(-28, 10)
        for px, py in ((-32, -22), (-15, -3), (0, -32), (15, -3), (32, -22), (28, 10)):
            ctx.line_to(px, py)
        ctx.close_path()
        g = cairo.LinearGradient(0, -32, 0, 10)
        g.add_color_stop_rgb(0, 1, 0.95, 0.55)
        g.add_color_stop_rgb(1, 0.95, 0.62, 0.1)
        fill_ink(ctx, g, 4.0)
        for px in (-15, 0, 15):
            ellipse(ctx, px, 2, 4.2, 4.2)
            ctx.set_source_rgb(1.0, 0.24, 0.43)
            ctx.fill()
        for px, py in ((-32, -22), (0, -32), (32, -22)):
            ellipse(ctx, px, py, 4.5, 4.5)
            fill_ink(ctx, (1, 0.9, 0.5), 2.2)
        ctx.restore()
    if "party_hat" in acc:
        ctx.save()
        ctx.translate(fx * 0.3 + r * 0.12, top + 6)
        ctx.rotate(0.18 + pose.hair_swing * 0.1)

        def cone() -> None:
            ctx.move_to(-30, 6)
            ctx.line_to(4, -76)
            ctx.line_to(34, 2)
            ctx.curve_to(14, 13, -12, 15, -30, 6)
            ctx.close_path()
        cone()
        g = cairo.LinearGradient(-30, 0, 34, 0)
        c1, c2 = accent, lighten(mix(accent, (0.35, 0.55, 1.0), 0.6), 0.1)
        for i in range(8):
            g.add_color_stop_rgb(i / 7, *(c1 if i % 2 else c2))
        fill_ink(ctx, g, 4.0)
        ellipse(ctx, 4, -78, 11, 11)
        fill_ink(ctx, body_grad(4, -78, 11, (1.0, 0.3, 0.5)), 3.5)
        ctx.restore()
    if "wizard_hat" in acc:
        ctx.save()
        ctx.translate(fx * 0.3, top + 10)
        bend = 14 + pose.hair_swing * 12 + 4 * math.sin(t * 2)
        col = mix(accent, (0.35, 0.25, 0.75), 0.55)

        def brim() -> None:
            ellipse(ctx, 0, 0, r * 1.25, r * 0.28)
        brim()
        fill_ink(ctx, body_grad(0, 0, r * 1.2, mul(col, 0.85)), 4.5)
        ctx.move_to(-r * 0.68, -2)
        ctx.curve_to(-r * 0.5, -r * 0.8, -r * 0.1, -r * 1.2, bend + r * 0.35, -r * 1.55)
        ctx.curve_to(r * 0.15, -r * 1.05, r * 0.5, -r * 0.6, r * 0.68, -2)
        ctx.curve_to(r * 0.3, 6, -r * 0.3, 6, -r * 0.68, -2)
        ctx.close_path()
        fill_ink(ctx, body_grad(-r * 0.2, -r * 0.6, r, col), 4.5)
        ctx.move_to(-r * 0.66, -8)
        ctx.curve_to(-r * 0.3, 0, r * 0.3, 0, r * 0.66, -8)
        _stroke(ctx, (1.0, 0.85, 0.3), 6)
        for px, py, rr in ((-r * 0.2, -r * 0.5, 7), (r * 0.18, -r * 0.85, 5), (r * 0.05, -r * 0.3, 4)):
            star(ctx, px, py, rr)
            ctx.set_source_rgb(1.0, 0.92, 0.45)
            ctx.fill()
        ctx.restore()


__all__ = ["BACK_STYLES", "HAIR_TOP", "hair_back", "hair_front", "hair_top", "head_accessories"]
