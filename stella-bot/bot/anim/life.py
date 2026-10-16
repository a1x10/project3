"""«Слой жизни» персонажа (design_wow §c.6): дыхание, моргание (иногда двойное, обязательно — на поворотах),
быстрые взгляды-саккады, переминание с ноги на ногу, движение губ по гласным текста и вторичное движение (волосы,
хвосты, уши, крылья отстают от тела и пружинят).

Всё — чистые функции времени: (t, seed, актёр) → число. Никакого состояния между кадрами, поэтому кадры можно
рисовать в любом порядке в разных процессах. Случайности — только через ease.rng/hash01/noise1.
Без cairo и numpy.
"""

from __future__ import annotations

import bisect
import functools
import math
from typing import Callable

from .ease import clamp, hash01, noise1, rng, smoothstep

LIP_CPS = 13.0  # скорость «чтения» реплики, знаков в секунду
BLINK_CLOSE, BLINK_HOLD, BLINK_OPEN = 0.05, 0.03, 0.08
BLINK_LEN = BLINK_CLOSE + BLINK_HOLD + BLINK_OPEN
DOUBLE_GAP = 0.22  # второй взмах двойного моргания — через столько секунд
HORIZON = 120.0  # на сколько секунд вперёд строить расписание (ролик ≤ 20–30 с)

VOWELS: dict[str, str] = {}
for _chars, _shape in (("аяaá", "a"), ("оуёюoóuú", "o"), ("еиэыeéiíy", "e")):
    for _c in _chars:
        VOWELS[_c] = _shape
        VOWELS[_c.upper()] = _shape


def actor_seed(seed: int, actor: str) -> int:
    """Число-«зерно» актёра (одинаковое в любом процессе)."""
    return int(hash01(seed, "actor", actor) * 2**31)


# ---------- моргание ----------
@functools.lru_cache(maxsize=256)
def _blink_times(aseed: int) -> tuple[tuple[float, ...], tuple[bool, ...]]:
    r = rng(aseed, "blink")
    t = r.uniform(0.4, 2.2)
    times, double = [], []
    while t < HORIZON:
        times.append(t)
        double.append(r.random() < 0.2)
        t += r.uniform(2.5, 5.0)
    return tuple(times), tuple(double)


def _blink_shape(d: float) -> float:
    """0..1 закрытость века через d секунд после начала взмаха: закрыть 0.05, держать 0.03, открыть 0.08."""
    if d < 0 or d >= BLINK_LEN:
        return 0.0
    if d < BLINK_CLOSE:
        return d / BLINK_CLOSE
    if d < BLINK_CLOSE + BLINK_HOLD:
        return 1.0
    return 1.0 - (d - BLINK_CLOSE - BLINK_HOLD) / BLINK_OPEN


def blink(t: float, aseed: int, forced: tuple[float, ...] = ()) -> float:
    """Закрытость век в момент t: раз в 2.5–5 с, 20 % — двойные, плюс обязательные (начало поворота)."""
    times, double = _blink_times(aseed)
    i = bisect.bisect_right(times, t) - 1
    v = 0.0
    if i >= 0:
        d = t - times[i]
        v = _blink_shape(d)
        if double[i]:
            v = max(v, _blink_shape(d - DOUBLE_GAP))
    for ft in forced:
        if 0 <= t - ft < BLINK_LEN:
            v = max(v, _blink_shape(t - ft))
    return v


# ---------- дыхание и переминание ----------
def breathing(t: float, aseed: int) -> float:
    """Фаза дыхания −1..1 (период 3.2 с, у каждого актёра своя фаза)."""
    phase = (aseed % 1000) / 1000.0 * 2 * math.pi
    return math.sin(2 * math.pi * t / 3.2 + phase)


