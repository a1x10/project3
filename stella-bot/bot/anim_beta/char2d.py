"""Прототип 2D-персонажа: параметрический «чиби» с риг-позой, эмоциями и псевдо-3D поворотом головы.

Локальные координаты: ноги в (0, 0), макушка около y = -300. Свет сверху-слева: cel-тень — полумесяц справа-снизу.
"""
import math

import cairocffi as cairo

TAU = 2 * math.pi


def mix(a, b, k):
    return tuple(x + (y - x) * k for x, y in zip(a, b, strict=False))


def mul(c, k):
    return tuple(max(0.0, min(1.0, x * k)) for x in c)


def palette(base, accent=None):
    base = tuple(base)
    return {
        "base": base,
        "shade": mix(mul(base, 0.78), (0.35, 0.2, 0.55), 0.18),  # тень чуть в фиолетовый — живее
        "light": mix(base, (1, 1, 1), 0.45),
        "line": mix(mul(base, 0.35), (0.12, 0.05, 0.2), 0.35),
        "accent": tuple(accent) if accent else mix(base, (1, 0.97, 0.92), 0.75),
    }


def ellipse(ctx, cx, cy, rx, ry, rot=0.0):
    ctx.save()
    ctx.translate(cx, cy)
    if rot:
        ctx.rotate(rot)
    ctx.scale(rx, ry)
    ctx.new_sub_path()
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()


def capsule(ctx, x0, y0, x1, y1, r):
    a = math.atan2(y1 - y0, x1 - x0)
    ctx.new_sub_path()
    ctx.arc(x1, y1, r, a - math.pi / 2, a + math.pi / 2)
    ctx.arc(x0, y0, r, a + math.pi / 2, a + 3 * math.pi / 2)
    ctx.close_path()


def part(ctx, path, pal, lw, light=(-0.18, -0.22), shade=True, hl=True, fill=None):
    """Заливка + cel-тень (полумесяц) + блик + цветная обводка. path(ctx) строит контур."""
    path(ctx)
    ctx.set_source_rgb(*(fill or pal["base"]))
    ctx.fill_preserve()
    ext = ctx.fill_extents()
    w, h = ext[2] - ext[0], ext[3] - ext[1]
    if shade or hl:
        ctx.save()
        ctx.clip()
        if shade:
            ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            ctx.rectangle(ext[0] - 5, ext[1] - 5, w + 10, h + 10)
            ctx.save()
            ctx.translate(light[0] * w * 0.6, light[1] * h * 0.6)
            path(ctx)
            ctx.restore()
            ctx.set_source_rgb(*pal["shade"])
            ctx.fill()
            ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
        if hl:
            ellipse(ctx, ext[0] + w * 0.32, ext[1] + h * 0.25, w * 0.16, h * 0.09, -0.5)
            ctx.set_source_rgba(*pal["light"], 0.75)
            ctx.fill()
        ctx.restore()
    else:
        ctx.new_path()
    path(ctx)
    ctx.set_source_rgb(*pal["line"])
    ctx.set_line_width(lw)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


