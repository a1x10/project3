"""Примитивы рисования мультика на cairocffi: фигуры, мультяшная обводка, объём и cel-тень, конечности-«шланги»,
сердечки и звёзды, мягкие тени, текст DejaVu Sans (кириллица есть) и картинки-спрайты.

Внешний вид перенесён из прототипа персонажей (wow/rig.py) без изменений: одна обводка INK, круглые стыки,
радиальный «объём» со светом сверху-слева, двухтоновая тень сдвинутой копией фигуры.
"""

from __future__ import annotations

import functools
import io
import math
import os
import re
import unicodedata
from typing import Any, Callable, Sequence

import cairocffi as cairo

from .model import AnimError
from .palette import INK, RGB, lighten, mul

FONT = "DejaVu Sans"
FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF",
             "/usr/share/fonts/truetype", "/usr/local/share/fonts")
CAP_MID = 0.36  # половина высоты заглавной буквы DejaVu Sans в долях кегля: так строка центрируется по y
MAX_SPRITE_PIXELS = 4096 * 4096
SHADOW_INK = (0.08, 0.04, 0.15)  # тени на земле — тёплый фиолетовый, не чёрный


# ---------- поверхность и цвет ----------
def new_surface(w: int, h: int) -> tuple[cairo.ImageSurface, cairo.Context]:
    """Прозрачная ARGB32-поверхность w×h и контекст к ней."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, int(w)), max(1, int(h)))
    return surface, cairo.Context(surface)


def set_source(ctx: cairo.Context, fill: Any, alpha: float = 1.0) -> None:
    """Источник рисования: RGB, RGBA (кортеж/список 0..1) или готовый cairo.Pattern (alpha к нему не применяется —
    для полупрозрачного паттерна используй paint_with_alpha или группу)."""
    if isinstance(fill, cairo.Pattern):
        ctx.set_source(fill)
        return
    if len(fill) >= 4:
        ctx.set_source_rgba(fill[0], fill[1], fill[2], fill[3] * alpha)
    elif alpha >= 1.0:
        ctx.set_source_rgb(fill[0], fill[1], fill[2])
    else:
        ctx.set_source_rgba(fill[0], fill[1], fill[2], alpha)


# ---------- фигуры (только путь; заливает вызывающий) ----------
def ellipse(ctx: cairo.Context, cx: float, cy: float, rx: float, ry: float, rot: float = 0.0) -> None:
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(rot)
    ctx.scale(max(abs(rx), 1e-4), max(abs(ry), 1e-4))
    ctx.new_sub_path()
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.restore()


def rrect(ctx: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    """Прямоугольник со скруглёнными углами радиуса r (не больше половины стороны)."""
    r = max(0.0, min(r, w / 2, h / 2))
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.close_path()


def smooth_closed(ctx: cairo.Context, pts: Sequence[tuple[float, float]], tension: float = 0.5) -> None:
    """Замкнутая гладкая кривая (Catmull-Rom → Безье) через точки."""
    n = len(pts)
    if n < 3:
        return
    ctx.move_to(*pts[0])
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) * tension / 3, p1[1] + (p2[1] - p0[1]) * tension / 3)
        c2 = (p2[0] - (p3[0] - p1[0]) * tension / 3, p2[1] - (p3[1] - p1[1]) * tension / 3)
        ctx.curve_to(*c1, *c2, *p2)
    ctx.close_path()


def heart(ctx: cairo.Context, x: float, y: float, s: float) -> None:
    ctx.move_to(x, y + s * 0.35)
    ctx.curve_to(x - s * 1.1, y - s * 0.35, x - s * 0.45, y - s * 1.05, x, y - s * 0.45)
    ctx.curve_to(x + s * 0.45, y - s * 1.05, x + s * 1.1, y - s * 0.35, x, y + s * 0.35)
    ctx.close_path()


def star(ctx: cairo.Context, x: float, y: float, r: float, n: int = 5, inner: float = 0.45,
         rot: float = -math.pi / 2) -> None:
    n = max(2, int(n))
    for i in range(2 * n):
        rr = r if i % 2 == 0 else r * inner
        a = rot + i * math.pi / n
        (ctx.move_to if i == 0 else ctx.line_to)(x + rr * math.cos(a), y + rr * math.sin(a))
    ctx.close_path()


def sparkle(ctx: cairo.Context, x: float, y: float, r: float) -> None:
    """Четырёхлучевая искра (как в аниме)."""
    k = r * 0.12
    ctx.move_to(x, y - r)
    ctx.curve_to(x + k, y - k, x + k, y - k, x + r, y)
    ctx.curve_to(x + k, y + k, x + k, y + k, x, y + r)
    ctx.curve_to(x - k, y + k, x - k, y + k, x - r, y)
    ctx.curve_to(x - k, y - k, x - k, y - k, x, y - r)
    ctx.close_path()


# ---------- заливка с мультяшной обводкой ----------
def fill_ink(ctx: cairo.Context, fill: Any, lw: float, ink: RGB = INK) -> None:
    """Заливка текущего пути (цвет или паттерн) + обводка ink толщиной lw с круглыми стыками."""
    set_source(ctx, fill)
    ctx.fill_preserve()
    set_source(ctx, ink)
    ctx.set_line_width(lw)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


def fill_union(ctx: cairo.Context, path_fn: Callable[[], None], fill: Any, lw: float, ink: RGB = INK) -> None:
    """Контур объединения нескольких фигур (облако, афро, куст, дым, пузырь с хвостиком): сначала толстая
    обводка всех частей, потом заливка всех частей поверх — внутренние швы исчезают."""
    path_fn()
    set_source(ctx, ink)
    ctx.set_line_width(lw * 2)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()
    path_fn()
    ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
    set_source(ctx, fill)
    ctx.fill()


def body_grad(x0: float, y0: float, r: float, base: RGB) -> cairo.RadialGradient:
    """Объём: свет сверху-слева (база +35 % к белому), база посередине, к краю — база ×0.72."""
    g = cairo.RadialGradient(x0 - r * 0.35, y0 - r * 0.45, r * 0.1, x0, y0, r * 1.25)
    g.add_color_stop_rgb(0, *lighten(base, 0.35))
    g.add_color_stop_rgb(0.55, *base)
    g.add_color_stop_rgb(1, *mul(base, 0.72))
    return g


def cel_shadow(ctx: cairo.Context, path_fn: Callable[[], None], base: RGB, dx: float, dy: float,
               k: float = 0.78) -> None:
    """Двухтоновая тень: фигура — клип, её копия, сдвинутая на (dx, dy), вырезается — остаётся тёмный серп
    цвета base×k с прозрачностью 0.55 на стороне, ПРОТИВОПОЛОЖНОЙ сдвигу (при (9, 6) — слева-сверху, как у
    одобренных персонажей прототипа)."""
    ctx.save()
    path_fn()
    ctx.clip()
    x1, y1, x2, y2 = ctx.clip_extents()
    ctx.translate(dx, dy)
    path_fn()
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    pad = abs(dx) + abs(dy) + 10
    ctx.rectangle(x1 - dx - pad, y1 - dy - pad, x2 - x1 + 2 * pad, y2 - y1 + 2 * pad)
    ctx.set_source_rgba(*mul(base, k), 0.55)
    ctx.fill()
    ctx.restore()


def _bez_point(p0, c, p1, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0], u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1])


def hose(ctx: cairo.Context, a: tuple[float, float], b: tuple[float, float], c: tuple[float, float],
         width: float, color: RGB, ink: RGB = INK, ow: float = 4.0, t0: float = 0.0, t1: float = 1.0,
         cap: Any = cairo.LINE_CAP_ROUND) -> None:
    """Конечность «резиновый шланг»: квадратичная кривая a → c через «локоть» b, обводка ow + цвет + блик."""
    # контрольная точка, чтобы кривая прошла через b при t = 0.5
    k = (2 * b[0] - (a[0] + c[0]) / 2, 2 * b[1] - (a[1] + c[1]) / 2)
    steps = 10
    pts = [_bez_point(a, k, c, t0 + (t1 - t0) * i / steps) for i in range(steps + 1)]
    ctx.set_line_cap(cap)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    for w, col in ((width + 2 * ow, ink), (width, color)):
        ctx.move_to(*pts[0])
        for p in pts[1:]:
            ctx.line_to(*p)
        ctx.set_line_width(w)
        set_source(ctx, col)
        ctx.stroke()
    # блик вдоль конечности
    ctx.move_to(*pts[1])
    for p in pts[2:-2]:
        ctx.line_to(p[0] - width * 0.18, p[1] - width * 0.18)
    ctx.set_line_width(width * 0.22)
    ctx.set_source_rgba(1, 1, 1, 0.28)
    ctx.stroke()


def blob_shadow(ctx: cairo.Context, x: float, y: float, rx: float, ry: float, alpha: float = 0.45) -> None:
    """Мягкая тень на земле: эллипс с радиальным градиентом от alpha в центре до нуля на краю."""
    if rx <= 0.5 or ry <= 0.5 or alpha <= 0.0:
        return
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(rx, ry)
    g = cairo.RadialGradient(0, 0, 0, 0, 0, 1)
    g.add_color_stop_rgba(0, *SHADOW_INK, alpha)
    g.add_color_stop_rgba(0.55, *SHADOW_INK, alpha * 0.6)
    g.add_color_stop_rgba(1, *SHADOW_INK, 0)
    ctx.set_source(g)
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.fill()
    ctx.restore()


# ---------- текст ----------
# Эмодзи, которых нет в DejaVu, → похожий символ шрифта; прочие — выкидываются.
_EMOJI_MAP: dict[str, str] = {}
for _chars, _to in (
    ("❤♥❣💖💕💗💓💘💝💞💟🧡💛💚💙💜🖤🤍🤎💌😻", "♥"),
    ("⭐🌟🌠", "★"), ("✨💫", "✦"),
    ("🎵", "♪"), ("🎶🎼", "♫"),
    ("😊🙂😀😃😄😁😆😅😂🤣😉😍🥰😘😗😙😚😋😛😜🤪😝🤗😇🥳😎😺😸", "☺"),
    ("😢😭😞😔🙁😟😕😿🥺😥😓", "☹"),
    ("🌞🌝", "☀"), ("☔🌂", "☂"), ("⛄", "☃"), ("🌸🌼🌺🌷💐🌻", "✿"), ("🍀", "☘"),
    ("✅☑", "✔"), ("❌❎", "✖"), ("👑", "♛"), ("📞📱", "☎"), ("📧📨📩", "✉"),
    ("➡", "→"), ("⬅", "←"), ("⬆", "↑"), ("⬇", "↓"),
):
    for _ch in _chars:
        _EMOJI_MAP[_ch] = _to

# невидимые служебные символы эмодзи и разметки — убираются молча
_SILENT = re.compile("[​-‏⁠-⁤︀-️⃣\U0001f3fb-\U0001f3ff\U000e0000-\U000e007f]")
# если шрифт не нашёлся — что DejaVu Sans точно умеет
_FALLBACK_RANGES = (
    (0x20, 0x7E), (0xA0, 0x24F), (0x370, 0x3FF), (0x400, 0x52F), (0x2010, 0x205E), (0x20A0, 0x20BF),
    (0x2100, 0x214F), (0x2190, 0x21FF), (0x2200, 0x22FF), (0x2500, 0x25FF), (0x2600, 0x26A1), (0x2700, 0x27BF),
)


def font_file(bold: bool = True) -> str | None:
    """Путь к файлу DejaVu Sans (жирный или обычный) или None, если не нашёлся."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in FONT_DIRS:
        for sub in ("", "dejavu"):
            path = os.path.join(d, sub, name)
            if os.path.isfile(path):
                return path
    return None


