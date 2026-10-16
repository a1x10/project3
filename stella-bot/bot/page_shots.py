"""Снимки готовой страницы «как на телефоне» и слайдов презентации — чтобы студия посмотрела на свою работу
и доделала её (а презентация из снимков слайдов и собирается).

Браузер (Playwright + Chromium) запускается отдельным процессом в своей группе: без ключей в окружении,
без сети (только file:/data:/blob:), с лимитом времени. Нет Playwright — страницы обходятся без доводки.
"""

from __future__ import annotations

import asyncio
import io
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
MAX_SLIDES = 25
DECK_PREVIEW = (1280, 720)  # столько видит модель при доводке слайдов — меньше токенов, детали различимы

# Общее начало процессов-фотографов: браузер без сети (прокси в никуда + только локальные адреса).
_BOOT = r"""
import asyncio, json, resource, sys
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # лимит памяти браузеру не ставим: он резервирует гигабайты адресов
from playwright.async_api import async_playwright

LOCAL = ("file:", "data:", "blob:", "about:")
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
        "--proxy-server=127.0.0.1:9", "--proxy-bypass-list=<-loopback>", "--disable-dev-shm-usage"]


async def open_page(p, errors, **ctx_args):
    browser = await p.chromium.launch(args=ARGS)
    ctx = await browser.new_context(locale="ru-RU", **ctx_args)

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
    return browser, page
"""

# Страница как на телефоне 390×844: сразу, через несколько секунд, после нажатия на главную кнопку и после
# прокрутки. В stdout — одна строка JSON.
_WORKER = _BOOT + r"""
page_path, out_dir = sys.argv[1], sys.argv[2]


async def main():
    errors, shots = [], []
    async with async_playwright() as p:
        browser, page = await open_page(p, errors, viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                        is_mobile=True, has_touch=True)

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
        for sel in ("[data-primary]", "button", "[role=button]", "a[href^='#']", ".btn", "[onclick]"):
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
        await page.keyboard.press("Escape")  # открылось окно — закрыть, чтобы увидеть прокрутку страницы
        await page.mouse.wheel(0, 844)
        await page.wait_for_timeout(1500)
        await shot("4", "после прокрутки вниз на экран")
        info = await page.evaluate("({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight})")
        await browser.close()
    print(json.dumps({"shots": shots, "errors": errors[:30], "scroll_width": info["w"], "height": info["h"]}))

asyncio.run(main())
"""

# Презентация: окно 1920×1080, каждый <section class="slide"> снимается отдельно (JPEG), заметки выступающего
# (<aside class="notes">) забираются текстом, проверяются вылезающий за край, мелкий и слишком длинный текст.
_DECK_WORKER = _BOOT + r"""
page_path, out_dir, max_slides = sys.argv[1], sys.argv[2], int(sys.argv[3])
FIX = (".slide{width:1920px!important;height:1080px!important;overflow:hidden!important;margin:0!important;"
       "box-sizing:border-box!important;flex:none!important}"
       "html,body{margin:0!important;padding:0!important}.slide .notes{display:none!important}")
CHECK = r'''(slide) => {
  const box = slide.getBoundingClientRect(), out = new Set();
  let small = 0, outside = 0, words = 0;
  const walker = document.createTreeWalker(slide, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode, el = node.parentElement, text = node.textContent.trim();
    if (!text || !el || el.closest('.notes')) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || +st.opacity === 0) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const r = range.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    words += text.split(/\s+/).length;
    if (parseFloat(st.fontSize) < 20) small++;
    if (r.left < box.left - 2 || r.right > box.right + 2 || r.top < box.top - 2 || r.bottom > box.bottom + 2) {
      outside++;
      out.add(text.slice(0, 40));
    }
  }
  const notes = slide.querySelector('.notes');
  return {notes: notes ? notes.textContent.trim() : '', small, outside, words, out: [...out].slice(0, 3)};
}'''


async def main():
    errors, slides, problems = [], [], []
    async with async_playwright() as p:
        browser, page = await open_page(p, errors, viewport={"width": 1920, "height": 1080}, device_scale_factor=1,
                                        reduced_motion="reduce")
        await page.goto("file://" + page_path, wait_until="load", timeout=30000)
        await page.add_style_tag(content=FIX)
        await page.evaluate("document.fonts.ready.then(() => true)")
        await page.wait_for_timeout(1500)
        found = await page.query_selector_all(".slide")
        if len(found) > max_slides:
            problems.append(f"слайдов {len(found)} — в презентацию попадут первые {max_slides}")
        for i, el in enumerate(found[:max_slides], 1):
            await el.scroll_into_view_if_needed()
            await page.wait_for_timeout(200)
            path = f"{out_dir}/{i}.jpg"
            await el.screenshot(path=path, type="jpeg", quality=92)
            info = await el.evaluate(CHECK)
            if info["outside"]:
                problems.append(f"слайд {i}: текст вылезает за край или обрезан ({'; '.join(info['out'])})")
            if info["small"]:
                problems.append(f"слайд {i}: мелкий текст (меньше 20 px) — {info['small']} шт.")
            if info["words"] > 70:
                problems.append(f"слайд {i}: много текста ({info['words']} слов)")
            slides.append([path, info["notes"][:3000]])
        await browser.close()
    print(json.dumps({"slides": slides, "errors": errors[:30], "problems": problems[:40]}))

asyncio.run(main())
"""


