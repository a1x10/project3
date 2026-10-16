"""Основа мультиков: сглаживания и детерминизм, палитра и разбор цветов, примитивы и текст cairo, раскладка."""

from __future__ import annotations

import io
import math
import random
import subprocess
import sys
from pathlib import Path

import pytest

from bot.anim import AnimError, catalog, ease, layout, palette

cairo = pytest.importorskip("cairocffi")
draw = pytest.importorskip("bot.anim.draw")

ROOT = Path(__file__).resolve().parents[1]


def _ink_pixels(surface) -> int:
    """Сколько пикселей поверхности непрозрачны (альфа > 0)."""
    surface.flush()
    data = bytes(surface.get_data())
    return sum(1 for i in range(3, len(data), 4) if data[i])


# ======================= ease =======================
@pytest.mark.parametrize("name", ease.EASINGS)
def test_easing_boundaries(name: str) -> None:
    assert ease.ease(name, 0.0) == 0.0
    assert ease.ease(name, 1.0) == 1.0
    assert ease.ease(name, -5.0) == 0.0
    assert ease.ease(name, 7.0) == 1.0
    assert ease.ease(name, float("nan")) == 0.0
    for i in range(1, 50):
        v = ease.ease(name, i / 50)
        assert math.isfinite(v) and -0.5 < v < 1.6


def test_easing_shapes() -> None:
    assert ease.ease("linear", 0.3) == pytest.approx(0.3)
    assert ease.ease("in", 0.5) < 0.5 < ease.ease("out", 0.5)
    assert ease.ease("in_out", 0.5) == pytest.approx(0.5)
    assert max(ease.ease("out_back", i / 100) for i in range(100)) > 1.0  # перелёт
    assert min(ease.ease("in_back", i / 100) for i in range(100)) < 0.0  # замах
    assert max(ease.ease("spring", i / 100) for i in range(100)) > 1.05
    assert ease.ease("unknown-name", 0.25) == pytest.approx(0.25)
    assert ease.ease_out_bounce(1.0) == 1.0 and ease.ease_out_bounce(0.0) == 0.0
    assert ease.ease_out_back(0.0) == pytest.approx(0.0) and ease.ease_out_back(1.0) == 1.0


def test_spring_and_helpers() -> None:
    assert ease.spring(0.0) == 0.0 and ease.spring(-1.0) == 0.0
    assert ease.spring(10.0) == pytest.approx(1.0, abs=1e-3)
    assert max(ease.spring(i / 100) for i in range(200)) > 1.1
    assert ease.spring(5.0, zeta=1.5) == pytest.approx(1.0, abs=1e-3)  # без перелёта
    assert ease.clamp(5) == 1.0 and ease.clamp(-1) == 0.0 and ease.clamp(float("nan")) == 0.0
    assert ease.clamp(5, 0, 10) == 5
    assert ease.lerp(10, 20, 0.25) == 12.5
    assert ease.window(1.5, 1, 2) == 0.5 and ease.window(0, 1, 2) == 0 and ease.window(3, 1, 2) == 1
    assert ease.window(1.0, 1.0, 1.0) == 1.0 and ease.window(0.9, 1.0, 1.0) == 0.0
    assert ease.smoothstep(0) == 0 and ease.smoothstep(1) == 1 and ease.smoothstep(0.5) == 0.5


def test_fade_weight() -> None:
    assert ease.fade_weight(0.5, 1, 3, 0.5) == 0.0
    assert ease.fade_weight(3.5, 1, 3, 0.5) == 0.0
    assert ease.fade_weight(1.0, 1, 3, 0.5) == 0.0
    assert ease.fade_weight(2.0, 1, 3, 0.5) == 1.0
    assert 0 < ease.fade_weight(1.25, 1, 3, 0.5) < 1
    assert 0 < ease.fade_weight(2.8, 1, 3, 0.5) < 1
    assert ease.fade_weight(2.0, 1, 3, 0.0) == 1.0
    assert ease.fade_weight(1.5, 1, 2, 5.0) == 1.0  # fade длиннее половины отрезка — пик ровно в середине


