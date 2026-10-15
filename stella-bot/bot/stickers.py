"""Библиотека стикеров.

data/stickers/<настроение>/*.webp|png — стикеры по настроениям (папка = настроение).
data/stickers/_collected/ — стикеры, которые Стелла «утащила» из чатов (настроение «любой»).
Если библиотека пустая, при старте рисуется стартовый набор текстовых стикеров.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import random
from collections import deque
from pathlib import Path

from .db import DB

log = logging.getLogger("stella.stickers")

ANY_MOOD = "любой"
COLLECTED_DIR = "_collected"

# Синонимы, чтобы «[стикер: смешно]» нашёл папку «смех»
SYNONYMS = {
    "смех": ["смешно", "ржу", "ору", "лол", "хаха", "угар", "ахаха", "funny", "lol", "laugh"],
    "любовь": ["люблю", "обнимаю", "сердечко", "мило", "нежность", "love", "hug", "обнимашки"],
    "шок": ["удивление", "в шоке", "что", "чтооо", "офигеть", "wow", "shock"],
    "грусть": ["грустно", "печаль", "плачу", "sad", "эх"],
    "злость": ["бесит", "злюсь", "ярость", "angry"],
    "думаю": ["хмм", "задумалась", "сомнение", "think"],
    "привет": ["хай", "здарова", "hello", "hi"],
    "пока": ["спокойной ночи", "ночи", "bye", "сплю"],
    "победа": ["ура", "джекпот", "красава", "win", "богатство", "радость"],
    "проигрыш": ["казино", "минус", "банкрот", "lose"],
    "поддержка": ["держись", "ты справишься", "я рядом", "support"],
    "кринж": ["стыд", "фейспалм", "facepalm", "cringe"],
    "согласна": ["база", "факт", "да", "yes", "agree"],
    "ок": ["окей", "принято", "ладно", "ok"],
}

# Стартовый набор: настроение -> надписи
STARTER = {
    "смех": ["АХАХАХ", "ОРУ", "я плачу 😭"],
    "любовь": ["люблю вас", "обнимаю"],
    "шок": ["ЧТООО", "в смысле"],
    "грусть": ["ну всё", "грустненько"],
    "злость": ["БЕСИТ"],
    "думаю": ["хмм...", "ну такое"],
    "привет": ["ПРИВЕТ", "хай"],
    "пока": ["спокойной ночи", "пока-пока"],
    "победа": ["КРАСАВА", "ДЖЕКПОТ"],
    "проигрыш": ["казино всегда побеждает", "минус бананы"],
    "поддержка": ["ты справишься", "я рядом"],
    "кринж": ["КРИНЖ"],
    "согласна": ["база", "факт"],
    "ок": ["ок", "принято"],
}
COLORS = ["#ff6b9d", "#7c5cff", "#2ec4b6", "#ff9f1c", "#3a86ff", "#ef476f", "#06d6a0", "#8338ec"]
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class StickerLibrary:
    def __init__(self, db: DB, root: str, rng: random.Random | None = None):
        self.db = db
        self.root = Path(root)
        self.rng = rng or random.Random()
        self._recent: dict[str, deque[int]] = {}

    async def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / COLLECTED_DIR).mkdir(exist_ok=True)
        has_any = any(p.is_file() for d in self.root.iterdir() if d.is_dir() and d.name != COLLECTED_DIR for p in d.iterdir())
        if not has_any:
            try:
                self._draw_starter_pack()
            except Exception:  # шрифта нет или Pillow не умеет webp — без стартового набора
                log.warning("не получилось нарисовать стартовые стикеры", exc_info=True)
        await self.scan()

    async def scan(self) -> int:
        """Подхватить файлы из папок (можно докидывать свои стикеры и перезапускать бота)."""
        added = 0
        for mood_dir in sorted(self.root.iterdir()):
            if not mood_dir.is_dir():
                continue
            mood = None if mood_dir.name == COLLECTED_DIR else mood_dir.name.lower()
            for f in sorted(mood_dir.iterdir()):
                if f.suffix.lower() not in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
                    continue
                digest = sha256(f.read_bytes())
                source = "collected" if mood is None else "pack"
                if await self.db.add_sticker(digest, str(f), mood, source):
                    added += 1
        if added:
            log.info("стикеров добавлено в библиотеку: %d", added)
        return added

    async def moods(self) -> list[str]:
        moods = await self.db.sticker_moods()
        if await self.db.count_stickers("collected"):
            moods.append(ANY_MOOD)
        return moods

    def _resolve(self, wanted: str, moods: list[str]) -> str | None:
        w = wanted.strip().lower()
        if not w:
            return None
        if w in moods:
            return w
        for mood, words in SYNONYMS.items():
            if mood in moods and (w == mood or w in words or any(x in w for x in words if len(x) > 3)):
                return mood
        for m in moods:
            if m.startswith(w[:4]) or w.startswith(m[:4]):
                return m
        return None

    async def pick(self, chat_key: str, wanted: str) -> tuple[int, bytes] | None:
        moods = await self.moods()
        mood = self._resolve(wanted, moods)
        if mood is None:
            return None
        rows = await self.db.stickers_for_mood(None if mood == ANY_MOOD else mood)
        rows = [r for r in rows if os.path.exists(r["path"])]
        if not rows:
            return None
        recent = self._recent.setdefault(chat_key, deque(maxlen=6))
        fresh = [r for r in rows if r["id"] not in recent] or rows
        row = self.rng.choice(fresh)
        recent.append(row["id"])
        await self.db.bump_sticker(row["id"])
        return row["id"], Path(row["path"]).read_bytes()

    @staticmethod
    def to_b64(data: bytes) -> str:
        return base64.b64encode(data).decode()

    async def collect(self, data: bytes, wa_message_id: str, limit: int) -> bool:
        """Сохранить чужой стикер в «утащенные»."""
        digest = sha256(data)
        if await self.db.sticker_by_sha(digest):
            return False
        if await self.db.count_stickers("collected") >= limit:
            return False
        path = self.root / COLLECTED_DIR / f"{digest[:16]}.webp"
        path.write_bytes(data)
        return await self.db.add_sticker(digest, str(path), None, "collected", wa_message_id)

    async def learn(self, data: bytes, mood: str, wa_message_id: str | None) -> str:
        """«стелла запомни стикер смех» ответом на стикер."""
        mood = mood.strip().lower()[:40]
        digest = sha256(data)
        existing = await self.db.sticker_by_sha(digest)
        folder = self.root / mood
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{digest[:16]}.webp"
        path.write_bytes(data)
        if existing:
            await self.db.set_sticker_mood(existing["id"], mood)
            return "updated"
        await self.db.add_sticker(digest, str(path), mood, "learned", wa_message_id)
        return "added"

    # ---------- стартовый набор ----------
    def _draw_starter_pack(self) -> None:
        from PIL import Image, ImageDraw, ImageFont

        font_path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
        if not font_path:
            raise FileNotFoundError("нет шрифта DejaVuSans-Bold")
        rng = random.Random(42)
        for mood, phrases in STARTER.items():
            folder = self.root / mood
            folder.mkdir(parents=True, exist_ok=True)
            for i, phrase in enumerate(phrases):
                text = phrase.replace(" 😭", "")
                img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                size = 120 if len(text) <= 6 else 92 if len(text) <= 10 else 64
                font = ImageFont.truetype(font_path, size)
                words = text.split()
                lines: list[str] = []
                for w in words:
                    if lines and draw.textlength(lines[-1] + " " + w, font=font) < 420:
                        lines[-1] += " " + w
                    else:
                        lines.append(w)
                while max(draw.textlength(line, font=font) for line in lines) > 430 and size > 40:
                    size -= 6
                    font = ImageFont.truetype(font_path, size)
                line_h = size * 1.15
                total_h = line_h * len(lines)
                color = rng.choice(COLORS)
                pad = 36
                width = max(draw.textlength(line, font=font) for line in lines)
                box = (256 - width / 2 - pad, 256 - total_h / 2 - pad, 256 + width / 2 + pad, 256 + total_h / 2 + pad)
                draw.rounded_rectangle(box, radius=48, fill=color, outline="white", width=10)
                y = 256 - total_h / 2
                for line in lines:
                    w = draw.textlength(line, font=font)
                    draw.text((256 - w / 2, y), line, font=font, fill="white", stroke_width=6, stroke_fill="#222222")
                    y += line_h
                img = img.rotate(rng.uniform(-7, 7), resample=Image.BICUBIC, expand=False)
                img.save(folder / f"starter_{i + 1}.webp", "WEBP")
        log.info("нарисован стартовый набор стикеров в %s", self.root)
