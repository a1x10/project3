"""Сайт панели: копия для GitHub Pages (папка docs в корне репозитория) совпадает с panel/ и не нарушает защиту."""

import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, "..", "panel")
DOCS = os.path.join(HERE, "..", "..", "docs")
FILES = ["index.html", "panel.css", "panel.js"]


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


@pytest.mark.skipif(not os.path.isdir(DOCS), reason="нет папки docs (сборка вне репозитория)")
def test_github_pages_copy_is_in_sync():
    for name in FILES:
        assert read(PANEL, name) == read(DOCS, name), f"docs/{name} устарел: cp stella-bot/panel/* docs/"
    assert os.path.exists(os.path.join(DOCS, ".nojekyll"))


def test_panel_has_no_unsafe_dom_or_inline_code():
    js = read(PANEL, "panel.js")
    html = read(PANEL, "index.html")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert bad not in js, bad
    assert "localStorage.setItem(\"stella.token\"" not in js and "localStorage.setItem('stella.token'" not in js
    assert "Content-Security-Policy" in html and "script-src 'self'" in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "встроенный <script> запрещён CSP"
    assert not re.search(r"\son[a-z]+\s*=", html), "обработчики on...= в разметке запрещены CSP"


AD = os.path.join(DOCS, "stella")


@pytest.mark.skipif(not os.path.isdir(AD), reason="нет рекламной страницы docs/stella")
def test_ad_site_is_static_and_safe():
    """Рекламная страница на том же адресе, что и панель: только свой код, без опасных вставок в DOM."""
    html = read(AD, "index.html")
    assert "script-src 'self'" in html and "connect-src 'none'" in html
    assert "require-trusted-types-for 'script'" in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "встроенный <script> запрещён CSP"
    assert not re.search(r"\son[a-z]+\s*=", html), "обработчики on...= в разметке запрещены CSP"
    assert not re.search(r"\sstyle\s*=", html), "атрибут style= запрещён CSP"
    for src in re.findall(r"<(?:script|link)[^>]+(?:src|href)=\"([^\"]+)\"", html):
        assert not re.match(r"(https?:)?//", src), f"внешний файл: {src}"
    files = {}
    for root, _, names in os.walk(AD):
        for name in names:
            if name.endswith((".js", ".css")):
                files[os.path.relpath(os.path.join(root, name), AD)] = read(root, name)
    assert {"common.js", "film.js", "landing.js", "base.css", "film.css", "landing.css", "fonts.css"} <= set(files)
    for name, code in files.items():
        if name.endswith(".js"):
            for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                        "setAttribute(\"style\"", "setAttribute('style'", "fetch(", "XMLHttpRequest", "WebSocket"):
                assert bad not in code, f"{name}: {bad}"
        for url in re.findall(r"https?://[\w-]+(?:\.[\w-]+)+[^\s\"'`)]*", code):
            assert url.startswith(("https://t.me/", "http://www.w3.org/")), f"{name}: внешний адрес {url}"
    for font in re.findall(r"url\((fonts/[^)]+)\)", files["fonts.css"]):
        assert os.path.exists(os.path.join(AD, font)), font