# ---------- лицо ----------
def eye(ctx, x, y, rx, ry, p, iris, line, side):
    """Большой мультяшный глаз: белок, радужка с градиентом, зрачок, два блика, веко (моргание/эмоция)."""
    openk = max(0.0, min(1.0, p.get("eye_open", 1.0)))
    special = p.get("eyes")
    ctx.save()
    ctx.translate(x, y)
    if openk < 0.12 or special == "closed_happy":
        # закрытый глаз: дуга ^ (счастье) или черта (сон)
        ctx.set_source_rgb(*line)
        ctx.set_line_width(rx * 0.32)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        if special == "closed_happy" or p.get("mouth") in ("grin", "laugh"):
            ctx.move_to(-rx * 0.8, ry * 0.15)
            ctx.curve_to(-rx * 0.4, -ry * 0.55, rx * 0.4, -ry * 0.55, rx * 0.8, ry * 0.15)
        else:
            ctx.move_to(-rx * 0.8, 0)
            ctx.curve_to(-rx * 0.3, ry * 0.3, rx * 0.3, ry * 0.3, rx * 0.8, 0)
        ctx.stroke()
        ctx.restore()
        return
    if special == "heart":
        s = rx * 1.05
        ctx.move_to(0, s * 0.75)
        ctx.curve_to(-s * 1.3, -s * 0.1, -s * 0.6, -s * 1.05, 0, -s * 0.35)
        ctx.curve_to(s * 0.6, -s * 1.05, s * 1.3, -s * 0.1, 0, s * 0.75)
        ctx.close_path()
        g = cairo.LinearGradient(0, -s, 0, s)
        g.add_color_stop_rgb(0, 1, 0.45, 0.6)
        g.add_color_stop_rgb(1, 0.85, 0.05, 0.3)
        ctx.set_source(g)
        ctx.fill_preserve()
        ctx.set_source_rgb(*line)
        ctx.set_line_width(rx * 0.14)
        ctx.stroke()
        ellipse(ctx, -s * 0.35, -s * 0.35, s * 0.18, s * 0.12, -0.6)
        ctx.set_source_rgba(1, 1, 1, 0.9)
        ctx.fill()
        ctx.restore()
        return
    ctx.save()
    ellipse(ctx, 0, 0, rx, ry)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill_preserve()
    ctx.clip_preserve()
    # радужка
    lx, ly = p.get("look", (0.0, 0.0))
    ix, iy = lx * rx * 0.35, ly * ry * 0.3
    ir = rx * 0.78 * p.get("iris", 1.0)
    g = cairo.LinearGradient(0, iy - ir, 0, iy + ir)
    g.add_color_stop_rgb(0, *mul(iris, 0.45))
    g.add_color_stop_rgb(0.55, *iris)
    g.add_color_stop_rgb(1, *mix(iris, (1, 1, 1), 0.45))
    ctx.new_path()
    ellipse(ctx, ix, iy, ir, ir * 1.12)
    ctx.set_source(g)
    ctx.fill()
    pr = ir * 0.48 * p.get("pupil", 1.0)
    ellipse(ctx, ix, iy, pr, pr * 1.15)
    ctx.set_source_rgb(0.06, 0.03, 0.1)
    ctx.fill()
    # блики
    ellipse(ctx, ix - ir * 0.38 * side, iy - ir * 0.42, ir * 0.36, ir * 0.3, -0.4)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    ellipse(ctx, ix + ir * 0.35 * side, iy + ir * 0.45, ir * 0.14, ir * 0.14)
    ctx.fill()
    if special == "star":
        ctx.save()
        ctx.translate(ix, iy)
        star_path(ctx, 0, 0, ir * 0.62, ir * 0.27, 5, -math.pi / 2)
        ctx.set_source_rgb(1, 0.95, 0.5)
        ctx.fill()
        ctx.restore()
    # верхнее веко: прикрывает глаз по эмоции (злость — наклон к носу, грусть — наружу)
    lid = 1 - openk
    tilt = p.get("lid_tilt", 0.0) * side  # >0 — злой наклон
    if lid > 0.01 or abs(tilt) > 0.01:
        top = -ry - 2
        yl = -ry + 2 * ry * lid
        ctx.move_to(-rx - 2, top)
        ctx.line_to(rx + 2, top)
        ctx.line_to(rx + 2, yl - tilt * ry * 0.6)
        ctx.line_to(-rx - 2, yl + tilt * ry * 0.6)
        ctx.close_path()
        ctx.set_source_rgb(*p["_skin"])
        ctx.fill()
        ctx.move_to(-rx - 2, yl + tilt * ry * 0.6)
        ctx.line_to(rx + 2, yl - tilt * ry * 0.6)
        ctx.set_source_rgb(*line)
        ctx.set_line_width(rx * 0.16)
        ctx.stroke()
    ctx.restore()
    ellipse(ctx, 0, 0, rx, ry)
    ctx.set_source_rgb(*line)
    ctx.set_line_width(rx * 0.15)
    ctx.stroke()
    # ресницы-«хвостик» снаружи
    ctx.move_to(side * rx * 0.75, -ry * 0.62)
    ctx.line_to(side * rx * 1.18, -ry * 0.9)
    ctx.set_line_width(rx * 0.14)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    ctx.restore()


