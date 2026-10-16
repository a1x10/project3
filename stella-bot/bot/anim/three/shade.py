"""Свет и материалы 3D: «игрушечная» рампа от освещённого цвета к сиреневой тени (не к чёрному), ободок (rim),
полусферный свет неба и земли, процедурное окружение для хрома, золота и камней, стекло с френелем.

Векторы — в пространстве камеры: x вправо, y вверх, z к зрителю. Свет — сверху-слева-спереди, как у 2D-героев.
Восемь материалов: plastic, toon, candy, clay, chrome, gold, glass, gem (формулы — design_wow §d.3, подобраны
по прототипам: с пластиком, у которого тень уходила в чёрное, игрушки выглядели «грязно»).
"""

from __future__ import annotations

from dataclasses import dataclass

import cairocffi as cairo
import numpy as np

from ..model import RGB
from ..palette import hx, lighten, mix, mul

MATERIALS = ("plastic", "toon", "candy", "clay", "chrome", "gold", "glass", "gem")

LIGHT = np.array([-0.45, 0.65, 0.60])
LIGHT = LIGHT / np.linalg.norm(LIGHT)
LILAC = np.array([0.22, 0.12, 0.38])  # куда уходит тень: тёплый сиреневый, а не чёрный
SKY = np.array([0.85, 0.9, 1.0])
GROUND = np.array([0.55, 0.45, 0.5])
GOLD_TINT = (1.0, 0.8, 0.35)


@dataclass(eq=False)
class Material:
    color: RGB = (0.3, 0.7, 1.0)
    kind: str = "plastic"  # MATERIALS
    rim: RGB = (0.75, 0.85, 1.0)
    alpha: float = 0.12  # стекло: прозрачность в середине (по краям плотнее — френель)
    vcolor: np.ndarray | None = None  # (N, 3) свой цвет у каждой вершины (брюшко, глазурь, полосы)


def _unit(a: np.ndarray) -> np.ndarray:
    return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-12)


def env(r: np.ndarray) -> np.ndarray:
    """Процедурное окружение для отражений: небо, светлый горизонт, земля и «софтбокс» сверху-слева."""
    y = r[:, 1]
    sky = np.array([0.55, 0.75, 1.0])
    hor = np.array([1.0, 0.97, 0.92])
    gnd = np.array([0.36, 0.32, 0.42])
    up = np.clip(y, 0, 1) ** 0.45
    dn = np.clip(-y, 0, 1) ** 0.35
    c = np.where((y >= 0)[:, None], hor * (1 - up[:, None]) + sky * up[:, None],
                 hor * 0.55 * (1 - dn[:, None]) + gnd * dn[:, None])
    c = c + 1.2 * np.exp(-((r[:, 0] + 0.45) ** 2 + (r[:, 1] - 0.55) ** 2) / 0.02)[:, None]
    return c


def env_gold(r: np.ndarray) -> np.ndarray:
    """Окружение для золота: бледно-золотое небо, яркий горизонт и резкая тёмная янтарная полоса под ним —
    как «металлический горизонт» у золотых букв (без оливкового оттенка, который даёт простое тонирование)."""
    y = r[:, 1]
    pale = np.array([1.0, 0.95, 0.68])
    mid = np.array([1.0, 0.8, 0.26])
    amber = np.array([0.82, 0.48, 0.08])
    deep = np.array([0.98, 0.78, 0.3])
    up = np.clip(y, 0, 1) ** 0.5
    dn = np.clip(-y, 0, 1) ** 0.5
    c = np.where((y >= 0)[:, None], pale * (1 - up[:, None]) + mid * up[:, None],
                 amber * (1 - dn[:, None]) + deep * dn[:, None])
    c = c + 0.9 * np.exp(-((r[:, 0] + 0.45) ** 2 + (r[:, 1] - 0.55) ** 2) / 0.02)[:, None]
    return c


