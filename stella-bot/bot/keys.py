"""Ключи других провайдеров (Groq, OpenRouter, Gemini, OpenAI) — добавляются в панели, их может быть несколько.

- Ключи хранятся в БД (kv «api_keys»), наружу — только в замаскированном виде (gsk_…9f3A).
- Несколько ключей одного провайдера работают по очереди: упёрся в лимит (429) — пауза этому ключу, берём
  следующий; ключ не принят (401/403) — помечаем ошибкой и тоже берём следующий.
- Какой провайдер Стелла использует сейчас — kv «llm_active» (выбирается в панели) — см. Settings.backend_for.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .db import DB

log = logging.getLogger("stella.keys")

KEYS_KV = "api_keys"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str
    default_model: str
    models: tuple[str, ...]
    signup_url: str
    hint: str


PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    Provider("groq", "Groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b",
             ("openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "llama-3.1-8b-instant"),
             "https://console.groq.com/keys", "Бесплатно с лимитами в минуту и в сутки; очень быстрый"),
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "openrouter/auto",
             ("openrouter/auto",), "https://openrouter.ai/keys",
             "Сотни моделей по одному ключу; есть бесплатные (с «:free» в названии)"),
    Provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
             "gemini-2.5-flash", ("gemini-2.5-flash", "gemini-2.5-pro"), "https://aistudio.google.com/apikey",
             "Бесплатный уровень с лимитами"),
    Provider("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4.1-mini", ("gpt-4.1-mini", "gpt-4.1"),
             "https://platform.openai.com/api-keys", "Платно, по балансу аккаунта"),
)}


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z") if ts else None


def mask(key: str) -> str:
    key = key.strip()
    return f"{key[:4]}…{key[-4:]}" if len(key) > 12 else "…" + key[-2:]


@dataclass
class ApiKey:
    id: str
    provider: str
    key: str
    label: str = ""
    added_at: float = field(default_factory=time.time)
    disabled: bool = False
    last_used: float | None = None
    last_error: str | None = None
    uses: int = 0
    models: list[str] = field(default_factory=list)  # что провайдер сам отдал при проверке

    def public(self, cooldown_until: float | None) -> dict[str, Any]:
        return {"id": self.id, "provider": self.provider, "label": self.label, "masked": mask(self.key),
                "disabled": self.disabled, "added_at": _iso(self.added_at), "last_used": _iso(self.last_used),
                "last_error": self.last_error, "uses": self.uses,
                "cooldown_until": _iso(cooldown_until) if cooldown_until and cooldown_until > time.time() else None}


class KeyStore:
    def __init__(self, db: "DB | None" = None):
        self.db = db
        self.keys: list[ApiKey] = []
        self.cooldown: dict[str, float] = {}  # id ключа -> до какого времени не трогать (лимит)
        self._turn: dict[str, int] = {}  # провайдер -> чей ход (по кругу)

    async def load(self) -> None:
        if self.db is None:
            return
        row = await self.db.kv_get(KEYS_KV)
        try:
            raw = json.loads(row[0]) if row and row[0] else []
        except ValueError:
            raw = []
        known = set(ApiKey.__dataclass_fields__)
        self.keys = [ApiKey(**{k: v for k, v in item.items() if k in known}) for item in raw
                     if isinstance(item, dict) and item.get("provider") in PROVIDERS and item.get("key")]

    async def save(self) -> None:
        if self.db is not None:
            await self.db.kv_set(KEYS_KV, json.dumps([asdict(k) for k in self.keys], ensure_ascii=False), time.time())

    def get(self, key_id: str) -> ApiKey | None:
        return next((k for k in self.keys if k.id == key_id), None)

    def public(self) -> list[dict[str, Any]]:
        return [k.public(self.cooldown.get(k.id)) for k in self.keys]

    def has(self, provider: str) -> bool:
        return any(k.provider == provider and not k.disabled for k in self.keys)

    async def add(self, provider: str, key: str, label: str = "") -> ApiKey:
        key = key.strip()
        if provider not in PROVIDERS:
            raise ValueError("нет такого провайдера")
        if not (16 <= len(key) <= 300) or any(c.isspace() for c in key):
            raise ValueError("это не похоже на ключ")
        if any(k.key == key for k in self.keys):
            raise ValueError("этот ключ уже добавлен")
        item = ApiKey(id="k_" + secrets.token_hex(4), provider=provider, key=key, label=label.strip()[:40])
        self.keys.append(item)
        await self.save()
        return item

    async def remove(self, key_id: str) -> bool:
        before = len(self.keys)
        self.keys = [k for k in self.keys if k.id != key_id]
        self.cooldown.pop(key_id, None)
        await self.save()
        return len(self.keys) < before

    def candidates(self, provider: str) -> list[ApiKey]:
        """Ключи провайдера в порядке очереди: сначала свободные (по кругу), на паузе — в конце."""
        pool = [k for k in self.keys if k.provider == provider and not k.disabled]
        if not pool:
            return []
        start = self._turn.get(provider, 0) % len(pool)
        self._turn[provider] = start + 1
        ordered = pool[start:] + pool[:start]
        now = time.time()
        return sorted(ordered, key=lambda k: self.cooldown.get(k.id, 0) > now)

    async def used(self, item: ApiKey) -> None:
        item.uses += 1
        item.last_used = time.time()
        if item.last_error:
            item.last_error = None
        await self.save()

    async def failed(self, item: ApiKey, error: str, retry_after: float | None = None) -> None:
        item.last_error = error[:200]
        if retry_after:
            self.cooldown[item.id] = time.time() + min(max(retry_after, 5), 3600)
        await self.save()


STORE = KeyStore()  # общий на весь бот; brain подключает к БД при старте
