"""Скриншоты готовой страницы «как на телефоне» — чтобы студия посмотрела на свою работу и доделала её.

Браузер (Playwright + Chromium) запускается отдельным процессом в своей группе: без ключей в окружении,
без сети (только file:/data:/blob:), с лимитом времени. Нет Playwright — шаг просто пропускается.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
from dataclasses import dataclass, field

log = logging.getLogger("stella.shots")

SHOTS_TIMEOUT = 120.0

# Код процесса-фотографа: страница открывается как на телефоне 390×844, снимки — сразу, через несколько секунд,
# после нажатия на главную кнопку и после прокрутки. В stdout — одна строка JSON.
_WORKER = r"""
import asyncio, json, resource, sys
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # лимит памяти браузеру не ставим: он резервирует гигабайты адресов
from playwright.async_api import async_playwright

page_path, out_dir = sys.argv[1], sys.argv[2]
LOCAL = ("file:", "data:", "blob:", "about:")

async def main():
    errors, shots = [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=[
            "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
            "--proxy-server=127.0.0.1:9", "--proxy-bypass-list=<-loopback>", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                        is_mobile=True, has_touch=True, locale="ru-RU")

        async def route(r):
            if r.request.url.startswith(LOCAL):
                await r.continue_()
            else:
                await r.abort()

        await ctx.route("**/*", route)
        page = await ctx.new_page()
        page.on("pageerror", lambda e: errors.append("ошибка JS: " + str(e)[:300]))
        page.on("console", lambda m: errors.append("console." + m.type + ": " + m.text[:300])
                if m.type in ("error", "warning") else None)

        async def shot(name, label):
            path = f"{out_dir}/{name}.jpg"
            await page.screenshot(path=path, type="jpeg", quality=80)
            shots.append([label, path])

        await page.goto("file://" + page_path, wait_until="load", timeout=30000)
        await page.wait_for_timeout(1500)
        await shot("1", "сразу после открытия (1.5 с)")
        await page.wait_for_timeout(2500)
        await shot("2", "через 4 секунды")
        target = None
        for sel in ("button", "[role=button]", "a[href^='#']", ".btn", "[onclick]"):
            for el in await page.query_selector_all(sel):
                if await el.is_visible():
                    target = el
                    break
            if target:
                break
        try:
            if target is not None:
                await target.tap(timeout=3000)
            else:
                await page.touchscreen.tap(195, 560)
            label = "после нажатия на первую кнопку" if target is not None else "после тапа по экрану"
        except Exception:
            await page.touchscreen.tap(195, 560)
            label = "после тапа по экрану"
        await page.wait_for_timeout(2500)
        await shot("3", label)
        await page.mouse.wheel(0, 844)
        await page.wait_for_timeout(1500)
        await shot("4", "после прокрутки вниз на экран")
        info = await page.evaluate("({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight})")
        await browser.close()
    print(json.dumps({"shots": shots, "errors": errors[:30], "scroll_width": info["w"], "height": info["h"]}))

asyncio.run(main())
"""


@dataclass
class Shots:
    images: list[tuple[str, bytes]] = field(default_factory=list)  # (подпись, jpeg)
    errors: list[str] = field(default_factory=list)
    overflow: bool = False  # страница шире экрана телефона

    def page_errors(self) -> int:
        return sum(1 for e in self.errors if e.startswith("ошибка JS"))


def available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def _env(home: str) -> dict[str, str]:
    """Только нужное браузеру — ключей и паролей из .env у него нет."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "LANG": "C.UTF-8"}
    for key in ("PLAYWRIGHT_BROWSERS_PATH", "FONTCONFIG_PATH"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


async def shoot(page: bytes, timeout: float = SHOTS_TIMEOUT) -> Shots:
    """Открыть страницу в браузере и снять 4 кадра. Ошибка браузера -> исключение ShotsError."""
    tmp = tempfile.mkdtemp(prefix="stella-shots-")
    try:
        path = os.path.join(tmp, "page.html")
        with open(path, "wb") as f:
            f.write(page)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", _WORKER, path, tmp, cwd=tmp, env=_env(tmp),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _kill(proc)
            await proc.wait()
            raise ShotsError("браузер не успел") from None
        finally:
            _kill(proc)  # браузер мог остаться после фотографа
        if proc.returncode != 0:
            raise ShotsError(f"браузер упал: {err.decode(errors='replace')[-300:]}")
        data = json.loads(out.decode().strip().splitlines()[-1])
        images = []
        for label, img in data["shots"]:
            with open(img, "rb") as f:
                images.append((label, f.read()))
        return Shots(images, list(data.get("errors") or []), int(data.get("scroll_width") or 0) > 392)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class ShotsError(Exception):
    pass
