"""Примеры, как общаются ребята: куски переписок, словечки, мемы — добавляются в панели («Настройки» → «Как общаются»).

К каждому ответу Стелла получает небольшую случайную выборку — чтобы писать на живом современном языке.
Номера телефонов и почта при добавлении заменяются на [номер] / [почта]; имена лучше убрать самому.
"""

from __future__ import annotations

import json
import random
import re
import secrets
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .db import DB

STYLE_KV = "style_examples"
KINDS = {"chat": "переписка", "slang": "словечки", "meme": "мемы и шутки"}
MAX_ITEMS = 300
MAX_TEXT = 6000
PROMPT_CHARS = 2400  # сколько примеров идёт в один ответ (чтобы не раздувать запрос)

_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s\-()]{8,}\d(?!\w)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def clean(text: str) -> str:
    text = _EMAIL.sub("[почта]", text)
    text = _PHONE.sub("[номер]", text)
    return text.replace("\r\n", "\n").strip()[:MAX_TEXT]


class StyleStore:
    def __init__(self, db: "DB | None" = None):
        self.db = db
        self.items: list[dict[str, Any]] = []

    async def load(self) -> None:
        if self.db is None:
            return
        row = await self.db.kv_get(STYLE_KV)
        try:
            data = json.loads(row[0]) if row and row[0] else []
        except ValueError:
            data = []
        self.items = [i for i in data if isinstance(i, dict) and i.get("kind") in KINDS and i.get("text")]

    async def save(self) -> None:
        if self.db is not None:
            await self.db.kv_set(STYLE_KV, json.dumps(self.items, ensure_ascii=False), time.time())

    async def add(self, kind: str, text: str) -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError("нет такого вида")
        text = clean(text)
        if len(text) < 3:
            raise ValueError("пусто")
        if len(self.items) >= MAX_ITEMS:
            raise ValueError(f"больше {MAX_ITEMS} примеров не храню — удали старые")
        item = {"id": "s_" + secrets.token_hex(4), "kind": kind, "text": text, "added_at": time.time()}
        self.items.append(item)
        await self.save()
        return item

    async def remove(self, item_id: str) -> bool:
        before = len(self.items)
        self.items = [i for i in self.items if i["id"] != item_id]
        await self.save()
        return len(self.items) < before

    def public(self) -> list[dict[str, Any]]:
        return [{"id": i["id"], "kind": i["kind"], "kind_name": KINDS[i["kind"]], "text": i["text"],
                 "chars": len(i["text"]), "added_at": i.get("added_at")} for i in self.items]

    def hint(self, rng: random.Random | None = None, budget: int = PROMPT_CHARS) -> str:
        """Случайная выборка для одного ответа: понемногу каждого вида, длинные переписки — кусочком."""
        if not self.items:
            return ""
        rng = rng or random.Random()
        pool = self.items[:]
        rng.shuffle(pool)
        parts: list[str] = []
        left = budget
        for item in sorted(pool, key=lambda i: i["kind"] != "slang"):  # словечки — первыми, они короткие
            text = item["text"]
            if len(text) > left:
                if left < 200:
                    break
                start = rng.randrange(0, max(1, len(text) - left))
                text = "…" + text[start:start + left - 2].strip() + "…"
            parts.append(f"[{KINDS[item['kind']]}]\n{text}")
            left -= len(text) + 20
            if left <= 0:
                break
        return ("Как сейчас общаются ребята — живые примеры (бери отсюда тон, словечки и юмор; дословно не "
                "копируй, людей из примеров не упоминай и не говори, что у тебя есть примеры):\n" + "\n\n".join(parts))


STORE = StyleStore()
