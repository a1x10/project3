"""Собирает стенд из картинки, сгенерированной ChatGPT: три PDF для типографии и превью.

Картинка (stand/ai/source.*) рисует весь стенд в разложенном виде, 3:2. Скрипт увеличивает ее в 4 раза
нейросетью Real-ESRGAN, режет на три панели, ставит настоящие QR-коды в пустые квадраты и добавляет
вылеты 3 мм.

Запуск: python stand/build_ai.py [путь_к_картинке]
Нужны: torch, spandrel, pillow, numpy, qrcode, img2pdf, pypdf; веса RealESRGAN_x4plus.pth
(скачиваются сами в ~/.cache/stella).
"""
import pathlib
import sys
import urllib.request

import img2pdf
import numpy as np
import qrcode
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

HERE = pathlib.Path(__file__).resolve().parent
AI = HERE / "ai"
OUT = HERE / "out_ai"
BLEED = 3  # мм
SCALE = 4
WEIGHTS_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
WEIGHTS = pathlib.Path.home() / ".cache" / "stella" / "RealESRGAN_x4plus.pth"

# Разметка исходника в долях ширины и высоты (картинка ChatGPT 3:2, проверено на 1280×853).
# Режем чуть внутри темных промежутков у линий сгиба, чтобы панели вышли почти точно 1:2:1.
CUT_LEFT, CUT_RIGHT = 316 / 1280, 968 / 1280
# центры пустых квадратов «Попробуйте сами» и сторона белой подложки под QR
QR_BOXES = [
    ((1062.5 / 1280, 719.5 / 853), "WIFI:T:nopass;S:SOS-STELLA-RESCUE;;"),
    ((1199.0 / 1280, 719.5 / 853), "http://10.42.0.1/verify"),
]
QR_SIDE = 96 / 1280

# панель: (имя файла, ширина и высота в мм без вылетов)
PANELS = {
    "left": ("stand_left_300x800.pdf", 300, 800),
    "center": ("stand_center_600x800.pdf", 600, 800),
    "right": ("stand_right_300x800.pdf", 300, 800),
}


def upscale(src: pathlib.Path) -> Image.Image:
    cache = AI / f"{src.stem}_x{SCALE}.png"
    if cache.exists() and cache.stat().st_mtime > src.stat().st_mtime:
        return Image.open(cache).convert("RGB")
    import torch
    from spandrel import ModelLoader

    if not WEIGHTS.exists():
        WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(WEIGHTS_URL, WEIGHTS)
    model = ModelLoader().load_from_file(str(WEIGHTS))
    model.eval()
    a = np.asarray(Image.open(src).convert("RGB")).astype(np.float32) / 255.0
    h, w, _ = a.shape
    out = np.zeros((h * SCALE, w * SCALE, 3), np.float32)
    tile, pad = 256, 16
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            y0, x0, y1, x1 = max(0, y - pad), max(0, x - pad), min(h, y + tile + pad), min(w, x + tile + pad)
            t = torch.from_numpy(a[y0:y1, x0:x1].transpose(2, 0, 1)).unsqueeze(0)
            with torch.no_grad():
                r = model(t)[0].clamp(0, 1).numpy().transpose(1, 2, 0)
            th, tw = min(tile, h - y) * SCALE, min(tile, w - x) * SCALE
            ty, tx = (y - y0) * SCALE, (x - x0) * SCALE
            out[y * SCALE:y * SCALE + th, x * SCALE:x * SCALE + tw] = r[ty:ty + th, tx:tx + tw]
    img = Image.fromarray((out * 255 + 0.5).astype(np.uint8))
    img.save(cache)
    return img


def qr_tile(data: str, side: int) -> Image.Image:
    """QR на белой скругленной подложке: на темном фоне телефоны читают только так."""
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    q.add_data(data)
    q.make(fit=True)
    n = q.modules_count
    box = max(1, int(side * 0.8) // n)
    code = q.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
    code = code.resize((n * box, n * box), Image.NEAREST)
    card = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle([0, 0, side - 1, side - 1], radius=side // 12, fill=(255, 255, 255, 255))
    off = (side - code.width) // 2
    card.paste(code, (off, off))
    return card


def with_bleed(img: Image.Image, px: int) -> Image.Image:
    a = np.asarray(img)
    return Image.fromarray(np.pad(a, ((px, px), (px, px), (0, 0)), mode="reflect"))


def mm(v):
    return v * 72 / 25.4


def save_pdf(img: Image.Image, path: pathlib.Path, w_mm: float, h_mm: float):
    jpg = path.with_suffix(".jpg")
    img.save(jpg, quality=95, subsampling=0, dpi=(img.width / ((w_mm + 2 * BLEED) / 25.4),) * 2)
    layout = img2pdf.get_layout_fun((mm(w_mm + 2 * BLEED), mm(h_mm + 2 * BLEED)), fit=img2pdf.FitMode.exact)
    path.write_bytes(img2pdf.convert(str(jpg), layout_fun=layout))
    jpg.unlink()
    reader, writer = PdfReader(path), PdfWriter()
    page = reader.pages[0]
    page.trimbox = RectangleObject([mm(BLEED), mm(BLEED), mm(w_mm + BLEED), mm(h_mm + BLEED)])
    page.bleedbox = page.mediabox
    writer.add_page(page)
    with open(path, "wb") as f:
        writer.write(f)


def main():
    src = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else next(AI.glob("source.*"))
    OUT.mkdir(exist_ok=True)
    big = upscale(src)
    W, H = big.size
    c1, c2 = round(W * CUT_LEFT), round(W * CUT_RIGHT)
    parts = {"left": (0, c1), "center": (c1, c2), "right": (c2, W)}
    dpi = H / (800 / 25.4)
    bleed_px = round(BLEED / 25.4 * dpi)
    previews = []
    for name, (x0, x1) in parts.items():
        fname, w_mm, h_mm = PANELS[name]
        target_w = round(H * w_mm / h_mm)
        sx = target_w / (x1 - x0)
        panel = big.crop((x0, 0, x1, H)).resize((target_w, H), Image.LANCZOS)
        if name == "right":
            side = round(QR_SIDE * W)
            for (fx, fy), data in QR_BOXES:
                cx, cy = (fx * W - x0) * sx, fy * H
                tile = qr_tile(data, side)
                panel.paste(tile, (round(cx - side / 2), round(cy - side / 2)), tile)
        print(f"{name}: {x1 - x0} -> {target_w} px (масштаб по ширине {sx:.3f}), {dpi:.0f} dpi")
        save_pdf(with_bleed(panel, bleed_px), OUT / fname, w_mm, h_mm)
        previews.append(panel)
    gap, pad = 12, 40
    k = 0.25
    small = [p.resize((round(p.width * k), round(p.height * k)), Image.LANCZOS) for p in previews]
    sheet = Image.new("RGB", (sum(p.width for p in small) + gap * 2 + pad * 2, small[0].height + pad * 2), (205, 210, 216))
    x = pad
    for p in small:
        sheet.paste(p, (x, pad))
        x += p.width + gap
    sheet.save(OUT / "stand_preview.png")
    print("готово:", ", ".join(sorted(f.name for f in OUT.iterdir())))


if __name__ == "__main__":
    main()
