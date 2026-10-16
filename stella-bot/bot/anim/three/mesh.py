"""3D-сетки мультика: примитивы (сфера и скруглённый куб, тор, тело вращения, цилиндр, конус, кристалл),
подготовка сетки (грани наружу по знаку объёма, нормали вершин, смежность рёбер) и выдавленные плоские контуры
(звезда, сердце, монета, буквы) с фаской.

Система координат объекта: x вправо, y вверх, z к зрителю (правая тройка). Грань (a, b, c) обходится против часовой,
если смотреть снаружи: нормаль cross(b − a, c − a) смотрит наружу, объём сетки положительный. Почти все предметы
вписаны в куб [-1, 1]³: «размер» на экране — это высота от y = -1 до y = 1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

# уровни детализации (число сегментов по кругу); всё, что строится по LOD, берёт значения отсюда — так кеш маленький
LOD_LEVELS = (8, 10, 12, 16, 20, 24, 28, 32, 40)


# ======================= сетка =======================
@dataclass(eq=False)
class Mesh:
    """Треугольная сетка. После prepare(): грани наружу, нормали вершин (по площади граней), рёбра и их грани."""

    v: np.ndarray  # (N, 3) вершины
    f: np.ndarray  # (M, 3) грани, int32
    flat: bool = False  # гранёная: свет по грани (кристалл, диско-шар), а не по вершинам
    convex: bool = True  # выпуклая — силуэт не может закрывать сам себя (контур без проверки перекрытий)
    n: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]  # (N, 3) нормали вершин
    edges: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]  # (E, 2) вершины рёбер
    ef: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]  # (E, 2) грани ребра, -1 — край
    fn: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]  # (M, 3) нормали граней

    @property
    def ntri(self) -> int:
        return int(len(self.f))

    def signed_volume(self) -> float:
        """Объём по формуле тетраэдров от начала координат: > 0, если грани смотрят наружу."""
        t = self.v[self.f]
        return float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6.0)

    def prepare(self) -> Mesh:
        self.v = np.ascontiguousarray(self.v, dtype=np.float64)
        self.f = np.ascontiguousarray(self.f, dtype=np.int32)
        # обход граней — наружу (по знаку объёма), иначе свет и отсечение задних граней перевернутся
        if self.signed_volume() < 0:
            self.f = np.ascontiguousarray(self.f[:, ::-1])
        tri = self.v[self.f]
        fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        vn = np.zeros_like(self.v)
        for j in range(3):
            np.add.at(vn, self.f[:, j], fn)  # длина fn = 2·площадь: нормаль вершины взвешена по площади
        self.n = vn / (np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12)
        self.fn = fn / (np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12)
        self.edges, self.ef = _adjacency(self.v, self.f)
        return self


def _adjacency(v: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Уникальные рёбра и две грани по их сторонам. Совпадающие по координатам вершины склеиваются, поэтому
    шов сетки (продублированные вершины) не считается краем."""
    q = np.round(v * 1e5).astype(np.int64)
    _, weld = np.unique(q, axis=0, return_inverse=True)
    weld = weld.reshape(-1)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    fid = np.tile(np.arange(len(f)), 3)
    key = np.sort(weld[e], axis=1)
    kk = key[:, 0].astype(np.int64) * (len(v) + 1) + key[:, 1]
    order = np.argsort(kk, kind="stable")
    _, start, cnt = np.unique(kk[order], return_index=True, return_counts=True)
    a = order[start]
    b = np.where(cnt > 1, order[np.minimum(start + 1, len(order) - 1)], -1)
    edges = e[a]
    ef = np.stack([fid[a], np.where(b >= 0, fid[np.maximum(b, 0)], -1)], axis=1)
    return edges.astype(np.int32), ef.astype(np.int32)


def lod_level(segments: float) -> int:
    """Ближайший уровень детализации не больше заданного (минимум — самый грубый)."""
    best = LOD_LEVELS[0]
    for lv in LOD_LEVELS:
        if lv <= segments + 1e-9:
            best = lv
    return best


def lod_for_radius(r_px: float, quality: str = "normal", lo: int = 10, hi: int = 32) -> int:
    """Сегменты по кругу для радиуса на экране: около r/4 (не грубее lo, не тоньше hi); fast — на треть грубее."""
    k = 4.0 if quality != "fast" else 6.0
    seg = min(max(r_px / k, lo), hi)
    return lod_level(seg)