def test_hash_rng_noise_deterministic() -> None:
    assert ease.hash01(7, "a", 1) == ease.hash01(7, "a", 1)
    assert ease.hash01(7, "a", 1) != ease.hash01(7, "a", 2)
    assert ease.hash01(7, "a") != ease.hash01(8, "a")
    vals = [ease.hash01(3, i) for i in range(500)]
    assert all(0.0 <= v < 1.0 for v in vals)
    assert 0.4 < sum(vals) / len(vals) < 0.6
    a = ease.rng(5, "conf", 2)
    b = ease.rng(5, "conf", 2)
    assert isinstance(a, random.Random)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]
    assert ease.rng(5, "conf", 2).random() != ease.rng(5, "conf", 3).random()
    xs = [i * 0.05 for i in range(400)]
    n1 = [ease.noise1(x, 11) for x in xs]
    assert n1 == [ease.noise1(x, 11) for x in xs]
    assert n1 != [ease.noise1(x, 12) for x in xs]
    assert all(-1.0 <= v <= 1.0 for v in n1)
    assert max(n1) - min(n1) > 0.8  # не константа
    assert max(abs(n1[i + 1] - n1[i]) for i in range(len(n1) - 1)) < 0.2  # гладкий
    assert ease.noise1(float("nan")) == 0.0 and ease.noise1(float("inf")) == 0.0


def test_hash_same_in_other_process() -> None:
    """Детерминизм между процессами (PYTHONHASHSEED не влияет): кадры рисуются в разных воркерах."""
    code = ("from bot.anim import ease; print(repr(ease.hash01(42, 'x', 1.5)), ease.rng(1, 'k').random(), "
            "repr(ease.noise1(3.7, 9)))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONHASHSEED": "123", "PATH": ""}, cwd=ROOT).stdout.split()
    assert out == [repr(ease.hash01(42, "x", 1.5)), str(ease.rng(1, "k").random()), repr(ease.noise1(3.7, 9))]


# ======================= palette =======================
def test_parse_color_hex() -> None:
    assert palette.parse_color("#ff0000") == (1.0, 0.0, 0.0)
    assert palette.parse_color("#F00") == (1.0, 0.0, 0.0)
    assert palette.parse_color("00ff00") == (0.0, 1.0, 0.0)
    assert palette.parse_color("  #0000ffcc ") == (0.0, 0.0, 1.0)
    assert palette.parse_color("rgb(255, 128, 0)") == pytest.approx((1.0, 128 / 255, 0.0))
    assert palette.parse_color([1, 0.5, 0]) == (1.0, 0.5, 0.0)
    assert palette.parse_color((255, 0, 0)) == (1.0, 0.0, 0.0)
    assert palette.hx("#ffffff") == (1.0, 1.0, 1.0)
    with pytest.raises(ValueError):
        palette.hx("#12")


@pytest.mark.parametrize("name, ref", [
    ("красный", "red"), ("Красная", "red"), ("red", "red"), ("RED", "red"),
    ("синий", "blue"), ("синее", "blue"), ("blue", "blue"),
    ("зелёный", "green"), ("зеленая", "green"), ("green", "green"),
    ("розовый", "pink"), ("pink", "pink"), ("фиолетовая", "purple"), ("purple", "purple"),
    ("рыжий", "ginger"), ("золотой", "gold"), ("gold", "gold"), ("жёлтый", "yellow"), ("желтая", "yellow"),
    ("оранжевый", "orange"), ("голубой", "light blue"), ("белая", "white"), ("чёрный", "black"),
    ("черное", "black"), ("серый", "grey"), ("gray", "grey"), ("коричневый", "brown"), ("бирюзовый", "teal"),
    ("сиреневый", "lilac"), ("серебряный", "silver"), ("Hot Pink", "hot pink"), ("тёмно-синий", "navy"),
    ("крассный", "red"),
])
def test_parse_color_names(name: str, ref: str) -> None:
    assert palette.parse_color(name) == palette.COLOR_NAMES[ref]


