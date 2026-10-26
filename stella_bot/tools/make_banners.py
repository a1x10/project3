"""Generates the section banners in assets/banners.

Usage: python tools/make_banners.py <fonts_dir>

The fonts dir must contain fontsource subsets (Unbounded 800/500 and
Montserrat 500/700, latin + cyrillic), e.g. from
https://cdn.jsdelivr.net/fontsource/fonts/unbounded@latest/cyrillic-800-normal.ttf
"""
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 640
OUT = Path(__file__).resolve().parent.parent / "assets" / "banners"

# key: (title, subtitle, accent_a, accent_b, motif)
SECTIONS = {
    "gate": ("ДОСТУП", "Ключ бета-тестирования", "#7c5cff", "#ff4fd8", "lock"),
    "stella": ("STELLA", "ИИ проекта STELLS", "#8b5cff", "#38e8ff", "orbit"),
    "menu": ("STELLS", "Лаборатория ИИ", "#6d5cff", "#ff5fa2", "orbit"),
    "agents": ("ИИ-АГЕНТЫ", "Создание и общение", "#3d8bff", "#7cf5ff", "neural"),
    "music": ("МУЗЫКА", "Генерация песен", "#ff4f8b", "#ffb84f", "eq"),
    "video": ("ВИДЕО", "Генерация видео", "#ff5f3d", "#ffd23d", "film"),
    "image": ("ИЗОБРАЖЕНИЯ", "Генерация картинок", "#ff4fd8", "#7c5cff", "grid"),
    "tts": ("ОЗВУЧКА", "Текст в речь", "#3dffb0", "#3d8bff", "wave"),
    "dialogue": ("ДИАЛОГИ", "Сцены на несколько голосов", "#ffb84f", "#ff4f8b", "bubbles"),
    "sfx": ("ЗВУКИ", "Звуковые эффекты", "#ffd23d", "#ff5f3d", "burst"),
    "sts": ("СМЕНА ГОЛОСА", "Голос в голос", "#a35cff", "#3dffb0", "wave"),
    "stt": ("РАСШИФРОВКА", "Речь в текст", "#38e8ff", "#3d8bff", "lines"),
    "design": ("ДИЗАЙН ГОЛОСА", "Голос по описанию", "#ff4fd8", "#38e8ff", "orbit"),
    "clone": ("КЛОН ГОЛОСА", "Мгновенное клонирование", "#7cf5ff", "#a35cff", "wave"),
    "isolate": ("ОЧИСТКА", "Удаление шума", "#3dffb0", "#38e8ff", "eq"),
    "dub": ("ДУБЛЯЖ", "Перевод видео и аудио", "#3d8bff", "#ff4fd8", "film"),
    "voices": ("ГОЛОСА", "Библиотека голосов", "#ffb84f", "#a35cff", "bubbles"),
    "settings": ("НАСТРОЙКИ", "Параметры генерации", "#8f9bb3", "#7c5cff", "grid"),
    "profile": ("ПРОФИЛЬ", "Ваш аккаунт STELLS", "#7c5cff", "#38e8ff", "orbit"),
}


class Fonts:
    def __init__(self, root: Path):
        def pair(name, weight, size):
            return (
                ImageFont.truetype(str(root / f"{name}-latin-{weight}.ttf"), size),
                ImageFont.truetype(str(root / f"{name}-cyrillic-{weight}.ttf"), size),
            )

        self.pair = pair


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def pick(fonts, ch):
    return fonts[1] if "Ѐ" <= ch <= "ӿ" else fonts[0]


def text_width(fonts, text, spacing=0):
    return sum(pick(fonts, c).getlength(c) + spacing for c in text) - spacing


def draw_text(draw, xy, text, fonts, fill, spacing=0):
    x, y = xy
    for c in text:
        f = pick(fonts, c)
        draw.text((x, y), c, font=f, fill=fill)
        x += f.getlength(c) + spacing


def glow(size, xy, radius, color, alpha):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = xy
    d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, alpha))
    return layer.filter(ImageFilter.GaussianBlur(radius * 0.55))


