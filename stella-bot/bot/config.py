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


ANTHROPIC_BACKENDS = ("agent_sdk", "messages_api")

DEFAULT_LIMIT_MESSAGE = ("Вы достигли лимита сообщений на сегодня 🙏 Чтобы общаться без ограничений, купите подписку — "
                         "вся информация у техподдержки: {support}")


@dataclass
class Settings:
    # --- модель ---
    llm_backend: str = field(default_factory=lambda: _str("LLM_BACKEND", "agent_sdk"))
    llm_model: str = field(default_factory=lambda: _str("LLM_MODEL", "claude-opus-5-5"))
    # high — умно и всё ещё быстро для чата; xhigh/max — ещё глубже, но ответ в чате может идти минуты
    llm_effort: str = field(default_factory=lambda: _str("LLM_EFFORT", "high"))
    # Модель для фоновой выжимки фактов о людях (дешёвая)
    llm_memory_model: str = field(default_factory=lambda: _str("LLM_MEMORY_MODEL", "claude-sonnet-5-5"))
    # глубина обдумывания для выжимки фактов (фоновая работа: medium — точно и недорого); пусто — как LLM_EFFORT
    llm_memory_effort: str = field(default_factory=lambda: _str("LLM_MEMORY_EFFORT", "medium"))
    # Автопереключение после окончания промокредитов
    llm_switch_at: date | None = field(default_factory=lambda: _date("LLM_SWITCH_AT"))
    # off — с этой даты модель выключена: ни одного запроса к Anthropic, свой баланс не тратится (команды,
    # казино, напоминания работают); messages_api — дальше работать за свой баланс API
    llm_backend_after: str = field(default_factory=lambda: _str("LLM_BACKEND_AFTER", "off"))
    # что она отвечает, когда к ней обращаются, а модель выключена (одному чату — не чаще раза в 6 часов)
    # модель у Groq / OpenRouter / Gemini / OpenAI (ключи — в панели, «Ключи»); пусто — модель провайдера по умолчанию
    alt_model: str = field(default_factory=lambda: _str("ALT_MODEL"))
    model_off_message: str = field(default_factory=lambda: _str("MODEL_OFF_MESSAGE", "Я пока на паузе 🙏"))
    llm_model_after: str = field(default_factory=lambda: _str("LLM_MODEL_AFTER", "claude-opus-5-5"))
    # Opus думает дольше, а презентация или видео — это длинный ответ: даём до 3 минут
    llm_timeout: float = field(default_factory=lambda: _float("LLM_TIMEOUT", 600))
    # потолок на один ответ (защита от зацикливания), $
    llm_max_call_usd: float = field(default_factory=lambda: _float("LLM_MAX_CALL_USD", 1.5))
    # поиск в интернете (выполняется на стороне Anthropic, к серверу доступа не даёт)
    llm_web_search: bool = field(default_factory=lambda: _bool("LLM_WEB_SEARCH", True))
    llm_max_turns: int = field(default_factory=lambda: _int("LLM_MAX_TURNS", 5))
    daily_budget_usd: float = field(default_factory=lambda: _float("DAILY_BUDGET_USD", 0.0))
    # сколько ответов модель готовит одновременно (каждый — отдельный процесс; больше — нужна память и лимиты API)
    llm_concurrency: int = field(default_factory=lambda: _int("LLM_CONCURRENCY", 3))

    # --- что она делает сама: стикеры, картинки, документы, презентации, таблицы, видео ---
    media_enabled: bool = field(default_factory=lambda: _bool("MEDIA_ENABLED", True))
    # дневные лимиты: 0 — без лимита (так по умолчанию: ботом пользуются свои; от трат — DAILY_BUDGET_USD)
    media_per_day: int = field(default_factory=lambda: _int("MEDIA_PER_DAY", 0))  # на чат в сутки
    # мультики с движением (make_cartoon): рисуются на сервере в отдельном процессе, по одному за раз
    anim_enabled: bool = field(default_factory=lambda: _bool("ANIM_ENABLED", True))
    anim_per_day: int = field(default_factory=lambda: _int("ANIM_PER_DAY", 0))  # на чат в сутки (владельцу — без лимита)
    # HTML-страницы (make_html): игры, открытки, викторины, сайты. Пишет их отдельный вызов модели («студия»)
    # с дизайн-промптом и максимальным обдумыванием, потом доводит по скриншотам из браузера («арт-директор»):
    # ~5–15 минут и ~1–3 $ за страницу на Opus 5.5 (effort max). Быстрее и дешевле: HTML_EFFORT=high
    html_enabled: bool = field(default_factory=lambda: _bool("HTML_ENABLED", True))
    html_model: str = field(default_factory=lambda: _str("HTML_MODEL", "claude-opus-5-5"))
    html_effort: str = field(default_factory=lambda: _str("HTML_EFFORT", "max"))
    html_max_tokens: int = field(default_factory=lambda: _int("HTML_MAX_TOKENS", 128000))
    html_timeout: float = field(default_factory=lambda: _float("HTML_TIMEOUT", 1500))  # на один вызов, с
    # сколько токенов модель видит на всю работу (обдумывание + код) и под это распределяет силы — чтобы на
    # effort max не упереться в HTML_MAX_TOKENS; 0 — без бюджета
    html_task_budget: int = field(default_factory=lambda: _int("HTML_TASK_BUDGET", 100000))
    # доводка по скриншотам (нужен браузер в образе: WITH_BROWSER=true) и с каким усилием
    html_polish: bool = field(default_factory=lambda: _bool("HTML_POLISH", True))
    html_polish_effort: str = field(default_factory=lambda: _str("HTML_POLISH_EFFORT", "max"))
    # презентации тоже делает студия (слайды рисуются в браузере -> PowerPoint + PDF); false — простые из списка
    deck_studio: bool = field(default_factory=lambda: _bool("DECK_STUDIO", True))
    html_per_day: int = field(default_factory=lambda: _int("HTML_PER_DAY", 0))  # на чат в сутки (админам — без лимита)
    html_per_day_total: int = field(default_factory=lambda: _int("HTML_PER_DAY_TOTAL", 0))  # на всех (кроме владельца)
    html_concurrency: int = field(default_factory=lambda: _int("HTML_CONCURRENCY", 2))
    # видео по ссылке: скинули TikTok/YouTube — скачивает (yt-dlp) и присылает ответом на это сообщение
    video_dl_enabled: bool = field(default_factory=lambda: _bool("VIDEO_DL_ENABLED", True))
    video_dl_per_day: int = field(default_factory=lambda: _int("VIDEO_DL_PER_DAY", 0))  # на чат в сутки
    video_dl_max_seconds: int = field(default_factory=lambda: _int("VIDEO_DL_MAX_SECONDS", 300))  # длиннее — не качает
    video_dl_max_mb: int = field(default_factory=lambda: _int("VIDEO_DL_MAX_MB", 30))
    # cookies.txt (формат Netscape) от аккаунта YouTube — если ютуб на сервере просит «войти»; пусто — data/cookies.txt
    video_dl_cookies: str = field(default_factory=lambda: _str("VIDEO_DL_COOKIES", ""))
    # она «видит» фото и стикеры, которые ей присылают (и на которые отвечают с вопросом к ней)
    vision_enabled: bool = field(default_factory=lambda: _bool("VISION_ENABLED", True))
    vision_max_images: int = field(default_factory=lambda: _int("VISION_MAX_IMAGES", 3))
    # голосовые: понимает (faster-whisper) и может ответить голосом (piper) — всё на сервере, бесплатно.
    # base — легче (~0.3 ГБ памяти), small — точнее (~0.5–0.7 ГБ). Модели скачиваются при первом голосовом.
    voice_enabled: bool = field(default_factory=lambda: _bool("VOICE_ENABLED", True))
    voice_stt_model: str = field(default_factory=lambda: _str("VOICE_STT_MODEL", "base"))
    voice_tts_voice: str = field(default_factory=lambda: _str("VOICE_TTS_VOICE", "ru_RU-irina-medium"))
    voice_max_seconds: int = field(default_factory=lambda: _int("VOICE_MAX_SECONDS", 180))
    # читает присланные файлы: PDF, Word, Excel, PowerPoint, текст
    documents_enabled: bool = field(default_factory=lambda: _bool("DOCUMENTS_ENABLED", True))
    # запуск кода в песочнице Anthropic — по просьбе владельца (и друзей при FRIENDS_MODE)
    sandbox_enabled: bool = field(default_factory=lambda: _bool("SANDBOX_ENABLED", True))
    sandbox_model: str = field(default_factory=lambda: _str("SANDBOX_MODEL", "claude-opus-5-5"))
    sandbox_effort: str = field(default_factory=lambda: _str("SANDBOX_EFFORT", "max"))
    # большая задача (mode=project) делается в фоне не дольше стольких секунд
    sandbox_project_timeout: float = field(default_factory=lambda: _float("SANDBOX_PROJECT_TIMEOUT", 1800))
    # запусков в сутки на человека (владельцу — без лимита)
    sandbox_per_day: int = field(default_factory=lambda: _int("SANDBOX_PER_DAY", 0))
    # quick-задача ждёт ответа не дольше стольких секунд (не держим очередь ответов бота) — дальше доделывает в фоне
    sandbox_quick_seconds: float = field(default_factory=lambda: _float("SANDBOX_QUICK_SECONDS", 150))
    # потолок расходов одного запуска, $ (дальше — останавливается, «продолжи» доделает); 0 — без потолка
    sandbox_max_run_usd: float = field(default_factory=lambda: _float("SANDBOX_MAX_RUN_USD", 10))
    # ультра-режим для программирования (как ultracode): план и тесты -> код -> независимая проверка -> исправления.
    # projects — так идёт каждая большая задача; ask — только когда просят «ультра»/«максимально»; off — выключен
    sandbox_ultra: str = field(default_factory=lambda: _str("SANDBOX_ULTRA", "projects"))
    # «напиши человеку от своего лица» по просьбе владельца: не больше стольких сообщений в сутки (за массовые
    # сообщения WhatsApp банит номер)
    outreach_per_day: int = field(default_factory=lambda: _int("OUTREACH_PER_DAY", 0))
    sandbox_ultra_rounds: int = field(default_factory=lambda: _int("SANDBOX_ULTRA_ROUNDS", 3))  # сколько проверок
    sandbox_ultra_max_usd: float = field(default_factory=lambda: _float("SANDBOX_ULTRA_MAX_USD", 30))
    sandbox_ultra_timeout: float = field(default_factory=lambda: _float("SANDBOX_ULTRA_TIMEOUT", 3600))

    # --- панель управления (сайт) ---
    # Оба пароля задаются ТОЛЬКО в .env на сервере. Пока хоть один пустой — панель выключена.
    panel_password_1: str = field(default_factory=lambda: _str("PANEL_PASSWORD_1"))
    panel_password_2: str = field(default_factory=lambda: _str("PANEL_PASSWORD_2"))
    # С каких сайтов можно открывать панель (GitHub Pages). Свой адрес бота (/panel/) разрешён всегда.
    panel_origins: list[str] = field(default_factory=lambda: _list("PANEL_ORIGINS") or ["https://a1x10.github.io"])
    panel_public_url: str = field(default_factory=lambda: _str("PANEL_PUBLIC_URL", "https://a1x10.github.io/project3/"))
    panel_session_hours: float = field(default_factory=lambda: _float("PANEL_SESSION_HOURS", 8))
    panel_idle_minutes: float = field(default_factory=lambda: _float("PANEL_IDLE_MINUTES", 30))
    # Cloudflare-туннель (docker compose --profile panel): бот сам узнаёт его адрес и присылает владельцу ссылку
    tunnel_metrics_url: str = field(default_factory=lambda: _str("TUNNEL_METRICS_URL", "http://tunnel:2000"))

    # --- розыгрыш: страница /giveaway/, админка по ссылке от Стеллы на «/розыгрыш», рассылка в личку Telegram ---
    giveaway_enabled: bool = field(default_factory=lambda: _bool("GIVEAWAY_ENABLED", True))
    # свой домен (https://…); пусто — адрес туннеля Cloudflare
    giveaway_public_url: str = field(default_factory=lambda: _str("GIVEAWAY_PUBLIC_URL"))
    giveaway_title: str = field(default_factory=lambda: _str("GIVEAWAY_TITLE", "Розыгрыш"))
    giveaway_prize: str = field(default_factory=lambda: _str("GIVEAWAY_PRIZE", "Безлимитный ИИ на 35 дней"))
    # письмо победителю прямо из админки (необязательно: без этого — кнопка «Открыть в почте»)
    giveaway_smtp_host: str = field(default_factory=lambda: _str("GIVEAWAY_SMTP_HOST"))
    giveaway_smtp_port: int = field(default_factory=lambda: _int("GIVEAWAY_SMTP_PORT", 465))
    giveaway_smtp_user: str = field(default_factory=lambda: _str("GIVEAWAY_SMTP_USER"))
    giveaway_smtp_pass: str = field(default_factory=lambda: _str("GIVEAWAY_SMTP_PASS"))
    giveaway_smtp_from: str = field(default_factory=lambda: _str("GIVEAWAY_SMTP_FROM"))

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
    # school — школьные чаты подростков (сленг, бережные правила); none — без этого блока
    audience: str = field(default_factory=lambda: _str("BOT_AUDIENCE", "school"))
    # minimal — просто ИИ-ассистент с короткой базовой инструкцией; full — подробный характер и правила
    prompt_style: str = field(default_factory=lambda: _str("PROMPT_STYLE", "minimal"))

    # --- люди ---
    owner_phone: str = field(default_factory=lambda: _digits(_str("OWNER_PHONE")))
    admin_phones: list[str] = field(default_factory=lambda: [_digits(x) for x in _list("ADMIN_PHONES")])
    allow_dms: bool = field(default_factory=lambda: _bool("ALLOW_DMS", True))
    # Режим друзей: всё, что было только у владельца и админов (запуск кода, без дневных лимитов, управление
    # группой, профиль Стеллы), — и тем, кто состоит в одной группе с владельцем или админом бота. Чужие (нашли
    # бота в Telegram по @username, добавили в свою группу) — как раньше: дневной бюджет и лимиты для всех
    friends_mode: bool = field(default_factory=lambda: _bool("FRIENDS_MODE", False))
    allowed_groups: list[str] = field(default_factory=lambda: _list("ALLOWED_GROUPS"))
    # Telegram — та же Стелла, рядом с WhatsApp: токен от @BotFather; пусто — Telegram выключен
    telegram_bot_token: str = field(default_factory=lambda: _str("TELEGRAM_BOT_TOKEN"))
    telegram_owner_id: str = field(default_factory=lambda: _str("TELEGRAM_OWNER_ID"))  # твой id (@userinfobot)
    # какие группы Telegram (id вида -100…); пусто — любые, куда добавили бота
    telegram_allowed_chats: list[str] = field(default_factory=lambda: _list("TELEGRAM_ALLOWED_CHATS"))
    # бота в Telegram может найти кто угодно по @username: в личке у каждого (кроме владельца) — лимит в сутки
    telegram_dm_per_day: int = field(default_factory=lambda: _int("TELEGRAM_DM_PER_DAY", 0))

    # --- подписки (выдаются в панели: «Люди» → человек → «Подписка») ---
    # сколько ответов в сутки Стелла даёт человеку без подписки; 0 — без лимита (владельцу и админам — всегда)
    free_replies_per_day: int = field(default_factory=lambda: _int("FREE_REPLIES_PER_DAY", 0))
    # что она пишет, когда лимит кончился; {support} — контакт техподдержки, {limit} — сколько было можно
    limit_message: str = field(default_factory=lambda: _str("LIMIT_MESSAGE") or DEFAULT_LIMIT_MESSAGE)
    support_contact: str = field(default_factory=lambda: _str("SUPPORT_CONTACT"))  # @username, ссылка или номер

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
    # сообщения старше этого (пришли пачкой после переподключения) — только в историю, без ответа
    reply_stale_minutes: float = field(default_factory=lambda: _float("REPLY_STALE_MINUTES", 30))
    # если к ней обратились сразу несколько человек — отвечает каждому отдельно (не больше стольких за раз)
    reply_each_max: int = field(default_factory=lambda: _int("REPLY_EACH_MAX", 5))

    # --- сама пишет в группы ---
    initiative_per_week: float = field(default_factory=lambda: _float("INITIATIVE_PER_WEEK", 2))
    initiative_hours: str = field(default_factory=lambda: _str("INITIATIVE_HOURS", "10-22"))
    initiative_min_gap_hours: float = field(default_factory=lambda: _float("INITIATIVE_MIN_GAP_HOURS", 36))
    initiative_quiet_minutes: float = field(default_factory=lambda: _float("INITIATIVE_QUIET_MINUTES", 60))
    initiative_open_minutes: float = field(default_factory=lambda: _float("INITIATIVE_OPEN_MINUTES", 30))

    # --- память ---
    memory_extract_every: int = field(default_factory=lambda: _int("MEMORY_EXTRACT_EVERY", 15))
    memory_facts_in_prompt: int = field(default_factory=lambda: _int("MEMORY_FACTS_IN_PROMPT", 15))
    memory_people_in_prompt: int = field(default_factory=lambda: _int("MEMORY_PEOPLE_IN_PROMPT", 20))
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
            kind, model = self.llm_backend_after, self.llm_model_after
        else:
            kind, model = self.llm_backend, self.llm_model
        if kind not in ANTHROPIC_BACKENDS and kind != "off":  # Groq и др. — своя модель
            model = self.alt_model
        return kind, model

    def model_off(self, today: date | None = None) -> bool:
        """Модель выключена (LLM_BACKEND_AFTER=off после LLM_SWITCH_AT): к Anthropic не ходим вообще — ни чат,
        ни память, ни страницы, ни песочница, — чтобы не тратить свой баланс."""
        return self.backend_for(today or self.local_today())[0] == "off"

    def anthropic_off(self, today: date | None = None) -> bool:
        """Сейчас не Anthropic (выключено или Groq и т. п.): страницы и песочница — только Anthropic, их не зовём."""
        return self.backend_for(today or self.local_today())[0] not in ANTHROPIC_BACKENDS

    def local_today(self) -> date:
        """Сегодня по часам владельца (TIMEZONE), а не сервера (в Docker — UTC): смена в его полночь."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        try:
            return datetime.now(ZoneInfo(self.timezone)).date()
        except Exception:
            return date.today()

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

    def is_owner(self, phone: str | None) -> bool:
        """Владелец: номер OWNER_PHONE в WhatsApp или TELEGRAM_OWNER_ID в Telegram («tg<id>», см. util.phone_of)."""
        if not phone:
            return False
        tg = self.telegram_owner_id.strip()
        return phone == self.owner_phone or bool(tg) and phone == f"tg{tg}"

    def is_admin(self, phone: str | None) -> bool:
        if not phone:
            return False
        return self.is_owner(phone) or phone in self.admin_phones


settings = Settings()
