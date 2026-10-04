"""Настройки бота. Всё читается из переменных окружения или из файла .env рядом с main.py."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-4o-mini",
}
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

log = logging.getLogger(__name__)


class ConfigError(Exception):
    """Ошибка в настройках: бот не может стартовать."""


def _str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _int(name: str, default: int) -> int:
    raw = _str(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} должно быть целым числом, сейчас: {raw!r}") from None


def _float(name: str, default: float) -> float:
    raw = _str(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} должно быть числом, сейчас: {raw!r}") from None


def _bool(name: str, default: bool) -> bool:
    raw = _str(name)
    if raw is None:
        return default
    if raw.lower() in ("1", "true", "yes", "on", "да"):
        return True
    if raw.lower() in ("0", "false", "no", "off", "нет"):
        return False
    raise ConfigError(f"{name} должно быть true или false, сейчас: {raw!r}")


def _int_list(name: str) -> tuple[int, ...]:
    ids = []
    for part in (_str(name) or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            raise ConfigError(f"{name}: {part!r} — не числовой Telegram ID") from None
    return tuple(ids)


def _path(name: str, base: Path, default: Path | None = None) -> Path | None:
    raw = _str(name)
    if raw is None:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (base / path)


@dataclass(frozen=True)
class Settings:
    # Telegram
    bot_token: str
    admin_ids: frozenset[int]
    alert_chat_id: int

    # Целевое приложение
    app_dir: Path
    start_cmd: str | None  # режим «бот сам держит процесс» (npm start, python3 app.py…)
    restart_cmd: str | None  # режим «процессом управляет pm2/systemd/docker»
    log_file: Path | None
    logs_cmd: str | None
    app_port: int | None
    app_port_explicit: bool  # False — порт угадан по HEALTH_URL
    health_url: str | None
    health_cmd: str | None
    health_timeout: float
    startup_timeout: float
    pid_file: Path

    # Мониторинг
    check_interval: float
    failure_threshold: int
    restart_attempts: int
    crash_loop_max: int
    crash_loop_window: float
    reminder_interval: float

    # ИИ
    ai_provider: str  # anthropic | openai | none
    ai_api_key: str | None
    ai_model: str
    ai_base_url: str | None
    ai_effort: str | None
    ai_log_lines: int
    ai_max_files: int
    ai_max_file_chars: int
    ai_extra_files: tuple[str, ...]

    # Патчи и git
    git_enabled: bool
    git_push: bool
    git_remote: str
    fix_check_cmd: str | None

    # Консоль /cmd
    shell_enabled: bool
    shell_timeout: float

    @property
    def managed(self) -> bool:
        """True — бот сам запускает приложение (APP_START_CMD), False — им управляет внешний менеджер."""
        return self.start_cmd is not None

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider != "none"

    @property
    def has_probe(self) -> bool:
        """Есть ли явная проверка здоровья (URL или команда), а не только «процесс жив»."""
        return bool(self.health_url or self.health_cmd)


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or BASE_DIR / ".env", override=False)

    token = _str("TELEGRAM_BOT_TOKEN") or _str("BOT_TOKEN")
    if not token:
        raise ConfigError("Не задан TELEGRAM_BOT_TOKEN (токен от @BotFather)")

    admin_ids = _int_list("ADMIN_IDS")
    if not admin_ids:
        raise ConfigError(
            "Не задан ADMIN_IDS. Без него любой человек мог бы управлять сервером через бота. "
            "Узнать свой ID: напиши боту /start — он ответит"
        )

    app_dir = _path("APP_DIR", BASE_DIR)
    if app_dir is None:
        raise ConfigError("Не задан APP_DIR — папка проекта, за которым следит бот")
    app_dir = app_dir.resolve()
    if not app_dir.is_dir():
        raise ConfigError(f"APP_DIR={app_dir} не существует или это не папка")

    start_cmd = _str("APP_START_CMD")
    restart_cmd = _str("APP_RESTART_CMD")
    if bool(start_cmd) == bool(restart_cmd):
        raise ConfigError(
            "Укажи ровно одно из двух: APP_START_CMD (бот сам запускает приложение, например `npm start`) "
            "или APP_RESTART_CMD (приложением управляет pm2/systemd/docker, например `pm2 restart app`)"
        )

    health_url = _str("HEALTH_URL")
    health_cmd = _str("HEALTH_CMD")
    if health_url:
        parsed = urlparse(health_url)
        if parsed.scheme not in ("http", "https", "tcp") or not parsed.hostname:
            raise ConfigError(f"HEALTH_URL должен быть http(s)://… или tcp://host:port, сейчас: {health_url!r}")
        if parsed.scheme == "tcp" and not parsed.port:
            raise ConfigError("Для HEALTH_URL вида tcp:// нужен порт, например tcp://127.0.0.1:5432")
    if restart_cmd and not (health_url or health_cmd):
        raise ConfigError("С APP_RESTART_CMD нужен HEALTH_URL или HEALTH_CMD — иначе непонятно, живо ли приложение")

    app_port = _int("APP_PORT", 0) or None
    app_port_explicit = app_port is not None
    if app_port is None and start_cmd and health_url:
        # Порт локального приложения берём из HEALTH_URL: его освобождаем перед рестартом
        parsed = urlparse(health_url)
        if parsed.hostname in LOCAL_HOSTS and parsed.port:
            app_port = parsed.port

    log_file = _path("APP_LOG_FILE", app_dir)
    logs_cmd = _str("APP_LOGS_CMD")
    if start_cmd and log_file is None:
        log_file = DATA_DIR / "app.log"

    provider = (_str("AI_PROVIDER") or "anthropic").lower()
    if provider not in ("anthropic", "openai", "none"):
        raise ConfigError(f"AI_PROVIDER должен быть anthropic, openai или none, сейчас: {provider!r}")
    api_key = _str("AI_API_KEY")
    if provider == "openai":
        api_key = api_key or _str("OPENAI_API_KEY")
    if provider == "anthropic" and not (api_key or _str("ANTHROPIC_API_KEY") or _str("ANTHROPIC_AUTH_TOKEN")):
        log.warning("Не найден ключ Anthropic (AI_API_KEY / ANTHROPIC_API_KEY): ИИ-анализ, скорее всего, не сработает")

    effort = (_str("AI_EFFORT") or ("high" if provider == "anthropic" else "")).lower() or None
    if effort == "none":
        effort = None
    if effort and effort not in EFFORT_LEVELS:
        raise ConfigError(f"AI_EFFORT должен быть одним из {', '.join(EFFORT_LEVELS)} или none")

    alert_chat_id = _int("ALERT_CHAT_ID", admin_ids[0])

    return Settings(
        bot_token=token,
        admin_ids=frozenset(admin_ids),
        alert_chat_id=alert_chat_id,
        app_dir=app_dir,
        start_cmd=start_cmd,
        restart_cmd=restart_cmd,
        log_file=log_file,
        logs_cmd=logs_cmd,
        app_port=app_port,
        app_port_explicit=app_port_explicit,
        health_url=health_url,
        health_cmd=health_cmd,
        health_timeout=_float("HEALTH_TIMEOUT", 5.0),
        startup_timeout=_float("STARTUP_TIMEOUT", 30.0),
        pid_file=_path("APP_PID_FILE", BASE_DIR, DATA_DIR / "app.pid"),
        check_interval=_float("CHECK_INTERVAL", 15.0),
        failure_threshold=max(1, _int("FAILURE_THRESHOLD", 2)),
        restart_attempts=max(1, _int("RESTART_ATTEMPTS", 2)),
        crash_loop_max=_int("CRASH_LOOP_MAX", 3),
        crash_loop_window=_float("CRASH_LOOP_WINDOW", 600.0),
        reminder_interval=_float("REMINDER_INTERVAL", 1800.0),
        ai_provider=provider,
        ai_api_key=api_key,
        ai_model=_str("AI_MODEL") or DEFAULT_MODELS.get(provider, ""),
        ai_base_url=_str("AI_BASE_URL"),
        ai_effort=effort,
        ai_log_lines=_int("AI_LOG_LINES", 150),
        ai_max_files=_int("AI_MAX_FILES", 3),
        ai_max_file_chars=_int("AI_MAX_FILE_CHARS", 40_000),
        ai_extra_files=tuple(f.strip() for f in (_str("AI_EXTRA_FILES") or "").split(",") if f.strip()),
        git_enabled=_bool("GIT_ENABLED", True),
        git_push=_bool("GIT_PUSH", False),
        git_remote=_str("GIT_REMOTE", "origin"),
        fix_check_cmd=_str("FIX_CHECK_CMD"),
        shell_enabled=_bool("SHELL_ENABLED", True),
        shell_timeout=_float("SHELL_TIMEOUT", 120.0),
    )
