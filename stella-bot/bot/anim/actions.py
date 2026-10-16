"""Актёрская игра: поза персонажа в момент t — чистая функция (plan, actor, t).

Слои (design_wow §c.5): L0 — тело и перемещение (ходьба, прыжки, танец…), L1 — руки и жесты (машет, хлопает,
показывает…), L2 — лицо (эмоция, речь), L3 — жизнь (дыхание, моргание, саккады, вторичное движение) — всегда.
Клипы одного слоя смешиваются окном 0.18 с: углы — линейно со smoothstep-весом, дискретное (форма кисти, рта) —
переключается на весе 0.5. Каждое действие — набор ключевых поз-чисел от τ (0..1 внутри клипа); принципы
анимации встроены: замах перед большим движением, сжатие-растяжение с сохранением объёма, перелёт пружиной,
дуги (интерполяция углов), моменты «живой паузы».

Видимость: актёр не участвует в сцене, ещё не появился (appear), уже исчез (poof) или ушёл за кадр → visible=False.
Слушатели смотрят на говорящего (глаза ±0.6 и голова на 0.2) — одно правило, которое делает сцены живыми.
"""

from __future__ import annotations

import bisect
import math
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable

from .chars.look import BUILDS, HUMAN, Build
from .ease import clamp, ease, ease_out_back, hash01, lerp, smoothstep
from .layout import char_height
from .life import actor_seed, blink, idle, lip, saccade, spring_lag, swing, word_starts
from .model import ActorFrame, ActorShot, Clip, EmotionSpan, Line, LookSpan, MarkEvent, Plan, Pose

FADE = 0.18  # окно смешивания клипов, с
EMO_FADE = 0.25  # смена эмоции
MOVES = frozenset({"walk", "walk_in", "walk_out", "run", "fly"})
TALK_KINDS = frozenset({"say", "shout", "whisper"})
REST_YAW = 0.25  # стоя «вполоборота» к тому, куда смотрит
STRIDE = {"walk": 0.42, "walk_in": 0.42, "walk_out": 0.42, "run": 0.8, "fly": 1.0}  # шаг цикла, доли роста
AUTO_MARK = {
    "excited": "sparkles", "love": "hearts", "angry": "anger", "surprised": "exclaim", "scared": "sweat",
    "sleepy": "zzz", "dizzy": "dizzy", "thinking": "question", "embarrassed": "sweat", "proud": "sparkles",
}
LOOP_MARKS = frozenset({"zzz", "dizzy"})
MARK_SECONDS = 1.6
HAPPY_TAIL = frozenset({"happy", "excited", "laugh", "love", "proud"})
GIBBERISH = "ба-ла ла бу ба-ла ла"

P = dict  # «поза-словарь»: канал → значение


# ---------- индекс плана (кеш на процесс; сам план не меняется) ----------
@dataclass
class _ActorIx:
    shots: dict[int, list[Clip]]
    emotions: list[EmotionSpan]
    emo_t0: list[float]
    marks: list[MarkEvent]
    lines: list[Line]
    looks: list[LookSpan]
    aseed: int
    build: Build
    forced_blinks: tuple[float, ...]
    base: str


@dataclass
class _Index:
    ref: Any
    key: tuple
    actors: dict[str, _ActorIx] = field(default_factory=dict)
    place: dict[tuple[str, int], ActorShot] = field(default_factory=dict)
    lines_by_shot: dict[int, list[Line]] = field(default_factory=dict)


_CACHE: dict[int, _Index] = {}


def _plan_key(plan: Plan) -> tuple:
    return (len(plan.clips), len(plan.lines), len(plan.emotions), len(plan.marks), len(plan.looks),
            len(plan.placements), len(plan.shots), round(plan.duration, 6), plan.seed)


def _shot_of(plan: Plan, t: float) -> int:
    return plan.shot_at(t).index


def _index(plan: Plan) -> _Index:
    key = _plan_key(plan)
    ix = _CACHE.get(id(plan))
    if ix is not None and ix.ref() is plan and ix.key == key:
        return ix
    try:
        ref = weakref.ref(plan)
    except TypeError:  # pragma: no cover — на всякий случай
        def ref(plan: Plan = plan) -> Plan:
            return plan
    ix = _Index(ref, key)
    for p in plan.placements:
        ix.place[(p.actor, p.shot)] = p
    for a, cast in plan.cast.items():
        shots: dict[int, list[Clip]] = {}
        for c in plan.clips:
            if c.actor == a:
                shots.setdefault(_shot_of(plan, c.t0 + 1e-6), []).append(c)
        for lst in shots.values():
            lst.sort(key=lambda c: (c.t0, c.layer))
        emos = sorted((e for e in plan.emotions if e.actor == a), key=lambda e: e.t0)
        turns = [c.t0 for c in plan.clips if c.actor == a and (c.action in ("turn", "spin") or c.action in MOVES)]
        ix.actors[a] = _ActorIx(
            shots=shots, emotions=emos, emo_t0=[e.t0 for e in emos],
            marks=[m for m in plan.marks if m.actor == a], lines=[ln for ln in plan.lines if ln.actor == a],
            looks=[lk for lk in plan.looks if lk.actor == a], aseed=actor_seed(plan.seed, a),
            build=BUILDS.get(cast.base, HUMAN), forced_blinks=tuple(sorted(turns)), base=cast.base,
        )
    for ln in plan.lines:
        ix.lines_by_shot.setdefault(_shot_of(plan, ln.t0 + 1e-6), []).append(ln)
    if len(_CACHE) > 16:
        _CACHE.clear()
    _CACHE[id(plan)] = ix
    return ix


# ---------- помощники ----------
def _trap(tau: float, a: float = 0.15, d: float = 0.2) -> float:
    """Путь 0..1 с трапецией скорости: разгон a, торможение d (ходьба не «линейная»)."""
    tau = clamp(tau)
    v = 1.0 / (1.0 - a / 2 - d / 2)
    if tau < a:
        return v * tau * tau / (2 * a)
    if tau < 1 - d:
        return v * (a / 2 + (tau - a))
    u = 1 - tau
    return 1.0 - v * u * u / (2 * d)


def _trap_speed(tau: float, a: float = 0.15, d: float = 0.2) -> float:
    """Скорость пути (доля от максимальной) в момент tau."""
    tau = clamp(tau)
    if tau < a:
        return tau / a
    if tau > 1 - d:
        return (1 - tau) / d
    return 1.0


def _env(lt: float, dur: float, t_in: float = 0.2, t_out: float = 0.2) -> float:
    """Огибающая действия: плавно вошли за t_in, плавно вышли за t_out до конца."""
    if dur <= 0:
        return 0.0
    t_in = min(t_in, dur / 2)
    t_out = min(t_out, dur / 2)
    return min(smoothstep(lt / t_in) if t_in > 0 else 1.0, smoothstep((dur - lt) / t_out) if t_out > 0 else 1.0)


def _bell(x: float) -> float:
    """Колокол 0→1→0 на x ∈ [0, 1]."""
    x = clamp(x)
    return math.sin(math.pi * x)


def fwd_arm(side: int, up: float, fore: float) -> tuple[float, float]:
    """Рука вперёд-назад: up — угол плеча от «вниз» (+ вперёд), fore — угол предплечья. → (плечо, локоть)."""
    if side > 0:
        return up, fore - up
    return -up, up - fore


def fwd_leg(side: int, thigh: float, knee: float) -> tuple[float, float]:
    """Нога вперёд-назад: thigh — угол бедра (+ вперёд), knee — сгиб колена."""
    return side * thigh, knee


def _rot(v: tuple[float, float], a: float) -> tuple[float, float]:
    ca, sa = math.cos(a), math.sin(a)
    return v[0] * ca - v[1] * sa, v[0] * sa + v[1] * ca


def _shoulder(b: Build, s: int, lean: float, bob: float, yaw: float) -> tuple[float, float]:
    narrow = 1 - 0.35 * abs(yaw)
    v = _rot((s * b.shoulder * narrow + yaw * 6, -(b.torso - 8)), lean + b.lean0)
    return v[0], b.hip_y + bob + v[1]


def _head_c(b: Build, lean: float, bob: float, yaw: float) -> tuple[float, float]:
    n = _rot((0.0, -b.torso), lean + b.lean0)
    h = _rot((yaw * 3, -b.neck), lean + b.lean0)
    return n[0] + h[0], b.hip_y + bob + n[1] + h[1]


