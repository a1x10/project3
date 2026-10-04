from __future__ import annotations

import asyncio
import time

import pytest
from conftest import FakeNotifier

from agent import AIError, Diagnosis, FilePatch
from git_patch import ApplyResult
from monitor import Busy, Monitor, State
from system import HealthResult

OK = HealthResult(True, "HTTP 200")
DOWN = HealthResult(False, "ConnectError: connection refused")


class FakeApp:
    def __init__(self, health=(), restarts=()):
        self.health = list(health)
        self.restarts = list(restarts)
        self.restart_calls = 0

    async def check_health(self):
        return self.health.pop(0) if len(self.health) > 1 else self.health[0]

    async def restart(self):
        self.restart_calls += 1
        return self.restarts.pop(0) if len(self.restarts) > 1 else self.restarts[0]

    async def recent_logs(self, lines):
        return "Traceback ... NameError"

    def adopt_previous(self):
        return None

    def describe(self):
        return "fake"

    def probe_description(self):
        return "fake"

    async def close(self):
        pass


class FakeAgent:
    label = "fake · model"

    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    async def analyze(self, *, logs, reason):
        self.calls += 1
        if self.error:
            raise self.error
        patch = FilePatch("app.py", None, "a", "b")
        return Diagnosis("fix1", "Опечатка", "NameError", "high", "", [], [patch], [], "fake-model")


class FakePatcher:
    def __init__(self, result):
        self.result = result
        self.applied = []

    async def apply(self, diag):
        self.applied.append(diag)
        return self.result


def make_monitor(make_settings, tmp_path, app, agent=None, patcher=None, **env):
    settings = make_settings(tmp_path, APP_RESTART_CMD="true", HEALTH_CMD="true", **env)
    notifier = FakeNotifier()
    monitor = Monitor(settings, app, agent, patcher or FakePatcher(ApplyResult(ok=True, healthy=True)), notifier)
    return monitor, notifier


def run(coro):
    return asyncio.run(coro)


def test_single_failure_is_not_an_incident_and_restart_fixes(make_settings, tmp_path):
    app = FakeApp(health=[DOWN, DOWN], restarts=[OK])
    monitor, notifier = make_monitor(make_settings, tmp_path, app)

    async def scenario():
        await monitor.check_once()
        assert app.restart_calls == 0 and notifier.messages == []  # FAILURE_THRESHOLD=2
        await monitor.check_once()

    run(scenario())
    assert app.restart_calls == 1 and monitor.state == State.UP
    texts = notifier.texts()
    assert "Приложение недоступно" in texts and "connection refused" in texts and "Поднял" in texts


def test_failed_restarts_escalate_to_ai_then_recovery_is_reported(make_settings, tmp_path):
    app = FakeApp(health=[DOWN, DOWN, DOWN, OK], restarts=[DOWN])
    agent = FakeAgent()
    monitor, notifier = make_monitor(make_settings, tmp_path, app, agent, REMINDER_INTERVAL="0")

    async def scenario():
        await monitor.check_once()
        await monitor.check_once()  # инцидент: 2 рестарта, оба неудачные → ИИ
        assert monitor.state == State.FAILED
        await monitor.check_once()  # всё ещё лежит: каскад заново не запускаем
        await monitor.check_once()  # поднялось само (например, починили руками)

    run(scenario())
    assert app.restart_calls == 2  # RESTART_ATTEMPTS
    assert agent.calls == 1 and len(notifier.diagnoses) == 1
    assert monitor.take_fix("fix1") is not None and monitor.take_fix("fix1") is None
    assert monitor.state == State.UP and "снова отвечает" in notifier.messages[-1][0]


def test_reminder_while_down(make_settings, tmp_path):
    app = FakeApp(health=[DOWN], restarts=[DOWN])
    monitor, notifier = make_monitor(make_settings, tmp_path, app, REMINDER_INTERVAL="60")

    async def scenario():
        await monitor.check_once()
        await monitor.check_once()
        before = len(notifier.messages)
        await monitor.check_once()
        assert len(notifier.messages) == before  # рано напоминать
        monitor._last_reminder = time.time() - 61
        await monitor.check_once()
        return before

    before = run(scenario())
    assert len(notifier.messages) == before + 1 and "всё ещё недоступно" in notifier.messages[-1][0]
    assert notifier.messages[-1][1] == ("restart", "logs", "debug")


def test_crash_loop_stops_auto_restarts(make_settings, tmp_path):
    app = FakeApp(health=[DOWN], restarts=[OK])
    monitor, notifier = make_monitor(make_settings, tmp_path, app, FakeAgent(), FAILURE_THRESHOLD="1")
    now = time.time()
    monitor._auto_restarts.extend([now - 30, now - 20, now - 10])

    run(monitor.check_once())
    assert app.restart_calls == 0
    assert "падает снова и снова" in notifier.texts()
    assert len(notifier.diagnoses) == 1 and monitor.state == State.FAILED


def test_ai_error_is_reported_with_buttons(make_settings, tmp_path):
    app = FakeApp(health=[DOWN], restarts=[DOWN])
    agent = FakeAgent(error=AIError("нет ключа"))
    monitor, notifier = make_monitor(make_settings, tmp_path, app, agent, FAILURE_THRESHOLD="1")

    run(monitor.check_once())
    text, actions = notifier.messages[-1]
    assert "ИИ-анализ не удался: нет ключа" in text and "restart" in actions


def test_without_ai_asks_for_manual_help(make_settings, tmp_path):
    app = FakeApp(health=[DOWN], restarts=[DOWN])
    monitor, notifier = make_monitor(make_settings, tmp_path, app, agent=None, FAILURE_THRESHOLD="1")
    run(monitor.check_once())
    assert "нужна ручная помощь" in notifier.messages[-1][0]


def test_pause_skips_checks(make_settings, tmp_path):
    app = FakeApp(health=[DOWN], restarts=[OK])
    monitor, notifier = make_monitor(make_settings, tmp_path, app, FAILURE_THRESHOLD="1")
    monitor.pause()
    run(monitor.check_once())
    assert app.restart_calls == 0 and monitor.last_health is None
    monitor.resume()
    run(monitor.check_once())
    assert app.restart_calls == 1


def test_manual_restart_is_rejected_while_busy(make_settings, tmp_path):
    app = FakeApp(health=[OK], restarts=[OK])
    monitor, _ = make_monitor(make_settings, tmp_path, app)

    async def scenario():
        async with monitor._op_lock:
            with pytest.raises(Busy):
                await monitor.manual_restart()
        return await monitor.manual_restart()

    assert run(scenario()).ok and monitor.state == State.UP


def test_apply_fix_updates_state(make_settings, tmp_path):
    app = FakeApp(health=[DOWN], restarts=[DOWN])
    patcher = FakePatcher(ApplyResult(ok=False, healthy=False))
    monitor, _ = make_monitor(make_settings, tmp_path, app, FakeAgent(), patcher)

    async def scenario():
        diag = await monitor.diagnose("HTTP 502")
        result = await monitor.apply_fix(monitor.take_fix(diag.id))
        assert not result.ok and monitor.state == State.FAILED
        patcher.result = ApplyResult(ok=True, healthy=True)
        await monitor.apply_fix(diag)

    run(scenario())
    assert len(patcher.applied) == 2 and monitor.state == State.UP
