"""Библиотеки и шрифты для HTML-страниц Стеллы: three.js, GSAP, конфетти, 2D-физика, шрифты с кириллицей.

Страница — один файл без интернета, поэтому нужное встраивается прямо в неё. Файлы скачиваются один раз
(версии и SHA-256 закреплены) и лежат в DATA_DIR/weblibs. Не скачались — подключаются с CDN с проверкой
целостности (SRI) по тем же хешам; тогда именно для них странице нужен интернет.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import posixpath
import re
from dataclasses import dataclass

log = logging.getLogger("stella.weblibs")

CDN = "https://cdn.jsdelivr.net/npm/"
T = "three@0.128.0/examples/js/"


@dataclass(frozen=True)
class Asset:
    file: str  # имя в кеше
    path: str  # путь на CDN
    sha256: str

    @property
    def url(self) -> str:
        return CDN + self.path

    @property
    def sri(self) -> str:
        return "sha256-" + base64.b64encode(bytes.fromhex(self.sha256)).decode()


def _a(file: str, path: str, sha: str) -> Asset:
    return Asset(file, path, sha)


THREE = _a("three.min.js", "three@0.128.0/build/three.min.js",
           "9274bbcec8d96168626c732b5d31c775aa8cfb7eaa0599bec0c175908a2c1ce2")
ORBIT = _a("OrbitControls.js", T + "controls/OrbitControls.js",
           "02bb4ade710f3e607329e37a21f098bc3ac70eb6e33daf8a65e79f4db785e7b2")
COPY_SHADER = _a("CopyShader.js", T + "shaders/CopyShader.js",
                 "6b5da4fe3b410286974590885f82fe4a446f25c728f7d6c888e2a2a331333949")
LUMA_SHADER = _a("LuminosityHighPassShader.js", T + "shaders/LuminosityHighPassShader.js",
                 "00ed0682e61ca207d9c62298269472d6d4eedd9d33528400e7cbc633da8544da")
GAMMA_SHADER = _a("GammaCorrectionShader.js", T + "shaders/GammaCorrectionShader.js",
                  "77c8fdedf8f488b7cab5392afb2d55f1acadf9d9086961b61dfd28f7ae80bdc3")
COMPOSER = _a("EffectComposer.js", T + "postprocessing/EffectComposer.js",
              "4fc320fa3185847797332bc2b0125b1a39b9cf5fc4170a2f180cfa54fb057a2b")
RENDER_PASS = _a("RenderPass.js", T + "postprocessing/RenderPass.js",
                 "57a549b2d6a947cddf0385a804dc70c3b2d155663d908e99e35d42274b3878be")
SHADER_PASS = _a("ShaderPass.js", T + "postprocessing/ShaderPass.js",
                 "2e64890b8e4c4dafcfd796d5c84877f2ad36a101c83263211c500ec40eaf1240")
BLOOM_PASS = _a("UnrealBloomPass.js", T + "postprocessing/UnrealBloomPass.js",
                "1ed342b273e9b077a3e92e5caeecd45043f03071306c696564d5b53f0562dced")
ROUNDED_BOX = _a("RoundedBoxGeometry.js", T + "geometries/RoundedBoxGeometry.js",
                 "5bad5d9e45d4d48bb713d924aec145dc6ea58be568357e50f131efa73a8639f5")
GSAP = _a("gsap.min.js", "gsap@3.15.0/dist/gsap.min.js",
          "92bb9a96476f983d212a2bc4f54c889039c1696dd4461d40a736860938570fbb")
SCROLL_TRIGGER = _a("ScrollTrigger.min.js", "gsap@3.15.0/dist/ScrollTrigger.min.js",
                    "b0b14d67b55b0c43c756ac0b106cfcb09d0879945f6ead64451065b0672916a2")
CONFETTI = _a("confetti.browser.js", "canvas-confetti@1.9.4/dist/confetti.browser.js",
              "49f4bcbc56e7ceb5c3d25d13db1d0da965b6cd1c8a54a707bb055be0685b0a95")
MATTER = _a("matter.min.js", "matter-js@0.20.0/build/matter.min.js",
            "72d30be0f579eb02ce1e0b6f9d359a4f392e6837e5a26ba8be5dbee7f88e24ae")

# <script src="lib/имя.js"> -> что встроить (по порядку)
LIBS: dict[str, tuple[Asset, ...]] = {
    "three": (THREE,),
    "three-orbit": (ORBIT,),
    "three-bloom": (COPY_SHADER, LUMA_SHADER, GAMMA_SHADER, COMPOSER, RENDER_PASS, SHADER_PASS, BLOOM_PASS),
    "three-roundedbox": (ROUNDED_BOX,),
    "gsap": (GSAP,),
    "gsap-scrolltrigger": (SCROLL_TRIGGER,),
    "confetti": (CONFETTI,),
    "matter": (MATTER,),
}

# Привычные адреса с CDN (модель по памяти пишет их) -> те же файлы: (пакет в адресе, имя файла) -> ресурс
_CDN_HOSTS = re.compile(r"^https?://(?:cdnjs\.cloudflare\.com|cdn\.jsdelivr\.net|unpkg\.com)/", re.IGNORECASE)
_ALIASES: dict[tuple[str, str], tuple[Asset, ...]] = {
    ("three", "three.min.js"): (THREE,),
    ("three", "three.js"): (THREE,),
    ("three", "orbitcontrols.js"): (ORBIT,),
    ("three", "copyshader.js"): (COPY_SHADER,),
    ("three", "luminosityhighpassshader.js"): (LUMA_SHADER,),
    ("three", "gammacorrectionshader.js"): (GAMMA_SHADER,),
    ("three", "effectcomposer.js"): (COMPOSER,),
    ("three", "renderpass.js"): (RENDER_PASS,),
    ("three", "shaderpass.js"): (SHADER_PASS,),
    ("three", "unrealbloompass.js"): (BLOOM_PASS,),
    ("three", "roundedboxgeometry.js"): (ROUNDED_BOX,),
    ("gsap", "gsap.min.js"): (GSAP,),
    ("gsap", "gsap.js"): (GSAP,),
    ("gsap", "scrolltrigger.min.js"): (SCROLL_TRIGGER,),
    ("gsap", "scrolltrigger.js"): (SCROLL_TRIGGER,),
    ("canvas-confetti", "confetti.browser.min.js"): (CONFETTI,),
    ("canvas-confetti", "confetti.browser.js"): (CONFETTI,),
    ("canvas-confetti", "confetti.min.js"): (CONFETTI,),
    ("matter", "matter.min.js"): (MATTER,),
    ("matter", "matter.js"): (MATTER,),
}

# Шрифты с кириллицей (Google Fonts через fontsource): семейство -> (толщины, кириллица, латиница)
_LATIN = ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, "
          "U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD")
_CYRILLIC = "U+0301, U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116"


def _var(slug: str, cyr: str, lat: str) -> tuple[Asset, Asset]:
    base = f"@fontsource-variable/{slug}@5.3.0/files/{slug}"
    return (_a(f"{slug}-cyrillic.woff2", f"{base}-cyrillic-wght-normal.woff2", cyr),
            _a(f"{slug}-latin.woff2", f"{base}-latin-wght-normal.woff2", lat))


def _static(slug: str, cyr: str, lat: str) -> tuple[Asset, Asset]:
    base = f"@fontsource/{slug}@5.3.0/files/{slug}"
    return (_a(f"{slug}-cyrillic.woff2", f"{base}-cyrillic-400-normal.woff2", cyr),
            _a(f"{slug}-latin.woff2", f"{base}-latin-400-normal.woff2", lat))


FONTS: dict[str, tuple[str, tuple[Asset, Asset]]] = {
    "Unbounded": ("200 900", _var("unbounded", "e30bf6a6063b6a47232bbd657e24c7cf4fdaf76fc2c50d92d9ee63e2ad2087cf",
                                  "22f9b928aa3928a896340422b54d690fbb5875c30eae4c106f029c61f2289fd6")),
    "Inter": ("100 900", _var("inter", "71d5ee93cc1e9f1d520a3a8b66456de18c7879d8df09d57fcd2eaff75fef0075",
                              "3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62")),
    "Montserrat": ("100 900", _var("montserrat", "a187b077090fe8ae3fd2d7496aabbeae604819c718a282e0afc92df72b450766",
                                   "06b16db7a969135d48d38c49183be7fb88d4452e2a3011957c7851941f4e4879")),
    "Rubik": ("300 900", _var("rubik", "bdb2b33ab916e9e7b42edb61f8aea5f5dd83ad773d6ee4e9b55665daf8954ce8",
                              "691cd1d9b4c0cdf31a1dcf04259c86f92c85e69f6622abab7964d81e36890691")),
    "Playfair Display": ("400 900", _var(
        "playfair-display", "c108681cba6a9820bff52f4a1a4a1d9edf356b347bd79b7c61e916028e8a8b54",
        "e0c764a8e9e1cce92163c55bac4b2ad6cd4cf8c696ce2289ab5c41565e65b7e2")),
    "Comfortaa": ("300 700", _var("comfortaa", "a0fee7d935b77461c002a314cfa398f1d32bf5aedb98063884239400e4663eaf",
                                  "408f20ae9895ceefa460a383d76497a91abc469e3d00b49f080efc7f4b12c60e")),
    "Caveat": ("400 700", _var("caveat", "6276a2f5a5554c16b422f00f114773a8d4013a81df18a338f7c216d80103c9af",
                               "891951df5e8b5b0f0bc760d31375405e795c666b5add70437de12d4a6482b33f")),
    "Russo One": ("400", _static("russo-one", "ae0eadf1b084ac50848e104486c8e929b4b702d8103a1ee064aa3d223dca7ed5",
                                 "8a6b754cd3bc5ad2bf0d0308bbd9c1b7f6b4ecdd915982ffedf50ed18fed4a46")),
    "Press Start 2P": ("400", _static(
        "press-start-2p", "c2a20dcb95ec8f4d1e8db6bd01dfedb669913f5e691e7baa3981b2d88a3b9ae3",
        "afec86997fdaf54af1f59358fa2c1e2a0f1d04146edad18e5cd141d0384a7548")),
    "Lobster": ("400", _static("lobster", "738fd39c3bd07649e0bceb56a847ce07c736799e7212c6570c3644d68188012b",
                               "aed68c73817364906ff95d97be87246d106bd38d5e4397e4866ec831ee22f7ba")),
}
_FONT_RE = {fam: re.compile(r"(?<![\w-])" + re.escape(fam).replace(r"\ ", r"\s+") + r"(?![\w-])", re.IGNORECASE)
            for fam in FONTS}

ALL: tuple[Asset, ...] = tuple(dict.fromkeys(
    [a for group in LIBS.values() for a in group] + [a for _, pair in FONTS.values() for a in pair]))

# Все повторы ограничены по длине: HTML от модели — до 400 тыс. знаков, а регулярка с неограниченным [^>]* на
# неудачном вводе работает квадратично и держит GIL — замер всего бота, а не только этой страницы
_SCRIPT_TAG = re.compile(r"<script\b([^>]{0,2000})>\s{0,200}</script\s{0,20}>", re.IGNORECASE)
_SRC = re.compile(r"""\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
_LINK_TAG = re.compile(r"<link\b[^>]{0,2000}>", re.IGNORECASE)
_DROP_LINK = re.compile(r"fonts\.(?:googleapis|gstatic)\.com|\brel\s*=\s*[\"']?\s*(?:dns-prefetch|preconnect|prefetch|preload|"
                        r"prerender|modulepreload)", re.IGNORECASE)
