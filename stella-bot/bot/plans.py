"""Подписки и лимиты сообщений — выдаются из панели (вкладка «Люди» → человек → «Подписка»).

- FREE_REPLIES_PER_DAY — сколько ответов в сутки Стелла даёт человеку без подписки (0 — без лимита).
- Каждому человеку можно выдать подписку (без лимита — на N дней или навсегда) или свой лимит в сутки.
- Владелец и админы бота — всегда без лимита. Друзья (FRIENDS_MODE) — тоже, если им не задан свой лимит.
- Лимит кончился — Стелла отвечает LIMIT_MESSAGE («купите подписку, вся информация у техподдержки…») не чаще
  раза в час и до завтра больше не отвечает этому человеку (модель не вызывается — денег не тратит).
"""

from __future__ import annotations

import json
import time
from datetime import date
from typing import TYPE_CHECKING, Any

from .config import DEFAULT_LIMIT_MESSAGE

if TYPE_CHECKING:
    from .config import Settings
    from .db import DB

KINDS = ("free", "unlimited", "limit")
NOTICE_EVERY = 3600  # «вы достигли лимита» — одному человеку не чаще раза в час


def plan_key(person_id: int) -> str:
    return f"plan:{person_id}"


def used_key(person_id: int) -> str:
    return f"replies:{person_id}"


async def get_plan(db: "DB", person_id: int, *, expired: bool = False) -> dict[str, Any] | None:
    """Действующая подписка или свой лимит; None — обычный (бесплатный) или подписка закончилась
    (expired=True — вернуть и закончившуюся: панель покажет, когда закончилась)."""
    row = await db.kv_get(plan_key(person_id))
    if not row or not row[0]:
        return None
    try:
        plan = json.loads(row[0])
    except ValueError:
        return None
    if not isinstance(plan, dict) or plan.get("kind") not in ("unlimited", "limit"):
        return None
    until = plan.get("until")
    if until and time.time() >= float(until) and not expired:
        return None
    return plan


async def set_plan(db: "DB", person_id: int, kind: str, days: int = 0, limit: int = 0) -> dict[str, Any] | None:
    if kind not in KINDS:
        raise ValueError("нет такого варианта")
    if kind == "free":
        await db.kv_set(plan_key(person_id), "", time.time())
        return None
    now = time.time()
    plan: dict[str, Any] = {"kind": kind, "since": now, "until": now + days * 86400 if days > 0 else None}
    if kind == "limit":
        plan["limit"] = max(1, int(limit))
    await db.kv_set(plan_key(person_id), json.dumps(plan), now)
    return plan


async def used_today(db: "DB", person_id: int) -> int:
    row = await db.kv_get(used_key(person_id))
    return int(row[1]) if row and row[0] == date.today().isoformat() else 0


async def count_reply(db: "DB", person_id: int) -> None:
    """+1 ответ сегодня (одна строка на человека: в value — дата, в num — сколько за эту дату)."""
    today = date.today().isoformat()
    row = await db.kv_get(used_key(person_id))
    if row and row[0] == today:
        await db.kv_add(used_key(person_id), 1)
    else:
        await db.kv_set(used_key(person_id), today, 1)


def daily_limit(s: "Settings", plan: dict[str, Any] | None, trusted: bool) -> int:
    """Сколько ответов в сутки положено человеку; 0 — без лимита."""
    if plan:
        return 0 if plan["kind"] == "unlimited" else max(1, int(plan.get("limit") or 1))
    if trusted:
        return 0
    return max(0, int(getattr(s, "free_replies_per_day", 0) or 0))


def limit_text(s: "Settings", limit: int) -> str:
    text = (getattr(s, "limit_message", "") or "").strip() or DEFAULT_LIMIT_MESSAGE
    support = (getattr(s, "support_contact", "") or "").strip()
    text = text.replace("{limit}", str(limit))
    if "{support}" in text:
        text = text.replace("{support}", support) if support else text.replace(": {support}", "").replace(
            "{support}", "").rstrip(" :—-")
    elif support:
        text += f"\n{support}"
    return text


def limit_hint(s: "Settings", limit: int, used: int) -> str:
    """Подсказка модели: у человека лимит — если спросит, знает, сколько осталось и где купить подписку."""
    support = (getattr(s, "support_contact", "") or "").strip()
    return (f"У этого человека лимит: {limit} твоих ответов в день, сегодня осталось {max(0, limit - used)}. Сама об "
            "этом не заговаривай; спросит про лимит или подписку — подписка снимает ограничение, купить её можно у "
            "техподдержки" + (f" ({support})" if support else "") + ".")
