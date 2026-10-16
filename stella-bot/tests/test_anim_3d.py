"""3D мультиков: сетки и их ориентация, контуры букв, материалы и предметы, запасной путь без сеток Гуро,
бюджет треугольников, заголовки в своей зоне, 3D-игрушки и детерминизм."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

np = pytest.importorskip("numpy")
cairo = pytest.importorskip("cairocffi")
pytest.importorskip("fontTools")

from bot.anim import catalog, layout  # noqa: E402
from bot.anim.model import PlannedTitle, Pose, PropSpec  # noqa: E402
from bot.anim.three import (draw_prop3d, draw_title3d, draw_toy3d, mesh_pattern_available,  # noqa: E402
                            toy_head_anchor)
from bot.anim.three import mesh as M  # noqa: E402
from bot.anim.three import meshpat, render3d, text3d, toys  # noqa: E402


# ---------- помощники ----------
def _surface(w: int = 96, h: int = 96):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    return s, cairo.Context(s)


def _pixels(s) -> np.ndarray:
    s.flush()
    h, stride = s.get_height(), s.get_stride()
    return np.frombuffer(bytes(s.get_data()), np.uint8).reshape(h, stride)[:, : s.get_width() * 4].reshape(
        h, s.get_width(), 4)


def _drawn(s) -> np.ndarray:
    return _pixels(s)[:, :, 3] > 0


def _non_uniform(s) -> bool:
    """Что-то нарисовано и это не одноцветная клякса (стекло полупрозрачное — смотрим все пиксели)."""
    px = _pixels(s)
    a = px[:, :, 3]
    if np.count_nonzero(a) < 30:
        return False
    rgba = px[a > 0].astype(int)
    return int((rgba.max(0) - rgba.min(0)).max()) > 20


@dataclass(frozen=True)
class FakeLook:
    base: str
    skin: tuple = (1.0, 0.88, 0.8)
    color: tuple | None = None
    accent: tuple | None = None
    eyes: tuple = (0.2, 0.15, 0.3)


class FaceSpy:
    """Простое лицо для тестов: два глаза и рот; считает вызовы и запоминает радиус."""

    def __init__(self) -> None:
        self.calls = 0
        self.radii: list[float] = []

    def __call__(self, ctx, look, pose, cx, cy, r, yaw) -> None:
        self.calls += 1
        self.radii.append(r)
        for s in (-1, 1):
            ctx.arc(cx + s * r * 0.4, cy, r * 0.15, 0, 2 * math.pi)
            ctx.set_source_rgb(0.05, 0.05, 0.1)
            ctx.fill()
        ctx.move_to(cx - r * 0.2, cy + r * 0.35)
        ctx.line_to(cx + r * 0.2, cy + r * 0.35)
        ctx.set_line_width(max(1.0, r * 0.08))
        ctx.stroke()


# ======================= сетки =======================
def _capsule():
    return toys._capsule(12)


PRIMITIVES = {
    "sphere": lambda: M.sphere(16),
    "ellipsoid": lambda: M.sphere(20, sx=0.5, sy=1.2, sz=0.8),
    "rounded_cube": lambda: M.sphere(16, e=0.3),
    "torus": lambda: M.torus(1.0, 0.4, 24, 12),
    "cylinder": lambda: M.cylinder(16),
    "cylinder_sharp": lambda: M.cylinder(16, bevel=0.0),
    "cone": lambda: M.cone(16),
    "gem": lambda: M.gem(8),
    "facet_sphere": lambda: M.facet_sphere(16, 10),
    "lathe_cup": lambda: M.lathe([(0.0, -1.0), (0.5, -1.0), (0.2, -0.5), (0.6, 0.8), (0.5, 0.85), (0.0, 0.4)], 16),
    "capsule": _capsule,
}


@pytest.mark.parametrize("name", sorted(PRIMITIVES))
def test_primitives_have_positive_volume_and_outward_faces(name: str) -> None:
    m = PRIMITIVES[name]()
    assert m.signed_volume() > 0
    # сетка замкнута: у каждого ребра две грани
    assert int((m.ef[:, 1] < 0).sum()) == 0
    assert np.all(np.isfinite(m.n)) and np.allclose(np.linalg.norm(m.n, axis=1), 1.0, atol=1e-6)
    if m.convex:  # у выпуклых каждая грань смотрит от центра
        tri = m.v[m.f]
        fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        assert np.all((fn * (tri.mean(1) - m.v.mean(0))).sum(1) > -1e-9)


def test_prepare_fixes_inverted_winding() -> None:
    good = M.sphere(12)
    bad = M.Mesh(good.v.copy(), good.f[:, ::-1].copy()).prepare()
    assert bad.signed_volume() > 0
    assert np.array_equal(np.sort(bad.f, 1), np.sort(good.f, 1))


def test_extrusion_quads_face_outward() -> None:
    ex = M.Extrusion([M.star_contour(), M.circle_contour(0.2)[::-1]], 0.3, 0.05).build()
    cen = ex.quads.mean(1)
    # стенки звезды смотрят от центра (наружная звезда) — кроме стенок дырки, они смотрят к центру
    r = np.hypot(cen[:, 0], cen[:, 1])
    outer = r > 0.35
    side_out = (ex.qn[outer, :2] * cen[outer, :2]).sum(1)
    assert np.mean(side_out > 0) > 0.95
    hole = r < 0.25
    assert np.all((ex.qn[hole, :2] * cen[hole, :2]).sum(1) < 0)
    assert len(ex.front) == 2 and len(ex.back) == 2


# ======================= буквы =======================
@pytest.mark.parametrize("ch,holes", [("О", 1), ("А", 1), ("Р", 1), ("№", 1), ("Ё", 0), ("Ж", 0), ("8", 2)])
def test_glyph_contours_orientation_and_holes(ch: str, holes: int) -> None:
    g = text3d.glyph(ch, 4, {})
    assert g.contours
    outers = [c for c in g.contours if M.signed_area(c) > 0]
    inner = [c for c in g.contours if M.signed_area(c) < 0]
    assert len(inner) == holes
    for c in inner:  # каждая дырка лежит внутри какого-то внешнего контура
        assert any(M.point_in_polygon(M._inner_probe(c), o) for o in outers)
    for c in outers:  # внешние ни в каком внешнем не лежат
        assert not any(M.point_in_polygon(M._inner_probe(c), o) for o in outers if o is not c)
    if ch == "Ё":
        assert len(outers) == 3  # буква и две точки


def test_orient_contours_handles_any_input_direction() -> None:
    sq = np.array([(0, 0), (2, 0), (2, 2), (0, 2)], float)
    hole = np.array([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)], float)
    for a, b in ((sq, hole), (sq[::-1], hole), (sq, hole[::-1]), (sq[::-1], hole[::-1])):
        out = M.orient_contours([a, b])
        assert M.signed_area(out[0]) > 0 and M.signed_area(out[1]) < 0


def test_letter_front_face_keeps_holes() -> None:
    """Перед «О» — один путь с правилом winding: середина буквы прозрачная, обод закрашен."""
    s, ctx = _surface(160, 160)
    title = PlannedTitle(0, "О", "gold3d", "pop", "center", 0.0, 9.0)
    draw_title3d(ctx, title, 3.0, 160, 160, {})
    a = _pixels(s)[:, :, 3]
    ys, xs = np.nonzero(a)
    cy, cx = int(ys.mean()), int(xs.mean())
    assert a[cy, cx] == 0  # дырка
    assert np.count_nonzero(a[cy, :]) > 10  # обод


# ======================= материалы и предметы =======================
@pytest.mark.parametrize("kind", catalog.PROPS_3D)
def test_every_prop_every_material_renders(kind: str) -> None:
    cache: dict = {}
    for mat in catalog.MATERIALS:
        for anim, t in (("spin", 0.7), ("bounce", 1.3)):
            s, ctx = _surface(72, 72)
            draw_prop3d(ctx, PropSpec(id="p", kind=kind, material=mat, anim=anim, text="Ёж"), t, 36, 36, 50, cache)
            assert _non_uniform(s), (kind, mat, anim)


@pytest.mark.parametrize("anim", catalog.PROP_ANIMS)
def test_prop_anims_and_colors(anim: str) -> None:
    cache: dict = {}
    s, ctx = _surface()
    draw_prop3d(ctx, PropSpec(id="a", kind="gift", anim=anim, color=(0.2, 0.6, 1.0)), 1.1, 48, 48, 60, cache)
    assert _non_uniform(s)


def test_prop_moves_with_time_and_ids_get_own_phase() -> None:
    cache: dict = {}
    imgs = []
    for t, pid in ((0.0, "a"), (0.4, "a"), (0.0, "b")):
        s, ctx = _surface()
        draw_prop3d(ctx, PropSpec(id=pid, kind="star", anim="spin"), t, 48, 48, 70, cache)
        imgs.append(_pixels(s).copy())
    assert not np.array_equal(imgs[0], imgs[1])
    assert not np.array_equal(imgs[0], imgs[2])


def test_bad_inputs_do_not_crash() -> None:
    cache: dict = {}
    s, ctx = _surface()
    draw_prop3d(ctx, PropSpec(id="x", kind="no_such_kind"), 0.0, 48, 48, 60, cache)  # → шар
    assert _non_uniform(s)
    for bad in (float("nan"), float("inf")):
        draw_prop3d(ctx, PropSpec(id="x", kind="cube"), bad, 48, 48, 60, cache)
        draw_prop3d(ctx, PropSpec(id="x", kind="cube"), 0.0, bad, 48, 60, cache)
    draw_prop3d(ctx, PropSpec(id="x", kind="cube"), 0.0, 48, 48, 0.5, cache)
    draw_prop3d(ctx, PropSpec(id="x", kind="text3d", text=""), 0.0, 48, 48, 30, cache)
    draw_prop3d(ctx, PropSpec(id="x", kind="text3d", text="🦄🦄 ok ❤"), 0.0, 48, 48, 30, cache)


def test_text3d_prop_fits_frame_width() -> None:
    s, ctx = _surface(200, 120)
    draw_prop3d(ctx, PropSpec(id="t", kind="text3d", text="ДЛИННАЯ ФРАЗА", anim="none"), 0.0, 100, 60, 80, {})
    xs = np.nonzero(_drawn(s).any(0))[0]
    assert xs.min() >= 0 and xs.max() <= 199 and xs.max() - xs.min() < 200


# ======================= запасной путь и бюджет =======================
def test_mesh_pattern_probe() -> None:
    assert isinstance(mesh_pattern_available(), bool)


def test_fallback_without_mesh_patterns(monkeypatch) -> None:
    monkeypatch.setattr(meshpat, "FORCE_FALLBACK", True)
    assert mesh_pattern_available() is False
    cache: dict = {}
    for kind in ("sphere", "torus", "planet", "gift"):
        s, ctx = _surface()
        draw_prop3d(ctx, PropSpec(id="f", kind=kind), 0.3, 48, 48, 70, cache)
        assert _non_uniform(s), kind
    s, ctx = _surface(120, 160)
    draw_toy3d(ctx, FakeLook("penguin3d"), Pose(), 60, 150, 140, 1, cache, FaceSpy())
    assert _non_uniform(s)


def test_fallback_has_no_background_seams(monkeypatch) -> None:
    """Без сеток Гуро треугольники стыкуются без щелей: внутри шара нет пикселей фона."""
    monkeypatch.setattr(meshpat, "FORCE_FALLBACK", True)
    s, ctx = _surface(200, 200)
    draw_prop3d(ctx, PropSpec(id="s", kind="sphere", color=(1.0, 1.0, 1.0)), 0.0, 100, 100, 180, {})
    a = _pixels(s)[:, :, 3]
    assert np.count_nonzero(a[60:140, 60:140] < 255) == 0


def test_triangle_budget_and_lod() -> None:
    budget = render3d.OBJECT_BUDGET
    assert budget * render3d.MAX_OBJECTS <= render3d.TRI_BUDGET
    for kind in catalog.PROPS_3D:
        cache: dict = {}
        s, ctx = _surface(720, 720)
        draw_prop3d(ctx, PropSpec(id="b", kind=kind, anim="spin"), 0.5, 360, 360, 700, cache)
        st = render3d.stats(cache)
        assert st["objects"] == 1
        if kind != "text3d":  # буквы — не сетки, у них свой счёт (кегль подбирается по ширине)
            assert 0 < st["tris"] <= budget, (kind, st["tris"])
    for base in catalog.BASES_3D:
        cache = {}
        s, ctx = _surface(720, 720)
        draw_toy3d(ctx, FakeLook(base), Pose(), 360, 710, 700, 1, cache, FaceSpy())
        assert 0 < render3d.stats(cache)["tris"] <= budget, base
    # детализация растёт с размером на экране
    assert M.lod_for_radius(20) < M.lod_for_radius(200)
    assert M.lod_for_radius(200, "fast") < M.lod_for_radius(200)


# ======================= заголовки =======================
LONG = ["Поздравляем с днём рождения Маш", "ОЧЕНЬДЛИННОЕСЛОВОБЕЗПРОБЕЛОВ!!!", "Ёжик и № 5, щука — ЙЦУКЕН ФЫВАП"]


@pytest.mark.parametrize("fmt", sorted(catalog.FORMATS))
def test_title_fits_its_zone(fmt: str) -> None:
    w, h = catalog.FORMATS[fmt]
    cache: dict = {}
    for text in LONG:
        assert len(text) <= catalog.MAX_TITLE_CHARS
        for pos in catalog.TITLE_POSITIONS:
            y0, y1 = layout.title_zone(fmt, pos)
            for style, anim, t in (("gold3d", "wave", 2.0), ("chrome3d", "wave", 2.7), ("candy3d", "drop", 3.0),
                                   ("gold3d", "type", 2.5)):
                s, ctx = _surface(w, h)
                draw_title3d(ctx, PlannedTitle(0, text, style, anim, pos, 0.0, 9.0), t, w, h, cache)
                d = _drawn(s)
                ys = np.nonzero(d.any(1))[0]
                xs = np.nonzero(d.any(0))[0]
                assert len(ys), (fmt, pos, text)
                assert ys.min() >= y0 * h - 2 and ys.max() <= y1 * h + 2, (fmt, pos, style, text, ys.min(), ys.max())
                assert xs.min() >= w * layout.SAFE * 0.5 and xs.max() <= w * (1 - layout.SAFE * 0.5), (fmt, text)


@pytest.mark.parametrize("anim", catalog.TITLE_ANIMS)
def test_title_anims_stagger_letters(anim: str) -> None:
    cache: dict = {}
    title = PlannedTitle(0, "ПРИВЕТ ЁЖИК", "gold3d", anim, "top", 1.0, 6.0)
    counts = []
    for t in (0.5, 1.45, 3.0):
        s, ctx = _surface(360, 360)
        draw_title3d(ctx, title, t, 360, 360, cache)
        counts.append(int(np.count_nonzero(_drawn(s))))
    assert counts[0] == 0  # до начала — ничего
    assert 0 < counts[1] < counts[2]  # в начале видно только первые буквы (сдвиг 0.07 с на букву)


def test_title_hidden_after_end_and_styles() -> None:
    cache: dict = {}
    for style in catalog.TITLE_STYLES:  # 2D-стили сюда не должны попадать, но и не ломают
        s, ctx = _surface(240, 240)
        draw_title3d(ctx, PlannedTitle(0, "Ура", style, "pop", "center", 0.0, 2.0), 1.0, 240, 240, cache)
        assert _non_uniform(s)
    s, ctx = _surface(240, 240)
    draw_title3d(ctx, PlannedTitle(0, "Ура", "gold3d", "pop", "center", 0.0, 2.0), 2.5, 240, 240, cache)
    assert not _drawn(s).any()
    s, ctx = _surface(240, 240)
    draw_title3d(ctx, PlannedTitle(0, "🦄🦄", "gold3d", "pop", "center", 0.0, 2.0), 1.0, 240, 240, cache)


# ======================= игрушки =======================
POSES = [
    Pose(),
    Pose(arm_r=(2.7, 0.5), arm_l=(1.2, 1.0), leg_l=(0.6, 0.8), leg_r=(-0.5, 0.0), lean=0.3, head_tilt=0.3),
    Pose(bob=-80, squash=1.25, yaw=0.9, wing_flap=1.0, scale=0.7, alpha=0.5, t=3.3),
    Pose(squash=0.7, yaw=-1.2, t=10.0, arm_l=(float("nan"), 0.0), bob=float("inf")),
]


@pytest.mark.parametrize("base", catalog.BASES_3D)
def test_toys_render_all_bases(base: str) -> None:
    cache: dict = {}
    for i, pose in enumerate(POSES):
        face = FaceSpy()
        s, ctx = _surface(160, 220)
        draw_toy3d(ctx, FakeLook(base, color=(0.9, 0.3, 0.5) if i == 1 else None), pose, 80, 210, 180,
                   -1 if i % 2 else 1, cache, face)
        assert _non_uniform(s), (base, i)
        if i in (0, 1):  # лицом к камере — лицо нарисовано, радиус разумный
            assert face.calls == 1 and 5 < face.radii[0] < 80
    ax, ay = toy_head_anchor(FakeLook(base), Pose(), 80, 210, 180, 1)
    assert ay < 210 - 180 * 0.95


def test_toy_face_hidden_when_turned_away() -> None:
    face = FaceSpy()
    s, ctx = _surface(160, 220)
    draw_toy3d(ctx, FakeLook("snowman3d"), Pose(yaw=1.5), 80, 210, 180, 1, {}, face)
    draw_toy3d(ctx, FakeLook("snowman3d"), Pose(yaw=1.5), 80, 210, 180, -1, {}, face)
    assert face.calls == 0


def test_toy_pose_changes_picture() -> None:
    cache: dict = {}
    imgs = []
    for pose in (Pose(), Pose(arm_r=(2.8, 0.3)), Pose(bob=-60), Pose(squash=0.75)):
        s, ctx = _surface(160, 260)
        draw_toy3d(ctx, FakeLook("robot3d"), pose, 80, 250, 180, 1, cache, FaceSpy())
        imgs.append(_pixels(s).copy())
    for other in imgs[1:]:
        assert not np.array_equal(imgs[0], other)


def test_toy_alpha_zero_draws_nothing() -> None:
    s, ctx = _surface()
    draw_toy3d(ctx, FakeLook("penguin3d"), Pose(alpha=0.0), 48, 90, 80, 1, {}, FaceSpy())
    assert not _drawn(s).any()


def test_toy_with_real_faces_if_available() -> None:
    chars = pytest.importorskip("bot.anim.chars")
    from bot.anim.model import CastSpec

    for base in catalog.BASES_3D:
        look = chars.build_look(CastSpec(id=base, base=base))
        s, ctx = _surface(160, 220)
        draw_toy3d(ctx, look, Pose(emotion="happy", mouth_open=0.5), 80, 210, 180, 1, {}, chars.draw_face)
        assert _non_uniform(s)


# ======================= детерминизм =======================
def _render_all(cache: dict) -> list[bytes]:
    out = []
    s, ctx = _surface(200, 200)
    draw_prop3d(ctx, PropSpec(id="d", kind="cake", anim="wobble"), 1.37, 100, 100, 150, cache)
    draw_prop3d(ctx, PropSpec(id="e", kind="disco_ball", anim="spin"), 0.81, 60, 60, 80, cache)
    out.append(bytes(s.get_data()))
    s, ctx = _surface(320, 320)
    draw_title3d(ctx, PlannedTitle(0, "Ура, Ёж!", "chrome3d", "wave", "center", 0.0, 9.0), 2.13, 320, 320, cache)
    out.append(bytes(s.get_data()))
    s, ctx = _surface(160, 220)
    draw_toy3d(ctx, FakeLook("penguin3d"), Pose(arm_l=(2.0, 0.4), t=1.7), 80, 210, 180, 1, cache, FaceSpy())
    out.append(bytes(s.get_data()))
    return out


def test_determinism_same_args_same_pixels() -> None:
    warm: dict = {}
    a = _render_all({})
    _render_all(warm)
    b = _render_all(warm)  # тёплый кеш
    c = _render_all({})
    assert a == b == c


def test_heavy_imports_stay_out_of_bot_anim() -> None:
    import subprocess
    import sys

    code = "import bot.anim, sys; print('bot.anim.three' in sys.modules, 'numpy' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    assert out.stdout.split() == ["False", "False"]
