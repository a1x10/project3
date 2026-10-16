"""Единый справочник имён мультиков: персонажи, действия, эмоции, фоны, предметы, эффекты…

Отсюда же берутся enum'ы схемы инструмента make_cartoon и списки допустимых значений в ошибках для модели.
Русские синонимы — чтобы модель (и люди в чате) могли писать как удобно: «кот», «танец», «конфетти».
"""

from __future__ import annotations

# ---------- персонажи ----------
# 2D-куклы (рисуются векторно) и 3D-игрушки (собраны из 3D-примитивов, лицо — то же 2D)
BASES_2D = (
    "stella", "boy", "girl", "teen", "cat", "dog", "fox", "bunny", "bear",
    "robot", "alien", "dragon", "ghost", "monster",
)
BASES_3D = ("robot3d", "penguin3d", "snowman3d")
BASES = BASES_2D + BASES_3D
HUMANS = ("stella", "boy", "girl", "teen")
CREATURES = ("cat", "dog", "fox", "bunny", "bear", "alien", "dragon", "monster")

BASE_ALIASES = {
    "стелла": "stella", "я": "stella", "me": "stella",
    "мальчик": "boy", "парень": "boy", "пацан": "boy", "man": "boy",
    "девочка": "girl", "девушка": "girl", "woman": "girl",
    "подросток": "teen", "тинейджер": "teen",
    "кот": "cat", "кошка": "cat", "котик": "cat", "котёнок": "cat", "котенок": "cat", "kitty": "cat",
    "собака": "dog", "пёс": "dog", "пес": "dog", "щенок": "dog", "puppy": "dog",
    "лиса": "fox", "лисичка": "fox", "лис": "fox",
    "заяц": "bunny", "зайчик": "bunny", "кролик": "bunny", "rabbit": "bunny",
    "медведь": "bear", "мишка": "bear",
    "робот": "robot", "инопланетянин": "alien", "пришелец": "alien",
    "дракон": "dragon", "дракончик": "dragon", "призрак": "ghost", "привидение": "ghost",
    "монстр": "monster", "чудик": "monster",
    "3d робот": "robot3d", "пингвин": "penguin3d", "penguin": "penguin3d", "снеговик": "snowman3d",
    "snowman": "snowman3d",
}

HAIR = ("short", "spiky", "bob", "long", "ponytail", "twintails", "bun", "afro", "curly", "none")
TOPS = ("tshirt", "hoodie", "dress", "shirt", "sweater", "suit")
BOTTOMS = ("pants", "shorts", "skirt")
PRINTS = ("star", "heart", "stripes")  # и ещё «number:7», «text:МАША» (до 6 знаков)
ACCESSORIES = (
    "glasses", "sunglasses", "cap", "crown", "bow", "headphones", "star_clips", "scarf",
    "party_hat", "wizard_hat", "mustache", "cape", "backpack",
)
SKINS = ("light", "fair", "tan", "brown", "dark", "deep")
MAX_ACCESSORIES = 3

# ---------- эмоции и значки над головой ----------
EMOTIONS = (
    "neutral", "happy", "excited", "laugh", "love", "smug", "sad", "cry", "angry", "surprised",
    "scared", "sleepy", "dizzy", "thinking", "embarrassed", "proud",
)
EMOTION_ALIASES = {
    "радость": "happy", "рад": "happy", "весёлый": "happy", "веселый": "happy", "улыбка": "happy",
    "восторг": "excited", "смех": "laugh", "смеётся": "laugh", "любовь": "love", "влюблён": "love",
    "хитрый": "smug", "грусть": "sad", "грустный": "sad", "плачет": "cry", "слёзы": "cry",
    "злой": "angry", "злость": "angry", "удивление": "surprised", "удивлён": "surprised", "страх": "scared",
    "испуг": "scared", "сонный": "sleepy", "спит": "sleepy", "думает": "thinking", "смущён": "embarrassed",
    "гордый": "proud", "joy": "happy", "mad": "angry", "shocked": "surprised", "fear": "scared",
}
MARKS = (
    "hearts", "sweat", "anger", "sparkles", "question", "exclaim", "zzz", "idea", "music", "dizzy",
    "steam", "shock", "tears",
)

