"""Готовит картинки для презентации: рамки устройств со скриншотами, коробку без фона, иконки и фоны.

Запуск: python presentation/assets.py
Нужны: pillow, numpy, playwright (Chromium). Скриншоты берутся из SHOTS (снимки нового дизайна сайта).
"""
import asyncio
import base64
import io
import os
import pathlib

import numpy as np
from PIL import Image
from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "assets"
SHOTS = pathlib.Path(os.getenv("STELLA_SHOTS", "/tmp/claude-0/ui"))


def data_url(img: Image.Image, fmt="PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, fmt)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


def cut_background(src: pathlib.Path, dst: pathlib.Path, bg=(248, 248, 248)):
    """Убирает ровный светлый фон рендера и восстанавливает цвет краев, чтобы не было светлой каймы на черном."""
    a = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
    bgv = np.array(bg, np.float32)
    diff = np.abs(a - bgv).max(axis=2)
    alpha = np.clip(diff / 40.0, 0, 1)
    safe = np.maximum(alpha, 1e-3)[..., None]
    rgb = np.clip((a - (1 - alpha[..., None]) * bgv) / safe, 0, 255)
    out = np.dstack([rgb, alpha * 255]).astype(np.uint8)
    img = Image.fromarray(out, "RGBA")
    img.crop(img.getbbox()).save(dst)


ICONS = {
    # белые линейные иконки 24×24
    "tower_off": '<path d="M12 9v12M8 21h8M9.2 6.2a4 4 0 0 1 5.6 0M6.4 3.4a8 8 0 0 1 11.2 0"/><path d="M3 3l18 18" stroke="#FF453A"/>',
    "pin_question": '<path d="M12 21s-7-6-7-11.5a7 7 0 0 1 14 0C19 15 12 21 12 21z"/><path d="M10 8.2a2 2 0 1 1 2.8 1.8c-.6.3-.8.7-.8 1.3"/><circle cx="12" cy="13.4" r=".5" fill="#fff"/>',
    "queue": '<path d="M4 6h10M4 12h16M4 18h7"/><circle cx="19" cy="6" r="1.6" fill="#FF453A" stroke="none"/>',
    "phone": '<rect x="6.5" y="2.5" width="11" height="19" rx="2.4"/><path d="M10.5 18.5h3"/>',
    "router": '<rect x="3" y="12.5" width="18" height="7.5" rx="2"/><circle cx="17" cy="16.2" r="1.2" fill="#FF453A" stroke="none"/><path d="M7 16.2h4M8.6 8.6a4.8 4.8 0 0 1 6.8 0M6.2 6.1a8.2 8.2 0 0 1 11.6 0"/>',
    "ai_chat": '<path d="M4 5h16a1.5 1.5 0 0 1 1.5 1.5v8.5A1.5 1.5 0 0 1 20 16.5h-9.5L6 20v-3.5H4A1.5 1.5 0 0 1 2.5 15V6.5A1.5 1.5 0 0 1 4 5z"/><circle cx="8" cy="10.8" r="1.2"/><circle cx="12" cy="8.6" r="1.2"/><circle cx="16" cy="11.6" r="1.2"/><path d="M9.1 10.2l1.8-1M13.1 9.3l1.8 1.6"/>',
    "rescuer": '<path d="M4.5 15.5a7.5 7.5 0 0 1 15 0"/><path d="M3 15.5h18v2.2H3zM12 8V5.5M9.5 8.6l-1-2M14.5 8.6l1-2"/>',
    "cloud": '<path d="M7 18.5h10.5a4 4 0 0 0 .6-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 18.5z"/>',
    "chip": '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/><rect x="9.5" y="9.5" width="5" height="5" rx=".8"/><path d="M9 3v3.5M12 3v3.5M15 3v3.5M9 17.5V21M12 17.5V21M15 17.5V21M3 9h3.5M3 12h3.5M3 15h3.5M17.5 9H21M17.5 12H21M17.5 15H21"/>',
    "rules": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2.8h6V4"/><circle cx="9" cy="10" r="1" fill="#FF453A" stroke="none"/><circle cx="9" cy="13.5" r="1" fill="#FF9F0A" stroke="none"/><circle cx="9" cy="17" r="1" fill="#30D158" stroke="none"/><path d="M12 10h4M12 13.5h4M12 17h4"/>',
    "shield": '<path d="M12 2.8l7.5 3v5.4c0 4.8-3.2 8.6-7.5 10-4.3-1.4-7.5-5.2-7.5-10V5.8z"/><path d="M8.6 12.2l2.4 2.4 4.6-4.8"/>',
    "bolt": '<path d="M13.5 2.5 5 13.5h6l-1.5 8 8.5-11h-6z"/>',
    "check_list": '<path d="M4 6.5l1.6 1.6L8.5 5M4 12.5l1.6 1.6 2.9-3.1M4 18.5l1.6 1.6 2.9-3.1M11.5 6.8H20M11.5 12.8H20M11.5 18.8H20"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2.5"/><path d="M8.5 10.5V7.8a3.5 3.5 0 0 1 7 0v2.7"/>',
    "wifi": '<path d="M2.5 8.8a13.5 13.5 0 0 1 19 0M5.6 12.1a9 9 0 0 1 12.8 0M8.7 15.3a4.6 4.6 0 0 1 6.6 0"/><circle cx="12" cy="18.6" r="1.1" fill="#fff"/>',
    "mesh": '<circle cx="5" cy="7" r="2"/><circle cx="19" cy="7" r="2"/><circle cx="12" cy="18" r="2"/><path d="M7 7h10M6 8.8l4.8 7.6M18 8.8l-4.8 7.6"/>',
    "battery_sun": '<rect x="3" y="9" width="12" height="9" rx="1.8"/><path d="M15 12v3M6 13.5h5"/><circle cx="18.5" cy="5.5" r="2"/><path d="M18.5 1.8v.8M22.2 5.5h-.8M21 3l-.6.6M16 3l.6.6"/>',
    "map": '<path d="M3 6.5l6-2.5 6 2.5 6-2.5v13.5l-6 2.5-6-2.5-6 2.5z"/><path d="M9 4v13.5M15 6.5V20"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/>',
    "people": '<circle cx="9" cy="8" r="3"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><circle cx="17" cy="9" r="2.4"/><path d="M15.8 14a4.6 4.6 0 0 1 5.2 5"/>',
    "first_aid": '<rect x="3" y="6.5" width="18" height="13" rx="2.5"/><path d="M9 6.5V4.5h6v2M12 10v6M9 13h6"/>',
    "question": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .8-1 1.6"/><circle cx="12" cy="16.6" r=".6" fill="#fff"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.4 2"/>',
    "ban": '<circle cx="12" cy="12" r="9"/><path d="M5.8 5.8l12.4 12.4"/>',
}

GLOWS = {
    # фон 16:9: черный и мягкое цветное свечение (без логотипов)
    "bg_red": "radial-gradient(60% 70% at 78% 95%, rgba(255,69,58,.42), transparent 70%), radial-gradient(45% 55% at 95% 60%, rgba(255,159,10,.20), transparent 70%)",
    "bg_red_center": "radial-gradient(48% 60% at 50% 62%, rgba(255,69,58,.30), transparent 72%)",
    "bg_blue": "radial-gradient(55% 70% at 80% 50%, rgba(10,132,255,.30), transparent 72%), radial-gradient(40% 50% at 10% 100%, rgba(94,92,230,.18), transparent 70%)",
    "bg_green": "radial-gradient(55% 70% at 85% 45%, rgba(48,209,88,.20), transparent 70%), radial-gradient(40% 50% at 0% 0%, rgba(10,132,255,.12), transparent 70%)",
    "bg_violet": "radial-gradient(55% 65% at 20% 50%, rgba(191,90,242,.26), transparent 72%), radial-gradient(45% 55% at 95% 90%, rgba(255,69,58,.18), transparent 70%)",
    "bg_dim": "radial-gradient(70% 60% at 50% 0%, rgba(255,255,255,.07), transparent 70%)",
}

PHONE = """<div style="width:430px;height:900px;border-radius:70px;padding:13px;background:linear-gradient(145deg,#4a4a4f,#1b1b1e 30%,#2d2d31 70%,#55555a);
box-shadow:inset 0 0 0 2px rgba(255,255,255,.12),0 0 0 1px #000">
<div style="position:relative;width:100%;height:100%;border-radius:58px;overflow:hidden;background:#000">
<img src="{src}" style="width:100%;height:100%;object-fit:cover;object-position:top">
<div style="position:absolute;top:12px;left:50%;transform:translateX(-50%);width:118px;height:34px;border-radius:20px;background:#000"></div>
</div></div>"""

WINDOW = """<div style="width:1600px;border-radius:22px;overflow:hidden;background:#1c1c1e;box-shadow:inset 0 0 0 1px rgba(255,255,255,.14)">
<div style="height:46px;display:flex;align-items:center;gap:10px;padding:0 20px;background:#2a2a2d;border-bottom:1px solid rgba(255,255,255,.08)">
<i style="width:14px;height:14px;border-radius:50%;background:#ff5f57"></i><i style="width:14px;height:14px;border-radius:50%;background:#febc2e"></i><i style="width:14px;height:14px;border-radius:50%;background:#28c840"></i>
<span style="flex:1;text-align:center;margin-right:66px;font:600 17px Arial;color:#9a9aa0">10.42.0.1/rescuer</span></div>
<img src="{src}" style="display:block;width:100%"></div>"""


async def shoot(page, html, path, w, h, transparent=True):
    await page.set_viewport_size({"width": w, "height": h})
    await page.set_content(f'<html><body style="margin:0;background:transparent">{html}</body></html>')
    await page.wait_for_timeout(150)
    el = await page.query_selector("body > *")
    await el.screenshot(path=str(path), omit_background=transparent)


async def main():
    OUT.mkdir(exist_ok=True)
    cut_background(ROOT / "case/img/all.png", OUT / "box.png")
    cut_background(ROOT / "case/img/exploded.png", OUT / "box_exploded.png")

    chat = Image.open(SHOTS / "c4_chat_dark.png").convert("RGB")
    home = Image.open(SHOTS / "c2_home_dark.png").convert("RGB")
    grid = Image.open(SHOTS / "r5_grid.png").convert("RGB").crop((0, 0, 2880, 1880)).resize((1600, 1044), Image.LANCZOS)
    det = Image.open(SHOTS / "r6_detail.png").convert("RGB").crop((200, 1030, 2620, 2570)).resize((1600, 1018), Image.LANCZOS)

    async with async_playwright() as p:
        br = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await br.new_page(device_scale_factor=2)
        await shoot(page, PHONE.format(src=data_url(chat.resize((780, 1688), Image.LANCZOS))), OUT / "phone_chat.png", 500, 960)
        await shoot(page, PHONE.format(src=data_url(home.resize((780, 1688), Image.LANCZOS))), OUT / "phone_home.png", 500, 960)
        page1 = await br.new_page(device_scale_factor=1)
        await shoot(page1, WINDOW.format(src=data_url(grid, "JPEG")), OUT / "win_console.png", 1640, 1140)
        await shoot(page1, WINDOW.format(src=data_url(det, "JPEG")), OUT / "win_dossier.png", 1640, 1120)
        for name, body in ICONS.items():
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="256" height="256" fill="none" '
                   f'stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
            await shoot(page1, svg, OUT / f"i_{name}.png", 256, 256)
        for name, grad in GLOWS.items():
            await shoot(page1, f'<div style="width:1920px;height:1080px;background:{grad},#000"></div>', OUT / f"{name}.png", 1920, 1080, False)
        await br.close()
    for f in OUT.glob("bg_*.png"):  # фоны в JPEG: меньше весит презентация
        Image.open(f).convert("RGB").save(f.with_suffix(".jpg"), quality=92)
        f.unlink()
    print("готово:", len(list(OUT.iterdir())), "файлов")


if __name__ == "__main__":
    asyncio.run(main())
