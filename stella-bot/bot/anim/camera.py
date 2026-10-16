"""Камера мультика: наезд, отъезд, панорама, слежение, «облёт», тряска, рывок — всё чистые функции времени.

Камера — аффинное преобразование кадра: сдвиг взгляда (x, y), масштаб zoom вокруг точки (w/2, PIVOT_Y·h),
поворот и тряска. Слои сцены сдвигаются по-разному (параллакс): небо 0.1, дальний план 0.3, средний 0.6,
земля и актёры 1.0, передние частицы 1.15; пузыри и титры — экранные (parallax 0): на них действует только
половина тряски. Чем ближе слой, тем сильнее он едет и сильнее увеличивается — получается «многоплановая» камера,
как в старых мультфильмах.

Движение на всю сцену — CameraEvent с kind из catalog.CAMERA_MOVES (static, zoom_in, zoom_out, pan_left,
pan_right, follow, orbit), короткие — из битов (catalog.CAMERA_BEATS: shake, zoom_in, zoom_out, punch, focus,
reset). zoom_in/zoom_out/focus из бита держатся до следующего бита камеры или reset; shake и punch возвращаются
сами; reset плавно возвращает камеру в покой и гасит движение сцены.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import cairocffi as cairo

from .ease import clamp, ease, ease_out_back, lerp, window
from .model import CameraEvent, Plan, PlannedShot

PIVOT_Y = 0.62  # точка кадра (доля высоты), вокруг которой масштабирует камера: между головами и ногами
PARALLAX: dict[str, float] = {"sky": 0.1, "far": 0.3, "mid": 0.6, "ground": 1.0, "front": 1.15, "screen": 0.0}

# пределы — их же учитывают поля фона (layer_margin), чтобы за краем нарисованного никогда не было пустоты
MAX_PAN = 0.30  # |x| ≤ 0.30·w
MAX_TILT = 0.08  # |y| ≤ 0.08·h
MAX_DRIFT = 0.08  # «облёт»: дальние слои едут против ближних не больше 0.08·w
ZOOM_MIN, ZOOM_MAX = 0.9, 1.6
MAX_ROT = 0.03  # радианы
SHAKE_MAX = 22.0  # пиксели при высоте кадра 720

MOVE_ONLY = frozenset({"static", "pan_left", "pan_right", "follow", "orbit"})
BEAT_ONLY = frozenset({"shake", "punch", "focus", "reset"})
LAG = 0.3  # отставание камеры при follow, секунды


@dataclass
class Cam:
    x: float = 0.0  # сдвиг центра взгляда, пиксели (вправо +)
    y: float = 0.0
    zoom: float = 1.0
    rot: float = 0.0
    shake_x: float = 0.0
    shake_y: float = 0.0
    drift: float = 0.0  # «облёт» (orbit): сдвиг дальних слоёв относительно плана актёров, пиксели
    orbit: float = 0.0  # угол облёта, радианы — 3D-предметы могут повернуться на него

    def is_rest(self) -> bool:
        return (self.x == 0.0 and self.y == 0.0 and self.zoom == 1.0 and self.rot == 0.0 and self.shake_x == 0.0
                and self.shake_y == 0.0 and self.drift == 0.0)


REST = Cam()


# ======================= преобразование =======================
def _layer(cam: Cam, w: int, h: int, parallax: float) -> tuple[float, float, float, float, float, float]:
    """(сдвиг экрана x, y, масштаб, поворот, сдвиг мира x, y) для слоя с данным параллаксом."""
    p = parallax
    z = max(0.05, 1.0 + (cam.zoom - 1.0) * p)
    ox = cam.x * p + cam.drift * (1.0 - p)
    oy = cam.y * p
    return cam.shake_x, cam.shake_y, z, cam.rot * min(p, 1.0), ox, oy


def apply_cam(ctx: cairo.Context, cam: Cam, w: int, h: int, parallax: float = 1.0) -> None:
    """ctx.translate/scale/rotate для слоя с параллаксом parallax (небо 0.1, дальний 0.3, средний 0.6,
    земля/актёры 1.0, передние частицы 1.15). parallax ≤ 0 — экранный слой (пузыри, титры): только половина
    тряски."""
    if parallax <= 0.0:
        if cam.shake_x or cam.shake_y:
            ctx.translate(cam.shake_x * 0.5, cam.shake_y * 0.5)
        return
    sx, sy, z, rot, ox, oy = _layer(cam, w, h, parallax)
    px, py = w / 2.0, h * PIVOT_Y
    ctx.translate(px + sx, py + sy)
    if rot:
        ctx.rotate(rot)
    if z != 1.0:
        ctx.scale(z, z)
    ctx.translate(-px - ox, -py - oy)


def to_screen(cam: Cam, w: int, h: int, x: float, y: float, parallax: float = 1.0) -> tuple[float, float]:
    """Точка слоя (пиксели «мира») → пиксели экрана; для якорей пузырей (голова актёра → экран)."""
    if parallax <= 0.0:
        return x + cam.shake_x * 0.5, y + cam.shake_y * 0.5
    sx, sy, z, rot, ox, oy = _layer(cam, w, h, parallax)
    px, py = w / 2.0, h * PIVOT_Y
    dx, dy = (x - px - ox) * z, (y - py - oy) * z
    if rot:
        c, s = math.cos(rot), math.sin(rot)
        dx, dy = dx * c - dy * s, dx * s + dy * c
    return px + sx + dx, py + sy + dy


def from_screen(cam: Cam, w: int, h: int, x: float, y: float, parallax: float = 1.0) -> tuple[float, float]:
    """Обратное к to_screen: пиксель экрана → точка слоя."""
    if parallax <= 0.0:
        return x - cam.shake_x * 0.5, y - cam.shake_y * 0.5
    sx, sy, z, rot, ox, oy = _layer(cam, w, h, parallax)
    px, py = w / 2.0, h * PIVOT_Y
    dx, dy = x - px - sx, y - py - sy
    if rot:
        c, s = math.cos(-rot), math.sin(-rot)
        dx, dy = dx * c - dy * s, dx * s + dy * c
    return px + ox + dx / z, py + oy + dy / z


def view_rect(cam: Cam, w: int, h: int, parallax: float = 1.0) -> tuple[float, float, float, float]:
    """Какая часть слоя видна в кадре: (x0, y0, x1, y1) в пикселях слоя (по рамке углов экрана)."""
    pts = [from_screen(cam, w, h, x, y, parallax) for x, y in ((0, 0), (w, 0), (0, h), (w, h))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def layer_margin(w: int, h: int, parallax: float) -> tuple[int, int]:
    """Сколько пикселей (mx, my) слою нужно нарисовать за краями кадра, чтобы при любых допустимых движениях
    камеры (пределы MAX_PAN, MAX_TILT, ZOOM_MIN, MAX_ROT, тряска) за краем не было пустоты."""
    p = max(0.0, parallax)
    z = max(0.05, 1.0 + (ZOOM_MIN - 1.0) * p)
    shake = SHAKE_MAX * h / 720.0 / z
    rot = (w + h) * 0.5 * MAX_ROT * min(p, 1.0)
    mx = MAX_PAN * w * p + MAX_DRIFT * w * abs(1.0 - p) + (w / 2.0) * (1.0 / z - 1.0) + rot + shake + 4
    my = MAX_TILT * h * p + max(PIVOT_Y, 1 - PIVOT_Y) * h * (1.0 / z - 1.0) + rot + shake + 4
    return int(math.ceil(max(0.0, mx))), int(math.ceil(max(0.0, my)))


# ======================= где актёр (для слежения) =======================
def _trap(tau: float, a: float = 0.15, d: float = 0.2) -> float:
    # путь 0..1 с разгоном и торможением — как ходят актёры
    tau = clamp(tau)
    v = 1.0 / (1.0 - a / 2 - d / 2)
    if tau < a:
        return v * tau * tau / (2 * a)
    if tau < 1 - d:
        return v * (a / 2 + (tau - a))
    u = 1 - tau
    return 1.0 - v * u * u / (2 * d)


_MOVES = frozenset({"walk", "walk_in", "walk_out", "run", "fly"})


def _path(plan: Plan, shot: PlannedShot, actor: str) -> tuple[float | None, list[tuple[float, float, float, float]]]:
    """Начальный x актёра в сцене и его перемещения (t0, t1, x0, x1) — доли ширины."""
    start = None
    for p in plan.placements:
        if p.actor == actor and p.shot == shot.index:
            start = p.x
            break
    moves = []
    for c in plan.clips:
        if c.actor != actor or c.layer != 0 or c.action not in _MOVES:
            continue
        if c.t1 <= shot.t0 - 1e-6 or c.t0 >= shot.t1 + 1e-6:
            continue
        try:
            moves.append((float(c.t0), float(c.t1), float(c.params["x0"]), float(c.params["x1"])))
        except (KeyError, TypeError, ValueError):
            continue
    moves.sort()
    if start is None and moves:
        start = moves[0][2]
    return start, moves


def _path_x(start: float | None, moves: list[tuple[float, float, float, float]], t: float) -> float | None:
    x = start
    for t0, t1, x0, x1 in moves:
        if t < t0:
            break
        if t >= t1:
            x = x1
            continue
        return lerp(x0, x1, _trap((t - t0) / max(1e-6, t1 - t0)))
    return x


def _lagged_x(start: float | None, moves: list[tuple[float, float, float, float]], t: float, t_min: float,
              lag: float = LAG) -> float | None:
    """x с отставанием пружины без состояния: свёртка пути с откликом критически задемпфированной пружины
    h(τ) = ω²·τ·e^(−ωτ), среднее отставание 2/ω = lag."""
    if start is None and not moves:
        return None
    om = 2.0 / max(0.05, lag)
    dt = lag / 8.0
    acc = wsum = 0.0
    for k in range(32):
        tau = (k + 0.5) * dt
        wk = tau * math.exp(-om * tau)
        x = _path_x(start, moves, max(t_min, t - tau))
        if x is None:
            continue
        acc += wk * x
        wsum += wk
    return acc / wsum if wsum > 0 else None


# ======================= камера в момент t =======================
def _is_move(ev: CameraEvent, shot: PlannedShot) -> bool:
    if ev.kind in MOVE_ONLY:
        return True
    if ev.kind in BEAT_ONLY:
        return False
    span = shot.t1 - shot.t0
    return abs(ev.t0 - shot.t0) < 1e-3 and (ev.t1 - ev.t0) >= 0.9 * span and span > 0.9


def camera_at(plan: Plan, shot: PlannedShot, t: float, actor_x: Callable[[str], float | None]) -> Cam:
    """Камера сцены shot в момент t (секунды ролика). actor_x(id) — текущий x актёра в пикселях (для focus и
    follow) или None. Без событий камеры — покой (Cam())."""
    w, h = plan.w, plan.h
    events = [c for c in plan.cameras if c.shot == shot.index and math.isfinite(c.t0)]
    if not events or not math.isfinite(t):
        return Cam()
    events.sort(key=lambda c: c.t0)
    k720 = h / 720.0

    def focus_x(actor: str | None, lagged: bool = False) -> float | None:
        if not actor or actor not in plan.cast:
            return None
        if not lagged:
            try:
                v = actor_x(actor)
            except Exception:  # камера не должна ронять кадр из-за чужой функции
                v = None
            if v is not None and math.isfinite(v):
                return float(v)
        start, moves = _path(plan, shot, actor)
        x = _lagged_x(start, moves, t, shot.t0) if lagged else _path_x(start, moves, t)
        return None if x is None else x * w

    # ---- движение на всю сцену ----
    zm, xm, ym, drift, orbit = 1.0, 0.0, 0.0, 0.0, 0.0
    for ev in events:
        if not _is_move(ev, shot) or ev.kind == "static":
            continue
        a = clamp(ev.amount)
        u = ease("in_out", window(t, ev.t0, ev.t1))
        if ev.kind in ("zoom_in", "zoom_out"):
            k = u if ev.kind == "zoom_in" else 1.0 - u
            zm *= 1.0 + 0.3 * a * k
            fx = focus_x(ev.focus)
            if fx is not None:
                xm += (fx - w / 2.0) * 0.6 * k
        elif ev.kind in ("pan_left", "pan_right"):
            amp = w * max(0.06, 0.25 * a)
            xm += amp * (1.0 - 2.0 * u) * (1.0 if ev.kind == "pan_left" else -1.0)
        elif ev.kind == "follow":
            fx = focus_x(ev.focus, lagged=True)
            if fx is not None:
                xm += (fx - w / 2.0) * 0.85
            zm *= 1.06 + 0.08 * a
        elif ev.kind == "orbit":
            s = 1.0 - 2.0 * u
            drift += MAX_DRIFT * w * (0.4 + 0.6 * a) * s
            orbit += -(0.4 + 0.6 * a) * 0.6 * s
            zm *= 1.04
            fx = focus_x(ev.focus)
            if fx is not None:
                xm += (fx - w / 2.0) * 0.4

    # ---- биты: удержание (zoom_in/zoom_out/focus/reset) и всплески (shake/punch) ----
    hz, hx, mw = 1.0, 0.0, 1.0
    pz, px = 1.0, 0.0
    shx = shy = rot = 0.0
    zoomed = False
    for ev in events:
        if _is_move(ev, shot) or t < ev.t0:
            continue
        a = clamp(ev.amount)
        tau = t - ev.t0
        if ev.kind == "shake":
            if tau < 0.7:
                amp = (4.0 + 10.0 * a) * k720
                e = math.exp(-12.0 * tau)
                shx += amp * e * math.sin(70.0 * tau)
                shy += 0.7 * amp * e * math.sin(53.0 * tau + 1.3)
                rot += 0.008 * (0.5 + a) * e * math.sin(41.0 * tau + 0.7)
            continue
        if ev.kind == "punch":
            hold_end = max(ev.t0 + 0.3, min(ev.t1, ev.t0 + 1.5))
            k = ease_out_back(window(t, ev.t0, ev.t0 + 0.3)) * (1.0 - ease("in_out", window(t, hold_end,
                                                                                            hold_end + 0.35)))
            if k:
                pz *= 1.0 + (0.1 + 0.12 * a) * k
                fx = focus_x(ev.focus)
                if fx is not None:
                    px += (fx - w / 2.0) * 0.35 * k
            continue
        dur = 0.4 if ev.kind == "reset" else max(0.25, min(ev.t1 - ev.t0, 0.8))
        u = ease("in_out", window(t, ev.t0, ev.t0 + dur))
        tz, tx = hz, hx
        if ev.kind == "zoom_in":
            tz = 1.15 + 0.35 * a
            fx = focus_x(ev.focus)
            tx = (fx - w / 2.0) * 0.8 if fx is not None else 0.0
            zoomed = True
        elif ev.kind == "focus":
            tz = 1.1 + 0.15 * a
            fx = focus_x(ev.focus)
            tx = (fx - w / 2.0) * 0.9 if fx is not None else hx
            zoomed = True
        elif ev.kind == "zoom_out":
            tz, tx = (1.0, 0.0) if zoomed else (1.0 - 0.1 * a, 0.0)
            zoomed = False
        elif ev.kind == "reset":
            tz, tx = 1.0, 0.0
            mw *= 1.0 - u
            zoomed = False
        hz = lerp(hz, tz, u)
        hx = lerp(hx, tx, u)

    zoom = (1.0 + (zm - 1.0) * mw) * hz * pz
    cam = Cam(x=xm * mw + hx + px, y=ym * mw, zoom=zoom, rot=rot, shake_x=shx, shake_y=shy, drift=drift * mw,
              orbit=orbit * mw)
    return clamp_cam(cam, w, h)


def clamp_cam(cam: Cam, w: int, h: int) -> Cam:
    """Зажать камеру в пределы, под которые рисуются поля фона; нечисловое — в покой."""
    def fin(v: float, d: float = 0.0) -> float:
        return v if math.isfinite(v) else d

    k720 = h / 720.0
    cam.zoom = clamp(fin(cam.zoom, 1.0), ZOOM_MIN, ZOOM_MAX)
    cam.x = clamp(fin(cam.x), -MAX_PAN * w, MAX_PAN * w)
    cam.y = clamp(fin(cam.y), -MAX_TILT * h, MAX_TILT * h)
    cam.rot = clamp(fin(cam.rot), -MAX_ROT, MAX_ROT)
    cam.shake_x = clamp(fin(cam.shake_x), -SHAKE_MAX * k720, SHAKE_MAX * k720)
    cam.shake_y = clamp(fin(cam.shake_y), -SHAKE_MAX * k720, SHAKE_MAX * k720)
    cam.drift = clamp(fin(cam.drift), -MAX_DRIFT * w, MAX_DRIFT * w)
    cam.orbit = clamp(fin(cam.orbit), -1.0, 1.0)
    # мелочь — в ноль: камера в покое даёт целые сдвиги (быстрое копирование слоёв, без размытия)
    for name in ("x", "y", "shake_x", "shake_y", "drift"):
        if abs(getattr(cam, name)) < 1e-3:
            setattr(cam, name, 0.0)
    if abs(cam.zoom - 1.0) < 1e-5:
        cam.zoom = 1.0
    if abs(cam.rot) < 1e-6:
        cam.rot = 0.0
    return cam
