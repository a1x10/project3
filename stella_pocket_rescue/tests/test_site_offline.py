"""Рекламный сайт должен открываться с коробки без интернета: все шрифты и скрипты лежат рядом."""
import hashlib
import re
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent / "site"
PAGES = ("index.html", "product.html", "presentation.html")
THREE_R128_SHA256 = "9274bbcec8d96168626c732b5d31c775aa8cfb7eaa0599bec0c175908a2c1ce2"  # как на cdnjs r128


@pytest.mark.parametrize("page", PAGES)
def test_no_external_resources(page):
    html = (SITE / page).read_text(encoding="utf-8")
    for tag in re.findall(r"<(?:link|script|img|source|iframe)\b[^>]*>", html, re.I):
        for url in re.findall(r"""(?:href|src)\s*=\s*["']([^"']+)""", tag, re.I):
            assert not re.match(r"(https?:)?//", url), (page, url)
            if not url.startswith(("data:", "#")):
                assert (SITE / url.split("?")[0]).is_file(), (page, url)
    assert "fonts.googleapis" not in html and "cdnjs" not in html and "../docs/" not in html


def test_vendored_three_is_the_cdnjs_r128_build():
    data = (SITE / "vendor" / "three.min.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == THREE_R128_SHA256


def test_font_css_points_to_bundled_files():
    css = (SITE / "vendor" / "fonts.css").read_text(encoding="utf-8")
    urls = re.findall(r"url\(([^)]+)\)", css)
    assert len(urls) >= 40
    for url in urls:
        assert (SITE / "vendor" / url).is_file(), url
    for family in ("Archivo", "IBM Plex Sans", "IBM Plex Mono", "Onest"):
        assert f"font-family: '{family}'" in css
    assert "cyrillic" in css and list((SITE / "vendor").glob("LICENSE-*.txt"))