def idle(t: float, aseed: int) -> dict[str, float]:
    """Добавки «живой стойки»: переминание (наклон ±0.03 раз в 3–5 с), покачивание головы, руки чуть дышат."""
    b = breathing(t, aseed)
    s = aseed % 9973
    return {
        "lean": 0.028 * noise1(t / 3.8, s),
        "head_tilt": 0.04 * noise1(t / 2.9 + 17.0, s),
        "squash": 0.012 * b,
        "arm": 0.02 * b + 0.035 * noise1(t / 2.3 + 40.0, s),
        "dx": 1.5 * noise1(t / 4.5 + 80.0, s),
    }


# ---------- взгляд: саккады ----------
@functools.lru_cache(maxsize=256)
def _saccades(aseed: int) -> tuple[tuple[float, ...], tuple[tuple[float, float], ...]]:
    r = rng(aseed, "saccade")
    t = 0.0
    times, targets = [0.0], [(0.0, 0.0)]
    while t < HORIZON:
        t += r.uniform(0.8, 2.5)
        times.append(t)
        targets.append((r.uniform(-0.25, 0.25), r.uniform(-0.12, 0.12)))
    return tuple(times), tuple(targets)


def saccade(t: float, aseed: int) -> tuple[float, float]:
    """Смещение взгляда: раз в 0.8–2.5 с прыгает на ±0.25, сам прыжок — 0.06 с (как у настоящих глаз)."""
    times, targets = _saccades(aseed)
    i = max(0, bisect.bisect_right(times, t) - 1)
    cur = targets[i]
    if i == 0:
        return cur
    prev = targets[i - 1]
    k = smoothstep((t - times[i]) / 0.06)
    return prev[0] + (cur[0] - prev[0]) * k, prev[1] + (cur[1] - prev[1]) * k


# ---------- губы по тексту ----------
def lip(text: str, t0: float, t: float, cps: float = LIP_CPS) -> tuple[float, str]:
    """(раскрытие рта 0..1, форма a|o|e|m): гласная — открытие 0.35 + 0.55·sin(π·доля) и форма по букве,
    согласная — 0.12, пробел и знаки — пауза. Текст «читается» со скоростью cps знаков в секунду."""
    if not text or cps <= 0:
        return 0.0, "m"
    pos = (t - t0) * cps
    if pos < 0 or pos >= len(text):
        return 0.0, "m"
    i = int(pos)
    ch = text[i]
    frac = pos - i
    if ch in VOWELS:
        return 0.35 + 0.55 * math.sin(math.pi * frac), VOWELS[ch]
    if ch.isalpha():
        return 0.12 * math.sin(math.pi * frac) + 0.06, "e"
    return 0.0, "m"


def word_starts(text: str) -> list[int]:
    """Номера букв, с которых начинаются слова (для жестов и кивков в такт речи)."""
    out = []
    prev_space = True
    for i, ch in enumerate(text):
        if ch.isalnum() and prev_space:
            out.append(i)
        prev_space = not ch.isalnum()
    return out


# ---------- вторичное движение ----------
def spring_lag(driver: Callable[[float], float], t: float, *, window: float = 0.6, n: int = 12,
               freq: float = 1.8, zeta: float = 0.35) -> float:
    """Насколько пружина «отстаёт» от движущегося тела: driver(t) − y(t). Пружину прогоняем по n выборкам
    за последние window секунд — без состояния, но с честным перелётом при остановке."""
    dt = window / n
    w = 2 * math.pi * freq
    y = driver(t - window)
    v = 0.0
    for k in range(1, n + 1):
        d = driver(t - window + k * dt)
        # полунеявный Эйлер — устойчив при таком шаге
        v += (w * w * (d - y) - 2 * zeta * w * v) * dt
        y += v * dt
    return driver(t) - y


def swing(lag: float, gain: float) -> float:
    """Отставание → качание волос/хвоста −1..1 (против движения)."""
    return clamp(-lag * gain, -1.0, 1.0)


__all__ = ["LIP_CPS", "VOWELS", "actor_seed", "blink", "breathing", "idle", "lip", "saccade", "spring_lag",
           "swing", "word_starts"]