# @import url('https://fonts.googleapis.com/css2?family=X:wght@400;700&display=swap'); — в адресе бывают «;»
_FONT_IMPORT = re.compile(r"""@import\s{1,20}(?:url\(\s{0,20})?(["']?)[^"'()\s]{0,2000}fonts\.googleapis\.com[^"'()\s]{0,2000}\1"""
                          r"""\s{0,20}\)?[^;{}\n]{0,200};?""", re.IGNORECASE)


def cache_dir() -> str:
    return os.path.join(os.environ.get("DATA_DIR", "data"), "weblibs")


def resolve(src: str) -> tuple[Asset, ...] | None:
    """Адрес из <script src> -> файлы, которые встроить (или None — не наша библиотека)."""
    s = src.strip()
    low = s.lower()
    if low.startswith(("lib/", "./lib/", "/lib/")):
        name = posixpath.basename(low)
        name = name.removesuffix(".js").removesuffix(".min")
        if name in LIBS:
            return LIBS[name]
        return next((a for (_, file), a in _ALIASES.items() if file in (name + ".js", name + ".min.js")), None)
    if _CDN_HOSTS.match(s):
        path = low.split("?", 1)[0].split("#", 1)[0]
        folder, base = posixpath.split(path)
        for (pkg, file), assets in _ALIASES.items():
            if file == base and re.search(rf"[/@]{re.escape(pkg)}(?:[@/.\-]|js/)", folder + "/"):
                return assets
    return None