def test_parse_color_modifiers_and_garbage() -> None:
    green = palette.COLOR_NAMES["green"]
    light = palette.parse_color("светло-зелёный")
    dark = palette.parse_color("dark red")
    assert light is not None and palette.luminance(light) > palette.luminance(green)
    assert dark is not None and palette.luminance(dark) < palette.luminance(palette.COLOR_NAMES["red"])
    default = (0.1, 0.2, 0.3)
    for junk in ("", "   ", "абракадабра", "#zzzzzz", "#12345", "qwerty", None, 42, True, {}, [], [1, "x", 2],
                 [float("nan"), 0, 0], "x" * 500, "rgb(a,b,c)", "__import__('os')"):
        assert palette.parse_color(junk, default) == default, junk
    assert palette.parse_color("абракадабра") is None


def test_palette_tables() -> None:
    assert len(palette.COLOR_NAMES) >= 40
    assert set(palette.SKIN_TONES) == set(catalog.SKINS)
    assert len(palette.TOY_COLORS) == 24 and len(set(palette.TOY_COLORS)) == 24
    for c in (*palette.COLOR_NAMES.values(), *palette.SKIN_TONES.values(), *palette.TOY_COLORS, palette.INK):
        assert len(c) == 3 and all(0.0 <= v <= 1.0 for v in c)
    assert palette.contrast(palette.INK, palette.hx("#1F1729")) < 1.01
    # кожа светлеет → темнеет по порядку
    lum = [palette.luminance(palette.SKIN_TONES[k]) for k in catalog.SKINS]
    assert lum == sorted(lum, reverse=True)


def test_color_ops() -> None:
    c = (0.5, 0.4, 0.2)
    assert palette.mul(c, 2) == (1.0, 0.8, 0.4)
    assert palette.mix((0, 0, 0), (1, 1, 1), 0.25) == (0.25, 0.25, 0.25)
    assert palette.lighten((0, 0, 0), 0.5) == (0.5, 0.5, 0.5)
    assert palette.darken((1, 1, 1), 0.5) == (0.5, 0.5, 0.5)
    assert palette.luminance((1, 1, 1)) == pytest.approx(1.0)
    assert palette.luminance((0, 0, 0)) == 0.0
    assert palette.contrast((0, 0, 0), (1, 1, 1)) == pytest.approx(21.0)
    assert palette.contrast(c, c) == 1.0


@pytest.mark.parametrize("c, bg", [
    ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0)),
    ((0.95, 0.95, 0.9), (1.0, 1.0, 1.0)),
    ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    ((0.1, 0.1, 0.3), (0.05, 0.05, 0.2)),
    ((0.4, 0.75, 0.4), (0.45, 0.8, 0.45)),
    ((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
])
def test_ensure_contrast(c, bg) -> None:
    out = palette.ensure_contrast(c, bg)
    assert palette.contrast(out, bg) >= 1.6
    assert all(0.0 <= v <= 1.0 for v in out)


def test_ensure_contrast_keeps_good_colors() -> None:
    red, sky = palette.COLOR_NAMES["red"], (0.75, 0.88, 1.0)
    assert palette.ensure_contrast(red, sky) == red
    assert palette.ensure_contrast(palette.INK, (1, 1, 1)) == palette.INK


def test_pick() -> None:
    assert palette.pick(3, 0) == palette.pick(3, 0)
    first = [palette.pick(9, i) for i in range(24)]
    assert len(set(first)) == 24 and all(c in palette.TOY_COLORS for c in first)
    assert palette.pick(9, 24) == palette.pick(9, 0)


# ======================= draw: текст =======================
def test_clean_text_mapping() -> None:
    assert draw.clean_text("Люблю ❤️ тебя", 50) == ("Люблю ♥ тебя", False)
    assert draw.clean_text("⭐🎵😊❤", 50) == ("★♪☺♥", False)
    assert draw.clean_text("♥★♪☺ ok", 50) == ("♥★♪☺ ok", False)
    text, dropped = draw.clean_text("Привет 🦄🎬 мир 中文!", 50)
    assert text == "Привет мир !" and dropped
    assert draw.clean_text("👍🏽", 10) == ("", True)
    assert draw.clean_text("Hello, Мир! 123 «ёжик» — №5, €10, 50%?", 100) == (
        "Hello, Мир! 123 «ёжик» — №5, €10, 50%?", False)
    assert draw.clean_text("  много   пробелов \t\n\n\n вторая  ", 100) == ("много пробелов\nвторая", False)
    assert draw.clean_text("ab\x00c\x07", 10) == ("ab c", False)


