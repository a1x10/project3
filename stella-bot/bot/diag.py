"""Почему Стелла молчит? Показывает, что мешает ей отвечать, и умеет это снять.

    docker compose exec bot python -m bot.diag                 # сводка по всем чатам
    docker compose exec bot python -m bot.diag --unpause       # снять паузу во всех чатах
    docker compose exec bot python -m bot.diag --forgive       # снять все обиды
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timezone
from zoneinfo import ZoneInfo

from .config import settings
from .db import DB, chat_paused
from .util import mask_phone, utcnow


def _local_hm(dt, tz: str) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).strftime("%H:%M")


def _ago(dt) -> str:
    if not dt:
        return "никогда"
    minutes = int((utcnow() - dt).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} мин назад"
    if minutes < 48 * 60:
        return f"{minutes // 60} ч назад"
    return f"{minutes // 1440} дн назад"


async def main(argv: list[str] | None = None, out=print) -> int:
    ap = argparse.ArgumentParser(description="Диагностика: почему Стелла не отвечает")
    ap.add_argument("--unpause", action="store_true", help="снять паузу во всех чатах")
    ap.add_argument("--forgive", action="store_true", help="снять все обиды")
    args = ap.parse_args(argv)
    s = settings
    db = DB(s.database_url)
    await db.init()
    try:
        out("=== настройки")
        out(f"личка: {'отвечает' if s.allow_dms else 'ВЫКЛЮЧЕНА (ALLOW_DMS=false)'}")
        if s.allowed_groups:
            out(f"группы: ТОЛЬКО {len(s.allowed_groups)} из ALLOWED_GROUPS, остальные она игнорирует")
        else:
            out("группы: все")
        spend = await db.kv_get(f"spend:{date.today().isoformat()}")
        spent = spend[1] if spend else 0.0
        over = s.daily_budget_usd > 0 and spent >= s.daily_budget_usd
        out(f"расход сегодня: {spent:.2f}$ из {s.daily_budget_usd:g}$" + (" — ЛИМИТ, отвечает только на обращения" if over else ""))
        saved = await db.kv_get("bot_jids")
        jids = json.loads(saved[0]) if saved and saved[0] else []
        has_lid = any(j.endswith("@lid") for j in jids)
        out(f"свой номер: {', '.join(mask_phone(j) for j in jids) or 'ещё не знает'}"
            + ("" if has_lid else " (свой LID пока не знает — @упоминания в группах с LID может не заметить)"))

        if args.unpause:
            n = await db.unpause_all(s.evolution_instance)
            out(f"\nпауза снята в чатах: {n}")
        if args.forgive:
            n = await db.clear_all_grudges()
            out(f"\nобид снято: {n}")

        chats = await db.all_chats(s.evolution_instance)
        out(f"\n=== чаты ({len(chats)})")
        for c in sorted(chats, key=lambda c: (not c["is_group"], c.get("title") or "")):
            name = c.get("title") or mask_phone(c["jid"]) if c["is_group"] else f"личка {mask_phone(c['jid'])}"
            problems = []
            if c["is_group"] and s.allowed_groups and c["jid"] not in s.allowed_groups:
                problems.append("не в ALLOWED_GROUPS")
            if not c["is_group"] and not s.allow_dms:
                problems.append("личка выключена")
            if chat_paused(c):
                problems.append(f"ПАУЗА до {_local_hm(c['paused_until'], s.timezone)} (снять: «стелла вернись» или --unpause)")
            if (c.get("chime_level") or s.chime_default) == "off" and c["is_group"]:
                problems.append("режим выкл: сама не вписывается, отвечает только на обращения")
            grudges = await db.active_grudges(c["id"])
            if grudges:
                problems.append(f"обижена на {len(grudges)} чел.")
            out(f"- {name}: последний её ответ {_ago(c.get('last_bot_at'))}"
                + (" | " + "; ".join(problems) if problems else ""))
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
