"""3D-игрушки — герои robot3d, penguin3d, snowman3d: «слоёная 3D-кукла» из примитивов (каждая деталь — целиком,
сетка + контур, детали по глубине с поправкой), лицо — то же 2D-лицо, что у остальных героев (face_fn), наклейкой
на голову: точка лица проецируется на поверхность, рисунок ложится в касательную плоскость (сжимается при
повороте, наклоняется вместе с головой) и прячется, когда голова отвернулась.

Поза (model.Pose) та же, что у 2D-кукол: bob, squash (объём сохраняется), lean, yaw, руки (плечо, локоть),
ноги (бедро, колено), наклон головы, взмах крыльев, scale, alpha; моргание, эмоции и рот — в face_fn.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, Callable

import cairocffi as cairo
import numpy as np

from ..model import RGB, Pose
from ..palette import hx, luminance, mix
from .mesh import cached, lathe, lod_for_radius, lod_level, rounded_profile
from .props3d import Kit
from .render3d import (OBJECT_BUDGET, Camera3D, Obj, draw_parts, estimate_tris, outline_px, sprite_camera, stats,
                       surface_affine)
from .shade import Material

FaceFn = Callable[[Any, Any, Pose, float, float, float, float], None]

TOY_COLORS: dict[str, tuple[str, str]] = {  # (основной, акцент) по умолчанию
    "robot3d": ("#ff9f1c", "#ff3d6e"),
    "penguin3d": ("#2b3a67", "#ff3d6e"),
    "snowman3d": ("#fbfdff", "#ff3d6e"),
}
BASE_TURN = 0.28  # игрушка чуть развёрнута в сторону взгляда (как 2D-герои «в три четверти»)
INK = (0.12, 0.09, 0.16)


def _rgb(v: Any, default: str) -> RGB:
    try:
        if v is not None and len(v) >= 3:
            return (float(v[0]), float(v[1]), float(v[2]))
    except TypeError:
        pass
    return hx(default)


def _face_look(look: Any, base: str) -> Any:
    """Look для лица: у робота-3D лицо — экран с огоньками, как у 2D-робота (base «robot»)."""
    if dataclasses.is_dataclass(look) and not isinstance(look, type) and hasattr(look, "base"):
        try:
            return dataclasses.replace(look, base=base)  # type: ignore[type-var]
        except (TypeError, ValueError):
            return look
    return look


def _face_decal(face_fn: FaceFn, look: Any, pose: Pose, p: tuple[float, float, float],
                n: tuple[float, float, float], r: float, yaw_k: float = 0.6,
                before: Callable[[cairo.Context, float], None] | None = None):
    """Наклейка-лицо: в точке p (локальные координаты детали) с нормалью n; r — радиус лица в единицах мира.
    before(ctx, ppu) — что нарисовать под лицом в той же плоскости (экран робота)."""
    def draw(ctx: cairo.Context, cam: Camera3D, M: np.ndarray, T: np.ndarray) -> None:
        nn = np.asarray(n, float)
        up = np.array([0.0, 1.0, 0.0])
        right = np.cross(up, nn)
        if np.linalg.norm(right) < 1e-6:
            right = np.array([1.0, 0.0, 0.0])
        right = right / np.linalg.norm(right)
        up2 = np.cross(nn, right)
        mtx, ppu, k = surface_affine(cam, M, T, p, tuple(right), tuple(up2), tuple(nn), iso=True)
        if k < 0.2 or ppu <= 0:
            return
        fwd = M @ nn
        fwd = fwd / (np.linalg.norm(fwd) + 1e-12)
        yaw = float(max(-1.0, min(1.0, fwd[0] * yaw_k)))
        # перевести в пиксели: 1 единица рисунка = 1 пиксель по вертикали
        ctx.transform(mtx)
        ctx.scale(1.0 / ppu, 1.0 / ppu)
        alpha = min(1.0, (k - 0.2) / 0.12)
        if alpha < 1.0:
            ctx.push_group()
        if before is not None:
            ctx.save()
            before(ctx, ppu)
            ctx.restore()
        face_fn(ctx, look, dataclasses.replace(pose, yaw=yaw), 0.0, 0.0, r * ppu, yaw)
        if alpha < 1.0:
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(alpha)

    return draw


# ======================= робот =======================
def _robot_screen(w: float, h: float) -> Callable[[cairo.Context, float], None]:
    """Тёмный экран-лицо робота (в пикселях: w, h — полуширина и полувысота в единицах мира)."""
    def draw(ctx: cairo.Context, ppu: float) -> None:
        from ..draw import rrect

        W, H = w * ppu, h * ppu
        rrect(ctx, -W, -H, 2 * W, 2 * H, min(W, H) * 0.45)
        g = cairo.LinearGradient(0, -H, 0, H)
        g.add_color_stop_rgb(0, 0.1, 0.12, 0.3)
        g.add_color_stop_rgb(1, 0.03, 0.04, 0.12)
        ctx.set_source(g)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(max(1.5, ppu * 0.025))
        ctx.stroke()
        # блик стекла
        rrect(ctx, -W * 0.82, -H * 0.8, W * 0.9, H * 0.28, H * 0.14)
        ctx.set_source_rgba(1, 1, 1, 0.1)
        ctx.fill()

    return draw


def _chest_panel(t: float, accent: RGB):
    """Панель на груди робота: три огонька мигают по очереди."""
    def draw(ctx: cairo.Context, cam: Camera3D, M: np.ndarray, T: np.ndarray) -> None:
        from ..draw import rrect

        mtx, ppu, k = surface_affine(cam, M, T, (0.0, -0.05, 0.99), (1, 0, 0), (0, 1, 0), (0, 0, 1), iso=True)
        if k < 0.2:
            return
        ctx.transform(mtx)
        rrect(ctx, -0.17, -0.07, 0.34, 0.14, 0.05)
        ctx.set_source_rgb(0.2, 0.22, 0.36)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(1.6 / ppu)
        ctx.stroke()
        for i, c in enumerate((accent, (0.3, 0.95, 1.0), (1.0, 0.85, 0.3))):
            on = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 5.0 - i * 2.1))
            ctx.arc(-0.1 + i * 0.1, 0.0, 0.035, 0, 2 * math.pi)
            ctx.set_source_rgb(*mix((0.25, 0.25, 0.35), c, on))
            ctx.fill()

    return draw


def _side(arm: tuple[float, float]) -> tuple[float, float]:
    a = float(arm[0]) if math.isfinite(arm[0]) else 0.25
    e = float(arm[1]) if math.isfinite(arm[1]) else 0.3
    return max(-0.6, min(3.14, a)), max(0.0, min(2.4, e))


def _build_robot(k: Kit, pose: Pose, look: Any, face_fn: FaceFn, color: RGB, accent: RGB, fc: int) -> None:
    root = k.root
    body_m = Material(color, "candy")
    white = Material(hx("#e9eef6"), "plastic")
    chrome = Material(hx("#c3ccd9"), "chrome")
    dark = Material(hx("#5c677d"), "plastic")
    acc = Material(accent, "candy")
    box = k.sph(k.seg, 0.32)
    small = k.sph(k.lv(0.55, 10))
    capsule = cached(k.cache, ("capsule", k.lv(0.5, 10)), lambda: _capsule(k.lv(0.5, 10)))
    # ноги
    for s, leg in ((1, pose.leg_l), (-1, pose.leg_r)):
        hip = float(leg[0]) if math.isfinite(leg[0]) else 0.0
        knee = float(leg[1]) if math.isfinite(leg[1]) else 0.0
        pv = Obj(None, pos=(s * 0.17, -0.6 + 0.08 * min(knee, 1.4), 0.0), rot=(-hip * 0.8, 0.0, 0.0), parent=root)
        k.add(capsule, dark, pos=(0, -0.17, 0), scale=(0.1, 0.19, 0.1), parent=pv, bias=0.05)
        k.add(box, dark, pos=(0, -0.34, 0.05), scale=(0.14, 0.06, 0.19), parent=pv, bias=0.02)
    body = k.add(box, body_m, pos=(0, -0.27, 0), scale=(0.44, 0.35, 0.33))
    body.decals.append(_chest_panel(k.t, accent))
    # голова на «шее»: наклон головы — вокруг шеи
    neck = Obj(None, pos=(0.0, 0.08, 0.0), rot=(0.0, 0.0, -_num(pose.head_tilt, 0.0, -0.6, 0.6) * fc), parent=root)
    head = k.add(box, white, pos=(0, 0.4, 0), scale=(0.5, 0.38, 0.42), parent=neck, bias=-0.04)
    sw, sh = 0.36, 0.26
    head.decals.append(_face_decal(face_fn, _face_look(look, "robot"), pose, (0.0, 0.0, 0.995), (0.0, 0.0, 1.0),
                                   0.3, before=_robot_screen(sw, sh)))
    stalk = cached(k.cache, ("lathe", "stalk", 8), lambda: lathe(rounded_profile(1.0, -1.0, 1.0, 0.0), 8,
                                                                    convex=True))
    wob = 0.12 * math.sin(k.t * 4.0)
    ant = Obj(None, pos=(0.0, 0.78, 0.0), rot=(0.0, 0.0, wob), parent=neck)
    k.add(stalk, chrome, pos=(0, 0.06, 0), scale=(0.025, 0.07, 0.025), parent=ant, outline=0.7, bias=0.03)
    k.add(small, acc, pos=(0, 0.17, 0), scale=0.065, parent=ant, bias=0.02)
    bolt = cached(k.cache, ("lathe", "bolt", 12), lambda: lathe(rounded_profile(1.0, -1.0, 1.0, 0.4), 12,
                                                                   convex=True))
    for s in (1, -1):
        k.add(bolt, acc, pos=(s * 0.5, 0.4, 0.0), rot=(0.0, 0.0, math.pi / 2), scale=(0.08, 0.035, 0.08),
              parent=neck, bias=0.01, outline=0.8)
    # руки: плечо → локоть → кисть
    for s, arm in ((1, pose.arm_l), (-1, pose.arm_r)):
        a, e = _side(arm)
        sh_ = Obj(None, pos=(s * 0.45, -0.02, 0.0), rot=(0.0, 0.0, s * a), parent=root)
        k.add(capsule, chrome, pos=(0, -0.12, 0), scale=(0.08, 0.13, 0.08), parent=sh_, bias=-0.02)
        el = Obj(None, pos=(0.0, -0.24, 0.0), rot=(-e * 0.45, 0.0, s * e * 0.55), parent=sh_)
        k.add(capsule, chrome, pos=(0, -0.11, 0), scale=(0.075, 0.12, 0.075), parent=el, bias=-0.03)
        k.add(small, acc, pos=(0, -0.25, 0), scale=0.085, parent=el, bias=-0.04)


def _capsule(n: int):  # type: ignore[no-untyped-def]
    """Капсула высотой 2 и радиусом 1 (по y), ось — y."""
    prof = [(0.0, -1.0)]
    for i in range(1, 5):
        a = -math.pi / 2 + math.pi / 2 * i / 4
        prof.append((math.cos(a), -0.5 + 0.5 * math.sin(a)))
    for i in range(1, 5):
        a = math.pi / 2 * i / 4
        prof.append((math.cos(a), 0.5 + 0.5 * math.sin(a)))
    prof[-1] = (0.0, 1.0)
    return lathe(prof, n, convex=True)


# ======================= пингвин =======================
def _ellipse_on_sphere(cx: float, cy: float, rx: float, ry: float, n: int = 40) -> np.ndarray:
    """Контур-эллипс на передней половине единичной сферы (x, y — проекция на плоскость лица)."""
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    x = cx + rx * np.cos(a)
    y = cy + ry * np.sin(a)
    rr = np.hypot(x, y)
    k = np.where(rr > 0.97, 0.97 / np.maximum(rr, 1e-9), 1.0)  # не дальше края сферы
    x, y = x * k, y * k
    z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1)) * 1.002
    return np.stack([x, y, z], 1)


def _build_penguin(k: Kit, pose: Pose, look: Any, face_fn: FaceFn, color: RGB, accent: RGB, fc: int) -> None:
    root = k.root
    orange = Material(hx("#ff9f1c"), "toon")
    mesh = k.sph(k.seg)
    sx, sy, sz = 0.6, 0.92, 0.56
    by = -0.04
    tilt = Obj(None, pos=(0.0, -0.95, 0.0), rot=(0.0, 0.0, -_num(pose.head_tilt, 0.0, -0.6, 0.6) * 0.5 * fc),
               parent=root)
    holder = Obj(None, pos=(0.0, 0.95, 0.0), parent=tilt)
    body = k.add(mesh, Material(color, "plastic", rim=(0.5, 0.56, 0.7)), pos=(0, by, 0),
                 scale=(sx, sy, sz), parent=holder)
    # белое брюшко и «маска» лица — одним пятном с чётким краем
    white = (0.97, 0.97, 1.0)
    body.patches.append(([_ellipse_on_sphere(0.0, -0.3, 0.6, 0.6), _ellipse_on_sphere(0.0, 0.42, 0.56, 0.3)], white))
    fy = 0.42
    fz = math.sqrt(max(0.0, 1 - fy * fy))
    body.decals.append(_face_decal(face_fn, look, pose, (0.0, fy, fz), (0.0, fy * 0.3, fz), 0.27))

    def on_body(lx: float, ly: float, out: float = 0.0) -> tuple[float, float, float]:
        lz = math.sqrt(max(0.0, 1 - lx * lx - ly * ly)) + out
        return (lx * sx, by + ly * sy, lz * sz)

    cone_m = cached(k.cache, ("cone", 12), lambda: _cone(12))
    k.add(cone_m, orange, pos=on_body(0.0, 0.3, 0.12), rot=(math.pi / 2, 0.0, 0.0), scale=(0.07, 0.09, 0.06),
          parent=holder, bias=-0.5, outline=0.8)
    flap = float(pose.wing_flap) if math.isfinite(pose.wing_flap) else 0.0
    flip_m = k.sph(k.lv(0.55, 10))
    for s, arm in ((1, pose.arm_l), (-1, pose.arm_r)):
        a, _e = _side(arm)
        ang = 0.1 + a * 0.95 + 0.5 * flap
        pv = Obj(None, pos=(s * 0.5, 0.04, 0.0), rot=(0.0, 0.0, s * ang), parent=holder)
        k.add(flip_m, Material(color, "plastic", rim=(0.5, 0.56, 0.7)), pos=(0, -0.25, 0), rot=(0.0, 0.0, s * -0.1),
              scale=(0.08, 0.28, 0.17), parent=pv, bias=0.02)
    foot_m = k.sph(k.lv(0.5, 10))
    for s, leg in ((1, pose.leg_l), (-1, pose.leg_r)):
        hip = float(leg[0]) if math.isfinite(leg[0]) else 0.0
        knee = float(leg[1]) if math.isfinite(leg[1]) else 0.0
        k.add(foot_m, orange, pos=(s * 0.21, -0.95 + 0.1 * min(knee, 1.4), 0.22 + 0.2 * hip),
              rot=(0.0, s * 0.25, 0.0), scale=(0.16, 0.055, 0.24), bias=-0.3)
    scarf = Material(accent, "toon")
    ring = k.tor(1.0, 0.16, k.lv(0.8, 16), 8)
    k.add(ring, scarf, pos=(0, 0.1, 0), rot=(0.06, 0.0, 0.0), scale=(0.6, 0.5, 0.56), parent=holder,
          split=body, outline=0.85)
    tail = k.sph(k.lv(0.5, 10), 0.4)
    k.add(tail, scarf, pos=(0.22, -0.06, 0.52), rot=(0.25, 0.0, 0.25), scale=(0.075, 0.15, 0.03), parent=holder,
          bias=-0.7, outline=0.85)


def _cone(n: int):  # type: ignore[no-untyped-def]
    from .mesh import cone

    return cone(n, 1.0, 2.0, 0.2)


# ======================= снеговик =======================
def _hat_profile() -> list[tuple[float, float]]:
    return [(0.0, 0.0), (0.3, 0.0), (0.31, 0.02), (0.3, 0.04), (0.19, 0.045), (0.19, 0.27), (0.17, 0.29),
            (0.0, 0.29)]


def _build_snowman(k: Kit, pose: Pose, look: Any, face_fn: FaceFn, color: RGB, accent: RGB, fc: int) -> None:
    root = k.root
    snow = Material((0.97, 0.98, 1.0), "plastic", rim=(0.7, 0.8, 1.0))
    mesh = k.sph(k.seg)
    k.add(mesh, snow, pos=(0, -0.56, 0), scale=(0.46, 0.43, 0.44))
    mid = k.add(k.sph(k.lv(0.85, 12)), snow, pos=(0, 0.0, 0), scale=(0.34, 0.33, 0.33), bias=-0.01)
    for i, yy in enumerate((0.5, 0.05, -0.4)):
        mid.decals.append(_coal(yy, 0.085 if i else 0.08))
    neck = Obj(None, pos=(0.0, 0.25, 0.0), rot=(0.0, 0.0, -_num(pose.head_tilt, 0.0, -0.6, 0.6) * fc), parent=root)
    head = k.add(k.sph(k.lv(0.8, 12)), snow, pos=(0, 0.25, 0), scale=0.27, parent=neck, bias=-0.02)
    head.decals.append(_face_decal(face_fn, look, pose, (0.0, 0.18, 0.98), (0.0, 0.18, 0.98), 0.2))
    cone_m = cached(k.cache, ("cone", 12), lambda: _cone(12))
    k.add(cone_m, Material(hx("#ff8c1a"), "toon"), pos=(0.0, 0.24, 0.36), rot=(math.pi / 2, 0.0, 0.0),
          scale=(0.045, 0.12, 0.045), parent=neck, bias=-0.6, outline=0.8)
    hat_pv = Obj(None, pos=(0.0, 0.47, 0.0), rot=(-0.12, 0.0, 0.14), parent=neck)
    hat_m = cached(k.cache, ("lathe", "hat", k.lv(0.7, 12)), lambda: lathe(_hat_profile(), k.lv(0.7, 12)))
    k.add(hat_m, Material((0.17, 0.15, 0.24), "plastic"), parent=hat_pv, bias=-0.2)
    band = cached(k.cache, ("lathe", "band", k.lv(0.7, 12)),
                  lambda: lathe(rounded_profile(1.0, -1.0, 1.0, 0.0), k.lv(0.7, 12), convex=True))
    k.add(band, Material(color if luminance(color) < 0.75 else accent, "candy"), pos=(0.0, 0.085, 0.0),
          scale=(0.197, 0.035, 0.197), parent=hat_pv, bias=-0.21, outline=0.7)
    # руки-веточки: угол от «вниз»; у снеговика по умолчанию торчат в стороны
    stick = cached(k.cache, ("capsule", 8), lambda: _capsule(8))
    wood = Material(hx("#7a4a24"), "clay")
    for s, arm in ((1, pose.arm_l), (-1, pose.arm_r)):
        a, e = _side(arm)
        ang = 1.5 + 0.62 * (a - 0.25)
        pv = Obj(None, pos=(s * 0.28, 0.08, 0.0), rot=(0.0, 0.0, s * ang), parent=root)
        k.add(stick, wood, pos=(0, -0.2, 0), scale=(0.022, 0.22, 0.022), parent=pv, outline=0.7, bias=0.02)
        tw = Obj(None, pos=(0.0, -0.3, 0.0), rot=(0.0, 0.0, -s * (0.7 + 0.3 * e)), parent=pv)
        k.add(stick, wood, pos=(0, -0.06, 0), scale=(0.016, 0.07, 0.016), parent=tw, outline=0.7, bias=0.02)
    scarf_c = color if luminance(color) < 0.75 else accent
    scarf = Material(scarf_c, "toon")
    k.add(k.tor(1.0, 0.3, k.lv(0.8, 16), 8), scarf, pos=(0, 0.27, 0), rot=(0.1, 0.0, 0.0),
          scale=(0.27, 0.2, 0.26), split=head, outline=0.85)
    k.add(k.sph(k.lv(0.5, 10), 0.4), scarf, pos=(-0.13, 0.12, 0.25), rot=(0.25, 0.0, -0.2),
          scale=(0.065, 0.13, 0.03), bias=-0.7, outline=0.85)


def _coal(y: float, r: float):
    def draw(ctx: cairo.Context, cam: Camera3D, M: np.ndarray, T: np.ndarray) -> None:
        z = math.sqrt(max(0.0, 1 - y * y))
        mtx, ppu, k = surface_affine(cam, M, T, (0.0, y, z), (1, 0, 0), (0, z, -y), (0.0, y, z))
        if k < 0.15:
            return
        ctx.transform(mtx)
        ctx.arc(0, 0, r, 0, 2 * math.pi)
        g = cairo.RadialGradient(-r * 0.3, -r * 0.35, r * 0.05, 0, 0, r)
        g.add_color_stop_rgb(0, 0.42, 0.4, 0.5)
        g.add_color_stop_rgb(1, 0.1, 0.09, 0.14)
        ctx.set_source(g)
        ctx.fill()

    return draw


BUILDERS = {"robot3d": _build_robot, "penguin3d": _build_penguin, "snowman3d": _build_snowman}


# ======================= поза и рисование =======================
def _num(v: float, default: float, lo: float, hi: float) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return max(lo, min(hi, v))


def _toy_colors(base: str, look: Any) -> tuple[RGB, RGB]:
    dc, da = TOY_COLORS[base]
    color = _rgb(getattr(look, "color", None), dc)
    accent = _rgb(getattr(look, "accent", None), da)
    if base == "penguin3d" and luminance(color) > 0.55:  # белому пингвину не видно брюшка — тёмная спинка
        color = mix(color, hx(dc), 0.7)
    if base == "robot3d" and luminance(color) > 0.8:  # белый корпус сливается с белой головой
        color = mix(color, (0.55, 0.62, 0.78), 0.4)
    return color, accent


def toy_frame(pose: Pose, x: float, y: float, height_px: float) -> tuple[float, float, float]:
    """(центр x, центр y, рост с учётом scale) — куда ставить спрайт-камеру игрушки."""
    scale = _num(pose.scale, 1.0, 0.05, 3.0)
    H = height_px * scale
    bob = _num(pose.bob, 0.0, -400.0, 100.0) / 300.0 * height_px
    return x, y + bob - H / 2, H


def toy_head_anchor(look: Any, pose: Pose, x: float, y: float, height_px: float, facing: int) -> tuple[float, float]:
    """Точка чуть выше макушки игрушки в пикселях (для пузыря реплики)."""
    cx, cy, H = toy_frame(pose, x, y, height_px)
    return cx, cy - H * 0.53


def draw_toy(ctx: cairo.Context, look: Any, pose: Pose, x: float, y: float, height_px: float, facing: int,
             cache: dict, face_fn: FaceFn) -> None:
    base = getattr(look, "base", "robot3d")
    if base not in BUILDERS:
        base = "robot3d"
    alpha = _num(pose.alpha, 1.0, 0.0, 1.0)
    if alpha <= 0.01 or not (height_px > 4) or not all(map(math.isfinite, (x, y, height_px))):
        return
    cx, cy, H = toy_frame(pose, x, y, height_px)
    if H < 4:
        return
    fc = 1 if facing >= 0 else -1
    squash = _num(pose.squash, 1.0, 0.6, 1.4)
    lean = _num(pose.lean, 0.0, -0.6, 0.6)
    yaw = _num(pose.yaw, 0.0, -1.5, 1.5)
    color, accent = _toy_colors(base, look)
    cam = sprite_camera(cx, cy, H)
    st = stats(cache)
    seg = lod_for_radius(H * 0.25, "normal", lo=10, hi=28)
    while True:
        feet = Obj(None, pos=(0.0, -1.0, 0.0), scale=(1 / math.sqrt(squash), squash, 1 / math.sqrt(squash)))
        up = Obj(None, pos=(0.0, 1.0, 0.0), parent=feet)
        pelvis = Obj(None, pos=(0.0, -0.45, 0.0), rot=(0.0, 0.0, -lean * fc), parent=up)
        back = Obj(None, pos=(0.0, 0.45, 0.0), parent=pelvis)
        root = Obj(None, rot=(0.0, fc * (BASE_TURN + 0.9 * yaw), 0.0), parent=back)
        kit = Kit(cache, seg, Material(color), _num(pose.t, 0.0, -1e6, 1e6), root)
        BUILDERS[base](kit, pose, look, face_fn, color, accent, fc)
        if estimate_tris(kit.parts) <= OBJECT_BUDGET or seg <= 8:
            break
        lower = lod_level(seg - 1)
        if lower >= seg:
            break
        seg = lower
    st["objects"] += 1
    if alpha < 1.0:
        ctx.push_group()
    draw_parts(ctx, cam, kit.parts, outline_px(H * 0.9), st)
    if alpha < 1.0:
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(alpha)

