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
DECK_PREVIEW = (1600, 900)  # столько видит модель при доводке слайдов: касания и обрезки ещё различимы

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

# Страница как на телефоне 390×844: сразу, через несколько секунд, после нажатия на главную кнопку, после
# прокрутки (у игры в один экран — пауза и финал) и на маленьком телефоне 360×640. В stdout — одна строка JSON.
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
            label = "через 2.5 с после нажатия на главную кнопку" if target is not None else "через 2.5 с после тапа"
        except Exception:
            await page.touchscreen.tap(195, 560)
            label = "через 2.5 с после тапа по экрану"
        await page.wait_for_timeout(2500)
        await shot("3", label)
        info = await page.evaluate("({w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight})")
        await page.keyboard.press("Escape")  # открылось окно — закрыть, чтобы увидеть прокрутку страницы
        await page.mouse.wheel(0, 844)
        await page.wait_for_timeout(1500)
        if await page.evaluate("window.scrollY") > 0:
            await shot("4", "после прокрутки вниз на экран")
        else:  # приложение в один экран (игра): вместо повтора — пауза и финал, если страница их даёт
            pause = await page.query_selector("[data-pause]")
            if pause is not None and await pause.is_visible():
                try:
                    await pause.tap(timeout=2000)
                    await page.wait_for_timeout(800)
                    await shot("4", "пауза (нажата кнопка data-pause)")
                    await pause.tap(timeout=2000)
                except Exception:
                    pass
            if await page.evaluate("typeof window.__studioEnd === 'function'"):
                try:
                    await page.evaluate("window.__studioEnd()")
                    await page.wait_for_timeout(1200)
                    await shot("5", "экран финала (window.__studioEnd)")
                except Exception:
                    pass
        await page.set_viewport_size({"width": 360, "height": 640})
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(800)
        await shot("6", "маленький телефон 360×640, то же состояние, верх страницы")
        await browser.close()
    print(json.dumps({"shots": shots, "errors": errors[:30], "scroll_width": info["w"], "height": info["h"]}))

asyncio.run(main())
"""

# Презентация: окно 1920×1080. Перед съёмкой — русская типографика (неразрывные пробелы перед тире, после
# коротких предлогов, между числом и словом), затем каждый <section class="slide"> снимается отдельно (JPEG),
# заметки выступающего (<aside class="notes">) забираются текстом, геометрия проверяется: текст за краем слайда
# или обрезан блоком, текст на тексте, текст под рисунком, линия под текстом, мелкий текст, много слов.
# JS и CSS приходят файлом (argv[4]) — без строк внутри строк.
_DECK_WORKER = _BOOT + r"""
page_path, out_dir, max_slides, assets = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
A = json.load(open(assets, encoding="utf-8"))


def say(i, info):
    out = []
    def snip(items):
        return "; ".join("«" + s + "»" for s in items[:3])
    if info["outside"]:
        out.append(f"слайд {i}: текст вылезает за край слайда ({snip(info['outside'])})")
    if info["clipped"]:
        out.append(f"слайд {i}: текст обрезан рамкой карточки или блока ({snip(info['clipped'])})")
    if info["overlaps"]:
        out.append(f"слайд {i}: текст наезжает на другой текст ({snip(info['overlaps'])})")
    if info["covered"]:
        out.append(f"слайд {i}: текст перекрыт рисунком или декором ({snip(info['covered'])})")
    if info["lines"]:
        out.append(f"слайд {i}: линия или кольцо проходит под текстом ({snip(info['lines'])})")
    if info["small"]:
        out.append(f"слайд {i}: мелкий текст (меньше 20 px) — {info['small']} шт.")
    if info["words"] > 50:
        out.append(f"слайд {i}: {info['words']} слов содержания при норме ≤ 40 — вычеркни второстепенное "
                   "(подробности — в заметки), кегль не уменьшай")
    if info["svg_words"] > 30:
        out.append(f"слайд {i}: много подписей на схеме ({info['svg_words']} слов)")
    geometry = sum(len(info[k]) for k in ("outside", "clipped", "overlaps", "covered"))
    return out, geometry


async def main():
    errors, slides, problems, geometry = [], [], [], 0
    async with async_playwright() as p:
        browser, page = await open_page(p, errors, viewport={"width": 1920, "height": 1080}, device_scale_factor=1,
                                        reduced_motion="reduce")
        await page.goto("file://" + page_path, wait_until="load", timeout=30000)
        await page.add_style_tag(content=A["fix_css"])
        await page.evaluate(A["typo_js"])
        await page.evaluate("document.fonts.ready.then(() => true)")
        await page.wait_for_timeout(1500)
        found = await page.query_selector_all(".slide")
        if len(found) > max_slides:
            problems.append(f"слайдов {len(found)} — в презентацию попадут первые {max_slides}")
        for i, el in enumerate(found[:max_slides], 1):
            await el.scroll_into_view_if_needed()
            await page.evaluate(A["settle_js"])  # два кадра отрисовки: без случайных недорисованных полос
            await page.wait_for_timeout(300)
            path = f"{out_dir}/{i}.jpg"
            await el.screenshot(path=path, type="jpeg", quality=92, animations="disabled")
            info = await el.evaluate(A["check_js"])
            said, geo = say(i, info)
            problems += said
            geometry += geo
            slides.append([path, info["notes"][:3000]])
        await browser.close()
    print(json.dumps({"slides": slides, "errors": errors[:30], "problems": problems[:60], "geometry": geometry}))

