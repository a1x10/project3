from __future__ import annotations

import re
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def jid_digits(jid: str | None) -> str:
    """'77771234512@s.whatsapp.net' / '77771234512:3@s.whatsapp.net' -> '77771234512'."""
    if not jid:
        return ""
    user = jid.split("@", 1)[0].split(":", 1)[0]
    return "".join(ch for ch in user if ch.isdigit())


def is_phone_jid(jid: str | None) -> bool:
    return bool(jid) and jid.endswith("@s.whatsapp.net")


def phone_of(jid: str | None) -> str:
    return jid_digits(jid) if is_phone_jid(jid) else ""


def mask_phone(value: str | None) -> str:
    """Маска для логов: +7 777 *** ** 12. Группы и LID сокращаются до хвоста."""
    if not value:
        return "-"
    if value.endswith("@g.us"):
        return f"group…{jid_digits(value)[-4:]}"
    if value.endswith("@lid"):
        return f"lid…{jid_digits(value)[-4:]}"
    d = jid_digits(value) if "@" in value else "".join(ch for ch in value if ch.isdigit())
    if len(d) < 6:
        return "***"
    return f"+{d[:-10] or d[0]} {d[-10:-7]} *** ** {d[-2:]}"


_YO = str.maketrans({"ё": "е", "Ё": "Е"})


def norm(text: str) -> str:
    """Нижний регистр, ё->е, схлопнутые пробелы."""
    return re.sub(r"\s+", " ", text.translate(_YO).lower()).strip()


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def money(n: int) -> str:
    """2000 -> '2 000 🍌'."""
    return f"{n:,}".replace(",", " ") + " 🍌"