@functools.lru_cache(maxsize=1)
def _font_charset() -> frozenset[int] | None:
    """Коды символов, которые есть и в обычном, и в жирном DejaVu Sans (по cmap шрифтов)."""
    try:
        from fontTools.ttLib import TTFont

        sets = []
        for bold in (False, True):
            path = font_file(bold)
            if path is None:
                return None
            sets.append(set(TTFont(path, lazy=True).getBestCmap()))
        return frozenset(sets[0] & sets[1])
    except Exception:  # без fontTools или шрифта — запасные диапазоны
        return None


def _has_glyph(code: int) -> bool:
    charset = _font_charset()
    if charset is not None:
        return code in charset
    return any(lo <= code <= hi for lo, hi in _FALLBACK_RANGES)


def clean_text(s: str, limit: int) -> tuple[str, bool]:
    """Текст для кадра: кириллица/латиница/цифры/знаки и символы DejaVu (♥★♪☺…) остаются, частые эмодзи
    заменяются похожими символами (❤→♥ ⭐→★ 🎵→♪ 😊→☺), остальное, чего нет в шрифте, выкидывается.
    Пробелы схлопываются, переводы строк сохраняются (не больше одного подряд). Длиннее limit — обрезка с «…».
    Второе значение — True, если что-то видимое выкинули или обрезали."""
    if not isinstance(s, str):
        s = str(s)
    s = unicodedata.normalize("NFC", _SILENT.sub("", s))
    out: list[str] = []
    dropped = False
    for ch in s:
        if ch in _EMOJI_MAP:
            out.append(_EMOJI_MAP[ch])
        elif ch == "\n":
            out.append("\n")
        elif ch.isspace() or unicodedata.category(ch) == "Cc":
            out.append(" ")
        elif _has_glyph(ord(ch)):
            out.append(ch)
        else:
            dropped = True
    text = re.sub(r"[ \t]+", " ", "".join(out))
    text = re.sub(r" ?\n[ \n]*", "\n", text).strip()
    limit = max(0, int(limit))
    if len(text) > limit:
        dropped = True
        text = (text[: max(0, limit - 1)].rstrip() + "…") if limit > 0 else ""
    return text, dropped


