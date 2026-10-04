"""Сквозной сценарий на настоящем процессе и git: упал → рестарт не помог → ИИ → «Применить» → работает."""

from __future__ import annotations

import asyncio
import sys

from conftest import DEMO_APP, FakeNotifier, FakeProvider, free_tcp_port, git, init_git_repo

from agent import Agent
from git_patch import Patcher
from monitor import Monitor, State
from system import AppController

BROKEN = "config = load_confg()"
FIXED = "config = load_config()"


def test_full_self_healing_cycle(make_settings, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "server.py").write_text(DEMO_APP.read_text())
    init_git_repo(repo)
    port = free_tcp_port()
    settings = make_settings(
        repo,
        APP_START_CMD=f"PORT={port} {sys.executable} server.py",
        HEALTH_URL=f"http://127.0.0.1:{port}/health",
        HEALTH_TIMEOUT="2",
        STARTUP_TIMEOUT="8",
        FAILURE_THRESHOLD="1",
        RESTART_ATTEMPTS="1",
    )

    def answer(prompt: str) -> dict:
        # «ИИ» видит трейсбек из логов и сам файл — и предлагает исправить опечатку
        assert "NameError: name 'load_confg' is not defined" in prompt
        assert '<file path="server.py">' in prompt
        return {
            "summary": "Опечатка в имени функции load_config",
            "root_cause": "Вызывается несуществующая функция load_confg",
            "confidence": "high",
            "edits": [{"file": "server.py", "search": BROKEN, "replace": FIXED}],
            "commands": [],
            "notes": "",
        }

    provider = FakeProvider(answer)
    app = AppController(settings)
    notifier = FakeNotifier()
    monitor = Monitor(settings, app, Agent(settings, provider=provider), Patcher(settings, app), notifier)

    async def scenario():
        try:
            await monitor._bootstrap()  # бот запускает приложение
            assert monitor.state == State.UP

            # Кто-то задеплоил опечатку, и процесс упал
            (repo / "server.py").write_text(DEMO_APP.read_text().replace(FIXED, BROKEN))
            git(repo, "commit", "-qam", "broken deploy")
            await app.stop()

            await monitor.check_once()  # алерт → рестарт (падает на старте) → ИИ
            assert monitor.state == State.FAILED
            assert len(notifier.diagnoses) == 1
            diag = notifier.diagnoses[0]
            assert diag.can_apply

            # Админ нажал «✅ Применить фикс»
            result = await monitor.apply_fix(monitor.take_fix(diag.id))
            assert result.ok, result.steps
            assert monitor.state == State.UP
            assert (await app.check_health()).ok
            return result
        finally:
            await app.stop()
            await app.close()

    result = asyncio.run(scenario())
    texts = notifier.texts()
    assert "Приложение недоступно" in texts and "Отправляю логи и код ИИ" in texts
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == result.branch
    assert FIXED in (repo / "server.py").read_text()
    assert len(provider.calls) == 1