def ik(b: Build, side: int, target: tuple[float, float], lean: float = 0.0, bob: float = 0.0,
       yaw: float = 0.0) -> tuple[float, float]:
    """Двухзвенная обратная кинематика руки: (плечо, локоть), чтобы кисть пришла в target (единицы куклы).
    Недосягаемое — кисть тянется в ту сторону; локоть — наружу."""
    sx, sy = _shoulder(b, side, lean, bob, yaw)
    dx, dy = (target[0] - sx) * side, target[1] - sy
    l1, l2 = b.upper_arm, b.forearm
    d = math.hypot(dx, dy)
    d = clamp(d, abs(l1 - l2) + 1.0, l1 + l2 - 0.5)
    th = math.atan2(dx, dy)
    al = math.acos(clamp((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d), -1.0, 1.0))
    best = None
    for a in (th + al, th - al):
        ex, ey = l1 * math.sin(a), l1 * math.cos(a)
        tx, ty = d * math.sin(th), d * math.cos(th)
        fa = math.atan2(tx - ex, ty - ey)
        cand = (ex, a, fa - a)
        if best is None or cand[0] > best[0]:
            best = cand
    assert best is not None
    bend = (best[2] + math.pi) % (2 * math.pi) - math.pi
    return best[1], bend


# ---------- контекст действия ----------
@dataclass
class _Ctx:
    t: float  # абсолютное время
    lt: float  # время от начала клипа
    tau: float  # 0..1 внутри клипа
    dur: float
    params: dict
    b: Build
    aseed: int
    units_w: float  # ширина кадра в единицах куклы
    x: float  # где стоит (доли кадра)
    facing: int
    base: P


def _units(c: _Ctx, frac: float) -> float:
    return frac * c.units_w


def up_angle(b: Build) -> float:
    """Угол «руки вверх»: у широкоголовых зверей — ниже и шире, иначе кисти прячутся за головой."""
    return 2.5 if b.body in ("human", "alien", "robot") else 2.1


# ---------- действия ----------
def a_idle(c: _Ctx) -> P:
    return {}


def _walk_like(c: _Ctx, kind: str) -> P:
    x0 = float(c.params.get("x0", c.x))
    x1 = float(c.params.get("x1", c.x))
    dist_h = abs(x1 - x0) * c.units_w / 300.0
    run = kind == "run"
    if dist_h > 1e-4:
        half = max(2, round(2 * dist_h / STRIDE.get(kind, 0.42)))
        phase = math.pi * half * _trap(c.tau)
        k = 0.45 + 0.55 * smoothstep(_trap_speed(c.tau) * 1.5)
    else:  # шаг на месте
        phase = 2 * math.pi * (2.6 if run else 1.6) * c.lt
        k = _env(c.lt, c.dur, 0.25, 0.25)
    s, co = math.sin(phase), math.cos(phase)
    if run:
        amp, knee, lean, bob_a = 0.8, 1.3, 0.2, 10.0
    else:
        amp, knee, lean, bob_a = 0.42, 0.75, 0.07, 5.0
    out: P = {
        "leg_l0": amp * s * k, "leg_l1": knee * max(0.0, -co) * k,
        "leg_r0": amp * s * k, "leg_r1": knee * max(0.0, co) * k,
        "bob": (-bob_a * abs(co) + bob_a * 0.4) * k, "lean": lean * k, "yaw": 0.45, "look_x": 0.35,
    }
    if run:
        for side, ph in ((1, s), (-1, s)):
            up = -0.75 * ph * side * k
            a, bend = fwd_arm(side, up, up + 1.5 * k)
            out[f"arm_{'r' if side > 0 else 'l'}0"], out[f"arm_{'r' if side > 0 else 'l'}1"] = a, bend
        out["hand_l"] = out["hand_r"] = "fist"
        # пыль от каждого шага
        if dist_h > 1e-4 and k > 0.6:
            half = max(2, round(2 * dist_h / STRIDE["run"]))
            rate = math.pi * half * _trap_speed(c.tau) / (c.dur * (1 - 0.175))
            if rate > 1e-3:
                since = ((phase - math.pi / 2) % math.pi) / rate
                if since < 0.35:
                    out["marks"] = [("_dust", since / 0.35)]
    else:
        a = 0.18 - 0.42 * s * k
        out.update({"arm_l0": a, "arm_l1": 0.35, "arm_r0": a, "arm_r1": 0.35})
    return out


def a_walk(c: _Ctx) -> P:
    return _walk_like(c, "walk")


def a_run(c: _Ctx) -> P:
    return _walk_like(c, "run")


def _jump(c: _Ctx, h: float, arms_up: float, crouch_end: float = 0.18, land: float = 0.78) -> P:
    tau = c.tau
    out: P = {}
    if tau < crouch_end:  # замах: присели, руки назад
        k = smoothstep(tau / crouch_end)
        out.update(squash=1 - 0.22 * k, bob=10 * k, lean=0.12 * k,
                   leg_l0=fwd_leg(-1, 0.45 * k, 0)[0], leg_r0=fwd_leg(1, 0.45 * k, 0)[0],
                   leg_l1=0.9 * k, leg_r1=0.9 * k)
        for side, nm in ((1, "r"), (-1, "l")):
            a, bend = fwd_arm(side, -0.7 * k, -0.4 * k)
            out[f"arm_{nm}0"], out[f"arm_{nm}1"] = a, bend
    elif tau < land:  # полёт: парабола, растяжение на взлёте, ноги поджаты в верхней точке
        u = (tau - crouch_end) / (land - crouch_end)
        lift = h * 300.0 * 4 * u * (1 - u)
        stretch = 1 + 0.2 * (1 - smoothstep(u / 0.3))
        tuck = math.sin(math.pi * u)
        out.update(bob=-lift, squash=stretch if u < 0.5 else 1 + 0.06 * (u - 0.5), lean=-0.04,
                   leg_l0=fwd_leg(-1, 0.5 * tuck, 0)[0], leg_r0=fwd_leg(1, 0.3 * tuck, 0)[0],
                   leg_l1=0.9 * tuck, leg_r1=0.6 * tuck)
        up = smoothstep(u / 0.2)
        out.update(arm_l0=lerp(0.3, arms_up, up), arm_l1=0.25, arm_r0=lerp(0.3, arms_up, up), arm_r1=0.25)
    else:  # приземление: сплющило и пружинит обратно
        v = (tau - land) / (1 - land)
        sq = 0.25 * math.exp(-4 * v) * math.cos(9 * v) * (1 - v)
        down = (1 - v) ** 2
        out.update(squash=1 - sq, bob=10 * down, leg_l1=0.8 * down, leg_r1=0.8 * down,
                   leg_l0=fwd_leg(-1, 0.4 * down, 0)[0], leg_r0=fwd_leg(1, 0.4 * down, 0)[0],
                   arm_l0=lerp(0.25, arms_up, (1 - smoothstep(v / 0.6)) * 0.7),
                   arm_r0=lerp(0.25, arms_up, (1 - smoothstep(v / 0.6)) * 0.7), arm_l1=0.3, arm_r1=0.3)
        if v < 0.4:
            out["marks"] = [("_dust", v / 0.4)]
    return out


def a_jump(c: _Ctx) -> P:
    return _jump(c, float(c.params.get("height", 0.5)), up_angle(c.b) - 0.1)


def a_hop(c: _Ctx) -> P:
    return _jump(c, float(c.params.get("height", 0.25)), 1.3, 0.22, 0.75)


def a_wave(c: _Ctx) -> P:
    side = -1 if c.params.get("hand") == "l" else 1
    nm = "r" if side > 0 else "l"
    w = min(ease_out_back(c.lt / 0.25), smoothstep((c.dur - c.lt) / 0.22))
    # предплечье качается наружу от головы (2.4..3.05 рад), чтобы ладонь всегда была видна сбоку
    fore = 2.72 + 0.32 * math.sin(12.0 * c.lt)
    return {f"arm_{nm}0": lerp(0.25, 2.0, w), f"arm_{nm}1": lerp(0.3, fore - 2.0, w), f"hand_{nm}": "open",
            "head_tilt": -0.08 * side * w}


def a_clap(c: _Ctx) -> P:
    e = _env(c.lt, c.dur, 0.2, 0.2)
    ph = (c.lt * 4.0) % 1.0
    together = (0.5 + 0.5 * math.cos(2 * math.pi * ph)) ** 3
    out: P = {"yaw": 0.05, "hand_l": "open", "hand_r": "open"}
    for side, nm in ((1, "r"), (-1, "l")):
        apart = ik(c.b, side, (side * 20, c.b.hip_y - c.b.torso * 0.62))
        meet = ik(c.b, side, (side * 4, c.b.hip_y - c.b.torso * 0.66))
        a = lerp(apart[0], meet[0], together)
        bnd = lerp(apart[1], meet[1], together)
        out[f"arm_{nm}0"] = lerp(0.25, a, e)
        out[f"arm_{nm}1"] = lerp(0.3, bnd, e)
    if e > 0.8 and ph < 0.2:
        out["marks"] = [("_spark", ph / 0.2)]
    return out


