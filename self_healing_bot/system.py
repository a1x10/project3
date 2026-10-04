"""Управление целевым приложением: проверка здоровья, перезапуск, логи, статистика сервера."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import psutil

from config import LOCAL_HOSTS, Settings
from shell import kill_process_group, run_shell, strip_ansi

log = logging.getLogger(__name__)

STOP_TIMEOUT = 10.0  # сколько ждём мягкой остановки (SIGTERM), потом SIGKILL
POLL_INTERVAL = 1.0  # как часто проверяем здоровье, пока приложение поднимается
PROCESS_GRACE = 5.0  # без HEALTH_URL/HEALTH_CMD процесс должен прожить столько секунд, чтобы считаться живым
RESTART_CMD_TIMEOUT = 120.0
LOGS_CMD_TIMEOUT = 30.0
LOG_ROTATE_BYTES = 10 * 1024 * 1024


@dataclass
class HealthResult:
    ok: bool
    detail: str


class AppController:
    """Знает, как проверить, перезапустить приложение и достать его логи."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._proc: asyncio.subprocess.Process | None = None  # процесс, запущенный этим экземпляром бота
        self._adopted: psutil.Process | None = None  # процесс, запущенный прошлым экземпляром бота
        self._started_at: float | None = None  # time.time() запуска приложения
        self._http: httpx.AsyncClient | None = None

    def describe(self) -> str:
        if self.s.managed:
            return f"{self.s.start_cmd} (в {self.s.app_dir})"
        return f"через `{self.s.restart_cmd}`"

    def probe_description(self) -> str:
        if self.s.health_url:
            return self.s.health_url
        if self.s.health_cmd:
            return f"команда: {self.s.health_cmd}"
        return "процесс жив"

    def uptime(self) -> float | None:
        if self.s.managed and self._alive_pid() is None:
            return None
        return time.time() - self._started_at if self._started_at else None

    def pid(self) -> int | None:
        return self._alive_pid()

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ---------- Проверка здоровья ----------

    async def check_health(self) -> HealthResult:
        if self.s.health_url:
            url = urlparse(self.s.health_url)
            if url.scheme == "tcp":
                return await self._check_tcp(url.hostname or "127.0.0.1", url.port or 0)
            return await self._check_http()
        if self.s.health_cmd:
            result = await run_shell(self.s.health_cmd, cwd=self.s.app_dir, timeout=self.s.health_timeout)
            if result.ok:
                return HealthResult(True, "HEALTH_CMD вернула 0")
            reason = "таймаут" if result.timed_out else f"код {result.returncode}"
            tail = _last_line(result.output)
            return HealthResult(False, f"HEALTH_CMD: {reason}" + (f" — {tail}" if tail else ""))
        pid = self._alive_pid()
        if pid is not None:
            return HealthResult(True, f"процесс жив (PID {pid})")
        code = self._proc.returncode if self._proc is not None else None
        return HealthResult(False, "процесс не запущен" + (f" (код выхода {code})" if code is not None else ""))

    async def _check_http(self) -> HealthResult:
        if self._http is None:
            host = urlparse(self.s.health_url).hostname
            self._http = httpx.AsyncClient(
                timeout=self.s.health_timeout,
                follow_redirects=True,
                trust_env=host not in LOCAL_HOSTS,  # localhost не должен уходить в HTTP_PROXY
            )
        started = time.monotonic()
        try:
            response = await self._http.get(self.s.health_url)
        except httpx.TimeoutException:
            return HealthResult(False, f"нет ответа за {self.s.health_timeout:g} с")
        except httpx.HTTPError as e:  # ConnectError, RemoteProtocolError, ReadError…
            return HealthResult(False, f"{type(e).__name__}: {e}" if str(e) else type(e).__name__)
        ms = (time.monotonic() - started) * 1000
        if response.is_success:
            return HealthResult(True, f"HTTP {response.status_code} за {ms:.0f} мс")
        return HealthResult(False, f"HTTP {response.status_code} {response.reason_phrase}".strip())

    async def _check_tcp(self, host: str, port: int) -> HealthResult:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), self.s.health_timeout)
        except asyncio.TimeoutError:
            return HealthResult(False, f"TCP {host}:{port}: нет ответа за {self.s.health_timeout:g} с")
        except OSError as e:
            return HealthResult(False, f"TCP {host}:{port}: {e.strerror or e}")
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return HealthResult(True, f"TCP {host}:{port} принимает соединения")

    async def wait_until_healthy(self, timeout: float | None = None) -> HealthResult:
        """Ждёт, пока приложение поднимется. Если процесс упал при старте — сразу возвращает ошибку."""
        timeout = self.s.startup_timeout if timeout is None else timeout
        grace = min(PROCESS_GRACE, timeout)
        deadline = time.monotonic() + timeout
        while True:
            if self.s.managed and self._alive_pid() is None:
                code = self._proc.returncode if self._proc is not None else None
                return HealthResult(False, f"процесс завершился сразу после запуска (код выхода {code})")
            health = await self.check_health()
            if health.ok and (self.s.has_probe or (self.uptime() or 0) >= grace):
                return health
            if time.monotonic() >= deadline:
                if health.ok:  # процесс жив, но не продержался grace-период — такого почти не бывает
                    return health
                return HealthResult(False, f"не поднялось за {timeout:g} с: {health.detail}")
            await asyncio.sleep(POLL_INTERVAL)

    # ---------- Перезапуск ----------

    async def restart(self) -> HealthResult:
        """Перезапускает приложение и ждёт, пока оно ответит."""
        if self.s.managed:
            await self.stop()
            try:
                await self._start()
            except OSError as e:
                return HealthResult(False, f"не удалось запустить `{self.s.start_cmd}`: {e}")
        else:
            result = await run_shell(self.s.restart_cmd, cwd=self.s.app_dir, timeout=RESTART_CMD_TIMEOUT)
            if not result.ok:
                reason = "таймаут" if result.timed_out else f"код {result.returncode}"
                tail = _last_line(result.output)
                message = f"APP_RESTART_CMD завершилась с ошибкой ({reason})"
                return HealthResult(False, f"{message}: {tail}" if tail else message)
            self._started_at = time.time()
        return await self.wait_until_healthy()

    async def stop(self) -> None:
        """Останавливает приложение вместе со всеми дочерними процессами и освобождает порт."""
        if not self.s.managed:
            return
        pid = self._alive_pid()
        if pid is not None:
            # start_new_session=True: приложение — лидер своей группы процессов, гасим её целиком
            # (иначе `npm start` умрёт, а node останется держать порт — тот самый EADDRINUSE)
            pgid = pid if _pgid(pid) == pid else None
            self._signal(pid, pgid, signal.SIGTERM)
            if not await self._wait_exit(STOP_TIMEOUT):
                log.warning("Приложение не остановилось за %s с — SIGKILL", STOP_TIMEOUT)
                self._signal(pid, pgid, signal.SIGKILL)
                await self._wait_exit(5)
            if pgid is not None:
                kill_process_group(pgid)  # потомки, пережившие родителя
        elif self._proc is not None:
            kill_process_group(self._proc.pid)  # лидер группы уже умер, но его потомки могли остаться
        self._proc = None
        self._adopted = None
        self._started_at = None
        with contextlib.suppress(OSError):
            self.s.pid_file.unlink()
        if self.s.app_port:
            # Порт, угаданный по HEALTH_URL, может принадлежать чужому процессу (например, nginx):
            # тогда трогаем только процессы, запущенные из папки проекта
            inside = None if self.s.app_port_explicit else self.s.app_dir
            killed = await asyncio.to_thread(free_port, self.s.app_port, inside)
            if killed:
                log.warning("Порт %s держали процессы %s — завершены", self.s.app_port, killed)

    async def _start(self) -> None:
        log_file = self.s.log_file
        assert log_file is not None and self.s.start_cmd
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _rotate(log_file)
        with open(log_file, "ab") as fh:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fh.write(f"\n===== [self-healing-bot] {stamp} запуск: {self.s.start_cmd} =====\n".encode())
            fh.flush()
            self._proc = await asyncio.create_subprocess_shell(
                self.s.start_cmd,
                cwd=self.s.app_dir,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=fh,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,  # приложение переживёт рестарт бота и не получит его Ctrl+C
                env={**os.environ, "PYTHONUNBUFFERED": "1"},  # иначе print() из Python-приложения теряется при падении
            )
        self._adopted = None
        self._started_at = time.time()
        self._write_pid_file(self._proc.pid)
        log.info("Запущено приложение: %s (PID %s)", self.s.start_cmd, self._proc.pid)

    def adopt_previous(self) -> int | None:
        """Подхватывает приложение, которое запустил прошлый экземпляр бота (по PID-файлу)."""
        if not self.s.managed or self._alive_pid() is not None:
            return None
        try:
            data = json.loads(self.s.pid_file.read_text())
            proc = psutil.Process(int(data["pid"]))
            # Сверяем время старта: PID мог достаться другому процессу после перезагрузки
            if abs(proc.create_time() - float(data["create_time"])) > 1 or proc.status() == psutil.STATUS_ZOMBIE:
                raise psutil.NoSuchProcess(proc.pid)
        except (OSError, ValueError, KeyError, TypeError, psutil.Error):
            with contextlib.suppress(OSError):
                self.s.pid_file.unlink()
            return None
        self._adopted = proc
        self._started_at = proc.create_time()
        log.info("Подхватил уже запущенное приложение, PID %s", proc.pid)
        return proc.pid

    def _alive_pid(self) -> int | None:
        if self._proc is not None and self._proc.returncode is None:
            return self._proc.pid
        if self._adopted is not None:
            with contextlib.suppress(psutil.Error):
                if self._adopted.is_running() and self._adopted.status() != psutil.STATUS_ZOMBIE:
                    return self._adopted.pid
            self._adopted = None
        return None

    async def _wait_exit(self, timeout: float) -> bool:
        if self._proc is not None:
            try:
                await asyncio.wait_for(self._proc.wait(), timeout)
                return True
            except asyncio.TimeoutError:
                return False
        if self._adopted is not None:
            _, alive = await asyncio.to_thread(psutil.wait_procs, [self._adopted], timeout)
            return not alive
        return True

    @staticmethod
    def _signal(pid: int, pgid: int | None, sig: int) -> None:
        if pgid is not None:
            kill_process_group(pgid, sig)
        else:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, sig)

    def _write_pid_file(self, pid: int) -> None:
        with contextlib.suppress(OSError, psutil.Error):
            data = {"pid": pid, "create_time": psutil.Process(pid).create_time(), "cmd": self.s.start_cmd}
            self.s.pid_file.parent.mkdir(parents=True, exist_ok=True)
            self.s.pid_file.write_text(json.dumps(data))

    # ---------- Логи ----------

    async def recent_logs(self, lines: int) -> str:
        if self.s.logs_cmd:
            result = await run_shell(self.s.logs_cmd, cwd=self.s.app_dir, timeout=LOGS_CMD_TIMEOUT)
            text = result.output
            if result.timed_out:
                text += f"\n[APP_LOGS_CMD не завершилась за {LOGS_CMD_TIMEOUT:g} с — выводи логи без follow-режима]"
        elif self.s.log_file:
            text = await asyncio.to_thread(tail_file, self.s.log_file, lines)
        else:
            return "(логи не настроены: укажи APP_LOG_FILE или APP_LOGS_CMD)"
        return "\n".join(text.splitlines()[-lines:])


