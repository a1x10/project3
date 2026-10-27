"""Скачивает публичные списки в data/blocklists/. Запуск: python scripts/update_blocklists.py"""
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "blocklists"
SOURCES = {
    "ads": ["https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts"],
    "trackers": ["https://v.firebog.net/hosts/Easyprivacy.txt"],
    "malware": ["https://urlhaus.abuse.ch/downloads/hostfile/"],
    "phishing": ["https://phishing.army/download/phishing_army_blocklist.txt"],
    "adult": ["https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/porn-only/hosts"],
}

for category, urls in SOURCES.items():
    chunks = []
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                chunks.append(r.read().decode("utf-8", "ignore"))
            print(f"ok   {category}: {url}")
        except Exception as e:
            print(f"FAIL {category}: {url}: {e}", file=sys.stderr)
    if chunks:
        # <категория>.txt с собственными записями не трогаем
        (OUT / f"{category}.remote.txt").write_text("\n".join(chunks), encoding="utf-8")
