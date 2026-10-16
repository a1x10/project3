"""Время и движение: сглаживания, пружина, гладкий шум и детерминированные «случайности».

Чистый Python без numpy — модуль лёгкий, его импортируют и бот (разбор сценария), и процесс рендера.
Все случайности мультика — только отсюда: hash01/rng зависят лишь от seed и ключа (sha1 от repr), поэтому кадр
можно нарисовать в любом порядке и в любом процессе и получить те же пиксели.
"""

from __future__ import annotations

import hashlib
import math
import random

EASINGS = ("linear", "in", "out", "in_out", "out_back", "in_back", "out_bounce", "out_elastic", "spring")


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Зажать x в [lo, hi]; NaN превращается в lo."""
    if x != x:  # NaN
        return lo
    return lo if x < lo else hi if x > hi else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def window(t: float, t0: float, t1: float) -> float:
    """Прогресс 0..1 внутри [t0, t1]; до t0 — 0, после t1 — 1. Пустой отрезок — ступенька в t0."""
    if t1 <= t0:
        return 1.0 if t >= t0 else 0.0
    return clamp((t - t0) / (t1 - t0))


def smoothstep(t: float) -> float:
    t = clamp(t)
    return t * t * (3.0 - 2.0 * t)


def ease_out_back(t: float, s: float = 1.70158) -> float:
    """Быстро к цели с небольшим перелётом и возвратом (появление пузыря, «пружинистая» остановка)."""
    t = clamp(t)
    if t >= 1.0:
        return 1.0
    x = t - 1.0
    return 1.0 + x * x * ((s + 1.0) * x + s)


def ease_in_back(t: float, s: float = 1.70158) -> float:
    """Замах назад перед движением (антиципация)."""
    t = clamp(t)
    if t >= 1.0:
        return 1.0
    return t * t * ((s + 1.0) * t - s)


def ease_out_bounce(t: float) -> float:
    """Падение с отскоками (как мячик), 0 → 1."""
    t = clamp(t)
    if t >= 1.0:
        return 1.0
    n, d = 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        t -= 1.5 / d
        return n * t * t + 0.75
    if t < 2.5 / d:
        t -= 2.25 / d
        return n * t * t + 0.9375
    t -= 2.625 / d
    return n * t * t + 0.984375


def ease_out_elastic(t: float) -> float:
    """Резинка: перелёт и затухающие колебания вокруг цели."""
    t = clamp(t)
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return 2.0 ** (-10.0 * t) * math.sin((t * 10.0 - 0.75) * (2.0 * math.pi / 3.0)) + 1.0


def spring(t: float, freq: float = 2.5, zeta: float = 0.3) -> float:
    """Переходный процесс пружины 0 → 1 с перелётом; t — секунды от толчка, freq — Гц, zeta — затухание.

    При t ≤ 0 — 0, дальше колебания вокруг 1 затухают (при zeta 0.3 перелёт около 37 %).
    """
    if t <= 0.0:
        return 0.0
    w = 2.0 * math.pi * max(0.01, freq)
    z = max(0.0, zeta)
    if z >= 1.0:  # без перелёта (критическое затухание)
        return 1.0 - (1.0 + w * t) * math.exp(-w * t)
    return 1.0 - math.exp(-z * w * t) * math.cos(w * math.sqrt(1.0 - z * z) * t)


_SPRING_END = spring(1.0)


def _spring01(t: float) -> float:
    # пружина на отрезке 0..1 с точным попаданием в 1 на конце
    return spring(t) + (1.0 - _SPRING_END) * smoothstep(t)


def _in_out(t: float) -> float:
    if t < 0.5:
        return 4.0 * t * t * t
    u = -2.0 * t + 2.0
    return 1.0 - u * u * u / 2.0


_EASE = {
    "linear": lambda t: t,
    "in": lambda t: t * t * t,
    "out": lambda t: 1.0 - (1.0 - t) ** 3,
    "in_out": _in_out,
    "out_back": ease_out_back,
    "in_back": ease_in_back,
    "out_bounce": ease_out_bounce,
    "out_elastic": ease_out_elastic,
    "spring": _spring01,
}


def ease(name: str, t: float) -> float:
    """Сглаживание по имени (EASINGS); t зажимается в 0..1, ease(·, 0) = 0, ease(·, 1) = 1. Неизвестное — linear."""
    t = clamp(t)
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return _EASE.get(name, _EASE["linear"])(t)


def fade_weight(t: float, t0: float, t1: float, fade: float) -> float:
    """Вес 0..1 на отрезке [t0, t1]: плавно входит за fade секунд от t0 и так же выходит к t1; снаружи 0."""
    if t < t0 or t > t1 or t1 <= t0:
        return 0.0
    if fade <= 0.0:
        return 1.0 if t < t1 else 0.0
    fade = min(fade, (t1 - t0) / 2.0)
    return min(smoothstep((t - t0) / fade), smoothstep((t1 - t) / fade))


# ---------- детерминированные случайности ----------
def _digest(seed: int, key: tuple[object, ...]) -> bytes:
    return hashlib.sha1(repr((seed,) + key).encode("utf-8", "backslashreplace")).digest()


def hash01(seed: int, *key: object) -> float:
    """Детерминированное число 0..1 (не включая 1) от seed и ключа; одинаково в любом процессе."""
    return int.from_bytes(_digest(seed, key)[:8], "big") / 2.0**64


def rng(seed: int, *key: object) -> random.Random:
    """Свой генератор random.Random для (seed, ключ): одинаковая последовательность в любом процессе."""
    return random.Random(int.from_bytes(_digest(seed, key)[:16], "big"))


def _ihash(i: int, seed: int) -> float:
    # быстрый целочисленный хэш решётки шума → -1..1 (sha1 для шума слишком медленный)
    h = (i * 374761393 + (seed & 0xFFFFFFFF) * 668265263 + 0x9E3779B9) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return h / 2147483647.5 - 1.0


def noise1(x: float, seed: int = 0) -> float:
    """Гладкий одномерный шум -1..1 (значения в целых точках, между ними — плавная пятой степени)."""
    if x != x or math.isinf(x):
        return 0.0
    i = math.floor(x)
    f = x - i
    u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0)
    return lerp(_ihash(i, seed), _ihash(i + 1, seed), u)