def a_point(c: _Ctx) -> P:
    lt, d = c.lt, c.dur
    if lt < 0.12:  # замах назад
        k = smoothstep(lt / 0.12)
        a, bnd = lerp(0.25, -0.2, k), 0.3 + 0.6 * k
    else:
        k = min(ease_out_back((lt - 0.12) / 0.22), smoothstep((d - lt) / 0.22))
        a, bnd = lerp(-0.2 if lt < 0.4 else 0.25, 1.45, k), lerp(0.9 if lt < 0.4 else 0.3, 0.05, k)
    return {"arm_r0": a, "arm_r1": bnd, "hand_r": "point" if lt > 0.1 else "open", "look_x": 0.85,
            "lean": 0.05 * smoothstep(lt / 0.3)}


def _gesture(kind: str, w: float, shout: bool) -> P:
    if w <= 0:
        return {}
    big = 1.25 if shout else 1.0
    if kind == "palm":
        return {"arm_r0": lerp(0.25, 0.85 * big, w), "arm_r1": lerp(0.3, 1.1, w), "hand_r": "open"}
    if kind == "point":
        return {"arm_r0": lerp(0.25, 1.2 * big, w), "arm_r1": lerp(0.3, 0.15, w), "hand_r": "point"}
    return {"arm_r0": lerp(0.25, 0.8 * big, w), "arm_r1": lerp(0.3, 1.35, w), "arm_l0": lerp(0.25, 0.8 * big, w),
            "arm_l1": lerp(0.3, 1.35, w), "hand_r": "open", "hand_l": "open", "head_tilt": 0.1 * w}


def talk_gestures(text: str, t0: float, t: float, cps: float, aseed: int, shout: bool = False,
                  rate: float = 0.35) -> P:
    """Жесты в такт речи: раз в 2–4 слова — раскрытая ладонь, указание или лёгкое пожатие плечами (0.55 с);
    кивок головой на начало слова."""
    starts = word_starts(text)
    if not starts:
        return {}
    pos = (t - t0) * cps
    out: P = {}
    last = -10
    for i, ci in enumerate(starts):
        ts = t0 + ci / cps
        if ts > t:
            break
        if i - last >= 2 and hash01(aseed, "gesture", round(t0, 3), i) < rate:
            last = i
            lt = t - ts
            if lt < 0.6:
                kind = ("palm", "point", "shrug")[int(hash01(aseed, "gk", round(t0, 3), i) * 3) % 3]
                out = _gesture(kind, _bell(lt / 0.6) ** 0.6, shout)
                out["_gw"] = _bell(lt / 0.6) ** 0.6
    # кивок на начало слова
    for ci in starts:
        if ci <= pos:
            since = (pos - ci) / cps
            if since < 0.25:
                nod = math.exp(-since / 0.08) * (1 - since / 0.25)
                out["_nod"] = max(out.get("_nod", 0.0), nod)
    return out


def a_talk(c: _Ctx) -> P:
    out = talk_gestures(GIBBERISH * 3, c.t - c.lt, c.t, 13.0, c.aseed, rate=0.5)
    gw = out.pop("_gw", 0.0)
    nod = out.pop("_nod", 0.0)
    e = _env(c.lt, c.dur, 0.15, 0.15)
    for k in list(out):
        if k.startswith("arm_"):
            out[k] = lerp(c.base.get(k, 0.25), out[k], e)
    out["head_tilt"] = out.get("head_tilt", 0.0) + 0.04 * nod
    out["look_y"] = 0.25 * nod
    del gw
    return out


def a_laugh(c: _Ctx) -> P:
    e = _env(c.lt, c.dur, 0.2, 0.25)
    out: P = {"lean": -0.12 * e + 0.03 * math.sin(2 * math.pi * 6 * c.t) * e,
              "bob": -4 * abs(math.sin(2 * math.pi * 3 * c.lt)) * e, "head_tilt": -0.08 * e}
    for side, nm in ((1, "r"), (-1, "l")):
        a, bnd = ik(c.b, side, (side * 8, c.b.hip_y - c.b.torso * 0.3), -0.12 * e)
        out[f"arm_{nm}0"], out[f"arm_{nm}1"] = lerp(0.25, a, e), lerp(0.3, bnd, e)
    return out


def a_cry(c: _Ctx) -> P:
    e = _env(c.lt, c.dur, 0.25, 0.25)
    hc = _head_c(c.b, 0.05, 0.0, 0.0)
    out: P = {"squash": 1 + 0.025 * math.sin(2 * math.pi * 3 * c.lt) * e, "head_tilt": 0.06 * e, "lean": 0.05 * e,
              "hand_l": "fist", "hand_r": "fist"}
    for side, nm in ((1, "r"), (-1, "l")):
        a, bnd = ik(c.b, side, (hc[0] + side * c.b.head_r * 0.42, hc[1] + c.b.head_r * 0.35), 0.05)
        out[f"arm_{nm}0"], out[f"arm_{nm}1"] = lerp(0.25, a, e), lerp(0.3, bnd, e)
    return out


def _dance(c: _Ctx) -> P:
    style = c.params.get("style", "bounce")
    lt = c.lt
    e = _env(lt, c.dur, 0.2, 0.25)
    out: P = {}
    if style == "sway":
        sw = math.sin(2 * math.pi * 1.0 * lt)
        out = {"lean": 0.15 * sw, "head_tilt": -0.1 * sw, "dx": 6 * sw, "yaw": 0.15 * sw,
               "arm_l0": 1.5 + 0.45 * sw, "arm_l1": 0.5, "arm_r0": 1.5 - 0.45 * sw, "arm_r1": 0.5,
               "leg_l1": 0.25 * max(0.0, sw), "leg_r1": 0.25 * max(0.0, -sw), "hand_l": "open", "hand_r": "open"}
    elif style == "robot":
        step = int(lt / 0.25)
        frac = (lt % 0.25) / 0.25
        # углы «под 90°», кисти — в стороны от большой головы, а не за ней
        poses = (((1.57, 0.95), (1.57, -1.57), 0.15, 0.3), ((1.57, -1.57), (1.57, 0.95), -0.15, -0.3),
                 ((0.2, 1.37), (1.57, 0.0), 0.0, 0.4), ((1.57, 0.0), (0.2, 1.37), 0.12, -0.4),
                 ((2.2, 0.0), (0.3, 0.0), -0.12, 0.0), ((0.3, 0.0), (2.2, 0.0), 0.12, 0.0))

        def pick(i: int) -> tuple:
            return poses[int(hash01(c.aseed, "robot", i) * len(poses)) % len(poses)]
        cur, prev = pick(step), pick(step - 1)
        k = smoothstep(frac / 0.25)  # быстрый «щелчок» и пауза — анимация «по двойкам»
        out = {"arm_r0": lerp(prev[0][0], cur[0][0], k), "arm_r1": lerp(prev[0][1], cur[0][1], k),
               "arm_l0": lerp(prev[1][0], cur[1][0], k), "arm_l1": lerp(prev[1][1], cur[1][1], k),
               "head_tilt": lerp(prev[2], cur[2], k), "yaw": lerp(prev[3], cur[3], k),
               "bob": 3 * (1 - k), "hand_l": "open", "hand_r": "open", "squash": 1 - 0.03 * (1 - k)}
    elif style == "disco":
        beat = lt * 2.0
        up = 0.5 + 0.5 * math.cos(math.pi * beat)
        hip = math.sin(math.pi * beat)
        la, lb = ik(c.b, -1, (-(c.b.waist_w + 4), c.b.hip_y - 6))
        out = {"arm_r0": lerp(-0.45, up_angle(c.b) + 0.05, up), "arm_r1": 0.0,
               "hand_r": "point", "arm_l0": la, "arm_l1": lb,
               "hand_l": "fist", "lean": 0.08 * hip, "dx": 5 * hip, "head_tilt": -0.12 * (up - 0.5),
               "leg_l1": 0.35 * max(0.0, hip), "leg_r1": 0.35 * max(0.0, -hip), "yaw": 0.2,
               "bob": -3 * abs(math.sin(math.pi * beat))}
    elif style == "spin":
        out = _spin_core(lt, c.dur, max(1, int(c.dur / 1.4)))
        out["bob"] = -6 * abs(math.sin(2 * math.pi * lt))
    elif style == "wiggle":
        w3 = 2 * math.pi * 3.0 * lt
        out = {"lean": 0.12 * math.sin(w3), "squash": 1 + 0.05 * math.sin(w3 + 1.2), "head_tilt": 0.15 * math.sin(w3),
               "arm_r0": 1.2 + 0.6 * math.sin(w3), "arm_r1": 0.8 * math.sin(w3 + 1.0),
               "arm_l0": 1.2 + 0.6 * math.sin(w3 + 2.0), "arm_l1": 0.8 * math.sin(w3 + 3.0),
               "dx": 3 * math.sin(w3 * 0.5), "hand_l": "open", "hand_r": "open"}
    else:  # bounce
        beat = lt * 2.2
        b = abs(math.sin(math.pi * beat))
        r_up = 0.5 + 0.5 * math.sin(math.pi * beat * 0.5)
        out = {"bob": -10 * b + 3, "squash": 1 + 0.07 * (b - 0.5), "leg_l1": 0.35 * (1 - b), "leg_r1": 0.35 * (1 - b),
               "leg_l0": -0.12 * (1 - b), "leg_r0": 0.12 * (1 - b),
               "arm_r0": lerp(0.6, up_angle(c.b), r_up), "arm_r1": 0.3,
               "arm_l0": lerp(0.6, up_angle(c.b), 1 - r_up), "arm_l1": 0.3,
               "head_tilt": 0.1 * math.sin(math.pi * beat), "hand_l": "fist", "hand_r": "fist", "yaw": 0.1}
    for k in list(out):
        if k in ("hand_l", "hand_r", "flip", "marks"):
            continue
        if k in ("squash",):
            out[k] = lerp(1.0, out[k], e)
        elif k in c.base:
            out[k] = lerp(c.base[k], out[k], e)
        else:
            out[k] = out[k] * e
    if lt < 2.0:
        out["marks"] = [("music", lt / 2.0)]
    return out


