"""Прототип 3D: примитивы (numpy), мульт-шейдинг по вершинам (Гуро через mesh pattern cairo), контур.

Порядок: художник по объектам (части персонажа) + внутри объекта сортировка треугольников по глубине.
Контур: «edges» — рёбра силуэта поверх объекта (для выпуклых), «hull» — вывернутая раздутая оболочка
(правильно перекрывается для тора/текста, но +50 % треугольников).
"""
import math

import cairocffi as cairo
import numpy as np

L = cairo.cairo


class Mesh:
    def __init__(self, v, f, smooth=True):
        v = np.asarray(v, np.float64)
        f = np.asarray(f, np.int32)
        if not smooth:  # плоские грани: у каждой грани свои вершины
            v = v[f].reshape(-1, 3)
            f = np.arange(len(v), dtype=np.int32).reshape(-1, 3)
        self.v, self.f = v, f
        fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
        vn = np.zeros_like(v)
        for j in range(3):
            np.add.at(vn, f[:, j], fn)
        self.vn = vn / (np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12)
        # рёбра и смежные грани — один раз
        e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
        key = np.sort(e, 1)
        # для плоских граней совпадающие по координатам вершины — одно ребро
        if not smooth:
            q = np.round(v * 1e4).astype(np.int64)
            _, uid = np.unique(q, axis=0, return_inverse=True)
            key = np.sort(uid.ravel()[e], 1)
        _, inv, cnt = np.unique(key[:, 0] * 10_000_000 + key[:, 1], return_inverse=True, return_counts=True)
        self.edges = e
        self.edge_face = np.tile(np.arange(len(f)), 3)
        self.edge_key = inv
        self.n_keys = len(cnt)
        self.ntri = len(f)


def ellipsoid(nu=20, nv=14):
    us = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    vs = np.linspace(0, np.pi, nv + 1)
    verts = [(0, 1, 0)]
    for j in range(1, nv):
        for i in range(nu):
            verts.append((math.sin(vs[j]) * math.cos(us[i]), math.cos(vs[j]), math.sin(vs[j]) * math.sin(us[i])))
    verts.append((0, -1, 0))
    f = []
    for i in range(nu):
        f.append((0, 1 + (i + 1) % nu, 1 + i))
    for j in range(nv - 2):
        for i in range(nu):
            a = 1 + j * nu + i
            b = 1 + j * nu + (i + 1) % nu
            c = a + nu
            d = b + nu
            f += [(a, b, c), (b, d, c)]
    last = len(verts) - 1
    base = 1 + (nv - 2) * nu
    for i in range(nu):
        f.append((base + i, base + (i + 1) % nu, last))
    return np.array(verts), np.array(f)


def torus(R=1.0, r=0.4, nu=32, nv=14):
    v = []
    for i in range(nu):
        a = 2 * np.pi * i / nu
        for j in range(nv):
            b = 2 * np.pi * j / nv
            v.append(((R + r * math.cos(b)) * math.cos(a), r * math.sin(b), (R + r * math.cos(b)) * math.sin(a)))
    f = []
    for i in range(nu):
        for j in range(nv):
            a = i * nv + j
            b = ((i + 1) % nu) * nv + j
            c = i * nv + (j + 1) % nv
            d = ((i + 1) % nu) * nv + (j + 1) % nv
            f += [(a, c, b), (b, c, d)]
    return np.array(v), np.array(f)


def gem(n=8):
    """Кристалл: верхняя площадка, корона, павильон (плоские грани)."""
    v = [(0, -1.0, 0)]
    for i in range(n):
        a = 2 * np.pi * i / n
        v.append((math.cos(a), 0.0, math.sin(a)))
    for i in range(n):
        a = 2 * np.pi * (i + 0.5) / n
        v.append((0.6 * math.cos(a), 0.45, 0.6 * math.sin(a)))
    v.append((0, 0.45, 0))
    f = []
    for i in range(n):
        f.append((0, 1 + (i + 1) % n, 1 + i))  # павильон
        a, b = 1 + i, 1 + (i + 1) % n
        c = 1 + n + i
        f.append((a, b, c))
        f.append((b, 1 + n + (i + 1) % n, c))
        f.append((c, 1 + n + (i + 1) % n, 2 * n + 1))
    return np.array(v), np.array(f)


