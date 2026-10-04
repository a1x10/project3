"""Запуск команд без блокировки бота: с таймаутом и убийством всего дерева процессов."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import signal
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
DRAIN_TIMEOUT = 2.0  # сколько ждать хвост вывода после выхода процесса
KILL_WAIT = 5.0
POLL_INTERVAL = 0.05

_detached_readers: set[asyncio.Future[None]] = set()


@dataclass
class CommandResult:
    returncode: int | None
    output: str
    timed_out: bool = False
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.returncode == 0


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def clean_output(raw: bytes) -> str:
    """Байты → текст без цветов и «перерисовок» прогресс-баров (\\r)."""
    text = strip_ansi(raw.decode("utf-8", errors="replace"))
    lines = text.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rsplit("\r", 1)[-1] for line in lines)


def kill_process_group(pgid: int, sig: int = signal.SIGKILL) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


async def run_shell(
    command: str,
    *,
    cwd: Path | str | None = None,
    timeout: float = 60.0,
    env: dict[str, str] | None = None,
    max_output: int = 200_000,
) -> CommandResult:
    """Выполняет команду в shell. stdout и stderr склеены, от вывода остаётся хвост в max_output байт."""
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,  # своя группа процессов — по таймауту убиваем всё дерево
    )
    return await _collect(proc, timeout, max_output)


async def run_exec(
    *args: str,
    cwd: Path | str | None = None,
    timeout: float = 60.0,
    env: dict[str, str] | None = None,
    max_output: int = 200_000,
) -> CommandResult:
    """То же, что run_shell, но без shell: аргументы передаются как есть (никаких инъекций)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    return await _collect(proc, timeout, max_output)


async def _collect(proc: asyncio.subprocess.Process, timeout: float, max_output: int) -> CommandResult:
    started = time.monotonic()
    buf = bytearray()
    truncated = False

    async def reader() -> None:
        nonlocal truncated
        assert proc.stdout is not None
        try:
            while chunk := await proc.stdout.read(65536):
                buf.extend(chunk)
                if len(buf) > 2 * max_output:
                    del buf[: len(buf) - max_output]
                    truncated = True
        except OSError as e:  # pipe закрылся с ошибкой — отдаём то, что успели прочитать
            log.debug("Чтение вывода команды прервано: %s", e)

    read_task = asyncio.ensure_future(reader())
    # proc.wait() в asyncio ждёт ещё и закрытия pipe, а его может держать фоновый потомок
    # (`/cmd node server.js &`). Поэтому ждём именно кода выхода самого процесса.
    timed_out = await _wait_returncode(proc, started + timeout)
    if timed_out:
        kill_process_group(proc.pid)
        await _wait_returncode(proc, time.monotonic() + KILL_WAIT)

    try:
        await asyncio.wait_for(asyncio.shield(read_task), DRAIN_TIMEOUT)
    except asyncio.TimeoutError:
        # Фоновый потомок всё ещё пишет в pipe: дочитываем в фоне, иначе он зависнет на записи
        _detached_readers.add(read_task)
        read_task.add_done_callback(_detached_readers.discard)

    data = bytes(buf[-max_output:])
    truncated = truncated or len(buf) > max_output
    output = clean_output(data)
    if truncated:
        output = "…[начало вывода обрезано]\n" + output
    return CommandResult(
        returncode=proc.returncode,
        output=output,
        timed_out=timed_out,
        duration=time.monotonic() - started,
    )


async def _wait_returncode(proc: asyncio.subprocess.Process, deadline: float) -> bool:
    """Ждёт завершения процесса до deadline. True — не дождались."""
    while proc.returncode is None:
        if time.monotonic() >= deadline:
            return True
        await asyncio.sleep(POLL_INTERVAL)
    return False