# ---------- действия ----------
ACTIONS = (
    "idle", "walk", "walk_in", "walk_out", "run", "jump", "hop", "wave", "clap", "point", "talk",
    "laugh", "cry", "dance", "spin", "fly", "float", "fall", "sit", "sleep", "think", "shrug",
    "facepalm", "nod", "shake_head", "bow", "hug", "high_five", "celebrate", "scared", "stomp",
    "turn", "appear", "poof", "grow", "shrink",
)
DANCE_STYLES = ("bounce", "sway", "robot", "disco", "spin", "wiggle")
ACTION_ALIASES = {
    "стоит": "idle", "стоять": "idle", "идёт": "walk", "идет": "walk", "идти": "walk", "ходит": "walk",
    "входит": "walk_in", "приходит": "walk_in", "уходит": "walk_out", "бежит": "run", "бег": "run",
    "прыгает": "jump", "прыжок": "jump", "подпрыгивает": "hop", "машет": "wave", "привет": "wave",
    "хлопает": "clap", "аплодирует": "clap", "показывает": "point", "говорит": "talk",
    "смеётся": "laugh", "смеется": "laugh", "плачет": "cry", "танцует": "dance", "танец": "dance",
    "крутится": "spin", "летит": "fly", "летает": "fly", "парит": "float", "падает": "fall",
    "сидит": "sit", "спит": "sleep", "думает": "think", "пожимает плечами": "shrug", "кивает": "nod",
    "качает головой": "shake_head", "кланяется": "bow", "обнимает": "hug", "обнимашки": "hug",
    "дай пять": "high_five", "празднует": "celebrate", "ура": "celebrate", "пугается": "scared",
    "топает": "stomp", "поворачивается": "turn", "появляется": "appear", "исчезает": "poof",
    "растёт": "grow", "уменьшается": "shrink", "dancing": "dance", "walking": "walk", "jumping": "jump",
    "running": "run", "waving": "wave", "flying": "fly", "disappear": "poof", "vanish": "poof",
}
LINE_KINDS = ("say", "think", "shout", "whisper")

# ---------- сцена ----------
FORMATS = {"square": (720, 720), "wide": (1280, 720), "tall": (720, 1280)}
BACKGROUNDS = (
    "park", "city", "forest", "beach", "space", "room", "classroom", "stage", "party", "winter",
    "underwater", "sky",
)
BACKGROUND_ALIASES = {
    "парк": "park", "улица": "park", "двор": "park", "город": "city", "лес": "forest", "пляж": "beach",
    "море": "beach", "космос": "space", "комната": "room", "дом": "room", "класс": "classroom",
    "школа": "classroom", "сцена": "stage", "концерт": "stage", "вечеринка": "party", "праздник": "party",
    "день рождения": "party", "зима": "winter", "снег": "winter", "под водой": "underwater", "небо": "sky",
    "street": "park", "school": "classroom", "concert": "stage", "birthday": "party", "ocean": "beach",
    "home": "room", "studio": "sky",
}
TIMES = ("day", "sunset", "evening", "night")
WEATHER = ("clear", "snow", "rain")
LANES = ("back", "mid", "front")
FACINGS = ("left", "right", "camera")