@functools.lru_cache(maxsize=1)
def _font_options() -> cairo.FontOptions:
    # без хинтинга: буквы не «прыгают» по пикселям, когда текст двигается и масштабируется
    return cairo.FontOptions(antialias=cairo.ANTIALIAS_GRAY, hint_style=cairo.HINT_STYLE_NONE,
                             hint_metrics=cairo.HINT_METRICS_OFF)


def _font(ctx: cairo.Context, size: float, bold: bool) -> None:
    ctx.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(max(0.5, size))
    ctx.set_font_options(_font_options())


def text_size(ctx: cairo.Context, text: str, size: float, bold: bool = True) -> tuple[float, float]:
    """(ширина, высота строки) текста в пикселях текущего пространства."""
    _font(ctx, size, bold)
    height = ctx.font_extents()[2]
    return (ctx.text_extents(text)[4] if text else 0.0), height


def text_path(ctx: cairo.Context, text: str, x: float, y: float, size: float, bold: bool = True,
              anchor: str = "center") -> None:
    """Добавить контуры строки в путь. anchor — center | left | right по x; y — середина строки
    (по высоте заглавных букв)."""
    _font(ctx, size, bold)
    if not text:
        return
    w = ctx.text_extents(text)[4]
    x0 = x - w / 2 if anchor == "center" else x - w if anchor == "right" else x
    ctx.move_to(x0, y + size * CAP_MID)
    ctx.text_path(text)