def _spin_core(lt: float, dur: float, turns: int) -> P:
    tau = clamp(lt / dur) if dur > 0 else 1.0
    phi = turns * ease("in_out", tau)
    q = phi % 1.0
    if phi >= turns - 1e-6:
        q = 0.0
    if q < 0.5:
        yaw, flip = 2 * q, False
    else:
        yaw, flip = 2 * (1 - q), True
    squash = 1 - 0.12 * _bell(tau / 0.15 if tau < 0.15 else 0) - 0.12 * _bell((tau - 0.85) / 0.15 if tau > 0.85 else 0)
    spread = _env(lt, dur, 0.15, 0.2)
    return {"yaw": yaw * 0.95, "flip": flip, "squash": squash, "arm_l0": lerp(0.25, 1.25, spread),
            "arm_r0": lerp(0.25, 1.25, spread), "arm_l1": 0.2, "arm_r1": 0.2}


def a_spin(c: _Ctx) -> P:
    return _spin_core(c.lt, c.dur, int(c.params.get("turns", 1)))


def a_fly(c: _Ctx) -> P:
    h = float(c.params.get("height", 0.3))
    up = smoothstep(c.tau / 0.25) * smoothstep((1 - c.tau) / 0.25)
    lift = h * 300 * up + 6 * math.sin(2 * math.pi * 0.8 * c.lt) * up
    trail = up
    out: P = {"bob": -lift, "lean": 0.25 * trail, "yaw": 0.5, "look_x": 0.5,
              "leg_l0": fwd_leg(-1, -0.3 * trail, 0)[0], "leg_r0": fwd_leg(1, -0.45 * trail, 0)[0],
              "leg_l1": 0.5 * trail, "leg_r1": 0.7 * trail, "hand_r": "fist"}
    a, bnd = fwd_arm(1, 2.4 * trail, 2.4 * trail)
    out["arm_r0"], out["arm_r1"] = lerp(0.25, a, trail), lerp(0.3, bnd, trail)
    a, bnd = fwd_arm(-1, -0.6 * trail, -0.4 * trail)
    out["arm_l0"], out["arm_l1"] = lerp(0.25, a, trail), lerp(0.3, bnd, trail)
    out["wings"] = 1.0
    return out


def a_float(c: _Ctx) -> P:
    e = _env(c.lt, c.dur, 0.4, 0.4)
    bob = -(24 + 8 * math.sin(2 * math.pi * 0.5 * c.lt)) * e
    sw = math.sin(2 * math.pi * 0.5 * c.lt + 1)
    return {"bob": bob, "leg_l1": 0.35 * e, "leg_r1": 0.45 * e, "leg_l0": fwd_leg(-1, 0.15 * e, 0)[0],
            "leg_r0": fwd_leg(1, 0.05 * e, 0)[0], "arm_l0": 0.25 + 0.4 * e + 0.1 * sw,
            "arm_r0": 0.25 + 0.4 * e - 0.1 * sw,
            "arm_l1": 0.5, "arm_r1": 0.5, "lean": 0.04 * sw * e, "wings": e}


SIT_BOB = 56.0


def _sit_pose(b: Build, k: float) -> P:
    drop = (b.thigh + b.shin) * 0.8
    return {"bob": drop * k, "leg_l0": fwd_leg(-1, 1.45 * k, 0)[0], "leg_r0": fwd_leg(1, 1.4 * k, 0)[0],
            "leg_l1": 0.2 * k, "leg_r1": 0.15 * k, "arm_l0": lerp(0.25, 0.45, k), "arm_r0": lerp(0.25, 0.45, k),
            "arm_l1": lerp(0.3, 0.0, k), "arm_r1": lerp(0.3, 0.0, k), "lean": -0.03 * k,
            "yaw": lerp(REST_YAW, 0.55, k)}  # вполоборота — ноги «вперёд» читаются


def a_sit(c: _Ctx) -> P:
    k = min(smoothstep(c.lt / 0.35), smoothstep((c.dur - c.lt) / 0.3))
    return _sit_pose(c.b, k)


def a_sleep(c: _Ctx) -> P:
    k = min(smoothstep(c.lt / 0.4), smoothstep((c.dur - c.lt) / 0.3))
    out = _sit_pose(c.b, k)
    breath = math.sin(2 * math.pi * 0.35 * c.lt)
    out.update(head_tilt=0.22 * k + 0.03 * breath * k, lean=0.08 * k, squash=1 + 0.03 * breath * k,
               blink=1.0 if k > 0.5 else 0.0, look_y=0.6 * k)
    return out


def a_think(c: _Ctx) -> P:
    e = _env(c.lt, c.dur, 0.3, 0.25)
    hc = _head_c(c.b, 0.0, 0.0, 0.25)
    a, bnd = ik(c.b, 1, (hc[0] + 6, hc[1] + c.b.head_r * 0.82))
    return {"arm_r0": lerp(c.base.get("arm_r0", 0.25), a, e), "arm_r1": lerp(c.base.get("arm_r1", 0.3), bnd, e),
            "hand_r": "fist", "head_tilt": 0.1 * e, "look_x": 0.5 * e, "look_y": -0.6 * e}


def a_shrug(c: _Ctx) -> P:
    e = _env(c.lt, c.dur, 0.2, 0.3)
    return {"arm_l0": lerp(0.25, 0.95, e), "arm_l1": lerp(0.3, 1.55, e), "arm_r0": lerp(0.25, 0.95, e),
            "arm_r1": lerp(0.3, 1.55, e), "hand_l": "open", "hand_r": "open", "head_tilt": 0.14 * e,
            "squash": 1 + 0.03 * e, "yaw": 0.05}


def a_facepalm(c: _Ctx) -> P:
    e = _env(c.lt, c.dur, 0.25, 0.3)
    lean = 0.14 * e
    hc = _head_c(c.b, lean, 0.0, 0.1)
    a, bnd = ik(c.b, 1, (hc[0] + 2, hc[1] + c.b.head_r * 0.15), lean)
    return {"lean": lean, "head_tilt": 0.22 * e, "arm_r0": lerp(0.25, a, e), "arm_r1": lerp(0.3, bnd, e),
            "hand_r": "open", "look_y": 0.8 * e, "yaw": 0.1, "blink": 0.0}


def a_nod(c: _Ctx) -> P:
    n = max(0.0, math.sin(2 * math.pi * 2.0 * c.lt / max(0.8, c.dur))) * _env(c.lt, c.dur, 0.1, 0.15)
    return {"look_y": 1.0 * n, "lean": 0.09 * n, "head_tilt": 0.07 * n, "bob": 3 * n, "squash": 1 - 0.02 * n}


def a_shake_head(c: _Ctx) -> P:
    e = _env(c.lt, c.dur, 0.12, 0.2)
    s = math.sin(2 * math.pi * 3.0 * c.lt)
    return {"yaw": 0.45 * s * e, "look_x": -0.4 * s * e, "head_tilt": 0.03 * s * e}


def a_bow(c: _Ctx) -> P:
    e = _env(c.lt, c.dur, 0.3, 0.35)
    return {"lean": 0.38 * e, "look_y": 0.8 * e, "arm_l0": lerp(0.25, 0.05, e), "arm_r0": lerp(0.25, 0.05, e),
            "arm_l1": lerp(0.3, 0.05, e), "arm_r1": lerp(0.3, 0.05, e), "head_tilt": 0.1 * e,
            "yaw": lerp(REST_YAW, 0.62, e)}  # поклон вполоборота — наклон читается как «вперёд»


