"""Запуск рендера мультика из бота (бета): один рендер за раз, свой процесс, таймаут, оценка времени.

Процесс рендера живёт в своей группе (start_new_session) и получает чистое окружение — без ключей API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
import time
from typing import Callable

log = logging.getLogger("stella.anim")

APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOT = ("import sys; sys.path.insert(0, %r); sys.argv[0] = 'stella-anim'; "
        "from bot.anim_beta.worker import main; main()" % APP_ROOT)
SAFE_ENV = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8",
            "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MALLOC_ARENA_MAX": "2", "HOME": "/tmp"}
MAX_BYTES = 15 * 1024 * 1024
MAX_WAITING = 3  # сколько мультиков может ждать своей очереди


class RenderError(Exception):
    """Мультик не получился: текст можно показать в чате."""


def effective_cpus() -> int:
    """Сколько ядер реально доступно (в Docker os.cpu_count() показывает все ядра машины)."""
    try:
        n = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        n = os.cpu_count() or 1
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, period = f.read().split()[:2]
        if quota != "max":
            n = min(n, max(1, int(int(quota) / int(period))))
    except (OSError, ValueError):
        pass
    return max(1, n)


def workers_count() -> int:
    return max(1, min(2, effective_cpus() - 1))


class _State:
    """Общее на процесс бота: очередь рендеров и скорость машины (уточняется после каждого ролика)."""

    def __init__(self) -> None:
        self.lock: asyncio.Lock | None = None
        self.loop = None
        self.waiting = 0
        self.busy_chats: set[int] = set()
        self.sec_per_frame = 0.045  # на одном воркере; уточняется по факту
        self.running_until = 0.0  # когда примерно закончится текущий рендер (time.monotonic)

    def get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self.lock is None or self.loop is not loop:  # новый цикл событий (тесты, перезапуск)
            self.lock, self.loop = asyncio.Lock(), loop
        return self.lock


STATE = _State()


def frames_of(plan: dict) -> int:
    return max(1, int(round(sum(s["dur"] for s in plan["scenes"]) * plan["fps"])))


def estimate_seconds(plan: dict) -> float:
    """Сколько ждать готового ролика: очередь + рисование + сборка, с запасом."""
    w, h = plan["size"]
    px = (w * h / (720 * 720)) ** 0.75
    weight = 1 + 0.25 * max(0, len(plan["cast"]) - 2) + 0.15 * len(plan.get("things", {}))
    workers = workers_count()
    speed = 1.0 if workers == 1 else 1.8
    render = frames_of(plan) * STATE.sec_per_frame * px * weight / speed
    ahead = max(0.0, STATE.running_until - time.monotonic()) + STATE.waiting * 15
    return (render + 2.0) * 1.3 + ahead


def human_eta(seconds: float) -> str:
    if seconds <= 12:
        return "секунд через 10"
    if seconds <= 50:
        return f"секунд через {int(-(-seconds // 5) * 5)}"
    if seconds <= 80:
        return "примерно через минуту"
    if seconds <= 150:
        return "минуты через две"
    return f"минут через {int(-(-seconds // 60))}"


def can_start(chat_id: int) -> str | None:
    """Почему сейчас нельзя поставить мультик (None — можно)."""
    if chat_id in STATE.busy_chats:
        return "один мультик для этого чата уже делается — дождись его"
    if STATE.waiting >= MAX_WAITING:
        return "сейчас очередь из мультиков, попроси через пару минут"
    return None


async def render(plan: dict, chat_id: int, *, timeout: float = 150,
                 on_start: Callable[[], None] | None = None) -> bytes:
    """Нарисовать мультик в отдельном процессе; по очереди с другими чатами. Возвращает байты MP4."""
    STATE.busy_chats.add(chat_id)
    STATE.waiting += 1
    waiting = True
    try:
        async with STATE.get_lock():
            STATE.waiting -= 1
            waiting = False
            est = estimate_seconds(plan) - 2.6
            STATE.running_until = time.monotonic() + max(5.0, est)
            if on_start:
                on_start()
            try:
                return await _run(plan, timeout)
            finally:
                STATE.running_until = 0.0
    finally:
        if waiting:  # отменили, пока ждал очереди
            STATE.waiting -= 1
        STATE.busy_chats.discard(chat_id)


async def _run(plan: dict, timeout: float) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RenderError("на сервере нет ffmpeg")
    tmp = tempfile.mkdtemp(prefix="stella-anim-")
    try:
        return await _run_in(plan, timeout, ffmpeg, tmp)
    finally:  # и при отмене (перезапуск бота), и при таймауте — без хвостов на диске
        shutil.rmtree(tmp, ignore_errors=True)


async def _run_in(plan: dict, timeout: float, ffmpeg: str, tmp: str) -> bytes:
    out = os.path.join(tmp, "video.mp4")
    job = {"plan": plan, "out": out, "workers": workers_count(), "deadline": int(timeout), "nice": 10,
           "ffmpeg": ffmpeg, "crf": 22, "max_mb": 16}
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-c", BOOT, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True, env=SAFE_ENV)
    events: list[dict] = []
    tail = bytearray()

    async def read_out() -> None:
        assert proc.stdout is not None
        async for line in proc.stdout:
            try:
                events.append(json.loads(line))
            except ValueError:
                continue

    async def read_err() -> None:  # читаем параллельно, чтобы канал не переполнился
        assert proc.stderr is not None
        while chunk := await proc.stderr.read(4096):
            tail.extend(chunk)
            del tail[:-4096]

    try:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(job) + "\n").encode())
        await proc.stdin.drain()  # stdin НЕ закрываем: EOF для рендера = бот умер
        await asyncio.wait_for(asyncio.gather(read_out(), read_err(), proc.wait()), timeout + 10)
    except asyncio.TimeoutError as exc:
        raise RenderError("мультик рисовался слишком долго — давай покороче или попроще") from exc
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # добить остатки группы, если есть
        except (ProcessLookupError, PermissionError):
            pass
        if proc.returncode is None:
            await proc.wait()
    done = next((e for e in events if e.get("ev") == "done"), None)
    if proc.returncode != 0 or done is None:
        err = next((e for e in events if e.get("ev") == "error"), None)
        log.warning("мультик не нарисовался: код %s, %s, %s", proc.returncode, err,
                    bytes(tail).decode(errors="replace")[-300:])
        if err and err.get("kind") == "memory":
            raise RenderError("мультик получился слишком тяжёлым — давай попроще")
        if err and err.get("kind") == "timeout":
            raise RenderError("мультик рисовался слишком долго — давай покороче или попроще")
        raise RenderError("не получилось собрать мультик")
    size = os.path.getsize(out)
    if not 0 < size <= MAX_BYTES:
        raise RenderError("ролик получился слишком большим")
    data = await asyncio.to_thread(_read, out)
    # подстраиваем скорость под эту машину: следующий прогноз будет точнее
    frames = frames_of(plan)
    w, h = plan["size"]
    px = (w * h / (720 * 720)) ** 0.75
    weight = 1 + 0.25 * max(0, len(plan["cast"]) - 2) + 0.15 * len(plan.get("things", {}))
    speed = 1.0 if job["workers"] == 1 else 1.8
    observed = max(0.0, time.monotonic() - started - 2.0) * speed / (frames * px * weight)
    STATE.sec_per_frame = min(0.5, max(0.01, 0.6 * STATE.sec_per_frame + 0.4 * observed))
    log.info("мультик: %d кадров %dx%d за %.1f с, %.0f КБ", frames, w, h, time.monotonic() - started,
             len(data) / 1024)
    return data


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()
