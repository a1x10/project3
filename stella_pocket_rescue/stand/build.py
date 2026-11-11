"""Собирает стенд для конкурса «Зерде»: три PDF для типографии и превью.

Запуск: python stand/build.py
Нужны: qrcode, playwright (браузер Chromium), pillow, pypdf, pdftoppm (poppler-utils).
"""
import asyncio
import os
import pathlib
import subprocess

import qrcode
import qrcode.image.svg
from PIL import Image
from playwright.async_api import async_playwright
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
BLEED = 3  # мм вылета с каждой стороны

# панель: (имя файла, ширина и высота в мм без вылетов)
PANELS = {
    "left": ("stand_left_300x800.pdf", 300, 800),
    "center": ("stand_center_600x800.pdf", 600, 800),
    "right": ("stand_right_300x800.pdf", 300, 800),
}

QR = {
    "qr_wifi.svg": "WIFI:T:nopass;S:SOS-STELLA-RESCUE;;",
    "qr_verify.svg": "http://10.42.0.1/verify",
}


def make_qr():
    for name, data in QR.items():
        q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
        q.add_data(data)
        q.make(fit=True)
        q.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(HERE / "img" / name)


async def render():
    chromium = os.getenv("CHROMIUM", "/opt/pw-browsers/chromium")
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chromium if os.path.exists(chromium) else None)
        page = await browser.new_page()
        for panel, (name, w, h) in PANELS.items():
            await page.goto((HERE / "stand.html").as_uri() + "?panel=" + panel)
            await page.evaluate("document.fonts.ready.then(() => true)")
            # текст не должен вылезать за панель: лист обрезает лишнее молча
            over = await page.evaluate(
                "(() => { const b = document.querySelector('#%s .body');"
                " return b.scrollHeight - b.clientHeight; })()" % panel)
            if over > 1:
                print(f"ВНИМАНИЕ: {panel} не помещается на {over * 25.4 / 96:.0f} мм")
            todo = await page.locator(f"#{panel} [data-todo]").count()
            if todo:
                print(f"заглушек на панели {panel}: {todo}")
            await page.pdf(
                path=str(OUT / name),
                width=f"{w + 2 * BLEED}mm",
                height=f"{h + 2 * BLEED}mm",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        await browser.close()


def mm(v):
    return v * 72 / 25.4


def set_boxes():
    """Chromium округляет размер страницы, поэтому задаем его точно и размечаем обрез для типографии."""
    for name, w, h in PANELS.values():
        path = OUT / name
        reader = PdfReader(path)
        writer = PdfWriter()
        page = reader.pages[0]
        top = float(page.mediabox.top)
        full = RectangleObject([0, top - mm(h + 2 * BLEED), mm(w + 2 * BLEED), top])
        page.mediabox = full
        page.cropbox = full
        page.bleedbox = full
        page.trimbox = RectangleObject([mm(BLEED), top - mm(h + BLEED), mm(w + BLEED), top - mm(BLEED)])
        writer.add_page(page)
        with open(path, "wb") as f:
            writer.write(f)


def preview(dpi=60):
    """Склеивает три панели без вылетов в одну картинку, как стенд стоит на столе."""
    cut = round(BLEED / 25.4 * dpi)
    parts = []
    for panel, (name, _, _) in PANELS.items():
        stem = OUT / f"_{panel}"
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-singlefile", str(OUT / name), str(stem)], check=True)
        im = Image.open(f"{stem}.png")
        parts.append(im.crop((cut, cut, im.width - cut, im.height - cut)))
        os.remove(f"{stem}.png")
    gap, pad = 6, 30
    w = sum(p.width for p in parts) + gap * (len(parts) - 1) + 2 * pad
    h = max(p.height for p in parts) + 2 * pad
    sheet = Image.new("RGB", (w, h), (205, 210, 216))
    x = pad
    for part in parts:
        sheet.paste(part, (x, pad))
        x += part.width + gap
    sheet.save(OUT / "stand_preview.png")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    make_qr()
    asyncio.run(render())
    set_boxes()
    preview()
    print("готово:", ", ".join(sorted(f.name for f in OUT.iterdir())))