def _partner_units(c: _Ctx) -> float:
    tx = c.params.get("tx")
    if tx is None:
        return 80.0
    return max(30.0, abs(float(tx) - c.x) * c.units_w)


def a_hug(c: _Ctx) -> P:
    e = _env(c.lt, c.dur, 0.25, 0.3)
    d = _partner_units(c)
    lean = 0.1 * e
    squeeze = 0.5 + 0.5 * math.sin(2 * math.pi * 1.2 * c.lt)
    out: P = {"lean": lean, "squash": 1 - 0.025 * squeeze * e, "head_tilt": 0.12 * e, "yaw": 0.3,
              "hand_l": "open", "hand_r": "open"}
    for side, nm, tgt in ((1, "r", (d * 0.85, c.b.hip_y - c.b.torso * 0.62)),
                          (-1, "l", (d * 0.55, c.b.hip_y - c.b.torso * 0.45))):
        a, bnd = ik(c.b, side, tgt, lean, 0.0, 0.3)
        out[f"arm_{nm}0"], out[f"arm_{nm}1"] = lerp(0.25, a, e), lerp(0.3, bnd, e)
    return out


def a_high_five(c: _Ctx) -> P:
    lt, d = c.lt, c.dur
    dist = _partner_units(c)
    contact = min(0.42, d * 0.4)
    # чиби-руки коротки, а головы большие: ладони встречаются под подбородками, между актёрами
    up = ik(c.b, 1, (dist * 0.5, c.b.hip_y - c.b.torso * 1.02), 0.06)
    if lt < 0.12:
        k = smoothstep(lt / 0.12)
        a, bnd = lerp(0.25, -0.3, k), lerp(0.3, 0.6, k)
    else:
        k = min(ease_out_back((lt - 0.12) / (contact - 0.12)), smoothstep((d - lt) / 0.28))
        a, bnd = lerp(-0.3 if lt < contact else 0.25, up[0], k), lerp(0.6 if lt < contact else 0.3, up[1], k)
    out: P = {"arm_r0": a, "arm_r1": bnd, "hand_r": "open", "look_y": 0.2 * k, "look_x": 0.6, "yaw": 0.35}
    if lt >= contact:
        v = (lt - contact) / max(0.2, d - contact)
        out["bob"] = -10 * _bell(v / 0.5)
        out["squash"] = 1 + 0.05 * _bell(v / 0.5)
        if lt - contact < 0.35:
            out["marks"] = [("_spark", (lt - contact) / 0.35)]
    return out


def a_celebrate(c: _Ctx) -> P:
    lt, d = c.lt, c.dur
    out: P = {}
    j0, j1 = 0.12, min(0.62, d * 0.45)
    if lt < j0:
        k = smoothstep(lt / j0)
        out.update(squash=1 - 0.18 * k, bob=8 * k, leg_l1=0.7 * k, leg_r1=0.7 * k)
    elif lt < j1:
        u = (lt - j0) / (j1 - j0)
        out.update(bob=-0.2 * 300 * 4 * u * (1 - u), squash=1 + 0.12 * (1 - smoothstep(u / 0.3)),
                   leg_l1=0.6 * _bell(u), leg_r1=0.4 * _bell(u))
    else:
        v = (lt - j1) / max(0.1, d - j1)
        out.update(squash=1 - 0.15 * math.exp(-6 * v) * math.cos(10 * v) * (1 - v))
    e = min(smoothstep(lt / 0.15), smoothstep((d - lt) / 0.25))
    pump = 0.15 * math.sin(2 * math.pi * 4 * lt)
    up = up_angle(c.b)
    out.update(arm_l0=lerp(0.25, up + pump, e), arm_r0=lerp(0.25, up - pump, e), arm_l1=0.25, arm_r1=0.25,
               hand_l="fist", hand_r="fist")
    return out


def a_scared(c: _Ctx) -> P:
    lt, d = c.lt, c.dur
    back = ease_out_back(lt / 0.25) * (1 - smoothstep((lt - (d - 0.35)) / 0.35))
    shiver = math.sin(2 * math.pi * 12 * lt) * 1.5 * _env(lt, d, 0.2, 0.2)
    e = _env(lt, d, 0.12, 0.3)
    out: P = {"dx": -22 * back + shiver, "bob": -14 * _bell(min(1.0, lt / 0.25)) + 4 * e, "lean": -0.12 * e,
              "leg_l1": 0.3 * e, "leg_r1": 0.3 * e, "hand_l": "open", "hand_r": "open"}
    hc = _head_c(c.b, -0.12, 0.0, 0.2)
    for side, nm in ((1, "r"), (-1, "l")):
        a, bnd = ik(c.b, side, (side * 16 + 6, hc[1] + c.b.head_r * 1.2), -0.12 * e)
        out[f"arm_{nm}0"], out[f"arm_{nm}1"] = lerp(0.25, a, e), lerp(0.3, bnd, e)
    return out


def a_stomp(c: _Ctx) -> P:
    tau = c.tau
    out: P = {"hand_l": "fist", "hand_r": "fist"}
    hit = 0.3
    if tau < hit:
        k = smoothstep(tau / hit)
        out.update(leg_r0=fwd_leg(1, 0.7 * k, 0)[0], leg_r1=1.1 * k, lean=-0.06 * k, bob=-4 * k,
                   arm_l0=lerp(0.25, 0.9, k), arm_r0=lerp(0.25, 0.9, k), arm_l1=lerp(0.3, 1.6, k),
                   arm_r1=lerp(0.3, 1.6, k))
    else:
        v = (tau - hit) / (1 - hit)
        slam = smoothstep(v / 0.08)
        out.update(leg_r0=fwd_leg(1, 0.7 * (1 - slam), 0)[0], leg_r1=1.1 * (1 - slam),
                   squash=1 - 0.15 * slam * math.exp(-5 * v) * math.cos(12 * v) * (1 - v) if v > 0.02 else 1.0,
                   bob=4 * slam * (1 - v), lean=0.06 * (1 - v), arm_l0=0.5, arm_r0=0.5, arm_l1=0.6, arm_r1=0.6,
                   dx=1.2 * math.sin(2 * math.pi * 9 * v) * (1 - v))
        if v < 0.45:
            out["marks"] = [("_dust", v / 0.45)]
    return out


def a_turn(c: _Ctx) -> P:
    return {}  # поворот делает _facing (развёртка yaw + моргание)


def a_appear(c: _Ctx) -> P:
    tau = c.tau
    s = ease_out_back(clamp((tau - 0.2) / 0.6))
    return {"scale": max(0.0, s), "alpha": smoothstep((tau - 0.15) / 0.25), "squash": 1 + 0.15 * (1 - s) * (s > 0),
            "marks": [("_puff", clamp(tau * 1.1))]}


def a_poof(c: _Ctx) -> P:
    tau = c.tau
    out: P = {}
    if tau < 0.3:
        k = tau / 0.3
        out["squash"] = 1 - 0.18 * _bell(k / 0.6) + 0.22 * smoothstep((k - 0.5) / 0.5)
    else:
        v = clamp((tau - 0.3) / 0.15)
        out["scale"] = 1 - ease("in_back", v) if v < 1 else 0.0
        out["squash"] = 1.2
        out["marks"] = [("_puff", clamp((tau - 0.28) / 0.72))]
    return out


def _grow(c: _Ctx) -> P:
    return {}  # масштаб считает _scale (накапливается до конца сцены)


ACTIONS: dict[str, Callable[[_Ctx], P]] = {
    "idle": a_idle, "walk": a_walk, "walk_in": a_walk, "walk_out": a_walk, "run": a_run, "jump": a_jump,
    "hop": a_hop, "wave": a_wave, "clap": a_clap, "point": a_point, "talk": a_talk, "laugh": a_laugh, "cry": a_cry,
    "dance": _dance, "spin": a_spin, "fly": a_fly, "float": a_float, "fall": None, "sit": a_sit,  # type: ignore
    "sleep": a_sleep, "think": a_think, "shrug": a_shrug, "facepalm": a_facepalm, "nod": a_nod,
    "shake_head": a_shake_head, "bow": a_bow, "hug": a_hug, "high_five": a_high_five, "celebrate": a_celebrate,
    "scared": a_scared, "stomp": a_stomp, "turn": a_turn, "appear": a_appear, "poof": a_poof, "grow": _grow,
    "shrink": _grow,
}