def wrap(ctx: cairo.Context, text: str, size: float, max_w: float, bold: bool = True,
         max_lines: int = 3) -> list[str]:
    """Разбить текст на строки не шире max_w (по словам; слишком длинное слово — по буквам).
    Больше max_lines строк — последняя обрезается с «…». Переводы строк в тексте соблюдаются."""
    _font(ctx, size, bold)
    max_lines = max(1, int(max_lines))

    def adv(s: str) -> float:
        return ctx.text_extents(s)[4]

    lines: list[str] = []
    overflow = False
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            cand = f"{cur} {word}" if cur else word
            if adv(cand) <= max_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
                cur = ""
            while len(word) > 1 and adv(word) > max_w:
                cut = 1
                while cut < len(word) - 1 and adv(word[: cut + 1]) <= max_w:
                    cut += 1
                lines.append(word[:cut])
                word = word[cut:]
            cur = word
            if len(lines) > max_lines:
                break
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            overflow = True
            break
    if len(lines) > max_lines or overflow:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(lines[-1], max_w, adv)
    return lines


def _ellipsize(line: str, max_w: float, adv: Callable[[str], float]) -> str:
    # «…» в конце строки: сначала убираем целые слова с конца, и только одно длинное слово режем по буквам
    def fits(s: str) -> bool:
        return adv(s.rstrip(" ,.;:—-") + "…") <= max_w

    words = line.split(" ")
    while len(words) > 1 and not fits(" ".join(words)):
        words.pop()
    if len(words) > 1 and len(words[-1].strip(" ,.;:—-")) <= 1:  # не оставлять висящее «и…», «в…»
        words.pop()
    last = " ".join(words)
    while len(last) > 1 and not fits(last):
        last = last[:-1]
    return last.rstrip(" ,.;:—-") + "…"


