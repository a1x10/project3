"""Один кадр мультика (бета): фон с параллаксом, персонажи 2D и 3D, 3D-предметы, конфетти, пузыри, камера.

Кадр — чистая функция (план, номер кадра): кадры рисуются в разных процессах и в любом порядке.
"""

from __future__ import annotations

import math

import cairocffi as cairo
import numpy as np

from . import char2d
from . import mesh3d as m3
from . import timeline as tl

_cache: dict = {}

# небо (верх, низ), солнце/луна, холмы (дальний, ближний), земля (верх, низ)
SKIES = {
    "meadow": {"sky": ((0.42, 0.68, 1.0), (0.98, 0.84, 0.9)), "sun": (1, 0.97, 0.75), "moon": False,
               "hills": ((0.55, 0.8, 0.55), (0.38, 0.72, 0.42)), "ground": ((0.42, 0.78, 0.38), (0.28, 0.6, 0.3)),
               "cloud": (1, 1, 1, 0.92), "stars": False},
    "sunset": {"sky": ((0.36, 0.25, 0.62), (1.0, 0.62, 0.42)), "sun": (1, 0.72, 0.4), "moon": False,
               "hills": ((0.55, 0.42, 0.62), (0.4, 0.36, 0.55)), "ground": ((0.45, 0.5, 0.42), (0.3, 0.32, 0.3)),
               "cloud": (1, 0.85, 0.85, 0.85), "stars": False},
    "night": {"sky": ((0.05, 0.06, 0.2), (0.22, 0.2, 0.45)), "sun": (0.95, 0.95, 1.0), "moon": True,
              "hills": ((0.16, 0.22, 0.38), (0.12, 0.2, 0.3)), "ground": ((0.14, 0.26, 0.22), (0.08, 0.16, 0.14)),
              "cloud": (0.7, 0.72, 0.9, 0.35), "stars": True},
}

SHAPES = ("gem", "star", "donut", "ball")


def hexrgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _mesh(shape: str):
    key = ("mesh", shape)
    if key not in _cache:
        if shape == "gem":
            _cache[key] = (m3.Mesh(*m3.gem(10), smooth=False), True)
        elif shape == "star":
            _cache[key] = (m3.Mesh(*m3.extrude(m3.star_poly(5, 1.0, 0.48), 0.38), smooth=False), True)
        elif shape == "donut":
            _cache[key] = (m3.Mesh(*m3.torus(1.0, 0.38, 32, 14)), False)
        else:
            _cache[key] = (m3.Mesh(*m3.ellipsoid(24, 16)), False)
    return _cache[key]


def bg_static(w: int, h: int, preset: str, M: float) -> cairo.ImageSurface:
    """Статичная часть фона в M раз больше кадра (запас под зум). Рисуется один раз на процесс."""
    key = (w, h, preset, M)
    if key in _cache:
        return _cache[key]
    sk = SKIES.get(preset, SKIES["meadow"])
    cw, ch = int(w * M), int(h * M)
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, cw, ch)
    c = cairo.Context(s)
    c.scale(cw / w, ch / h)
    g = cairo.LinearGradient(0, 0, 0, h)
    g.add_color_stop_rgb(0, *sk["sky"][0])
    g.add_color_stop_rgb(0.7, *sk["sky"][1])
    c.set_source(g)
    c.paint()
    if sk["stars"]:
        r = tl.seeded(3, "stars")
        for _ in range(90):
            c.arc(r.uniform(0, w), r.uniform(0, h * 0.55), r.uniform(0.8, 2.2), 0, 2 * math.pi)
            c.set_source_rgba(1, 1, 0.95, r.uniform(0.5, 1))
            c.fill()
    cx, cy = w * 0.82, h * 0.16
    glow = cairo.RadialGradient(cx, cy, 0, cx, cy, h * 0.22)
    glow.add_color_stop_rgba(0, *sk["sun"], 1)
    glow.add_color_stop_rgba(0.3, *sk["sun"], 0.9 if not sk["moon"] else 0.35)
    glow.add_color_stop_rgba(1, *sk["sun"], 0)
    c.set_source(glow)
    c.paint()
    if sk["moon"]:  # месяц: диск минус сдвинутый диск (через группу — сквозь вырез видно свечение, а не пятно)
        c.push_group()
        c.arc(cx, cy, h * 0.055, 0, 2 * math.pi)
        c.set_source_rgb(0.97, 0.96, 0.88)
        c.fill()
        c.set_operator(cairo.OPERATOR_CLEAR)
        c.arc(cx + h * 0.024, cy - h * 0.014, h * 0.05, 0, 2 * math.pi)
        c.fill()
        c.pop_group_to_source()
        c.paint()
    for k, (base, col) in enumerate(zip((0.58, 0.68), sk["hills"], strict=True)):
        c.move_to(0, h)
        for i in range(0, w + 41, 20):
            c.line_to(i, h * base + 28 * math.sin(i / (110 + 40 * k) + k * 2))
        c.line_to(w, h)
        c.close_path()
        c.set_source_rgb(*col)
        c.fill()
    c.rectangle(0, h * 0.78, w, h * 0.22)
    gg = cairo.LinearGradient(0, h * 0.78, 0, h)
    gg.add_color_stop_rgb(0, *sk["ground"][0])
    gg.add_color_stop_rgb(1, *sk["ground"][1])
    c.set_source(gg)
    c.fill()
    r = tl.seeded(1, "flowers")
    dim = 0.45 if sk["moon"] else 1.0
    for _ in range(60):
        fx, fy = r.uniform(0, w), r.uniform(h * 0.8, h)
        c.arc(fx, fy, r.uniform(2.5, 5), 0, 2 * math.pi)
        col = r.choice(((1, 1, 1), (1, 0.85, 0.3), (1, 0.55, 0.7)))
        c.set_source_rgb(*(v * dim for v in col))
        c.fill()
    s.flush()
    _cache[key] = s
    return s