def a_fall(c: _Ctx) -> P:
    tau = c.tau
    b = c.b
    out: P = {}
    if tau < 0.2:  # споткнулся
        k = smoothstep(tau / 0.2)
        flail = math.sin(2 * math.pi * 7 * c.lt)
        out.update(lean=0.4 * k, arm_l0=lerp(0.25, 2.6 + 0.3 * flail, k), arm_r0=lerp(0.25, 2.3 - 0.3 * flail, k),
                   arm_l1=0.4, arm_r1=0.4, leg_r0=fwd_leg(1, -0.5 * k, 0)[0], leg_r1=0.6 * k, look_y=-0.5 * k,
                   hand_l="open", hand_r="open")
    elif tau < 0.8:  # плюх — сидит, оглушён
        v = (tau - 0.2) / 0.6
        drop = smoothstep(v / 0.2)
        out = _sit_pose(b, drop)
        imp = (v - 0.2) / 0.8 if v >= 0.2 else -1
        if imp >= 0:
            out["squash"] = 1 - 0.25 * math.exp(-8 * imp) * math.cos(14 * imp)
            if imp < 0.3:
                out["marks"] = [("_dust", imp / 0.3)]
        out["lean"] = lerp(0.4, -0.12, drop)
        out["head_tilt"] = 0.15 * math.sin(2 * math.pi * 1.3 * c.lt)
    else:  # встаёт
        v = (tau - 0.8) / 0.2
        out = _sit_pose(b, 1 - smoothstep(v))
        out["squash"] = 1 + 0.06 * _bell(v)
    return out


ACTIONS["fall"] = a_fall


# ---------- смешивание клипов ----------
NUMERIC = ("bob", "lean", "squash", "head_tilt", "yaw", "arm_l0", "arm_l1", "arm_r0", "arm_r1", "leg_l0", "leg_l1",
           "leg_r0", "leg_r1", "look_x", "look_y", "scale", "alpha", "dx", "blink", "wings")
DISCRETE = ("hand_l", "hand_r")


def _rest() -> P:
    return {"bob": 0.0, "lean": 0.0, "squash": 1.0, "head_tilt": 0.0, "yaw": REST_YAW, "arm_l0": 0.25, "arm_l1": 0.3,
            "arm_r0": 0.25, "arm_r1": 0.3, "leg_l0": 0.06, "leg_l1": 0.0, "leg_r0": 0.06, "leg_r1": 0.0,
            "look_x": 0.0, "look_y": 0.0, "scale": 1.0, "alpha": 1.0, "dx": 0.0, "blink": 0.0, "wings": 0.0,
            "hand_l": "open", "hand_r": "open"}


def _apply(base: P, act: P, w: float) -> None:
    if w <= 0.0:
        return
    for k, v in act.items():
        if k in DISCRETE:
            if w >= 0.5:
                base[k] = v
        elif k == "marks":
            if w >= 0.3:
                base.setdefault("marks", []).extend(v)
        elif k == "flip":
            if w >= 0.5:
                base["flip"] = bool(v)
        elif isinstance(v, (int, float)):
            cur = base.get(k, 0.0)
            base[k] = cur + (float(v) - cur) * w


def _layer_weights(clips: list[Clip], t: float) -> list[tuple[Clip, float]]:
    """(клип, вес) клипов слоя, влияющих на момент t. Клип входит за FADE от начала и выходит за FADE после
    конца (держа последнюю позу); соседние клипы так переходят друг в друга без рывков."""
    out = []
    for c in clips:
        if c.t0 > t:
            break
        if t >= c.t1 + FADE:
            continue
        instant = c.action in ("appear", "poof", "spin")
        win = 1.0 if instant else smoothstep((t - c.t0) / FADE)
        wout = 1.0 if t <= c.t1 else 1.0 - smoothstep((t - c.t1) / FADE)
        if c.action == "poof" and t > c.t1:
            wout = 1.0
        w = win * wout
        if w > 1e-4:
            out.append((c, w))
    return out


def _eval(c: Clip, t: float, b: Build, aseed: int, units_w: float, x: float, facing: int, base: P) -> P:
    fn = ACTIONS.get(c.action)
    if fn is None:
        return {}
    dur = max(1e-3, c.t1 - c.t0)
    lt = clamp(t - c.t0, 0.0, dur)
    ctx = _Ctx(t, lt, lt / dur, dur, c.params, b, aseed, units_w, x, facing, base)
    return fn(ctx)


# ---------- корень: x, поворот, масштаб ----------
def _moves(clips: list[Clip]) -> list[Clip]:
    return [c for c in clips if c.layer == 0 and c.action in MOVES and "x0" in c.params and "x1" in c.params]


def root_x(moves: list[Clip], x_place: float, t: float) -> tuple[float, Clip | None]:
    """x актёра (доли кадра) по цепочке клипов перемещения; во время клипа — с трапецией скорости."""
    x = x_place
    if moves and moves[0].action == "walk_in" and t < moves[0].t0:
        return float(moves[0].params["x0"]), None
    for c in moves:
        if t < c.t0:
            break
        x0, x1 = float(c.params["x0"]), float(c.params["x1"])
        if t >= c.t1:
            x = x1
            continue
        tau = (t - c.t0) / max(1e-6, c.t1 - c.t0)
        return lerp(x0, x1, _trap(tau)), c
    return x, None


def _facing(clips: list[Clip], place: ActorShot, t: float,
            xf: Callable[[float], float]) -> tuple[int, bool, float | None]:
    """(куда смотрит ±1, «в камеру», мировой yaw во время поворота или None)."""
    f = 1 if place.facing >= 0 else -1
    cam = place.facing == 0
    for c in clips:
        if c.t0 > t:
            break
        if c.action in MOVES and "x0" in c.params:
            dx = float(c.params["x1"]) - float(c.params["x0"])
            if abs(dx) > 1e-4:
                f, cam = (1 if dx > 0 else -1), False
        elif c.action == "turn":
            to = c.params.get("to", "camera")
            f1, cam1 = f, cam
            if to == "left":
                f1, cam1 = -1, False
            elif to == "right":
                f1, cam1 = 1, False
            else:
                cam1 = True
            if t < c.t1:
                before = 0.0 if cam else f * REST_YAW
                after = 0.0 if cam1 else f1 * REST_YAW
                if f1 != f and not cam1:
                    before, after = f * max(REST_YAW, 0.45), f1 * max(REST_YAW, 0.45)
                tau = (t - c.t0) / max(1e-3, c.t1 - c.t0)
                wy = before + (after - before) * ease_out_back(tau)
                if abs(wy) > 1e-3:
                    f = 1 if wy > 0 else -1
                return f, False, wy
            f, cam = f1, cam1
        elif c.action in ("point", "hug", "high_five") and c.params.get("tx") is not None:
            dx = float(c.params["tx"]) - xf(c.t0)
            if abs(dx) > 1e-3:
                f, cam = (1 if dx > 0 else -1), False
    return f, cam, None


def _scale(clips: list[Clip], t: float) -> float:
    s = 1.0
    for c in clips:
        if c.t0 > t:
            break
        if c.action in ("grow", "shrink"):
            fct = float(c.params.get("factor", 1.5 if c.action == "grow" else 0.6))
            fct = clamp(fct, 0.4, 2.2)
            tau = (t - c.t0) / max(1e-3, c.t1 - c.t0)
            k = ease("spring", tau) if tau < 1 else 1.0
            s *= 1 + (fct - 1) * k
    return s


# ---------- эмоции ----------
def _emotion(A: _ActorIx, t: float, shot_t0: float) -> tuple[str, float, EmotionSpan | None]:
    """(эмоция, сила, отрезок): новая эмоция набирает силу за 0.25 с (с 0.35 — без «пустого» лица)."""
    i = bisect.bisect_right(A.emo_t0, t) - 1
    if i < 0:
        return "neutral", 1.0, None
    e = A.emotions[i]
    if t >= e.t1:
        return "neutral", 1.0, None
    if e.t0 <= shot_t0 + 1e-6:
        return e.emotion, 1.0, e
    return e.emotion, 0.35 + 0.65 * smoothstep((t - e.t0) / EMO_FADE), e