# ======================= примитивы =======================
def _sp(x: np.ndarray, p: float) -> np.ndarray:
    return np.sign(x) * np.abs(x) ** p


def sphere(nu: int = 24, nv: int | None = None, sx: float = 1.0, sy: float = 1.0, sz: float = 1.0,
           e: float = 1.0) -> Mesh:
    """Сфера / эллипсоид; e < 1 — «скруглённый куб» (суперэллипсоид). Полюса — настоящие вершины (без дырок)."""
    nu = max(6, int(nu))
    nv = max(4, int(nv if nv is not None else round(nu * 2 / 3)))
    us = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    vs = np.linspace(0, np.pi, nv + 1)[1:-1]
    V, U = np.meshgrid(vs, us, indexing="ij")  # (nv-1, nu)
    x = _sp(np.sin(V), e) * _sp(np.cos(U), e)
    y = _sp(np.cos(V), e)
    z = -_sp(np.sin(V), e) * _sp(np.sin(U), e)
    ring = np.stack([x * sx, y * sy, z * sz], -1).reshape(-1, 3)
    v = np.vstack([[0.0, sy, 0.0], ring, [0.0, -sy, 0.0]])
    f = []
    top, bot = 0, len(v) - 1
    rows = nv - 1
    for i in range(nu):
        j = (i + 1) % nu
        f.append((top, 1 + i, 1 + j))
    for r in range(rows - 1):
        for i in range(nu):
            j = (i + 1) % nu
            a, b = 1 + r * nu + i, 1 + r * nu + j
            c, d = a + nu, b + nu
            f.append((a, c, b))
            f.append((b, c, d))
    base = 1 + (rows - 1) * nu
    for i in range(nu):
        j = (i + 1) % nu
        f.append((base + i, bot, base + j))
    return Mesh(v, np.array(f, np.int32)).prepare()


def torus(R: float = 1.0, r: float = 0.4, nu: int = 32, nv: int = 14) -> Mesh:
    """Тор в плоскости XZ (дырка смотрит вверх по y)."""
    nu, nv = max(6, int(nu)), max(4, int(nv))
    us = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    vs = np.linspace(0, 2 * np.pi, nv, endpoint=False)
    U, V = np.meshgrid(us, vs, indexing="ij")
    x = (R + r * np.cos(V)) * np.cos(U)
    z = (R + r * np.cos(V)) * np.sin(U)
    y = r * np.sin(V)
    v = np.stack([x, y, z], -1).reshape(-1, 3)
    i = np.arange(nu)[:, None]
    j = np.arange(nv)[None, :]
    a = i * nv + j
    b = i * nv + (j + 1) % nv
    c = ((i + 1) % nu) * nv + j
    d = ((i + 1) % nu) * nv + (j + 1) % nv
    f = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([b, d, c], -1).reshape(-1, 3)])
    return Mesh(v, f.astype(np.int32), convex=False).prepare()


def lathe(profile: Sequence[tuple[float, float]], n: int = 24, convex: bool = False) -> Mesh:
    """Тело вращения вокруг оси y. profile — точки (радиус, y) снизу вверх; точка с радиусом 0 в начале или в
    конце — полюс, иначе торец закрывается плоской «крышкой» с вершиной в центре."""
    n = max(6, int(n))
    prof = [(max(0.0, float(r)), float(y)) for r, y in profile]
    if len(prof) < 2:
        raise ValueError("профиль тела вращения — хотя бы две точки")
    us = np.linspace(0, 2 * np.pi, n, endpoint=False)
    cu, su = np.cos(us), -np.sin(us)
    verts: list[np.ndarray] = []
    rings: list[int | list[int]] = []  # индекс полюса или индексы кольца
    count = 0
    for r, y in prof:
        if r < 1e-9:
            verts.append(np.array([[0.0, y, 0.0]]))
            rings.append(count)
            count += 1
        else:
            verts.append(np.stack([r * cu, np.full(n, y), r * su], -1))
            rings.append(list(range(count, count + n)))
            count += n
    f: list[tuple[int, int, int]] = []
    # нижняя крышка
    if isinstance(rings[0], list):
        c0 = count
        verts.append(np.array([[0.0, prof[0][1], 0.0]]))
        count += 1
        ring = rings[0]
        for i in range(n):
            f.append((c0, ring[(i + 1) % n], ring[i]))
    for k in range(len(rings) - 1):
        lo, hi = rings[k], rings[k + 1]
        if isinstance(lo, int) and isinstance(hi, int):
            continue
        for i in range(n):
            j = (i + 1) % n
            if isinstance(lo, int):
                f.append((lo, hi[j], hi[i]))  # type: ignore[index]
            elif isinstance(hi, int):
                f.append((lo[i], lo[j], hi))
            else:
                f.append((lo[i], lo[j], hi[i]))
                f.append((lo[j], hi[j], hi[i]))
    if isinstance(rings[-1], list):
        c1 = count
        verts.append(np.array([[0.0, prof[-1][1], 0.0]]))
        count += 1
        ring = rings[-1]
        for i in range(n):
            f.append((ring[i], ring[(i + 1) % n], c1))
    return Mesh(np.vstack(verts), np.array(f, np.int32), convex=convex).prepare()


