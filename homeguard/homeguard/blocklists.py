"""Списки блокировки и уровни защиты.

Файлы data/blocklists/<категория>.txt: по одному домену в строке (или формат hosts).
Блокируется и сам домен, и все его поддомены.
"""
from __future__ import annotations
import logging
import re

from . import config

log = logging.getLogger("homeguard.lists")

# Что включает каждый уровень.
LEVELS = {
    "off":    {"title": "Выключена", "categories": [], "suspicious_tlds": False, "block_doh": False},
    "basic":  {"title": "Обычная", "categories": ["ads"], "suspicious_tlds": False, "block_doh": False},
    "medium": {"title": "Средняя", "categories": ["ads", "trackers", "malware", "phishing"],
               "suspicious_tlds": False, "block_doh": False},
    "strict": {"title": "Строгая", "categories": ["ads", "trackers", "malware", "phishing", "adult"],
               "suspicious_tlds": True, "block_doh": True},
}
LEVEL_DESCRIPTIONS = {
    "off": "Всё пропускается, запросы только записываются в журнал.",
    "basic": "Блокирует рекламу.",
    "medium": "Реклама, трекеры, вредоносные и фишинговые сайты. Показывает предупреждение.",
    "strict": "Всё из «Средней» + взрослый контент, подозрительные зоны (.zip, .top…) и обход фильтра через DoH.",
}

SUSPICIOUS_TLDS = {"zip", "mov", "top", "xyz", "click", "country", "gq", "tk", "ml", "cf", "work", "rest"}
DOH_DOMAINS = {"dns.google", "cloudflare-dns.com", "mozilla.cloudflare-dns.com", "dns.quad9.net",
               "doh.opendns.com", "dns.adguard.com", "doh.dns.sb"}

_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9\-_.]*[a-z0-9])?$")

_cache: dict[str, set[str]] | None = None


def _parse(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if not line:
            continue
        parts = line.split()
        dom = parts[-1]  # поддержка формата hosts "0.0.0.0 example.com"
        if dom in ("localhost", "0.0.0.0", "local") or not _DOMAIN_RE.match(dom) or "." not in dom:
            continue
        out.add(dom)
    return out


def load(force: bool = False) -> dict[str, set[str]]:
    global _cache
    if _cache is not None and not force:
        return _cache
    _cache = {}
    if config.BLOCKLIST_DIR.exists():
        for f in sorted(config.BLOCKLIST_DIR.glob("*.txt")):
            # ads.txt (свои записи) и ads.remote.txt (скачанные) сливаются в категорию "ads"
            _cache.setdefault(f.stem.split(".")[0], set()).update(
                _parse(f.read_text(encoding="utf-8", errors="ignore")))
    log.info("Списки: %s", {k: len(v) for k, v in _cache.items()})
    return _cache


def counts() -> dict[str, int]:
    return {k: len(v) for k, v in load().items()}


def _suffixes(domain: str):
    labels = domain.split(".")
    for i in range(len(labels) - 1):
        yield ".".join(labels[i:])


def check(domain: str, level: str) -> tuple[bool, str | None]:
    """(заблокировать?, причина)."""
    cfg = LEVELS.get(level, LEVELS["medium"])
    domain = domain.rstrip(".").lower()
    lists = load()
    for cat in cfg["categories"]:
        entries = lists.get(cat, set())
        for suffix in _suffixes(domain):
            if suffix in entries:
                return True, cat
    if cfg["block_doh"] and any(s in DOH_DOMAINS for s in _suffixes(domain)):
        return True, "doh"
    if cfg["suspicious_tlds"] and domain.rsplit(".", 1)[-1] in SUSPICIOUS_TLDS:
        return True, "suspicious_tld"
    return False, None