def motif(kind, a, b, rnd):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = 960, 320

    def mix(t):
        return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

    if kind == "orbit":
        for i, r in enumerate((90, 150, 215, 280)):
            d.ellipse((cx - r * 1.35, cy - r * 0.55, cx + r * 1.35, cy + r * 0.55), outline=(*mix(i / 3), 150), width=3)
        d.ellipse((cx - 62, cy - 62, cx + 62, cy + 62), fill=(*mix(0.4), 255))
        for i in range(7):
            ang = rnd.random() * math.tau
            r = rnd.choice((150, 215, 280))
            x, y = cx + math.cos(ang) * r * 1.35, cy + math.sin(ang) * r * 0.55
            d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(*mix(rnd.random()), 255))
    elif kind == "eq":
        n = 15
        for i in range(n):
            h = 40 + abs(math.sin(i * 0.7) * 200) + rnd.random() * 60
            x = 720 + i * 34
            d.rounded_rectangle((x, cy - h / 2, x + 20, cy + h / 2), radius=10, fill=(*mix(i / n), 235))
    elif kind == "wave":
        for k in range(3):
            pts = []
            for x in range(660, 1260, 4):
                t = (x - 660) / 600
                env = math.sin(t * math.pi)
                y = cy + math.sin(t * 22 + k * 1.3) * 150 * env * (1 - k * 0.25)
                pts.append((x, y))
            d.line(pts, fill=(*mix(k / 2), 230 - k * 50), width=6 - k)
    elif kind == "film":
        for i in range(3):
            x = 700 + i * 180
            y = cy - 140 + (i % 2) * 40
            d.rounded_rectangle((x, y, x + 160, y + 220), radius=18, outline=(*mix(i / 2), 230), width=5)
            for j in range(5):
                d.rectangle((x + 10, y + 14 + j * 42, x + 22, y + 34 + j * 42), fill=(*mix(i / 2), 180))
                d.rectangle((x + 138, y + 14 + j * 42, x + 150, y + 34 + j * 42), fill=(*mix(i / 2), 180))
            tx, ty = x + 80, y + 110
            d.polygon([(tx - 22, ty - 30), (tx - 22, ty + 30), (tx + 30, ty)], fill=(*mix(i / 2), 255))
    elif kind == "grid":
        for i in range(5):
            for j in range(5):
                if rnd.random() < 0.25:
                    continue
                x, y = 780 + i * 92, 90 + j * 95
                s = 70 + rnd.random() * 14
                d.rounded_rectangle((x, y, x + s, y + s * 0.85), radius=14, fill=(*mix((i + j) / 8), 70 + int(rnd.random() * 160)))
    elif kind == "neural":
        nodes = [(700 + rnd.random() * 540, 70 + rnd.random() * 500) for _ in range(16)]
        for i, p in enumerate(nodes):
            for q in nodes[i + 1 :]:
                if math.dist(p, q) < 200:
                    d.line([p, q], fill=(*mix(0.5), 120), width=2)
        for i, (x, y) in enumerate(nodes):
            r = 8 + rnd.random() * 10
            d.ellipse((x - r, y - r, x + r, y + r), fill=(*mix(i / 16), 255))
    elif kind == "bubbles":
        boxes = [(700, 120, 1060, 230, 0), (860, 270, 1230, 380, 1), (720, 420, 1040, 520, 0)]
        for x1, y1, x2, y2, side in boxes:
            col = (*mix(side), 220)
            d.rounded_rectangle((x1, y1, x2, y2), radius=40, fill=col)
            for k in range(3):
                bx = x1 + 60 + k * 70
                d.rounded_rectangle((bx, (y1 + y2) / 2 - 8, bx + 50, (y1 + y2) / 2 + 8), radius=8, fill=(255, 255, 255, 140))
    elif kind == "burst":
        for i in range(28):
            ang = i / 28 * math.tau
            r1, r2 = 70, 160 + rnd.random() * 130
            d.line(
                [(cx + math.cos(ang) * r1, cy + math.sin(ang) * r1), (cx + math.cos(ang) * r2, cy + math.sin(ang) * r2)],
                fill=(*mix(i / 28), 230),
                width=6,
            )
        d.ellipse((cx - 50, cy - 50, cx + 50, cy + 50), fill=(*mix(0.5), 255))
    elif kind == "lines":
        for i in range(8):
            w = 280 + rnd.random() * 260
            y = 110 + i * 56
            d.rounded_rectangle((700, y, 700 + w, y + 22), radius=11, fill=(*mix(i / 8), 210))
    elif kind == "lock":
        d.rounded_rectangle((850, 280, 1100, 500), radius=36, fill=(*mix(0.2), 235))
        d.arc((890, 140, 1060, 360), start=180, end=360, fill=(*mix(0.8), 255), width=30)
        d.line([(905, 250), (905, 285)], fill=(*mix(0.8), 255), width=30)
        d.line([(1045, 250), (1045, 285)], fill=(*mix(0.8), 255), width=30)
        d.ellipse((955, 355, 995, 395), fill=(10, 8, 20, 255))
        d.rectangle((967, 380, 983, 440), fill=(10, 8, 20, 255))
    return layer