def rounded_profile(r: float, y0: float, y1: float, bevel: float, steps: int = 3,
                    rows: int = 1) -> list[tuple[float, float]]:
    """Профиль цилиндра со скруглёнными рёбрами (дуги радиуса bevel), снизу вверх, с центрами крышек.
    rows > 1 — бок делится на столько поясов (нужно для цвета по вершинам: глазурь, полосы)."""
    bevel = max(0.0, min(bevel, r * 0.95, (y1 - y0) / 2 * 0.95))
    pts: list[tuple[float, float]] = [(0.0, y0)]
    if bevel <= 1e-6:
        side = [(r, y0 + (y1 - y0) * k / rows) for k in range(rows + 1)]
        return pts + side + [(0.0, y1)]
    for k in range(steps + 1):
        a = -math.pi / 2 + (math.pi / 2) * k / steps
        pts.append((r - bevel + bevel * math.cos(a), y0 + bevel + bevel * math.sin(a)))
    ya, yb = y0 + bevel, y1 - bevel
    for k in range(1, rows):
        pts.append((r, ya + (yb - ya) * k / rows))
    for k in range(steps + 1):
        a = (math.pi / 2) * k / steps
        pts.append((r - bevel + bevel * math.cos(a), y1 - bevel + bevel * math.sin(a)))
    pts.append((0.0, y1))
    return pts


def cylinder(n: int = 24, r: float = 1.0, h: float = 2.0, bevel: float = 0.12) -> Mesh:
    """Цилиндр вдоль y высотой h с мягко скруглёнными рёбрами."""
    return lathe(rounded_profile(r, -h / 2, h / 2, bevel), n, convex=True)


def cone(n: int = 24, r: float = 1.0, h: float = 2.0, bevel: float = 0.08) -> Mesh:
    """Конус вдоль y (вершина вверху) со скруглённым краем основания."""
    y0, y1 = -h / 2, h / 2
    b = max(0.0, min(bevel, r * 0.5))
    prof = [(0.0, y0)]
    if b > 0:
        for k in range(4):
            a = -math.pi / 2 + (math.pi / 2) * k / 3
            prof.append((r - b + b * math.cos(a), y0 + b + b * math.sin(a)))
    else:
        prof.append((r, y0))
    prof.append((0.0, y1))
    return lathe(prof, n, convex=True)


def gem(n: int = 8, h_top: float = 0.42, h_bot: float = 1.0, r_table: float = 0.58) -> Mesh:
    """Гранёный кристалл (бриллиант): площадка, корона, павильон. Свет по граням."""
    v = [(0.0, -h_bot, 0.0)]
    for i in range(n):
        a = 2 * math.pi * i / n
        v.append((math.cos(a), 0.0, -math.sin(a)))
    for i in range(n):
        a = 2 * math.pi * (i + 0.5) / n
        v.append((r_table * math.cos(a), h_top, -r_table * math.sin(a)))
    v.append((0.0, h_top, 0.0))
    f = []
    for i in range(n):
        j = (i + 1) % n
        f.append((0, 1 + j, 1 + i))
        f.append((1 + i, 1 + j, 1 + n + i))
        f.append((1 + j, 1 + n + j, 1 + n + i))
        f.append((1 + n + i, 1 + n + j, 2 * n + 1))
    return Mesh(np.array(v, float), np.array(f, np.int32), flat=True).prepare()