def extrude(poly, depth=0.4):
    """Выдавленный выпукло-звёздный контур (звезда, сердце): веер от центра + бока."""
    poly = np.asarray(poly)
    n = len(poly)
    v = [(0, 0, -depth / 2), (0, 0, depth / 2)]
    for x, y in poly:
        v.append((x, y, -depth / 2))
    for x, y in poly:
        v.append((x, y, depth / 2))
    f = []
    for i in range(n):
        a, b = 2 + i, 2 + (i + 1) % n
        f.append((0, a, b))
        f.append((1, n + b, n + a))
        f.append((a, n + a, b))
        f.append((b, n + a, n + b))
    return np.array(v, float), np.array(f)


def star_poly(n=5, r1=1.0, r2=0.45):
    return [(r * math.cos(math.pi / 2 + math.pi * i / n), r * math.sin(math.pi / 2 + math.pi * i / n))
            for i, r in ((i, r1 if i % 2 == 0 else r2) for i in range(2 * n))]


def rot(ax, ay, az):
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


LIGHT = np.array([-0.55, 0.65, -0.55])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def toon_colors(n, view, base, ramp="soft"):
    """Цвет вершин: два тона (тень/свет) с мягким переходом + блик + ободок (rim)."""
    base = np.asarray(base)
    shade = base * 0.62 + np.array([0.08, 0.02, 0.18]) * 0.6
    lam = n @ LIGHT
    k = np.clip((lam - 0.05) / 0.25, 0, 1) if ramp == "soft" else (lam > 0.1).astype(float)
    k = k * k * (3 - 2 * k)
    col = shade[None] + (base - shade)[None] * k[:, None]
    h = LIGHT - view
    h /= np.linalg.norm(h)
    spec = np.clip(n @ h, 0, 1) ** 40
    col += (spec > 0.35)[:, None] * 0.0 + np.clip((spec - 0.25) * 3, 0, 1)[:, None] * 0.55
    rim = np.clip(1 - np.abs(n @ view), 0, 1) ** 3
    col += rim[:, None] * 0.25 * (lam > -0.2)[:, None]
    return np.clip(col, 0, 1)


def project(P, cam):
    z = P[:, 2] + cam["dist"]
    k = cam["f"] / z
    return np.stack([cam["cx"] + P[:, 0] * k, cam["cy"] - P[:, 1] * k], -1), z


