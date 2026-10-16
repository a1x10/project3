"""3D мультика: предметы из PROPS_3D, объёмные заголовки (gold3d/chrome3d/candy3d) и 3D-игрушки (robot3d,
penguin3d, snowman3d). Всё — «3D-спрайты»: у каждого объекта своя маленькая перспективная камера в его точке
кадра, свет общий. Подробности — design_wow §d.

Модуль тяжёлый (numpy, cairocffi, fontTools): его импортирует только процесс рендера.
"""

from __future__ import annotations

from typing import Any, Callable

import cairocffi as cairo

from ..model import PlannedTitle, Pose, PropSpec
from .meshpat import mesh_pattern_available
from .props3d import draw_prop
from .text3d import draw_title3d as _draw_title3d
from .toys import draw_toy, toy_head_anchor

__all__ = ["draw_prop3d", "draw_title3d", "draw_toy3d", "mesh_pattern_available", "toy_head_anchor"]

FaceFn = Callable[[Any, Any, Pose, float, float, float, float], None]


def draw_prop3d(ctx: cairo.Context, prop: PropSpec, t: float, x: float, y: float, size_px: float, cache: dict,
                quality: str = "normal") -> None:
    """3D-предмет prop.kind (из PROPS_3D; text3d — надпись prop.text) с центром (x, y) и высотой size_px
    в момент t. Цвет и материал по умолчанию — свои у каждого предмета. Тень под предметом не рисует."""
    draw_prop(ctx, prop, t, x, y, size_px, cache, quality)


def draw_title3d(ctx: cairo.Context, title: PlannedTitle, t: float, w: int, h: int, cache: dict,
                 quality: str = "normal") -> None:
    """3D-заголовок (gold3d/chrome3d/candy3d) в зоне layout.title_zone, анимация по буквам."""
    _draw_title3d(ctx, title, t, w, h, cache, quality)


def draw_toy3d(ctx: cairo.Context, look: Any, pose: Pose, x: float, y: float, height_px: float, facing: int,
               cache: dict, face_fn: FaceFn) -> None:
    """3D-игрушка look.base ∈ BASES_3D в позе pose; (x, y) — точка между ступнями на земле, height_px — рост.
    Лицо рисует face_fn(ctx, look, pose, cx, cy, r, yaw) — то же 2D-лицо, что у остальных героев."""
    draw_toy(ctx, look, pose, x, y, height_px, facing, cache, face_fn)