def star_path(ctx, cx, cy, r1, r2, n=5, rot=0.0):
    for i in range(2 * n):
        r = r1 if i % 2 == 0 else r2
        a = rot + math.pi * i / n
        (ctx.move_to if i == 0 else ctx.line_to)(cx + r * math.cos(a), cy + r * math.sin(a))
    ctx.close_path()


def mouth(ctx, x, y, w, p, line):
    kind = p.get("mouth", "smile")
    o = p.get("mouth_open", 0.0)
    ctx.save()
    ctx.translate(x, y)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_source_rgb(*line)
    ctx.set_line_width(w * 0.13)
    if kind in ("grin", "laugh", "open", "o", "shout") or o > 0.15:
        if kind == "o":
            ellipse(ctx, 0, w * 0.1, w * 0.28, w * 0.34 * (0.6 + o))
        elif kind == "shout":
            ctx.move_to(-w * 0.5, w * 0.25)
            ctx.curve_to(-w * 0.3, -w * 0.2, w * 0.3, -w * 0.2, w * 0.5, w * 0.25)
            ctx.curve_to(w * 0.3, w * (0.4 + o), -w * 0.3, w * (0.4 + o), -w * 0.5, w * 0.25)
        else:
            ctx.move_to(-w * 0.55, -w * 0.05)
            ctx.curve_to(-w * 0.2, w * 0.05, w * 0.2, w * 0.05, w * 0.55, -w * 0.05)
            ctx.curve_to(w * 0.45, w * (0.45 + 0.6 * o), -w * 0.45, w * (0.45 + 0.6 * o), -w * 0.55, -w * 0.05)
        ctx.close_path()
        ctx.set_source_rgb(0.42, 0.06, 0.16)
        ctx.fill_preserve()
        ctx.save()
        ctx.clip_preserve()
        ellipse(ctx, 0, w * (0.42 + 0.5 * o), w * 0.32, w * 0.2)  # язык
        ctx.set_source_rgb(1, 0.45, 0.55)
        ctx.fill()
        ctx.rectangle(-w, -w * 0.3, 2 * w, w * 0.2)  # зубки
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        ctx.restore()
        ctx.set_source_rgb(*line)
        ctx.stroke()
    elif kind == "cat":
        ctx.move_to(-w * 0.45, 0)
        ctx.curve_to(-w * 0.4, w * 0.25, -w * 0.05, w * 0.25, 0, 0)
        ctx.curve_to(w * 0.05, w * 0.25, w * 0.4, w * 0.25, w * 0.45, 0)
        ctx.stroke()
    elif kind == "frown":
        ctx.move_to(-w * 0.4, w * 0.2)
        ctx.curve_to(-w * 0.2, -w * 0.12, w * 0.2, -w * 0.12, w * 0.4, w * 0.2)
        ctx.stroke()
    elif kind == "wavy":
        ctx.move_to(-w * 0.45, 0)
        for i in range(4):
            ctx.rel_curve_to(w * 0.11, -w * 0.15 * (-1) ** i, w * 0.11, -w * 0.15 * (-1) ** i, w * 0.225, 0)
        ctx.stroke()
    else:  # smile / smug
        k = 0.35 if kind == "smile" else 0.18
        ctx.move_to(-w * 0.42, 0)
        ctx.curve_to(-w * 0.2, w * k, w * 0.2, w * k, w * 0.42, -w * (0.08 if kind == "smug" else 0))
        ctx.stroke()
    ctx.restore()


# ---------- персонаж ----------
SPECIES = {"cat", "bunny", "bear", "fox"}