asyncio.run(main())
"""

# Что подменяется на время съёмки слайдов: размер слайда, заметки скрыты, переносы заголовков ровные.
DECK_FIX_CSS = (
    ".slide{width:1920px!important;height:1080px!important;overflow:hidden!important;margin:0!important;"
    "box-sizing:border-box!important;flex:none!important}"
    "html,body{margin:0!important;padding:0!important}.slide .notes{display:none!important}"
    ".slide h1,.slide h2,.slide h3{text-wrap:balance}.slide p,.slide li,.slide figcaption{text-wrap:pretty}")

# Русская типографика в тексте слайдов (до съёмки — PowerPoint и PDF собираются из снимков).
DECK_TYPO_JS = r"""() => {
  const NB = ' ';
  const SHORT = /(^|[\s («„"])(в|к|с|у|о|а|и|я|на|не|по|за|до|из|от|об|во|со|но|ко|для|при|без|над|под|про|и|или)\s+(?=\S)/gi;
  const fix = (t) => {
    t = t.replace(/\s+([—–])/g, NB + '$1');
    for (let k = 0; k < 2; k++) t = t.replace(SHORT, (m, a, w) => a + w + NB);
    t = t.replace(/\s+(же|ли|бы)(?=[\s.,!?…»]|$)/g, NB + '$1');
    t = t.replace(/(\d)[  ](?=\d{3}(?!\d))/g, '$1 ');
    t = t.replace(/(\d)\s+(?=[^\s\d])/g, '$1' + NB);
    return t;
  };
  for (const slide of document.querySelectorAll('.slide')) {
    const walker = document.createTreeWalker(slide, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const el = node.parentElement;
      if (!el || el.closest('script,style,.notes')) continue;
      const before = node.textContent, after = fix(before);
      if (after !== before) node.textContent = after;
    }
  }
  return true;
}"""

DECK_SETTLE_JS = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))"

# Проверка одного слайда: что видно глазом, но не видно по коду.
DECK_CHECK_JS = r"""(slide) => {
  const box = slide.getBoundingClientRect();
  const area = box.width * box.height;
  const CHROME = '.notes,[data-chrome],footer,.foot,.footer,.kicker,[aria-hidden="true"]';
  const GEOM = new Set(['line', 'path', 'polyline', 'polygon', 'circle', 'ellipse', 'rect']);
  const res = {notes: '', small: 0, words: 0, svg_words: 0, outside: [], clipped: [], overlaps: [], covered: [], lines: []};
  const notes = slide.querySelector('.notes');
  res.notes = notes ? notes.textContent.trim() : '';
  const items = [];
  const walker = document.createTreeWalker(slide, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode, el = node.parentElement, text = node.textContent.replace(/\s+/g, ' ').trim();
    if (!text || !el || el.closest('.notes,script,style')) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || +st.opacity < 0.2) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const rects = [...range.getClientRects()].filter(r => r.width > 1 && r.height > 1);
    if (!rects.length) continue;
    const chrome = !!el.closest(CHROME);
    const words = (text.match(/[\p{L}\p{N}]+/gu) || []).length;
    const inSvg = !!el.closest('svg');
    if (!chrome) {
      if (inSvg) res.svg_words += words; else res.words += words;
      if (parseFloat(st.fontSize) < 20) res.small++;
    }
    items.push({el, text: text.slice(0, 40), rects, shown: []});
  }
  const add = (list, s) => { if (list.length < 5 && !list.includes(s)) list.push(s); };
  const PAINT = new Set(['IMG', 'CANVAS', 'VIDEO', 'image', 'text', 'use', ...GEOM]);
  const paints = (e) => {  // рисует ли элемент сам (а не пустая обёртка или корневой <svg>)
    if (PAINT.has(e.tagName)) return true;
    const es = getComputedStyle(e);
    const bg = es.backgroundColor.match(/[\d.]+/g);
    return (bg && (bg.length < 4 || +bg[3] > 0.05)) || es.backgroundImage !== 'none' ||
      (parseFloat(es.borderTopWidth) > 0 && es.borderTopStyle !== 'none');
  };
  const related = (a, b) => a === b || a.contains(b) || b.contains(a);
  const outOf = (r, b) => r.left < b.left - 2 || r.right > b.right + 2 || r.top < b.top - 2 || r.bottom > b.bottom + 2;
  for (const it of items) {
    for (const r of it.rects) {
      if (outOf(r, box)) { add(res.outside, it.text); continue; }
      let clipped = false;
      for (let p = it.el; p && p !== slide; p = p.parentElement) {  // обрезать может и сам блок с текстом
        const ps = getComputedStyle(p);
        if (/(hidden|clip)/.test(ps.overflowX + ps.overflowY) && p.namespaceURI === 'http://www.w3.org/1999/xhtml') {
          if (outOf(r, p.getBoundingClientRect())) clipped = true;
          break;
        }
      }
      if (clipped) add(res.clipped, it.text); else it.shown.push(r);  // дальше проверяем только видимые строки
    }
  }
  for (let a = 0; a < items.length; a++) {
    for (let b = a + 1; b < items.length; b++) {
      if (related(items[a].el, items[b].el)) continue;
      let hit = false;
      for (const r1 of items[a].shown) {
        for (const r2 of items[b].shown) {
          const w = Math.min(r1.right, r2.right) - Math.max(r1.left, r2.left) - 4;
          const h = Math.min(r1.bottom, r2.bottom) - Math.max(r1.top, r2.top) - 4;
          if (w > 0 && h > 0) { hit = true; break; }
        }
        if (hit) break;
      }
      if (hit) add(res.overlaps, items[a].text + '» и «' + items[b].text);
    }
  }
  const style = document.createElement('style');
  style.textContent = '.slide *{pointer-events:auto!important}';
  document.head.appendChild(style);
  for (const it of items) {
    let covered = false, under = false;
    for (const r of it.shown) {
      for (const [x, y] of [0.2, 0.5, 0.8].flatMap(fx => [0.3, 0.5, 0.7].map(fy =>
          [r.left + r.width * fx, r.top + r.height * fy]))) {
        const stack = document.elementsFromPoint(x, y);
        const own = stack.findIndex(e => e === it.el || it.el.contains(e));
        if (own < 0) continue;
        for (const e of stack.slice(0, own)) {
          if (related(e, it.el) || !slide.contains(e)) continue;
          const er = e.getBoundingClientRect();
          if (er.width * er.height > area * 0.8 || !paints(e)) continue;
          const es = getComputedStyle(e);
          if (+es.opacity < 0.35 || es.visibility === 'hidden') continue;
          covered = true;
        }
        for (const e of stack.slice(own + 1)) {
          if (!GEOM.has(e.tagName) || related(e, it.el)) continue;
          const es = getComputedStyle(e);
          if (es.stroke === 'none' || +es.strokeOpacity < 0.25 || parseFloat(es.strokeWidth) < 1) continue;
          const filled = e.tagName !== 'line' && es.fill !== 'none' && !/rgba\(.*,\s*0\)$/.test(es.fill) &&
            +es.fillOpacity > 0.1;
          if (filled) continue;  // залитая фигура под текстом — это фон, а не линия
          under = true;
        }
      }
    }
    if (covered) add(res.covered, it.text);
    if (under) add(res.lines, it.text);
  }
  style.remove();
  return res;
}"""


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
    geometry: int = 0  # сколько найдено текста за краем, обрезанного, наложенного или перекрытого

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


async def _run_worker(code: str, page: bytes, args: list[str], timeout: float,
                      extra: tuple[str, str] | None = None) -> tuple[dict, str]:
    """Запустить процесс-фотограф над страницей; вернуть его JSON и папку со снимками (её удаляет вызывающий).
    extra — (имя, текст) файла рядом со страницей; его путь уходит последним аргументом."""
    tmp = tempfile.mkdtemp(prefix="stella-shots-")
    try:
        path = os.path.join(tmp, "page.html")
        await asyncio.to_thread(_write, path, page)
        if extra is not None:
            extra_path = os.path.join(tmp, extra[0])
            await asyncio.to_thread(_write, extra_path, extra[1].encode("utf-8"))
            args = [*args, extra_path]
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
    """Открыть страницу в браузере как на телефоне и снять 4–6 кадров. Ошибка браузера -> ShotsError."""
    data, tmp = await _run_worker(_WORKER, page, [], timeout)
    try:
        images = [(label, await asyncio.to_thread(_read, img)) for label, img in data["shots"]]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return Shots(images, list(data.get("errors") or []), int(data.get("scroll_width") or 0) > 392)


async def shoot_deck(page: bytes, timeout: float = SHOTS_TIMEOUT * 2) -> DeckShots:
    """Снять каждый слайд презентации 1920×1080 + заметки выступающего + найденные проблемы."""
    assets = json.dumps({"fix_css": DECK_FIX_CSS, "typo_js": DECK_TYPO_JS, "settle_js": DECK_SETTLE_JS,
                         "check_js": DECK_CHECK_JS}, ensure_ascii=False)
    data, tmp = await _run_worker(_DECK_WORKER, page, [str(MAX_SLIDES)], timeout, extra=("assets.json", assets))
    try:
        slides = [Slide(await asyncio.to_thread(_read, img), notes) for img, notes in data["slides"]]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    previews = await asyncio.to_thread(lambda: [(f"слайд {i}", _preview(s.jpeg)) for i, s in enumerate(slides, 1)])
    problems = list(data.get("problems") or [])
    if not slides:
        problems.insert(0, 'не найдено ни одного <section class="slide">')
    return DeckShots(slides, previews, list(data.get("errors") or []), problems, int(data.get("geometry") or 0))


def _preview(jpeg: bytes) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    img.thumbnail(DECK_PREVIEW, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()