def tail_file(path: Path, lines: int, block: int = 65536, max_bytes: int = 4 * 1024 * 1024) -> str:
    """Последние `lines` строк файла без чтения его целиком."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = size = f.tell()
            data = b""
            while pos > 0 and data.count(b"\n") <= lines and size - pos < max_bytes:
                step = min(block, pos)
                pos -= step
                f.seek(pos)
                data = f.read(step) + data
    except FileNotFoundError:
        return f"(файла логов {path} пока нет)"
    text = strip_ansi(data.decode("utf-8", errors="replace"))
    return "\n".join(text.splitlines()[-lines:])


def free_port(port: int, inside: Path | None = None) -> list[int]:
    """Завершает процессы, слушающие TCP-порт (аналог `fuser -k PORT/tcp`). Возвращает их PID.

    inside — трогать только процессы, у которых рабочая папка внутри этой директории.
    """
    me = os.getpid()
    victims: dict[int, psutil.Process] = {}
    try:
        connections = psutil.net_connections(kind="tcp")
    except psutil.AccessDenied:
        # Без прав на чтение соединений владельцев порта не проверить: fuser — только для явного APP_PORT
        if inside is None and shutil.which("fuser"):
            subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True, timeout=15, check=False)
        return []
    for conn in connections:
        if conn.status != psutil.CONN_LISTEN or not conn.laddr or conn.laddr.port != port:
            continue
        if not conn.pid or conn.pid == me:
            continue
        try:
            proc = psutil.Process(conn.pid)
            if inside is not None:
                cwd = Path(proc.cwd()).resolve()
                if cwd != inside and inside not in cwd.parents:
                    log.warning("Порт %s держит чужой процесс %s (%s) — не трогаю", port, proc.pid, proc.name())
                    continue
        except (psutil.Error, OSError):
            continue
        victims[conn.pid] = proc
    for proc in victims.values():
        with contextlib.suppress(psutil.Error):
            proc.terminate()
    _, alive = psutil.wait_procs(list(victims.values()), timeout=5)
    for proc in alive:
        with contextlib.suppress(psutil.Error):
            proc.kill()
    return sorted(victims)


def server_stats() -> dict[str, str]:
    """Нагрузка на сервер для /status."""
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    stats = {
        "CPU": f"{psutil.cpu_percent(interval=0.3):.0f}%",
        "RAM": f"{vm.percent:.0f}% ({_gb(vm.used)} из {_gb(vm.total)})",
        "Диск /": f"{disk.percent:.0f}% (свободно {_gb(disk.free)})",
    }
    with contextlib.suppress(OSError, AttributeError):
        stats["Load avg"] = " ".join(f"{x:.2f}" for x in os.getloadavg())
    return stats


def _gb(value: float) -> str:
    return f"{value / 1024 ** 3:.1f} ГБ"


def _pgid(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return None


def _rotate(path: Path) -> None:
    with contextlib.suppress(OSError):
        if path.stat().st_size > LOG_ROTATE_BYTES:
            path.replace(path.with_name(path.name + ".1"))


def _last_line(text: str, limit: int = 300) -> str:
    for line in reversed(text.strip().splitlines()):
        if line.strip():
            return line.strip()[:limit]
    return ""