def _read(asset: Asset, folder: str) -> bytes | None:
    try:
        with open(os.path.join(folder, asset.file), "rb") as f:
            data = f.read()
    except OSError:
        return None
    return data if hashlib.sha256(data).hexdigest() == asset.sha256 else None


def missing(folder: str | None = None) -> list[Asset]:
    folder = folder or cache_dir()
    return [a for a in ALL if _read(a, folder) is None]


_lock = asyncio.Lock()


async def ensure(folder: str | None = None, client=None, timeout: float = 30.0) -> list[Asset]:
    """Скачать недостающее (с проверкой хеша). Возвращает то, что скачать не вышло."""
    import httpx

    folder = folder or cache_dir()
    async with _lock:
        todo = await asyncio.to_thread(missing, folder)
        if not todo:
            return []
        await asyncio.to_thread(os.makedirs, folder, exist_ok=True)
        own = client is None
        client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        failed = []
        try:
            for asset in todo:
                try:
                    resp = await client.get(asset.url)
                    resp.raise_for_status()
                    data = resp.content
                    if hashlib.sha256(data).hexdigest() != asset.sha256:
                        raise ValueError("хеш не совпал")
                    await asyncio.to_thread(_write, folder, asset.file, data)
                except Exception as exc:
                    log.warning("не скачалась библиотека %s: %s", asset.path, exc)
                    failed.append(asset)
        finally:
            if own:
                await client.aclose()
        if not failed:
            log.info("библиотеки для HTML-страниц скачаны (%d файлов)", len(todo))
        return failed