def test_clean_text_limit() -> None:
    text, dropped = draw.clean_text("а" * 120, 100)
    assert len(text) == 100 and text.endswith("…") and dropped
    assert draw.clean_text("коротко", 7) == ("коротко", False)
    assert draw.clean_text("коротко", 0) == ("", True)
    assert draw.clean_text("и\u0306", 5) == ("\u0439", False)  # и + кратка → «й» (NFC)


def test_font_covers_cyrillic() -> None:
    for ch in "АБВЁЖЩЪЫЬЭЮЯабвёжщъыьэюяҚҒӘ♥★♪☺":
        assert draw._has_glyph(ord(ch)), ch
    assert not draw._has_glyph(ord("中"))


def test_text_draws_pixels() -> None:
    surface, ctx = draw.new_surface(160, 60)
    draw.draw_text(ctx, "Привет!", 80, 30, 24, (0.2, 0.1, 0.4))
    n = _ink_pixels(surface)
    assert n > 150
    surface2, ctx2 = draw.new_surface(160, 60)
    draw.draw_text(ctx2, "Привет!", 80, 30, 24, (1, 1, 1), outline=palette.INK, outline_w=3)
    assert _ink_pixels(surface2) > n  # обводка добавляет пиксели
    surface3, ctx3 = draw.new_surface(40, 40)
    draw.draw_text(ctx3, "", 20, 20, 24, (0, 0, 0))
    assert _ink_pixels(surface3) == 0


def test_text_anchor_and_size() -> None:
    surface, ctx = draw.new_surface(200, 80)
    w, h = draw.text_size(ctx, "Ёжик", 30)
    assert 40 < w < 120 and 30 <= h <= 40
    w_reg, _ = draw.text_size(ctx, "Ёжик", 30, bold=False)
    assert w_reg < w
    assert draw.text_size(ctx, "", 30)[0] == 0.0
    for anchor, expect in (("left", (100, 100 + w)), ("right", (100 - w, 100)), ("center", (100 - w / 2, 100 + w / 2))):
        ctx.new_path()
        draw.text_path(ctx, "Ёжик", 100, 40, 30, anchor=anchor)
        x1, y1, x2, y2 = ctx.path_extents()
        assert expect[0] - 3 <= x1 and x2 <= expect[1] + 3, anchor
        assert abs((y1 + y2) / 2 - 40) < 6  # y — середина строки


@pytest.mark.parametrize("max_w, max_lines", [(60, 3), (120, 2), (200, 3), (400, 1), (90, 5)])
def test_wrap_limits(max_w: float, max_lines: int) -> None:
    _, ctx = draw.new_surface(10, 10)
    text = "Сегодня у Стеллы день рождения, и все друзья пришли поздравить её с праздником!"
    lines = draw.wrap(ctx, text, 20, max_w, max_lines=max_lines)
    assert 1 <= len(lines) <= max_lines
    for ln in lines:
        assert draw.text_size(ctx, ln, 20)[0] <= max_w + 0.01, ln
    if len(lines) == max_lines and max_w < 400:
        assert lines[-1].endswith("…")


def test_wrap_short_and_long_words() -> None:
    _, ctx = draw.new_surface(10, 10)
    assert draw.wrap(ctx, "Привет", 20, 300) == ["Привет"]
    assert draw.wrap(ctx, "раз\nдва", 20, 300) == ["раз", "два"]
    assert draw.wrap(ctx, "", 20, 300) == []
    lines = draw.wrap(ctx, "Суперкалифраджилистикэкспиалидоциус", 20, 80, max_lines=10)
    assert len(lines) > 1 and "".join(lines) == "Суперкалифраджилистикэкспиалидоциус"
    assert all(draw.text_size(ctx, ln, 20)[0] <= 80 for ln in lines)