@dataclass
class Shots:
    images: list[tuple[str, bytes]] = field(default_factory=list)  # (подпись, jpeg)
    errors: list[str] = field(default_factory=list)
    overflow: bool = False  # страница шире экрана телефона
    problems: list[str] = field(default_factory=list)

    def page_errors(self) -> int:
        return sum(1 for e in self.errors if e.startswith("ошибка JS"))


@dataclass
class Slide:
    jpeg: bytes  # 1920×1080
    notes: str = ""


@dataclass
class DeckShots:
    slides: list[Slide] = field(default_factory=list)
    images: list[tuple[str, bytes]] = field(default_factory=list)  # уменьшенные — для модели
    errors: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def page_errors(self) -> int:
        return sum(1 for e in self.errors if e.startswith("ошибка JS"))


class ShotsError(Exception):
    pass


def _browsers_root() -> str:
    return os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.expanduser("~/.cache/ms-playwright")


def available() -> bool:
    """Есть Playwright и скачанный им Chromium."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    try:
        return any(name.startswith("chromium") for name in os.listdir(_browsers_root()))
    except OSError:
        return False


def _env(home: str) -> dict[str, str]:
    """Только нужное браузеру — ключей и паролей из .env у него нет. HOME у фотографа свой (временный), поэтому
    папку с браузерами передаём явно — ту же, где её нашёл available()."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "LANG": "C.UTF-8",
           "PLAYWRIGHT_BROWSERS_PATH": _browsers_root()}
    if os.environ.get("FONTCONFIG_PATH"):
        env["FONTCONFIG_PATH"] = os.environ["FONTCONFIG_PATH"]
    return env


def _write(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def _run_worker(code: str, page: bytes, args: list[str], timeout: float) -> tuple[dict, str]:
    """Запустить процесс-фотограф над страницей; вернуть его JSON и папку со снимками (её удаляет вызывающий)."""
    tmp = tempfile.mkdtemp(prefix="stella-shots-")
    try:
        path = os.path.join(tmp, "page.html")
        await asyncio.to_thread(_write, path, page)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", code, path, tmp, *args, cwd=tmp, env=_env(tmp),
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
        try:
            return json.loads(out.decode().strip().splitlines()[-1]), tmp
        except (ValueError, IndexError) as exc:
            raise ShotsError("браузер ничего не вернул") from exc
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


async def shoot(page: bytes, timeout: float = SHOTS_TIMEOUT) -> Shots:
    """Открыть страницу в браузере как на телефоне и снять 4 кадра. Ошибка браузера -> ShotsError."""
    data, tmp = await _run_worker(_WORKER, page, [], timeout)
    try:
        images = [(label, await asyncio.to_thread(_read, img)) for label, img in data["shots"]]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return Shots(images, list(data.get("errors") or []), int(data.get("scroll_width") or 0) > 392)


async def shoot_deck(page: bytes, timeout: float = SHOTS_TIMEOUT * 2) -> DeckShots:
    """Снять каждый слайд презентации 1920×1080 + заметки выступающего + найденные проблемы."""
    data, tmp = await _run_worker(_DECK_WORKER, page, [str(MAX_SLIDES)], timeout)
    try:
        slides = [Slide(await asyncio.to_thread(_read, img), notes) for img, notes in data["slides"]]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    previews = await asyncio.to_thread(lambda: [(f"слайд {i}", _preview(s.jpeg)) for i, s in enumerate(slides, 1)])
    problems = list(data.get("problems") or [])
    if not slides:
        problems.insert(0, 'не найдено ни одного <section class="slide">')
    return DeckShots(slides, previews, list(data.get("errors") or []), problems)


def _preview(jpeg: bytes) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    img.thumbnail(DECK_PREVIEW, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()