def banner(key, fonts):
    title, subtitle, ca, cb, kind = SECTIONS[key]
    a, b = hex2rgb(ca), hex2rgb(cb)
    rnd = random.Random(key)

    img = Image.new("RGBA", (W, H), (7, 6, 15, 255))
    # vertical gradient base
    base = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        base.line([(0, y), (W, y)], fill=(int(7 + 10 * t), int(6 + 4 * t), int(15 + 22 * t), 255))

    img = Image.alpha_composite(img, glow((W, H), (980, 260), 330, a, 120))
    img = Image.alpha_composite(img, glow((W, H), (1150, 520), 260, b, 100))
    img = Image.alpha_composite(img, glow((W, H), (160, 80), 220, a, 55))

    stars = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stars)
    for _ in range(170):
        x, y = rnd.random() * W, rnd.random() * H
        r = rnd.choice((0.8, 1, 1.3, 1.8, 2.4))
        sd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, int(60 + rnd.random() * 170)))
    for _ in range(5):
        x, y = rnd.random() * W, rnd.random() * H
        sd.line([(x - 12, y), (x + 12, y)], fill=(255, 255, 255, 200), width=2)
        sd.line([(x, y - 12), (x, y + 12)], fill=(255, 255, 255, 200), width=2)
    img = Image.alpha_composite(img, stars)

    m = motif(kind, a, b, rnd)
    img = Image.alpha_composite(img, m.filter(ImageFilter.GaussianBlur(14)))
    img = Image.alpha_composite(img, m)

    # left readability scrim
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdr = ImageDraw.Draw(scrim)
    for x in range(760):
        sdr.line([(x, 0), (x, H)], fill=(7, 6, 15, int(170 * (1 - x / 760) ** 1.4)))
    img = Image.alpha_composite(img, scrim)

    title_fonts = fonts.pair("unbounded", 800, 96)
    while text_width(title_fonts, title, 2) > 620:
        size = title_fonts[0].size - 4
        title_fonts = fonts.pair("unbounded", 800, size)
    label_fonts = fonts.pair("montserrat", 700, 24)
    sub_fonts = fonts.pair("montserrat", 500, 38)

    tlayer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(tlayer)
    ty = 250 - title_fonts[0].size // 2
    draw_text(td, (80, ty), title, title_fonts, (*a, 255), 2)
    img = Image.alpha_composite(img, tlayer.filter(ImageFilter.GaussianBlur(18)))

    d = ImageDraw.Draw(img)
    draw_text(d, (80, 120), "S T E L L S   ·   B E T A   A C C E S S", label_fonts, (255, 255, 255, 170))
    d.rounded_rectangle((80, 168, 160, 174), radius=3, fill=(*a, 255))
    d.rounded_rectangle((168, 168, 200, 174), radius=3, fill=(*b, 255))
    draw_text(d, (80, ty), title, title_fonts, (255, 255, 255, 255), 2)
    draw_text(d, (82, ty + title_fonts[0].size + 34), subtitle, sub_fonts, (225, 225, 245, 230))

    chip_fonts = fonts.pair("montserrat", 700, 22)
    chip = "STELLA AI"
    cw = text_width(chip_fonts, chip, 3)
    d.rounded_rectangle((80, 520, 80 + cw + 70, 570), radius=25, outline=(255, 255, 255, 90), width=2)
    d.ellipse((100, 538, 114, 552), fill=(*b, 255))
    draw_text(d, (128, 531), chip, chip_fonts, (255, 255, 255, 220), 3)

    return img.convert("RGB")


def main():
    fonts = Fonts(Path(sys.argv[1]))
    OUT.mkdir(parents=True, exist_ok=True)
    for key in SECTIONS:
        banner(key, fonts).save(OUT / f"{key}.jpg", quality=90, optimize=True, progressive=True)
        print("ok", key)


if __name__ == "__main__":
    main()
