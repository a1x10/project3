"""Персонажи мультика: внешность (Look), кукла (draw_character), лицо (draw_face) и точка над головой.

Тянет cairo — импортируй только в процессе рендера (бот импортирует лишь bot.anim и лёгкие модули).
"""

from .body import draw_character, head_anchor
from .face import draw_face
from .look import Look, build_look

__all__ = ["Look", "build_look", "draw_character", "draw_face", "head_anchor"]