def draw_mesh(ctx, mesh, M, pos, cam, color, outline="edges", lw=3.0, line=(0.12, 0.06, 0.2), flat=False,
              stats=None):
    """Нарисовать один объект. M — 3x3 поворот+масштаб, pos — сдвиг в мире."""
    P = mesh.v @ M.T + pos
    N = mesh.vn @ np.linalg.inv(M)  # нормали при неравномерном масштабе
    N /= np.linalg.norm(N, axis=1, keepdims=True) + 1e-12
    S, z = project(P, cam)
    F = mesh.f
    tri = P[F]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    cen = tri.mean(1) + np.array([0, 0, cam["dist"]])
    facing = (fn * cen).sum(1) < 0
    view = np.array([0, 0, 1.0])
    if flat:
        fnn = fn / (np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12)
        fc = toon_colors(fnn, view, color, ramp="hard")
        vc = np.repeat(fc[:, None, :], 3, 1)
    else:
        vc = toon_colors(N, view, color)[F]
    if outline == "hull":
        Ph = P + N * lw * cam["dist"] / cam["f"]  # толщина в пикселях на расстоянии центра
        Sh, _ = project(Ph, cam)
        trh = Ph[F]
        fnh = np.cross(trh[:, 1] - trh[:, 0], trh[:, 2] - trh[:, 0])
        cenh = trh.mean(1) + np.array([0, 0, cam["dist"]])
        back = (fnh * cenh).sum(1) > 0
        idx_h = np.nonzero(back)[0]
        idx_f = np.nonzero(facing)[0]
        depth = np.concatenate([cenh[idx_h, 2], cen[idx_f, 2]])
        pts = np.concatenate([Sh[F[idx_h]], S[F[idx_f]]])
        cols = np.concatenate([np.broadcast_to(np.array(line), (len(idx_h), 3, 3)), vc[idx_f]])
        order = np.argsort(-depth, kind="stable")
        pts, cols = pts[order], cols[order]
    else:
        idx = np.nonzero(facing)[0]
        order = idx[np.argsort(-cen[idx, 2])]
        pts, cols = S[F[order]], vc[order]
    if stats is not None:
        stats["tri"] = stats.get("tri", 0) + len(pts)
    if not len(pts):
        return
    # mesh pattern (Гуро); рисуем только в рамке объекта
    ptr = L.cairo_pattern_create_mesh()
    if flat:  # плоские грани: расширяем треугольник на 0.6 px от центра — без швов
        c = pts.mean(1, keepdims=True)
        d = pts - c
        ln = np.linalg.norm(d, axis=2, keepdims=True) + 1e-9
        pts = pts + d / ln * 0.6
    for (p0, p1, p2), (c0, c1, c2) in zip(pts.tolist(), cols.tolist(), strict=True):
        L.cairo_mesh_pattern_begin_patch(ptr)
        L.cairo_mesh_pattern_move_to(ptr, *p0)
        L.cairo_mesh_pattern_line_to(ptr, *p1)
        L.cairo_mesh_pattern_line_to(ptr, *p2)
        L.cairo_mesh_pattern_set_corner_color_rgb(ptr, 0, *c0)
        L.cairo_mesh_pattern_set_corner_color_rgb(ptr, 1, *c1)
        L.cairo_mesh_pattern_set_corner_color_rgb(ptr, 2, *c2)
        L.cairo_mesh_pattern_end_patch(ptr)
    x0, y0 = pts.reshape(-1, 2).min(0)
    x1, y1 = pts.reshape(-1, 2).max(0)
    ctx.save()
    ctx.rectangle(math.floor(x0) - 1, math.floor(y0) - 1, math.ceil(x1 - x0) + 3, math.ceil(y1 - y0) + 3)
    ctx.clip()
    ctx.set_source(cairo.Pattern._from_pointer(ptr, incref=False))
    ctx.paint()
    ctx.restore()
    if outline == "edges":
        fe = facing[mesh.edge_face]
        cnt = np.bincount(mesh.edge_key, weights=fe.astype(float), minlength=mesh.n_keys)
        sil = (cnt == 1)[mesh.edge_key] & fe
        ctx.set_source_rgb(*line)
        ctx.set_line_width(lw)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        for i0, i1 in mesh.edges[sil].tolist():
            ctx.move_to(*S[i0])
            ctx.line_to(*S[i1])
        ctx.stroke()


# ---------- 3D-«игрушка»: персонаж из эллипсоидов + нарисованное 2D-лицо ----------
SPHERE = Mesh(*ellipsoid(22, 16))
SMALL = Mesh(*ellipsoid(14, 10))


def toy(ctx, cam, t, color, x=0.0, y=0.0, turn=0.0, face=None, stats=None):
    """Части: (имя, меш, центр, радиусы, родитель-голова?). Ходьба/подпрыгивание — простые синусы."""
    face = face or {}
    R = rot(0.08, turn, 0.0)
    bounce = abs(math.sin(t * 6)) * 0.12
    sq = 1 + 0.06 * math.sin(t * 12)
    root = np.array([x, y + bounce, 0.0])
    parts = [
        ("foot_l", SMALL, (-0.32, -0.95, 0.05 + 0.15 * math.sin(t * 6)), (0.26, 0.16, 0.34), color, 1),
        ("foot_r", SMALL, (0.32, -0.95, 0.05 - 0.15 * math.sin(t * 6)), (0.26, 0.16, 0.34), color, 1),
        ("body", SPHERE, (0, -0.45, 0), (0.62 / sq ** 0.5, 0.6 * sq, 0.55), color, 0),
        ("belly", SMALL, (0, -0.45, -0.3), (0.42, 0.42, 0.28), (1, 0.95, 0.85), 0),
        ("arm_l", SMALL, (-0.66, -0.35, 0), (0.18, 0.34, 0.18), color, 2),
        ("arm_r", SMALL, (0.66, -0.25 + 0.15 * math.sin(t * 8), -0.1), (0.18, 0.34, 0.18), color, 2),
        ("head", SPHERE, (0, 0.55, 0), (0.85, 0.72, 0.75), color, 0),
        ("ear_l", SMALL, (-0.5, 1.2, 0.05), (0.2, 0.36, 0.12), color, 0),
        ("ear_r", SMALL, (0.5, 1.2, 0.05), (0.2, 0.36, 0.12), color, 0),
    ]
    drawn = []
    for name, mesh, c, r, col, _ in parts:
        ang = 0.0
        if name.startswith("arm"):
            ang = (0.5 if name == "arm_l" else -0.9 - 0.4 * math.sin(t * 8))
        if name.startswith("ear"):
            ang = (0.35 if name == "ear_l" else -0.35)
        M = R @ rot(0, 0, ang) @ np.diag(r)
        pos = R @ np.array(c) + root
        drawn.append(((pos[2]), name, mesh, M, pos, col))
    # художник по частям: дальние первыми (z растёт от камеры)
    for _z, name, mesh, M, pos, col in sorted(drawn, key=lambda d: -d[0]):
        draw_mesh(ctx, mesh, M, pos, cam, col, outline="edges", lw=3.5, stats=stats)
        if name == "head":
            face_decals(ctx, cam, R, pos, face)


