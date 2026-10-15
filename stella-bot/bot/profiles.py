"""Посмотреть анкеты, которые Стелла сама заполнила про участников.

    docker compose exec bot python -m bot.profiles              # все группы
    docker compose exec bot python -m bot.profiles --group 7в   # одна группа
"""

from __future__ import annotations

import argparse
import asyncio

from .config import settings
from .db import DB
from .util import norm


async def main(argv: list[str] | None = None, out=print) -> int:
    ap = argparse.ArgumentParser(description="Анкеты участников")
    ap.add_argument("--group", help="часть названия группы")
    args = ap.parse_args(argv)
    db = DB(settings.database_url)
    await db.init()
    try:
        groups = await db.group_chats(settings.evolution_instance)
        if args.group:
            groups = [g for g in groups if norm(args.group) in norm(g.get("title") or "") or args.group == g["jid"]]
        if not groups:
            out("групп не найдено")
            return 1
        for g in groups:
            members = await db.chat_members(g["id"], limit=500)
            out(f"=== «{g.get('title') or 'без названия'}» — участников: {len(members)}")
            for p in members:
                profile = await db.get_profile(p.id, g["id"])
                facts = await db.get_facts(p.id, g["id"], 500)
                out(f"\n{p.name} [{p.ref}]  (фактов: {len(facts)})")
                if profile:
                    for k, v in profile.items():
                        out(f"  {k}: {v}")
                else:
                    out("  анкета пока пустая")
            out("")
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
