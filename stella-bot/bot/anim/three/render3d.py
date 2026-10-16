"""Рисование 3D: «спрайт-камера» у каждого объекта, преобразования и свет в numpy, отсечение задних граней,
сортировка художника, заливка сеткой Гуро (meshpat) и сглаженный мультяшный контур силуэта поверх.

Объект собирается из частей (Obj) с иерархией (pos/rot/scale относительно родителя). Части рисуются целиком
(сетка + контур + наклейки) по глубине центра с поправкой bias — «слоёная кукла»: так нет «лесенки» на стыках,
как при одной общей сортировке треугольников. Кольцо вокруг тела (кольцо планеты, шарф) — split: его дальняя
половина рисуется до тела, ближняя — после.

Камера: смотрит из (0, 0, dist) в сторону −z, y вверх; экранный y — вниз.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import cairocffi as cairo
import numpy as np

from ..palette import INK
from . import meshpat
from .mesh import Extrusion, Mesh
from .shade import LIGHT as LIGHT_DIR
from .shade import Material, flat_fill, shade

DIST = 6.0
TRI_BUDGET = 5000  # видимых треугольников в кадре
MAX_OBJECTS = 6  # 3D-объектов на экране (catalog.MAX_3D_ON_SCREEN)
OBJECT_BUDGET = TRI_BUDGET // MAX_OBJECTS  # на один объект — так в сумме бюджет не превысить


def rot_xyz(rx: float, ry: float, rz: float) -> np.ndarray:
    """Поворот: сначала вокруг x, потом y, потом z (правая тройка)."""
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    rx_ = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry_ = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz_ = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz_ @ ry_ @ rx_


def _unit(a: np.ndarray) -> np.ndarray:
    return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-12)


@dataclass
class Camera3D:
    """Перспективная камера спрайта: точка (0, 0, 0) мира попадает в (cx, cy) экрана, 1 единица на глубине
    dist — f / dist пикселей."""

    cx: float
    cy: float
    f: float
    dist: float = DIST

    @property
    def pos(self) -> np.ndarray:
        return np.array([0.0, 0.0, self.dist])

    def depth(self, P: np.ndarray) -> np.ndarray:
        return np.maximum(self.dist - P[..., 2], 0.2)

    def project(self, P: np.ndarray) -> np.ndarray:
        """Точки мира (..., 3) → экран (..., 2)."""
        k = self.f / self.depth(P)
        return np.stack([self.cx + P[..., 0] * k, self.cy - P[..., 1] * k], -1)

    def px_per_unit(self, z: float = 0.0) -> float:
        return self.f / max(self.dist - z, 0.2)


def sprite_camera(x: float, y: float, size_px: float, dist: float = DIST) -> Camera3D:
    """Камера, у которой отрезок y ∈ [-1, 1] в начале координат занимает size_px по высоте в точке (x, y)."""
    return Camera3D(float(x), float(y), max(float(size_px), 1e-3) / 2 * dist, dist)


Decal = Callable[[cairo.Context, Camera3D, np.ndarray, np.ndarray], None]


@dataclass(eq=False)
class Obj:
    """Часть 3D-объекта. shape — Mesh, Extrusion или None (пустой узел иерархии: шарнир, корень)."""

    shape: Mesh | Extrusion | None = None
    mat: Material | None = None
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rot: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    parent: Obj | None = None
    outline: float = 1.0  # множитель толщины контура, 0 — без контура
    bias: float = 0.0  # поправка глубины при сортировке частей (минус — рисовать позже, поверх)
    split: Obj | None = None  # кольцо вокруг этой части: дальняя половина до неё, ближняя — после
    decals: list[Decal] = field(default_factory=list)  # 2D-рисунки на поверхности (лицо, точки кубика)
    cap: Any = None  # Extrusion: заливка передней грани — функция (y0, y1, x0, x1) → cairo.Pattern
    side2: tuple[float, float, float] | None = None  # Extrusion: второй цвет полосок стенок (карамель)
    shine: tuple[float, float, float] | None = None  # Extrusion: блик (x, y середины полосы, полуширина), пиксели
    grout: bool = False  # гранёный шар: тёмные швы между плитками (диско-шар)
    # «покраска» области сетки чётким краем: (контуры на поверхности (k, 3) в локальных координатах, цвет);
    # контуры одного направления складываются, встречные — вырезают (брюшко пингвина, глазурь)
    patches: list[tuple[Any, tuple[float, float, float]]] = field(default_factory=list)
    clip_decals: bool = False  # обрезать наклейки по силуэту части (лицо у края головы не «вылезает»)
    silhouette: list = field(default_factory=list, repr=False)  # замкнутые петли силуэта последнего кадра


def world(o: Obj) -> tuple[np.ndarray, np.ndarray]:
    """Матрица 3×3 и сдвиг части в мире (с учётом родителей)."""
    m = rot_xyz(*o.rot) @ np.diag(np.asarray(o.scale, float))
    t = np.asarray(o.pos, float)
    if o.parent is not None:
        pm, pt = world(o.parent)
        return pm @ m, pm @ t + pt
    return m, t


# ======================= статистика и бюджет =======================
def stats(cache: dict) -> dict:
    """Счётчики воркера: сколько видимых треугольников и объектов нарисовано (для тестов и замеров)."""
    return cache.setdefault(("three", "stats"), {"tris": 0, "objects": 0})


def estimate_tris(parts: Sequence[Obj], cam: Camera3D | None = None) -> int:
    """Оценка видимых треугольников с запасом: у замкнутой сетки к камере смотрит около половины граней
    (у сплюснутых деталей — чуть больше)."""
    n = 0.0
    for o in parts:
        if cam is not None and isinstance(o.shape, Mesh) and o.shape.is_sphere:
            M, T = world(o)
            if _impostor_radius(cam, o, M, T) > 0:  # крошечный шар рисуется кружком
                n += 1
                continue
        if isinstance(o.shape, Mesh):
            n += o.shape.ntri * 0.62
        elif isinstance(o.shape, Extrusion):
            n += len(o.shape.quads) * 0.62 * 2
    return int(n)


# ======================= контур =======================
def _chains(pairs: list[tuple[int, int]]) -> list[tuple[list[int], bool]]:
    """Рёбра (пары номеров вершин) → цепочки вершин (номера, замкнута ли)."""
    adj: dict[int, list[int]] = {}
    for k, (a, b) in enumerate(pairs):
        adj.setdefault(a, []).append(k)
        adj.setdefault(b, []).append(k)
    used = [False] * len(pairs)
    out: list[tuple[list[int], bool]] = []
    # сначала цепочки от концов (вершины степени 1), потом замкнутые петли
    starts = [v for v, es in adj.items() if len(es) == 1] + list(adj)
    for s in starts:
        for k0 in adj[s]:
            if used[k0]:
                continue
            chain = [s]
            cur, k = s, k0
            while True:
                used[k] = True
                a, b = pairs[k]
                nxt = b if a == cur else a
                chain.append(nxt)
                cur = nxt
                cand = [e for e in adj[cur] if not used[e]]
                if not cand or len(adj[cur]) > 2:
                    break
                k = cand[0]
            closed = chain[0] == chain[-1] and len(chain) > 3
            out.append((chain[:-1] if closed else chain, closed))
    return out


def smooth_path(ctx: cairo.Context, pts: list[list[float]], closed: bool, smooth: bool = True,
                corner_deg: float = 50.0) -> None:
    """Ломаная → путь: гладкий Catmull-Rom (через все точки), а в острых углах (> corner_deg) — без скругления."""
    n = len(pts)
    if n < 2:
        return
    ctx.move_to(*pts[0])
    if not smooth or n < 3:
        for p in pts[1:]:
            ctx.line_to(*p)
        if closed:
            ctx.close_path()
        return
    P = np.asarray(pts, float)
    cos_lim = math.cos(math.radians(corner_deg))
    if closed:
        prev, nxt = np.roll(P, 1, 0), np.roll(P, -1, 0)
    else:
        prev = np.vstack([P[:1], P[:-1]])
        nxt = np.vstack([P[1:], P[-1:]])
    d1 = _unit(P - prev)
    d2 = _unit(nxt - P)
    corner = (d1 * d2).sum(1) < cos_lim
    if not closed:
        corner[0] = corner[-1] = True
    # касательная — по соседям (как у Catmull-Rom), а длина «ручек» — треть ЭТОГО отрезка: при отрезках разной
    # длины (длинный бок цилиндра + мелкая фаска) кривая не делает петель и «крючков»
    tdir = _unit(nxt - prev)
    tdir[corner] = 0.0
    m = n if closed else n - 1
    for i in range(m):
        j = (i + 1) % n
        seg = float(np.hypot(*(P[j] - P[i]))) / 3.0
        c1 = P[i] + tdir[i] * seg
        c2 = P[j] - tdir[j] * seg
        ctx.curve_to(c1[0], c1[1], c2[0], c2[1], P[j][0], P[j][1])
    if closed:
        ctx.close_path()


def _relax(P: np.ndarray, closed: bool, cap: float = 3.0) -> np.ndarray:
    """Сгладить «лесенку» силуэта: силуэт сетки идёт то по меридиану, то по параллели, и черта зигзагует.
    Двигаются только вершины зигзага (поворот меняет знак у соседей): p' = p/2 + (prev + next)/4 гасит зигзаг
    через точку полностью. Выпуклые участки (скруглённые углы куба, бок шара) не трогаем — иначе черта уходит
    внутрь и из-под неё выглядывает заливка."""
    if closed:
        prev, nxt = np.roll(P, 1, 0), np.roll(P, -1, 0)
    else:
        prev = np.vstack([P[:1], P[:-1]])
        nxt = np.vstack([P[1:], P[-1:]])
    d1 = P - prev
    d2 = nxt - P
    cr = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    sg = np.sign(np.where(np.abs(cr) < 1e-9, 0.0, cr))
    zig = (sg != 0) & ((sg != np.roll(sg, 1)) | (sg != np.roll(sg, -1)))
    if not closed:
        zig[0] = zig[-1] = False
    out = P.copy()
    out[zig] = 0.5 * P[zig] + 0.25 * (prev[zig] + nxt[zig])
    # сдвиг не больше cap пикселей: настоящие изломы (поля шляпы, край кубка) почти не трогаем
    d = out - P
    ln = np.linalg.norm(d, axis=1, keepdims=True)
    return P + d * np.minimum(1.0, cap / np.maximum(ln, 1e-9))


def _occluded(mid: np.ndarray, mdepth: np.ndarray, tri: np.ndarray, tdepth: np.ndarray) -> np.ndarray:
    """Какие точки mid (k, 2) с глубиной mdepth закрыты треугольниками tri (t, 3, 2) с глубиной вершин tdepth."""
    if not len(mid) or not len(tri):
        return np.zeros(len(mid), bool)
    hidden = np.zeros(len(mid), bool)
    a = tri[:, 0]
    v0 = tri[:, 1] - a
    v1 = tri[:, 2] - a
    d00 = (v0 * v0).sum(1)
    d01 = (v0 * v1).sum(1)
    d11 = (v1 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    ok = np.abs(den) > 1e-9
    a, v0, v1, d00, d01, d11, den, td = a[ok], v0[ok], v1[ok], d00[ok], d01[ok], d11[ok], den[ok], tdepth[ok]
    step = max(1, 200_000 // max(1, len(a)))
    for s in range(0, len(mid), step):
        m = mid[s:s + step]
        v2 = m[:, None, :] - a[None]
        d20 = (v2 * v0[None]).sum(2)
        d21 = (v2 * v1[None]).sum(2)
        v = (d11 * d20 - d01 * d21) / den
        w = (d00 * d21 - d01 * d20) / den
        u = 1 - v - w
        inside = (u > 0.02) & (v > 0.02) & (w > 0.02)
        z = u * td[:, 0] + v * td[:, 1] + w * td[:, 2]
        hidden[s:s + step] = (inside & (z < mdepth[s:s + step, None] - 0.03)).any(1)
    return hidden


def _stroke_edges(ctx: cairo.Context, S: np.ndarray, weld: np.ndarray, pairs: np.ndarray, lw: float,
                  smooth: bool, alpha: float = 1.0, min_len: float = 0.0, keep: list | None = None,
                  relax: bool = True) -> None:
    """Обвести рёбра (пары вершин) цепочками; открытые цепочки короче min_len пикселей — пропустить
    (короткие «засечки» касательных на фаске мелькают при вращении)."""
    if not len(pairs) or lw <= 0:
        return
    wp = weld[pairs]
    rep: dict[int, int] = {}
    for (i0, i1), (w0, w1) in zip(pairs.tolist(), wp.tolist(), strict=True):
        rep.setdefault(w0, i0)
        rep.setdefault(w1, i1)
    loops: list[list[list[float]]] = []
    for chain, closed in _chains([tuple(x) for x in wp.tolist()]):
        pts = [S[rep[w]].tolist() for w in chain]
        if min_len > 0 and not closed:
            arr = np.asarray(pts)
            if float(np.linalg.norm(np.diff(arr, axis=0), axis=1).sum()) < min_len:
                continue
        if relax and smooth and len(pts) >= 5:
            pts = _relax(np.asarray(pts, float), closed, 0.7 * lw + 1.0).tolist()
        if closed:
            loops.append(pts)
        smooth_path(ctx, pts, closed, smooth)
    if keep is not None:
        keep.extend(loops)
    ctx.set_source_rgba(*INK, alpha)
    ctx.set_line_width(lw)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


# ======================= сетка =======================
def draw_mesh(ctx: cairo.Context, cam: Camera3D, o: Obj, M: np.ndarray, T: np.ndarray, lw: float,
              half: tuple[str, float] | None = None, st: dict | None = None) -> None:
    """Одна часть-сетка: Гуро (или грани у гранёных), потом контур силуэта. half — ("far"|"near", глубина)."""
    m = o.shape
    assert isinstance(m, Mesh) and o.mat is not None
    P = m.v @ M.T + T
    sign = 1.0 if np.linalg.det(M) >= 0 else -1.0
    tri = P[m.f]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) * sign
    cen = tri.mean(1)
    to_cam = cam.pos - cen
    facing = (fn * to_cam).sum(1) > 0
    cdepth = cam.depth(cen)
    sel = facing
    if half is not None:
        sel = sel & ((cdepth > half[1]) if half[0] == "far" else (cdepth <= half[1]))
    idx = np.nonzero(sel)[0]
    if not len(idx):
        return
    order = idx[np.argsort(-cdepth[idx], kind="stable")]
    S = cam.project(P)
    if st is not None:
        st["tris"] += len(order)
    mat = o.mat
    if m.flat:
        fnn = _unit(fn[order])
        base = None
        if mat.vcolor is not None and len(mat.vcolor) == len(m.v):
            base = mat.vcolor[m.f[order]].mean(1)
        cols = shade(fnn, _unit(to_cam[order]), mat, base=base)
        pts = S[m.f[order]]
        if o.grout:  # швы между плитками: сначала всё тёмным, потом плитки чуть меньше и чуть разной яркости
            jit = 0.82 + 0.36 * ((np.sin(order * 12.9898) * 43758.5453) % 1.0)
            cols = np.clip(cols[:, :3] * jit[:, None], 0, 1)
            meshpat.fill_flat(ctx, pts, np.tile([0.3, 0.28, 0.4], (len(pts), 1)), 0.8)
            meshpat.fill_flat(ctx, pts, cols, -0.45 * min(1.0, lw / 2.5))
        else:
            meshpat.fill_flat(ctx, pts, cols)
    else:
        N = _unit(m.n @ np.linalg.inv(M))
        V = _unit(cam.pos - P)
        cols = shade(N, V, mat)
        tris = S[m.f[order]]
        meshpat.paint_triangles(ctx, tris, cols[m.f[order]])
        for src, pcol in o.patches:
            # та же сетка своим цветом, но только внутри проекции контуров: край — сглаженный клип, а не
            # размытая интерполяция цвета по крупным треугольникам. src — контуры или функция (M, T, cam) →
            # контуры либо (контуры, линии): линии потом обводятся тонко (края ленты на подарке)
            got = src(M, T, cam) if callable(src) else src
            loops, lines = got if isinstance(got, tuple) else (got, [])
            if not loops:
                continue
            pc = shade(N, V, mat, base=np.asarray(pcol, float))
            polys = [cam.project(np.asarray(loop, float) @ M.T + T) for loop in loops]
            # только треугольники, задевающие рамку хоть одного контура: заливка сеткой дорогая
            tlo, thi = tris.min(1), tris.max(1)
            near = np.zeros(len(tris), bool)
            for poly in polys:
                plo, phi = poly.min(0) - 1, poly.max(0) + 1
                near |= np.all(thi >= plo, 1) & np.all(tlo <= phi, 1)
            if not near.any():
                continue
            ctx.save()
            _cap_path(ctx, polys)
            ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
            ctx.clip()
            meshpat.paint_triangles(ctx, tris[near], pc[m.f[order[near]]])
            ctx.restore()
            if lines and lw > 0:
                for ln in lines:
                    sp = cam.project(np.asarray(ln, float) @ M.T + T).tolist()
                    ctx.move_to(*sp[0])
                    for q in sp[1:]:
                        ctx.line_to(*q)
                ctx.set_source_rgba(*INK, 0.85)
                ctx.set_line_width(lw * 0.45)
                ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                ctx.stroke()
    if o.outline <= 0 or lw <= 0:
        return
    ef = m.ef
    f0 = facing[ef[:, 0]]
    f1 = np.where(ef[:, 1] >= 0, facing[np.maximum(ef[:, 1], 0)], False)
    sil = np.nonzero(f0 != f1)[0]
    if not len(sil):
        return
    pairs = m.edges[sil]
    ed = cam.depth(P[pairs].mean(1))
    if half is not None:
        keep = (ed > half[1]) if half[0] == "far" else (ed <= half[1])
        pairs, ed = pairs[keep], ed[keep]
    if not m.convex and len(pairs):
        tdep = cam.depth(tri[order])
        hidden = _occluded(S[pairs].mean(1), ed, S[m.f[order]], tdep)
        pairs = pairs[~hidden]
    alpha = 0.55 if mat.kind == "glass" else 1.0
    weld = _weld(m)
    # у невыпуклых (тор, кубок) — без коротких обрывков: там, где поверхность почти ребром к камере, силуэт
    # многоугольной сетки распадается на «чёрточки»
    min_len = 0.0 if m.convex else 4.0 * lw * o.outline
    o.silhouette = []
    _stroke_edges(ctx, S, weld, pairs, lw * o.outline, smooth=not m.flat, alpha=alpha, min_len=min_len,
                  keep=o.silhouette if m.convex else None)


def _weld(m: Mesh) -> np.ndarray:
    w = getattr(m, "_weld", None)
    if w is None:
        q = np.round(m.v * 1e5).astype(np.int64)
        _, w = np.unique(q, axis=0, return_inverse=True)
        w = w.reshape(-1)
        m._weld = w  # type: ignore[attr-defined]
    return w


# ======================= выдавленная фигура =======================
def _cap_path(ctx: cairo.Context, polys: list[np.ndarray]) -> None:
    for poly in polys:
        pl = poly.tolist()
        ctx.move_to(*pl[0])
        for p in pl[1:]:
            ctx.line_to(*p)
        ctx.close_path()


def draw_extrusion(ctx: cairo.Context, cam: Camera3D, o: Obj, M: np.ndarray, T: np.ndarray, lw: float,
                   st: dict | None = None, sil: bool = True) -> None:
    """Выдавленная фигура: видимые стенки по глубине (раздутые на 0.7 px), контур силуэта толщины (sil), потом
    видимая плоская грань (один путь, правило winding — дырки в «О», «А», «Р» получаются сами), блик и контур."""
    ex = o.shape
    assert isinstance(ex, Extrusion)
    mat = o.mat or Material()
    if not len(ex.quads):
        return
    glass = mat.kind == "glass"
    if glass:
        ctx.push_group()
    Minv = np.linalg.inv(M)
    Q = ex.quads @ M.T + T
    cen = Q.mean(1)
    to_cam = cam.pos - cen
    Nq = _unit(ex.qn @ Minv)
    vis = (Nq * to_cam).sum(1) > 0
    idx = np.nonzero(vis)[0]
    d2 = ex.depth / 2
    nf = _unit(np.array([0.0, 0.0, 1.0]) @ Minv)
    pc = M @ np.array([0.0, 0.0, d2]) + T
    front_vis = float(nf @ (cam.pos - pc)) > 0
    pb = M @ np.array([0.0, 0.0, -d2]) + T
    back_vis = float(-nf @ (cam.pos - pb)) > 0
    caps = ex.front if front_vis else ex.back if back_vis else []
    cap_polys = [cam.project(c @ M.T + T) for c in caps]
    lw_cap = lw * o.outline
    order = idx[np.argsort(-cam.depth(cen[idx]), kind="stable")] if len(idx) else idx
    if len(order):
        if st is not None:
            st["tris"] += 2 * len(order)
        base = np.tile(np.asarray(mat.color, float), (len(order), 1))
        if o.side2 is not None:
            stripe = ((ex.qk[order] // 2) % 2) == 1
            base[stripe] = np.asarray(o.side2, float)
        side_mat = Material(mat.color, "plastic" if glass else mat.kind, rim=mat.rim)
        cols = shade(Nq[order], _unit(to_cam[order]), side_mat, base=base)
        meshpat.fill_flat(ctx, cam.project(Q[order]), cols, 0.7)
    if sil and lw_cap > 0 and ex.edges is not None and len(ex.edges):
        # контур силуэта толщины: рёбра, у которых видна только одна сторона (стенка или плоская грань);
        # закрытые ближними стенками — убираются, закрытые плоской гранью — её заливка ляжет поверх
        side_vis = np.concatenate([vis, [back_vis, front_vis]])  # индексы -2 и -1 — задняя и передняя грани
        f0 = side_vis[ex.ef[:, 0]]
        f1 = side_vis[ex.ef[:, 1]]
        sel = np.nonzero(f0 != f1)[0]
        if len(sel):
            pairs = ex.edges[sel]
            P = ex.epts @ M.T + T
            S = cam.project(P)
            if len(order):
                qs = cam.project(Q[order])
                tri = np.concatenate([qs[:, [0, 1, 2]], qs[:, [0, 2, 3]]])
                qd = cam.depth(Q[order])
                tdep = np.concatenate([qd[:, [0, 1, 2]], qd[:, [0, 2, 3]]])
                # ребро закрыто, если закрыта хоть одна из трёх точек на нём: у вогнутых фигур (звезда в профиль)
                # иначе остаются короткие «засечки» наполовину спрятанных рёбер
                a2, b2 = S[pairs[:, 0]], S[pairs[:, 1]]
                da, db = cam.depth(P[pairs[:, 0]]), cam.depth(P[pairs[:, 1]])
                fr = np.array([0.15, 0.5, 0.85])
                pts = (a2[None] + (b2 - a2)[None] * fr[:, None, None]).reshape(-1, 2)
                dep = (da[None] + (db - da)[None] * fr[:, None]).reshape(-1)
                hid = _occluded(pts, dep, tri, tdep).reshape(3, -1).any(0)
                pairs = pairs[~hid]
            ident = np.arange(len(S))
            # у выдавленных фигур контур точный (без «лесенки» сетки): не разглаживаем, только скругляем стыки
            _stroke_edges(ctx, S, ident, pairs, lw_cap, smooth=True, min_len=2.5 * lw_cap, relax=False)
    if cap_polys:
        allp = np.concatenate(cap_polys)
        x0, y0 = allp.min(0)
        x1, y1 = allp.max(0)
        _cap_path(ctx, cap_polys)
        ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
        if o.cap is not None:
            ctx.set_source(o.cap(y0, y1, x0, x1))
        else:
            ctx.set_source(flat_fill(mat.kind, tuple(mat.color), y0, y1, x0, x1))
        ctx.fill()
        if o.shine is not None:  # бегущий блик: (x середины полосы, y опоры, полуширина), полоса под 45°
            sx, sy, hw = o.shine
            ctx.save()
            _cap_path(ctx, cap_polys)
            ctx.clip()
            g = cairo.LinearGradient(sx - hw, sy - hw, sx + hw, sy + hw)
            g.add_color_stop_rgba(0.0, 1, 1, 1, 0)
            g.add_color_stop_rgba(0.5, 1, 1, 1, 0.75)
            g.add_color_stop_rgba(1.0, 1, 1, 1, 0)
            ctx.set_source(g)
            ctx.paint()
            ctx.restore()
        if lw_cap > 0:
            _cap_path(ctx, cap_polys)
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(lw_cap)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke()
    if glass:
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(0.62)


# ======================= наклейки на поверхности =======================
def surface_affine(cam: Camera3D, M: np.ndarray, T: np.ndarray, p: Sequence[float],
                   u: Sequence[float] = (1.0, 0.0, 0.0), v: Sequence[float] = (0.0, 1.0, 0.0),
                   n: Sequence[float] | None = None, iso: bool = False) -> tuple[cairo.Matrix, float, float]:
    """Аффинная «касательная» проекция для 2D-рисунка на поверхности. В точке p части (её локальные координаты)
    с осями u (вправо) и v (вверх) строится матрица: 1 единица рисунка = 1 локальная единица (iso — 1 единица
    мира), y рисунка — вниз. Ответ: (матрица для ctx.transform, пикселей на единицу по вертикали, k — насколько
    поверхность смотрит на камеру, -1..1)."""
    p = np.asarray(p, float)
    u = np.asarray(u, float)
    v = np.asarray(v, float)
    eps = 1e-3
    if iso:  # оси — в мире, единичной длины: рисунок не растягивается вместе с неравномерным масштабом части
        P = M @ p + T
        W = np.stack([P, P + _unit(M @ u) * eps, P + _unit(M @ v) * eps])
    else:
        W = np.stack([p, p + u * eps, p + v * eps]) @ M.T + T
    S = cam.project(W)
    eu = (S[1] - S[0]) / eps
    ev = (S[2] - S[0]) / eps
    nn = np.cross(u, v) if n is None else np.asarray(n, float)
    nw = _unit(nn @ np.linalg.inv(M))
    k = float(nw @ _unit(cam.pos - W[0]))
    mtx = cairo.Matrix(float(eu[0]), float(eu[1]), float(-ev[0]), float(-ev[1]), float(S[0][0]), float(S[0][1]))
    return mtx, float(np.linalg.norm(ev)), k


# ======================= крошечные шары =======================
IMPOSTOR_PX = 13.0  # шар меньше этого радиуса на экране — 2D-кружок с тем же светом (ёлочные игрушки, кисти)


def _impostor_radius(cam: Camera3D, o: Obj, M: np.ndarray, T: np.ndarray) -> float:
    """Радиус шара на экране, если часть — маленький равномерный шар без наклеек и покраски; иначе 0."""
    m = o.shape
    if not isinstance(m, Mesh) or not m.is_sphere or o.patches or o.decals or o.mat is None:
        return 0.0
    if o.mat.vcolor is not None or o.mat.kind == "glass":
        return 0.0
    sc = np.linalg.norm(M, axis=0)
    if sc.max() > sc.min() * 1.06:
        return 0.0
    r = cam.f * float(sc.mean()) / float(cam.depth(T))
    return r if r < IMPOSTOR_PX else 0.0


def _impostor(ctx: cairo.Context, cam: Camera3D, o: Obj, T: np.ndarray, r: float, lw: float,
              st: dict | None) -> None:
    """Маленький шар одним кружком: радиальный градиент из цветов того же материала (свет → середина → тень),
    блик и контур. На таком размере не отличить от сетки, а стоит в разы дешевле."""
    assert o.mat is not None
    ctx.new_path()  # без «хвоста» от текущей точки вызывающего
    cx, cy = (float(v) for v in cam.project(T[None])[0])
    lx, ly = float(LIGHT_DIR[0]), float(LIGHT_DIR[1])
    N = _unit(np.array([[lx, ly, 0.75], [0.0, 0.0, 1.0], [-lx, -ly, 0.25]]))
    V = np.tile([0.0, 0.0, 1.0], (3, 1))
    c = shade(N, V, o.mat)[:, :3].tolist()
    hx_, hy_ = cx + lx * r * 0.4, cy - ly * r * 0.4
    g = cairo.RadialGradient(hx_, hy_, r * 0.05, cx, cy, r * 1.05)
    g.add_color_stop_rgb(0.0, *c[0])
    g.add_color_stop_rgb(0.45, *c[1])
    g.add_color_stop_rgb(1.0, *c[2])
    ctx.arc(cx, cy, r, 0, 2 * math.pi)
    ctx.set_source(g)
    ctx.fill_preserve()
    if o.outline > 0 and lw > 0:
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(lw * o.outline)
        ctx.stroke()
    else:
        ctx.new_path()
    if st is not None:
        st["tris"] += 1


# ======================= «слоёная кукла» =======================
def draw_parts(ctx: cairo.Context, cam: Camera3D, parts: Sequence[Obj], lw: float, st: dict | None = None) -> None:
    """Нарисовать части объекта по глубине (дальние первыми); у каждой — заливка, контур и наклейки."""
    ctx.new_path()  # путь не входит в save/restore: чужая текущая точка дала бы лишнюю линию к первой дуге
    entries: list[tuple[float, int, Obj, np.ndarray, np.ndarray, tuple[str, float] | None]] = []
    for i, o in enumerate(parts):
        if o.shape is None:
            continue
        M, T = world(o)
        if abs(np.linalg.det(M)) < 1e-12:
            continue
        d = float(cam.depth(T)) + o.bias
        if o.split is not None and isinstance(o.shape, Mesh):
            _, ts = world(o.split)
            ref = float(cam.depth(ts))
            entries.append((ref + 0.5, i, o, M, T, ("far", ref)))
            entries.append((ref - 0.5 + o.bias, i, o, M, T, ("near", ref)))
        else:
            entries.append((d, i, o, M, T, None))
    entries.sort(key=lambda e: (-e[0], e[1]))
    for _, _, o, M, T, half in entries:
        r_imp = _impostor_radius(cam, o, M, T) if half is None else 0.0
        if r_imp > 0:
            _impostor(ctx, cam, o, T, r_imp, lw, st)
        elif isinstance(o.shape, Mesh):
            draw_mesh(ctx, cam, o, M, T, lw, half, st)
        else:
            draw_extrusion(ctx, cam, o, M, T, lw, st)
        if half is None or half[0] == "near":
            for decal in o.decals:
                ctx.save()
                ctx.new_path()
                if o.clip_decals and o.silhouette:
                    for loop in o.silhouette:
                        smooth_path(ctx, loop, True, True)
                    ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
                    ctx.clip()
                decal(ctx, cam, M, T)
                ctx.restore()


def outline_px(size_px: float) -> float:
    """Толщина мультяшного контура для объекта высотой size_px."""
    return min(3.6, max(1.4, size_px * 0.019))
