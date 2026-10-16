"""Сценарий мультика от модели (JSON) → проверенный Spec.

Разбор снисходительный: синонимы (рус./англ.) и опечатки превращаются в ближайшее допустимое значение
с предупреждением («happyy → happy»), неизвестные ключи игнорируются, числа зажимаются в диапазоны, строки
обрезаются, лишнее сверх лимитов отбрасывается с предупреждением. SpecError — только когда пригодного не осталось:
путь вида shots[0].beats[2].do и список того, что можно.

Модуль лёгкий: работает в процессе бота во время вызова инструмента — без cairo и numpy. Код от модели никогда
не выполняется: всё, что она прислала, — просто данные.
"""

from __future__ import annotations

import difflib
import math
import re
import unicodedata
import zlib
from collections.abc import Callable, Mapping
from typing import Any

from . import catalog as C
from .model import (
    RGB,
    BackgroundSpec,
    BeatSpec,
    CameraSpec,
    CastSpec,
    EffectSpec,
    OutfitPart,
    PlaceSpec,
    PropSpec,
    ShotSpec,
    Spec,
    SpecError,
    TitleSpec,
)
from .palette import SKIN_TONES, parse_color, pick

MAX_WARNINGS = 20  # больше предупреждений модели не показываем — только «…и ещё N»
MAX_SVG_CHARS = 200_000
MAX_BG_TEXT = 60  # надпись на доске/табличке фона
MAX_SIGN_TEXT = 24
MAX_ID_CHARS = 32
_SCAN_DEPTH = 24  # глубже по вложенности сценарий не разглядываем (там всё равно нет нужных ключей)

# ---------- эмодзи → символы DejaVu (как draw.clean_text, но без cairo/fontTools) ----------
_EMOJI_MAP: dict[str, str] = {}
for _chars, _to in (
    ("❤♥❣💖💕💗💓💘💝💞💟🧡💛💚💙💜🖤🤍🤎💌😻", "♥"),
    ("⭐🌟🌠", "★"), ("✨💫", "✦"),
    ("🎵", "♪"), ("🎶🎼", "♫"),
    ("😊🙂😀😃😄😁😆😅😂🤣😉😍🥰😘😗😙😚😋😛😜🤪😝🤗😇🥳😎😺😸", "☺"),
    ("😢😭😞😔🙁😟😕😿🥺😥😓", "☹"),
    ("🌞🌝", "☀"), ("☔🌂", "☂"), ("⛄", "☃"), ("🌸🌼🌺🌷💐🌻", "✿"), ("🍀", "☘"),
    ("✅☑", "✔"), ("❌❎", "✖"), ("👑", "♛"), ("📞📱", "☎"), ("📧📨📩", "✉"),
    ("➡", "→"), ("⬅", "←"), ("⬆", "↑"), ("⬇", "↓"),
):
    for _ch in _chars:
        _EMOJI_MAP[_ch] = _to

# невидимые служебные символы эмодзи и разметки — убираются молча
_SILENT = re.compile("[​-‏⁠-⁤︀-️⃣\U0001f3fb-\U0001f3ff\U000e0000-\U000e007f]")
# что точно есть в DejaVu Sans (латиница, кириллица, греческий, знаки, стрелки, фигуры, ♥★♪☺…)
_GLYPH_RANGES = (
    (0x20, 0x7E), (0xA0, 0x24F), (0x370, 0x3FF), (0x400, 0x52F), (0x2010, 0x205E), (0x20A0, 0x20BF),
    (0x2100, 0x214F), (0x2190, 0x21FF), (0x2200, 0x22FF), (0x2500, 0x25FF), (0x2600, 0x26A1), (0x2700, 0x27BF),
)


def _has_glyph(code: int) -> bool:
    return any(lo <= code <= hi for lo, hi in _GLYPH_RANGES)


def clean_text(s: str, limit: int) -> tuple[str, bool]:
    """Текст для кадра: буквы, цифры, знаки и символы DejaVu (♥★♪☺…) остаются, частые эмодзи заменяются похожими
    символами (❤→♥ ⭐→★ 🎵→♪ 😊→☺), остальное выкидывается. Пробелы схлопываются, переводы строк — не больше
    одного подряд. Длиннее limit — обрезка по слову с «…». Второе значение — True, если что-то выкинули/обрезали."""
    if not isinstance(s, str):
        s = str(s)
    s = unicodedata.normalize("NFC", _SILENT.sub("", s[: max(0, int(limit)) * 8 + 256]))
    out: list[str] = []
    dropped = False
    for ch in s:
        if ch in _EMOJI_MAP:
            out.append(_EMOJI_MAP[ch])
        elif ch == "\n":
            out.append("\n")
        elif ch.isspace() or unicodedata.category(ch) == "Cc":
            out.append(" ")
        elif _has_glyph(ord(ch)):
            out.append(ch)
        else:
            dropped = True
    text = re.sub(r"[ \t]+", " ", "".join(out))
    text = re.sub(r" ?\n[ \n]*", "\n", text).strip()
    limit = max(0, int(limit))
    if len(text) > limit:
        dropped = True
        if limit <= 1:
            return text[:limit], True
        cut = text[: limit - 1]
        space = max(cut.rfind(" "), cut.rfind("\n"))
        if space >= limit * 0.6:
            cut = cut[:space]
        text = cut.rstrip(" ,.;:-\n") + "…"
    return text, dropped