def _emotion_body(emo: str, w: float, t: float, since: float, b: Build, base: P) -> None:
    """Как эмоция меняет тело (design_wow §c.4): покачивания, наклоны и «свободные» руки."""
    if emo == "neutral" or w <= 0:
        return
    tw = 2 * math.pi * t

    def add(k: str, v: float) -> None:
        base[k] = base.get(k, 0.0) + v * w

    def arms(pr: P, kw: float = 0.85) -> None:
        for k, v in pr.items():
            if k in DISCRETE:
                if w >= 0.5:
                    base[k] = v
            else:
                base[k] = lerp(base[k], v, w * kw)
    if emo == "happy":
        add("bob", -2 * (0.5 + 0.5 * math.sin(tw * 1.2)))
    elif emo == "excited":
        add("bob", -4 * abs(math.sin(tw * 2)))
        add("squash", 0.02)
        arms({"arm_l0": 0.6, "arm_l1": 1.7, "arm_r0": 0.6, "arm_r1": 1.7, "hand_l": "fist", "hand_r": "fist"}, 0.6)
    elif emo == "laugh":
        add("lean", -0.08 + 0.03 * math.sin(tw * 6))
        add("bob", -3 * abs(math.sin(tw * 3)))
    elif emo == "love":
        add("lean", 0.05 * math.sin(tw))
        add("head_tilt", 0.1)
        hc = _head_c(b, 0.0, 0.0, 0.25)
        pr: P = {}
        for side, nm in ((1, "r"), (-1, "l")):
            a, bnd = ik(b, side, (side * 10 + 4, hc[1] + b.head_r * 1.35))
            pr[f"arm_{nm}0"], pr[f"arm_{nm}1"] = a, bnd
        arms(pr, 0.7)
    elif emo == "smug":
        add("lean", -0.05)
        add("head_tilt", -0.06)
    elif emo == "sad":
        add("lean", 0.08)
        add("head_tilt", 0.1)
        add("look_y", 0.3)
        arms({"arm_l0": 0.08, "arm_l1": 0.08, "arm_r0": 0.08, "arm_r1": 0.08})
    elif emo == "cry":
        add("squash", 0.025 * math.sin(tw * 3))
        add("bob", 1.5 * math.sin(tw * 3))
    elif emo == "angry":
        add("lean", 0.06)
        add("dx", 1.0 * math.sin(tw * 8))
        arms({"arm_l0": 0.45, "arm_l1": 0.45, "arm_r0": 0.45, "arm_r1": 0.45, "hand_l": "fist", "hand_r": "fist"})
    elif emo == "surprised":
        k = _bell(since / 0.4) if since < 0.4 else 0.0
        add("dx", -8 * k)
        add("bob", -10 * k)
        arms({"arm_l0": 1.0, "arm_l1": 1.3, "arm_r0": 1.0, "arm_r1": 1.3, "hand_l": "open", "hand_r": "open"}, 0.7)
    elif emo == "scared":
        add("dx", 1.5 * math.sin(tw * 12))
        add("lean", -0.08)
        add("leg_l1", 0.2)
        add("leg_r1", 0.2)
        hc = _head_c(b, -0.08, 0.0, 0.25)
        pr = {"hand_l": "open", "hand_r": "open"}
        for side, nm in ((1, "r"), (-1, "l")):
            a, bnd = ik(b, side, (side * 14 + 6, hc[1] + b.head_r * 1.25), -0.08)
            pr[f"arm_{nm}0"], pr[f"arm_{nm}1"] = a, bnd
        arms(pr, 0.75)
    elif emo == "sleepy":
        add("lean", 0.04 * math.sin(tw * 0.35))
        add("head_tilt", 0.12)
    elif emo == "dizzy":
        add("lean", 0.08 * math.sin(tw * 1.2))
        add("dx", 4 * math.cos(tw * 1.2))
        add("head_tilt", 0.12 * math.sin(tw * 1.2 + 1))
    elif emo == "thinking":
        add("head_tilt", 0.08)
        hc = _head_c(b, 0.0, 0.0, 0.25)
        a, bnd = ik(b, 1, (hc[0] + 6, hc[1] + b.head_r * 0.82))
        arms({"arm_r0": a, "arm_r1": bnd, "hand_r": "fist"}, 0.9)
    elif emo == "embarrassed":
        add("scale", -0.03)
        add("head_tilt", 0.1)
        pr = {}
        for side, nm in ((1, "r"), (-1, "l")):
            a, bnd = ik(b, side, (side * 5, b.hip_y - b.torso * 0.3))
            pr[f"arm_{nm}0"], pr[f"arm_{nm}1"] = a, bnd
        arms(pr, 0.8)
    elif emo == "proud":
        add("lean", -0.06)
        add("head_tilt", -0.05)
        add("squash", 0.02)
        pr = {"hand_l": "fist", "hand_r": "fist"}
        for side, nm in ((1, "r"), (-1, "l")):
            a, bnd = ik(b, side, (side * (b.waist_w + 5), b.hip_y - 8))
            pr[f"arm_{nm}0"], pr[f"arm_{nm}1"] = a, bnd
        arms(pr, 0.9)


# ---------- главное ----------
def _invisible(actor: str, lane: str, t: float) -> ActorFrame:
    return ActorFrame(actor, False, Pose(t=t, alpha=0.0), 0.5, lane, 1)