# ======================= draw: фигуры и спрайты =======================
def test_primitives_draw() -> None:
    surface, ctx = draw.new_surface(160, 160)
    base = palette.COLOR_NAMES["pink"]

    def path() -> None:
        draw.ellipse(ctx, 80, 80, 40, 50, 0.3)

    path()
    draw.fill_ink(ctx, draw.body_grad(80, 80, 50, base), 4)
    draw.cel_shadow(ctx, path, base, 9, 6)
    draw.rrect(ctx, 5, 5, 40, 30, 50)
    draw.fill_ink(ctx, (0.2, 0.6, 1.0, 0.8), 3)
    draw.smooth_closed(ctx, [(120, 10), (150, 20), (140, 50), (110, 40)])
    draw.fill_ink(ctx, base, 2)
    draw.smooth_closed(ctx, [(0, 0), (1, 1)])  # слишком мало точек — без ошибки
    draw.fill_union(ctx, lambda: (draw.heart(ctx, 30, 130, 20), draw.star(ctx, 60, 130, 20)), (1, 1, 1), 2)
    draw.sparkle(ctx, 130, 130, 18)
    draw.fill_ink(ctx, (1, 1, 0.6), 2)
    draw.hose(ctx, (100, 100), (120, 120), (110, 150), 10, (0.3, 0.5, 1.0))
    draw.blob_shadow(ctx, 80, 150, 40, 8)
    draw.blob_shadow(ctx, 80, 150, 0, 0)  # нулевой размер — без ошибки
    draw.ellipse(ctx, 10, 10, 0, 0)
    ctx.new_path()
    draw.set_source(ctx, (1, 0, 0), 0.5)
    draw.set_source(ctx, cairo.SolidPattern(0, 0, 0))
    assert _ink_pixels(surface) > 6000


def test_cel_shadow_darkens_inside_only() -> None:
    surface, ctx = draw.new_surface(100, 100)
    base = (0.4, 0.8, 1.0)

    def path() -> None:
        draw.ellipse(ctx, 50, 50, 30, 30)

    path()
    draw.set_source(ctx, base)
    ctx.fill()
    before = bytes(surface.get_data())
    draw.cel_shadow(ctx, path, base, 9, 6)
    surface.flush()
    after = bytes(surface.get_data())
    assert before != after
    stride = surface.get_stride()
    corner = 2 * stride + 2 * 4
    assert after[corner:corner + 4] == before[corner:corner + 4] == b"\x00\x00\x00\x00"  # снаружи не рисует


def test_sprite_round_trip() -> None:
    src, ctx = draw.new_surface(64, 48)
    ctx.set_source_rgba(1, 0, 0, 1)
    ctx.rectangle(0, 0, 32, 48)
    ctx.fill()
    ctx.set_source_rgba(0, 0, 1, 0.5)
    ctx.rectangle(32, 0, 32, 48)
    ctx.fill()
    png = draw.to_png(src)
    assert png.startswith(b"\x89PNG")
    sprite = draw.sprite_from_png(png)
    assert (sprite.get_width(), sprite.get_height()) == (64, 48)
    assert sprite.get_format() == cairo.FORMAT_ARGB32
    assert draw.to_png(sprite) == png
    small = draw.sprite_from_png(png, max_side=32)
    assert (small.get_width(), small.get_height()) == (32, 24)
    # нарисовать спрайт: слева красный, справа полупрозрачный синий
    dst, dctx = draw.new_surface(100, 100)
    draw.paint_sprite(dctx, sprite, 50, 50, 80, 60)
    draw.paint_sprite(dctx, sprite, 50, 50, 0, 60)  # нулевой размер — пропуск
    dst.flush()
    data, stride = bytes(dst.get_data()), dst.get_stride()
    b, g, r, a = data[50 * stride + 25 * 4: 50 * stride + 25 * 4 + 4]
    assert r > 240 and a > 240 and b < 10
    b, g, r, a = data[50 * stride + 75 * 4: 50 * stride + 75 * 4 + 4]
    assert b > 100 and 100 < a < 160 and r < 10
    assert data[5 * stride + 5 * 4 + 3] == 0  # вне спрайта прозрачно


def test_sprite_from_other_formats_and_garbage() -> None:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (300, 150), (0, 255, 0)).save(buf, "JPEG")
    sprite = draw.sprite_from_png(buf.getvalue(), max_side=100)
    assert (sprite.get_width(), sprite.get_height()) == (100, 50)
    with pytest.raises(AnimError):
        draw.sprite_from_png(b"not an image at all")
    huge = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (50000).to_bytes(4, "big") * 2 + b"\x08\x06\x00\x00\x00"
    with pytest.raises(AnimError):
        draw.sprite_from_png(huge)