def _plain(s: str, limit: int) -> str:
    """Подпись к ролику (её рисует WhatsApp, не мы): эмодзи можно, управляющие символы — нет."""
    s = "".join(ch for ch in s[: limit * 2 + 16] if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s[:limit].rstrip()


# ---------- словари синонимов (в дополнение к catalog.*_ALIASES) ----------
_FORMAT_ALIASES = {
    "квадрат": "square", "квадратный": "square", "1:1": "square", "горизонтальный": "wide", "широкий": "wide",
    "16:9": "wide", "landscape": "wide", "horizontal": "wide", "вертикальный": "tall", "9:16": "tall",
    "portrait": "tall", "vertical": "tall", "stories": "tall", "сторис": "tall", "reels": "tall",
}
# база → (настоящая база, внешность по умолчанию)
_BASE_EXTRA: dict[str, tuple[str, dict[str, Any]]] = {}
for _names, _base, _extra in (
    (("teacher", "учитель", "училка", "преподаватель"), "teen", {"accessories": ("glasses",)}),
    (("учительница",), "girl", {"accessories": ("glasses",), "hair": "bun"}),
    (("grandpa", "дедушка", "дед", "старик"), "boy", {"accessories": ("glasses", "mustache"), "hair_color": "#e8e4dc"}),
    (("grandma", "бабушка", "бабуля", "старушка"), "girl",
     {"accessories": ("glasses",), "hair": "bun", "hair_color": "#dcdcdc"}),
    (("king", "король", "царь", "принц", "prince"), "boy", {"accessories": ("crown", "cape")}),
    (("queen", "королева", "princess", "принцесса", "царевна"), "girl", {"accessories": ("crown",)}),
    (("wizard", "волшебник", "маг", "колдун"), "boy", {"accessories": ("wizard_hat", "cape")}),
    (("witch", "ведьма", "волшебница", "фея", "fairy"), "girl", {"accessories": ("wizard_hat",)}),
    (("superhero", "супергерой", "герой", "hero"), "boy", {"accessories": ("cape",)}),
    (("мама", "mom", "mother", "женщина", "тётя", "тетя", "сестра", "sister", "подруга"), "girl", {}),
    (("папа", "dad", "father", "мужчина", "дядя", "брат", "brother", "друг", "friend", "человек", "person",
      "human", "ребёнок", "ребенок", "kid", "child", "школьник", "student", "ученик"), "boy", {}),
    (("школьница", "ученица", "студентка"), "girl", {}),
    (("cat", "kitten", "котэ"), "cat", {}),
    (("собачка", "doggy", "псина"), "dog", {}),
    (("зайка", "зая"), "bunny", {}),
    (("медвежонок", "teddy", "мишутка"), "bear", {}),
    (("робот-3d", "робот3d", "3d-робот"), "robot3d", {}),
    (("пингвинёнок", "пингвиненок"), "penguin3d", {}),
    (("змей", "дракоша"), "dragon", {}),
    (("инопланетный", "нло", "ufo", "марсианин"), "alien", {}),
    (("чудище", "чудовище", "monstr"), "monster", {}),
):
    for _n in _names:
        _BASE_EXTRA[_n] = (_base, _extra)

_HAIR_ALIASES = {
    "короткие": "short", "короткая": "short", "короткая стрижка": "short", "ёжик": "spiky", "торчком": "spiky",
    "каре": "bob", "длинные": "long", "длинная": "long", "распущенные": "long", "хвост": "ponytail",
    "хвостик": "ponytail", "коса": "ponytail", "хвостики": "twintails", "два хвостика": "twintails",
    "косички": "twintails", "косы": "twintails", "pigtails": "twintails", "braids": "twintails", "пучок": "bun",
    "гулька": "bun", "афро": "afro", "кудри": "curly", "кудрявые": "curly", "кудрявая": "curly", "лысый": "none",
    "лысая": "none", "без волос": "none", "нет": "none", "buzz": "short", "bald": "none",
}
_TOP_ALIASES = {
    "футболка": "tshirt", "майка": "tshirt", "t-shirt": "tshirt", "tee": "tshirt", "jersey": "tshirt",
    "джерси": "tshirt", "худи": "hoodie", "толстовка": "hoodie", "куртка": "hoodie", "кофта": "sweater",
    "свитер": "sweater", "платье": "dress", "сарафан": "dress", "рубашка": "shirt", "блузка": "shirt",
    "костюм": "suit", "пиджак": "suit", "jacket": "suit",
}
_BOTTOM_ALIASES = {
    "брюки": "pants", "штаны": "pants", "джинсы": "pants", "jeans": "pants", "trousers": "pants",
    "шорты": "shorts", "юбка": "skirt",
}
_PRINT_ALIASES = {
    "звезда": "star", "звёздочка": "star", "звезды": "star", "stars": "star", "сердце": "heart",
    "сердечко": "heart", "hearts": "heart", "полоски": "stripes", "полоска": "stripes", "полосатый": "stripes",
    "stripe": "stripes", "striped": "stripes",
}
_ACC_ALIASES = {
    "очки": "glasses", "солнечные очки": "sunglasses", "тёмные очки": "sunglasses", "черные очки": "sunglasses",
    "кепка": "cap", "бейсболка": "cap", "корона": "crown", "коронка": "crown", "бант": "bow", "бантик": "bow",
    "наушники": "headphones", "заколки": "star_clips", "заколки-звёздочки": "star_clips", "шарф": "scarf",
    "колпак": "party_hat", "праздничный колпак": "party_hat", "birthday hat": "party_hat",
    "шляпа волшебника": "wizard_hat", "колпак волшебника": "wizard_hat", "witch hat": "wizard_hat",
    "усы": "mustache", "moustache": "mustache", "плащ": "cape", "накидка": "cape", "рюкзак": "backpack",
}
_SKIN_ALIASES = {
    "светлая": "light", "светлый": "light", "белая": "light", "white": "light", "бледная": "fair",
    "бледный": "fair", "pale": "fair", "смуглая": "tan", "смуглый": "tan", "загорелая": "tan", "загорелый": "tan",
    "оливковая": "tan", "olive": "tan", "medium": "tan", "коричневая": "brown", "тёмная": "dark", "тёмный": "dark",
    "очень тёмная": "deep", "чёрная": "deep", "black": "deep",
}
_LANE_ALIASES = {
    "сзади": "back", "дальний": "back", "далеко": "back", "background": "back", "середина": "mid", "middle": "mid",
    "center": "mid", "центр": "mid", "спереди": "front", "ближний": "front", "близко": "front", "передний": "front",
    "foreground": "front",
}
_FACING_ALIASES = {
    "влево": "left", "налево": "left", "вправо": "right", "направо": "right", "в камеру": "camera",
    "камера": "camera", "на зрителя": "camera", "зритель": "camera", "front": "camera", "viewer": "camera",
    "forward": "camera",
}
_TIME_ALIASES = {
    "день": "day", "утро": "day", "morning": "day", "noon": "day", "закат": "sunset", "рассвет": "sunset",
    "sunrise": "sunset", "dusk": "sunset", "вечер": "evening", "сумерки": "evening", "ночь": "night",
    "midnight": "night",
}
_WEATHER_ALIASES = {
    "ясно": "clear", "солнечно": "clear", "sunny": "clear", "снег": "snow", "снегопад": "snow", "snowy": "snow",
    "дождь": "rain", "ливень": "rain", "rainy": "rain", "storm": "rain", "гроза": "rain",
}
_BG_ALIASES = {
    "кухня": "room", "спальня": "room", "квартира": "room", "офис": "room", "house": "room", "bedroom": "room",
    "kitchen": "room", "урок": "classroom", "сад": "park", "поле": "park", "луг": "park", "meadow": "park",
    "garden": "park", "town": "city", "джунгли": "forest", "jungle": "forest", "горы": "forest",
    "mountains": "forest", "океан": "beach", "дно": "underwater", "аквариум": "underwater", "облака": "sky",
    "clouds": "sky", "дискотека": "party", "диско": "party", "disco": "party", "club": "party", "клуб": "party",
    "театр": "stage", "theater": "stage", "theatre": "stage", "шоу": "stage", "show": "stage",
    "новый год": "winter", "рождество": "winter", "christmas": "winter", "каток": "winter", "планета": "space",
    "луна": "space", "moon": "space", "галактика": "space", "galaxy": "space",
}
_PROP_EXTRA = {
    "text": "text3d", "title": "text3d", "word": "text3d", "letters": "text3d", "буквы": "text3d",
    "3d текст": "text3d", "3d надпись": "text3d", "board": "sign", "доска": "sign", "плакат": "sign",
    "poster": "sign", "ёлочка": "christmas_tree", "новогодняя ёлка": "christmas_tree", "кекс": "cake",
    "cupcake": "cake", "пирог": "cake", "мячик": "ball", "автомобиль": "car", "домик": "house", "кресло": "chair",
    "диско шар": "disco_ball", "дискотечный шар": "disco_ball", "mirror ball": "disco_ball", "звёздочка": "star",
    "монетка": "coin", "медаль": "coin", "игральная кость": "dice", "кубики": "dice", "подарочек": "gift",
    "коробка": "gift", "колонна": "cylinder", "пирамида": "cone", "кольцо": "torus", "ring": "torus",
    "сердечко": "heart", "сокровище": "gem", "рисунок": "svg", "картинка": "svg", "image": "svg",
}
_MATERIAL_ALIASES = {
    "пластик": "plastic", "пластиковый": "plastic", "мульт": "toon", "мультяшный": "toon", "cartoon": "toon",
    "карамель": "candy", "конфета": "candy", "леденец": "candy", "глянец": "candy", "пластилин": "clay",
    "глина": "clay", "хром": "chrome", "металл": "chrome", "серебро": "chrome", "silver": "chrome",
    "metal": "chrome", "золото": "gold", "золотой": "gold", "стекло": "glass", "стеклянный": "glass",
    "кристалл": "gem", "драгоценный": "gem", "алмаз": "gem", "gold3d": "gold", "chrome3d": "chrome",
    "candy3d": "candy", "neon": "toon", "comic": "toon", "plain": "plastic",
}
_PROP_ANIM_ALIASES = {
    "вращение": "spin", "вращается": "spin", "крутится": "spin", "rotate": "spin", "rotating": "spin",
    "парит": "float", "плавает": "float", "летает": "float", "hover": "float", "прыгает": "bounce",
    "скачет": "bounce", "пульсирует": "pulse", "пульс": "pulse", "beat": "pulse", "качается": "swing",
    "раскачивается": "swing", "покачивается": "wobble", "дрожит": "wobble", "шатается": "wobble", "нет": "none",
    "static": "none", "статично": "none",
}
_AMOUNT_ALIASES = {
    "мало": "few", "немного": "few", "чуть": "few", "little": "few", "some": "few", "обычно": "normal",
    "средне": "normal", "medium": "normal", "много": "lots", "очень много": "lots", "lot": "lots",
    "many": "lots", "much": "lots", "max": "lots", "куча": "lots",
}
_TITLE_STYLE_ALIASES = {
    "золото": "gold3d", "золотой": "gold3d", "gold": "gold3d", "хром": "chrome3d", "chrome": "chrome3d",
    "серебро": "chrome3d", "silver": "chrome3d", "карамель": "candy3d", "candy": "candy3d",
    "конфетный": "candy3d", "неон": "neon", "комикс": "comic", "простой": "plain", "обычный": "plain",
    "3d": "gold3d",
}
_TITLE_ANIM_ALIASES = {
    "падает": "drop", "падение": "drop", "fall": "drop", "вращение": "spin", "крутится": "spin",
    "появление": "pop", "выскакивает": "pop", "bounce": "pop", "волна": "wave", "печать": "type",
    "печатается": "type", "typewriter": "type", "typing": "type",
}
_POSITION_ALIASES = {
    "верх": "top", "сверху": "top", "вверху": "top", "центр": "center", "середина": "center", "middle": "center",
    "низ": "bottom", "снизу": "bottom", "внизу": "bottom",
}
_CAMERA_MOVE_ALIASES = {
    "статично": "static", "неподвижно": "static", "none": "static", "наезд": "zoom_in", "приближение": "zoom_in",
    "zoom": "zoom_in", "push in": "zoom_in", "отъезд": "zoom_out", "отдаление": "zoom_out", "pull out": "zoom_out",
    "панорама влево": "pan_left", "панорама вправо": "pan_right", "pan": "pan_right", "следить": "follow",
    "track": "follow", "облёт": "orbit", "вокруг": "orbit",
}
_CAMERA_BEAT_ALIASES = {
    "тряска": "shake", "трясти": "shake", "дрожь": "shake", "наезд": "zoom_in", "приближение": "zoom_in",
    "zoom": "zoom_in", "отъезд": "zoom_out", "удар": "punch", "punch in": "punch", "рывок": "punch",
    "фокус": "focus", "сброс": "reset", "назад": "reset", "static": "reset", "normal": "reset",
}
_TRANSITION_ALIASES = {
    "склейка": "cut", "резко": "cut", "none": "cut", "затемнение": "fade", "fade black": "fade",
    "наплыв": "crossfade", "растворение": "crossfade", "dissolve": "crossfade", "шторка": "wipe", "круг": "iris",
    "диафрагма": "iris", "circle": "iris", "зум": "zoom", "сдвиг": "slide", "push": "slide", "вспышка": "flash",
    "white": "flash",
}
_MARK_ALIASES = {
    "сердечки": "hearts", "сердце": "hearts", "heart": "hearts", "любовь": "hearts", "пот": "sweat",
    "капля": "sweat", "капелька": "sweat", "злость": "anger", "гнев": "anger", "angry": "anger",
    "искры": "sparkles", "блёстки": "sparkles", "звёздочки": "sparkles", "sparkle": "sparkles",
    "вопрос": "question", "?": "question", "??": "question", "восклицание": "exclaim", "!": "exclaim",
    "!!": "exclaim", "exclamation": "exclaim", "сон": "zzz", "z": "zzz", "zz": "zzz", "sleep": "zzz",
    "идея": "idea", "лампочка": "idea", "ноты": "music", "музыка": "music", "note": "music", "notes": "music",
    "♪": "music", "головокружение": "dizzy", "пар": "steam", "шок": "shock", "слёзы": "tears", "tear": "tears",
    "cry": "tears",
}
_EMOTION_EXTRA = {
    "грустит": "sad", "злится": "angry", "сердится": "angry", "сердитый": "angry", "испуган": "scared",
    "испугана": "scared", "удивлена": "surprised", "счастлив": "happy", "счастливый": "happy", "счастье": "happy",
    "радостный": "happy", "радуется": "excited", "в восторге": "excited", "влюблена": "love",
    "смущена": "embarrassed", "стыд": "embarrassed", "гордится": "proud", "задумчивый": "thinking",
    "устал": "sleepy", "усталый": "sleepy", "tired": "sleepy", "shy": "embarrassed", "confused": "thinking",
    "cool": "smug", "крутой": "smug", "хитрая": "smug", "ржёт": "laugh", "хохочет": "laugh", "upset": "sad",
    "crying": "cry", "furious": "angry", "nervous": "scared", "calm": "neutral", "спокойный": "neutral",
    "normal": "neutral", "обычный": "neutral",
}
_ACTION_EXTRA = {
    "enter": "walk_in", "come in": "walk_in", "exit": "walk_out", "leave": "walk_out", "go": "walk",
    "move": "walk", "speak": "talk", "say": "talk", "sing": "talk", "поёт": "talk", "кричит": "talk",
    "applaud": "clap", "greet": "wave", "hello": "wave", "flip": "spin", "twirl": "spin", "rotate": "spin",
    "teleport": "appear", "hide": "poof", "sitting": "sit", "sleeping": "sleep", "thinking": "think",
    "crying": "cry", "laughing": "laugh", "highfive": "high_five", "high5": "high_five", "дать пять": "high_five",
    "обнять": "hug", "обнимаются": "hug", "танцевать": "dance", "прыгать": "jump", "бежать": "run",
    "лететь": "fly", "взлетает": "fly", "кружится": "spin",
}
_EFFECT_EXTRA = {
    "снегопад": "snow", "ливень": "rain", "искорки": "sparkles", "блестки": "sparkles", "сердца": "hearts",
    "сердце": "hearts", "heart": "hearts", "star": "stars", "sparkle": "sparkles", "firework": "fireworks",
    "салюты": "fireworks", "balloon": "balloons", "шары": "balloons", "bubble": "bubbles",
    "мыльные пузыри": "bubbles", "leaf": "leaves", "листопад": "leaves", "coin": "coins", "деньги": "coins",
    "money": "coins", "notes": "music", "музыка": "music", "дымок": "smoke", "пламя": "fire", "облачко": "poof",
    "пуф": "poof", "хлопок": "poof", "glitter": "sparkles", "magic": "sparkles", "магия": "sparkles",
    "волшебство": "sparkles",
}
_DANCE_ALIASES = {
    "прыжки": "bounce", "прыгает": "bounce", "качается": "sway", "покачивание": "sway", "робот": "robot",
    "диско": "disco", "кружится": "spin", "кружение": "spin", "вертится": "spin", "извивается": "wiggle",
    "виляет": "wiggle", "twist": "wiggle", "синхронно": "sync", "флешмоб": "sync", "together": "sync",
}
_SIDE_ALIASES = {
    "слева": "left", "левый": "left", "влево": "left", "l": "left", "справа": "right", "правый": "right",
    "вправо": "right", "r": "right",
}
_TO_WORDS = {
    "left": "left", "влево": "left", "налево": "left", "слева": "left", "right": "right", "вправо": "right",
    "направо": "right", "справа": "right", "center": "center", "centre": "center", "middle": "center",
    "центр": "center", "в центр": "center", "середина": "center", "offscreen": "offscreen", "off": "offscreen",
    "away": "offscreen", "out": "offscreen", "за кадр": "offscreen", "прочь": "offscreen", "exit": "offscreen",
}
_LOOK_WORDS = {
    "camera": "camera", "viewer": "camera", "audience": "camera", "зритель": "camera", "в камеру": "camera",
    "камера": "camera", "на нас": "camera", "left": "left", "влево": "left", "налево": "left", "right": "right",
    "вправо": "right", "направо": "right",
}
_ALL_WORDS = {"all", "все", "всё", "everyone", "everybody", "все вместе", "вместе", "*", "каждый", "each"}
_LINE_KEYS = (("say", "say"), ("shout", "shout"), ("think", "think"), ("whisper", "whisper"),
              ("line", None), ("text", None), ("говорит", "say"), ("кричит", "shout"), ("думает", "think"))
_LINE_KIND_ALIASES = {"говорит": "say", "кричит": "shout", "думает": "think", "шепчет": "whisper",
                      "speak": "say", "yell": "shout", "thought": "think"}

# 2D-предметы, которые стоят на земле (у остальных по умолчанию место в воздухе)
_GROUND_PROPS = {
    "table", "chair", "sign", "tree", "bush", "flower", "ball", "book", "phone", "pizza", "ice_cream", "cup",
    "guitar", "microphone", "umbrella", "car", "house", "cake", "gift", "trophy", "christmas_tree", "dice",
    "cube", "cylinder", "cone",
}
_PROP_SLOTS = (0.5, 0.2, 0.8, 0.35, 0.65, 0.1, 0.9, 0.5)
_BOTTOM_DEFAULT: dict[str, RGB] = {"pants": (0.23, 0.33, 0.55), "shorts": (0.25, 0.42, 0.75)}
_NUMBER_RE = re.compile(r"^(?:number|номер|no|№|#)?\s*[:.]?\s*(\d{1,2})$")


# ---------- общие помощники ----------
def _key(s: str) -> str:
    s = unicodedata.normalize("NFC", s).lower().replace("ё", "е").strip()
    s = re.sub(r"[\s\-]+", "_", s)
    return s.strip("_.,;:\"'«»`()[]{}")


class _Vocab:
    """Допустимые значения + синонимы: точное совпадение, синоним, потом опечатка (difflib, cutoff 0.6)."""

    def __init__(self, allowed: tuple[str, ...] | list[str], *alias_maps: Mapping[str, str]):
        self.allowed = tuple(allowed)
        ok = set(self.allowed)
        self.map: dict[str, str] = {}
        for value in self.allowed:
            self.map.setdefault(_key(value), value)
        for aliases in alias_maps:
            for word, value in aliases.items():
                if value in ok:
                    self.map.setdefault(_key(word), value)
        self.keys = list(self.map)

    def find(self, text: str) -> tuple[str | None, bool]:
        """(значение или None, найдено ли по опечатке)."""
        k = _key(text[:64])
        if not k or len(k) > 48:
            return None, False
        if k in self.map:
            return self.map[k], False
        close = difflib.get_close_matches(k, self.keys, n=1, cutoff=0.6)
        if close:
            return self.map[close[0]], True
        return None, False


_V_FORMAT = _Vocab(tuple(C.FORMATS), _FORMAT_ALIASES)
_V_BASE = _Vocab(C.BASES, C.BASE_ALIASES)
_V_HAIR = _Vocab(C.HAIR, _HAIR_ALIASES)
_V_TOP = _Vocab(C.TOPS, _TOP_ALIASES)
_V_BOTTOM = _Vocab(C.BOTTOMS, _BOTTOM_ALIASES)
_V_PRINT = _Vocab(C.PRINTS, _PRINT_ALIASES)
_V_ACC = _Vocab(C.ACCESSORIES, _ACC_ALIASES)
_V_SKIN = _Vocab(C.SKINS, _SKIN_ALIASES)
_V_LANE = _Vocab(C.LANES, _LANE_ALIASES)
_V_FACING = _Vocab(C.FACINGS, _FACING_ALIASES)
_V_TIME = _Vocab(C.TIMES, _TIME_ALIASES)
_V_WEATHER = _Vocab(C.WEATHER, _WEATHER_ALIASES)
_V_BG = _Vocab(C.BACKGROUNDS, C.BACKGROUND_ALIASES, _BG_ALIASES)
_V_PROP = _Vocab(C.PROPS, C.PROP_ALIASES, _PROP_EXTRA)
_V_MATERIAL = _Vocab(C.MATERIALS, _MATERIAL_ALIASES)
_V_PROP_ANIM = _Vocab(C.PROP_ANIMS, _PROP_ANIM_ALIASES)
_V_EFFECT = _Vocab(C.EFFECTS, C.EFFECT_ALIASES, _EFFECT_EXTRA)
_V_AMOUNT = _Vocab(C.AMOUNTS, _AMOUNT_ALIASES)
_V_TITLE_STYLE = _Vocab(C.TITLE_STYLES, _TITLE_STYLE_ALIASES)
_V_TITLE_ANIM = _Vocab(C.TITLE_ANIMS, _TITLE_ANIM_ALIASES)
_V_POSITION = _Vocab(C.TITLE_POSITIONS, _POSITION_ALIASES)
_V_CAM_MOVE = _Vocab(C.CAMERA_MOVES, _CAMERA_MOVE_ALIASES)
_V_CAM_BEAT = _Vocab(C.CAMERA_BEATS, _CAMERA_BEAT_ALIASES)
_V_CAM_ANY = _Vocab(tuple(dict.fromkeys(C.CAMERA_BEATS + C.CAMERA_MOVES)), _CAMERA_BEAT_ALIASES, _CAMERA_MOVE_ALIASES)
_V_TRANSITION = _Vocab(C.TRANSITIONS, _TRANSITION_ALIASES)
_V_EMOTION = _Vocab(C.EMOTIONS, C.EMOTION_ALIASES, _EMOTION_EXTRA)
_V_MARK = _Vocab(C.MARKS, _MARK_ALIASES)
_V_ACTION = _Vocab(C.ACTIONS, C.ACTION_ALIASES, _ACTION_EXTRA)
_V_DANCE = _Vocab(C.DANCE_STYLES + ("sync",), _DANCE_ALIASES)
_V_SIDE = _Vocab(("left", "right"), _SIDE_ALIASES)
_V_LINE_KIND = _Vocab(C.LINE_KINDS, _LINE_KIND_ALIASES)


def _safe_str(value: Any) -> str:
    """str() без исключений (огромные int, странные объекты)."""
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 10**18:
        return "<int>"
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        return f"<{type(value).__name__}>"


def _short(value: Any) -> str:
    if isinstance(value, str):
        s = value
    elif isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 10**18:
        s = "<int>"
    else:
        try:
            s = repr(value)
        except Exception:  # noqa: BLE001
            s = f"<{type(value).__name__}>"
    s = s.replace("\n", " ")
    return s if len(s) <= 30 else s[:29] + "…"


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_str(value: Any) -> str | None:
    """Строка из строки или числа; всё остальное — None."""
    if isinstance(value, str):
        return value
    if _is_num(value):
        return _fmt_num(value)
    return None


def _fmt_num(value: int | float) -> str:
    if isinstance(value, int):
        return str(value) if abs(value) < 10**18 else "0"
    return repr(value) if math.isfinite(value) else "0"


def _canon(obj: Any, out: list[str], depth: int, limit: int) -> int:
    """Детерминированная запись сценария (для seed) и её примерный размер в байтах JSON.
    SVG-реквизит не считается (только его контрольная сумма). Глубже _SCAN_DEPTH не спускаемся."""
    size = 0
    stack: list[tuple[Any, int, bool]] = [(obj, depth, False)]
    while stack:
        cur, d, is_svg = stack.pop()
        if d > _SCAN_DEPTH:
            out.append("…")
            size += 1
            continue
        if isinstance(cur, Mapping):
            out.append("{")
            size += 2
            items = sorted(((_safe_str(k)[:200], v) for k, v in cur.items()), key=lambda kv: kv[0])
            for ks, v in reversed(items):
                stack.append((v, d + 1, ks == "svg"))
                stack.append((ks, d + 1, False))
            continue
        if isinstance(cur, (list, tuple)):
            out.append("[")
            size += 2
            for v in reversed(cur):
                stack.append((v, d + 1, False))
            continue
        if isinstance(cur, str):
            if is_svg:
                out.append(f"svg:{zlib.crc32(cur.encode('utf-8', 'replace')):08x}")
                size += 10
            else:
                out.append(cur)
                size += len(cur.encode("utf-8", "replace")) + 3
        elif cur is None or isinstance(cur, bool):
            out.append(repr(cur))
            size += 5
        elif _is_num(cur):
            out.append(_fmt_num(cur))
            size += 8
        else:
            out.append(type(cur).__name__)
            size += 8
        if size > limit:
            return size
    return size


# ---------- разбор ----------
class _Parser:
    def __init__(self, raw: Mapping[str, Any], max_seconds: float, svg_renderer: Callable[[str], bytes] | None):
        self.raw = raw
        self.max_seconds = max_seconds
        self.svg_renderer = svg_renderer
        self.warnings: list[str] = []
        self.cast: dict[str, CastSpec] = {}
        self.cast_order = 0
        self.seed = 0
        self.svg_used = 0
        self.beats_total = 0

    # --- предупреждения ---
    def warn(self, text: str) -> None:
        text = text if len(text) <= 200 else text[:199] + "…"
        if text not in self.warnings:
            self.warnings.append(text)

    # --- примитивы ---
    def num(self, value: Any, lo: float, hi: float, default: float | None, path: str) -> float | None:
        if value is None:
            return default
        if isinstance(value, str):
            s = value.strip().replace(",", ".")
            pct = s.endswith("%")
            try:
                value = float(s.rstrip("%")) / (100.0 if pct else 1.0)
            except ValueError:
                self.warn(f"{path}: «{_short(s)}» — не число, оставила по умолчанию")
                return default
        if not _is_num(value):
            self.warn(f"{path}: нужно число, а не {type(value).__name__}")
            return default
        try:
            x = float(value)
        except OverflowError:
            x = math.inf if value > 0 else -math.inf
        if not math.isfinite(x):
            self.warn(f"{path}: число должно быть конечным")
            return default
        if x < lo or x > hi:
            clamped = min(hi, max(lo, x))
            if abs(clamped - x) > 0.05 * (hi - lo):
                self.warn(f"{path}: {_fmt_num(value)} вне {_fmt_num(lo)}..{_fmt_num(hi)} — взяла {clamped:g}")
            x = clamped
        return x

    def enum(self, value: Any, vocab: _Vocab, path: str, default: str | None = None, *,
             required: bool = False) -> str | None:
        if value is None:
            if required:
                raise SpecError(path, "нужно значение", vocab.allowed)
            return default
        text = _as_str(value)
        if text is None:
            if required:
                raise SpecError(path, f"нужна строка, а не {type(value).__name__}", vocab.allowed)
            self.warn(f"{path}: нужна строка — оставила {default}" if default else f"{path}: нужна строка — пропустила")
            return default
        if not text.strip():
            return default
        found, fuzzy = vocab.find(text)
        if found is None:
            if required:
                raise SpecError(path, f"«{_short(text)}» нет", vocab.allowed)
            if text.strip():
                self.warn(f"{path}: «{_short(text)}» нет — "
                          + (f"взяла {default}" if default else "пропустила")
                          + ". Можно: " + ", ".join(vocab.allowed[:16]))
            return default
        if fuzzy:
            self.warn(f"{path}: «{_short(text)}» → {found}")
        return found

    def text(self, value: Any, limit: int, path: str, what: str = "текст") -> str:
        if value is None:
            return ""
        s = _as_str(value)
        if s is None:
            self.warn(f"{path}: {what} должен быть строкой")
            return ""
        out, dropped = clean_text(s, limit)
        if dropped:
            raw_len = len(s.strip())
            if raw_len > limit:
                self.warn(f"{path}: {what} — сократила до {limit} знаков")
            elif out != s.strip():
                self.warn(f"{path}: эмодзи и редкие символы в тексте не рисуются (можно ♥ ★ ♪ ☺)")
        return out

    def color(self, value: Any, path: str) -> RGB | None:
        if value is None:
            return None
        got = parse_color(value)
        if got is None:
            self.warn(f"{path}: «{_short(value)}» — не цвет (нужно #RRGGBB или название), оставила по умолчанию")
        return got

    # --- актёры ---
    def norm_id(self, value: Any) -> str | None:
        s = _as_str(value)
        if s is None:
            return None
        s = re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().lower()[:MAX_ID_CHARS]
        return s or None

    def base_of(self, word: str) -> tuple[str, dict[str, Any]] | None:
        """База по слову: «кот» → cat, «barsik_cat» → cat, «учитель» → teen (+очки)."""
        k = _key(word)
        if not k:
            return None
        for cand in (k, k.replace("_", " ")):
            if cand in _BASE_EXTRA:
                return _BASE_EXTRA[cand]
            if cand in _V_BASE.map:
                return _V_BASE.map[cand], {}
        for token in re.split(r"[_\d]+", k):
            if len(token) < 2:
                continue
            if token in _BASE_EXTRA:
                return _BASE_EXTRA[token]
            if token in _V_BASE.map:
                return _V_BASE.map[token], {}
        close = difflib.get_close_matches(k, _V_BASE.keys, n=1, cutoff=0.8)
        if close:
            return _V_BASE.map[close[0]], {}
        return None

    def actor(self, value: Any, path: str, *, create: bool) -> str | None:
        """id актёра из cast (по id, имени, опечатке); если нет — создать по базе из id (create=True).
        None — если нельзя и create=False; SpecError — если нельзя и create=True."""
        aid = self.norm_id(value)
        if aid is None:
            if create:
                raise SpecError(path, "нужен id актёра (строка)", tuple(self.cast))
            return None
        if aid in self.cast:
            return aid
        k = _key(aid)
        for cid, cs in self.cast.items():
            if _key(cid) == k or (cs.name and _key(cs.name) == k):
                return cid
        close = difflib.get_close_matches(aid, list(self.cast), n=1, cutoff=0.8)
        if close:
            self.warn(f"{path}: «{_short(value)}» → {close[0]}")
            return close[0]
        # «кот», когда в cast есть ровно один кот, — это он
        found = self.base_of(aid)
        if found is not None:
            same = [cid for cid, cs in self.cast.items() if cs.base == found[0]]
            if len(same) == 1 and aid in C.BASES + tuple(C.BASE_ALIASES):
                return same[0]
        if not create:
            self.warn(f"{path}: актёра «{_short(value)}» нет — пропустила")
            return None
        if found is None:
            raise SpecError(path, f"актёра «{_short(value)}» нет в cast — опиши его в cast (base) или возьми из "
                                  "имеющихся", tuple(self.cast) + C.BASES)
        self.add_cast(aid, {"base": found[0]}, f"{path}", auto=True)
        self.warn(f"{path}: актёра «{_short(value)}» не было в cast — добавила ({self.cast[aid].base})")
        return aid

    def add_cast(self, aid: str, raw: Any, path: str, auto: bool = False) -> None:
        if len(self.cast) >= C.MAX_CAST:
            raise SpecError(path, f"актёров больше {C.MAX_CAST} — оставь до {C.MAX_CAST}", tuple(self.cast))
        self.cast[aid] = self.cast_spec(aid, raw, path, len(self.cast))

    def cast_spec(self, aid: str, raw: Any, path: str, idx: int) -> CastSpec:
        if isinstance(raw, str):
            raw = {"base": raw}
        if not isinstance(raw, Mapping):
            self.warn(f"{path}: описание актёра должно быть объектом — взяла по id")
            raw = {}
        base_raw = raw.get("base", raw.get("kind", raw.get("type")))
        extra: dict[str, Any] = {}
        base: str | None = None
        if base_raw is not None:
            text = _as_str(base_raw)
            found = self.base_of(text) if text else None
            if found is not None:
                base, extra = found
            else:
                base = self.enum(base_raw, _V_BASE, f"{path}.base", required=True)
        if base is None:
            for word in (aid, _as_str(raw.get("name")) or ""):
                found = self.base_of(word) if word else None
                if found is not None:
                    base, extra = found
                    break
        if base is None:
            base = ("girl", "boy")[idx % 2]
            self.warn(f"{path}.base: не указана — взяла {base}")
        name = self.text(raw.get("name"), C.MAX_NAME_CHARS, f"{path}.name", "имя")
        skin = self.skin(raw.get("skin"), f"{path}.skin")
        hair = self.enum(raw.get("hair"), _V_HAIR, f"{path}.hair") if raw.get("hair") is not None else extra.get("hair")
        hair_color = self.color(raw.get("hair_color"), f"{path}.hair_color")
        if hair_color is None and "hair_color" in extra:
            hair_color = parse_color(extra["hair_color"])
        accessories = self.accessories(raw.get("accessories"), f"{path}.accessories")
        if not accessories and raw.get("accessories") is None:
            accessories = tuple(extra.get("accessories", ()))
        size = self.num(raw.get("size"), 0.6, 1.4, 1.0, f"{path}.size")
        return CastSpec(
            id=aid, base=base, name=name, skin=skin, hair=hair, hair_color=hair_color,
            eyes=self.color(raw.get("eyes"), f"{path}.eyes"),
            top=self.outfit(raw.get("top"), _V_TOP, f"{path}.top", idx, top=True),
            bottom=self.outfit(raw.get("bottom"), _V_BOTTOM, f"{path}.bottom", idx, top=False),
            shoes=self.color(raw.get("shoes"), f"{path}.shoes"),
            color=self.color(raw.get("color"), f"{path}.color"),
            accent=self.color(raw.get("accent"), f"{path}.accent"),
            accessories=accessories, size=size if size is not None else 1.0,
        )

    def skin(self, value: Any, path: str) -> RGB | None:
        if value is None:
            return None
        text = _as_str(value)
        if text is not None:
            found, fuzzy = _V_SKIN.find(text)
            if found is not None:
                if fuzzy:
                    self.warn(f"{path}: «{_short(text)}» → {found}")
                return SKIN_TONES[found]
        return self.color(value, path)

    def accessories(self, value: Any, path: str) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            items: list[Any] = [p for p in re.split(r"[,;/]| и ", value) if p.strip()]
        elif isinstance(value, (list, tuple)):
            items = list(value[:12])
        else:
            self.warn(f"{path}: нужен список")
            return ()
        out: list[str] = []
        for i, item in enumerate(items):
            got = self.enum(item, _V_ACC, f"{path}[{i}]")
            if got and got not in out:
                out.append(got)
        if len(out) > C.MAX_ACCESSORIES:
            self.warn(f"{path}: не больше {C.MAX_ACCESSORIES} аксессуаров — оставила {', '.join(out[:3])}")
            out = out[: C.MAX_ACCESSORIES]
        return tuple(out)

    def outfit(self, value: Any, vocab: _Vocab, path: str, idx: int, *, top: bool) -> OutfitPart | None:
        if value is None:
            return None
        if isinstance(value, str):
            style, fuzzy = vocab.find(value)
            if style is not None and not fuzzy:
                value = {"style": style}
            else:
                color = parse_color(value)
                if color is None:
                    self.warn(f"{path}: «{_short(value)}» не поняла — нужно {{style, color}}")
                    return None
                value = {"color": value}
        if not isinstance(value, Mapping):
            self.warn(f"{path}: нужно {{style, color}}")
            return None
        default_style = "tshirt" if top else "pants"
        style = self.enum(value.get("style"), vocab, f"{path}.style", default_style) or default_style
        color = self.color(value.get("color"), f"{path}.color")
        if color is None:
            color = pick(self.seed, idx) if top else _BOTTOM_DEFAULT.get(style, pick(self.seed, idx + 7))
        prt = self.print_(value.get("print"), f"{path}.print") if top else None
        return OutfitPart(style=style, color=color, print=prt)

    def print_(self, value: Any, path: str) -> str | None:
        if value is None:
            return None
        if _is_num(value):
            value = _fmt_num(value)
        if not isinstance(value, str):
            self.warn(f"{path}: нужна строка")
            return None
        s = value.strip()
        low = s.lower()
        m = _NUMBER_RE.match(low)
        if m:
            return f"number:{int(m.group(1))}"
        if low.startswith("text:") or low.startswith("текст:"):
            txt, _ = clean_text(s.split(":", 1)[1], 6)
            return f"text:{txt}" if txt else None
        found, fuzzy = _V_PRINT.find(s)
        if found is not None:
            if fuzzy:
                self.warn(f"{path}: «{_short(s)}» → {found}")
            return found
        txt, _ = clean_text(s, 6)
        if txt and len(s) <= 6:
            return f"text:{txt}"
        self.warn(f"{path}: «{_short(s)}» нет. Можно: star, heart, stripes, number:7, text:МАША (до 6 знаков)")
        return None

    # --- сцена ---
    def background(self, value: Any, path: str) -> BackgroundSpec:
        if value is None:
            return BackgroundSpec()
        if isinstance(value, str):
            value = {"preset": value}
        if not isinstance(value, Mapping):
            self.warn(f"{path}: нужно {{preset, time}}")
            return BackgroundSpec()
        return BackgroundSpec(
            preset=self.enum(value.get("preset", value.get("kind")), _V_BG, f"{path}.preset", "park") or "park",
            time=self.enum(value.get("time"), _V_TIME, f"{path}.time", "day") or "day",
            weather=self.enum(value.get("weather"), _V_WEATHER, f"{path}.weather", "clear") or "clear",
            text=self.text(value.get("text"), MAX_BG_TEXT, f"{path}.text", "надпись"),
            accent=self.color(value.get("accent"), f"{path}.accent"),
        )

    def camera(self, value: Any, path: str) -> tuple[str, Any, float]:
        if value is None:
            return "static", None, 0.5
        if isinstance(value, str):
            value = {"move": value}
        if not isinstance(value, Mapping):
            self.warn(f"{path}: нужно {{move, focus, amount}}")
            return "static", None, 0.5
        move = self.enum(value.get("move", value.get("kind")), _V_CAM_MOVE, f"{path}.move", "static") or "static"
        amount = self.num(value.get("amount"), 0.0, 1.0, 0.5, f"{path}.amount")
        return move, value.get("focus"), 0.5 if amount is None else amount

    def place_entry(self, value: Any, path: str) -> PlaceSpec:
        if _is_num(value):
            value = {"x": value}
        elif isinstance(value, str):
            lane, _ = _V_LANE.find(value)
            value = {"lane": lane} if lane else {"x": value}
        if not isinstance(value, Mapping):
            self.warn(f"{path}: нужно {{x, lane, facing}}")
            return PlaceSpec()
        x = self.num(value.get("x"), 0.0, 1.0, None, f"{path}.x")
        lane = self.enum(value.get("lane"), _V_LANE, f"{path}.lane", "mid") or "mid"
        facing = self.enum(value.get("facing", value.get("face")), _V_FACING, f"{path}.facing")
        return PlaceSpec(x=x, lane=lane, facing=facing)

    def prop(self, value: Any, path: str, n: int) -> PropSpec | None:
        if isinstance(value, str):
            value = {"kind": value}
        if not isinstance(value, Mapping):
            self.warn(f"{path}: предмет должен быть объектом — пропустила")
            return None
        kind_raw = value.get("kind", value.get("type"))
        if kind_raw is None:
            kind_raw = "svg" if value.get("svg") is not None else "text3d" if value.get("text") is not None else None
        if kind_raw is None:
            self.warn(f"{path}: нет kind — пропустила. Можно: " + ", ".join(C.PROPS[:20]))
            return None
        kind = self.enum(kind_raw, _V_PROP, f"{path}.kind")
        if kind is None:
            return None
        pid = self.norm_id(value.get("id")) or f"{kind}{n}"
        size = self.num(value.get("size"), 0.03, 0.8, 0.25 if kind == "svg" else 0.2, f"{path}.size") or 0.2
        x = self.num(value.get("x"), 0.0, 1.0, None, f"{path}.x")
        if x is None:
            x = _PROP_SLOTS[n % len(_PROP_SLOTS)]
        y_default = (0.9 - size / 2) if kind in _GROUND_PROPS else 0.18 if kind == "disco_ball" else 0.3
        y = self.num(value.get("y"), 0.0, 1.0, y_default, f"{path}.y")
        mat_raw = value.get("material")
        if mat_raw is None and value.get("style") is not None and kind in C.PROPS_3D:
            mat_raw = value.get("style")
        material = self.enum(mat_raw, _V_MATERIAL, f"{path}.material") if kind in C.PROPS_3D else None
        anim = self.enum(value.get("anim"), _V_PROP_ANIM, f"{path}.anim", "none") or "none"
        lane = self.enum(value.get("lane"), _V_LANE, f"{path}.lane", "mid") or "mid"
        limit = C.MAX_TEXT3D_CHARS if kind == "text3d" else MAX_SIGN_TEXT if kind == "sign" else 12
        text = self.text(value.get("text"), limit, f"{path}.text", "надпись")
        if kind == "text3d" and not text:
            self.warn(f"{path}: у text3d нет text — пропустила")
            return None
        svg_png: bytes | None = None
        if kind == "svg":
            svg_png = self.svg(value.get("svg"), path)
            if svg_png is None:
                return None
        return PropSpec(id=pid, kind=kind, x=x, y=y if y is not None else y_default, size=size,
                        color=self.color(value.get("color"), f"{path}.color"), material=material, anim=anim,
                        text=text, svg_png=svg_png, lane=lane)

    def svg(self, value: Any, path: str) -> bytes | None:
        if not isinstance(value, str) or "<svg" not in value[:4000].lower():
            self.warn(f"{path}.svg: нужен SVG-код (<svg …>) — предмет пропустила")
            return None
        if len(value) > MAX_SVG_CHARS:
            self.warn(f"{path}.svg: слишком большой SVG — предмет пропустила")
            return None
        if self.svg_used >= C.MAX_SVG_PROPS:
            self.warn(f"{path}: SVG-предметов не больше {C.MAX_SVG_PROPS} на мультик — лишний пропустила")
            return None
        if self.svg_renderer is None:
            self.warn(f"{path}: SVG-предметы сейчас недоступны — пропустила")
            return None
        self.svg_used += 1
        try:
            png = self.svg_renderer(value)
        except Exception:  # noqa: BLE001 — любой сбой растеризации: просто без предмета
            self.warn(f"{path}.svg: не получилось нарисовать SVG — предмет пропустила")
            return None
        if not isinstance(png, (bytes, bytearray)) or not bytes(png[:8]).startswith(b"\x89PNG"):
            self.warn(f"{path}.svg: не получилось нарисовать SVG — предмет пропустила")
            return None
        return bytes(png)

    def effect(self, value: Any, path: str, *, kind_key: str = "kind") -> EffectSpec | None:
        if isinstance(value, str):
            value = {kind_key: value}
        if not isinstance(value, Mapping):
            self.warn(f"{path}: эффект должен быть объектом — пропустила")
            return None
        kind = self.enum(value.get(kind_key, value.get("kind")), _V_EFFECT, f"{path}.{kind_key}")
        if kind is None:
            return None
        return EffectSpec(
            kind=kind,
            at=self.num(value.get("at"), 0.0, self.max_seconds, None, f"{path}.at"),
            seconds=self.num(value.get("seconds"), 0.2, self.max_seconds, None, f"{path}.seconds"),
            x=self.num(value.get("x"), 0.0, 1.0, None, f"{path}.x"),
            y=self.num(value.get("y"), 0.0, 1.0, None, f"{path}.y"),
            amount=self.amount(value.get("amount"), f"{path}.amount"),
        )

    def amount(self, value: Any, path: str) -> str:
        if _is_num(value):
            x = self.num(value, 0.0, 1.0, 0.5, path)
            x = 0.5 if x is None else x
            return "few" if x < 0.34 else "normal" if x < 0.67 else "lots"
        return self.enum(value, _V_AMOUNT, path, "normal") or "normal"

    def title(self, value: Any, path: str) -> TitleSpec | None:
        if value is None:
            return None
        if isinstance(value, str) or _is_num(value):
            value = {"text": value}
        if not isinstance(value, Mapping):
            self.warn(f"{path}: нужно {{text, style, anim}}")
            return None
        text = self.text(value.get("text"), C.MAX_TITLE_CHARS, f"{path}.text", "заголовок")
        if not text:
            if value.get("text") is not None:
                self.warn(f"{path}: пустой заголовок — пропустила")
            return None
        at = self.num(value.get("at"), 0.0, self.max_seconds, 0.0, f"{path}.at")
        return TitleSpec(
            text=text,
            style=self.enum(value.get("style"), _V_TITLE_STYLE, f"{path}.style", "gold3d") or "gold3d",
            anim=self.enum(value.get("anim"), _V_TITLE_ANIM, f"{path}.anim", "drop") or "drop",
            position=self.enum(value.get("position"), _V_POSITION, f"{path}.position", "top") or "top",
            at=0.0 if at is None else at,
            seconds=self.num(value.get("seconds"), 0.5, self.max_seconds, None, f"{path}.seconds"),
        )

    # --- биты ---
    def who(self, value: Any, path: str) -> list[str] | str | None:
        """Список id, «ALL» или None (не указан — как у предыдущего бита)."""
        if value is None:
            return None
        if isinstance(value, str) or _is_num(value):
            text = _as_str(value) or ""
            if _key(text).replace("_", " ") in _ALL_WORDS:
                return "ALL"
            parts = [p for p in re.split(r"\s*(?:[,;&+]| и | and )\s*", text) if p.strip()]
        elif isinstance(value, (list, tuple)):
            parts = list(value[: C.MAX_CAST * 2])
        else:
            self.warn(f"{path}: who — строка (id или \"all\") или список id; взяла как у предыдущего бита")
            return None
        out: list[str] = []
        for i, p in enumerate(parts):
            ps = _as_str(p)
            if ps is not None and _key(ps).replace("_", " ") in _ALL_WORDS:
                return "ALL"
            if ps is None:
                self.warn(f"{path}[{i}]: id актёра должен быть строкой")
                continue
            aid = self.actor(ps, path, create=True)
            if aid and aid not in out:
                out.append(aid)
        return out or None

    def beat(self, value: Any, path: str) -> dict[str, Any] | None:
        if isinstance(value, str):
            value = {"say": value} if value.strip() else {}
        if not isinstance(value, Mapping):
            self.warn(f"{path}: бит должен быть объектом — пропустила")
            return None
        d: dict[str, Any] = {"path": path, "who": self.who(value.get("who", value.get("actor")), f"{path}.who")}
        do_raw = value.get("do", value.get("action"))
        d["do"] = self.enum(do_raw, _V_ACTION, f"{path}.do", required=True) if do_raw is not None else None
        line, kind = None, "say"
        for key, k in _LINE_KEYS:
            if value.get(key) is not None:
                if line is not None:
                    self.warn(f"{path}: в бите одна реплика — «{key}» пропустила")
                    continue
                line = self.text(value[key], C.MAX_LINE_CHARS, f"{path}.{key}", "реплика")
                kind = k or self.enum(value.get("kind", value.get("line_kind")), _V_LINE_KIND, f"{path}.kind", "say")
        d["line"] = line or None
        d["line_kind"] = kind or "say"
        d["emotion"] = self.enum(value.get("emotion"), _V_EMOTION, f"{path}.emotion")
        d["mark"] = self.enum(value.get("mark"), _V_MARK, f"{path}.mark")
        d["to"] = self.to(value.get("to"), f"{path}.to")
        d["side"] = self.enum(value.get("from", value.get("side")), _V_SIDE, f"{path}.from")
        tgt = value.get("target")
        d["target"] = self.actor(tgt, f"{path}.target", create=True) if _as_str(tgt) else None
        d["look"] = self.look(value.get("look"), f"{path}.look")
        d["style"] = None
        if value.get("style") is not None and d["do"] == "dance":
            d["style"] = self.enum(value.get("style"), _V_DANCE, f"{path}.style", "bounce")
        secs = value.get("seconds", value.get("wait", value.get("pause")))
        d["seconds"] = self.num(secs, 0.2, self.max_seconds, None, f"{path}.seconds")
        d["at"] = self.num(value.get("at"), 0.0, self.max_seconds, None, f"{path}.at")
        w = value.get("with", value.get("with_prev"))
        d["with_prev"] = bool(w) and not (isinstance(w, str) and _key(w) in ("no", "false", "нет", "0"))
        d["effect"] = None
        if value.get("effect") is not None:
            eff = value["effect"]
            if isinstance(eff, str) or _is_num(eff):
                eff = {"kind": _as_str(eff), "seconds": value.get("seconds") if d["do"] is None else None,
                       "x": value.get("x"), "y": value.get("y"),
                       "amount": value.get("amount") if value.get("camera") is None else None}
            d["effect"] = self.effect(eff, f"{path}.effect")
        d["camera"], d["camera_focus"] = None, None
        amount = value.get("amount")
        d["amount"] = self.num(amount, 0.0, 1.0, None, f"{path}.amount") if _is_num(amount) else None
        if value.get("camera") is not None:
            cam = value["camera"]
            focus = value.get("focus")
            if isinstance(cam, Mapping):
                focus = cam.get("focus", focus)
                if cam.get("amount") is not None:
                    d["amount"] = self.num(cam.get("amount"), 0.0, 1.0, None, f"{path}.camera.amount")
                cam = cam.get("move", cam.get("kind"))
            d["camera"] = self.enum(cam, _V_CAM_ANY, f"{path}.camera")
            if focus is not None:
                d["camera_focus"] = self.actor(focus, f"{path}.focus", create=False)
        elif d["do"] is None and value.get("focus") is not None:
            d["camera_focus"] = self.actor(value.get("focus"), f"{path}.focus", create=False)
        return d

    def to(self, value: Any, path: str) -> float | str | None:
        if value is None:
            return None
        if isinstance(value, Mapping):
            value = value.get("x", value.get("id"))
            if value is None:
                return None
        if _is_num(value):
            return self.num(value, 0.0, 1.0, None, path)
        if not isinstance(value, str):
            self.warn(f"{path}: нужно x 0..1, id актёра или left/right/center/offscreen")
            return None
        k = _key(value).replace("_", " ")
        if k in _TO_WORDS:
            return _TO_WORDS[k]
        try:
            return self.num(float(value.replace(",", ".")), 0.0, 1.0, None, path)
        except ValueError:
            pass
        return self.actor(value, path, create=True)

    def look(self, value: Any, path: str) -> str | None:
        if value is None:
            return None
        s = _as_str(value)
        if s is None:
            self.warn(f"{path}: нужно id актёра или camera/left/right")
            return None
        k = _key(s).replace("_", " ")
        if k in _LOOK_WORDS:
            return _LOOK_WORDS[k]
        return self.actor(s, path, create=False)

    # --- сценарий целиком ---
    def run(self) -> Spec:
        raw = self.raw
        fmt = self.enum(raw.get("format"), _V_FORMAT, "format", "square") or "square"
        seed_raw = raw.get("seed")
        canon: list[str] = []
        _canon({k: v for k, v in raw.items() if k != "seed"}, canon, 0, 10**9)
        seed = zlib.crc32("\x1f".join(canon).encode("utf-8", "replace")) & 0x7FFFFFFF
        if seed_raw is not None:
            got = self.num(seed_raw, -1e15, 1e15, None, "seed")
            if got is not None:
                seed = int(abs(got)) & 0x7FFFFFFF
        self.seed = seed
        caption = ""
        cap = raw.get("caption")
        if cap is not None:
            cs = _as_str(cap)
            if cs is None:
                self.warn("caption: нужна строка")
            else:
                if len(cs) > C.MAX_CAPTION_CHARS:
                    self.warn(f"caption: подпись сокращена до {C.MAX_CAPTION_CHARS} знаков")
                caption = _plain(cs, C.MAX_CAPTION_CHARS)

        # cast: объект {id: {...}} или список [{id, ...}]
        cast_raw = raw.get("cast", raw.get("characters", raw.get("actors")))
        entries: list[tuple[Any, Any, str]] = []
        if isinstance(cast_raw, Mapping):
            entries = [(k, v, f"cast.{_short(_safe_str(k))}") for k, v in cast_raw.items()]
        elif isinstance(cast_raw, (list, tuple)):
            for i, item in enumerate(cast_raw):
                if isinstance(item, Mapping):
                    entries.append((item.get("id", item.get("name")), item, f"cast[{i}]"))
                elif isinstance(item, str):
                    entries.append((item, {"base": item}, f"cast[{i}]"))
                else:
                    self.warn(f"cast[{i}]: нужен объект {{id, base, …}} — пропустила")
        elif cast_raw is not None:
            self.warn("cast: нужен объект {id: {base, …}} — актёров возьму из битов")
        if len(entries) > C.MAX_CAST:
            self.warn(f"cast: актёров больше {C.MAX_CAST} — оставила первых {C.MAX_CAST}")
            entries = entries[: C.MAX_CAST]
        for k, v, path in entries:
            aid = self.norm_id(k)
            if aid is None:
                aid = self.norm_id(v.get("base")) if isinstance(v, Mapping) else None
                if aid is None or aid in self.cast:
                    self.warn(f"{path}: нет id — пропустила")
                    continue
            if _key(aid).replace("_", " ") in _ALL_WORDS or aid in _TO_WORDS or aid in _LOOK_WORDS:
                self.warn(f"{path}: id «{aid}» занят служебным словом — переименуй; пропустила")
                continue
            if aid in self.cast:
                self.warn(f"{path}: id «{aid}» повторяется — оставила первый")
                continue
            self.add_cast(aid, v, path)

        shots_raw = raw.get("shots", raw.get("scenes"))
        if shots_raw is None and raw.get("beats") is not None:
            shots_raw = [{k: raw[k] for k in ("beats", "background", "camera", "place", "props", "effects",
                                              "title", "seconds") if k in raw}]
        if isinstance(shots_raw, Mapping):
            shots_raw = [shots_raw]
        if not isinstance(shots_raw, (list, tuple)) or not shots_raw:
            raise SpecError("shots", "нужна хотя бы одна сцена: shots: [{beats: [...]}]")
        if len(shots_raw) > C.MAX_SHOTS:
            self.warn(f"shots: сцен больше {C.MAX_SHOTS} — оставила первые {C.MAX_SHOTS}")
            shots_raw = shots_raw[: C.MAX_SHOTS]
        top_bg, top_title = raw.get("background"), raw.get("title")

        drafts: list[dict[str, Any]] = []
        for i, sraw in enumerate(shots_raw):
            d = self.shot_draft(sraw, f"shots[{i}]", top_bg, top_title if i == 0 else None)
            if d is not None:
                drafts.append(d)
        if not drafts:
            raise SpecError("shots", "ни одной пригодной сцены: нужны beats с who/do/say")
        shots = self.finish_shots(drafts)
        if not shots:
            raise SpecError("shots", "ни одной пригодной сцены: нужны beats с who/do/say")
        warnings = self.warnings
        if len(warnings) > MAX_WARNINGS:
            warnings = warnings[: MAX_WARNINGS - 1] + [f"…и ещё {len(warnings) - MAX_WARNINGS + 1} поправок"]
        return Spec(format=fmt, size=C.FORMATS[fmt], cast=dict(self.cast), shots=tuple(shots), caption=caption,
                    seed=seed, warnings=tuple(warnings), max_seconds=self.max_seconds)

    def shot_draft(self, raw: Any, path: str, top_bg: Any, top_title: Any) -> dict[str, Any] | None:
        if not isinstance(raw, Mapping):
            self.warn(f"{path}: сцена должна быть объектом — пропустила")
            return None
        d: dict[str, Any] = {"path": path}
        d["background"] = self.background(raw.get("background", top_bg), f"{path}.background")
        d["camera"] = self.camera(raw.get("camera"), f"{path}.camera")
        # place
        place: dict[str, PlaceSpec] = {}
        praw = raw.get("place")
        items: list[tuple[Any, Any, str]] = []
        if isinstance(praw, Mapping):
            items = [(k, v, f"{path}.place.{_short(_safe_str(k))}") for k, v in praw.items()]
        elif isinstance(praw, (list, tuple)):
            for j, item in enumerate(praw):
                if isinstance(item, Mapping):
                    items.append((item.get("id", item.get("who")), item, f"{path}.place[{j}]"))
        elif praw is not None:
            self.warn(f"{path}.place: нужен объект {{id: {{x, lane}}}}")
        for k, v, p in items[: C.MAX_CAST * 2]:
            ks = _as_str(k)
            if ks is not None and _key(ks).replace("_", " ") in _ALL_WORDS:
                self.warn(f"{p}: в place нужны id актёров, «all» нельзя — пропустила")
                continue
            aid = self.actor(k, p, create=True)
            if aid and aid not in place:
                place[aid] = self.place_entry(v, p)
        d["place"] = place
        d["has_place"] = bool(place)
        # props
        props: list[PropSpec] = []
        props_raw = raw.get("props", raw.get("objects"))
        if isinstance(props_raw, Mapping):
            props_raw = [dict(v, id=k) if isinstance(v, Mapping) else v for k, v in props_raw.items()]
        if props_raw is not None and not isinstance(props_raw, (list, tuple)):
            self.warn(f"{path}.props: нужен список")
            props_raw = []
        props_raw = list(props_raw or [])
        if len(props_raw) > C.MAX_PROPS_PER_SHOT:
            self.warn(f"{path}.props: предметов больше {C.MAX_PROPS_PER_SHOT} — лишние пропустила")
            props_raw = props_raw[: C.MAX_PROPS_PER_SHOT]
        for j, pr in enumerate(props_raw):
            got = self.prop(pr, f"{path}.props[{j}]", len(props))
            if got is not None:
                props.append(got)
        d["props"] = props
        # effects
        effects: list[EffectSpec] = []
        eff_raw = raw.get("effects")
        if isinstance(eff_raw, (str, Mapping)):
            eff_raw = [eff_raw]
        if eff_raw is not None and not isinstance(eff_raw, (list, tuple)):
            self.warn(f"{path}.effects: нужен список")
            eff_raw = []
        for j, er in enumerate(list(eff_raw or [])[: C.MAX_EFFECTS_PER_SHOT * 2]):
            got = self.effect(er, f"{path}.effects[{j}]")
            if got is not None:
                effects.append(got)
        d["effects"] = effects
        d["title"] = self.title(raw.get("title", top_title), f"{path}.title")
        d["seconds"] = self.num(raw.get("seconds"), 1.0, self.max_seconds, None, f"{path}.seconds")
        d["transition"] = self.enum(raw.get("transition"), _V_TRANSITION, f"{path}.transition", "fade") or "fade"
        # beats
        beats_raw = raw.get("beats")
        if isinstance(beats_raw, Mapping):
            beats_raw = [beats_raw]
        if beats_raw is not None and not isinstance(beats_raw, (list, tuple)):
            self.warn(f"{path}.beats: нужен список")
            beats_raw = []
        beats_raw = list(beats_raw or [])
        if len(beats_raw) > C.MAX_BEATS_PER_SHOT:
            self.warn(f"{path}.beats: битов больше {C.MAX_BEATS_PER_SHOT} — лишние пропустила")
            beats_raw = beats_raw[: C.MAX_BEATS_PER_SHOT]
        room = C.MAX_BEATS - self.beats_total
        if len(beats_raw) > room:
            self.warn(f"{path}.beats: всего битов больше {C.MAX_BEATS} — лишние пропустила")
            beats_raw = beats_raw[: max(0, room)]
        self.beats_total += len(beats_raw)
        beats = []
        for j, br in enumerate(beats_raw):
            got = self.beat(br, f"{path}.beats[{j}]")
            if got is not None:
                beats.append(got)
        d["beats"] = beats
        return d

    def finish_shots(self, drafts: list[dict[str, Any]]) -> list[ShotSpec]:
        """Кто в какой сцене, «all» → список, лимиты на экране, сборка ShotSpec."""
        single = len(drafts) == 1
        # кто вообще где-то участвует
        used: set[str] = set()
        for d in drafts:
            used.update(d["place"])
            for b in d["beats"]:
                if isinstance(b["who"], list):
                    used.update(b["who"])
                for key in ("target", "to"):
                    if isinstance(b[key], str) and b[key] in self.cast:
                        used.add(b[key])
        orphans = [a for a in self.cast if a not in used]
        orphan_shot = next((n for n, d in enumerate(drafts) if not d["has_place"]), None)
        shots: list[ShotSpec] = []
        for n, d in enumerate(drafts):
            path = d["path"]
            parts: list[str] = list(d["place"])
            any_all = any(b["who"] == "ALL" for b in d["beats"])
            for b in d["beats"]:
                ids = b["who"] if isinstance(b["who"], list) else []
                ids = ids + [b[k] for k in ("target", "to") if isinstance(b[k], str) and b[k] in self.cast]
                for a in ids:
                    if a not in parts:
                        parts.append(a)
            if not d["has_place"] and (single or any_all or not parts):
                for a in self.cast:
                    if a not in parts:
                        parts.append(a)
            if n == orphan_shot:
                for a in orphans:
                    if a not in parts:
                        parts.append(a)
            needs_actor = any(b["who"] is None and self.beat_has_actor_stuff(b) for b in d["beats"])
            if not parts and (needs_actor or any_all):
                if not self.cast:
                    self.add_cast("stella", {"base": "stella"}, path)
                    self.warn(f"{path}: актёров нет — взяла Стеллу (stella)")
                parts.append(next(iter(self.cast)))
            if len(parts) > C.MAX_ON_SCREEN:
                self.warn(f"{path}: на экране не больше {C.MAX_ON_SCREEN} актёров — "
                          f"{', '.join(parts[C.MAX_ON_SCREEN:])} в сцену не попали")
                parts = parts[: C.MAX_ON_SCREEN]
            on = set(parts)
            beats: list[BeatSpec] = []
            prev_who: tuple[str, ...] = ()
            n_effects = len(d["effects"])
            for b in d["beats"]:
                who_raw = b["who"]
                if who_raw == "ALL":
                    who = tuple(parts)
                elif isinstance(who_raw, list):
                    who = tuple(a for a in who_raw if a in on)
                    if len(who) < len(who_raw):
                        self.warn(f"{b['path']}.who: {', '.join(a for a in who_raw if a not in on)} нет в сцене")
                elif self.beat_has_actor_stuff(b):
                    who = prev_who or (tuple(parts[:1]))
                else:
                    who = ()
                if who:
                    prev_who = who
                target = b["target"] if b["target"] in on else None
                to = b["to"]
                if isinstance(to, str) and to not in ("left", "right", "center", "offscreen") and to not in on:
                    to = None
                look = b["look"]
                if look is not None and look not in ("camera", "left", "right") and look not in on:
                    look = None
                focus = b["camera_focus"] if b["camera_focus"] in on else None
                effect = b["effect"]
                if effect is not None:
                    if n_effects >= C.MAX_EFFECTS_PER_SHOT:
                        self.warn(f"{b['path']}.effect: эффектов в сцене больше {C.MAX_EFFECTS_PER_SHOT} — пропустила")
                        effect = None
                    else:
                        n_effects += 1
                camera = b["camera"]
                if camera is not None and camera not in C.CAMERA_BEATS:
                    if camera == "static":
                        camera = "reset"
                    elif d["camera"][0] == "static":
                        self.warn(f"{b['path']}.camera: {camera} — это движение на всю сцену, поставила в camera.move")
                        d["camera"] = (camera, d["camera"][1], b["amount"] if b["amount"] is not None else 0.5)
                        camera = None
                    else:
                        self.warn(f"{b['path']}.camera: {camera} в бите нельзя. Можно: " + ", ".join(C.CAMERA_BEATS))
                        camera = None
                do = b["do"]
                if do is None and to is not None and who:
                    do = "walk"
                beat = BeatSpec(
                    who=who, do=do, line=b["line"] if who else None, line_kind=b["line_kind"], emotion=b["emotion"],
                    mark=b["mark"], to=to, side=b["side"], target=target, look=look, style=b["style"],
                    seconds=b["seconds"], at=b["at"], with_prev=b["with_prev"], effect=effect, camera=camera,
                    camera_focus=focus, amount=b["amount"],
                )
                if not who and (do or b["line"] or b["emotion"] or b["mark"]):
                    self.warn(f"{b['path']}: непонятно, кто это делает (who) — пропустила")
                    continue
                if not (who or effect or camera or beat.seconds):
                    self.warn(f"{b['path']}: пустой бит — пропустила")
                    continue
                beats.append(beat)
            # эффекты сцены сверх лимита
            effects = d["effects"]
            if len(effects) > C.MAX_EFFECTS_PER_SHOT:
                self.warn(f"{path}.effects: эффектов больше {C.MAX_EFFECTS_PER_SHOT} — лишние пропустила")
                effects = effects[: C.MAX_EFFECTS_PER_SHOT]
            # 3D на экране: предметы + 3D-игрушки
            props = d["props"]
            toys = sum(1 for a in parts if self.cast[a].base in C.BASES_3D)
            room3d = max(0, C.MAX_3D_ON_SCREEN - toys)
            kept: list[PropSpec] = []
            n3d = 0
            for p in props:
                if p.kind in C.PROPS_3D:
                    if n3d >= room3d:
                        self.warn(f"{path}.props: 3D-объектов на экране не больше {C.MAX_3D_ON_SCREEN} — "
                                  f"{p.id} пропустила")
                        continue
                    n3d += 1
                kept.append(p)
            move, focus_raw, amount = d["camera"]
            focus = None
            if focus_raw is not None:
                focus = self.actor(focus_raw, f"{path}.camera.focus", create=False)
                if focus is not None and focus not in on:
                    self.warn(f"{path}.camera.focus: {focus} нет в сцене — пропустила")
                    focus = None
            if not (beats or d["title"] or kept or effects):
                self.warn(f"{path}: в сцене ничего нет — пропустила")
                continue
            place = {a: d["place"].get(a, PlaceSpec()) for a in parts}
            shots.append(ShotSpec(
                background=d["background"], camera=CameraSpec(move=move, focus=focus, amount=amount), place=place,
                props=tuple(kept), effects=tuple(effects), title=d["title"], beats=tuple(beats),
                seconds=d["seconds"], transition=d["transition"],
            ))
        return shots

    @staticmethod
    def beat_has_actor_stuff(b: Mapping[str, Any]) -> bool:
        return bool(b["do"] or b["line"] or b["emotion"] or b["mark"] or b["look"] or b["to"] is not None
                    or b["target"])


def parse_spec(raw: Mapping[str, Any], *, max_seconds: float = 20.0,
               svg_renderer: Callable[[str], bytes] | None = None) -> Spec:
    """JSON сценария от модели → Spec. Поправленное — в Spec.warnings; непоправимое — SpecError (путь + что можно).
    svg_renderer(svg) → PNG вызывается для предметов kind=svg (не больше MAX_SVG_PROPS); без него они пропускаются."""
    if isinstance(raw, (str, bytes)):
        import json

        try:
            raw = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise SpecError("", "сценарий — не JSON-объект") from exc
    if not isinstance(raw, Mapping):
        raise SpecError("", "сценарий должен быть JSON-объектом {cast, shots}")
    try:
        max_seconds = float(max_seconds)
    except (TypeError, ValueError):
        max_seconds = 20.0
    if not math.isfinite(max_seconds):
        max_seconds = 20.0
    max_seconds = min(120.0, max(2.0, max_seconds))
    size = _canon(raw, [], 0, C.MAX_SPEC_JSON)
    if size > C.MAX_SPEC_JSON:
        raise SpecError("", f"сценарий слишком длинный (больше {C.MAX_SPEC_JSON // 1000} КБ) — сократи реплики "
                            "и число битов")
    try:
        return _Parser(raw, max_seconds, svg_renderer).run()
    except SpecError:
        raise
    except RecursionError as exc:
        raise SpecError("", "сценарий слишком запутанный — упрости") from exc
