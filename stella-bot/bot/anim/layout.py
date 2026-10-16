"""Раскладка кадра: где земля у каждого плана, какого роста герои в каждом формате, где стоять нескольким актёрам
и куда ставить заголовок. Всё — в долях кадра (y вниз), пиксели — только у ground_y и char_height.

Числа подобраны по прототипам: главный герой занимает 50–60 % высоты квадратного кадра (в мелком масштабе персонажи
«теряются»), сверху остаётся зона под заголовок и пузыри реплик.
"""

from __future__ import annotations

GROUND: dict[str, float] = {"back": 0.86, "mid": 0.90, "front": 0.95}  # y ступней, доля высоты кадра
LANE_SCALE: dict[str, float] = {"back": 0.8, "mid": 0.9, "front": 1.0}
MAIN_HEIGHT: dict[str, float] = {"square": 0.55, "wide": 0.60, "tall": 0.38}  # рост «главного» героя, доля h
SAFE = 0.05  # безопасное поле по краям кадра (доля)
OFFSCREEN_L = -0.18  # x за левым краем кадра (вход/выход)
OFFSCREEN_R = 1.18

# в каком диапазоне x расставлять актёров и как далеко друг от друга (не больше), доли ширины
SPREAD: dict[str, tuple[float, float]] = {"square": (0.2, 0.8), "wide": (0.15, 0.85), "tall": (0.25, 0.75)}
MAX_GAP: dict[str, float] = {"square": 0.32, "wide": 0.30, "tall": 0.40}
HEAD_ROOM = 0.08  # над макушкой самого крупного героя остаётся хотя бы столько (доля h)

# зоны заголовка (y0, y1) — доли высоты кадра
TITLE_ZONES: dict[str, dict[str, tuple[float, float]]] = {
    "square": {"top": (0.05, 0.24), "center": (0.38, 0.62), "bottom": (0.76, 0.95)},
    "wide": {"top": (0.05, 0.25), "center": (0.37, 0.63), "bottom": (0.75, 0.95)},
    "tall": {"top": (0.06, 0.21), "center": (0.42, 0.58), "bottom": (0.82, 0.95)},
}


def _fmt(fmt: str) -> str:
    return fmt if fmt in MAIN_HEIGHT else "square"


def _lane(lane: str) -> str:
    return lane if lane in GROUND else "mid"


def ground_y(h: int, lane: str) -> float:
    """y земли (ступней) для плана lane в пикселях."""
    return GROUND[_lane(lane)] * h


def char_height(fmt: str, h: int, lane: str, size: float = 1.0) -> float:
    """Рост персонажа в пикселях: доля формата × масштаб плана × относительный рост (size 0.3–2).
    Не выше, чем помещается между землёй и верхним полем кадра."""
    lane = _lane(lane)
    size = min(2.0, max(0.3, size if size == size else 1.0))
    height = MAIN_HEIGHT[_fmt(fmt)] * h * LANE_SCALE[lane] * size
    return min(height, ground_y(h, lane) - HEAD_ROOM * h)


def spread_x(n: int, fmt: str) -> list[float]:
    """x для n актёров слева направо (доли ширины), симметрично относительно центра. Пока помещаются — стоят
    не дальше MAX_GAP друг от друга (чтобы разговаривали, а не кричали через весь кадр), иначе равномерно на всём
    диапазоне формата: square 0.2–0.8, wide 0.15–0.85, tall 0.25–0.75."""
    if n <= 0:
        return []
    if n == 1:
        return [0.5]
    lo, hi = SPREAD[_fmt(fmt)]
    step = min((hi - lo) / (n - 1), MAX_GAP[_fmt(fmt)])
    start = 0.5 - step * (n - 1) / 2
    return [round(start + step * i, 6) for i in range(n)]


def title_zone(fmt: str, position: str) -> tuple[float, float]:
    """(y0, y1) — полоса кадра под заголовок для top | center | bottom (неизвестное — top)."""
    zones = TITLE_ZONES[_fmt(fmt)]
    return zones.get(position, zones["top"])


def fmt_of(w: int, h: int) -> str:
    """Формат по размеру кадра: wide (шире), tall (выше) или square."""
    if w > h * 1.15:
        return "wide"
    if h > w * 1.15:
        return "tall"
    return "square"
