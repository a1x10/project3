"""Общие типы мультика — договор между частями движка.

Spec — сценарий, как его понял spec.parse_spec() (уже проверенный, с подставленными значениями по умолчанию).
Plan — тот же мультик, разложенный по времени timeline.compile_plan(): у всего абсолютные секунды от начала ролика.
Pose — поза персонажа в один момент; Look — его внешность. Всё время — в секундах, координаты сцены — доли кадра
(x и y от 0 до 1, y вниз), размеры — доли высоты кадра. Пиксели появляются только при рисовании.

Plan целиком передаётся в процесс рендера (pickle), поэтому здесь только простые данные — без функций и cairo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

RGB = tuple[float, float, float]  # каждая составляющая 0..1


class AnimError(Exception):
    """Понятная модели ошибка (по-русски): что не так и как поправить."""


class SpecError(AnimError):
    """Ошибка в сценарии: где именно (путь вида shots[0].beats[2].do) и что можно вместо этого."""

    def __init__(self, path: str, msg: str, allowed: Sequence[str] = ()):
        self.path = path
        self.allowed = tuple(allowed)
        text = f"{path}: {msg}" if path else msg
        if self.allowed:
            text += ". Можно: " + ", ".join(self.allowed[:40])
        super().__init__(text)


# ======================= сценарий (spec.parse_spec) =======================
@dataclass(frozen=True)
class OutfitPart:
    style: str  # catalog.TOPS / catalog.BOTTOMS
    color: RGB
    print: str | None = None  # star | heart | stripes | number:7 | text:МАША


@dataclass(frozen=True)
class CastSpec:
    id: str
    base: str  # catalog.BASES
    name: str = ""
    skin: RGB | None = None
    hair: str | None = None  # catalog.HAIR; None — как принято у этой базы
    hair_color: RGB | None = None
    eyes: RGB | None = None
    top: OutfitPart | None = None
    bottom: OutfitPart | None = None
    shoes: RGB | None = None
    color: RGB | None = None  # основной цвет у зверей/роботов/монстров
    accent: RGB | None = None
    accessories: tuple[str, ...] = ()
    size: float = 1.0  # 0.6–1.4, относительный рост


@dataclass(frozen=True)
class PlaceSpec:
    x: float | None = None  # 0..1; None — расставить автоматически
    lane: str = "mid"  # back | mid | front
    facing: str | None = None  # left | right | camera; None — лицом к центру кадра


@dataclass(frozen=True)
class PropSpec:
    id: str
    kind: str  # catalog.PROPS
    x: float = 0.5  # центр предмета, доли кадра
    y: float = 0.6
    size: float = 0.2  # доля высоты кадра
    color: RGB | None = None
    material: str | None = None  # catalog.MATERIALS, для 3D
    anim: str = "none"  # catalog.PROP_ANIMS
    text: str = ""  # для sign / text3d
    svg_png: bytes | None = None  # kind == "svg": рисунок модели, уже очищенный и растрированный в боте (PNG)
    lane: str = "mid"


@dataclass(frozen=True)
class EffectSpec:
    kind: str  # catalog.EFFECTS
    at: float | None = None  # секунды от начала СЦЕНЫ; None — с начала сцены (или вместе с битом)
    seconds: float | None = None
    x: float | None = None
    y: float | None = None
    amount: str = "normal"  # few | normal | lots


@dataclass(frozen=True)
class TitleSpec:
    text: str
    style: str = "gold3d"  # catalog.TITLE_STYLES
    anim: str = "drop"  # catalog.TITLE_ANIMS
    position: str = "top"  # top | center | bottom
    at: float = 0.0  # от начала сцены
    seconds: float | None = None  # None — до конца сцены


@dataclass(frozen=True)
class CameraSpec:
    move: str = "static"  # catalog.CAMERA_MOVES — движение на всю сцену
    focus: str | None = None  # id актёра
    amount: float = 0.5  # 0..1


@dataclass(frozen=True)
class BackgroundSpec:
    preset: str = "park"  # catalog.BACKGROUNDS
    time: str = "day"  # catalog.TIMES
    weather: str = "clear"  # catalog.WEATHER
    text: str = ""  # надпись на доске/табличке фона (classroom, stage)
    accent: RGB | None = None


@dataclass(frozen=True)
class BeatSpec:
    """Один «бит» сценария: актёрский (who + do/реплика), эффект или камера."""

    who: tuple[str, ...] = ()  # id актёров; «all» уже раскрыт в список
    do: str | None = None  # catalog.ACTIONS
    line: str | None = None  # текст реплики
    line_kind: str = "say"  # say | think | shout | whisper
    emotion: str | None = None
    mark: str | None = None
    to: float | str | None = None  # куда идти: x 0..1, id актёра, left/right/center/offscreen
    side: str | None = None  # откуда входить: left | right
    target: str | None = None  # на кого показывать/кого обнимать
    look: str | None = None  # id | camera | left | right
    style: str | None = None  # стиль танца и т. п.
    seconds: float | None = None
    at: float | None = None  # от начала сцены
    with_prev: bool = False
    effect: EffectSpec | None = None  # бит-эффект
    camera: str | None = None  # бит-камера: catalog.CAMERA_BEATS
    camera_focus: str | None = None
    amount: float | None = None


@dataclass(frozen=True)
class ShotSpec:
    background: BackgroundSpec
    camera: CameraSpec
    place: dict[str, PlaceSpec]
    props: tuple[PropSpec, ...]
    effects: tuple[EffectSpec, ...]
    title: TitleSpec | None
    beats: tuple[BeatSpec, ...]
    seconds: float | None
    transition: str  # переход к СЛЕДУЮЩЕЙ сцене; catalog.TRANSITIONS


@dataclass(frozen=True)
class Spec:
    format: str  # square | wide | tall
    size: tuple[int, int]  # (w, h) в пикселях
    cast: dict[str, CastSpec]
    shots: tuple[ShotSpec, ...]
    caption: str
    seed: int
    warnings: tuple[str, ...]  # что поправили сами (модель увидит в ответе инструмента)


# ======================= план по времени (timeline.compile_plan) =======================
@dataclass
class Clip:
    """Действие актёра на отрезке [t0, t1). Слой 0 — тело и перемещение, 1 — руки и жесты."""

    actor: str
    action: str  # catalog.ACTIONS
    t0: float
    t1: float
    layer: int = 0
    # уже посчитанные параметры:
    #   walk/walk_in/walk_out/run/fly: x0, x1 (доли кадра; за кадром — <0 или >1)
    #   jump/hop: height (доля роста 0.2–0.8); dance: style; spin: turns; grow/shrink: factor
    #   point/hug/high_five: target (id), tx (x цели); turn: to (left|right|camera); wave: hand (l|r)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmotionSpan:
    actor: str
    emotion: str  # catalog.EMOTIONS
    t0: float
    t1: float  # до следующей эмоции этого актёра или конца его появления


@dataclass
class MarkEvent:
    actor: str
    kind: str  # catalog.MARKS
    t0: float
    t1: float


@dataclass
class Line:
    """Реплика: пузырь над головой и движение рта (для say/shout/whisper)."""

    actor: str
    text: str
    kind: str  # say | think | shout | whisper
    t0: float
    t1: float


@dataclass
class LookSpan:
    actor: str
    target: str  # id актёра | camera | left | right
    t0: float
    t1: float


@dataclass
class ActorShot:
    """Где актёр стоит в начале сцены и виден ли он в ней вообще."""

    actor: str
    shot: int
    x: float  # доли кадра
    lane: str  # back | mid | front
    facing: int  # 1 — вправо, -1 — влево, 0 — в камеру
    visible: bool = True  # False — в сцене не участвует (или появится через appear/walk_in)


@dataclass
class PlannedProp:
    shot: int
    prop: PropSpec
    is3d: bool


@dataclass
class PlannedEffect:
    shot: int
    kind: str
    t0: float
    t1: float
    x: float | None
    y: float | None
    amount: str
    seed: int


@dataclass
class PlannedTitle:
    shot: int
    text: str
    style: str
    anim: str
    position: str
    t0: float
    t1: float


@dataclass
class CameraEvent:
    """Движение камеры: на всю сцену (move из CAMERA_MOVES) или короткое из бита (CAMERA_BEATS)."""

    shot: int
    kind: str
    t0: float
    t1: float
    focus: str | None = None
    amount: float = 0.5


@dataclass
class PlannedShot:
    index: int
    t0: float
    t1: float
    background: BackgroundSpec
    transition: str  # переход к следующей сцене (у последней — cut)
    transition_s: float = 0.5  # длительность перехода; он идёт на отрезке [t1 - s/2, t1 + s/2]


@dataclass
class Plan:
    w: int
    h: int
    fps: int
    seed: int
    duration: float
    format: str
    cast: dict[str, CastSpec]
    shots: list[PlannedShot]
    placements: list[ActorShot]
    clips: list[Clip]
    emotions: list[EmotionSpan]
    marks: list[MarkEvent]
    lines: list[Line]
    looks: list[LookSpan]
    props: list[PlannedProp]
    effects: list[PlannedEffect]
    titles: list[PlannedTitle]
    cameras: list[CameraEvent]
    caption: str = ""
    warnings: list[str] = field(default_factory=list)
    quality: str = "normal"  # normal | fast (быстрее: проще сглаживание, меньше полигонов)

    @property
    def n_frames(self) -> int:
        return max(1, int(round(self.duration * self.fps)))

    def shot_at(self, t: float) -> PlannedShot:
        for shot in self.shots:
            if t < shot.t1:
                return shot
        return self.shots[-1]


# ======================= персонаж в кадре =======================
@dataclass
class Pose:
    """Поза куклы в один момент. Углы — радианы; длины — единицы куклы (рост 300)."""

    bob: float = 0.0  # вертикальный сдвиг всей куклы, минус — вверх (-200..40)
    lean: float = 0.0  # наклон корпуса вокруг таза (-0.4..0.4)
    squash: float = 1.0  # 0.7..1.3, объём сохраняется: x / sqrt(s), y * s, относительно ступней
    head_tilt: float = 0.0  # -0.4..0.4
    yaw: float = 0.0  # поворот головы и корпуса -1..1 (2.5D)
    arm_l: tuple[float, float] = (0.25, 0.3)  # (плечо: 0 — вниз, + наружу/вверх до 3.1; локоть 0..2.2)
    arm_r: tuple[float, float] = (0.25, 0.3)
    leg_l: tuple[float, float] = (0.06, 0.0)  # (бедро -0.9..0.9; колено 0..1.4)
    leg_r: tuple[float, float] = (0.06, 0.0)
    hand_l: str = "open"  # open | fist | point | peace | hold
    hand_r: str = "open"
    look: tuple[float, float] = (0.0, 0.0)  # зрачки -1..1; голова следует на 30 %
    blink: float = 0.0  # 0 — открыты, 1 — закрыты
    emotion: str = "neutral"
    emotion_w: float = 1.0  # сила эмоции 0..1 (плавная смена)
    mouth_open: float = 0.0  # 0..1
    mouth_shape: str = "m"  # a | o | e | m
    hair_swing: float = 0.0  # -1..1, вторичное движение
    tail_swing: float = 0.0
    ear_swing: float = 0.0
    wing_flap: float = 0.0  # фаза взмаха крыльев -1..1
    marks: tuple[tuple[str, float], ...] = ()  # (значок, прогресс 0..1) над головой
    scale: float = 1.0  # grow/shrink/appear
    alpha: float = 1.0  # appear/poof, призрак
    t: float = 0.0  # абсолютное время (для анимированных деталей: спирали, слёзы)


@dataclass
class ActorFrame:
    """Где и как нарисовать актёра в момент t (результат actions.actor_frame)."""

    actor: str
    visible: bool
    pose: Pose
    x: float  # доли кадра (точка между ступнями)
    lane: str
    facing: int  # 1 / -1 (в камеру — 1 с yaw 0)
    lift: float = 0.0  # подъём над землёй в долях роста (прыжок, полёт) — для тени
    speaking: bool = False