def actor_frame(plan: Plan, actor: str, t: float, *, shot: int | None = None) -> ActorFrame:
    """Поза и место актёра в момент t (чистая функция). shot — номер сцены, если нужно нарисовать именно её
    (например, старую сцену во время перехода); по умолчанию — сцена, идущая в момент t."""
    ix = _index(plan)
    sh = plan.shots[shot] if shot is not None and 0 <= shot < len(plan.shots) else plan.shot_at(t)
    place = ix.place.get((actor, sh.index))
    cast = plan.cast.get(actor)
    A = ix.actors.get(actor)
    if place is None or cast is None or A is None:
        return _invisible(actor, "mid", t)
    lane = place.lane
    if not place.visible:
        return _invisible(actor, lane, t)
    clips = A.shots.get(sh.index, [])
    b = A.build
    height = char_height(plan.format, plan.h, lane, cast.size)
    units_w = plan.w / max(1e-6, height / 300.0)
    moves = _moves(clips)

    def xf(tt: float) -> float:
        return root_x(moves, place.x, tt)[0]

    x, move = root_x(moves, place.x, t)
    facing, cam, turn_yaw = _facing(clips, place, t, xf)
    # ---- база: стойка + жизнь + эмоция
    base = _rest()
    base["yaw"] = 0.0 if cam else REST_YAW
    lf = idle(t, A.aseed)
    base["lean"] += lf["lean"]
    base["head_tilt"] += lf["head_tilt"]
    base["squash"] += lf["squash"]
    base["arm_l0"] += lf["arm"]
    base["arm_r0"] += lf["arm"]
    base["dx"] += lf["dx"]
    # остановка после шага: корпус по инерции качнётся вперёд и пружиной вернётся (2.5 Гц, ζ = 0.3)
    done = [c for c in moves if c.t1 <= t]
    if done and move is None:
        dt = t - done[-1].t1
        if dt < 1.0:
            kick = 0.12 if done[-1].action == "run" else 0.07
            base["lean"] += kick * math.exp(-0.3 * 2 * math.pi * 2.5 * dt) * math.sin(2 * math.pi * 2.5 * dt * 0.95)
    emo, emo_w, span = _emotion(A, t, sh.t0)
    _emotion_body(emo, emo_w, t, t - span.t0 if span else 99.0, b, base)
    # ---- клипы: L0, потом L1
    l0 = [c for c in clips if c.layer == 0]
    l1 = [c for c in clips if c.layer != 0]
    active_l1 = False
    for layer in (l0, l1):
        for c, w in _layer_weights(layer, t):
            act = _eval(c, t, b, A.aseed, units_w, x, facing, base)
            _apply(base, act, w)
            if layer is l1 and w > 0.3:
                active_l1 = True
    # ---- речь
    speaking = False
    line = next((ln for ln in A.lines if ln.t0 <= t < ln.t1), None)
    mouth_open, mouth_shape = 0.0, "m"
    if line is not None and line.kind in TALK_KINDS:
        speaking = True
        dur = max(0.4, line.t1 - line.t0 - 0.3)
        cps = max(13.0, len(line.text) / dur) if line.text else 13.0
        mouth_open, mouth_shape = lip(line.text, line.t0, t, cps)
        if line.kind == "shout":
            mouth_open = min(1.0, mouth_open * 1.25 + 0.1)
            base["lean"] += 0.06
        elif line.kind == "whisper":
            mouth_open *= 0.45
            base["lean"] += 0.05
        if not active_l1:
            g = talk_gestures(line.text, line.t0, t, cps, A.aseed, shout=line.kind == "shout")
            gw = g.pop("_gw", 0.0)
            nod = g.pop("_nod", 0.0)
            if line.kind == "whisper":
                hc = _head_c(b, base["lean"], base["bob"], base["yaw"])
                a, bnd = ik(b, 1, (hc[0] + b.head_r * 0.55, hc[1] + b.head_r * 0.6), base["lean"])
                e = _env(t - line.t0, line.t1 - line.t0, 0.25, 0.25)
                _apply(base, {"arm_r0": a, "arm_r1": bnd, "hand_r": "open"}, e)
            elif gw > 0:
                _apply(base, g, gw)
            base["head_tilt"] += 0.035 * nod
            base["look_y"] += 0.2 * nod
    elif line is not None and line.kind == "think":
        base["look_y"] -= 0.4
        base["look_x"] += 0.3
    talk_clip = next((c for c in clips if c.action == "talk" and c.t0 <= t < c.t1), None)
    if not speaking and talk_clip is not None:
        mouth_open, mouth_shape = lip(GIBBERISH * 3, talk_clip.t0, t, 13.0)
        speaking = True
    # ---- взгляд: явный LookSpan → на говорящего → на соседа
    look_dir: float | None = None  # мировое направление −1..1
    look_cam = False
    lk = next((s for s in A.looks if s.t0 <= t < s.t1), None)
    attend = 0.0
    if lk is not None:
        if lk.target == "camera":
            look_cam = True
        elif lk.target in ("left", "right"):
            look_dir = -1.0 if lk.target == "left" else 1.0
        else:
            tx = _actor_x(plan, ix, lk.target, sh.index, t)
            if tx is not None and abs(tx - x) > 1e-3:
                look_dir = 1.0 if tx > x else -1.0
    elif not speaking:
        sp = _speaker(plan, ix, sh.index, actor, t)
        if sp is not None:
            tx = _actor_x(plan, ix, sp, sh.index, t)
            if tx is not None and abs(tx - x) > 1e-3:
                look_dir = 1.0 if tx > x else -1.0
                attend = 1.0
    else:
        near = _nearest(plan, ix, sh.index, actor, x, t)
        if near is not None:
            look_dir = 1.0 if near > x else -1.0
            attend = 0.5
    if look_cam:
        base["look_x"] *= 0.2
        base["yaw"] *= 0.3
    elif look_dir is not None:
        local = look_dir * facing
        base["look_x"] = lerp(base["look_x"], 0.6 * local, 0.85)
        base["yaw"] += 0.2 * local * (1.0 if attend >= 1.0 else 0.6)
    sx, sy = saccade(t, A.aseed)
    k_sac = 0.45 if (attend or lk is not None) else 1.0
    base["look_x"] += sx * k_sac
    base["look_y"] += sy * k_sac
    # ---- поворот и разворот (spin)
    if turn_yaw is not None:
        base["yaw"] = turn_yaw * facing
    if base.get("flip"):
        facing = -facing
    # ---- масштаб, видимость
    scale = _scale(clips, t) * base["scale"]
    alpha = base["alpha"]
    appear = next((c for c in l0 if c.action == "appear"), None)
    if appear is not None and t < appear.t0:
        return _invisible(actor, lane, t)
    poofs = [c for c in l0 if c.action == "poof" and c.t1 <= t]
    if poofs and not any(c.action == "appear" and c.t0 >= poofs[-1].t1 and c.t0 <= t for c in l0):
        return _invisible(actor, lane, t)
    dx_frac = base["dx"] * facing / units_w
    xx = x + dx_frac
    half = 0.3 * height / max(1.0, plan.w) * max(1.0, scale)  # полуширина с хвостами и руками
    visible = (xx + half > 0.0) and (xx - half < 1.0)
    # ---- моргание и вторичное движение
    bl = max(blink(t, A.aseed, A.forced_blinks), clamp(base["blink"]))
    if line is not None and line.kind == "think":
        bl = max(bl, 0.0)
    bob = base["bob"]

    def x_h(tt: float) -> float:
        return root_x(moves, place.x, tt)[0] * units_w / 300.0

    lag = spring_lag(x_h, t)
    hair = swing(lag * facing, 16.0) + 0.06 * math.sin(t * 2.1 + A.aseed % 7)
    l0w = _layer_weights(l0, t)

    def bob_at(tt: float) -> float:
        v = 0.0
        for c, w in l0w:
            if c.action in ("jump", "hop", "celebrate", "fly", "float", "fall", "sit", "sleep", "stomp", "scared"):
                act = _eval(c, tt, b, A.aseed, units_w, x, facing, _rest())
                v += act.get("bob", 0.0) * w
        return v / 300.0

    vlag = spring_lag(bob_at, t, window=0.5, n=10, freq=2.2) if l0w else 0.0
    ear = clamp(vlag * 10.0 + 0.35 * hair, -1.0, 1.0)
    tail = clamp(0.3 * math.sin(t * 2.4 + A.aseed % 5) + swing(lag * facing, 9.0), -1.0, 1.0)
    if A.base == "dog" and emo in HAPPY_TAIL:
        tail = 0.85 * math.sin(2 * math.pi * 5.0 * t)
    lift = max(0.0, -bob) / 300.0
    flying = base["wings"] > 0.3 or lift > 0.05
    wing = math.sin(2 * math.pi * (4.0 if flying else 1.1) * t) * (1.0 if flying else 0.35)
    # ---- значки
    marks = _marks(A, emo, span, t, sh.t0, base.get("marks", []))
    pose = Pose(
        bob=bob, lean=clamp(base["lean"], -0.45, 0.45), squash=clamp(base["squash"], 0.65, 1.35),
        head_tilt=clamp(base["head_tilt"], -0.45, 0.45), yaw=clamp(base["yaw"], -1.0, 1.0),
        arm_l=(base["arm_l0"], base["arm_l1"]), arm_r=(base["arm_r0"], base["arm_r1"]),
        leg_l=(base["leg_l0"], base["leg_l1"]), leg_r=(base["leg_r0"], base["leg_r1"]),
        hand_l=base["hand_l"], hand_r=base["hand_r"],
        look=(clamp(base["look_x"], -1.0, 1.0), clamp(base["look_y"], -1.0, 1.0)), blink=clamp(bl),
        emotion=emo, emotion_w=clamp(emo_w), mouth_open=clamp(mouth_open), mouth_shape=mouth_shape,
        hair_swing=clamp(hair, -1.0, 1.0), tail_swing=tail, ear_swing=ear, wing_flap=wing, marks=marks,
        scale=max(0.0, scale), alpha=clamp(alpha), t=t,
    )
    puffing = any(m[0] == "_puff" for m in marks)
    return ActorFrame(actor, visible and (pose.scale > 0.005 or puffing), pose, xx, lane, facing, lift, speaking)


def _marks(A: _ActorIx, emo: str, span: EmotionSpan | None, t: float, shot_t0: float,
           extra: list) -> tuple[tuple[str, float], ...]:
    out: list[tuple[str, float]] = []
    seen: set[str] = set()
    for m in A.marks:
        if m.t0 <= t < m.t1 and m.kind not in seen:
            out.append((m.kind, (t - m.t0) / max(1e-3, m.t1 - m.t0)))
            seen.add(m.kind)
    if span is not None and emo in AUTO_MARK:
        kind = AUTO_MARK[emo]
        if kind not in seen:
            if kind in LOOP_MARKS:
                t1 = span.t1
            else:
                t1 = min(span.t1, span.t0 + MARK_SECONDS)
            if span.t0 <= t < t1:
                out.append((kind, (t - span.t0) / max(1e-3, t1 - span.t0)))
                seen.add(kind)
            if emo == "angry" and t < min(span.t1, span.t0 + 2.4) and "steam" not in seen:
                out.append(("steam", (t - span.t0) / max(1e-3, min(span.t1, span.t0 + 2.4) - span.t0)))
                seen.add("steam")
    for kind, p in extra:
        if kind.startswith("_") or kind not in seen:
            out.append((kind, clamp(p)))
            seen.add(kind)
    vis = [m for m in out if not m[0].startswith("_")][:3]
    inner = [m for m in out if m[0].startswith("_")]
    return tuple(vis + inner)


def _actor_x(plan: Plan, ix: _Index, actor: str, shot: int, t: float) -> float | None:
    place = ix.place.get((actor, shot))
    A = ix.actors.get(actor)
    if place is None or A is None or not place.visible:
        return None
    return root_x(_moves(A.shots.get(shot, [])), place.x, t)[0]


def _speaker(plan: Plan, ix: _Index, shot: int, actor: str, t: float) -> str | None:
    best = None
    for ln in ix.lines_by_shot.get(shot, []):
        if ln.actor != actor and ln.kind in TALK_KINDS and ln.t0 <= t < ln.t1:
            if best is None or ln.t0 > best.t0:
                best = ln
    return best.actor if best is not None else None


def _nearest(plan: Plan, ix: _Index, shot: int, actor: str, x: float, t: float) -> float | None:
    best = None
    for a in plan.cast:
        if a == actor:
            continue
        ox = _actor_x(plan, ix, a, shot, t)
        if ox is None or ox < 0.0 or ox > 1.0:
            continue
        if best is None or abs(ox - x) < abs(best - x):
            best = ox
    return best


__all__ = ["ACTIONS", "FADE", "actor_frame", "fwd_arm", "fwd_leg", "ik", "root_x", "talk_gestures"]