def draw_text(ctx: cairo.Context, text: str, x: float, y: float, size: float, color: Any, bold: bool = True,
              anchor: str = "center", outline: RGB | None = None, outline_w: float = 0.0) -> None:
    """Строка текста цветом color; с outline — сначала обводка (снаружи букв толщиной outline_w), потом заливка."""
    if not text:
        return
    ctx.new_path()
    text_path(ctx, text, x, y, size, bold, anchor)
    if outline is not None and outline_w > 0:
        set_source(ctx, outline)
        ctx.set_line_width(outline_w * 2)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke_preserve()
    set_source(ctx, color)
    ctx.fill()


# ---------- спрайты ----------
def _png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


def _from_pillow(data: bytes, max_side: int) -> cairo.ImageSurface:
    import numpy as np
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        if im.width * im.height > MAX_SPRITE_PIXELS:
            raise AnimError("картинка предмета слишком большая")
        im.draft("RGBA", (max_side, max_side))
        im = im.convert("RGBA")
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        rgba = np.asarray(im, dtype=np.uint16)
    h, w = rgba.shape[:2]
    a = rgba[:, :, 3:4]
    pre = (rgba[:, :, :3] * a + 127) // 255  # cairo хранит цвет, умноженный на альфу
    bgra = np.concatenate([pre[:, :, ::-1], a], axis=2).astype(np.uint8)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    surface.flush()
    stride = surface.get_stride()
    buf = np.frombuffer(surface.get_data(), dtype=np.uint8).reshape(h, stride)
    buf[:, : w * 4] = bgra.reshape(h, w * 4)
    surface.mark_dirty()
    return surface


def sprite_from_png(png: bytes, max_side: int = 512) -> cairo.ImageSurface:
    """PNG (или другая картинка, которую понимает Pillow) → ARGB32-поверхность не больше max_side по большей
    стороне. Испорченные данные — AnimError."""
    max_side = max(1, int(max_side))
    size = _png_size(png)
    if size is not None and size[0] * size[1] > MAX_SPRITE_PIXELS:
        raise AnimError("картинка предмета слишком большая")
    try:
        if size is None:
            raise ValueError("не PNG")
        src = cairo.ImageSurface.create_from_png(io.BytesIO(png))
    except AnimError:
        raise
    except Exception:  # не PNG или необычный PNG — пробуем Pillow
        try:
            return _from_pillow(png, max_side)
        except AnimError:
            raise
        except Exception as e:
            raise AnimError("не удалось прочитать картинку предмета") from e
    w, h = src.get_width(), src.get_height()
    k = min(1.0, max_side / max(w, h, 1))
    if k >= 1.0 and src.get_format() == cairo.FORMAT_ARGB32:
        return src
    nw, nh = max(1, round(w * k)), max(1, round(h * k))
    out, ctx = new_surface(nw, nh)
    ctx.scale(nw / w, nh / h)
    ctx.set_source_surface(src, 0, 0)
    ctx.get_source().set_filter(cairo.FILTER_GOOD)
    ctx.paint()
    out.flush()
    return out


def paint_sprite(ctx: cairo.Context, sprite: cairo.ImageSurface, cx: float, cy: float, w_px: float, h_px: float,
                 rot: float = 0.0, alpha: float = 1.0) -> None:
    """Нарисовать спрайт с центром (cx, cy) размером w_px×h_px, поворотом rot и прозрачностью alpha."""
    sw, sh = sprite.get_width(), sprite.get_height()
    if w_px <= 0 or h_px <= 0 or alpha <= 0 or sw <= 0 or sh <= 0:
        return
    ctx.save()
    ctx.translate(cx, cy)
    if rot:
        ctx.rotate(rot)
    ctx.scale(w_px / sw, h_px / sh)
    ctx.rectangle(-sw / 2, -sh / 2, sw, sh)
    ctx.clip()
    ctx.set_source_surface(sprite, -sw / 2, -sh / 2)
    ctx.get_source().set_filter(cairo.FILTER_BILINEAR)
    ctx.paint_with_alpha(min(1.0, alpha))
    ctx.restore()


def to_png(surface: cairo.ImageSurface) -> bytes:
    """Поверхность → байты PNG (для тестов и отладки)."""
    buf = io.BytesIO()
    surface.write_to_png(buf)
    return buf.getvalue()