def _write(folder: str, name: str, data: bytes) -> None:
    tmp = os.path.join(folder, f".{name}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(folder, name))


@dataclass
class Embedded:
    html: str
    script_src: list[str]  # что всё же грузится с CDN (нет в кеше) — для CSP
    font_src: list[str]


def embed(html: str, folder: str | None = None) -> Embedded:
    """Встроить в страницу библиотеки из <script src="lib/…"> (и привычных адресов CDN) и нужные шрифты."""
    folder = folder or cache_dir()
    # шрифты ищем в странице как её написала модель — не в коде встроенных библиотек
    families = [fam for fam in FONTS if _FONT_RE[fam].search(html)]
    done: set[Asset] = set()
    script_src: list[str] = []

    def script(m: re.Match[str]) -> str:
        attrs = m.group(1)
        src = _SRC.search(attrs)
        if not src:
            return m.group(0)
        assets = resolve(next(g for g in src.groups() if g is not None))
        if assets is None:
            return m.group(0)
        out = []
        for asset in assets:
            if asset in done:  # одна библиотека дважды — второй раз не нужна
                continue
            done.add(asset)
            data = _read(asset, folder)
            if data is not None:
                code = data.decode("utf-8", "replace").replace("</script", "<\\/script")
                out.append(f"<script>/* {asset.path} */\n{code}\n</script>")
            else:
                script_src.append(asset.url)
                out.append(f'<script src="{asset.url}" integrity="{asset.sri}" crossorigin="anonymous"></script>')
        return "\n".join(out)

    html = _SCRIPT_TAG.sub(script, html)
    # шрифты Google не нужны (встроим свои), а dns-prefetch/preconnect — запросы в обход CSP
    html = _LINK_TAG.sub(lambda m: "" if _DROP_LINK.search(m.group(0)) else m.group(0), html)
    html = _FONT_IMPORT.sub("", html)
    faces: list[str] = []
    font_src: list[str] = []
    for family in families:
        weights, (cyr, lat) = FONTS[family]
        for asset, rng in ((cyr, _CYRILLIC), (lat, _LATIN)):
            data = _read(asset, folder)
            if data is not None:
                url = "data:font/woff2;base64," + base64.b64encode(data).decode()
            else:
                url = asset.url
                font_src.append(asset.url)
            faces.append(f"@font-face{{font-family:'{family}';font-style:normal;font-display:swap;"
                         f"font-weight:{weights};src:url({url}) format('woff2');unicode-range:{rng}}}")
    if faces:
        html = "<style>" + "\n".join(faces) + "</style>\n" + html
    return Embedded(html, script_src, font_src)