def draw_character(ctx, look, pose):
    """look: вид (species, colors, iris). pose: x, y, scale, facing, yaw, lean, squash, arms, legs, face."""
    pal = palette(look["color"], look.get("accent"))
    sp = look["species"]
    s = pose.get("scale", 1.0)
    face = dict(pose.get("face", {}))
    face["_skin"] = pal["base"]
    lw = 6.0
    ctx.save()
    ctx.translate(pose["x"], pose["y"])
    # тень на земле — до сжатия/растяжения
    ctx.save()
    hk = max(0.4, 1 - pose.get("air", 0) / 260)
    ctx.scale(s * hk, s * 0.22 * hk)
    ctx.arc(0, 0, 95, 0, TAU)
    shg = cairo.RadialGradient(0, 0, 0, 0, 0, 95)
    shg.add_color_stop_rgba(0, 0.1, 0.05, 0.2, 0.38)
    shg.add_color_stop_rgba(1, 0.1, 0.05, 0.2, 0)
    ctx.set_source(shg)
    ctx.fill()
    ctx.restore()
    ctx.translate(0, -pose.get("air", 0) * s)
    sq = pose.get("squash", 1.0)
    ctx.scale(s * pose.get("facing", 1) / math.sqrt(sq), s * sq)
    ctx.rotate(pose.get("lean", 0.0))
    yaw = pose.get("yaw", 0.0)  # -1..1, поворот головы/корпуса (псевдо-3D)

    # хвост — позади всего
    tph = pose.get("tail", 0.0)
    if sp in ("cat", "fox"):
        ctx.save()
        ctx.translate(-48 - 10 * yaw, -60)
        sw = math.sin(tph) * 0.35
        if sp == "cat":
            ctx.move_to(0, 0)
            ctx.curve_to(-60, 0 + 10 * sw, -70 + 30 * sw, -70, -40 + 50 * sw, -110)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_source_rgb(*pal["line"])
            ctx.set_line_width(30)
            ctx.stroke_preserve()
            ctx.set_source_rgb(*pal["base"])
            ctx.set_line_width(19)
            ctx.stroke()
        else:
            def tail(c):
                c.move_to(0, 0)
                c.curve_to(-70, 20, -120 + 30 * sw, -60, -70 + 40 * sw, -150)
                c.curve_to(-40, -100, -10, -60, 10, -20)
                c.close_path()
            part(ctx, tail, pal, lw)

            def tip(c):
                c.move_to(-70 + 40 * sw, -150)
                c.curve_to(-95 + 30 * sw, -120, -95 + 25 * sw, -95, -85 + 20 * sw, -85)
                c.curve_to(-60, -100, -55 + 20 * sw, -120, -70 + 40 * sw, -150)
                c.close_path()
            part(ctx, tip, palette((1, 0.98, 0.95)), lw * 0.8, shade=False, hl=False)
        ctx.restore()
    elif sp == "bunny":
        part(ctx, lambda c: ellipse(c, -52 - 10 * yaw, -52, 22, 20), palette((1, 1, 1)), lw)

    # ноги
    for side in (-1, 1):
        a = pose.get("leg_l" if side < 0 else "leg_r", 0.0)
        ctx.save()
        ctx.translate(side * 28 - 8 * yaw, -38)
        ctx.rotate(a)
        part(ctx, lambda c: capsule(c, 0, 0, 0, 26, 21), pal, lw, hl=False)
        part(ctx, lambda c: ellipse(c, 6, 36, 27, 15), pal, lw, hl=False)
        ctx.restore()

    # тело
    def body(c):
        c.move_to(0, -150)
        c.curve_to(52, -150, 74, -80, 66, -40)
        c.curve_to(60, -10, 30, -4, 0, -4)
        c.curve_to(-30, -4, -60, -10, -66, -40)
        c.curve_to(-74, -80, -52, -150, 0, -150)
        c.close_path()
    part(ctx, body, pal, lw)
    # животик
    bx = 14 * yaw
    part(ctx, lambda c: ellipse(c, bx, -55, 42 - 8 * abs(yaw), 40), palette(pal["accent"]), lw * 0.0 + 0.01, shade=False,
         hl=False)

    # руки: дальняя рука (по yaw) рисуется за телом было бы правильнее; для прототипа — обе спереди
    for side in (-1, 1):
        a = pose.get("arm_l" if side < 0 else "arm_r", 0.0)
        ctx.save()
        ctx.translate(side * (52 - 6 * yaw * side), -118)
        ctx.rotate(-side * a)
        part(ctx, lambda c, side=side: capsule(c, 0, 0, side * 14, 52, 16), pal, lw, hl=False)
        ctx.restore()

    # голова
    ctx.save()
    ctx.translate(0, -150 + pose.get("head_bob", 0.0))
    ctx.rotate(pose.get("head_tilt", 0.0))
    HR, HY = 102, -86  # радиус и центр головы
    ex = 18 * yaw  # уши/макушка уезжают от поворота
    if sp == "cat" or sp == "fox":
        big = 1.25 if sp == "fox" else 1.0
        for side in (-1, 1):
            flop = pose.get("ear", 0.0) * side

            def ear(c, side=side, flop=flop):
                c.move_to(side * 30 - ex, HY - 80)
                c.curve_to(side * 55 - ex, HY - 150 * big + flop * 20, side * 70 - ex, HY - 160 * big + flop * 20,
                           side * (95 + 10 * big) - ex, HY - 140 * big + flop * 30)
                c.curve_to(side * 100 - ex, HY - 100, side * 95 - ex, HY - 70, side * 85 - ex, HY - 45)
                c.close_path()
            part(ctx, ear, pal, lw, hl=False)

            def inner(c, side=side, flop=flop):
                c.move_to(side * 48 - ex, HY - 82)
                c.curve_to(side * 64 - ex, HY - 125 * big + flop * 15, side * 72 - ex, HY - 128 * big + flop * 15,
                           side * 86 - ex, HY - 118 * big + flop * 22)
                c.curve_to(side * 88 - ex, HY - 95, side * 84 - ex, HY - 80, side * 78 - ex, HY - 65)
                c.close_path()
            part(ctx, inner, palette((1, 0.62, 0.72)), 0.01, shade=False, hl=False)
    elif sp == "bunny":
        for side in (-1, 1):
            flop = pose.get("ear", 0.0)
            ctx.save()
            ctx.translate(side * 38 - ex, HY - 78)
            ctx.rotate(side * (0.18 + 0.25 * flop))
            part(ctx, lambda c: ellipse(c, 0, -62, 25, 70), pal, lw, hl=False)
            part(ctx, lambda c: ellipse(c, 0, -58, 12, 52), palette((1, 0.62, 0.72)), 0.01, shade=False, hl=False)
            ctx.restore()
    elif sp == "bear":
        for side in (-1, 1):
            part(ctx, lambda c, side=side: ellipse(c, side * 72 - ex, HY - 72, 30, 30), pal, lw, hl=False)
            part(ctx, lambda c, side=side: ellipse(c, side * 72 - ex, HY - 70, 15, 15), palette((1, 0.7, 0.75)), 0.01,
                 shade=False, hl=False)

    def head(c):
        c.move_to(0, HY - 92)
        c.curve_to(72, HY - 92, HR + 10, HY - 40, HR + 4, HY + 10)
        c.curve_to(HR, HY + 62, 60, HY + 86, 0, HY + 86)
        c.curve_to(-60, HY + 86, -HR, HY + 62, -HR - 4, HY + 10)
        c.curve_to(-HR - 10, HY - 40, -72, HY - 92, 0, HY - 92)
        c.close_path()
    part(ctx, head, pal, lw)
    # мордочка: светлые щёки у лисы
    fx = HR * 0.55 * math.sin(yaw * 0.9)  # центр лица смещается по поверхности «шара»
    if sp == "fox":
        def muzzle(c):
            c.move_to(fx - 85, HY + 15)
            c.curve_to(fx - 60, HY + 5, fx - 20, HY + 20, fx, HY + 40)
            c.curve_to(fx + 20, HY + 20, fx + 60, HY + 5, fx + 85, HY + 15)
            c.curve_to(fx + 70, HY + 80, fx - 70, HY + 80, fx - 85, HY + 15)
            c.close_path()
        ctx.save()
        head(ctx)
        ctx.clip()
        part(ctx, muzzle, palette((1, 0.98, 0.95)), 0.01, shade=False, hl=False)
        ctx.restore()
    # глаза на «сфере»: угол каждого глаза +-0.42 рад, ширина сжимается по cos
    iris = look.get("iris", (0.25, 0.55, 0.95))
    for side in (-1, 1):
        ang = yaw * 0.9 + side * 0.42
        vis = math.cos(ang)
        if vis < 0.15:
            continue
        x = HR * 0.98 * math.sin(ang)
        rx = 25 * (0.35 + 0.65 * vis)
        eye(ctx, x, HY + 4, rx, 31, face, iris, pal["line"], side)
        # брови
        b = face.get("brow", 0.0)  # <0 злые, >0 грустные/удивлённые
        by = HY - 42 - 8 * face.get("brow_up", 0)
        ctx.move_to(x - rx * 0.9, by + side * b * 10)
        ctx.line_to(x + rx * 0.9, by - side * b * 10)
        ctx.set_source_rgb(*pal["line"])
        ctx.set_line_width(7)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
    # румянец
    bl = face.get("blush", 0.5)
    if bl > 0:
        for side in (-1, 1):
            ang = yaw * 0.9 + side * 0.72
            if math.cos(ang) < 0.2:
                continue
            x = HR * 0.92 * math.sin(ang)
            g = cairo.RadialGradient(x, HY + 42, 0, x, HY + 42, 24)
            g.add_color_stop_rgba(0, 1, 0.35, 0.45, 0.65 * bl)
            g.add_color_stop_rgba(1, 1, 0.35, 0.45, 0)
            ctx.set_source(g)
            ellipse(ctx, x, HY + 42, 24, 16)
            ctx.fill()
    # нос и рот
    ellipse(ctx, fx * 1.05, HY + 34, 9, 6.5)
    ctx.set_source_rgb(*mix(pal["line"], (0.9, 0.3, 0.4), 0.5))
    ctx.fill()
    mouth(ctx, fx * 1.05, HY + 50, 34, face, pal["line"])
    if sp == "cat":
        ctx.set_source_rgb(*pal["line"])
        ctx.set_line_width(3)
        for side in (-1, 1):
            for k in (-1, 1):
                ctx.move_to(fx + side * 55, HY + 40 + k * 6)
                ctx.line_to(fx + side * 95, HY + 34 + k * 14)
        ctx.stroke()
    # эмоциональные значки
    if "sweat" in face.get("fx", ()):
        ctx.move_to(HR * 0.8, HY - 55)
        ctx.curve_to(HR * 0.8 + 14, HY - 30, HR * 0.8 + 10, HY - 15, HR * 0.8, HY - 15)
        ctx.curve_to(HR * 0.8 - 10, HY - 15, HR * 0.8 - 14, HY - 30, HR * 0.8, HY - 55)
        ctx.set_source_rgb(0.6, 0.85, 1)
        ctx.fill_preserve()
        ctx.set_source_rgb(0.2, 0.4, 0.7)
        ctx.set_line_width(3)
        ctx.stroke()
    if "anger" in face.get("fx", ()):
        ctx.save()
        ctx.translate(HR * 0.62, HY - 70)
        ctx.set_source_rgb(0.9, 0.1, 0.15)
        ctx.set_line_width(6)
        for k in range(4):
            ctx.save()
            ctx.rotate(k * math.pi / 2)
            ctx.move_to(5, -16)
            ctx.curve_to(5, -6, 6, -5, 16, -5)
            ctx.stroke()
            ctx.restore()
        ctx.restore()
    if "tears" in face.get("fx", ()):
        for side in (-1, 1):
            ang = yaw * 0.9 + side * 0.42
            x = HR * 0.98 * math.sin(ang)
            ctx.move_to(x + side * 8, HY + 25)
            ctx.curve_to(x + side * 20, HY + 60, x + side * 5, HY + 90, x + side * 14, HY + 120)
            ctx.set_source_rgba(0.55, 0.8, 1, 0.9)
            ctx.set_line_width(10)
            ctx.stroke()
    ctx.restore()  # голова
    ctx.restore()