PROPS_2D = (
    "table", "chair", "sign", "tree", "bush", "flower", "ball", "book", "phone", "pizza", "ice_cream",
    "cup", "guitar", "microphone", "umbrella", "car", "house", "svg",
)
PROPS_3D = (
    "sphere", "cube", "torus", "cylinder", "cone", "gem", "star", "heart", "coin", "dice", "planet",
    "gift", "cake", "balloon", "donut", "trophy", "disco_ball", "rocket", "christmas_tree", "text3d",
)
PROPS = PROPS_2D + PROPS_3D
PROP_ALIASES = {
    "стол": "table", "стул": "chair", "табличка": "sign", "дерево": "tree", "куст": "bush", "цветок": "flower",
    "мяч": "ball", "книга": "book", "телефон": "phone", "пицца": "pizza", "мороженое": "ice_cream",
    "чашка": "cup", "гитара": "guitar", "микрофон": "microphone", "зонт": "umbrella", "машина": "car",
    "дом": "house", "шар": "sphere", "куб": "cube", "кубик": "cube", "бублик": "torus", "цилиндр": "cylinder",
    "конус": "cone", "алмаз": "gem", "кристалл": "gem", "звезда": "star", "сердце": "heart", "монета": "coin",
    "кость": "dice", "планета": "planet", "подарок": "gift", "торт": "cake", "воздушный шар": "balloon",
    "шарик": "balloon", "пончик": "donut", "кубок": "trophy", "диско-шар": "disco_ball", "дискошар": "disco_ball",
    "ракета": "rocket", "ёлка": "christmas_tree", "елка": "christmas_tree", "надпись": "text3d",
    "box": "cube", "ball3d": "sphere", "diamond": "gem", "crystal": "gem", "present": "gift", "tree3d": "christmas_tree",
}
MATERIALS = ("plastic", "toon", "candy", "clay", "chrome", "gold", "glass", "gem")
PROP_ANIMS = ("none", "spin", "float", "bounce", "pulse", "wobble", "swing")

EFFECTS = (
    "confetti", "snow", "rain", "hearts", "stars", "sparkles", "fire", "smoke", "poof", "fireworks",
    "balloons", "bubbles", "leaves", "coins", "music", "flash",
)
EFFECT_ALIASES = {
    "конфетти": "confetti", "снег": "snow", "дождь": "rain", "сердечки": "hearts", "звёзды": "stars",
    "звезды": "stars", "блёстки": "sparkles", "искры": "sparkles", "огонь": "fire", "дым": "smoke",
    "салют": "fireworks", "фейерверк": "fireworks", "шарики": "balloons", "пузыри": "bubbles",
    "листья": "leaves", "монеты": "coins", "ноты": "music", "вспышка": "flash",
}
AMOUNTS = ("few", "normal", "lots")

TITLE_STYLES = ("gold3d", "chrome3d", "candy3d", "neon", "comic", "plain")
TITLE_STYLES_3D = ("gold3d", "chrome3d", "candy3d")
TITLE_ANIMS = ("drop", "spin", "pop", "wave", "type")
TITLE_POSITIONS = ("top", "center", "bottom")

CAMERA_MOVES = ("static", "zoom_in", "zoom_out", "pan_left", "pan_right", "follow", "orbit")
CAMERA_BEATS = ("shake", "zoom_in", "zoom_out", "punch", "focus", "reset")
TRANSITIONS = ("cut", "fade", "crossfade", "wipe", "iris", "zoom", "slide", "flash")

# ---------- лимиты сценария (что бы ни прислала модель) ----------
MAX_CAST = 5
MAX_ON_SCREEN = 4
MAX_SHOTS = 4
MAX_BEATS_PER_SHOT = 12
MAX_BEATS = 30
MAX_PROPS_PER_SHOT = 8
MAX_SVG_PROPS = 3
MAX_3D_ON_SCREEN = 6
MAX_EFFECTS_PER_SHOT = 6
MAX_LINE_CHARS = 100
MAX_TITLE_CHARS = 32
MAX_TEXT3D_CHARS = 12
MAX_NAME_CHARS = 20
MAX_CAPTION_CHARS = 300
MAX_SPEC_JSON = 24_000  # байт JSON сценария (SVG-реквизит не считается)
MAX_PARTICLES = 300  # видимых частиц в кадре