def face_decals(ctx, cam, R, head_pos, face):
    """Глаза/рот — 2D поверх головы, в точках на её поверхности; сжимаются по углу к камере."""
    for side in (-1, 1):
        local = np.array([side * 0.32, 0.05, -0.62])
        n = R @ (local / np.linalg.norm(local))
        p = R @ local + head_pos
        if n[2] > -0.15:
            continue  # отвернулся
        (sx, sy), = project(p[None], cam)[0]
        k = cam["f"] / (p[2] + cam["dist"])
        sxk = max(0.25, -n[2])
        ctx.save()
        ctx.translate(sx, sy)
        ctx.scale(sxk, 1)
        rx, ry = 0.15 * k, 0.2 * k
        ctx.arc(0, 0, 1, 0, 0)
        ctx.new_path()
        ctx.save(); ctx.scale(rx, ry); ctx.arc(0, 0, 1, 0, 2 * math.pi); ctx.restore()
        ctx.set_source_rgb(0.08, 0.04, 0.12)
        ctx.fill()
        ctx.save(); ctx.translate(-rx * 0.3, -ry * 0.35); ctx.scale(rx * 0.38, ry * 0.3)
        ctx.arc(0, 0, 1, 0, 2 * math.pi); ctx.restore()
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        ctx.save(); ctx.translate(rx * 0.3, ry * 0.4); ctx.scale(rx * 0.16, ry * 0.12)
        ctx.arc(0, 0, 1, 0, 2 * math.pi); ctx.restore()
        ctx.fill()
        ctx.restore()
        # румянец
        lb = np.array([side * 0.55, -0.18, -0.48])
        nb = R @ (lb / np.linalg.norm(lb))
        if nb[2] < -0.2:
            pb = R @ lb + head_pos
            (bx, by), = project(pb[None], cam)[0]
            g = cairo.RadialGradient(bx, by, 0, bx, by, 0.14 * k)
            g.add_color_stop_rgba(0, 1, 0.4, 0.5, 0.6)
            g.add_color_stop_rgba(1, 1, 0.4, 0.5, 0)
            ctx.set_source(g)
            ctx.arc(bx, by, 0.14 * k, 0, 2 * math.pi)
            ctx.fill()
    lm = np.array([0.0, -0.22, -0.7])
    nm = R @ (lm / np.linalg.norm(lm))
    if nm[2] < -0.2:
        pm = R @ lm + head_pos
        (mx, my), = project(pm[None], cam)[0]
        k = cam["f"] / (pm[2] + cam["dist"])
        o = face.get("open", 0.5)
        ctx.move_to(mx - 0.13 * k, my)
        ctx.curve_to(mx - 0.06 * k, my + 0.14 * k * (0.4 + o), mx + 0.06 * k, my + 0.14 * k * (0.4 + o), mx + 0.13 * k, my)
        ctx.close_path()
        ctx.set_source_rgb(0.45, 0.05, 0.15)
        ctx.fill_preserve()
        ctx.set_source_rgb(0.12, 0.06, 0.2)
        ctx.set_line_width(2.5)
        ctx.stroke()