def vignette(w: int, h: int) -> cairo.ImageSurface:
    key = ("vig", w, h)
    if key not in _cache:
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        c = cairo.Context(s)
        g = cairo.RadialGradient(w / 2, h / 2, min(w, h) * 0.35, w / 2, h / 2, max(w, h) * 0.78)
        g.add_color_stop_rgba(0, 0.1, 0, 0.2, 0)
        g.add_color_stop_rgba(1, 0.1, 0, 0.2, 0.35)
        c.set_source(g)
        c.paint()
        _cache[key] = s
    return _cache[key]


def clouds(ctx, w: int, h: int, t: float, seed: int, color) -> None:
    r = tl.seeded(seed, "clouds")
    for _ in range(4):
        sp = r.uniform(8, 20)
        cx = (r.uniform(0, w) + t * sp) % (w + 300) - 150
        cy = h * r.uniform(0.08, 0.32)
        sc = r.uniform(0.7, 1.2)
        for j in range(5):
            ctx.new_sub_path()
            ctx.arc(cx + (j - 2) * 30 * sc, cy + (8 if j % 2 else 0) * sc, (26 + 7 * (j % 3)) * sc, 0, 2 * math.pi)
        ctx.set_source_rgba(*color)
        ctx.fill()


def confetti(ctx, w: int, h: int, ev: dict, t: float, seed: int) -> int:
    u = t - ev["t"]
    if u < 0 or u > ev.get("dur", 2.5):
        return 0
    r = tl.seeded(seed, "confetti", ev["t"])
    n = ev.get("n", 90)
    ref = h / 720
    x0, y0 = ev["x"] * w, ev["y"] * h
    cols = ((1, 0.3, 0.4), (1, 0.85, 0.2), (0.3, 0.8, 1), (0.5, 1, 0.5), (0.85, 0.5, 1))
    fade = min(1.0, (ev.get("dur", 2.5) - u) / 0.5)
    for _ in range(n):
        a = r.uniform(-math.pi, 0)
        sp = r.uniform(250, 650) * ref
        vx, vy = math.cos(a) * sp * 0.8, math.sin(a) * sp
        x = x0 + vx * u * (1 - 0.35 * u)
        y = y0 + vy * u + 0.5 * 700 * ref * u * u * 0.6
        rot = r.uniform(0, 6) + u * r.uniform(-10, 10)
        sz = r.uniform(5, 10) * ref
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(rot)
        ctx.scale(1, max(0.05, abs(math.cos(u * 8 + rot))))
        ctx.rectangle(-sz, -sz * 0.45, 2 * sz, sz * 0.9)
        ctx.restore()
        ctx.set_source_rgba(*r.choice(cols), fade)
        ctx.fill()
    return n


def _wrap(ctx, text: str, max_w: float) -> list[str]:
    """Перенос по словам; слово длиннее строки режется по буквам."""
    lines: list[str] = []
    line = ""
    for wd in text.split():
        while ctx.text_extents(wd)[4] > max_w and len(wd) > 1:  # «Шшшшш…» без пробелов
            cut = len(wd) - 1
            while cut > 1 and ctx.text_extents(wd[:cut])[4] > max_w:
                cut -= 1
            if line:
                lines.append(line)
                line = ""
            lines.append(wd[:cut])
            wd = wd[cut:]
        probe = (line + " " + wd).strip()
        if ctx.text_extents(probe)[4] > max_w and line:
            lines.append(line)
            line = wd
        else:
            line = probe
    if line:
        lines.append(line)
    return lines or [""]


