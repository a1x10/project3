"""Эмоции Стеллы как набор параметров лица.

Каждая эмоция — это «ручки» мимики: насколько опущены веки, куда наклонены брови,
насколько расширены зрачки, как часто бегает взгляд и т.д. Между эмоциями лицо
плавно перетекает (линейная интерполяция параметров), поэтому переходы живые.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace


@dataclass
class FaceParams:
    # --- форма глаза
    eye_w: float = 1.0          # ширина глаза (множитель)
    eye_h: float = 1.0          # высота глаза (широко раскрытые > 1)
    upper: float = 0.08         # верхнее веко: 0 — открыто, 1 — почти закрыто
    closed: float = 0.0         # глаза закрыты (сон); моргание добавляется сверху
    upper_tilt: float = 0.0     # + внутренний угол века ниже (злость), − выше (грусть)
    upper_arch: float = 0.6     # выгнутость края века
    lower: float = 0.06         # нижнее веко поднято (прищур)
    lower_curve: float = 0.1    # + нижнее веко дугой вверх — «улыбающиеся глаза»
    squint_asym: float = 0.0    # + правый глаз прищурен сильнее левого (презрение)
    # --- радужка и зрачок
    iris: float = 1.0           # размер радужки
    pupil: float = 0.42         # зрачок относительно радужки (0.25 узкий … 0.85 огромный)
    tint: tuple = (255, 255, 255)
    tint_amt: float = 0.0       # насколько окрасить радужку в tint
    saturation: float = 1.0     # 0 — серые «потухшие» глаза
    shine: float = 0.9          # блики («блеск в глазах»)
    sparkle: float = 0.0        # искорки
    # --- взгляд
    gaze_x: float = 0.0
    gaze_y: float = 0.0         # + вниз
    converge: float = 0.0       # + сведены на собеседника, − «сквозь» (расфокус)
    wander: float = 0.45        # амплитуда «бегающего» взгляда
    saccade_rate: float = 0.6   # скачков взгляда в секунду
    blink_rate: float = 14.0    # морганий в минуту
    blink_time: float = 0.16    # длительность моргания, с
    # --- брови
    brow_y: float = 0.0         # + подняты
    brow_angle: float = 0.0     # + внутренние концы вверх (грусть/страх), − вниз (гнев)
    brow_curve: float = 0.4     # дуга
    brow_in: float = 0.0        # сведены к переносице
    brow_asym: float = 0.0      # + правая бровь выше левой
    brow_alpha: float = 1.0
    # --- лицо
    crow: float = 0.0           # «лучики» в уголках глаз
    blush: float = 0.0          # румянец
    tears: float = 0.0          # слёзы / влажный блеск
    tremble: float = 0.0        # дрожь (страх, ярость)
    glow: float = 0.0           # красное свечение по краям (гнев)
    tilt: float = 0.0           # наклон головы
    bob: float = 0.0            # подпрыгивание (радость)
    bob_speed: float = 1.5
    # --- рот
    mouth_curve: float = 0.25   # + улыбка, − грусть
    mouth_open: float = 0.0
    mouth_asym: float = 0.0     # + правый уголок вверх (ухмылка)
    mouth_w: float = 1.0
    # --- эффекты
    hearts: float = 0.0
    anger_mark: float = 0.0
    sweat: float = 0.0
    zzz: float = 0.0
    dots: float = 0.0           # «думаю…»
    ring: float = 0.0           # индикатор «слушаю»

    def lerp(self, other: "FaceParams", t: float) -> "FaceParams":
        t = max(0.0, min(1.0, t))
        out = {}
        for f in fields(self):
            a, b = getattr(self, f.name), getattr(other, f.name)
            if isinstance(a, tuple):
                out[f.name] = tuple(x + (y - x) * t for x, y in zip(a, b))
            else:
                out[f.name] = a + (b - a) * t
        return FaceParams(**out)

    def approach(self, target: "FaceParams", k: float) -> None:
        """Шаг экспоненциального сглаживания к target (на месте)."""
        for f in fields(self):
            a, b = getattr(self, f.name), getattr(target, f.name)
            if isinstance(a, tuple):
                setattr(self, f.name, tuple(x + (y - x) * k for x, y in zip(a, b)))
            else:
                setattr(self, f.name, a + (b - a) * k)


NEUTRAL = FaceParams()

# Описания взяты из задания: как выглядят глаза человека при каждой эмоции.
PRESETS: dict[str, dict] = {
    "neutral": {},
    # Радость и счастье: глаза слегка сужаются, в уголках лучики-морщинки, зрачки чуть
    # расширены, взгляд мягкий и искрящийся.
    "joy": dict(eye_h=0.97, upper=0.1, upper_arch=0.9, lower=0.22, lower_curve=0.68, pupil=0.55, gaze_y=-0.3,
                shine=1.0, sparkle=0.9, brow_y=0.3, brow_angle=0.1, brow_curve=0.75, crow=1.0,
                blush=0.35, mouth_curve=1.0, mouth_open=0.18, bob=0.6, bob_speed=1.7,
                blink_rate=12, wander=0.35, saccade_rate=0.5, tint=(120, 230, 255), tint_amt=0.25),
    # Грусть и печаль: взгляд вниз/расфокусирован, веки опущены, внутренние уголки глаз и
    # бровей приподняты. Тоска и уязвимость.
    "sadness": dict(upper=0.36, upper_tilt=-0.6, upper_arch=0.3, lower=0.1, lower_curve=-0.05,
                    gaze_y=0.6, converge=-0.15, wander=0.2, saccade_rate=0.25, blink_rate=9,
                    blink_time=0.32, shine=0.5, tears=0.75, brow_y=0.2, brow_angle=0.95,
                    brow_curve=0.15, saturation=0.55, mouth_curve=-0.75, mouth_w=0.8,
                    tint=(110, 140, 220), tint_amt=0.3),
    # Гнев и злость: брови сведены к переносице и опущены, глаза сужены, мышцы напряжены.
    # Взгляд пронзительный, «колющий».
    "anger": dict(eye_h=0.95, upper=0.36, upper_tilt=0.9, upper_arch=0.1, lower=0.2, lower_curve=-0.2,
                  pupil=0.27, iris=0.92, wander=0.04, saccade_rate=0.08, blink_rate=4, blink_time=0.12,
                  shine=0.55, brow_y=-0.8, brow_angle=-1.0, brow_curve=0.0, brow_in=1.0, tremble=0.25,
                  glow=0.45, mouth_curve=-0.6, mouth_w=0.7, tint=(255, 60, 40), tint_amt=0.6),
    # Страх и испуг: глаза широко раскрыты, видна белая полоска белка над радужкой, зрачки
    # резко расширены. Взгляд застывший или суетливый, ищущий выход.
    "fear": dict(eye_w=1.05, eye_h=1.22, upper=0.0, upper_arch=0.8, lower=0.0, lower_curve=0.0,
                 iris=0.74, pupil=0.75, gaze_y=0.16, wander=1.0, saccade_rate=2.6, blink_rate=24,
                 blink_time=0.1, brow_y=0.55, brow_angle=1.0, brow_curve=0.35, brow_in=0.6,
                 tremble=0.6, sweat=1.0, mouth_curve=-0.45, mouth_open=0.22, mouth_w=0.75,
                 saturation=0.85, tint=(200, 220, 255), tint_amt=0.2),
    # Удивление: брови высоко подняты, глаза широко распахнуты, взгляд устремлён на объект.
    # Похоже на страх, но без напряжения.
    "surprise": dict(eye_w=1.04, eye_h=1.24, upper=0.0, lower=0.0, lower_curve=0.0, iris=0.9, pupil=0.5,
                     wander=0.03, saccade_rate=0.08, blink_rate=5, shine=1.0, brow_y=1.0, brow_angle=0.15,
                     brow_curve=1.0, mouth_curve=0.0, mouth_open=0.8, mouth_w=0.5),
    # Интерес, влюблённость, симпатия: зрачки сильно расширены, взгляд долгий, тёплый,
    # внимательный, сфокусированный на человеке.
    "love": dict(upper=0.1, upper_arch=0.8, lower=0.17, lower_curve=0.45, iris=1.05, pupil=0.82,
                 converge=0.3, wander=0.05, saccade_rate=0.1, blink_rate=8, blink_time=0.36, shine=1.0,
                 sparkle=0.5, brow_y=0.25, brow_angle=0.3, brow_curve=0.6, blush=0.85, hearts=1.0,
                 tilt=0.35, mouth_curve=0.7, tint=(255, 120, 190), tint_amt=0.35),
    # Интерес — то же внимание, но без «сердечек».
    "interest": dict(eye_h=1.06, upper=0.04, lower=0.08, iris=1.02, pupil=0.7, converge=0.2, wander=0.08,
                     saccade_rate=0.15, blink_rate=8, shine=1.0, brow_y=0.4, brow_angle=0.2, brow_curve=0.6,
                     brow_asym=0.25, tilt=0.25, mouth_curve=0.35),
    # Презрение и отвращение: один уголок рта кривится, глаза слегка прищурены — смотрит
    # на что-то неприятное свысока.
    "contempt": dict(upper=0.33, upper_tilt=0.1, upper_arch=0.25, lower=0.24, lower_curve=0.0,
                     squint_asym=0.4, gaze_x=0.35, gaze_y=0.35, wander=0.08, saccade_rate=0.15,
                     blink_rate=9, blink_time=0.26, shine=0.6, brow_y=0.05, brow_asym=0.7,
                     brow_angle=-0.15, brow_curve=0.3, mouth_curve=0.0, mouth_asym=0.85, mouth_w=0.8,
                     tilt=-0.15, tint=(170, 210, 90), tint_amt=0.2),
    # Уверенность и вызов: прямой, открытый, неподвижный и твёрдый взгляд «глаза в глаза»,
    # который не отводят первыми.
    "confidence": dict(upper=0.17, upper_tilt=0.18, upper_arch=0.35, lower=0.12, lower_curve=0.1,
                       pupil=0.45, gaze_x=0.0, gaze_y=0.0, converge=0.12, wander=0.0, saccade_rate=0.0,
                       blink_rate=2, blink_time=0.14, shine=1.0, brow_y=-0.12, brow_angle=-0.3,
                       brow_curve=0.2, mouth_curve=0.35, mouth_asym=0.3),
    # Усталость или скука: тяжёлый взгляд «сквозь» собеседника, медленное моргание,
    # полуприкрытые веки, нет фокуса и блеска.
    "boredom": dict(upper=0.52, upper_tilt=-0.12, upper_arch=0.12, lower=0.1, lower_curve=0.0,
                    pupil=0.36, gaze_y=0.12, converge=-0.35, wander=0.22, saccade_rate=0.12,
                    blink_rate=7, blink_time=0.75, shine=0.12, brow_y=-0.1, brow_angle=0.1,
                    brow_curve=0.1, saturation=0.4, mouth_curve=-0.15, mouth_w=0.7),
    # --- служебные состояния
    "listening": dict(eye_h=1.07, upper=0.02, pupil=0.56, brow_y=0.3, brow_curve=0.6, wander=0.08,
                      saccade_rate=0.15, converge=0.1, ring=1.0, mouth_curve=0.3),
    "thinking": dict(gaze_x=0.55, gaze_y=-0.55, upper=0.1, brow_y=0.2, brow_asym=0.45, wander=0.08,
                     saccade_rate=0.2, dots=1.0, mouth_curve=0.0, mouth_asym=-0.3, mouth_w=0.7),
    "sleep": dict(closed=1.0, upper=0.3, lower=0.0, lower_curve=0.0, brow_y=-0.05, brow_angle=0.05, zzz=1.0,
                  wander=0.0, saccade_rate=0.0, blink_rate=0.0, mouth_curve=0.15, mouth_w=0.6,
                  bob=0.35, bob_speed=0.25, shine=0.0),
}

ALIASES = {
    "радость": "joy", "счастье": "joy", "веселье": "joy", "happy": "joy", "smile": "joy",
    "грусть": "sadness", "печаль": "sadness", "тоска": "sadness", "sad": "sadness",
    "гнев": "anger", "злость": "anger", "ярость": "anger", "раздражение": "anger", "angry": "anger",
    "страх": "fear", "испуг": "fear", "scared": "fear",
    "удивление": "surprise", "изумление": "surprise", "surprised": "surprise",
    "любовь": "love", "влюбленность": "love", "влюблённость": "love", "симпатия": "love", "нежность": "love",
    "интерес": "interest", "любопытство": "interest", "curious": "interest",
    "презрение": "contempt", "отвращение": "contempt", "брезгливость": "contempt", "disgust": "contempt",
    "уверенность": "confidence", "вызов": "confidence", "решимость": "confidence",
    "усталость": "boredom", "скука": "boredom", "tired": "boredom", "bored": "boredom",
    "спокойствие": "neutral", "нейтрально": "neutral", "calm": "neutral",
    "сон": "sleep", "думаю": "thinking", "слушаю": "listening",
}

EMOTION_NAMES_RU = {
    "neutral": "спокойствие", "joy": "радость", "sadness": "грусть", "anger": "злость", "fear": "страх",
    "surprise": "удивление", "love": "симпатия", "interest": "интерес", "contempt": "презрение",
    "confidence": "уверенность", "boredom": "скука", "listening": "слушаю", "thinking": "думаю",
    "sleep": "сон",
}

EMOTIONS = ["joy", "sadness", "anger", "fear", "surprise", "love", "interest", "contempt", "confidence", "boredom"]


_STEM_ALIASES: dict[str, str] = {}


def resolve(name: str | None) -> str:
    """'радость' / 'симпатию' / 'joy' -> 'joy'; неизвестное -> 'neutral'."""
    if not name:
        return "neutral"
    key = name.strip().lower().replace("ё", "е")
    if key in PRESETS:
        return key
    if key in ALIASES:
        return ALIASES[key]
    from ..nlp.text import stem  # падежи: «покажи грусть / симпатию / скуку»
    if not _STEM_ALIASES:
        for alias, target in ALIASES.items():
            _STEM_ALIASES[stem(alias)] = target
    return _STEM_ALIASES.get(stem(key), "neutral")


def preset(name: str, intensity: float = 1.0) -> FaceParams:
    full = replace(NEUTRAL, **PRESETS[resolve(name)])
    return NEUTRAL.lerp(full, intensity) if intensity < 1.0 else full
