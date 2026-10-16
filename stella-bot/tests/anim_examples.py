"""Примеры сценариев make_cartoon — какими их написала бы модель на обычные просьбы в чате.

Общие для тестов всех пакетов мультиков (разбор, план, кадры, движок) и для QA-листов. PROMPTS — просьба, на
которую написан сценарий. Все примеры проходят parse_spec + compile_plan без ошибок (проверяет
tests/test_anim_spec.py); stress упирается в лимиты и сжимается по времени.
"""

from __future__ import annotations

from typing import Any

PROMPTS: dict[str, str] = {
    "birthday": "сделай мультик Маше на день рождения, с котом Барсиком и тортом",
    "disco_cat": "мультик: кот танцует под дискошаром",
    "cube3d": "3D вращающийся куб с надписью ПРИВЕТ",
    "argue": "мультик про двух друзей, которые спорят",
    "space_robot": "робот летит в космосе",
    "school": "сделай вертикальное видео: урок в школе, учительница спрашивает Колю",
    "stress": "огромный мультик со всеми друзьями, снегом, космосом, концертом и фейерверком",
}

EXAMPLES: dict[str, dict[str, Any]] = {
    # (1) design_wow §(a): день рождения в двух сценах
    "birthday": {
        "format": "square",
        "caption": "Маша, с днём рождения! 🎂",
        "seed": 7,
        "cast": {
            "stella": {"base": "stella"},
            "masha": {"base": "girl", "name": "Маша", "skin": "light", "hair": "long", "hair_color": "рыжий",
                      "eyes": "#3fbf5f", "top": {"style": "dress", "color": "#ff7eb6", "print": "heart"},
                      "accessories": ["party_hat"]},
            "barsik": {"base": "cat", "name": "Барсик", "color": "#ffa94d", "accessories": ["bow"], "size": 0.8},
        },
        "shots": [
            {
                "background": {"preset": "party", "time": "evening"},
                "camera": {"move": "zoom_in", "focus": "masha", "amount": 0.4},
                "place": {"stella": {"x": 0.2, "facing": "right"}, "masha": {"x": 0.55},
                          "barsik": {"x": 0.85, "lane": "front"}},
                "props": [
                    {"id": "cake", "kind": "cake", "x": 0.55, "y": 0.66, "size": 0.2},
                    {"id": "b1", "kind": "balloon", "x": 0.1, "y": 0.3, "color": "#ff3d6e", "anim": "float"},
                    {"id": "b2", "kind": "balloon", "x": 0.92, "y": 0.25, "color": "#3ec1ff", "anim": "float"},
                ],
                "title": {"text": "С ДНЁМ РОЖДЕНИЯ!", "style": "gold3d", "anim": "drop", "seconds": 4},
                "beats": [
                    {"who": "stella", "do": "walk_in", "from": "left"},
                    {"who": "stella", "do": "wave", "say": "Маша, с днём рождения!", "emotion": "excited"},
                    {"who": "barsik", "do": "jump", "emotion": "laugh", "with": "prev"},
                    {"effect": "confetti", "with": "prev"},
                    {"who": "masha", "say": "Ой, спасибо!!!", "emotion": "love", "mark": "hearts"},
                    {"who": "all", "do": "dance", "style": "bounce", "seconds": 3},
                ],
                "transition": "iris",
            },
            {
                "background": {"preset": "space", "time": "night"},
                "place": {"masha": {"x": 0.45}},
                "props": [
                    {"id": "pl", "kind": "planet", "x": 0.8, "y": 0.28, "size": 0.3, "color": "#8a6bff",
                     "anim": "spin"},
                    {"id": "n", "kind": "text3d", "text": "12", "style": "chrome3d", "x": 0.25, "y": 0.3,
                     "size": 0.3, "anim": "spin"},
                ],
                "beats": [
                    {"who": "masha", "do": "fly", "emotion": "excited", "think": "Я лечу к звёздам!"},
                    {"effect": "stars", "with": "prev"},
                    {"camera": "shake", "amount": 0.3},
                ],
            },
        ],
    },
    # (2) сцена-вечеринка: стили танца, диско-шар, конфетти
    "disco_cat": {
        "format": "square",
        "caption": "Диско-кот зажигает 🐱✨",
        "seed": 21,
        "cast": {
            "murzik": {"base": "cat", "name": "Мурзик", "color": "#ffa94d", "accent": "#fff3e0",
                       "accessories": ["sunglasses"]},
        },
        "shots": [
            {
                "background": {"preset": "party", "time": "night"},
                "camera": {"move": "zoom_in", "focus": "murzik", "amount": 0.3},
                "place": {"murzik": {"x": 0.5, "lane": "front", "facing": "camera"}},
                "props": [
                    {"id": "disco", "kind": "disco_ball", "x": 0.5, "y": 0.14, "size": 0.2, "anim": "spin"},
                    {"id": "spk", "kind": "microphone", "x": 0.15, "size": 0.18},
                ],
                "effects": [{"kind": "sparkles", "amount": "few"}],
                "title": {"text": "ДИСКО-КОТ", "style": "neon", "anim": "pop", "position": "top", "at": 0.5,
                          "seconds": 3},
                "beats": [
                    {"who": "murzik", "do": "dance", "style": "disco", "emotion": "excited", "seconds": 3},
                    {"effect": "confetti", "with": "prev", "amount": "lots"},
                    {"who": "murzik", "do": "spin", "mark": "music"},
                    {"who": "murzik", "do": "dance", "style": "robot", "shout": "Мяу-диско!", "seconds": 2.5},
                    {"camera": "shake", "amount": 0.4, "with": "prev"},
                    {"who": "murzik", "do": "dance", "style": "wiggle", "emotion": "laugh", "seconds": 2.5},
                    {"effect": "music", "with": "prev"},
                ],
            },
        ],
    },
    # (3) только 3D: куб, 3D-надпись, золотой заголовок, без персонажей
    "cube3d": {
        "format": "square",
        "caption": "Держи 3D-кубик с приветом ✨",
        "seed": 3,
        "shots": [
            {
                "background": {"preset": "sky", "time": "sunset"},
                "camera": {"move": "orbit", "amount": 0.4},
                "props": [
                    {"id": "cube", "kind": "cube", "x": 0.5, "y": 0.52, "size": 0.36, "material": "candy",
                     "color": "#8a6bff", "anim": "spin"},
                    {"id": "word", "kind": "text3d", "text": "ПРИВЕТ", "x": 0.5, "y": 0.84, "size": 0.14,
                     "material": "gold", "anim": "wobble"},
                    {"id": "g1", "kind": "gem", "x": 0.14, "y": 0.3, "size": 0.12, "color": "#3fe0f0",
                     "anim": "float"},
                    {"id": "s1", "kind": "star", "x": 0.86, "y": 0.3, "size": 0.12, "material": "gold",
                     "anim": "spin"},
                ],
                "title": {"text": "ПРИВЕТ!", "style": "gold3d", "anim": "drop"},
                "effects": [{"kind": "sparkles"}],
                "beats": [
                    {"seconds": 1.5},
                    {"camera": "zoom_in", "amount": 0.5},
                    {"effect": "stars", "seconds": 2},
                    {"camera": "reset"},
                ],
                "seconds": 6,
            },
        ],
    },
    # (4) две сцены: спорят (say/shout/think/whisper, злость), мирятся (смех, обнимашки), переход iris
    "argue": {
        "format": "wide",
        "caption": "Поспорили — и помирились 🤝",
        "seed": 11,
        "cast": {
            "petya": {"base": "boy", "name": "Петя", "hair": "spiky", "top": {"style": "hoodie", "color": "#3a6df0"},
                      "bottom": {"style": "pants", "color": "#2b2f4a"}},
            "vasya": {"base": "boy", "name": "Вася", "skin": "tan", "hair": "curly", "hair_color": "рыжий",
                      "top": {"style": "tshirt", "color": "#ff9f1c", "print": "number:7"}, "accessories": ["cap"]},
        },
        "shots": [
            {
                "background": {"preset": "park", "time": "day"},
                "place": {"petya": {"x": 0.3}, "vasya": {"x": 0.7}},
                "props": [{"id": "ball", "kind": "ball", "x": 0.5, "size": 0.09, "color": "#ffffff"}],
                "beats": [
                    {"who": "petya", "do": "point", "target": "vasya", "say": "Это мой мяч!", "emotion": "angry"},
                    {"who": "vasya", "do": "stomp", "shout": "Нет, мой!", "emotion": "angry", "mark": "anger"},
                    {"who": "petya", "do": "shake_head", "think": "Вот упрямый…", "emotion": "smug"},
                    {"who": "vasya", "do": "shrug", "whisper": "Ну и ладно…", "emotion": "sad"},
                ],
                "transition": "iris",
            },
            {
                "background": {"preset": "park", "time": "sunset"},
                "camera": {"move": "zoom_in", "amount": 0.3},
                "beats": [
                    {"who": "vasya", "say": "Давай играть вместе?", "emotion": "happy"},
                    {"who": "petya", "do": "laugh", "say": "Давай!"},
                    {"who": ["petya", "vasya"], "do": "hug", "mark": "hearts"},
                    {"who": "all", "do": "celebrate", "emotion": "excited"},
                ],
            },
        ],
    },
    # (5) космос: полёт, планета, ракета, звёзды, 3D-робот появляется и даёт пять
    "space_robot": {
        "format": "wide",
        "caption": "Робот летит к звёздам 🚀",
        "seed": 42,
        "cast": {
            "robo": {"base": "robot", "name": "Робби", "color": "#9fb4c7", "accent": "#3fe0f0"},
            "bolt": {"base": "robot3d", "name": "Болт", "color": "#ff5d8f"},
        },
        "shots": [
            {
                "background": {"preset": "space", "time": "night"},
                "camera": {"move": "follow", "focus": "robo", "amount": 0.6},
                "place": {"robo": {"x": 0.15}},
                "props": [
                    {"id": "planet", "kind": "planet", "x": 0.8, "y": 0.28, "size": 0.32, "color": "#8a6bff",
                     "anim": "spin"},
                    {"id": "rocket", "kind": "rocket", "x": 0.3, "y": 0.22, "size": 0.16, "anim": "float"},
                ],
                "effects": [{"kind": "stars", "amount": "lots"}],
                "beats": [
                    {"who": "robo", "do": "fly", "to": 0.7, "emotion": "excited", "say": "Полный вперёд!"},
                    {"who": "robo", "do": "spin", "mark": "sparkles"},
                    {"who": "robo", "do": "wave", "look": "camera", "say": "Привет, Земля!"},
                ],
                "transition": "zoom",
            },
            {
                "background": {"preset": "space", "time": "night"},
                "place": {"robo": {"x": 0.3}, "bolt": {"x": 0.72, "lane": "front"}},
                "title": {"text": "КОСМОС", "style": "chrome3d", "anim": "wave"},
                "beats": [
                    {"who": "bolt", "do": "appear", "emotion": "surprised"},
                    {"effect": "poof", "with": "prev", "x": 0.72},
                    {"who": "bolt", "do": "high_five", "target": "robo", "emotion": "happy"},
                    {"who": "all", "do": "dance", "style": "robot", "seconds": 2.5},
                ],
            },
        ],
    },
    # (6) вертикальный формат: класс, надпись на доске, учительница и ученик, знаки вопроса
    "school": {
        "format": "tall",
        "caption": "Урок математики 📚",
        "seed": 5,
        "cast": {
            "teacher": {"base": "teen", "name": "Анна Петровна", "hair": "bun", "hair_color": "#6b3f2a",
                        "top": {"style": "suit", "color": "#5b4bd6"}, "bottom": {"style": "skirt", "color": "#2b2f4a"},
                        "accessories": ["glasses"], "size": 1.15},
            "kolya": {"base": "boy", "name": "Коля", "accessories": ["backpack"], "size": 0.85},
        },
        "shots": [
            {
                "background": {"preset": "classroom", "time": "day", "text": "2 + 2 = ?"},
                "place": {"teacher": {"x": 0.32, "lane": "back"}, "kolya": {"x": 0.68, "lane": "front"}},
                "props": [{"id": "book", "kind": "book", "x": 0.86, "size": 0.07}],
                "title": {"text": "УРОК", "style": "comic", "anim": "pop", "position": "top", "seconds": 2},
                "beats": [
                    {"who": "teacher", "do": "point", "target": "kolya",
                     "say": "Коля, сколько будет два плюс два?"},
                    {"who": "kolya", "do": "think", "emotion": "thinking", "mark": "question"},
                    {"who": "kolya", "do": "shrug", "think": "Хм… пять?", "emotion": "embarrassed", "mark": "sweat"},
                    {"who": "teacher", "do": "facepalm", "emotion": "sad"},
                    {"who": "kolya", "do": "jump", "shout": "Четыре!", "emotion": "excited", "mark": "idea"},
                    {"who": "teacher", "do": "clap", "say": "Молодец!", "emotion": "proud"},
                    {"effect": "stars", "with": "prev", "amount": "few"},
                ],
            },
        ],
    },
    # (7) всё сразу на пределе лимитов: 5 актёров, 4 сцены, погода, 3D, эффекты, все виды камеры и переходов
    "stress": {
        "format": "wide",
        "caption": "Самый большой мультик 🎉",
        "seed": 99,
        "cast": {
            "stella": {"base": "stella", "accessories": ["star_clips", "scarf"]},
            "masha": {"base": "girl", "name": "Маша", "hair": "twintails", "hair_color": "розовый",
                      "top": {"style": "sweater", "color": "#3ec46d", "print": "text:МАША"},
                      "bottom": {"style": "skirt", "color": "#5b4bd6"}, "shoes": "#ff3b3b"},
            "barsik": {"base": "cat", "name": "Барсик", "color": "серый", "accessories": ["crown"]},
            "rex": {"base": "dog", "name": "Рекс", "color": "#c98b4f", "accessories": ["headphones"]},
            "pingu": {"base": "penguin3d", "name": "Пингу"},
        },
        "shots": [
            {
                "background": {"preset": "winter", "time": "day", "weather": "snow"},
                "camera": {"move": "pan_right", "amount": 0.5},
                "place": {"stella": {"x": 0.2}, "masha": {"x": 0.42}, "barsik": {"x": 0.62, "lane": "front"},
                          "rex": {"x": 0.85, "lane": "back"}},
                "props": [
                    {"id": "tree", "kind": "christmas_tree", "x": 0.08, "size": 0.45},
                    {"id": "gift", "kind": "gift", "x": 0.3, "size": 0.12, "color": "#ff3b3b"},
                    {"id": "bal", "kind": "balloon", "x": 0.7, "y": 0.22, "color": "#ffd23f", "anim": "float"},
                    {"id": "st", "kind": "star", "x": 0.5, "y": 0.12, "size": 0.1, "anim": "spin"},
                    {"id": "coin", "kind": "coin", "x": 0.9, "y": 0.2, "size": 0.08, "anim": "spin"},
                    {"id": "hrt", "kind": "heart", "x": 0.35, "y": 0.2, "size": 0.08, "anim": "pulse"},
                    {"id": "bush", "kind": "bush", "x": 0.97, "size": 0.15},
                    {"id": "sign", "kind": "sign", "x": 0.75, "size": 0.18, "text": "ЗИМА"},
                ],
                "effects": [{"kind": "sparkles", "amount": "few"}],
                "beats": [
                    {"who": "stella", "do": "wave", "say": "Всем привет!", "emotion": "happy"},
                    {"who": "barsik", "do": "jump", "amount": 0.9, "with": "prev"},
                    {"who": "rex", "do": "run", "to": "barsik", "emotion": "excited"},
                    {"who": "all", "do": "clap", "seconds": 1.2},
                    {"effect": "fireworks", "with": "prev", "amount": "lots"},
                    {"camera": "punch", "focus": "masha"},
                ],
                "transition": "iris",
            },
            {
                "background": {"preset": "beach", "time": "sunset", "weather": "rain"},
                "place": {"masha": {"x": 0.3}, "rex": {"x": 0.55}, "pingu": {"x": 0.8, "lane": "front"}},
                "props": [
                    {"id": "umb", "kind": "umbrella", "x": 0.15, "size": 0.3, "color": "#ff5d8f"},
                    {"id": "ice", "kind": "ice_cream", "x": 0.45, "size": 0.1},
                ],
                "effects": [{"kind": "bubbles", "at": 0.5, "seconds": 2.5}, {"kind": "leaves", "amount": "few"}],
                "beats": [
                    {"who": "pingu", "do": "appear", "emotion": "surprised", "mark": "exclaim"},
                    {"effect": "poof", "with": "prev"},
                    {"who": "pingu", "do": "grow", "amount": 0.4},
                    {"who": "masha", "do": "shrink", "think": "Ого, какой большой!", "emotion": "scared"},
                    {"camera": "shake", "amount": 0.6, "with": "prev"},
                    {"who": "rex", "do": "spin", "amount": 1.0, "emotion": "dizzy"},
                ],
                "transition": "wipe",
            },
            {
                "background": {"preset": "stage", "time": "evening", "text": "КОНЦЕРТ"},
                "camera": {"move": "zoom_in", "focus": "stella", "amount": 0.5},
                "place": {"stella": {"x": 0.5, "facing": "camera"}, "barsik": {"x": 0.25, "lane": "front"},
                          "masha": {"x": 0.78, "lane": "back"}},
                "props": [
                    {"id": "disco", "kind": "disco_ball", "x": 0.5, "y": 0.12, "size": 0.14, "anim": "spin"},
                    {"id": "mic", "kind": "microphone", "x": 0.6, "size": 0.2},
                    {"id": "gtr", "kind": "guitar", "x": 0.1, "size": 0.25},
                ],
                "effects": [{"kind": "music"}, {"kind": "confetti", "at": 1.0, "amount": "normal"}],
                "beats": [
                    {"who": "stella", "do": "dance", "style": "disco", "shout": "Ля-ля-ля!", "emotion": "excited"},
                    {"who": "barsik", "do": "float", "with": "prev", "emotion": "love", "mark": "music"},
                    {"who": "masha", "do": "dance", "style": "sway", "with": "prev"},
                    {"camera": "zoom_out", "amount": 0.4},
                ],
                "transition": "slide",
            },
            {
                "background": {"preset": "underwater", "time": "night"},
                "camera": {"move": "zoom_out", "amount": 0.3},
                "place": {"stella": {"x": 0.3}, "pingu": {"x": 0.7}},
                "props": [{"id": "gem", "kind": "gem", "x": 0.5, "y": 0.3, "size": 0.12, "material": "glass"}],
                "title": {"text": "КОНЕЦ", "style": "candy3d", "anim": "spin"},
                "effects": [{"kind": "flash"}, {"kind": "hearts", "amount": "lots"}],
                "beats": [
                    {"who": "all", "do": "bow"},
                    {"who": "stella", "do": "poof", "whisper": "Пока!"},
                    {"who": "pingu", "do": "walk_out", "from": "right"},
                ],
                "transition": "flash",
            },
        ],
    },
}
