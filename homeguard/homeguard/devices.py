"""Определение производителя и типа устройства по MAC / имени."""
from __future__ import annotations
import re

# Небольшая встроенная таблица. Полную можно положить в data/oui.txt (формат: "AABBCC<TAB>Vendor").
OUI = {
    "F8A45F": "Xiaomi", "64CC2E": "Xiaomi", "286C07": "Xiaomi", "7802F8": "Xiaomi", "AC1E9E": "Xiaomi",
    "FC64BA": "Xiaomi", "34CE00": "Xiaomi",
    "04B429": "Sony", "FCF152": "Sony", "A8E3EE": "Sony", "30F9ED": "Sony", "0013A9": "Sony",
    "3C2EF9": "Apple", "F0DBF8": "Apple", "A4D1D2": "Apple", "BC926B": "Apple", "F4F15A": "Apple",
    "001A11": "Google", "F4F5D8": "Google", "3C5AB4": "Google",
    "B827EB": "Raspberry Pi", "DCA632": "Raspberry Pi", "E45F01": "Raspberry Pi",
    "5CF370": "Samsung", "8C7712": "Samsung", "FCA13E": "Samsung",
    "C83A35": "Tenda", "50C7BF": "TP-Link", "F4F26D": "TP-Link", "98DAC4": "TP-Link",
    "6C3B6B": "MikroTik", "18C04D": "Yandex", "E09D31": "Yandex",
}

_extra_loaded = False


def _load_extra():
    global _extra_loaded
    if _extra_loaded:
        return
    _extra_loaded = True
    from . import config
    path = config.ROOT / "data" / "oui.txt"
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and len(parts[0]) == 6:
                OUI.setdefault(parts[0].upper(), parts[1].strip())


def vendor_of(mac: str) -> str | None:
    _load_extra()
    key = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()[:6]
    return OUI.get(key)


def is_random_mac(mac: str) -> bool:
    """Телефоны часто используют приватный (случайный) MAC — второй бит первого байта."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0b10)
    except ValueError:
        return False


def guess_type(hostname: str | None, vendor: str | None, is_gateway: bool = False) -> str:
    """Возвращает: router | computer | phone | tv | speaker | appliance | iot | unknown."""
    if is_gateway:
        return "router"
    h = (hostname or "").lower()
    v = (vendor or "").lower()
    rules = [
        ("router", r"gateway|router|keenetic|mikrotik|tp-link|tenda"),
        ("tv", r"bravia|tv|sony|samsung-tv|lg-?web|androidtv"),
        ("speaker", r"yandex|station|alice|echo|homepod|nest-?mini|google-home"),
        ("appliance", r"washer|washing|stiral|dishwasher|fridge|vacuum|roborock|dreame|viomi|mijia"),
        ("phone", r"iphone|android|galaxy|redmi|poco|xiaomi-?1|pixel|oneplus|huawei|honor|-15t|phone"),
        ("computer", r"desktop|laptop|macbook|imac|pc-|-pc|ubuntu|win-|raspberry|komp|comp"),
    ]
    for dtype, pattern in rules:
        if re.search(pattern, h):
            return dtype
    if "raspberry" in v or "apple" in v:
        return "computer"
    if "sony" in v:
        return "tv"
    if "yandex" in v:
        return "speaker"
    if "mikrotik" in v or "tp-link" in v or "tenda" in v:
        return "router"
    if "xiaomi" in v:
        return "phone"
    return "unknown"
