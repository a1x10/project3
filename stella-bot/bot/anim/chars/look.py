"""Внешность персонажа: Look собирается из CastSpec (что задала модель) и хороших значений по умолчанию для базы.

У каждой базы — готовый «дизайн», поэтому {"base": "cat"} уже выглядит законченным. Если в ролике два актёра одной
базы без подробностей, второй получает другой вариант (по хэшу его id), чтобы они не были близнецами. Стелла —
всегда одна и та же (лавандовые хвостики со звёздами, розовая футболка).

Пропорции (Build) — в единицах куклы: рост 300, (0, 0) — точка между ступнями, y вниз.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import catalog as C
from ..ease import hash01
from ..model import RGB, CastSpec
from ..palette import SKIN_TONES, hx, lighten, mix, mul

# какие базы как устроены
HUMAN_BASES = frozenset(C.HUMANS)
CHUNKY_BASES = frozenset({"cat", "dog", "fox", "bunny", "bear", "dragon"})
TOY_BASES = frozenset(C.BASES_3D)


@dataclass(frozen=True)
class Build:
    """Пропорции куклы. Голова и волосы — около 42 % роста (чиби ≈ 2.6 головы)."""

    head_r: float = 62.0  # радиус головы
    head_w: float = 1.0  # ширина головы относительно радиуса
    torso: float = 78.0  # от таза до шеи
    neck: float = 56.0  # от шеи до центра головы
    shoulder: float = 31.0  # полуширина плеч (суставы)
    hip_w: float = 15.0  # полуширина тазобедренных суставов
    chest_w: float = 33.0  # полуширина корпуса у плеч
    waist_w: float = 30.0  # у таза
    upper_arm: float = 30.0
    forearm: float = 28.0
    arm_w: float = 15.0
    hand_r: float = 11.0
    thigh: float = 36.0
    shin: float = 34.0
    leg_w: float = 20.0
    foot: tuple[float, float] = (17.0, 10.0)
    body: str = "human"  # human | chunky | robot | blob | ghost | toy
    lean0: float = 0.0  # привычный наклон (сутулость)

    @property
    def hip_y(self) -> float:
        """Высота таза: ноги прямо вниз + немного на подошву."""
        return -(self.thigh + self.shin + 2.0)

    @property
    def head_y(self) -> float:
        """Центр головы в стойке «смирно»."""
        return self.hip_y - self.torso - self.neck


HUMAN = Build()
TEEN = Build(head_r=58.0, torso=88.0, neck=52.0, shoulder=33.0, chest_w=35.0, waist_w=31.0, upper_arm=36.0,
             forearm=33.0, thigh=44.0, shin=42.0, leg_w=21.0, foot=(18.0, 10.0))
CHUNKY = Build(head_r=66.0, head_w=1.1, torso=64.0, neck=58.0, shoulder=33.0, hip_w=19.0, chest_w=36.0,
               waist_w=43.0, upper_arm=27.0, forearm=25.0, arm_w=21.0, hand_r=13.0, thigh=27.0, shin=25.0,
               leg_w=27.0, foot=(19.0, 12.0), body="chunky")
BEAR = Build(head_r=68.0, head_w=1.12, torso=66.0, neck=58.0, shoulder=36.0, hip_w=21.0, chest_w=40.0, waist_w=48.0,
             upper_arm=27.0, forearm=25.0, arm_w=23.0, hand_r=14.0, thigh=26.0, shin=24.0, leg_w=29.0,
             foot=(21.0, 13.0), body="chunky")
ROBOT = Build(head_r=60.0, head_w=1.05, torso=76.0, neck=60.0, shoulder=36.0, hip_w=16.0, chest_w=36.0, waist_w=34.0,
              upper_arm=30.0, forearm=28.0, arm_w=15.0, hand_r=12.0, thigh=34.0, shin=32.0, leg_w=18.0,
              foot=(19.0, 11.0), body="robot")
ALIEN = Build(head_r=64.0, head_w=1.0, torso=70.0, neck=56.0, shoulder=29.0, chest_w=31.0, waist_w=30.0,
              upper_arm=30.0, forearm=28.0, arm_w=14.0, hand_r=11.0, thigh=36.0, shin=34.0, leg_w=18.0,
              foot=(17.0, 10.0), body="alien")
BLOB = Build(head_r=70.0, head_w=1.0, torso=40.0, neck=46.0, shoulder=52.0, hip_w=26.0, chest_w=72.0, waist_w=74.0,
             upper_arm=24.0, forearm=22.0, arm_w=21.0, hand_r=13.0, thigh=18.0, shin=16.0, leg_w=26.0,
             foot=(21.0, 13.0), body="blob")
GHOST = Build(head_r=62.0, torso=40.0, neck=56.0, shoulder=60.0, chest_w=70.0, waist_w=72.0, upper_arm=10.0,
              forearm=8.0, arm_w=20.0, hand_r=15.0, thigh=36.0, shin=34.0, body="ghost")
TOY = Build(body="toy")

BUILDS: dict[str, Build] = {
    "stella": HUMAN, "boy": HUMAN, "girl": HUMAN, "teen": TEEN,
    "cat": CHUNKY, "dog": CHUNKY, "fox": CHUNKY, "bunny": CHUNKY, "bear": BEAR, "dragon": CHUNKY,
    "robot": ROBOT, "alien": ALIEN, "ghost": GHOST, "monster": BLOB,
    "robot3d": TOY, "penguin3d": TOY, "snowman3d": TOY,
}
KINDS: dict[str, str] = {
    "stella": "human", "boy": "human", "girl": "human", "teen": "human",
    "cat": "creature", "dog": "creature", "fox": "creature", "bunny": "creature", "bear": "creature",
    "dragon": "creature", "robot": "robot", "alien": "alien", "ghost": "ghost", "monster": "monster",
    "robot3d": "toy", "penguin3d": "toy", "snowman3d": "toy",
}


@dataclass(frozen=True)
class Look:
    """Внешность актёра (неизменяемая: её можно класть в кеш и сравнивать)."""

    base: str
    skin: RGB  # кожа у людей; у зверей/роботов — цвет «кожи» лица (обычно = color)
    color: RGB  # основной цвет: мех, металл, тело; у людей — цвет верха
    accent: RGB  # второй цвет: заколки, кепка, уши изнутри, рожки, антенны
    eyes: RGB
    kind: str = "human"  # human | creature | robot | alien | ghost | monster | toy
    hair: str = "none"  # catalog.HAIR
    hair_color: RGB = (0.23, 0.16, 0.12)
    top: str | None = None  # catalog.TOPS или None (без одежды)
    top_color: RGB = (1.0, 0.49, 0.71)
    top_print: str | None = None  # star | heart | stripes | number:7 | text:МАША
    bottom: str | None = None  # catalog.BOTTOMS или None
    bottom_color: RGB = (0.23, 0.33, 0.55)
    shoes: RGB = (0.17, 0.18, 0.26)
    belly: RGB = (1.0, 0.95, 0.88)  # светлое брюшко / мордочка у зверей
    accessories: tuple[str, ...] = ()
    lashes: bool = False
    name: str = ""
    size: float = 1.0  # относительный рост (уже учитывает compose через layout.char_height)
    build: Build = field(default=HUMAN)

    @property
    def human(self) -> bool:
        return self.kind == "human"

    def has(self, accessory: str) -> bool:
        return accessory in self.accessories


# ---------- готовые дизайны (вариант 0 — «канонический») ----------
def _h(s: str | None) -> RGB | None:
    return hx(s) if s else None


_HUMAN: dict[str, list[dict]] = {
    "stella": [dict(skin="light", hair="twintails", hair_color="#b48cff", eyes="#8a4dff", lashes=True,
                    top=("tshirt", "#ff7eb6", "star"), bottom=("skirt", "#5b4bd6"), shoes="#ffffff",
                    accent="#ffd23f", acc=("star_clips",))],
    "boy": [
        dict(skin="fair", hair="spiky", hair_color="#3b2a20", eyes="#2f8f5b", top=("tshirt", "#2ec4b6", None),
             bottom=("pants", "#2b3a67"), shoes="#ff5d5d", accent="#ff9f1c", acc=("cap",)),
        dict(skin="tan", hair="short", hair_color="#1d1412", eyes="#6b3f1d", top=("hoodie", "#ff7f6b", None),
             bottom=("shorts", "#3a6df0"), shoes="#ffffff", accent="#ffd23f", acc=()),
        dict(skin="light", hair="curly", hair_color="#e8b04a", eyes="#3a7bd5", top=("sweater", "#7cdf6b", None),
             bottom=("pants", "#5b4bd6"), shoes="#2b2d42", accent="#ff3b3b", acc=("glasses",)),
        dict(skin="dark", hair="short", hair_color="#1d1412", eyes="#5a3418", top=("shirt", "#ffd23f", None),
             bottom=("pants", "#30343f"), shoes="#ff9f1c", accent="#3ec1ff", acc=()),
    ],
    "girl": [
        dict(skin="fair", hair="long", hair_color="#7a4024", eyes="#2f9e8f", lashes=True, top=("dress", "#ffb347", None),
             bottom=None, shoes="#ff5d8f", accent="#ff5d8f", acc=("bow",)),
        dict(skin="dark", hair="afro", hair_color="#1d1412", eyes="#5a3418", lashes=True, top=("tshirt", "#ffd166", None),
             bottom=("pants", "#ef476f"), shoes="#3a0ca3", accent="#06d6a0", acc=("headphones",)),
        dict(skin="light", hair="bob", hair_color="#e8b04a", eyes="#3a7bd5", lashes=True,
             top=("sweater", "#7b6cf6", None), bottom=("skirt", "#30343f"), shoes="#2b2d42", accent="#ff7eb6", acc=()),
        dict(skin="tan", hair="ponytail", hair_color="#2b1a12", eyes="#2f8f5b", lashes=True,
             top=("tshirt", "#06d6a0", "heart"), bottom=("shorts", "#3a6df0"), shoes="#ffffff", accent="#ff3fa4",
             acc=()),
    ],
    "teen": [
        dict(skin="tan", hair="short", hair_color="#2b2233", eyes="#6b3f1d", top=("hoodie", "#5b4bd6", None),
             bottom=("pants", "#2b3a67"), shoes="#ffffff", accent="#3fe0f0", acc=("headphones",)),
        dict(skin="light", hair="ponytail", hair_color="#c0392b", eyes="#2f8f5b", lashes=True,
             top=("hoodie", "#ff7eb6", None), bottom=("pants", "#30343f"), shoes="#ffffff", accent="#ffd23f",
             acc=("headphones",)),
        dict(skin="brown", hair="curly", hair_color="#1d1412", eyes="#5a3418", top=("hoodie", "#2ec4b6", None),
             bottom=("shorts", "#30343f"), shoes="#ff5d5d", accent="#ffd23f", acc=("headphones",)),
    ],
}

# зверушки и прочие: color, belly, accent, eyes
_CREATURE: dict[str, list[tuple[str, str, str, str]]] = {
    "cat": [("#ffa94d", "#fff1dc", "#ff8fab", "#3fbf5f"), ("#a3acc0", "#f2f4f8", "#ff8fab", "#f2b822"),
            ("#4a4458", "#f6f2ff", "#ff8fab", "#7cdf6b"), ("#ffd9a8", "#fffaf0", "#ff8fab", "#3ec1ff")],
    "dog": [("#d49a5f", "#fff1dc", "#8a5a35", "#6b3f1d"), ("#f3eee4", "#ffffff", "#c8915a", "#4a2a14"),
            ("#5a4e58", "#efe6dc", "#2f2832", "#7a4a20"), ("#f2b25c", "#fff3dc", "#c2803e", "#5a3418")],
    "fox": [("#ff7a2f", "#fff4e6", "#3a2430", "#e0a030"), ("#f2f0f6", "#ffffff", "#9aa5b8", "#3ec1ff")],
    "bunny": [("#f4f1ff", "#ffffff", "#ffadc6", "#e0245e"), ("#c9a27e", "#fff4e6", "#ffadc6", "#5a3418"),
              ("#b8b8cc", "#f4f4fa", "#ffadc6", "#3a6df0")],
    "bear": [("#9a6a45", "#e8c9a0", "#e8c9a0", "#3a2414"), ("#f2f2f2", "#ffffff", "#d8d8e0", "#2a2a3a"),
             ("#d9a05b", "#fbe3bd", "#fbe3bd", "#5a3418")],
    "robot": [("#c9d3e2", "#e8eef6", "#ff9f1c", "#3fe0f0"), ("#ffd23f", "#fff3c4", "#3a6df0", "#7cff6b"),
              ("#ff7eb6", "#ffe0ef", "#5b4bd6", "#3fe0f0")],
    "alien": [("#9be564", "#d9f7c0", "#ff5d8f", "#2a2a2a"), ("#b48cff", "#e9dcff", "#7cff6b", "#2a2a2a"),
              ("#5cc8ff", "#d2f0ff", "#ffd23f", "#2a2a2a")],
    "dragon": [("#5dd39e", "#fff3b0", "#ffd23f", "#ff9f1c"), ("#ff6b6b", "#ffe3a3", "#ffd23f", "#ffd23f"),
               ("#8a6cf6", "#ffd9f0", "#ff7eb6", "#ffd23f")],
    "ghost": [("#eef2ff", "#ffffff", "#b48cff", "#4b3fbf")],
    "monster": [("#ff6fae", "#ffe0ef", "#ffd23f", "#6b3f1d"), ("#7cdf6b", "#e3ffd9", "#ffd23f", "#6b3f1d"),
                ("#5cc8ff", "#e0f5ff", "#ff9f1c", "#6b3f1d"), ("#b06bff", "#f0e0ff", "#7cff6b", "#6b3f1d")],
    "robot3d": [("#f2f4f8", "#ffffff", "#ffb627", "#3fe0f0")],
    "penguin3d": [("#2e3a66", "#ffffff", "#ffb627", "#3a2a4a")],
    "snowman3d": [("#ffffff", "#ffffff", "#ff7a1a", "#2a2233")],
}

_GENERIC_IDS = frozenset(C.BASE_ALIASES) | frozenset(C.BASES)


def _variant(cast: CastSpec, n: int) -> int:
    """Номер варианта дизайна: «канонический» для Стеллы и безымянных (кот, boy…), иначе — по хэшу id."""
    if n <= 1 or cast.base == "stella" or cast.id.lower() in _GENERIC_IDS:
        return 0
    return int(hash01(0, "look", cast.id) * n) % n


def _contrast_fix(c: RGB, against: RGB) -> RGB:
    # волосы почти цвета кожи — чуть темнее, чтобы чёлка читалась
    d = sum(abs(a - b) for a, b in zip(c, against, strict=True))
    return mul(c, 0.8) if d < 0.18 else c


def build_look(cast: CastSpec, seed: int = 0) -> Look:
    """Внешность актёра: всё, что задала модель, плюс готовый дизайн базы для остального.

    seed не меняет внешность (один и тот же актёр выглядит одинаково во всех мультиках); вариант дизайна для
    второго актёра той же базы выбирается по его id."""
    base = cast.base if cast.base in C.BASES else "boy"
    build = BUILDS[base]
    kind = KINDS[base]
    acc = tuple(a for a in cast.accessories if a in C.ACCESSORIES)[: C.MAX_ACCESSORIES]
    size = cast.size if isinstance(cast.size, (int, float)) and cast.size == cast.size else 1.0
    if base in _HUMAN:
        variants = _HUMAN[base]
        v = variants[_variant(cast, len(variants))]
        skin = cast.skin or SKIN_TONES[v["skin"]]
        hair = cast.hair if cast.hair in C.HAIR else v["hair"]
        hair_color = cast.hair_color or hx(v["hair_color"])
        if cast.hair_color is None:
            hair_color = _contrast_fix(hair_color, skin)
        top_style, top_hex, top_print = v["top"]
        top_color = hx(top_hex)
        if cast.top is not None:
            top_style, top_color, top_print = cast.top.style, cast.top.color, cast.top.print
        elif cast.color is not None:
            top_color = cast.color
        if v["bottom"] is not None:
            bottom, bottom_color = v["bottom"][0], hx(v["bottom"][1])
        else:
            bottom, bottom_color = None, mul(top_color, 0.7)
        if cast.bottom is not None:
            bottom, bottom_color = cast.bottom.style, cast.bottom.color
        if top_style == "suit" and cast.bottom is None:
            bottom, bottom_color = "pants", mul(top_color, 0.85)
        if top_style == "dress" and cast.bottom is None:
            bottom = None
        accent = cast.accent or hx(v["accent"])
        if not acc and not cast.accessories:
            acc = tuple(v["acc"])
        return Look(
            base=base, skin=skin, color=top_color, accent=accent, eyes=cast.eyes or hx(v["eyes"]), kind=kind,
            hair=hair, hair_color=hair_color, top=top_style if top_style in C.TOPS else "tshirt", top_color=top_color,
            top_print=top_print, bottom=bottom if bottom in C.BOTTOMS else None, bottom_color=bottom_color,
            shoes=cast.shoes or hx(v["shoes"]), belly=lighten(skin, 0.4), accessories=acc,
            lashes=bool(v.get("lashes", False)), name=cast.name, size=size, build=build,
        )
    variants = _CREATURE[base]
    col_hex, belly_hex, accent_hex, eyes_hex = variants[_variant(cast, len(variants))]
    color = cast.color or hx(col_hex)
    belly = hx(belly_hex)
    if cast.color is not None:
        belly = mix(color, (1.0, 0.98, 0.94), 0.72)
    accent = cast.accent or hx(accent_hex)
    if cast.accent is None and cast.color is not None and base in ("dog", "fox"):
        accent = mul(color, 0.6) if base == "dog" else (0.23, 0.14, 0.19)
    top = cast.top.style if cast.top is not None and kind in ("creature", "alien", "monster") else None
    bottom = cast.bottom.style if cast.bottom is not None and kind in ("creature", "alien") else None
    return Look(
        base=base, skin=color, color=color, accent=accent, eyes=cast.eyes or hx(eyes_hex), kind=kind,
        hair=cast.hair if (cast.hair in C.HAIR and kind == "alien") else "none",
        hair_color=cast.hair_color or mul(color, 0.6),
        top=top, top_color=cast.top.color if cast.top is not None else color,
        top_print=cast.top.print if cast.top is not None else None,
        bottom=bottom, bottom_color=cast.bottom.color if cast.bottom is not None else mul(color, 0.8),
        shoes=cast.shoes or mul(color, 0.92), belly=belly, accessories=acc,
        lashes=base in ("bunny", "fox"), name=cast.name, size=size, build=build,
    )
