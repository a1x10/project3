"""Превращаем ответ модели в «живые» сообщения: короткие пузыри, стикеры, реакции, редкие опечатки."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

SILENCE_MARKERS = ("<молчу>", "<silence>", "[молчу]")

_STICKER_RE = re.compile(r"\[\s*(?:стикер|sticker)\s*[:：]\s*([^\]]+?)\s*\]", re.IGNORECASE)
_REACTION_RE = re.compile(r"\[\s*(?:реакция|reaction|react)\s*[:：]\s*([^\]]+?)\s*\]", re.IGNORECASE)
_TOKEN_RE = re.compile(r"(\[\s*(?:стикер|sticker|реакция|reaction|react)\s*[:：][^\]]*\])", re.IGNORECASE)
# То, чем модель иногда «подписывает» реплику, копируя формат лога
_PREFIX_RE = re.compile(r"^\s*(?:★\s*)?(?:\[\d{1,2}:\d{2}\]\s*)?(?:стелла|stella)\s*(?:\[[^\]]*\])?\s*:\s*", re.IGNORECASE)
_MD_RE = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"__(.+?)__"), r"\1"),
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),
    (re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+", re.MULTILINE), ""),
    (re.compile(r"`([^`]*)`"), r"\1"),
]


@dataclass
class Segment:
    kind: str  # text | sticker | reaction
    value: str


def is_silence(text: str) -> bool:
    t = text.strip().lower()
    return not t or any(t.startswith(m) or t == m.strip("<>[]") for m in SILENCE_MARKERS)


def _clean_line(line: str) -> str:
    for rx, repl in _MD_RE:
        line = rx.sub(repl, line)
    line = _PREFIX_RE.sub("", line)
    for m in SILENCE_MARKERS:
        line = line.replace(m, "")
    return line.strip()


def _split_long(line: str, limit: int = 260) -> list[str]:
    if len(line) <= limit:
        return [line]
    parts: list[str] = []
    buf = ""
    for sentence in re.split(r"(?<=[.!?…])\s+", line):
        if buf and len(buf) + len(sentence) + 1 > limit * 0.6:
            parts.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf:
        parts.append(buf)
    return parts


def parse_reply(text: str, max_bubbles: int = 6) -> list[Segment]:
    """Строки -> отдельные сообщения; [стикер: x] и [реакция: 😂] -> действия."""
    if is_silence(text):
        return []
    segments: list[Segment] = []
    for raw_line in text.replace("\r", "").split("\n"):
        for piece in _TOKEN_RE.split(raw_line):
            if not piece.strip():
                continue
            if m := _STICKER_RE.fullmatch(piece.strip()):
                segments.append(Segment("sticker", m.group(1).strip().lower()))
                continue
            if m := _REACTION_RE.fullmatch(piece.strip()):
                emoji = m.group(1).strip()
                if emoji and not any(s.kind == "reaction" for s in segments):
                    segments.append(Segment("reaction", emoji[:8]))
                continue
            line = _clean_line(piece)
            if line:
                segments.extend(Segment("text", p) for p in _split_long(line))
    # Не больше max_bubbles текстовых пузырей (хвост склеиваем) и не больше одного стикера
    result: list[Segment] = []
    tail: Segment | None = None
    n_text = 0
    seen_sticker = False
    for s in segments:
        if s.kind == "text":
            n_text += 1
            if n_text >= max_bubbles:
                if tail is None:
                    tail = Segment("text", s.value)
                    result.append(tail)
                else:
                    tail.value += " " + s.value
                continue
        elif s.kind == "sticker":
            if seen_sticker:
                continue
            seen_sticker = True
        result.append(s)
    return result


# ---------- опечатки ----------
_KEYBOARD_ROWS = ["йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю"]
_NEIGHBORS: dict[str, str] = {}
for _row in _KEYBOARD_ROWS:
    for _i, _ch in enumerate(_row):
        _NEIGHBORS[_ch] = (_row[_i - 1] if _i > 0 else "") + (_row[_i + 1] if _i + 1 < len(_row) else "")

_WORD_RE = re.compile(r"[А-Яа-яЁё]{5,}")


def _typo_word(word: str, rng: random.Random) -> str:
    i = rng.randrange(1, len(word) - 1)
    kind = rng.random()
    if kind < 0.35:  # переставить соседние буквы
        return word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    if kind < 0.6:  # пропустить букву
        return word[:i] + word[i + 1 :]
    if kind < 0.8:  # промахнуться по соседней клавише
        ch = word[i].lower()
        options = _NEIGHBORS.get(ch, "")
        if options:
            new = rng.choice(options)
            new = new.upper() if word[i].isupper() else new
            return word[:i] + new + word[i + 1 :]
    return word[:i] + word[i] + word[i:]  # двойная буква


def add_typo(text: str, rng: random.Random, rate: float, protect: set[str] | None = None) -> tuple[str, str | None]:
    """С вероятностью rate портим одно слово. Возвращает (текст, исправление «*слово» или None)."""
    if rate <= 0 or rng.random() >= rate:
        return text, None
    protect = {p.lower() for p in (protect or set())}
    words = [m for m in _WORD_RE.finditer(text) if m.group(0).lower() not in protect and not m.group(0)[0].isupper()]
    if not words:
        return text, None
    m = rng.choice(words)
    broken = _typo_word(m.group(0), rng)
    if broken == m.group(0):
        return text, None
    return text[: m.start()] + broken + text[m.end() :], "*" + m.group(0)


def casualize(text: str, rng: random.Random) -> str:
    """Как пишут в чатах: точку в конце одиночного сообщения обычно не ставят."""
    if text.endswith(".") and not text.endswith("..") and rng.random() < 0.85:
        text = text[:-1]
    return text


def typing_ms(text: str, rng: random.Random, chars_per_sec: float) -> int:
    """Сколько «печатать» сообщение: по длине, с разбросом, в разумных пределах."""
    if chars_per_sec <= 0:
        return 0
    speed = chars_per_sec * rng.uniform(0.75, 1.3)
    seconds = len(text) / speed + rng.uniform(0.3, 1.0)
    return int(min(max(seconds, 0.9), 9.0) * 1000)
