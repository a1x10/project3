"""Все настройки берутся из переменных окружения (.env). Ключей в коде нет."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "да")


def _list(name: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]


def _date(name: str) -> date | None:
    raw = _str(name)
    return date.fromisoformat(raw) if raw else None


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


@dataclass
class Settings:
    # --- модель ---
    llm_backend: str = field(default_factory=lambda: _str("LLM_BACKEND", "agent_sdk"))
    llm_model: str = field(default_factory=lambda: _str("LLM_MODEL", "claude-sonnet-5-5"))
    llm_effort: str = field(default_factory=lambda: _str("LLM_EFFORT", "low"))
    # Модель для фоновой выжимки фактов о людях (дешёвая)
    llm_memory_model: str = field(default_factory=lambda: _str("LLM_MEMORY_MODEL", "claude-haiku-5-5"))
    # Автопереключение после окончания промокредитов
    llm_switch_at: date | None = field(default_factory=lambda: _date("LLM_SWITCH_AT"))
    llm_backend_after: str = field(default_factory=lambda: _str("LLM_BACKEND_AFTER", "messages_api"))
    llm_model_after: str = field(default_factory=lambda: _str("LLM_MODEL_AFTER", "claude-haiku-5-5"))
    llm_timeout: float = field(default_factory=lambda: _float("LLM_TIMEOUT", 90))
    llm_max_turns: int = field(default_factory=lambda: _int("LLM_MAX_TURNS", 5))
    daily_budget_usd: float = field(default_factory=lambda: _float("DAILY_BUDGET_USD", 12.0))

    # --- Evolution API ---
    evolution_url: str = field(default_factory=lambda: _str("EVOLUTION_URL", "http://evolution:8080").rstrip("/"))
    evolution_api_key: str = field(default_factory=lambda: _str("EVOLUTION_API_KEY"))
    evolution_instance: str = field(default_factory=lambda: _str("EVOLUTION_INSTANCE", "stella"))
    evolution_auto_setup: bool = field(default_factory=lambda: _bool("EVOLUTION_AUTO_SETUP", True))
    webhook_url: str = field(default_factory=lambda: _str("BOT_WEBHOOK_URL", "http://bot:8000/webhook"))
    webhook_secret: str = field(default_factory=lambda: _str("WEBHOOK_SECRET"))

    # --- база ---
    database_url: str = field(default_factory=lambda: _str("DATABASE_URL", "sqlite:///data/bot.db"))
    data_dir: str = field(default_factory=lambda: _str("DATA_DIR", "data"))
    stickers_dir: str = field(default_factory=lambda: _str("STICKERS_DIR", "data/stickers"))

    # --- личность ---
    bot_name: str = field(default_factory=lambda: _str("BOT_NAME", "Стелла"))
    bot_model_name: str = field(default_factory=lambda: _str("BOT_MODEL_NAME", "Stells"))
    bot_creator: str = field(default_factory=lambda: _str("BOT_CREATOR", "Алексей"))
    bot_project: str = field(default_factory=lambda: _str("BOT_PROJECT", "Codex"))
    swear_level: int = field(default_factory=lambda: _int("SWEAR_LEVEL", 0))
    timezone: str = field(default_factory=lambda: _str("BOT_TIMEZONE", "Asia/Almaty"))

    # --- люди ---
    owner_phone: str = field(default_factory=lambda: _digits(_str("OWNER_PHONE")))
    admin_phones: list[str] = field(default_factory=lambda: [_digits(x) for x in _list("ADMIN_PHONES")])
    allow_dms: bool = field(default_factory=lambda: _bool("ALLOW_DMS", True))
    allowed_groups: list[str] = field(default_factory=lambda: _list("ALLOWED_GROUPS"))

    # --- «как человек» ---
    reply_delay_min: float = field(default_factory=lambda: _float("REPLY_DELAY_MIN", 2))
    reply_delay_max: float = field(default_factory=lambda: _float("REPLY_DELAY_MAX", 5))
    batch_window_min: float = field(default_factory=lambda: _float("BATCH_WINDOW_MIN", 3))
    batch_window_max: float = field(default_factory=lambda: _float("BATCH_WINDOW_MAX", 5))
    batch_max_wait: float = field(default_factory=lambda: _float("BATCH_MAX_WAIT", 12))
    typing_chars_per_sec: float = field(default_factory=lambda: _float("TYPING_CHARS_PER_SEC", 9))
    typo_rate: float = field(default_factory=lambda: _float("TYPO_RATE", 0.0))  # 0 — пишет без опечаток
    typo_fix_rate: float = field(default_factory=lambda: _float("TYPO_FIX_RATE", 0.4))
    max_bubbles: int = field(default_factory=lambda: _int("MAX_BUBBLES", 6))
    rate_limit_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MIN", 20))
    chime_default: str = field(default_factory=lambda: _str("CHIME_IN", "normal"))
    continue_window: float = field(default_factory=lambda: _float("CONTINUE_WINDOW", 120))
    history_window: int = field(default_factory=lambda: _int("HISTORY_WINDOW", 40))
    owner_takeover_minutes: int = field(default_factory=lambda: _int("OWNER_TAKEOVER_MINUTES", 30))

    # --- сама пишет в группы ---
    initiative_per_week: float = field(default_factory=lambda: _float("INITIATIVE_PER_WEEK", 2))
    initiative_hours: str = field(default_factory=lambda: _str("INITIATIVE_HOURS", "10-22"))
    initiative_min_gap_hours: float = field(default_factory=lambda: _float("INITIATIVE_MIN_GAP_HOURS", 36))
    initiative_quiet_minutes: float = field(default_factory=lambda: _float("INITIATIVE_QUIET_MINUTES", 60))
    initiative_open_minutes: float = field(default_factory=lambda: _float("INITIATIVE_OPEN_MINUTES", 30))

    # --- память ---
    memory_extract_every: int = field(default_factory=lambda: _int("MEMORY_EXTRACT_EVERY", 30))
    memory_facts_in_prompt: int = field(default_factory=lambda: _int("MEMORY_FACTS_IN_PROMPT", 12))
    memory_max_facts: int = field(default_factory=lambda: _int("MEMORY_MAX_FACTS", 150))
    memory_share_across_chats: bool = field(default_factory=lambda: _bool("MEMORY_SHARE_ACROSS_CHATS", False))

    # --- казино ---
    casino_start_balance: int = field(default_factory=lambda: _int("CASINO_START_BALANCE", 2000))
    casino_bonus: int = field(default_factory=lambda: _int("CASINO_BONUS", 500))
    casino_bonus_hours: float = field(default_factory=lambda: _float("CASINO_BONUS_HOURS", 12))
    casino_min_bet: int = field(default_factory=lambda: _int("CASINO_MIN_BET", 10))

    # --- стикеры ---
    sticker_collect: bool = field(default_factory=lambda: _bool("STICKER_COLLECT", True))
    sticker_collect_limit: int = field(default_factory=lambda: _int("STICKER_COLLECT_LIMIT", 500))

    # --- алерты ---
    alert_webhook_url: str = field(default_factory=lambda: _str("ALERT_WEBHOOK_URL"))
    log_level: str = field(default_factory=lambda: _str("LOG_LEVEL", "INFO"))

    def backend_for(self, today: date) -> tuple[str, str]:
        """Какой бэкенд и модель использовать сегодня (после LLM_SWITCH_AT — запасные)."""
        if self.llm_switch_at and today >= self.llm_switch_at:
            return self.llm_backend_after, self.llm_model_after
        return self.llm_backend, self.llm_model

    def initiative_window(self) -> tuple[int, int]:
        """(начало, конец) в часах; «20-0» — до полуночи, «0-24» или «10-10» — круглые сутки."""
        try:
            start, end = (int(x) for x in self.initiative_hours.split("-", 1))
        except ValueError:
            return 10, 22
        start = max(0, min(start, 23))
        end = 24 if end in (0, 24) else max(1, min(end, 23))
        if start == end:
            return 0, 24
        return start, end

    def is_admin(self, phone: str | None) -> bool:
        if not phone:
            return False
        return phone == self.owner_phone or phone in self.admin_phones


settings = Settings()
