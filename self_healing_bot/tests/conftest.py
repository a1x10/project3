from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))

from config import load_settings  # noqa: E402

DEMO_APP = BOT_DIR / "demo_app" / "server.py"

ENV_KEYS = [
    "TELEGRAM_BOT_TOKEN", "BOT_TOKEN", "ADMIN_IDS", "ALERT_CHAT_ID", "APP_DIR", "APP_START_CMD", "APP_RESTART_CMD",
    "APP_LOG_FILE", "APP_LOGS_CMD", "APP_PORT", "APP_PID_FILE", "HEALTH_URL", "HEALTH_CMD", "HEALTH_TIMEOUT",
    "STARTUP_TIMEOUT", "CHECK_INTERVAL", "FAILURE_THRESHOLD", "RESTART_ATTEMPTS", "CRASH_LOOP_MAX",
    "CRASH_LOOP_WINDOW", "REMINDER_INTERVAL", "AI_PROVIDER", "AI_API_KEY", "AI_MODEL", "AI_BASE_URL", "AI_EFFORT",
    "AI_LOG_LINES", "AI_MAX_FILES", "AI_MAX_FILE_CHARS", "AI_EXTRA_FILES", "GIT_ENABLED", "GIT_PUSH", "GIT_REMOTE",
    "FIX_CHECK_CMD", "SHELL_ENABLED", "SHELL_TIMEOUT", "OPENAI_API_KEY",
]


@pytest.fixture
def make_settings(tmp_path, monkeypatch):
    """Собирает Settings из переменных окружения, как в реальном запуске (но без файла .env)."""

    def factory(app_dir: Path, **env):
        for key in ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        values = {
            "TELEGRAM_BOT_TOKEN": "42:TEST-TOKEN",
            "ADMIN_IDS": "1001",
            "APP_DIR": str(app_dir),
            "APP_LOG_FILE": str(tmp_path / "app.log"),
            "APP_PID_FILE": str(tmp_path / "app.pid"),
            "AI_PROVIDER": "none",
            "STARTUP_TIMEOUT": "10",
        }
        values.update({key: str(value) for key, value in env.items()})
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        return load_settings(env_file=tmp_path / "missing.env")

    return factory


def free_tcp_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def init_git_repo(path: Path) -> None:
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "dev@example.com")
    git(path, "config", "user.name", "Dev")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "initial")


class FakeNotifier:
    def __init__(self):
        self.messages: list[tuple[str, tuple[str, ...]]] = []
        self.diagnoses = []

    async def send(self, text, actions=(), chat_id=None):
        self.messages.append((text, tuple(actions)))

    async def send_diagnosis(self, diag, chat_id=None):
        self.diagnoses.append(diag)

    def texts(self) -> str:
        return "\n---\n".join(text for text, _ in self.messages)


class FakeProvider:
    """Подменяет LLM: возвращает заранее заданный ответ и запоминает промпты."""

    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, system, user):
        self.calls.append((system, user))
        data = self.response(user) if callable(self.response) else self.response
        return data, "fake-model"