def facet_sphere(nu: int = 20, nv: int = 12) -> Mesh:
    """Гранёный шар (диско-шар): плоские четырёхугольные плитки, вершины у каждой плитки свои."""
    us = np.linspace(0, 2 * np.pi, nu + 1)
    vs = np.linspace(0, np.pi, nv + 1)
    verts: list[tuple[float, float, float]] = []
    f: list[tuple[int, int, int]] = []

    def p(vv: float, uu: float) -> tuple[float, float, float]:
        return (math.sin(vv) * math.cos(uu), math.cos(vv), -math.sin(vv) * math.sin(uu))

    for r in range(nv):
        for i in range(nu):
            a, b = p(vs[r], us[i]), p(vs[r], us[i + 1])
            c, d = p(vs[r + 1], us[i]), p(vs[r + 1], us[i + 1])
            k = len(verts)
            if r == 0:
                verts += [a, c, d]
                f.append((k, k + 1, k + 2))
            elif r == nv - 1:
                verts += [a, c, b]
                f.append((k, k + 1, k + 2))
            else:
                verts += [a, c, b, d]
                f.append((k, k + 1, k + 2))
                f.append((k + 2, k + 1, k + 3))
    return Mesh(np.array(verts, float), np.array(f, np.int32), flat=True).prepare()


# ======================= плоские контуры и выдавливание =======================
def signed_area(c: np.ndarray) -> float:
    """Площадь многоугольника со знаком: > 0 — против часовой (y вверх)."""
    x, y = c[:, 0], c[:, 1]
    return float(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def point_in_polygon(p: np.ndarray, poly: np.ndarray) -> bool:
    """Чётно-нечётное правило (луч вправо)."""
    x, y = float(p[0]), float(p[1])
    xs, ys = poly[:, 0], poly[:, 1]
    xn, yn = np.roll(xs, -1), np.roll(ys, -1)
    cond = (ys > y) != (yn > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = xs + (y - ys) * (xn - xs) / (yn - ys)
    return bool(np.count_nonzero(cond & (x < xi)) % 2)


def orient_contours(contours: Sequence[np.ndarray]) -> list[np.ndarray]:
    """Внешние контуры — против часовой, дырки — по часовой (по глубине вложенности). Шрифты бывают с любым
    направлением обхода (в TrueType внешние идут по часовой), поэтому направление выводится из геометрии."""
    cs = [np.asarray(c, float) for c in contours if len(c) >= 3 and abs(signed_area(np.asarray(c, float))) > 1e-9]
    out = []
    for i, c in enumerate(cs):
        probe = _inner_probe(c)
        depth = sum(1 for j, o in enumerate(cs) if j != i and point_in_polygon(probe, o))
        want_ccw = depth % 2 == 0
        if (signed_area(c) > 0) != want_ccw:
            c = c[::-1].copy()
        out.append(c)
    return out


def _inner_probe(c: np.ndarray) -> np.ndarray:
    """Точка чуть внутри контура возле его вершины (для проверки вложенности, надёжнее самой вершины)."""
    sgn = 1.0 if signed_area(c) > 0 else -1.0
    a, b = c[0], c[1]
    d = b - a
    nrm = np.array([-d[1], d[0]]) * sgn
    nrm /= np.linalg.norm(nrm) + 1e-12
    scale = float(np.ptp(c, axis=0).max()) * 1e-3 + 1e-6
    return (a + b) / 2 + nrm * scale


def inset(c: np.ndarray, d: float) -> np.ndarray:
    """Сдвиг контура внутрь материала на d (внешние против часовой, дырки по часовой: «левая» нормаль смотрит
    в материал у обоих). В острых углах сдвиг ограничен, чтобы не было «усов»."""
    prev, nxt = np.roll(c, 1, 0), np.roll(c, -1, 0)
    e1 = c - prev
    e2 = nxt - c
    e1 = e1 / (np.linalg.norm(e1, axis=1, keepdims=True) + 1e-12)
    e2 = e2 / (np.linalg.norm(e2, axis=1, keepdims=True) + 1e-12)
    n1 = np.stack([-e1[:, 1], e1[:, 0]], 1)
    n2 = np.stack([-e2[:, 1], e2[:, 0]], 1)
    nb = n1 + n2
    nb = nb / (np.linalg.norm(nb, axis=1, keepdims=True) + 1e-12)
    cosh = np.clip((nb * n1).sum(1), 0.4, 1.0)
    return c + nb * (d / cosh)[:, None]


def star_contour(r: float = 1.0, inner: float = 0.48, n: int = 5) -> np.ndarray:
    pts = []
    for i in range(2 * n):
        rr = r if i % 2 == 0 else r * inner
        a = math.pi / 2 + i * math.pi / n
        pts.append((rr * math.cos(a), rr * math.sin(a)))
    return np.array(pts)


def heart_contour(k: int = 48) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, k, endpoint=False)
    x = 16 * np.sin(t) ** 3
    y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    c = np.stack([x, y], 1) / 17.0
    c[:, 1] += 0.12  # центр масс сердца — посередине высоты
    return c[::-1].copy() if signed_area(c) < 0 else c


def circle_contour(r: float = 1.0, k: int = 40) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, k, endpoint=False)
    return np.stack([r * np.cos(t), r * np.sin(t)], 1)