def shade(N: np.ndarray, V: np.ndarray, mat: Material, base: np.ndarray | None = None) -> np.ndarray:
    """Цвет точек поверхности. N — нормали, V — направления на камеру (оба (n, 3), единичные).
    base — свой цвет каждой точки (иначе mat.vcolor или mat.color). Ответ (n, 3), у стекла — (n, 4) с альфой."""
    n = len(N)
    if base is None:
        base = mat.vcolor if mat.vcolor is not None and len(mat.vcolor) == n else np.asarray(mat.color, float)
    base = np.broadcast_to(np.asarray(base, float), (n, 3))
    ndl = N @ LIGHT
    h = _unit(LIGHT[None, :] + V)
    ndh = np.clip((N * h).sum(1), 0, 1)
    ndv = np.clip((N * V).sum(1), 0, 1)
    hemi = GROUND + (SKY - GROUND) * (0.5 + 0.5 * N[:, 1])[:, None]
    rim = ((1 - ndv) ** 3)[:, None] * np.asarray(mat.rim, float)
    k = mat.kind
    if k in ("chrome", "gold", "gem"):
        r = 2 * (N * V).sum(1)[:, None] * N - V
        if k == "gold":
            col = env_gold(r) * (0.6 + 0.4 * base / max(float(np.max(base)), 1e-3)) + 0.18 * rim
            col = col + (ndh ** 90)[:, None] * 1.2
        elif k == "gem":
            col = env(r) * (base * 1.15 + 0.1) * 0.95 + 0.3 * rim
            col = col + (ndh ** 60)[:, None] * 1.4
        else:
            col = env(r) * (0.55 + 0.45 * base) * 0.95 + 0.25 * rim
            col = col + (ndh ** 120)[:, None] * 1.5
    elif k == "toon":
        d = np.clip((ndl - 0.05) / 0.12, 0, 1)
        shadow = base * 0.6 + LILAC * 0.4
        col = shadow + (np.minimum(base * 1.05, 1) - shadow) * d[:, None]
        col = col + (np.clip((ndh - 0.95) / 0.02, 0, 1) * 0.8)[:, None] + 0.35 * rim
    elif k == "clay":
        d = np.clip((ndl + 0.5) / 1.5, 0, 1)
        d = d * d * (3 - 2 * d)
        shadow = base * 0.62 + LILAC * 0.38
        col = shadow + (base * 1.02 - shadow) * d[:, None]
        col = col * (0.88 + 0.12 * hemi) + 0.15 * rim
    elif k == "glass":
        r = 2 * (N * V).sum(1)[:, None] * N - V
        fres = (1 - ndv) ** 2.5
        sp = ndh ** 90
        col = base * 0.7 + 0.5 * env(r) * fres[:, None] + 2.0 * sp[:, None]
        a = np.clip(mat.alpha + 0.85 * fres + 0.9 * sp, 0, 1)
        return np.concatenate([np.clip(col, 0, 1), a[:, None]], 1)
    else:  # plastic / candy: свет = база, тень = база, сдвинутая в сиреневый
        d = np.clip((ndl + 0.2) / 1.0, 0, 1)
        d = d * d * (3 - 2 * d)
        shadow = base * 0.55 + LILAC * 0.45
        lit = np.minimum(base * 1.08 + 0.04, 1)
        col = shadow + (lit - shadow) * d[:, None]
        col = col * (0.85 + 0.15 * hemi)
        if k == "candy":
            col = col + (ndh ** 70)[:, None] * 0.9
        else:
            col = col + (ndh ** 30)[:, None] * 0.45
        col = col + 0.5 * rim
    return np.clip(col, 0, 1)


def material(color: RGB | None, kind: str | None, default_color: RGB, default_kind: str = "plastic",
             **kw: object) -> Material:
    """Материал предмета: цвет и вид из сценария или красивые значения по умолчанию."""
    k = kind if kind in MATERIALS else default_kind
    c = tuple(float(x) for x in color[:3]) if color is not None else default_color
    if color is None and k == "gold":
        c = (1.0, 0.82, 0.3)
    if color is None and k == "chrome":
        c = (0.92, 0.94, 1.0)
    return Material(c, k, **kw)  # type: ignore[arg-type]


# ---------- плоские заливки (передние грани букв и фигур) ----------
def metal_stops(kind: str, color: RGB) -> list[tuple[float, RGB]]:
    """Вертикальный градиент «металла» с резким тёмным горизонтом посередине."""
    if kind == "gold":
        return [(0.0, (1.0, 0.98, 0.75)), (0.45, (1.0, 0.83, 0.28)), (0.55, (0.93, 0.62, 0.1)),
                (1.0, (1.0, 0.88, 0.4))]
    if kind == "chrome":
        c = mix(color, (0.9, 0.93, 1.0), 0.6)
        return [(0.0, (0.98, 0.99, 1.0)), (0.45, mix(c, (0.62, 0.7, 0.86), 0.5)), (0.55, mix(c, (0.3, 0.33, 0.46), 0.6)),
                (1.0, mix(c, (0.86, 0.9, 0.98), 0.5))]
    if kind == "gem":
        return [(0.0, lighten(color, 0.55)), (0.45, lighten(color, 0.15)), (0.55, mul(color, 0.7)),
                (1.0, lighten(color, 0.3))]
    if kind == "candy":
        return [(0.0, lighten(color, 0.55)), (0.35, lighten(color, 0.12)), (1.0, mul(color, 0.82))]
    if kind == "toon":
        return [(0.0, lighten(color, 0.1)), (0.6, color), (0.61, mix(color, tuple(LILAC), 0.3)),
                (1.0, mix(color, tuple(LILAC), 0.3))]
    if kind == "clay":
        return [(0.0, lighten(color, 0.12)), (1.0, mix(color, tuple(LILAC), 0.3))]
    return [(0.0, lighten(color, 0.4)), (0.5, color), (1.0, mul(color, 0.82))]  # plastic, glass


def flat_fill(kind: str, color: RGB, y0: float, y1: float, x0: float | None = None,
              x1: float | None = None) -> cairo.LinearGradient:
    """Заливка плоской передней грани: вертикальный градиент по материалу от y0 до y1 (пиксели)."""
    if x0 is None or x1 is None:
        g = cairo.LinearGradient(0, y0, 0, y1)
    else:  # чуть по диагонали — свет сверху-слева
        g = cairo.LinearGradient(x0, y0, x0 + (x1 - x0) * 0.25, y1)
    for off, c in metal_stops(kind, color):
        g.add_color_stop_rgb(off, *c)
    return g


TITLE_STYLES = {
    # перед: градиент; бок: цвет стенок; второй цвет полосок стенок (карамель)
    "gold3d": {"front": "gold", "color": (1.0, 0.82, 0.3), "side": (0.95, 0.55, 0.12), "side2": None},
    "chrome3d": {"front": "chrome", "color": (0.85, 0.9, 1.0), "side": (0.42, 0.48, 0.64), "side2": None},
    "candy3d": {"front": "candy", "color": hx("#ff5fa2"), "side": hx("#ff3d8b"), "side2": (1.0, 0.96, 0.98)},
}
