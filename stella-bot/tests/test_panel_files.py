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
    assert "1010" not in js + html and "2013" not in js + html  # паролей в публичных файлах нет
