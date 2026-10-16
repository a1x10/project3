"""Заливка треугольников плавным цветом (Гуро) через cairo mesh pattern и запасной путь без него.

В cairocffi нет класса MeshPattern, но в самой libcairo (≥ 1.12) он есть: зовём cairo_pattern_create_mesh и
cairo_mesh_pattern_* напрямую через низкоуровневый cffi и оборачиваем готовый указатель в cairo.Pattern.
Каждый треугольник — «заплатка» с цветом в трёх углах. Если такой вызов недоступен (старая libcairo) или
выключен (FORCE_FALLBACK в тестах) — «расширенные треугольники»: каждый заливается средним цветом и чуть раздут
от центра (на 0.8 px), чтобы между соседями не просвечивали щели.
"""

from __future__ import annotations

import math

import cairocffi as cairo
import numpy as np

FORCE_FALLBACK = False  # тесты и отладка: делать вид, что сеток Гуро нет
EXPAND_PX = 0.8

_available: bool | None = None


def _probe() -> bool:
    try:
        if cairo.cairo_version() < 11200:
            return False
        lib = cairo.cairo
        ptr = lib.cairo_pattern_create_mesh()
        lib.cairo_mesh_pattern_begin_patch(ptr)
        lib.cairo_mesh_pattern_move_to(ptr, 0.0, 0.0)
        lib.cairo_mesh_pattern_line_to(ptr, 4.0, 0.0)
        lib.cairo_mesh_pattern_line_to(ptr, 0.0, 4.0)
        for k in range(3):
            lib.cairo_mesh_pattern_set_corner_color_rgb(ptr, k, 1.0, 0.0, 0.0)
        lib.cairo_mesh_pattern_end_patch(ptr)
        ok = lib.cairo_pattern_status(ptr) == 0
        lib.cairo_pattern_destroy(ptr)
        return bool(ok)
    except Exception:  # нет символа в библиотеке, другой бэкенд cffi — работаем запасным путём
        return False


def mesh_pattern_available() -> bool:
    """Можно ли заливать сеткой Гуро (cairo mesh pattern) в этом процессе."""
    global _available
    if FORCE_FALLBACK:
        return False
    if _available is None:
        _available = _probe()
    return _available


def gouraud_pattern(pts: np.ndarray, cols: np.ndarray) -> cairo.Pattern:
    """Паттерн из треугольников pts (k, 3, 2) с цветами углов cols (k, 3, 3|4); порядок — порядок рисования
    (дальние первыми: следующая заплатка ложится поверх предыдущей)."""
    lib = cairo.cairo
    ptr = lib.cairo_pattern_create_mesh()
    begin, end = lib.cairo_mesh_pattern_begin_patch, lib.cairo_mesh_pattern_end_patch
    move, line = lib.cairo_mesh_pattern_move_to, lib.cairo_mesh_pattern_line_to
    rgba = cols.shape[-1] == 4
    corner = lib.cairo_mesh_pattern_set_corner_color_rgba if rgba else lib.cairo_mesh_pattern_set_corner_color_rgb
    P = pts.reshape(-1, 6).tolist()
    C = cols.reshape(len(cols), -1).tolist()
    if rgba:
        for p, c in zip(P, C, strict=True):
            begin(ptr)
            move(ptr, p[0], p[1])
            line(ptr, p[2], p[3])
            line(ptr, p[4], p[5])
            corner(ptr, 0, c[0], c[1], c[2], c[3])
            corner(ptr, 1, c[4], c[5], c[6], c[7])
            corner(ptr, 2, c[8], c[9], c[10], c[11])
            end(ptr)
    else:
        for p, c in zip(P, C, strict=True):
            begin(ptr)
            move(ptr, p[0], p[1])
            line(ptr, p[2], p[3])
            line(ptr, p[4], p[5])
            corner(ptr, 0, c[0], c[1], c[2])
            corner(ptr, 1, c[3], c[4], c[5])
            corner(ptr, 2, c[6], c[7], c[8])
            end(ptr)
    return cairo.Pattern._from_pointer(ptr, incref=False)


def expand(pts: np.ndarray, px: float = EXPAND_PX) -> np.ndarray:
    """Раздуть многоугольники (k, m, 2) от их центра на px пикселей — без щелей между соседями."""
    c = pts.mean(1, keepdims=True)
    d = pts - c
    ln = np.linalg.norm(d, axis=2, keepdims=True) + 1e-9
    return c + d * (1.0 + px / ln)


def fill_flat(ctx: cairo.Context, pts: np.ndarray, cols: np.ndarray, px: float = EXPAND_PX) -> None:
    """Каждый многоугольник (k, m, 2) — своим цветом cols (k, 3|4), раздутый на px (сглаженная заливка)."""
    if not len(pts):
        return
    P = expand(pts, px).tolist() if px != 0 else pts.tolist()
    C = np.clip(cols, 0, 1).tolist()
    rgba = len(C[0]) == 4
    move, line, close, fill = ctx.move_to, ctx.line_to, ctx.close_path, ctx.fill
    for poly, c in zip(P, C, strict=True):
        move(*poly[0])
        for q in poly[1:]:
            line(*q)
        close()
        if rgba:
            ctx.set_source_rgba(c[0], c[1], c[2], c[3])
        else:
            ctx.set_source_rgb(c[0], c[1], c[2])
        fill()


def paint_triangles(ctx: cairo.Context, pts: np.ndarray, cols: np.ndarray, smooth: bool = True) -> None:
    """Треугольники (k, 3, 2), цвета углов (k, 3, 3|4): сеткой Гуро (обрезано рамкой объекта), а без неё —
    запасным путём (средний цвет на треугольник, раздутый от центра)."""
    if not len(pts):
        return
    if smooth and mesh_pattern_available():
        x0, y0 = pts.reshape(-1, 2).min(0)
        x1, y1 = pts.reshape(-1, 2).max(0)
        ctx.save()
        ctx.rectangle(math.floor(x0) - 1, math.floor(y0) - 1, math.ceil(x1 - x0) + 3, math.ceil(y1 - y0) + 3)
        ctx.clip()
        ctx.set_source(gouraud_pattern(pts, cols))
        ctx.paint()
        ctx.restore()
        return
    # без сглаживания и с небольшим раздуванием: соседние треугольники стыкуются без светлых «волосков»,
    # а ступеньки внешнего края закрывает контур силуэта
    ctx.save()
    ctx.set_antialias(cairo.ANTIALIAS_NONE)
    fill_flat(ctx, pts, cols.mean(1), 0.5)
    ctx.restore()
