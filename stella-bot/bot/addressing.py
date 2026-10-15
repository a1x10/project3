"""Понимаем, обращаются ли к Стелле, без вызова модели.

direct   — точно к ней: личка, имя, @упоминание, ответ на её сообщение
continue — похоже на продолжение разговора с ней (модель может промолчать)
ambient  — обычный разговор в группе (Стелла может сама вписаться, если есть что сказать)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parser import Incoming
from .util import jid_digits, norm

DIRECT = "direct"
CONTINUE = "continue"
AMBIENT = "ambient"

_WORD = re.compile(r"[a-zа-яё]+", re.IGNORECASE)
_SUFFIXES = (
    "", "а", "ы", "е", "у", "ой", "ою", "очка", "очки", "очке", "очку", "очкой", "ка", "ки", "ке", "ку", "кой",
    "ечка", "ечке", "ечку", "юша", "юшка", "ик",
)
_LATIN = {"stella", "stela", "stells", "stels", "stellka"}


def name_stems(bot_name: str) -> list[str]:
    """«Стелла» -> стемы «стелл», «стел», «стэлл» (ловит стелла/стел/стеллочка, но не «стеллаж»)."""
    n = norm(bot_name)
    base = n[:-1] if n.endswith(("а", "я")) else n
    stems = {base}
    if base.endswith("лл"):
        stems.add(base[:-1])
    stems |= {s.replace("е", "э") for s in list(stems)}
    return sorted(stems, key=len, reverse=True)


def mentions_name(text: str, stems: list[str]) -> bool:
    for word in _WORD.findall(norm(text)):
        if word in _LATIN:
            return True
        for stem in stems:
            if word.startswith(stem) and word[len(stem):] in _SUFFIXES:
                return True
    return False


def strip_name_prefix(text: str, stems: list[str]) -> tuple[bool, str]:
    """«Стелла, красное 500» -> (True, «красное 500»)."""
    m = re.match(r"^\s*@?([a-zа-яё]+)[\s,!:.\-—]*(.*)$", text, re.IGNORECASE | re.DOTALL)
    if m and mentions_name(m.group(1), stems):
        return True, m.group(2).strip()
    return False, text.strip()


@dataclass
class BotIdentity:
    jids: set[str]  # номер и LID бота

    def digits(self) -> set[str]:
        return {jid_digits(j) for j in self.jids if j}


def classify(
    inc: Incoming,
    *,
    stems: list[str],
    bot: BotIdentity,
    quoted_is_bot: bool,
    talking_with_sender: bool,
) -> str:
    if inc.is_dm:
        return DIRECT
    if quoted_is_bot:
        return DIRECT
    bot_digits = bot.digits()
    if any(jid_digits(j) in bot_digits for j in inc.mentioned):
        return DIRECT
    if bot_digits and any(f"@{d}" in inc.text for d in bot_digits if d):
        return DIRECT
    if inc.text and mentions_name(inc.text, stems):
        return DIRECT
    addressed_elsewhere = bool(inc.mentioned) or (inc.quoted_id is not None)
    if talking_with_sender and not addressed_elsewhere:
        return CONTINUE
    return AMBIENT


ARGUMENT_MARKERS = re.compile(
    r"(кто прав|спор|поспорим|как думаете|ваше мнение|народ|ребят|девочки|пацаны|кто знает|подскажите|а вы|\?$)",
    re.IGNORECASE,
)


def looks_like_open_question(text: str) -> bool:
    return bool(ARGUMENT_MARKERS.search(text.strip()))
