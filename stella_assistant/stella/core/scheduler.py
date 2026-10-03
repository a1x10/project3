"""Планировщик фоновых задач: периодические проверки (будильники, датчики, присутствие)."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("stella.scheduler")


@dataclass
class Job:
    fn: Callable
    interval: float | None
    next_run: float
    name: str
    threaded: bool = False


class Scheduler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="scheduler")
        self.jobs: list[Job] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def every(self, seconds: float, fn: Callable, name: str = "", first_delay: float | None = None,
              threaded: bool = False) -> Job:
        job = Job(fn, seconds, time.time() + (seconds if first_delay is None else first_delay), name or fn.__name__,
                  threaded)
        with self._lock:
            self.jobs.append(job)
        return job

    def at(self, ts: float, fn: Callable, name: str = "", threaded: bool = True) -> Job:
        job = Job(fn, None, ts, name or fn.__name__, threaded)
        with self._lock:
            self.jobs.append(job)
        return job

    def after(self, seconds: float, fn: Callable, name: str = "") -> Job:
        return self.at(time.time() + seconds, fn, name)

    def cancel(self, job: Job):
        with self._lock:
            if job in self.jobs:
                self.jobs.remove(job)

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            now = time.time()
            with self._lock:
                due = [j for j in self.jobs if j.next_run <= now]
                for j in due:
                    if j.interval is None:
                        self.jobs.remove(j)
                    else:
                        j.next_run = now + j.interval
            for j in due:
                if j.threaded:
                    threading.Thread(target=self._safe, args=(j,), daemon=True, name=f"job-{j.name}").start()
                else:
                    self._safe(j)
            self._stop.wait(0.25)

    @staticmethod
    def _safe(job: Job):
        try:
            job.fn()
        except Exception:
            log.exception("Ошибка в фоновой задаче %s", job.name)
