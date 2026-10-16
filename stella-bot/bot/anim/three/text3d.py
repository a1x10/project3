"""Объёмный текст: буквы DejaVu Sans Bold (fontTools) выдавливаются с фаской, перед — градиент стиля и бегущий
блик; 3D-заголовки (gold3d, chrome3d, candy3d) с анимацией по буквам и надпись-предмет text3d.

Контуры TrueType обходятся в любом направлении (внешние обычно по часовой), поэтому направление выводится из
вложенности (mesh.orient_contours): внешние против часовой, дырки по часовой — тогда передняя грань — один путь
с правилом winding (дырки «О», «А», «Р», «№» получаются сами), а сдвиг фаски внутрь одинаков для всех контуров.
Каждая буква — свой маленький 3D-спрайт со своей камерой, как в одобренном прототипе.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass
from typing import Any

import cairocffi as cairo
import numpy as np
from fontTools.pens.basePen import BasePen

from .. import catalog, layout
from ..draw import clean_text, font_file
from ..ease import ease, ease_out_back, ease_out_bounce, window
from ..model import RGB, AnimError, PlannedTitle
from ..palette import mul
from .mesh import Extrusion, cached
from .render3d import Obj, draw_extrusion, sprite_camera, stats
from .shade import TITLE_STYLES, Material, metal_stops

CAP_MID = 0.365  # середина высоты заглавных DejaVu Sans Bold (em): вокруг неё вертится буква
DEPTH = 0.2  # толщина букв, em
BEVEL = 0.03
STAGGER = 0.07  # сдвиг анимации между соседними буквами, с
LETTER_ROT = (-0.25, -0.3, 0.0)  # лёгкий поворот: видны правая и нижняя стенки, как «тень» у объёмных букв


# ======================= контуры букв =======================
class _FlatPen(BasePen):
    """Перо fontTools, которое раскладывает кривые на отрезки (steps на кривую)."""

    def __init__(self, glyph_set: Any, steps: int):
        super().__init__(glyph_set)
        self.steps = max(1, steps)
        self.contours: list[list[tuple[float, float]]] = []
        self.cur: list[tuple[float, float]] | None = None

    def _moveTo(self, p):  # noqa: N802 — имена из fontTools
        self.cur = [p]

    def _lineTo(self, p):  # noqa: N802
        if self.cur is not None:
            self.cur.append(p)

    def _curveToOne(self, p1, p2, p3):  # noqa: N802
        if self.cur is None:
            return
        p0 = self.cur[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            u = 1 - t
            self.cur.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                             u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))

    def _qCurveToOne(self, p1, p2):  # noqa: N802
        if self.cur is None:
            return
        p0 = self.cur[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            u = 1 - t
            self.cur.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                             u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))

    def _closePath(self):  # noqa: N802
        if self.cur and len(self.cur) > 2:
            if self.cur[-1] == self.cur[0]:
                self.cur.pop()
            # повторы подряд (точка кривой совпала с вершиной) ломают нормали фаски
            pts = [p for i, p in enumerate(self.cur) if i == 0 or p != self.cur[i - 1]]
            if len(pts) > 2:
                self.contours.append(pts)
        self.cur = None

    _endPath = _closePath


@functools.lru_cache(maxsize=1)
def _font() -> tuple[dict, Any, Any, int]:
    from fontTools.ttLib import TTFont

    path = font_file(bold=True)
    if path is None:
        raise AnimError("не нашёлся шрифт DejaVu Sans Bold для объёмного текста")
    font = TTFont(path, lazy=True)
    return font.getBestCmap(), font.getGlyphSet(), font["hmtx"], font["head"].unitsPerEm


@dataclass(eq=False)
class Glyph:
    ch: str
    contours: list[np.ndarray]  # em, y вверх, от базовой линии; уже ориентированы
    adv: float  # ширина шага, em
    cx: float  # середина рамки буквы по x, em (от начала шага)
    lo_y: float
    hi_y: float


def glyph(ch: str, steps: int = 4, cache: dict | None = None) -> Glyph:
    """Контуры одной буквы (em). Нет в шрифте — «?»."""
    cache = {} if cache is None else cache

    def build() -> Glyph:
        from .mesh import orient_contours

        cmap, gs, hmtx, upem = _font()
        name = cmap.get(ord(ch)) if len(ch) == 1 else None
        if name is None:
            name = cmap.get(ord("?"))
        pen = _FlatPen(gs, steps)
        gs[name].draw(pen)
        cs = orient_contours([np.array(c, float) / upem for c in pen.contours])
        adv = hmtx[name][0] / upem
        if cs:
            allp = np.concatenate(cs)
            lo, hi = allp.min(0), allp.max(0)
            return Glyph(ch, cs, adv, float((lo[0] + hi[0]) / 2), float(lo[1]), float(hi[1]))
        return Glyph(ch, [], adv, adv / 2, 0.0, 0.0)

    return cached(cache, ("glyph", ch, steps), build)  # type: ignore[return-value]


def glyph_contours(text: str, steps: int = 4, cache: dict | None = None
                   ) -> tuple[list[tuple[list[np.ndarray], float, str]], float]:
    """Строка → [(контуры буквы в em, сдвиг x начала буквы, буква)], общая ширина в em (пробелы без контуров)."""
    out = []
    x = 0.0
    for ch in text:
        g = glyph(ch, steps, cache)
        if g.contours:
            out.append((g.contours, x, ch))
        x += g.adv
    return out, x


def letter_extrusion(ch: str, steps: int, cache: dict, depth: float = DEPTH, bevel: float = BEVEL) -> Extrusion | None:
    """Выдавленная буква с центром (cx, CAP_MID) в начале координат (так буква вертится вокруг себя)."""
    g = glyph(ch, steps, cache)
    if not g.contours:
        return None

    def build() -> Extrusion:
        shift = np.array([g.cx, CAP_MID])
        return Extrusion([c - shift for c in g.contours], depth=depth, bevel=bevel).build()

    return cached(cache, ("letter", ch, steps, depth, bevel), build)  # type: ignore[return-value]


# ======================= раскладка =======================
@dataclass
class Placed:
    ch: str
    i: int  # номер буквы с контуром (для сдвига анимации)
    x: float  # центр буквы (cx, CAP_MID) на экране, пиксели
    y: float
    line: int


@dataclass
class TitleLayout:
    em: float  # пикселей на em
    letters: list[Placed]
    lines: list[str]
    x0: float
    x1: float
    y0: float
    y1: float


def _line_metrics(line: str, steps: int, cache: dict) -> tuple[float, float, float]:
    """(ширина em, верх над базовой линией em, низ под ней em, с минусом)."""
    w = 0.0
    hi, lo = 0.73, 0.0
    for ch in line:
        g = glyph(ch, steps, cache)
        w += g.adv
        if g.contours:
            hi = max(hi, g.hi_y)
            lo = min(lo, g.lo_y)
    return w, hi, lo


def _splits(text: str, max_lines: int) -> list[list[str]]:
    """Варианты разбиения на 1..max_lines строк по пробелам (лучший для каждого числа строк — самый ровный)."""
    if "\n" in text:
        return [[s.strip() for s in text.split("\n") if s.strip()][:max_lines] or [text.strip()]]
    words = text.split(" ")
    out = [[text]]
    n = len(words)
    for k in range(2, max_lines + 1):
        if n < k:
            break
        best: list[str] | None = None
        best_w = 1e9
        if k == 2:
            cuts = [(i,) for i in range(1, n)]
        else:
            cuts = [(i, j) for i in range(1, n) for j in range(i + 1, n)]
        for cut in cuts:
            idx = (0,) + cut + (n,)
            lines = [" ".join(words[idx[q]:idx[q + 1]]) for q in range(k)]
            wmax = max(len(s) for s in lines)
            if wmax < best_w:
                best, best_w = lines, wmax
        if best:
            out.append(best)
    return out


LINE_GAP = 0.12  # em между строками (между низом одной и верхом следующей)


def fit_layout(text: str, zone_px: tuple[float, float, float, float], steps: int, cache: dict,
               max_em: float, max_lines: int = 3, anim_room: float = 0.12) -> TitleLayout:
    """Подобрать кегль и разбиение на строки, чтобы текст целиком (с толщиной, контуром и запасом на
    анимацию anim_room em) влез в прямоугольник zone_px = (x0, y0, x1, y1)."""
    zx0, zy0, zx1, zy1 = zone_px
    aw, ah = max(zx1 - zx0, 1.0), max(zy1 - zy0, 1.0)
    best: tuple[float, list[str], list[tuple[float, float, float]]] | None = None
    for lines in _splits(text, max_lines):
        mets = [_line_metrics(s, steps, cache) for s in lines]
        w_em = max(m[0] for m in mets) + 0.16  # толщина вправо и контур
        h_em = sum(m[1] - m[2] for m in mets) + LINE_GAP * (len(lines) - 1) + 0.12 + 2 * anim_room
        em = min(aw / w_em, ah / h_em, max_em)
        if best is None or em > best[0] * 1.04:  # больше строк — только если заметно крупнее
            best = (em, lines, mets)
    assert best is not None
    em, lines, mets = best
    total_h = (sum(m[1] - m[2] for m in mets) + LINE_GAP * (len(lines) - 1)) * em
    top = (zy0 + zy1) / 2 - total_h / 2 - 0.03 * em  # стенки торчат вниз — чуть выше центра
    letters: list[Placed] = []
    k = 0
    y = top
    xs0, xs1 = [], []
    for li, (line, (w, hi, lo)) in enumerate(zip(lines, mets)):
        base = y + hi * em
        x = (zx0 + zx1) / 2 - w * em / 2
        xs0.append(x)
        xs1.append(x + w * em)
        for ch in line:
            g = glyph(ch, steps, cache)
            if g.contours:
                letters.append(Placed(ch, k, x + g.cx * em, base - CAP_MID * em, li))
                k += 1
            x += g.adv * em
        y = base - lo * em + LINE_GAP * em
    return TitleLayout(em, letters, lines, min(xs0), max(xs1), top, top + total_h)


# ======================= стили =======================
def _line_cap(kind: str, color: RGB, y0: float, y1: float):
    """Градиент перед-грани по всей строке (а не по букве): металлический горизонт идёт одной линией."""
    g = cairo.LinearGradient(0, y0, 0, y1)
    for off, c in metal_stops(kind, color):
        g.add_color_stop_rgb(off, *c)

    def fill(_y0: float, _y1: float, _x0: float, _x1: float) -> cairo.Pattern:
        return g

    return fill


@dataclass
class LetterState:
    visible: bool = True
    dx: float = 0.0  # пиксели
    dy: float = 0.0
    scale: float = 1.0
    rot: tuple[float, float, float] = (0.0, 0.0, 0.0)  # добавка к LETTER_ROT


def _title_anim(anim: str, lt: float, i: int, t_abs: float, h: float, em: float, exit_k: float) -> LetterState:
    """Состояние буквы через lt секунд после её личного старта (lt < 0 — ещё не появилась)."""
    s = LetterState()
    idle = 0.04 * math.sin(t_abs * 3.0 - i * 0.5)
    if anim == "wave":
        if lt < 0:
            return LetterState(visible=False)
        s.scale = ease_out_back(window(lt, 0, 0.3))
        s.dy = -math.sin(t_abs * 4.2 - i * 0.55) * 0.13 * em
        s.rot = (0.0, 0.0, 0.05 * math.cos(t_abs * 4.2 - i * 0.55))
    elif anim == "spin":
        if lt < 0:
            return LetterState(visible=False)
        s.scale = ease("out", window(lt, 0, 0.18))
        turn = (1 - ease("out", window(lt, 0, 0.9))) * 2 * math.pi
        s.rot = (0.0, turn, idle if lt > 0.9 else 0.0)
    elif anim == "pop":
        if lt < 0:
            return LetterState(visible=False)
        s.scale = ease_out_back(window(lt, 0, 0.45), 2.2)
        s.rot = (0.0, 0.0, idle * window(lt, 0.45, 0.9))
    elif anim == "type":
        if lt < 0:
            return LetterState(visible=False)
        p = window(lt, 0, 0.16)
        s.scale = 1.35 - 0.35 * ease("out", p)  # «штамп»: появилась крупной и встала на место
        s.dy = -0.08 * em * (1 - p)
        s.rot = (0.0, 0.0, idle * window(lt, 0.3, 0.8))
    else:  # drop
        if lt < 0:
            return LetterState(visible=False)
        p = window(lt, 0, 0.7)
        s.dy = -(1 - ease_out_bounce(p)) * h * 0.35
        spin = (1 - ease("in_out", window(lt, 0, 0.6))) * 2.2
        s.rot = (0.0, spin, idle if lt > 0.8 else 0.0)
        if lt > 0.8:  # покачивание после приземления
            s.dy += 0.035 * em * math.sin(t_abs * 3.0 - i * 0.5) * window(lt, 0.8, 1.2)
    if exit_k > 0:
        s.scale *= 1 - ease("in_back", exit_k)
        s.dy += -0.15 * em * exit_k
        if s.scale <= 0.01:
            s.visible = False
    return s


def _draw_letter(ctx: cairo.Context, ex: Extrusion, x: float, y: float, em: float, st: LetterState,
                 mat: Material, cap: Any, side2: RGB | None, shine: Any, lw: float, sts: dict) -> None:
    size = 2 * em * max(st.scale, 0.0)
    if size < 1.0:
        return
    cam = sprite_camera(x + st.dx, y + st.dy, size)
    rot = (LETTER_ROT[0] + st.rot[0], LETTER_ROT[1] + st.rot[1], LETTER_ROT[2] + st.rot[2])
    o = Obj(ex, mat, rot=rot, cap=cap, side2=side2, shine=shine)
    from .render3d import world

    M, T = world(o)
    draw_extrusion(ctx, cam, o, M, T, lw * min(1.0, st.scale), sts, back_outline=False)


def _shine(t: float, x0: float, x1: float, em: float, y: float, period: float = 3.4,
           sweep: float = 0.9) -> tuple[float, float, float] | None:
    """Бегущий блик: раз в period секунд проходит слева направо за sweep секунд (x середины, y опоры, полуширина)."""
    if t < 0:
        return None
    ph = t % period
    if ph > sweep:
        return None
    hw = em * 0.8
    return (x0 - hw * 2 + (x1 - x0 + hw * 4) * ph / sweep, y, hw)


def title_steps(n_letters: int, quality: str) -> int:
    steps = 4 if n_letters <= 14 else 3 if n_letters <= 24 else 2
    return max(2, steps - 1) if quality == "fast" else steps


def draw_title3d(ctx: cairo.Context, title: PlannedTitle, t: float, w: int, h: int, cache: dict,
                 quality: str = "normal") -> None:
    """3D-заголовок на кадре w×h в момент t (секунды ролика): буквы падают/крутятся/выпрыгивают по очереди."""
    if t < title.t0 or t > title.t1:
        return
    text, _ = clean_text(title.text, catalog.MAX_TITLE_CHARS)
    text = text.strip()
    if not text:
        return
    style = TITLE_STYLES.get(title.style, TITLE_STYLES["gold3d"])
    fmt = layout.fmt_of(w, h)
    zy0, zy1 = layout.title_zone(fmt, title.position)
    steps = title_steps(len(text.replace(" ", "")), quality)
    zone = (w * layout.SAFE, h * zy0, w * (1 - layout.SAFE), h * zy1)
    lay = cached(cache, ("title_layout", text, w, h, zy0, zy1, steps),
                 lambda: fit_layout(text, zone, steps, cache, max_em=min(w, h) * 0.2))
    em = lay.em
    tt = t - title.t0
    n = len(lay.letters)
    dur = title.t1 - title.t0
    sts = stats(cache)
    kind, color = style["front"], style["color"]
    mat = Material(style["side"], "plastic")
    lw = min(3.0, max(1.2, em * 0.035))
    # линейные градиенты перед-граней — на строку (кеш по строке и кеглю)
    caps = {}
    for li in range(len(lay.lines)):
        ys = [p.y for p in lay.letters if p.line == li]
        if ys:
            yc = ys[0]
            caps[li] = _line_cap(kind, color, yc - 0.42 * em, yc + 0.42 * em)
    entry_end = (n - 1) * STAGGER + 0.9
    for p in lay.letters:
        ex = letter_extrusion(p.ch, steps, cache)
        if ex is None:
            continue
        lt = tt - p.i * STAGGER
        exit_k = 0.0
        if dur >= 1.2 and math.isfinite(dur):
            exit_k = window(tt, dur - 0.35, dur)
        st = _title_anim(title.anim, lt, p.i, t, h, em, exit_k)
        if not st.visible:
            continue
        shine = _shine(tt - entry_end, lay.x0, lay.x1, em, p.y)
        _draw_letter(ctx, ex, p.x, p.y, em, st, mat, caps.get(p.line), style["side2"], shine, lw, sts)


# ======================= надпись-предмет text3d =======================
def word_style(color: RGB | None, material: str | None) -> tuple[str, RGB, RGB, RGB | None]:
    """(вид передней грани, её цвет, цвет стенок, второй цвет полосок) для надписи-предмета."""
    if material in (None, "gold") and color is None:
        st = TITLE_STYLES["gold3d"]
        return st["front"], st["color"], st["side"], None
    if material == "chrome":
        st = TITLE_STYLES["chrome3d"]
        return "chrome", color or st["color"], st["side"], None
    if material == "candy" and color is None:
        st = TITLE_STYLES["candy3d"]
        return "candy", st["color"], st["side"], st["side2"]
    c = color if color is not None else (1.0, 0.82, 0.3)
    kind = material if material in ("gold", "toon", "candy", "clay", "gem", "glass", "plastic") else "plastic"
    return kind, c, mul(c, 0.72), None


def draw_word(ctx: cairo.Context, text: str, x: float, y: float, em: float, *, color: RGB | None,
              material: str | None, anim: str, t: float, phase: float, cache: dict, quality: str = "normal",
              max_w: float | None = None) -> None:
    """Надпись-предмет: строка объёмных букв с центром (x, y). em — пикселей на em (≈ высота строки)."""
    text, _ = clean_text(text, catalog.MAX_TEXT3D_CHARS)
    text = text.replace("\n", " ").strip()
    if not text:
        return
    steps = 3 if quality == "fast" else 4
    w_em, hi, lo = _line_metrics(text, steps, cache)
    if max_w is not None and w_em * em > max_w:
        em = max_w / max(w_em, 1e-3)
    kind, fcol, side, side2 = word_style(color, material)
    mat = Material(side, "plastic" if kind not in ("glass",) else "glass")
    lw = min(3.0, max(1.2, em * 0.035))
    sts = stats(cache)
    tp = t + phase
    # общий сдвиг/наклон слова по анимации предмета
    dy_all, rz_all, sc_all = 0.0, 0.0, 1.0
    if anim == "float":
        dy_all = -math.sin(tp * 2 * math.pi / 2.2) * 0.12 * em
        rz_all = 0.03 * math.sin(tp * 2 * math.pi / 4.4)
    elif anim == "pulse":
        beat = max(0.0, math.sin(tp * 2 * math.pi / 0.9)) ** 6
        sc_all = 1.0 + 0.1 * beat
    elif anim == "wobble":
        rz_all = 0.12 * math.sin(tp * 2 * math.pi / 1.1)
    elif anim == "swing":
        rz_all = 0.18 * math.sin(tp * 2 * math.pi / 1.6)
    em2 = em * sc_all
    total = w_em * em2
    cx0 = x - total / 2
    yc = y - ((hi + lo) / 2 - CAP_MID) * em2
    cap = _line_cap(kind, fcol, yc - 0.42 * em2, yc + 0.42 * em2)
    pen = 0.0
    k = 0
    pivot_y = y - 0.6 * em2 if anim == "swing" else y
    cr, sr = math.cos(rz_all), math.sin(rz_all)
    for ch in text:
        g = glyph(ch, steps, cache)
        ex = letter_extrusion(ch, steps, cache) if g.contours else None
        if ex is not None:
            lx = cx0 + (pen + g.cx) * em2
            ly = yc
            # поворот слова целиком (пиксели, y вниз)
            ox, oy = lx - x, ly - pivot_y
            lx, ly = x + ox * cr - oy * sr, pivot_y + ox * sr + oy * cr
            st = LetterState(rot=(0.0, 0.0, -rz_all))
            if anim == "spin":
                st.rot = (0.0, (tp * 2 * math.pi / 2.4 - k * 0.35) % (2 * math.pi), -rz_all)
            elif anim == "bounce":
                ph = (tp / 0.9 - k * 0.09) % 1.0
                st.dy = -4 * ph * (1 - ph) * 0.35 * em2
            ly += dy_all
            _draw_letter(ctx, ex, lx, ly, em2, st, mat, cap, side2, None, lw, sts)
            k += 1
        pen += g.adv

