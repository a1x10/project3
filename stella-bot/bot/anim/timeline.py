"""Spec → Plan: мультик, разложенный по абсолютному времени (секунды от начала ролика).

Правила (design_wow §f):
- длительность бита — наибольшее из: действие по умолчанию (у ходьбы — путь / скорость), реплика
  0.6 + len/13 с (1–6 с), seconds бита (seconds заменяет длительность действия по умолчанию);
- биты идут по очереди с «вдохом» 0.15 с; with_prev — одновременно с предыдущим; at — с этой секунды сцены;
- групповой бит (несколько who) — сдвиг 0.08 с на каждого следующего (у dance style=sync — без сдвига);
- сцена = конец последнего бита + хвост 0.6 с (или seconds сцены, но реплики не обрезаются);
- ролик длиннее предела не больше чем на 30 % — ужимаем (реплики 16 зн/с, короче паузы и хвосты, потом
  равномерно всё время) с предупреждением; иначе SpecError со списком длительностей сцен.

Гарантии для отрисовки (actions.actor_frame и др.):
- у одного актёра на одном слое клипы не перекрываются (новое действие прерывает старое, длинное «фоновое» —
  танец, сидение, сон — продолжается после него), отсортированы по времени;
- у клипов перемещения params x0 → x1 — цепочка: x0 следующего = x1 предыдущего (или ActorShot.x), позиция
  после сцены переходит в следующую, если там нет place;
- ActorShot.visible — участвует ли актёр в сцене; если сцена начинается с его входа из-за кадра (walk_in и т. п.),
  ActorShot.x уже за кадром; до appear и после poof прячут сами actions по клипам;
- эмоции — непересекающиеся отрезки EmotionSpan; эмоция действия (laugh, cry, sleep → sleepy…) — только на время
  действия, потом возвращается прежняя.

Модуль лёгкий (без cairo и numpy): compile_plan работает в процессе бота.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from . import catalog as C
from .ease import hash01
from .layout import OFFSCREEN_L, OFFSCREEN_R, spread_x
from .model import (
    ActorShot,
    BeatSpec,
    CameraEvent,
    Clip,
    EmotionSpan,
    Line,
    LookSpan,
    MarkEvent,
    Plan,
    PlannedEffect,
    PlannedProp,
    PlannedShot,
    PlannedTitle,
    ShotSpec,
    Spec,
    SpecError,
)

LINE_CPS = 13.0  # скорость чтения реплики, знаков в секунду
FAST_CPS = 16.0  # при сжатии
BREATH = 0.15  # пауза между битами
STAGGER = 0.08  # сдвиг в групповом бите
TAIL = 0.6  # хвост сцены после последнего бита
LEAD = 0.2  # первая сцена: чуть-чуть до первого бита
MIN_MOVE = 0.6  # перемещение не короче
REACT = 0.8  # бит только с эмоцией/значком/взглядом
PAUSE = 0.5  # пустой бит-пауза
MARK_SECONDS = 1.6
COMPRESS_MAX = 1.3  # до +30 % сверх предела — ужимаем, дальше — SpecError
NEAR = 0.18  # «подойти к актёру» — встать на таком расстоянии с ближней стороны
TITLE_CARD = 2.5  # сцена без битов (только заголовок/предметы)
EPS = 1e-6

SPEED = {"walk": 0.25, "walk_in": 0.25, "walk_out": 0.25, "run": 0.6, "fly": 0.35}  # доли ширины в секунду
MOVES = frozenset(SPEED)
PAIR = frozenset({"hug", "high_five"})
GAP = {"hug": 0.15, "high_five": 0.21}  # расстояние между центрами двух актёров
ACTION_SECONDS = {
    "idle": 1.0, "walk": 1.0, "walk_in": 1.0, "walk_out": 1.0, "run": 0.8, "jump": 1.0, "hop": 0.5, "wave": 1.2,
    "clap": 1.5, "point": 1.2, "talk": 1.5, "laugh": 1.5, "cry": 2.0, "dance": 3.0, "spin": 1.0, "fly": 2.0,
    "float": 2.0, "fall": 1.5, "sit": 2.0, "sleep": 3.0, "think": 2.0, "shrug": 1.0, "facepalm": 1.2, "nod": 0.8,
    "shake_head": 1.0, "bow": 1.2, "hug": 2.0, "high_five": 1.2, "celebrate": 1.5, "scared": 1.5, "stomp": 1.0,
    "turn": 0.3, "appear": 0.6, "poof": 0.6, "grow": 0.8, "shrink": 0.8,
}
# руки и жесты (слой 1) — идут поверх ходьбы и танца; всё остальное — тело (слой 0)
LAYER1 = frozenset({"wave", "clap", "point", "talk", "shrug", "facepalm", "nod", "shake_head", "think"})
# «фоновые» действия: тянутся на всю реплику и продолжаются после прервавшего их действия
LOOPABLE = frozenset({"idle", "talk", "dance", "float", "sleep", "sit", "think", "cry", "laugh", "clap"})
IMPLIED_EMOTION = {
    "laugh": "laugh", "cry": "cry", "scared": "scared", "sleep": "sleepy", "think": "thinking",
    "celebrate": "excited", "stomp": "angry", "fall": "dizzy", "hug": "love", "facepalm": "embarrassed",
}
CAMERA_BEAT_SECONDS = {"shake": 0.35, "zoom_in": 0.6, "zoom_out": 0.6, "punch": 0.6, "focus": 0.6, "reset": 0.3}
EFFECT_SECONDS = {  # эффект из бита, если seconds не задан
    "confetti": 3.0, "fireworks": 3.0, "flash": 0.4, "poof": 0.8, "hearts": 2.5, "sparkles": 2.0, "stars": 3.0,
    "music": 3.0, "coins": 2.5, "balloons": 4.0, "bubbles": 4.0, "leaves": 4.0, "smoke": 2.5, "fire": 3.0,
    "snow": 6.0, "rain": 6.0,
}
SHOT_EFFECT_SHORT = {"flash": 0.4, "poof": 0.8}  # эффекты сцены без seconds идут до конца сцены, кроме этих
TRANSITION_SECONDS = {
    "cut": 0.5, "fade": 0.6, "crossfade": 0.5, "wipe": 0.5, "iris": 0.6, "zoom": 0.5, "slide": 0.5, "flash": 0.4,
}
_FACING = {"left": -1, "right": 1, "camera": 0}


def line_seconds(text: str, cps: float = LINE_CPS) -> float:
    """Сколько держать реплику: 0.6 + len/13 с, в пределах 1–6 с."""
    return min(6.0, max(1.0, 0.6 + len(text or "") / max(1.0, cps)))


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _bounds(fmt: str) -> tuple[float, float]:
    xs = spread_x(5, fmt)
    return (min(xs), max(xs)) if xs else (0.2, 0.8)


def _offscreen(x: float) -> bool:
    return x < 0.0 or x > 1.0


@dataclass
class _Level:
    """Насколько ужимать: скорость чтения, паузы, хвосты и общий множитель времени k."""

    cps: float = LINE_CPS
    breath: float = BREATH
    tail: float = TAIL
    lead: float = 1.0
    k: float = 1.0


@dataclass
class _Stage:
    """Состояние одной сцены, пока раскладываем её биты."""

    index: int
    t0: float
    parts: list[str]
    home: dict[str, float]  # где актёр стоит «по расстановке» (туда входит walk_in)
    cur: dict[str, float]  # где он сейчас (после уже разложенных битов)
    face: dict[str, int]
    clips: list[Clip] = field(default_factory=list)
    line_end: float = 0.0  # абсолютное время конца последней реплики
    hard_end: float = 0.0  # явные seconds у эффектов/заголовка — сцена не короче


class _Build:
    def __init__(self, spec: Spec, fps: int, level: _Level):
        self.spec = spec
        self.fps = fps
        self.lv = level
        self.k = level.k
        self.lo, self.hi = _bounds(spec.format)
        self.clips: list[Clip] = []
        self.lines: list[Line] = []
        self.marks: list[MarkEvent] = []
        self.looks: list[LookSpan] = []
        self.effects: list[PlannedEffect] = []
        self.titles: list[PlannedTitle] = []
        self.cameras: list[CameraEvent] = []
        self.props: list[PlannedProp] = []
        self.placements: list[ActorShot] = []
        self.shots: list[PlannedShot] = []
        self.emo_base: dict[str, list[tuple[float, str]]] = {}
        self.emo_implied: dict[str, list[tuple[float, float, str]]] = {}
        self.pos: dict[str, float] = {}  # x актёра на конец последней сцены, где он был
        self.lane: dict[str, str] = {}
        self.warnings: list[str] = []
        self.durations: list[float] = []
        self.duration = 0.0
        self.emotions: list[EmotionSpan] = []
        self.auto_ids: set[int] = set()  # id() автоматических событий камеры
        self._n_effect = 0

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    # ---------- весь ролик ----------
    def run(self) -> None:
        t = 0.0
        prev_transition: str | None = None
        for i, shot in enumerate(self.spec.shots):
            if prev_transition is None:
                lead = LEAD
            elif prev_transition == "cut":
                lead = BREATH
            else:
                lead = TRANSITION_SECONDS.get(prev_transition, 0.5) / 2 + 0.1
            dur = self.shot(i, shot, t, lead * self.lv.lead)
            self.durations.append(dur)
            t += dur
            prev_transition = shot.transition
        self.duration = t
        self.emotions = self.emotion_spans()

    # ---------- одна сцена ----------
    def shot(self, i: int, s: ShotSpec, t0: float, lead: float) -> float:
        cast = self.spec.cast
        parts = [a for a in s.place if a in cast]
        for b in s.beats:  # на случай сценария, собранного не через parse_spec
            for a in list(b.who) + [b.target] + ([b.to] if isinstance(b.to, str) else []):
                if a in cast and a not in parts and len(parts) < C.MAX_ON_SCREEN:
                    parts.append(a)
        home, lanes, face = self.start_positions(s, parts)
        st = _Stage(i, t0, parts, dict(home), dict(home), dict(face))
        k = self.k

        cursor: float | None = None
        prev_start = lead
        has_prev = False
        content_end = t0 + lead
        for b in s.beats:
            if b.at is not None:
                start = b.at * k
            elif b.with_prev and has_prev:
                start = prev_start
            else:
                start = lead if cursor is None else cursor + self.lv.breath
            end = self.beat(st, b, t0 + start) - t0
            if b.at is None:
                cursor = end if cursor is None else max(cursor, end)
            prev_start, has_prev = start, True
            content_end = max(content_end, t0 + end)
        for e in s.effects:
            if e.seconds is not None:
                st.hard_end = max(st.hard_end, t0 + ((e.at or 0.0) + e.seconds) * k)
        if s.title is not None and s.title.seconds is not None:
            st.hard_end = max(st.hard_end, t0 + (s.title.at + s.title.seconds) * k)

        if s.beats:
            natural = max(content_end, st.hard_end) - t0 + self.lv.tail
        else:
            natural = max(TITLE_CARD * k, st.hard_end - t0 + self.lv.tail)
        if s.seconds is not None:
            dur = s.seconds * k
            need = st.line_end - t0 + 0.2
            if dur < need - EPS:
                self.warn(f"сцена {i + 1}: seconds={s.seconds:g} мало для реплик — сделала {need:.1f} с")
                dur = need
        else:
            dur = natural
        dur = max(dur, 1.0)
        t1 = t0 + dur

        self.finish_clips(st, t1)
        for a in cast:
            if a in parts:
                first = next((c for c in st.clips if c.actor == a and c.layer == 0), None)
                x = home[a]
                if first is not None and first.action in MOVES and _offscreen(first.params.get("x0", x)):
                    x = first.params["x0"]
                self.placements.append(ActorShot(a, i, x, lanes[a], face[a], True))
                self.lane[a] = lanes[a]
            else:
                self.placements.append(ActorShot(a, i, self.pos.get(a, 0.5), self.lane.get(a, "mid"), 0, False))
        self.clamp_events(i, t0, t1)
        self.shot_extras(i, s, t0, t1)
        is_last = i == len(self.spec.shots) - 1
        transition = "cut" if is_last else s.transition
        self.shots.append(PlannedShot(i, t0, t1, s.background, transition,
                                      TRANSITION_SECONDS.get(transition, 0.5)))
        return dur

    def start_positions(self, s: ShotSpec, parts: list[str]) -> tuple[dict[str, float], dict[str, str], dict[str, int]]:
        """Где кто стоит в начале сцены: place → x; иначе позиция из прошлой сцены; иначе свободное место
        из layout.spread_x. Лицом — как в place, иначе к центру кадра."""
        explicit: dict[str, float] = {}
        carried: dict[str, float] = {}
        for a in parts:
            p = s.place.get(a)
            if p is not None and p.x is not None:
                explicit[a] = _clamp(p.x, 0.0, 1.0)
            elif a in self.pos and 0.04 <= self.pos[a] <= 0.96:
                carried[a] = self.pos[a]
        free = list(spread_x(len(parts), self.spec.format))
        for x in list(explicit.values()) + list(carried.values()):
            if free:
                free.remove(min(free, key=lambda f: abs(f - x)))
        free.sort()
        home: dict[str, float] = {}
        rest = [a for a in parts if a not in explicit and a not in carried]
        for n, a in enumerate(rest):
            home[a] = free[n] if n < len(free) else 0.5
        home.update(explicit)
        home.update(carried)
        home = {a: home[a] for a in parts}
        lanes: dict[str, str] = {}
        face: dict[str, int] = {}
        for a in parts:
            p = s.place.get(a)
            auto = p is None or (p.x is None and p.facing is None and p.lane == "mid")
            lanes[a] = self.lane.get(a, "mid") if auto and a in carried else (p.lane if p is not None else "mid")
            if p is not None and p.facing in _FACING:
                face[a] = _FACING[p.facing]
            else:
                x = home[a]
                if len(parts) == 1 and abs(x - 0.5) < 0.12:
                    face[a] = 0
                elif abs(x - 0.5) < 1e-6:
                    others = [home[o] for o in parts if o != a]
                    mean = sum(others) / len(others) if others else 0.5
                    face[a] = 0 if abs(mean - x) < 1e-6 else (1 if mean > x else -1)
                else:
                    face[a] = 1 if x < 0.5 else -1
        return home, lanes, face

    # ---------- один бит ----------
    def beat(self, st: _Stage, b: BeatSpec, t: float) -> float:
        """Разложить бит, начинающийся в t (абсолютное время). Возвращает абсолютный конец бита."""
        k = self.k
        who = [a for a in b.who if a in st.cur]
        end = t
        if b.seconds is not None:
            end = t + b.seconds * k
        if not who and b.effect is None and b.camera is None:
            return max(end, t + PAUSE * k)
        n = len(who)
        sync = b.do == "dance" and b.style == "sync"
        stagger = 0.0 if n < 2 or sync else STAGGER * k
        meet: dict[str, float] = {}  # hug/high_five: когда актёры сошлись — тогда и эмоция со значком
        if b.do in PAIR and who:
            end = max(end, self.pairs(st, b, who, t, meet))
        for j, a in enumerate(who):
            end = max(end, self.actor_beat(st, b, a, t + j * stagger, skip_do=b.do in PAIR,
                                           react_at=meet.get(a)))
        if b.effect is not None:
            e = b.effect
            dur = (e.seconds if e.seconds is not None else EFFECT_SECONDS.get(e.kind, 2.5)) * k
            x = e.x
            if x is None and who and not _offscreen(st.cur[who[0]]):
                x = st.cur[who[0]]
            self.add_effect(st.index, e.kind, t, t + dur, x, e.y, e.amount)
            if e.seconds is not None:
                st.hard_end = max(st.hard_end, t + dur)
            if not who:
                end = max(end, t + (b.seconds * k if b.seconds is not None else min(PAUSE * k, dur)))
        if b.camera is not None:
            dur = CAMERA_BEAT_SECONDS.get(b.camera, 0.6) * k
            focus = b.camera_focus or (who[0] if who else None)
            amount = 0.5 if b.amount is None else b.amount
            t1 = float("inf") if b.camera == "reset" else t + dur
            # явная камера из бита важнее автоматической (тряска на прыжке, рывок на крике) рядом с ней
            self.cameras[:] = [c for c in self.cameras
                               if not (id(c) in self.auto_ids and c.shot == st.index and abs(c.t0 - t) < 0.8)]
            self.cameras.append(CameraEvent(st.index, b.camera, t, t1, focus, amount))
            if not who:
                end = max(end, t + dur)
        return end

    def actor_beat(self, st: _Stage, b: BeatSpec, a: str, t: float, *, skip_do: bool,
                   react_at: float | None = None) -> float:
        k = self.k
        tr = t if react_at is None else react_at
        end = t
        line_dur = 0.0
        if b.line:
            line_dur = max(1.0, line_seconds(b.line, self.lv.cps) * min(1.0, k))
            self.lines.append(Line(a, b.line, b.line_kind, t, t + line_dur))
            st.line_end = max(st.line_end, t + line_dur)
            end = t + line_dur
            if b.line_kind == "shout" and b.camera is None:
                self.auto_camera(st.index, "punch", t, t + CAMERA_BEAT_SECONDS["punch"] * k, a, 0.4)
        if b.do is not None and not skip_do:
            end = max(end, self.action(st, b, a, b.do, t, line_dur))
        if b.emotion is not None:
            self.emo_base.setdefault(a, []).append((tr, b.emotion))
        if b.mark is not None:
            self.marks.append(MarkEvent(a, b.mark, tr, tr + MARK_SECONDS))
        if (b.emotion or b.mark or b.look) and b.do is None and not b.line:
            end = max(end, t + REACT * k)
        if b.seconds is not None:
            end = max(end, t + b.seconds * k)
        if b.look is not None and b.look != a:
            self.looks.append(LookSpan(a, b.look, t, max(end, t + 1.0)))
        return end

    def action(self, st: _Stage, b: BeatSpec, a: str, do: str, t: float, line_dur: float) -> float:
        """Клипы действия do актёра a с момента t. Возвращает абсолютный конец."""
        k = self.k
        if do in MOVES:
            x0, x1 = self.move_xs(st, a, do, b)
            dur = self.move_seconds(do, x0, x1, b.seconds)
            params: dict[str, object] = {"x0": x0, "x1": x1}
            if do == "fly":
                params["height"] = 0.3 if b.amount is None else round(0.15 + 0.35 * b.amount, 3)
            self.add_clip(st, Clip(a, do, t, t + dur, 0, params))
            st.cur[a] = x1
            if x1 != x0:
                st.face[a] = 1 if x1 > x0 else -1
            return t + dur
        t_act = t
        walk_end = t
        if b.to is not None and do not in ("point", "turn"):
            x0 = st.cur[a]
            x1 = self.target_x(st, a, b.to, x0)
            if abs(x1 - x0) > 0.02:
                wdur = self.move_seconds("walk", x0, x1, None)
                self.add_clip(st, Clip(a, "walk", t, t + wdur, 0, {"x0": x0, "x1": x1}))
                st.cur[a] = x1
                st.face[a] = 1 if x1 > x0 else -1
                walk_end = t + wdur
                if do not in LAYER1:
                    t_act = walk_end  # сначала дойти, потом прыгать/танцевать
        dur = (b.seconds if b.seconds is not None else ACTION_SECONDS.get(do, 1.0)) * k
        if do == "talk" and b.seconds is None and line_dur > 0:
            dur = line_dur
        elif do in LOOPABLE and line_dur > dur:
            dur = line_dur  # танцует/говорит, пока звучит реплика
        params = self.params(st, b, a, do, t_act, dur)
        layer = 1 if do in LAYER1 else 0
        self.add_clip(st, Clip(a, do, t_act, t_act + dur, layer, params))
        if b.emotion is None and do in IMPLIED_EMOTION:
            self.emo_implied.setdefault(a, []).append((t_act, t_act + dur, IMPLIED_EMOTION[do]))
        if do == "stomp" and b.camera is None:
            self.auto_camera(st.index, "shake", t_act + 0.3 * dur, t_act + 0.3 * dur + 0.35 * k, a, 0.35)
        if do == "jump" and float(params.get("height", 0.5)) > 0.5 and b.camera is None:
            self.auto_camera(st.index, "shake", t_act + 0.85 * dur, t_act + 0.85 * dur + 0.35 * k, a, 0.4)
        return max(t_act + dur, walk_end)

    def params(self, st: _Stage, b: BeatSpec, a: str, do: str, t: float, dur: float) -> dict[str, object]:
        amount = b.amount
        if do == "jump":
            return {"height": 0.5 if amount is None else round(0.2 + 0.6 * amount, 3)}
        if do == "hop":
            return {"height": 0.25 if amount is None else round(0.15 + 0.25 * amount, 3)}
        if do == "dance":
            style = b.style if b.style in C.DANCE_STYLES else "bounce"
            return {"style": style}
        if do == "spin":
            return {"turns": 1 if amount is None else 1 + int(round(2 * amount))}
        if do == "grow":
            return {"factor": 1.5 if amount is None else round(1.0 + amount, 3)}
        if do == "shrink":
            return {"factor": 0.6 if amount is None else round(1.0 - 0.5 * amount, 3)}
        if do == "wave":
            return {"hand": "r"}
        if do == "turn":
            to = b.to if b.to in ("left", "right") else b.look if b.look in ("left", "right", "camera") else None
            if to is None:
                to = "left" if st.face.get(a, 0) > 0 else "right"
            st.face[a] = _FACING[to]
            return {"to": to}
        if do == "point":
            x = st.cur[a]
            target = None
            tgt = b.target if b.target in st.cur and b.target != a else None
            if tgt is None and isinstance(b.to, str) and b.to in st.cur and b.to != a:
                tgt = b.to
            if tgt is not None:
                target, tx = tgt, st.cur[tgt]
            elif b.to in ("left", "right"):
                tx = 0.0 if b.to == "left" else 1.0
            elif isinstance(b.to, float):
                tx = b.to
            else:
                near = self.nearest(st, a)
                if near is not None:
                    target, tx = near, st.cur[near]
                else:
                    tx = _clamp(x + 0.3 * (st.face.get(a) or 1), 0.0, 1.0)
            if target is not None:
                self.looks.append(LookSpan(a, target, t, t + dur))
            if abs(tx - x) > 1e-3:
                st.face[a] = 1 if tx > x else -1
            return {"target": target, "tx": tx}
        return {}

    def pairs(self, st: _Stage, b: BeatSpec, who: list[str], t: float, meet: dict[str, float]) -> float:
        """hug/high_five: оба подходят друг к другу (два walk), потом действие у обоих."""
        k = self.k
        do = b.do or "hug"
        couples: list[tuple[str, str]] = []
        solo: list[str] = []
        if len(who) == 1:
            a = who[0]
            p = b.target if b.target in st.cur and b.target != a else None
            if p is None and isinstance(b.to, str) and b.to in st.cur and b.to != a:
                p = b.to
            if p is None:
                p = self.nearest(st, a)
            if p is None:
                solo.append(a)
            else:
                couples.append((a, p))
        else:
            couples = list(zip(who[0::2], who[1::2], strict=False))
            if len(who) % 2:
                last = who[-1]
                p = b.target if b.target in st.cur and b.target not in who else None
                if p is not None:
                    couples.append((last, p))
                else:
                    solo.append(last)
        end = t
        for a, p in couples:
            xa, xb = st.cur[a], st.cur[p]
            gap = GAP[do]
            sgn = 1 if xa <= xb else -1
            mid = _clamp((xa + xb) / 2, 0.08 + gap / 2, 0.92 - gap / 2)
            ta, tb = mid - sgn * gap / 2, mid + sgn * gap / 2
            wa = self.walk_to(st, a, ta, t)
            wb = self.walk_to(st, p, tb, t)
            t_act = t + max(wa, wb)
            dur = (b.seconds if b.seconds is not None else ACTION_SECONDS[do]) * k
            self.add_clip(st, Clip(a, do, t_act, t_act + dur, 0, {"target": p, "tx": tb}))
            self.add_clip(st, Clip(p, do, t_act, t_act + dur, 0, {"target": a, "tx": ta}))
            st.face[a], st.face[p] = sgn, -sgn
            meet[a] = meet[p] = t_act
            if do == "hug":
                for x in (a, p):
                    if not (x in who and b.emotion):
                        self.emo_implied.setdefault(x, []).append((t_act, t_act + dur, "love"))
            end = max(end, t_act + dur)
        for a in solo:
            self.warn(f"{do}: актёру {a} не с кем — сделала celebrate")
            dur = ACTION_SECONDS["celebrate"] * k
            self.add_clip(st, Clip(a, "celebrate", t, t + dur, 0, {}))
            end = max(end, t + dur)
        return end

    def walk_to(self, st: _Stage, a: str, x1: float, t: float) -> float:
        x0 = st.cur[a]
        if abs(x1 - x0) <= 0.02:
            return 0.0
        dur = self.move_seconds("walk", x0, x1, None)
        self.add_clip(st, Clip(a, "walk", t, t + dur, 0, {"x0": x0, "x1": x1}))
        st.cur[a] = x1
        return dur

    def nearest(self, st: _Stage, a: str) -> str | None:
        x = st.cur[a]
        others = [o for o in st.parts if o != a and not _offscreen(st.cur[o])]
        if not others:
            return None
        return min(others, key=lambda o: (abs(st.cur[o] - x), st.parts.index(o)))

    def move_xs(self, st: _Stage, a: str, do: str, b: BeatSpec) -> tuple[float, float]:
        x = st.cur[a]
        if do == "walk_in":
            dest = st.home[a]
            if b.to is not None and b.to != "offscreen":
                dest = self.target_x(st, a, b.to, dest)
            if _offscreen(dest):
                dest = 0.5
            side = b.side or ("left" if dest < 0.5 else "right")
            return (OFFSCREEN_L if side == "left" else OFFSCREEN_R), dest
        if do == "walk_out":
            side = b.side or (b.to if b.to in ("left", "right") else None) or ("left" if x < 0.5 else "right")
            return x, (OFFSCREEN_L if side == "left" else OFFSCREEN_R)
        x0 = x
        if b.side is not None:  # «выбегает слева» — из-за кадра
            x0 = OFFSCREEN_L if b.side == "left" else OFFSCREEN_R
        if b.to is not None:
            return x0, self.target_x(st, a, b.to, x0)
        if b.side is not None or _offscreen(x0):
            return x0, st.home[a] if not _offscreen(st.home[a]) else 0.5
        dist = 0.35 if do == "fly" else 0.3
        direction = st.face.get(a) or (1 if x0 < 0.5 else -1)
        x1 = x0 + direction * dist
        if not self.lo - 0.05 <= x1 <= self.hi + 0.05:
            x1 = x0 - direction * dist
        return x0, _clamp(x1, self.lo, self.hi)

    def target_x(self, st: _Stage, a: str, to: float | str, from_x: float) -> float:
        if isinstance(to, (int, float)) and not isinstance(to, bool):
            return _clamp(float(to), 0.04, 0.96)
        if to == "left":
            return self.lo
        if to == "right":
            return self.hi
        if to == "center":
            return 0.5
        if to == "offscreen":
            return OFFSCREEN_L if from_x < 0.5 else OFFSCREEN_R
        if to in st.cur and to != a:
            ox = st.cur[to]
            if _offscreen(ox):
                return from_x if not _offscreen(from_x) else st.home[a]
            side = -1 if from_x <= ox else 1
            x = ox + side * NEAR
            if not 0.06 <= x <= 0.94:
                x = ox - side * NEAR
            return _clamp(x, 0.06, 0.94)
        return from_x

    def move_seconds(self, do: str, x0: float, x1: float, seconds: float | None) -> float:
        if seconds is not None:
            return max(MIN_MOVE, seconds * self.k)
        dist = abs(x1 - x0)
        if dist < 1e-3:
            return ACTION_SECONDS.get(do, 1.0) * self.k
        return max(MIN_MOVE, dist / SPEED.get(do, 0.25) * self.k)

    # ---------- клипы: без перекрытий на слое, цепочка позиций ----------
    def add_clip(self, st: _Stage, clip: Clip) -> None:
        st.clips.append(clip)

    def finish_clips(self, st: _Stage, t_end: float) -> None:
        by: dict[tuple[str, int], list[Clip]] = {}
        for c in st.clips:
            by.setdefault((c.actor, c.layer), []).append(c)
        out_all: list[Clip] = []
        for clips in by.values():
            out_all.extend(_no_overlap(clips))
        out_all = [c for c in out_all if c.t0 < t_end - 1e-4]
        for c in out_all:
            c.t1 = min(c.t1, t_end)
        out_all.sort(key=lambda c: (c.t0, st.parts.index(c.actor) if c.actor in st.parts else 99, c.layer))
        # цепочка позиций: x0 каждого перемещения = где актёр был
        for a in st.parts:
            x = st.home[a]
            for c in out_all:
                if c.actor != a or c.layer != 0 or c.action not in MOVES:
                    continue
                x0 = float(c.params["x0"])  # type: ignore[arg-type]
                # walk_in и «выбегает слева» начинают за кадром нарочно; остальное — откуда актёр пришёл
                if not (c.action == "walk_in" or (_offscreen(x0) and not _offscreen(x))):
                    c.params["x0"] = x
                x = float(c.params["x1"])  # type: ignore[arg-type]
            self.pos[a] = x
        st.clips = out_all
        self.clips.extend(out_all)

    def auto_camera(self, shot: int, kind: str, t0: float, t1: float, focus: str | None, amount: float) -> None:
        """Тряска на приземлении/топоте, рывок на крике — если рядом нет другой камеры этой сцены."""
        for c in self.cameras:
            if c.shot == shot and abs(c.t0 - t0) < 0.8:
                return
        ev = CameraEvent(shot, kind, t0, t1, focus, amount)
        self.auto_ids.add(id(ev))
        self.cameras.append(ev)

    def add_effect(self, shot: int, kind: str, t0: float, t1: float, x: float | None, y: float | None,
                   amount: str) -> None:
        seed = int(hash01(self.spec.seed, "effect", shot, self._n_effect, kind) * 2**31)
        self._n_effect += 1
        self.effects.append(PlannedEffect(shot, kind, t0, t1, x, y, amount, seed))

    def clamp_events(self, shot: int, t0: float, t1: float) -> None:
        """Всё, что началось в этой сцене, заканчивается вместе с ней; начавшееся после её конца — выкинуть."""
        for lst in (self.lines, self.marks, self.looks):
            keep = []
            for ev in lst:
                if ev.t0 >= t0 - EPS:  # события этой сцены (прошлые уже обрезаны)
                    if ev.t0 >= t1 - 1e-4:
                        continue
                    ev.t1 = min(ev.t1, t1)
                keep.append(ev)
            lst[:] = keep
        for ev in self.cameras + self.effects:
            if ev.shot == shot:
                ev.t1 = min(ev.t1, t1)
        self.cameras[:] = [c for c in self.cameras if c.shot != shot or c.t0 < t1 - 1e-4]
        self.effects[:] = [e for e in self.effects if e.shot != shot or e.t0 < t1 - 1e-4]

    def shot_extras(self, i: int, s: ShotSpec, t0: float, t1: float) -> None:
        k = self.k
        if s.camera.move != "static":
            focus = s.camera.focus if s.camera.focus in self.spec.cast else None
            self.cameras.insert(0, CameraEvent(i, s.camera.move, t0, t1, focus, s.camera.amount))
        if s.background.weather in ("snow", "rain"):
            self.add_effect(i, s.background.weather, t0, t1, None, None, "normal")
        for e in s.effects:
            e0 = t0 + (e.at or 0.0) * k
            if e0 >= t1 - 0.2:
                self.warn(f"сцена {i + 1}: эффект {e.kind} at={e.at:g} позже конца сцены — пропустила")
                continue
            if e.seconds is not None:
                e1 = e0 + e.seconds * k
            elif e.kind in SHOT_EFFECT_SHORT:
                e1 = e0 + SHOT_EFFECT_SHORT[e.kind] * k
            else:
                e1 = t1
            self.add_effect(i, e.kind, e0, min(e1, t1), e.x, e.y, e.amount)
        for p in s.props:
            self.props.append(PlannedProp(i, p, p.kind in C.PROPS_3D))
        if s.title is not None:
            ti = s.title
            a0 = t0 + ti.at * k
            if a0 > t1 - 1.0:
                a0 = max(t0, t1 - 1.0)
            a1 = t1 if ti.seconds is None else min(t1, a0 + ti.seconds * k)
            self.titles.append(PlannedTitle(i, ti.text, ti.style, ti.anim, ti.position, a0, max(a1, a0 + 0.3)))

    # ---------- эмоции ----------
    def emotion_spans(self) -> list[EmotionSpan]:
        """Непересекающиеся отрезки: заданная эмоция держится до следующей; эмоция действия — на время действия.
        Из перекрывающихся побеждает начавшаяся позже (при равенстве — заданная явно)."""
        out: list[EmotionSpan] = []
        end = self.duration
        for a in self.spec.cast:
            base = sorted(self.emo_base.get(a, []), key=lambda e: e[0])
            imp = self.emo_implied.get(a, [])
            if not base and not imp:
                continue
            points = sorted({0.0, end, *(e[0] for e in base), *(e[0] for e in imp), *(min(e[1], end) for e in imp)})
            segs: list[list] = []
            for p0, p1 in zip(points, points[1:], strict=False):
                if p1 - p0 < 1e-6 or p0 >= end:
                    continue
                mid = (p0 + p1) / 2
                best: tuple[float, int, str] | None = None
                b_cur = [e for e in base if e[0] <= mid]
                if b_cur:
                    best = (b_cur[-1][0], 1, b_cur[-1][1])
                for e in imp:
                    if e[0] <= mid < e[1] and (best is None or (e[0], 0) > best[:2]):
                        best = (e[0], 0, e[2])
                if best is None:
                    continue
                emo = best[2]
                if segs and segs[-1][2] == emo and abs(segs[-1][1] - p0) < 1e-9:
                    segs[-1][1] = p1
                else:
                    segs.append([p0, p1, emo])
            out.extend(EmotionSpan(a, emo, s0, s1) for s0, s1, emo in segs)
        out.sort(key=lambda e: (e.t0, e.actor))
        return out


def _no_overlap(clips: list[Clip]) -> list[Clip]:
    """Клипы одного актёра на одном слое → без перекрытий. Новое прерывает старое; перемещение не рвётся
    (если новое началось почти сразу — ждёт конца шага); длинное фоновое (танец, сон…) продолжается после."""
    queue: list[tuple[float, int, Clip]] = []
    seq = 0
    for c in clips:
        queue.append((c.t0, seq, c))
        seq += 1
    queue.sort(key=lambda q: (q[0], q[1]))
    out: list[Clip] = []
    while queue:
        _, _, c = queue.pop(0)
        if c.t1 - c.t0 < 1e-4:
            continue
        while out and out[-1].t1 > c.t0 + 1e-9:
            p = out[-1]
            if p.action in MOVES:
                if c.t0 - p.t0 >= 0.3:
                    p.t1 = c.t0  # шаг ускоряется, но приходит туда же
                else:
                    shift = p.t1 - c.t0
                    c.t0 += shift
                    c.t1 += shift
                break
            if p.action in LOOPABLE and p.t1 - c.t1 >= 0.4:
                rest = Clip(p.actor, p.action, c.t1, p.t1, p.layer, dict(p.params))
                bisect.insort(queue, (rest.t0, seq, rest), key=lambda q: (q[0], q[1]))
                seq += 1
            if c.t0 - p.t0 < 0.15:
                out.pop()
            else:
                p.t1 = c.t0
                break
        out.append(c)
    return out


def _squeeze(c: float, k: float = 1.0) -> _Level:
    """Сжатие c 0..1: реплики 16 зн/с, паузы 0.15 → 0.05 с, хвост сцены 0.6 → 0.25 с; k — общий множитель."""
    return _Level(cps=FAST_CPS, breath=BREATH - 0.10 * c, tail=TAIL - 0.35 * c, lead=1.0 - 0.5 * c, k=k)


def _compress(spec: Spec, fps: int, limit: float) -> _Build:
    """Наименьшее сжатие, при котором ролик укладывается в limit (подбор делением пополам)."""
    def build(lv: _Level) -> _Build:
        b = _Build(spec, fps, lv)
        b.run()
        return b

    best = build(_Level(cps=FAST_CPS))
    if best.duration <= limit + EPS:
        return best
    full = build(_squeeze(1.0))
    if full.duration <= limit + EPS:
        lo, hi, best = 0.0, 1.0, full
        for _ in range(10):
            mid = (lo + hi) / 2
            b = build(_squeeze(mid))
            if b.duration <= limit + EPS:
                hi, best = mid, b
            else:
                lo = mid
        return best
    lo, hi = 0.4, 1.0  # множитель времени k: lo укладывается (проверим), hi — нет
    best = build(_squeeze(1.0, lo))
    if best.duration > limit + EPS:
        return best  # дальше обрежет _truncate
    for _ in range(12):
        mid = (lo + hi) / 2
        b = build(_squeeze(1.0, mid))
        if b.duration <= limit + EPS:
            lo, best = mid, b
        else:
            hi = mid
    return best


def compile_plan(spec: Spec, *, fps: int = 24, quality: str = "normal") -> Plan:
    """Spec → Plan: абсолютное время всего. Длиннее spec.max_seconds — ужимает (до +30 %) или SpecError."""
    try:
        fps = int(fps)
    except (TypeError, ValueError):
        fps = 24
    fps = max(6, min(60, fps))
    limit = float(getattr(spec, "max_seconds", 20.0) or 20.0)
    if not spec.shots:
        raise SpecError("shots", "нужна хотя бы одна сцена")
    first = _Build(spec, fps, _Level())
    first.run()
    best = first
    if first.duration > limit + EPS:
        if first.duration > limit * COMPRESS_MAX + EPS:
            per = ", ".join(f"сцена {i + 1} — {d:.1f} с" for i, d in enumerate(first.durations))
            raise SpecError("shots", f"мультик выходит {first.duration:.1f} с, а можно до {limit:g} с ({per}). "
                                     "Сократи реплики, биты или seconds")
        best = _compress(spec, fps, limit)
        how = "реплики быстрее, паузы короче" + (", всё чуть быстрее" if best.k < 1.0 else "")
        best.warnings.insert(0, f"мультик выходил {first.duration:.1f} с при пределе {limit:g} с — ужала до "
                                f"{min(best.duration, limit):.1f} с ({how})")
    plan = Plan(
        w=spec.size[0], h=spec.size[1], fps=fps, seed=spec.seed, duration=best.duration, format=spec.format,
        cast=dict(spec.cast), shots=best.shots, placements=best.placements,
        clips=sorted(best.clips, key=lambda c: (c.t0, c.actor, c.layer)), emotions=best.emotions,
        marks=sorted(best.marks, key=lambda m: (m.t0, m.actor)), lines=sorted(best.lines, key=lambda x: x.t0),
        looks=sorted(best.looks, key=lambda x: (x.t0, x.actor)), props=best.props,
        effects=sorted(best.effects, key=lambda e: (e.t0, e.shot)), titles=best.titles,
        cameras=sorted(best.cameras, key=lambda c: (c.t0, c.shot)), caption=spec.caption,
        warnings=list(spec.warnings) + best.warnings, quality=quality if quality in ("normal", "fast") else "normal",
    )
    if plan.duration > limit + EPS:
        _truncate(plan, limit)
    return plan


def _truncate(plan: Plan, limit: float) -> None:
    """Последняя страховка: обрезать ролик ровно по пределу."""
    plan.duration = limit
    plan.shots = [s for s in plan.shots if s.t0 < limit - 0.5] or plan.shots[:1]
    plan.shots[-1].t1 = limit
    plan.shots[-1].transition = "cut"
    n = len(plan.shots)
    plan.placements = [p for p in plan.placements if p.shot < n]
    plan.props = [p for p in plan.props if p.shot < n]
    for lst in (plan.clips, plan.emotions, plan.marks, plan.lines, plan.looks, plan.effects, plan.titles,
                plan.cameras):
        lst[:] = [ev for ev in lst if ev.t0 < limit - 1e-4]
        for ev in lst:
            ev.t1 = min(ev.t1, limit)
