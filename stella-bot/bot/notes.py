"""Что Стелла знает про группу «от владельца»: кто есть кто, свои мемы, правила чата.

Это хранится только в базе на сервере (в git не попадает) и показывается Стелле в каждом ответе.

    docker compose exec bot python -m bot.notes                     # группы и что про них записано
    docker compose exec -T bot python -m bot.notes set < about.txt  # записать (текст из stdin)
    docker compose exec -T bot python -m bot.notes set --group 7в <<'EOF'
    ...текст...
    EOF
    docker compose exec bot python -m bot.notes clear --group 7в
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .config import settings
from .db import DB
from .util import mask_phone, norm

MAX_ABOUT = 4000


def _pick(groups: list[dict], query: str | None) -> dict | None:
    if query:
        q = norm(query)
        found = [g for g in groups if q in norm(g.get("title") or "") or q == g["jid"]]
    else:
        found = groups
    return found[0] if len(found) == 1 else None


async def main(argv: list[str] | None = None, stdin=None, out=print) -> int:
    ap = argparse.ArgumentParser(description="Заметки владельца о группе")
    ap.add_argument("action", nargs="?", default="show", choices=["show", "set", "clear"])
    ap.add_argument("--group", help="часть названия группы или её JID (нужно, если групп несколько)")
    args = ap.parse_args(argv)

    db = DB(settings.database_url)
    await db.init()
    try:
        groups = await db.group_chats(settings.evolution_instance)
        if args.action == "show":
            if not groups:
                out("групп пока нет: Стелла должна получить хотя бы одно сообщение в группе")
            for g in groups:
                out(f"— «{g.get('title') or 'без названия'}» ({mask_phone(g['jid'])}, --group {g['jid']})")
                out((g.get("about") or "  (ничего не записано)").strip())
                out("")
            return 0
        chat = _pick(groups, args.group)
        if chat is None:
            out("не поняла, какая группа. Укажи --group (часть названия или JID). Есть:")
            for g in groups:
                out(f"  «{g.get('title') or 'без названия'}»  {g['jid']}")
            return 1
        if args.action == "clear":
            await db.update_chat(chat["id"], about=None)
            out(f"очищено для «{chat.get('title') or chat['jid']}»")
            return 0
        text = (stdin or sys.stdin).read().strip()
        if not text:
            out("пустой текст — ничего не записала")
            return 1
        if len(text) > MAX_ABOUT:
            out(f"текст длинный ({len(text)} символов), сохраню первые {MAX_ABOUT}")
            text = text[:MAX_ABOUT]
        await db.update_chat(chat["id"], about=text)
        out(f"записала про «{chat.get('title') or chat['jid']}» ({len(text)} символов) ✅")
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