def test_no_heavy_imports_in_package() -> None:
    code = "import sys, bot.anim; print('cairocffi' in sys.modules, 'numpy' in sys.modules, bot.anim.AnimError)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=ROOT).stdout
    assert out.startswith("False False")


# ======================= layout =======================
@pytest.mark.parametrize("fmt", list(catalog.FORMATS))
@pytest.mark.parametrize("lane", catalog.LANES)
def test_layout_heights(fmt: str, lane: str) -> None:
    w, h = catalog.FORMATS[fmt]
    gy = layout.ground_y(h, lane)
    assert gy == pytest.approx(layout.GROUND[lane] * h)
    hgt = layout.char_height(fmt, h, lane)
    assert 0.25 * h < hgt < gy  # герой крупный, но голова в кадре
    assert hgt == pytest.approx(layout.MAIN_HEIGHT[fmt] * h * layout.LANE_SCALE[lane])
    assert layout.char_height(fmt, h, lane, 1.4) > hgt > layout.char_height(fmt, h, lane, 0.6)
    assert gy - layout.char_height(fmt, h, lane, 1.4) >= layout.HEAD_ROOM * h - 1e-6
    assert layout.char_height(fmt, h, lane, float("nan")) == pytest.approx(hgt)


def test_layout_lanes_order() -> None:
    assert layout.GROUND["back"] < layout.GROUND["mid"] < layout.GROUND["front"]
    for fmt in catalog.FORMATS:
        hs = [layout.char_height(fmt, 720, lane) for lane in catalog.LANES]
        assert hs == sorted(hs)
    assert layout.ground_y(720, "nonsense") == layout.ground_y(720, "mid")
    assert layout.char_height("nonsense", 720, "mid") == layout.char_height("square", 720, "mid")


@pytest.mark.parametrize("fmt", list(catalog.FORMATS))
def test_spread_x(fmt: str) -> None:
    lo, hi = {"square": (0.2, 0.8), "wide": (0.15, 0.85), "tall": (0.25, 0.75)}[fmt]
    assert layout.spread_x(0, fmt) == []
    assert layout.spread_x(1, fmt) == [0.5]
    for n in range(2, catalog.MAX_CAST + 1):
        xs = layout.spread_x(n, fmt)
        assert len(xs) == n and xs == sorted(xs)
        assert lo - 1e-9 <= xs[0] and xs[-1] <= hi + 1e-9
        assert xs[0] + xs[-1] == pytest.approx(1.0)
        gaps = [b - a for a, b in zip(xs[:-1], xs[1:], strict=True)]
        assert max(gaps) - min(gaps) < 1e-5  # равномерно
    assert layout.spread_x(catalog.MAX_ON_SCREEN, fmt)[-1] - layout.spread_x(catalog.MAX_ON_SCREEN, fmt)[0] > 0.4


@pytest.mark.parametrize("fmt", list(catalog.FORMATS))
def test_title_zone(fmt: str) -> None:
    zones = {p: layout.title_zone(fmt, p) for p in catalog.TITLE_POSITIONS}
    for y0, y1 in zones.values():
        assert layout.SAFE - 1e-9 <= y0 < y1 <= 1 - layout.SAFE + 1e-9
        assert y1 - y0 >= 0.1
    assert zones["top"][1] <= zones["center"][0] and zones["center"][1] <= zones["bottom"][0]
    assert layout.title_zone(fmt, "???") == zones["top"]
    # заголовок сверху не залезает на голову главного героя
    w, h = catalog.FORMATS[fmt]
    head_top = (layout.ground_y(h, "mid") - layout.char_height(fmt, h, "mid")) / h
    assert zones["top"][1] <= head_top + 0.02


def test_fmt_of_and_offscreen() -> None:
    for fmt, (w, h) in catalog.FORMATS.items():
        assert layout.fmt_of(w, h) == fmt
    assert layout.OFFSCREEN_L < 0 < 1 < layout.OFFSCREEN_R
