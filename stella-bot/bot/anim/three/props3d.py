"""3D-предметы (catalog.PROPS_3D): примитивы и составные (подарок, торт, шарик, кубок, планета, пончик, ракета,
ёлка, диско-шар, кубик, монета…). У каждого — красивые цвет и материал по умолчанию; цвет и материал из сценария
красят «главную» часть, мелкие детали (лента, свечи, окошко) остаются своими.

Предмет вписан в y ∈ [-1, 1] (size_px — его высота на экране) и рисуется своей спрайт-камерой как «слоёная
кукла» (render3d.draw_parts). Анимации: spin, float, bounce, pulse, wobble, swing — фаза своя у каждого предмета
(по его id), всё — чистая функция времени.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import cairocffi as cairo
import numpy as np

from ..ease import hash01, noise1, rng
from ..model import RGB, PropSpec
from ..palette import hx, lighten, mix, mul
from .mesh import (Extrusion, circle_contour, cone, facet_sphere, gem, heart_contour, lathe, lod_for_radius,
                   lod_level, rounded_profile, sphere, star_contour, torus)
from .mesh import cached as _cached
from .render3d import (OBJECT_BUDGET, Camera3D, Obj, draw_parts, estimate_tris, outline_px, sprite_camera, stats,
                       surface_affine, world)
from .shade import Material, material

Draw2D = Callable[[cairo.Context, Camera3D], None]


# ======================= набор деталей =======================
@dataclass
class Kit:
    """Всё, что нужно сборщику предмета: кеш сеток, детализация, главный материал, время."""

    cache: dict
    seg: int  # сегментов по кругу у главной детали
    main: Material
    t: float
    root: Obj
    parts: list[Obj] = field(default_factory=list)
    under: list[Draw2D] = field(default_factory=list)  # 2D до деталей (нитка шарика, пламя ракеты)
    over: list[Draw2D] = field(default_factory=list)  # 2D поверх (огоньки свечей, искры)
    seed: int = 0

    def lv(self, frac: float, lo: int = 8) -> int:
        return lod_level(max(lo, self.seg * frac))

    def sph(self, n: int, e: float = 1.0):  # type: ignore[no-untyped-def]
        return _cached(self.cache, ("sphere", n, e), lambda: sphere(n, e=e))

    def tor(self, R: float, r: float, n: int, m: int | None = None):  # type: ignore[no-untyped-def]
        m = m if m is not None else max(6, n // 2)
        return _cached(self.cache, ("torus", R, r, n, m), lambda: torus(R, r, n, m))

    def lat(self, name: str, n: int, profile: Callable[[], list[tuple[float, float]]], convex: bool = False):
        return _cached(self.cache, ("lathe", name, n), lambda: lathe(profile(), n, convex=convex))

    def add(self, shape, mat: Material | None = None, pos=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0),  # type: ignore[no-untyped-def]
            scale=(1.0, 1.0, 1.0), parent: Obj | None = None, **kw) -> Obj:
        if isinstance(scale, (int, float)):
            scale = (scale, scale, scale)
        o = Obj(shape, mat or self.main, pos=pos, rot=rot, scale=scale, parent=parent or self.root, **kw)
        self.parts.append(o)
        return o

    def screen(self, o: Obj, cam: Camera3D, p: tuple[float, float, float]) -> tuple[float, float, float]:
        """Точка детали (локальные координаты) → экран (x, y) и глубина."""
        M, T = world(o)
        P = M @ np.asarray(p, float) + T
        s = cam.project(P[None])[0]
        return float(s[0]), float(s[1]), float(cam.depth(P[None])[0])


def _m(color: RGB | str, kind: str = "plastic", **kw) -> Material:  # type: ignore[no-untyped-def]
    c = hx(color) if isinstance(color, str) else color
    return Material(c, kind, **kw)  # type: ignore[arg-type]


# ======================= наклейки =======================
def _pip_decal(n: int, half: float, axis: tuple[float, float, float], up: tuple[float, float, float]):
    """Точки игрального кубика на грани с нормалью axis (половина ребра half)."""
    nrm = np.asarray(axis, float)
    v = np.asarray(up, float)
    u = np.cross(v, nrm)
    s = half * 0.42
    layout = {1: [(0, 0)], 2: [(-1, -1), (1, 1)], 3: [(-1, -1), (0, 0), (1, 1)],
              4: [(-1, -1), (1, -1), (-1, 1), (1, 1)], 5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)],
              6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)]}[n]

    def draw(ctx: cairo.Context, cam: Camera3D, M: np.ndarray, T: np.ndarray) -> None:
        mtx, ppu, k = surface_affine(cam, M, T, tuple(nrm * half * 0.995), tuple(u), tuple(v), tuple(nrm))
        if k < 0.12:
            return
        ctx.transform(mtx)
        r = half * (0.2 if n == 1 else 0.13)
        for px, py in layout:
            ctx.new_sub_path()
            ctx.arc(px * s, py * s, r, 0, 2 * math.pi)
        col = (0.9, 0.16, 0.3) if n == 1 else (0.16, 0.12, 0.26)
        ctx.set_source_rgba(*col, min(1.0, (k - 0.12) * 6))
        ctx.fill()

    return draw


def _coin_decal(depth: float, radius: float, color: RGB):
    """Чеканка монеты: кольцо и звезда на видимой плоской стороне."""
    star = star_contour(radius * 0.5, 0.45)
    ring = circle_contour(radius * 0.78, 40)

    def draw(ctx: cairo.Context, cam: Camera3D, M: np.ndarray, T: np.ndarray) -> None:
        for zs in (1.0, -1.0):
            nrm = (0.0, 0.0, zs)
            mtx, ppu, k = surface_affine(cam, M, T, (0.0, 0.0, zs * depth / 2), (zs, 0.0, 0.0), (0.0, 1.0, 0.0), nrm)
            if k < 0.05:
                continue
            ctx.save()
            ctx.transform(mtx)
            lw = 1.4 / max(ppu, 1e-3)
            ctx.new_path()
            for x, y in ring.tolist():
                ctx.line_to(x, -y)
            ctx.close_path()
            ctx.set_source_rgba(*mul(color, 0.62), 0.9)
            ctx.set_line_width(lw * 1.6)
            ctx.stroke()
            ctx.new_path()
            for x, y in star.tolist():
                ctx.line_to(x, -y)
            ctx.close_path()
            g = cairo.LinearGradient(0, -radius * 0.5, 0, radius * 0.5)
            g.add_color_stop_rgb(0, *lighten(color, 0.35))
            g.add_color_stop_rgb(1, *mul(color, 0.78))
            ctx.set_source(g)
            ctx.fill_preserve()
            ctx.set_source_rgba(*mul(color, 0.5), 1.0)
            ctx.set_line_width(lw * 1.2)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke()
            ctx.restore()

    return draw


def _star_decal(p: tuple[float, float, float], r: float, color: RGB):
    """Звезда-эмблема на выпуклой поверхности (кубок)."""
    def draw(ctx: cairo.Context, cam: Camera3D, M: np.ndarray, T: np.ndarray) -> None:
        mtx, ppu, k = surface_affine(cam, M, T, p, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        if k < 0.2:
            return
        ctx.transform(mtx)
        pts = star_contour(r, 0.45)
        ctx.new_path()
        for x, y in pts.tolist():
            ctx.line_to(x, -y)
        ctx.close_path()
        ctx.set_source_rgb(*color)
        ctx.fill_preserve()
        ctx.set_source_rgb(0.12, 0.09, 0.16)
        ctx.set_line_width(1.6 / max(ppu, 1e-3))
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()

    return draw


def _window_decal(p: tuple[float, float, float], r: float):
    """Иллюминатор ракеты: стекло с бликом в металлической оправе."""
    def draw(ctx: cairo.Context, cam: Camera3D, M: np.ndarray, T: np.ndarray) -> None:
        mtx, ppu, k = surface_affine(cam, M, T, p, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        if k < 0.2:
            return
        ctx.transform(mtx)
        lw = 1.8 / max(ppu, 1e-3)
        ctx.arc(0, 0, r, 0, 2 * math.pi)
        ctx.set_source_rgb(0.8, 0.85, 0.95)
        ctx.fill_preserve()
        ctx.set_source_rgb(0.12, 0.09, 0.16)
        ctx.set_line_width(lw)
        ctx.stroke()
        g = cairo.RadialGradient(-r * 0.3, -r * 0.3, r * 0.05, 0, 0, r * 0.75)
        g.add_color_stop_rgb(0, 0.75, 0.95, 1.0)
        g.add_color_stop_rgb(1, 0.15, 0.45, 0.85)
        ctx.arc(0, 0, r * 0.72, 0, 2 * math.pi)
        ctx.set_source(g)
        ctx.fill_preserve()
        ctx.set_source_rgb(0.12, 0.09, 0.16)
        ctx.set_line_width(lw * 0.8)
        ctx.stroke()
        ctx.arc(-r * 0.25, -r * 0.25, r * 0.16, 0, 2 * math.pi)
        ctx.set_source_rgba(1, 1, 1, 0.85)
        ctx.fill()

    return draw


def _sprinkles(seed: int, R: float, r: float, ice_top: Callable[[float], float]):
    """Посыпка пончика: короткие цветные палочки в точках глазури (видны только те, что смотрят на камеру)."""
    rnd = rng(seed, "sprinkles")
    cols = [hx(c) for c in ("#ffffff", "#ffd23f", "#3ec1ff", "#7cdf6b", "#b48cff", "#ff3b3b")]
    items = []
    for i in range(26):
        u = rnd.uniform(0, 2 * math.pi)
        v = rnd.uniform(0.25, 1.35)  # верх тора (v=π/2 — макушка)
        if math.sin(v) < ice_top(u) + 0.15:
            continue
        cu, su = math.cos(u), -math.sin(u)
        cv, sv = math.cos(v), math.sin(v)
        p = ((R + r * cv) * cu, r * sv, (R + r * cv) * su)
        n = (cv * cu, sv, cv * su)
        tu = (-su, 0.0, cu)  # касательная вдоль кольца
        tv = np.cross(n, tu)
        items.append((p, n, tu, tuple(tv), rnd.uniform(0, math.pi), cols[i % len(cols)]))

    def draw(ctx: cairo.Context, cam: Camera3D, M: np.ndarray, T: np.ndarray) -> None:
        for p, n, tu, tv, ang, col in items:
            mtx, ppu, k = surface_affine(cam, M, T, p, tu, tv, n)
            if k < 0.25:
                continue
            ctx.save()
            ctx.transform(mtx)
            ctx.rotate(ang)
            L = r * 0.32
            ctx.move_to(-L / 2, 0)
            ctx.line_to(L / 2, 0)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_width(r * 0.13)
            ctx.set_source_rgb(*col)
            ctx.stroke()
            ctx.restore()

    return draw


# ======================= 2D-эффекты у предметов =======================
def _flame(ctx: cairo.Context, x: float, y: float, s: float, t: float, seed: float, down: bool = False) -> None:
    """Язычок пламени: капля с радиальным градиентом (жёлтая середина → оранжевый → красный край), дрожит."""
    fl = 1.0 + 0.18 * noise1(t * 9.0 + seed * 10, 3)
    sway = 0.18 * noise1(t * 6.0 + seed * 20, 5)
    h = s * 1.9 * fl
    ctx.save()
    ctx.translate(x, y)
    if down:
        ctx.scale(1, -1)
    ctx.move_to(0, 0)
    ctx.curve_to(s * 0.9, -s * 0.2, s * 0.6 + sway * s, -h * 0.6, sway * s * 2, -h)
    ctx.curve_to(-s * 0.6 + sway * s, -h * 0.6, -s * 0.9, -s * 0.2, 0, 0)
    ctx.close_path()
    g = cairo.RadialGradient(0, -h * 0.28, s * 0.1, 0, -h * 0.3, h * 0.75)
    g.add_color_stop_rgb(0, 1.0, 0.98, 0.75)
    g.add_color_stop_rgb(0.35, 1.0, 0.82, 0.25)
    g.add_color_stop_rgb(0.75, 1.0, 0.45, 0.12)
    g.add_color_stop_rgb(1.0, 0.92, 0.2, 0.15)
    ctx.set_source(g)
    ctx.fill()
    ctx.restore()
    # ореол
    gg = cairo.RadialGradient(x, y - (h * 0.4 if not down else -h * 0.4), 0, x, y - (h * 0.4 if not down else -h * 0.4),
                              h * 1.1)
    gg.add_color_stop_rgba(0, 1.0, 0.85, 0.4, 0.35)
    gg.add_color_stop_rgba(1, 1.0, 0.6, 0.2, 0.0)
    ctx.set_source(gg)
    ctx.arc(x, y - (h * 0.4 if not down else -h * 0.4), h * 1.1, 0, 2 * math.pi)
    ctx.fill()


def _sparkle(ctx: cairo.Context, x: float, y: float, r: float, alpha: float) -> None:
    from ..draw import sparkle

    if r < 0.5 or alpha <= 0.01:
        return
    g = cairo.RadialGradient(x, y, 0, x, y, r * 1.2)
    g.add_color_stop_rgba(0, 1, 1, 1, 0.5 * alpha)
    g.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(g)
    ctx.arc(x, y, r * 1.2, 0, 2 * math.pi)
    ctx.fill()
    sparkle(ctx, x, y, r)
    ctx.set_source_rgba(1, 1, 1, alpha)
    ctx.fill()


# ======================= сборщики предметов =======================
# (цвет по умолчанию, материал по умолчанию, наклон к зрителю, поворот вокруг вертикали)
DEFAULTS: dict[str, tuple[str, str, float, float]] = {
    "sphere": ("#3ec1ff", "plastic", 0.25, 0.5),
    "cube": ("#ff5d8f", "candy", 0.42, 0.62),
    "torus": ("#b48cff", "plastic", 1.0, 0.2),
    "cylinder": ("#2ec4b6", "plastic", 0.35, 0.3),
    "cone": ("#ff9f1c", "plastic", 0.3, 0.0),
    "gem": ("#b06bff", "gem", 0.38, 0.25),
    "star": ("#ffd23f", "gold", 0.08, 0.38),
    "heart": ("#ff3d6e", "candy", 0.06, 0.32),
    "coin": ("#ffd23f", "gold", 0.1, 0.55),
    "dice": ("#fbfbff", "plastic", 0.42, 0.6),
    "planet": ("#8a6bff", "plastic", 0.32, 0.4),
    "gift": ("#ff4d6d", "candy", 0.34, 0.55),
    "cake": ("#ff9ecf", "candy", 0.38, 0.3),
    "balloon": ("#ff3b3b", "candy", 0.05, 0.3),
    "donut": ("#ff7eb6", "candy", 0.85, 0.2),
    "trophy": ("#ffd23f", "gold", 0.2, 0.35),
    "disco_ball": ("#e8e4ff", "chrome", 0.15, 0.3),
    "rocket": ("#f4f6ff", "plastic", 0.12, 0.45),
    "christmas_tree": ("#3ec46d", "toon", 0.22, 0.2),
    "text3d": ("#ffd23f", "gold", 0.0, 0.0),
}


def _b_sphere(k: Kit) -> None:
    k.add(k.sph(k.seg), scale=0.98)


def _b_cube(k: Kit) -> None:
    k.add(k.sph(k.seg, 0.28), scale=0.64)


def _b_torus(k: Kit) -> None:
    k.add(k.tor(1.0, 0.42, k.seg, max(8, k.seg // 2)), scale=0.7)


def _b_cylinder(k: Kit) -> None:
    k.add(k.lat("cyl", k.seg, lambda: rounded_profile(0.62, -0.84, 0.84, 0.12), convex=True))


def _b_cone(k: Kit) -> None:
    k.add(_cached(k.cache, ("cone", k.seg), lambda: cone(k.seg, 0.78, 1.8)))


def _b_gem(k: Kit) -> None:
    k.add(_cached(k.cache, ("gem", 10), lambda: gem(10)), pos=(0, 0.36, 0), scale=1.0)
    t = k.t

    def glint(ctx: cairo.Context, cam: Camera3D) -> None:
        ph = (t * 0.45 + k.seed * 0.17) % 1.0
        if ph < 0.25:
            a = math.sin(ph / 0.25 * math.pi)
            x, y, _ = k.screen(k.parts[0], cam, (-0.35, 0.25, 0.4))
            _sparkle(ctx, x, y, cam.px_per_unit() * 0.32 * a, a)

    k.over.append(glint)


def _b_star(k: Kit) -> None:
    ex = _cached(k.cache, ("ex_star",), lambda: Extrusion([star_contour(1.0, 0.48)], 0.36, 0.08).build())
    k.add(ex, pos=(0, -0.04, 0), scale=0.98)


def _b_heart(k: Kit) -> None:
    ex = _cached(k.cache, ("ex_heart",), lambda: Extrusion([heart_contour(56)], 0.42, 0.1).build())
    k.add(ex, scale=1.08)


def _b_coin(k: Kit) -> None:
    ex = _cached(k.cache, ("ex_coin",), lambda: Extrusion([circle_contour(0.95, 56)], 0.2, 0.06).build())
    o = k.add(ex)
    o.decals.append(_coin_decal(0.2, 0.89, tuple(k.main.color) if k.main.kind != "gold" else (1.0, 0.8, 0.3)))


def _b_dice(k: Kit) -> None:
    half = 0.62
    o = k.add(k.sph(k.seg, 0.22), scale=half)
    for n, ax, up in ((1, (0, 0, 1), (0, 1, 0)), (6, (0, 0, -1), (0, 1, 0)), (2, (0, 1, 0), (0, 0, -1)),
                      (5, (0, -1, 0), (0, 0, 1)), (3, (1, 0, 0), (0, 1, 0)), (4, (-1, 0, 0), (0, 1, 0))):
        o.decals.append(_pip_decal(n, 1.0, ax, up))


def _bands_vcolor(m, base: RGB, seed: int) -> np.ndarray:  # type: ignore[no-untyped-def]
    """Полосы планеты по широте (чуть волнистые)."""
    y = m.v[:, 1]
    ang = np.arctan2(m.v[:, 2], m.v[:, 0])
    w = y + 0.06 * np.sin(ang * 3 + seed)
    b = np.asarray(base, float)
    light = np.asarray(lighten(base, 0.35))
    dark = np.asarray(mix(base, (0.2, 0.1, 0.4), 0.45))
    band = np.clip(np.sin(w * 6.0) * 2.0, 0, 1)
    band2 = np.clip((np.abs(w + 0.25) - 0.09) / 0.05, 0, 1)
    col = b[None] * (1 - band[:, None] * 0.75) + light[None] * band[:, None] * 0.75
    col = col * band2[:, None] + dark[None] * (1 - band2[:, None])
    return col


def _b_planet(k: Kit) -> None:
    mesh = k.sph(k.seg)
    base = tuple(k.main.color)
    vc = _cached(k.cache, ("planet_vc", k.seg, base), lambda: _bands_vcolor(mesh, base, 1))
    body = k.add(mesh, Material(base, k.main.kind, vcolor=vc), scale=0.62)
    ring_m = k.tor(1.0, 0.16, k.lv(1.0, 16), 6)
    rv = ring_m.v
    rr = np.hypot(rv[:, 0], rv[:, 2])
    ring_c = hx("#ffd23f")
    rvc = np.where((rr < 1.0)[:, None], np.asarray(lighten(ring_c, 0.35))[None], np.asarray(ring_c)[None])
    k.add(ring_m, Material(ring_c, "toon", vcolor=rvc), rot=(0.18, 0.0, 0.32), scale=(0.98, 0.22, 0.98),
          split=body, outline=0.8)


def _ribbon_bands(wa: float, wb: float):
    """Ленты подарка на скруглённом кубе (локальный куб [-1, 1]³): полоса |x| < wa вокруг через перед и верх
    и полоса |z| < wb вокруг через бока и верх. На каждой видимой грани — прямоугольник ленты в её плоскости."""
    def faces(M: np.ndarray, T: np.ndarray, cam: Camera3D):  # type: ignore[no-untyped-def]
        loops, lines = [], []
        Minv = np.linalg.inv(M)
        for ax in range(3):
            for sg in (-1.0, 1.0):
                n = np.zeros(3)
                n[ax] = sg
                c = M @ n + T
                nw = n @ Minv
                if float(nw @ (cam.pos - c)) <= 0:
                    continue
                o1, o2 = [a for a in range(3) if a != ax]
                for band_ax, w in ((0, wa), (2, wb)):
                    if band_ax == ax:
                        continue  # эта лента обходит грань стороной
                    other = o2 if band_ax == o1 else o1
                    rect = []
                    for u, v in ((-w, -1.0), (w, -1.0), (w, 1.0), (-w, 1.0)):
                        p = np.zeros(3)
                        p[ax] = sg * 1.004
                        p[band_ax] = u
                        p[other] = v
                        rect.append(p)
                    rect_a = np.array(rect)
                    loops.append(rect_a)
                    # края ленты — тонкой линией, не доходя до скруглённых рёбер куба
                    lines.append(rect_a[[0, 3]] * np.where(np.arange(3) == other, 0.84, 1.0))
                    lines.append(rect_a[[1, 2]] * np.where(np.arange(3) == other, 0.84, 1.0))
        return loops, lines

    return faces


def _b_gift(k: Kit) -> None:
    box = k.add(k.sph(k.seg, 0.25), pos=(0, -0.22, 0), scale=(0.7, 0.56, 0.7))
    rib_c = hx("#ffd23f") if np.linalg.norm(np.asarray(k.main.color) - np.asarray(hx("#ffd23f"))) > 0.25 \
        else hx("#ff3d6e")
    box.patches.append((_ribbon_bands(0.2, 0.2), rib_c))
    rib = _m(rib_c, "candy")
    loop = k.tor(1.0, 0.36, k.lv(0.6, 12), 8)
    for s in (-1, 1):
        k.add(loop, rib, pos=(s * 0.2, 0.47, 0.0), rot=(math.pi / 2, 0.0, s * 0.55), scale=(0.2, 0.2, 0.15),
              bias=-0.3)
    k.add(k.sph(k.lv(0.5)), rib, pos=(0, 0.38, 0.0), scale=0.11, bias=-0.35)


def _cake_vcolor(m, body: RGB, icing: RGB, top: float, drip: float, waves: int) -> np.ndarray:  # type: ignore[no-untyped-def]
    ang = np.arctan2(m.v[:, 2], m.v[:, 0])
    edge = top - 0.05 - drip * np.clip(np.sin(ang * waves) * 0.8 + 0.4 * np.sin(ang * waves * 2 + 1.3), 0, 1)
    k = np.clip((m.v[:, 1] - edge) / 0.025, 0, 1)
    return np.asarray(body)[None] * (1 - k[:, None]) + np.asarray(icing)[None] * k[:, None]


def _b_cake(k: Kit) -> None:
    body = tuple(k.main.color)
    cream = hx("#fff6ea")
    n = k.seg
    m1 = k.lat("cake1", n, lambda: rounded_profile(0.82, -0.92, -0.28, 0.07, rows=8), convex=True)
    m2 = k.lat("cake2", n, lambda: rounded_profile(0.58, -0.3, 0.2, 0.07, rows=7), convex=True)
    vc1 = _cached(k.cache, ("cake_vc1", n, body), lambda: _cake_vcolor(m1, body, cream, -0.28, 0.2, 7))
    vc2 = _cached(k.cache, ("cake_vc2", n, body), lambda: _cake_vcolor(m2, cream, body, 0.2, 0.17, 6))
    k.add(m1, Material(body, k.main.kind, vcolor=vc1))
    k.add(m2, Material(body, k.main.kind, vcolor=vc2), bias=-0.05)
    cm = k.lat("candle", k.lv(0.4, 8), lambda: rounded_profile(1.0, -1.0, 1.0, 0.25), convex=True)
    candles = []
    for i, (ang, col) in enumerate(((0.35, "#3ec1ff"), (2.45, "#ffd23f"), (4.4, "#7cdf6b"))):
        x, z = 0.3 * math.cos(ang), -0.3 * math.sin(ang)
        c = k.add(cm, _m(col, "candy"), pos=(x, 0.36, z), scale=(0.05, 0.16, 0.05), bias=-0.6, outline=0.7)
        candles.append((c, i))
    t = k.t

    def flames(ctx: cairo.Context, cam: Camera3D) -> None:
        ppu = cam.px_per_unit()
        for c, i in sorted(candles, key=lambda ci: -k.screen(ci[0], cam, (0, 1, 0))[2]):
            x, y, _ = k.screen(c, cam, (0, 1.05, 0))
            _flame(ctx, x, y, ppu * 0.06, t, i * 0.37 + k.seed)

    k.over.append(flames)


def _b_balloon(k: Kit) -> None:
    k.add(k.sph(k.seg), pos=(0, 0.24, 0), scale=(0.62, 0.74, 0.62))
    knot = k.add(_cached(k.cache, ("cone", 10), lambda: cone(10, 1.0, 2.0, 0.2)), pos=(0, -0.55, 0),
                 rot=(math.pi, 0, 0), scale=(0.09, 0.06, 0.09), bias=0.05, outline=0.8)
    t = k.t

    def string(ctx: cairo.Context, cam: Camera3D) -> None:
        x0, y0, _ = k.screen(knot, cam, (0, 1.0, 0))
        ppu = cam.px_per_unit()
        L = ppu * 0.45
        sw = 0.12 * ppu * math.sin(t * 2.1 + k.seed * 3)
        ctx.move_to(x0, y0)
        ctx.curve_to(x0 + sw, y0 + L * 0.35, x0 - sw, y0 + L * 0.7, x0 + sw * 0.5, y0 + L)
        ctx.set_source_rgb(0.12, 0.09, 0.16)
        ctx.set_line_width(max(1.2, ppu * 0.012))
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()

    k.under.append(string)


def _b_donut(k: Kit) -> None:
    R, r = 1.0, 0.5
    mesh = k.tor(R, r, k.seg, max(10, k.seg // 2))
    icing = tuple(k.main.color)
    dough = hx("#e8a96a")

    def top_edge(u: float) -> float:
        return -0.15 + 0.22 * max(0.0, math.sin(u * 5 + 1.0)) ** 2

    def vcol() -> np.ndarray:
        v = mesh.v
        u = np.arctan2(-v[:, 2], v[:, 0])
        sv = v[:, 1] / r
        edge = -0.15 + 0.22 * np.clip(np.sin(u * 5 + 1.0), 0, 1) ** 2
        kk = np.clip((sv - edge) / 0.12, 0, 1)
        return np.asarray(dough)[None] * (1 - kk[:, None]) + np.asarray(icing)[None] * kk[:, None]

    vc = _cached(k.cache, ("donut_vc", k.seg, icing), vcol)
    o = k.add(mesh, Material(icing, k.main.kind, vcolor=vc), scale=0.62)
    o.decals.append(_sprinkles(k.seed, R, r, top_edge))


def _trophy_profile() -> list[tuple[float, float]]:
    cup = []
    for i in range(9):  # чаша: от ножки к краю
        a = i / 8
        cup.append((0.14 + 0.5 * math.sin(a * math.pi / 2) ** 0.8, -0.28 + 1.0 * a))
    return [(0.0, -0.78), (0.42, -0.78), (0.44, -0.74), (0.3, -0.68), (0.13, -0.6), (0.1, -0.45), (0.13, -0.36)] + \
        cup[1:] + [(0.66, 0.73), (0.6, 0.76), (0.54, 0.62), (0.44, 0.55), (0.33, 0.5), (0.22, 0.46), (0.11, 0.43),
                   (0.0, 0.42)]  # дно чаши — мелкими поясами: длинные рёбра ломают проверку перекрытия контура


def _b_trophy(k: Kit) -> None:
    cup = k.add(k.lat("trophy", k.seg, _trophy_profile))
    k.add(k.sph(k.lv(0.6), 0.3), _m("#4b3a8c", "plastic"), pos=(0, -0.89, 0), scale=(0.52, 0.11, 0.42), bias=0.1)
    ring = k.tor(1.0, 0.24, k.lv(0.7, 12), 8)
    for s in (-1, 1):
        k.add(ring, None, pos=(s * 0.6, 0.36, 0.0), rot=(math.pi / 2, 0.0, 0.0), scale=(0.24, 0.24, 0.3))
    col = tuple(k.main.color)
    emblem = mul(col, 0.82) if k.main.kind != "gold" else (0.98, 0.62, 0.12)
    cup.decals.append(_star_decal((0.0, 0.28, 0.49), 0.17, emblem))


def _b_disco(k: Kit) -> None:
    nu = max(16, min(28, k.seg))
    mesh = _cached(k.cache, ("facet", nu), lambda: facet_sphere(nu, max(10, nu * 3 // 5)))
    ball = k.add(mesh, pos=(0, -0.06, 0), scale=0.88, grout=True)
    k.add(k.lat("cap", 12, lambda: rounded_profile(1.0, -1.0, 1.0, 0.3), convex=True),
          _m("#c3ccd9", "chrome"), pos=(0, 0.86, 0), scale=(0.12, 0.07, 0.12), bias=0.2)
    rnd = rng(k.seed, "disco")
    spots = [(rnd.uniform(0, 2 * math.pi), rnd.uniform(0.6, 2.4), rnd.uniform(0, 1)) for _ in range(7)]
    t = k.t

    def sparkles(ctx: cairo.Context, cam: Camera3D) -> None:
        M, T = world(ball)
        ppu = cam.px_per_unit()
        for u, v, ph in spots:
            n = np.array([math.sin(v) * math.cos(u), math.cos(v), -math.sin(v) * math.sin(u)])
            P = M @ n + T
            nw = M @ n
            facing = float(nw[2] / (np.linalg.norm(nw) + 1e-9))
            if facing < 0.3:
                continue
            a = max(0.0, math.sin((t * 1.3 + ph) * 2 * math.pi)) ** 3
            s = cam.project(P[None])[0]
            _sparkle(ctx, float(s[0]), float(s[1]), ppu * 0.17 * a, a)

    k.over.append(sparkles)


def _rocket_body() -> list[tuple[float, float]]:
    return [(0.0, -0.6), (0.26, -0.6), (0.34, -0.48), (0.38, -0.25), (0.39, 0.0), (0.37, 0.2), (0.33, 0.38),
            (0.3, 0.46), (0.0, 0.46)]


def _rocket_nose() -> list[tuple[float, float]]:
    pts = [(0.0, 0.4), (0.305, 0.4)]
    for i in range(1, 8):
        a = i / 8
        pts.append((0.305 * math.cos(a * math.pi / 2) ** 0.9, 0.42 + 0.5 * math.sin(a * math.pi / 2) ** 1.1))
    return pts + [(0.0, 0.94)]


def _b_rocket(k: Kit) -> None:
    body = k.add(k.lat("rocket_body", k.seg, _rocket_body, convex=True))
    red = _m("#ff3b3b", "candy")
    k.add(k.lat("rocket_nose", k.seg, _rocket_nose, convex=True), red, bias=-0.05)
    k.add(k.lat("rocket_nozzle", k.lv(0.6), lambda: rounded_profile(1.0, -1.0, 1.0, 0.2), convex=True),
          _m("#5c677d", "chrome"), pos=(0, -0.66, 0), scale=(0.2, 0.08, 0.2), bias=0.05)
    fin = _cached(k.cache, ("ex_fin",), lambda: Extrusion(
        [np.array([(0.0, 0.05), (0.0, -0.33), (0.3, -0.5), (0.34, -0.42), (0.22, -0.14)])], 0.07, 0.02).build())
    for i in range(3):
        ang = i * 2 * math.pi / 3 + 0.4
        k.add(fin, red, pos=(0.33 * math.cos(ang), -0.28, -0.33 * math.sin(ang)), rot=(0.0, ang, 0.0))
    body.decals.append(_window_decal((0.0, 0.12, 0.388), 0.15))
    t = k.t

    def flame(ctx: cairo.Context, cam: Camera3D) -> None:
        x, y, _ = k.screen(body, cam, (0, -0.7, 0))
        _flame(ctx, x, y, cam.px_per_unit() * 0.13, t, k.seed, down=True)

    k.under.append(flame)


def _b_tree(k: Kit) -> None:
    green = tuple(k.main.color)
    cone_m = _cached(k.cache, ("tree_cone", k.seg), lambda: cone(k.seg, 1.0, 2.0, 0.06))
    tiers = [(0.8, -0.72, -0.08), (0.64, -0.4, 0.26), (0.47, -0.08, 0.6)]
    for i, (r, y0, y1) in enumerate(tiers):
        h = y1 - y0
        k.add(cone_m, Material(mix(green, lighten(green, 0.2), i * 0.3), k.main.kind),
              pos=(0, (y0 + y1) / 2, 0), scale=(r, h / 2, r), bias=-0.01 * i)
    k.add(k.lat("trunk", k.lv(0.5), lambda: rounded_profile(1.0, -1.0, 1.0, 0.15), convex=True),
          _m("#8b5a2b", "clay"), pos=(0, -0.84, 0), scale=(0.15, 0.17, 0.15), bias=0.2)
    star = _cached(k.cache, ("ex_star_small",), lambda: Extrusion([star_contour(1.0, 0.48)], 0.4, 0.1).build())
    k.add(star, _m("#ffd23f", "gold"), pos=(0, 0.76, 0), scale=0.2, bias=-2.0)
    ball = k.sph(k.lv(0.5, 10))
    rnd = rng(k.seed, "tree")
    cols = ["#ff3b3b", "#ffd23f", "#3ec1ff", "#ff7eb6", "#b48cff"]
    for i in range(8):
        ti = i % 3
        r, y0, y1 = tiers[ti]
        f = rnd.uniform(0.25, 0.75)
        y = y0 + (y1 - y0) * f * 0.6 + 0.02
        rad = r * (1 - (y - y0) / (y1 - y0)) + 0.03
        ang = rnd.uniform(-1.3, 1.3) + (math.pi if i % 4 == 3 else 0.0)
        k.add(ball, _m(cols[i % len(cols)], "candy"), pos=(rad * math.sin(ang), y, rad * math.cos(ang)),
              scale=0.075, outline=0.7, bias=-0.02)


BUILDERS: dict[str, Callable[[Kit], None]] = {
    "sphere": _b_sphere, "cube": _b_cube, "torus": _b_torus, "cylinder": _b_cylinder, "cone": _b_cone,
    "gem": _b_gem, "star": _b_star, "heart": _b_heart, "coin": _b_coin, "dice": _b_dice, "planet": _b_planet,
    "gift": _b_gift, "cake": _b_cake, "balloon": _b_balloon, "donut": _b_donut, "trophy": _b_trophy,
    "disco_ball": _b_disco, "rocket": _b_rocket, "christmas_tree": _b_tree,
}


# ======================= анимации =======================
@dataclass
class Motion:
    dy: float = 0.0  # единицы предмета (вверх +)
    rot: tuple[float, float, float] = (0.0, 0.0, 0.0)
    spin: float = 0.0  # вокруг собственной вертикали
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    pivot: float = 0.0  # y точки, вокруг которой качание/сжатие


def prop_motion(anim: str, t: float, phase: float) -> Motion:
    """Движение предмета по анимации (чистая функция времени)."""
    tp = t + phase
    tau = 2 * math.pi
    if anim == "spin":
        return Motion(spin=tp * tau / 2.6)
    if anim == "float":
        return Motion(dy=0.08 * math.sin(tp * tau / 2.2), spin=0.35 * math.sin(tp * tau / 4.4),
                      rot=(0.0, 0.0, 0.05 * math.sin(tp * tau / 3.1)))
    if anim == "bounce":
        p = (tp / 0.9) % 1.0
        hgt = 4 * p * (1 - p)
        c = max(0.0, 1.0 - min(p, 1 - p) / 0.1)  # у земли — сплющивание
        sy = 1.0 - 0.22 * c + 0.06 * hgt
        sx = 1.0 / math.sqrt(sy)
        return Motion(dy=0.32 * hgt, scale=(sx, sy, sx), pivot=-1.0)
    if anim == "pulse":
        beat = max(0.0, math.sin(tp * tau / 0.9)) ** 6
        s = 1.0 + 0.1 * beat
        return Motion(scale=(s, s, s))
    if anim == "wobble":
        return Motion(rot=(0.0, 0.0, 0.2 * math.sin(tp * tau / 1.1)), spin=0.12 * math.sin(tp * tau / 2.2),
                      pivot=-1.0)
    if anim == "swing":
        return Motion(rot=(0.0, 0.0, 0.38 * math.sin(tp * tau / 1.6)), pivot=1.0)
    return Motion()


# ======================= рисование предмета =======================
def build_prop(kind: str, kit: Kit) -> None:
    BUILDERS.get(kind, _b_sphere)(kit)


def draw_prop(ctx: cairo.Context, prop: PropSpec, t: float, x: float, y: float, size_px: float, cache: dict,
              quality: str = "normal") -> None:
    """3D-предмет с центром (x, y) и высотой size_px в момент t."""
    kind = prop.kind if prop.kind in DEFAULTS else "sphere"
    if size_px < 2 or not all(map(math.isfinite, (x, y, size_px, t))):
        return
    dcol, dkind, tilt, yaw0 = DEFAULTS[kind]
    phase = hash01(0, "prop", prop.id) * 7.0
    seed = int(hash01(0, "seed", prop.id) * 1e6)
    if kind == "text3d":
        from .text3d import draw_word

        max_w = _frame_width(ctx)
        draw_word(ctx, prop.text or "3D", x, y, size_px, color=prop.color, material=prop.material,
                  anim=prop.anim, t=t, phase=phase, cache=cache, quality=quality,
                  max_w=max_w * 0.92 if max_w else None)
        return
    mat = material(prop.color, prop.material, hx(dcol), dkind)
    mo = prop_motion(prop.anim, t, phase)
    cam = sprite_camera(x, y, size_px)
    st = stats(cache)
    seg = lod_for_radius(size_px * 0.45, quality)
    while True:
        # цепочка узлов: качание вокруг опоры → сдвиг/сжатие → наклон к зрителю → поворот вокруг вертикали
        piv = Obj(None, pos=(0.0, mo.pivot + mo.dy, 0.0), rot=mo.rot, scale=mo.scale)
        back = Obj(None, pos=(0.0, -mo.pivot, 0.0), parent=piv)
        tilt_n = Obj(None, rot=(tilt, 0.0, 0.0), parent=back)
        root = Obj(None, rot=(0.0, yaw0 + mo.spin, 0.0), parent=tilt_n)
        kit = Kit(cache, seg, mat, t + phase, root, seed=seed)
        build_prop(kind, kit)
        if estimate_tris(kit.parts) <= OBJECT_BUDGET or seg <= 8:
            break
        lower = lod_level(seg - 1)
        if lower >= seg:
            break
        seg = lower
    st["objects"] += 1
    for fn in kit.under:
        ctx.save()
        fn(ctx, cam)
        ctx.restore()
    draw_parts(ctx, cam, kit.parts, outline_px(size_px), st)
    for fn in kit.over:
        ctx.save()
        fn(ctx, cam)
        ctx.restore()


def _frame_width(ctx: cairo.Context) -> float | None:
    """Ширина кадра в координатах пользователя (с учётом камеры сцены), если цель — картинка."""
    try:
        target = ctx.get_target()
        w = target.get_width()
    except Exception:  # не ImageSurface (PDF/запись) — без ограничения
        return None
    dx, dy = ctx.device_to_user_distance(w, 0)
    return float(math.hypot(dx, dy))