@dataclass(eq=False)
class Extrusion:
    """Выдавленная фигура: перед (z = +depth/2, к зрителю) и зад — плоские грани, заливаются одним путём;
    фаска 45° и стенки — четырёхугольники. contours — плоские контуры (y вверх), уже ориентированные."""

    contours: list[np.ndarray]
    depth: float = 0.25
    bevel: float = 0.04
    quads: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]  # (K, 4, 3)
    qn: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]  # (K, 3) наружу
    qk: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]  # (K,) номер вдоль контура
    front: list[np.ndarray] = field(default_factory=list, repr=False)  # контуры передней грани (n, 3)
    back: list[np.ndarray] = field(default_factory=list, repr=False)
    lo: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]  # углы рамки (2,) в плоскости
    hi: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]

    def build(self) -> Extrusion:
        self.contours = orient_contours(self.contours)
        d2 = self.depth / 2
        b = max(0.0, min(self.bevel, d2 * 0.9))
        qs, ns, ks = [], [], []
        for c in self.contours:
            m = len(c)
            ring = inset(c, b) if b > 0 else c
            if b > 0:
                layers = [(ring, d2, 1.0), (c, d2 - b, 0.0), (c, -d2 + b, 0.0), (ring, -d2, -1.0)]
            else:
                layers = [(c, d2, 0.0), (c, -d2, 0.0)]
            # наружная нормаль стенки в плоскости: «правая» от направления обхода
            edge = np.roll(c, -1, 0) - c
            out2 = np.stack([edge[:, 1], -edge[:, 0]], 1)
            out2 = out2 / (np.linalg.norm(out2, axis=1, keepdims=True) + 1e-12)
            for (ca, za, sa), (cb, zb, sb) in zip(layers[:-1], layers[1:]):
                A = np.column_stack([ca, np.full(m, za)])
                B = np.column_stack([cb, np.full(m, zb)])
                q = np.stack([A, np.roll(A, -1, 0), np.roll(B, -1, 0), B], 1)
                n = np.cross(q[:, 1] - q[:, 0], q[:, 3] - q[:, 0])
                zsign = sa if sa else sb  # фаска спереди смотрит к зрителю, сзади — от него
                want = np.column_stack([out2, np.full(m, 0.7 * zsign)])
                n = n * np.where((n * want).sum(1) < 0, -1.0, 1.0)[:, None]
                qs.append(q)
                ns.append(n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12))
                ks.append(np.arange(m))
            self.front.append(np.column_stack([ring, np.full(m, d2)]))
            self.back.append(np.column_stack([ring, np.full(m, -d2)]))
        self.quads = np.concatenate(qs) if qs else np.zeros((0, 4, 3))
        self.qn = np.concatenate(ns) if ns else np.zeros((0, 3))
        self.qk = np.concatenate(ks) if ks else np.zeros(0, int)
        allp = np.concatenate(self.contours) if self.contours else np.zeros((1, 2))
        self.lo, self.hi = allp.min(0), allp.max(0)
        return self


# ======================= кеш =======================
def cached(cache: dict, key: tuple, build: Callable[[], object]):  # type: ignore[no-untyped-def]
    """Достать из кеша воркера или построить один раз."""
    k = ("three",) + key
    obj = cache.get(k)
    if obj is None:
        obj = build()
        cache[k] = obj
    return obj