def bubble(ctx, w: int, h: int, text: str, ax: float, ay: float, scale: float,
           taken: list | None = None, draw: bool = True, at: tuple | None = None) -> tuple:
    """Нарисовать пузырь (или только найти ему место: draw=False). Возвращает (bx, by) — где он встал."""
    """Пузырь речи с хвостиком к говорящему; текст переносится по словам; рамка не выходит за кадр."""
    ctx.select_font_face("DejaVu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    max_w = w * (0.42 if w > h else 0.62 if w == h else 0.8)
    fs = 30 * scale
    for _ in range(5):  # мельче шрифт, пока реплика не влезет в 4 строки
        ctx.set_font_size(fs)
        lines = _wrap(ctx, text, max_w)
        if len(lines) <= 4:
            break
        fs *= 0.86
    if len(lines) > 4:
        lines = lines[:4]
        lines[-1] = lines[-1].rstrip(" ,.!?…")[:-1] + "…"
    tw = min(max(ctx.text_extents(ln)[4] for ln in lines), max_w)
    pad = 18 * scale
    bw, bh = tw + 2 * pad, len(lines) * fs * 1.2 + 2 * pad - fs * 0.2
    bx = min(max(ax - bw / 2, 10), w - bw - 10)
    by = max(ay - bh - 40 * scale, 10)
    if taken:  # два пузыря одновременно — второй не должен закрывать первый
        def hits(x, y):
            return any(x < tx + tw_ + 6 and tx < x + bw + 6 and y < ty + th + 6 and ty < y + bh + 6
                       for tx, ty, tw_, th in taken)

        if hits(bx, by):
            options = [(bx, ty - bh - 10) for tx, ty, tw_, th in taken] + \
                      [(bx, ty + th + 10) for tx, ty, tw_, th in taken] + \
                      [(tx + tw_ + 10, by) for tx, ty, tw_, th in taken] + [(tx - bw - 10, by) for tx, ty, tw_, th in taken]
            for x, y in options:
                x, y = min(max(x, 10), w - bw - 10), min(max(y, 10), h - bh - 10)
                if not hits(x, y):
                    bx, by = x, y
                    break
    if at is not None:
        bx, by = at
    if taken is not None:
        taken.append((bx, by, bw, bh))
    if not draw:
        return bx, by
    r = 22 * scale
    ctx.new_path()
    ctx.arc(bx + bw - r, by + r, r, -math.pi / 2, 0)
    ctx.arc(bx + bw - r, by + bh - r, r, 0, math.pi / 2)
    tx = min(max(ax, bx + 2 * r), bx + bw - 2 * r)
    ctx.line_to(tx + 14 * scale, by + bh)
    ctx.line_to(ax, max(ay - 6 * scale, by + bh + 4))
    ctx.line_to(tx - 6 * scale, by + bh)
    ctx.arc(bx + r, by + bh - r, r, math.pi / 2, math.pi)
    ctx.arc(bx + r, by + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill_preserve()
    ctx.set_source_rgb(0.12, 0.06, 0.2)
    ctx.set_line_width(4 * scale)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()
    y = by + pad + fs * 0.85
    for ln in lines:
        ctx.move_to(bx + (bw - ctx.text_extents(ln)[4]) / 2, y)
        ctx.show_text(ln)
        y += fs * 1.2
    return bx, by


def render_frame(plan: dict, i: int, surf, stats: dict | None = None) -> None:
    w, h = plan["size"]
    ctx = cairo.Context(surf)
    ctx.set_antialias(cairo.ANTIALIAS_FAST if plan.get("fast_aa") else cairo.ANTIALIAS_DEFAULT)
    scene, t = tl.locate(plan, i)
    seed = plan["seed"]
    cam = tl.camera(scene, t)
    z = cam["zoom"]
    M = max(1.0, max(k.get("zoom", 1) for k in scene.get("camera", [{"zoom": 1}])))
    sky = SKIES.get(scene.get("bg", "meadow"), SKIES["meadow"])
    bg = bg_static(w, h, scene.get("bg", "meadow"), M)
    ox, oy = (cam["x"] - 0.5) * w, (cam["y"] - 0.5) * h
    ctx.set_source_rgb(*sky["ground"][1])  # подложка: кадр всегда закрашен целиком, без остатков прошлого
    ctx.paint()
    ctx.save()
    ctx.translate(w / 2, h / 2)
    ctx.scale(z, z)
    ctx.translate(-w / 2 - ox, -h / 2 - oy)
    ctx.save()
    ctx.scale(w / bg.get_width(), h / bg.get_height())
    ctx.set_source_surface(bg, 0, 0)
    ctx.get_source().set_filter(cairo.FILTER_BILINEAR)
    ctx.paint()
    ctx.restore()
    clouds(ctx, w, h, i / plan["fps"], seed, sky["cloud"])
    # мир: сортировка по y ног (ниже — ближе)
    items = []
    for who, look in plan["cast"].items():
        if who not in scene["place"]:
            continue
        pose, saying = tl.char_state(plan, scene, who, t)
        items.append((pose["y"], who, look, pose, saying))
    for th, spec in plan.get("things", {}).items():
        if th in scene["place"]:
            p = scene["place"][th]
            items.append((p["y"], th, spec, None, None))
    items.sort(key=lambda it: it[0])
    bubbles = []
    ref = h / 720 if w >= h else w / 720
    for _, who, look, pose, saying in items:
        if pose is None:  # 3D-предмет
            p = scene["place"][who]
            spin = 0.5 * t  # предметы всегда чуть вращаются, «spin» — быстро
            for ev in scene["events"]:
                if ev.get("who") == who and ev.get("act") == "spin" and ev["t"] <= t:
                    spin += min(t - ev["t"], ev.get("dur", 1.0)) * 2.2
            bob = math.sin(t * 2.4) * 0.08
            camd = {"cx": p["x"] * w, "cy": p["y"] * h, "f": 900 * ref, "dist": 6.0}
            mesh, flat = _mesh(look.get("shape", "gem"))
            st: dict = {}
            m3.draw_mesh(ctx, mesh, m3.rot(0.35, spin + 0.4, 0.0) * look.get("size", 1.0), np.array([0, bob, 0]),
                         camd, hexrgb(look["color"]), outline="edges", lw=3 * ref, flat=flat, stats=st)
            if stats is not None:
                stats["tri"] = stats.get("tri", 0) + st.get("tri", 0)
            r = tl.seeded(seed, who, "spark")
            for _k in range(8):  # блёстки вокруг предмета
                a = r.uniform(0, 6.28) + t * r.uniform(0.5, 1.5)
                rr = r.uniform(110, 170) * ref * look.get("size", 1.0)
                ph = (t * r.uniform(1, 2) + r.random()) % 1
                sx, sy = p["x"] * w + math.cos(a) * rr, p["y"] * h + math.sin(a) * rr * 0.6
                s = 10 * ref * math.sin(ph * math.pi)
                if s > 0.3:
                    char2d.star_path(ctx, sx, sy, s, s * 0.35, 4, 0)
                    ctx.set_source_rgba(1, 1, 0.8, 0.95)
                    ctx.fill()
            continue
        X, Y = pose["x"] * w, pose["y"] * h
        size = look.get("size", 0.42) * h / 300
        if look["kind"] == "toy":
            camd = {"cx": X, "cy": Y - 1.1 * 95 * size, "f": 95 * size * 9.0, "dist": 9.0}
            m3.toy(ctx, camd, t, hexrgb(look["color"]), y=pose["air"] / 95,
                   turn=pose["yaw"] * 0.8 + (0 if pose["facing"] > 0 else 0.6),
                   face={"open": pose["face"].get("mouth_open", 0.3)}, stats=stats)
            head = (X, Y - 300 * size * 0.62 - pose["air"] * size)
        else:
            pose = dict(pose, x=X, y=Y, scale=size)
            char2d.draw_character(ctx, {"species": look["kind"], "color": hexrgb(look["color"]),
                                        "iris": hexrgb(look.get("eyes", "#3a7bd5"))}, pose)
            head = (X, Y - (300 + pose["air"]) * size)
        if saying:
            bubbles.append((saying["say"], head))
    n = 0
    for ev in scene["events"]:
        if ev.get("fx") == "confetti":
            n += confetti(ctx, w, h, ev, t, seed)
    ctx.restore()  # камера
    # пузыри — в экранных координатах поверх мира; позиция через камеру
    taken: list = []
    placed = []
    for text, (hx, hy) in bubbles:  # сначала места, потом рисуем с конца: хвостик позднего уходит под ранний
        sx = (hx - w / 2 - ox) * z + w / 2
        sy = (hy - h / 2 - oy) * z + h / 2
        placed.append((text, sx, sy, bubble(ctx, w, h, text, sx, sy, ref, taken, draw=False)))
    for text, sx, sy, pos in reversed(placed):
        bubble(ctx, w, h, text, sx, sy, ref, None, at=pos)
    ctx.set_source_surface(vignette(w, h), 0, 0)
    ctx.paint()
    # затемнение в начале и в конце ролика
    total = sum(s["dur"] for s in plan["scenes"])
    T = i / plan["fps"]
    a = max(0.0, 1 - T / 0.4, 1 - (total - T) / 0.4)
    if a > 0:
        ctx.set_source_rgba(0, 0, 0, min(1, a))
        ctx.paint()
    surf.flush()
    if stats is not None:
        stats["particles"] = stats.get("particles", 0) + n
