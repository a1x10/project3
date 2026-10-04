"""Мониторинг и каскад восстановления: health-check → рестарт → ИИ-дебаг → фикс по кнопке."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Sequence
from typing import Protocol

from agent import AIError, Agent, Diagnosis
from config import Settings
from git_patch import ApplyResult, Patcher
from system import AppController, HealthResult
from telegram_ui import esc, fmt_duration

log = logging.getLogger(__name__)

FIX_TTL = 24 * 3600  # сколько живёт кнопка «Применить фикс»
MAX_PENDING_FIXES = 20


class Notifier(Protocol):
    async def send(self, text: str, actions: Sequence[str] = (), chat_id: int | None = None) -> None: ...

    async def send_diagnosis(self, diag: Diagnosis, chat_id: int | None = None) -> None: ...


class State:
    UNKNOWN = "unknown"
    UP = "up"
    RECOVERING = "recovering"
    FAILED = "failed"  # автоматически поднять не вышло, ждём человека


class Busy(Exception):
    """Уже идёт другая операция (рестарт, применение фикса или ИИ-анализ)."""


class Monitor:
    def __init__(
        self,
        settings: Settings,
        app: AppController,
        agent: Agent | None,
        patcher: Patcher,
        notifier: Notifier,
    ) -> None:
        self.s = settings
        self.app = app
        self.agent = agent
        self.patcher = patcher
        self.notifier = notifier

        self.state = State.UNKNOWN
        self.paused = False
        self.last_health: HealthResult | None = None
        self.last_check_at: float | None = None
        self.down_since: float | None = None
        self.failures = 0
        self.started_at = time.time()

        self._auto_restarts: deque[float] = deque(maxlen=100)
        self._fixes: dict[str, Diagnosis] = {}
        self._op_lock = asyncio.Lock()  # рестарты и патчи — строго по одному
        self._ai_lock = asyncio.Lock()
        self._last_reminder = 0.0
        self._task: asyncio.Task[None] | None = None

    @property
    def busy(self) -> bool:
        return self._op_lock.locked()

    @property
    def ai_busy(self) -> bool:
        return self._ai_lock.locked()

    # ---------- Жизненный цикл ----------

    async def start(self) -> None:
        # Ссылку на задачу храним, иначе сборщик мусора может её прибить
        self._task = asyncio.create_task(self._run(), name="monitor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.app.close()

    async def _run(self) -> None:
        try:
            await self._bootstrap()
        except Exception:
            log.exception("Ошибка при старте мониторинга")
        while True:
            await asyncio.sleep(self.s.check_interval)
            try:
                await self.check_once()
            except Exception:  # одна неудачная проверка не должна убивать мониторинг
                log.exception("Ошибка в цикле мониторинга")

    async def _bootstrap(self) -> None:
        adopted = self.app.adopt_previous()
        health = await self.app.check_health()
        started = False
        if not health.ok and self.s.managed:
            async with self._op_lock:
                health = await self.app.restart()
            started = True
        self._record(health)
        if health.ok:
            self._mark_up()

        if adopted:
            how = f"подхватил запущенное ранее (PID {adopted})"
        elif started:
            how = "запустил приложение"
        else:
            how = "приложение уже работало"
        ai = self.agent.label if self.agent else "выключен"
        await self.notifier.send(
            "🤖 <b>Self-Healing Bot запущен</b>\n"
            f"Приложение: <code>{esc(self.app.describe())}</code>\n"
            f"Проверка: <code>{esc(self.app.probe_description())}</code> каждые {self.s.check_interval:g} с\n"
            f"ИИ: {esc(ai)}\n"
            f"{'✅' if health.ok else '❌'} {esc(how)}: {esc(health.detail)}"
        )

    # ---------- Мониторинг ----------

    async def check_once(self) -> None:
        if self.paused or self.busy:
            return
        health = await self.app.check_health()
        self._record(health)
        if health.ok:
            if self.state == State.FAILED and self.down_since:
                await self.notifier.send(
                    f"✅ Приложение снова отвечает (простой {fmt_duration(time.time() - self.down_since)}).\n"
                    f"{esc(health.detail)}"
                )
            self._mark_up()
            return

        self.failures += 1
        if self.failures < self.s.failure_threshold:
            return  # одиночный сбой — ещё не авария
        if self.state == State.FAILED:
            await self._maybe_remind(health)
            return
        await self.recover(health.detail)

    async def recover(self, reason: str) -> None:
        if self._op_lock.locked():
            return
        async with self._op_lock:
            self.state = State.RECOVERING
            self.down_since = self.down_since or time.time()
            if self._crash_loop():
                await self.notifier.send(
                    f"🔁 <b>Приложение падает снова и снова</b>: {self.s.crash_loop_max} перезапуска(ов) "
                    f"за {fmt_duration(self.s.crash_loop_window)}. Автоперезапуск остановлен.\n"
                    f"Последняя ошибка: <code>{esc(reason)}</code>"
                )
                error = reason
            else:
                await self.notifier.send(
                    f"🚨 <b>Приложение недоступно</b>\nОшибка: <code>{esc(reason)}</code>\n\n🔄 Перезапускаю…"
                )
                result = await self._restart_with_retries()
                if result.ok:
                    self._record(result)
                    self._mark_up()
                    await self.notifier.send(f"✅ Поднял простым перезапуском.\n{esc(result.detail)}")
                    return
                error = result.detail
            self.state = State.FAILED
            self._last_reminder = time.time()
        # ИИ думает вне блокировки: пока он работает, /restart и /cmd остаются доступны
        await self._escalate(error)

    async def _restart_with_retries(self) -> HealthResult:
        result = HealthResult(False, "перезапуск не выполнялся")
        for attempt in range(1, self.s.restart_attempts + 1):
            self._auto_restarts.append(time.time())
            result = await self.app.restart()
            if result.ok:
                return result
            log.warning("Перезапуск %d/%d не помог: %s", attempt, self.s.restart_attempts, result.detail)
        return result

    def _crash_loop(self) -> bool:
        if self.s.crash_loop_max <= 0:
            return False
        since = time.time() - self.s.crash_loop_window
        return sum(1 for t in self._auto_restarts if t >= since) >= self.s.crash_loop_max

    async def _escalate(self, error: str) -> None:
        if self.agent is None:
            await self.notifier.send(
                "🛠 Автоматически поднять не получилось — нужна ручная помощь.\n"
                f"Последняя ошибка: <code>{esc(error)}</code>",
                actions=("restart", "logs"),
            )
            return
        await self.notifier.send("🧠 Перезапуск не помог. Отправляю логи и код ИИ на анализ…")
        try:
            diag = await self.diagnose(error)
        except Busy:
            return
        except AIError as e:
            await self.notifier.send(
                f"⚠️ ИИ-анализ не удался: {esc(e)}\nПоследняя ошибка: <code>{esc(error)}</code>",
                actions=("logs", "debug", "restart"),
            )
            return
        await self.notifier.send_diagnosis(diag)

    async def _maybe_remind(self, health: HealthResult) -> None:
        if self.s.reminder_interval <= 0 or time.time() - self._last_reminder < self.s.reminder_interval:
            return
        self._last_reminder = time.time()
        down = fmt_duration(time.time() - (self.down_since or time.time()))
        await self.notifier.send(
            f"⏰ Приложение всё ещё недоступно ({down}).\nОшибка: <code>{esc(health.detail)}</code>",
            actions=("restart", "logs", "debug"),
        )

    # ---------- Действия по командам ----------

    async def diagnose(self, reason: str) -> Diagnosis:
        if self.agent is None:
            raise AIError("ИИ выключен (AI_PROVIDER=none)")
        if self._ai_lock.locked():
            raise Busy("ИИ-анализ уже идёт")
        async with self._ai_lock:
            logs = await self.app.recent_logs(self.s.ai_log_lines)
            diag = await self.agent.analyze(logs=logs, reason=reason)
            self._remember_fix(diag)
            return diag

    async def manual_restart(self) -> HealthResult:
        if self._op_lock.locked():
            raise Busy("уже идёт перезапуск или применение фикса")
        async with self._op_lock:
            result = await self.app.restart()
            self._record(result)
            if result.ok:
                self._mark_up()
            else:
                self.state = State.FAILED
                self.down_since = self.down_since or time.time()
                self._last_reminder = time.time()
            return result

    def take_fix(self, fix_id: str) -> Diagnosis | None:
        diag = self._fixes.pop(fix_id, None)
        if diag is None or time.time() - diag.created_at > FIX_TTL:
            return None
        return diag

    async def apply_fix(self, diag: Diagnosis) -> ApplyResult:
        async with self._op_lock:
            result = await self.patcher.apply(diag)
            if result.healthy:
                self._mark_up()
            elif self.state != State.FAILED:
                self.state = State.FAILED
                self.down_since = self.down_since or time.time()
                self._last_reminder = time.time()
            return result

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False
        self.failures = 0

    # ---------- Внутреннее ----------

    def _record(self, health: HealthResult) -> None:
        self.last_health = health
        self.last_check_at = time.time()

    def _mark_up(self) -> None:
        self.state = State.UP
        self.failures = 0
        self.down_since = None

    def _remember_fix(self, diag: Diagnosis) -> None:
        now = time.time()
        for fix_id, old in list(self._fixes.items()):
            if now - old.created_at > FIX_TTL:
                del self._fixes[fix_id]
        if not diag.can_apply:
            return
        while len(self._fixes) >= MAX_PENDING_FIXES:
            self._fixes.pop(next(iter(self._fixes)))
        self._fixes[diag.id] = diag
