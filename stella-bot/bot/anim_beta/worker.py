"""Процесс рендера мультика (бета): лимиты, пул воркеров со скользящим окном, ffmpeg, прогресс строками JSON.

Запускается ботом как `python -I -c BOOT` в своей группе процессов. Задание — одна строка JSON в stdin;
stdin остаётся открытым: EOF = бот умер -> убиваем всю группу (пул и ffmpeg).
"""

from __future__ import annotations

import collections
import json
import os
import resource
import signal
import subprocess
import sys
import threading
import time

_surf = None
_plan = None


def _limit(as_mb: int, cpu_s: int, fsize_mb: int) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (as_mb << 20, as_mb << 20))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_mb << 20, fsize_mb << 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _init(plan_json: str, as_mb: int, cpu_s: int) -> None:
    """Инициализатор процесса пула: свои лимиты, план разбирается один раз."""
    global _surf, _plan
    _limit(as_mb, cpu_s, 1)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)  # stdout — канал протокола, воркерам туда нельзя
    import cairocffi as cairo

    _plan = json.loads(plan_json)
    w, h = _plan["size"]
    _surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)


def _chunk(start: int, stop: int):
    from bot.anim_beta.frame import render_frame

    out = []
    t0 = time.perf_counter()
    for i in range(start, stop):
        render_frame(_plan, i, _surf)
        out.append(bytes(_surf.get_data()))
    return start, out, (time.perf_counter() - t0) / max(1, stop - start)


def emit(**kw) -> None:
    sys.stdout.write(json.dumps(kw) + "\n")
    sys.stdout.flush()


def main() -> None:
    if os.getpgid(0) != os.getpid():
        os.setpgid(0, 0)
    job = json.loads(sys.stdin.buffer.readline())
    deadline = int(job["deadline"])

    def die(*_):
        sys.stdout.flush()
        try:
            os.killpg(0, signal.SIGKILL)
        finally:
            os._exit(3)

    def watch():  # бот умер (stdin закрылся) — убить всю группу
        while os.read(0, 4096):
            pass
        die()

    threading.Thread(target=watch, daemon=True).start()
    signal.signal(signal.SIGALRM, die)
    signal.alarm(deadline + 5)
    os.nice(job.get("nice", 10))
    _limit(job.get("main_as_mb", 1024), deadline, job.get("max_mb", 16) + 1)

    plan = job["plan"]
    w, h = plan["size"]
    fps = plan["fps"]
    n = max(1, int(round(sum(s["dur"] for s in plan["scenes"]) * fps)))
    t_start = time.perf_counter()
    ff = subprocess.Popen(
        [job.get("ffmpeg", "ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", str(job.get("crf", 22)), "-profile:v", "main",
         "-threads", "2", "-maxrate", "4M", "-bufsize", "8M", "-g", str(2 * fps),
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", job["out"]],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    workers = max(1, int(job.get("workers", 1)))
    chunk = 2
    # ProcessPoolExecutor, а не Pool: упавший воркер -> BrokenProcessPool, а не тихий перезапуск по кругу
    pool = ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn"), initializer=_init,
                               initargs=(json.dumps(plan), min(job.get("worker_as_mb", 512),
                                                               job.get("main_as_mb", 1024)), deadline))
    emit(ev="start", frames=n, workers=workers)
    window: collections.deque = collections.deque()
    starts = list(range(0, n, chunk))
    nxt = done = 0
    per_frame = []
    last = 0.0
    err = ""
    try:
        while nxt < len(starts) or window:
            while nxt < len(starts) and len(window) < 2 * workers:  # не больше 2×workers кусков в полёте
                s = starts[nxt]
                window.append(pool.submit(_chunk, s, min(s + chunk, n)))
                nxt += 1
            _s, frames, sec = window.popleft().result(timeout=deadline)
            per_frame.append(sec)
            for fr in frames:
                ff.stdin.write(fr)
            done += len(frames)
            now = time.perf_counter()
            if now - last > 1.0 or done == n:
                last = now
                el = now - t_start
                emit(ev="progress", done=done, frames=n, eta=round(el / done * (n - done), 1))
        ff.stdin.close()
        err = ff.stderr.read().decode(errors="replace")[-300:]
        rc = ff.wait()
    except MemoryError:
        emit(ev="error", kind="memory", msg="не хватило памяти")
        die()
    except BrokenProcessPool as exc:
        emit(ev="error", kind="worker", msg=f"процесс рисования упал: {exc!r}"[:300])
        die()
    except BrokenPipeError:
        emit(ev="error", kind="ffmpeg", msg=ff.stderr.read().decode(errors="replace")[-300:])
        die()
    except Exception as exc:  # ошибка в кадре (MemoryError внутри воркера приходит сюда же)
        kind = "memory" if "MemoryError" in repr(exc) else "bug"
        emit(ev="error", kind=kind, msg=repr(exc)[:300])
        die()
    pool.shutdown(wait=True)
    if rc != 0:
        emit(ev="error", kind="ffmpeg", msg=err)
        os._exit(2)
    per_frame.sort()
    emit(ev="done", bytes=os.path.getsize(job["out"]), secs=round(time.perf_counter() - t_start, 2),
         ms_per_frame=round(per_frame[len(per_frame) // 2] * 1000, 1))
    sys.stdout.flush()
    os._exit(0)  # не ждать поток, читающий stdin
