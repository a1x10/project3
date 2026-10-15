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
    "ечка", "ечке", "ечку", "юша", "юшка", "ик", "я", "ей", "ька", "ьки", "ьке", "ьку", "ькой",
    "чка", "чки", "чке", "чку", "уля", "уся", "ус", "ушка", "аа", "ааа", "ах",
)
_LATIN = {"stella", "stela", "stells", "stels", "stellka", "stelka", "stel", "stelll"}
# латинские буквы, которые выглядят как русские: «Cтелла» с английской C
_HOMOGLYPHS = str.maketrans({"a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "k": "к",
                             "m": "м", "t": "т", "h": "н", "b": "в"})
_CYR = re.compile(r"[а-яё]")
_LAT = re.compile(r"[a-z]")


def name_stems(bot_name: str) -> list[str]:
    """«Стелла» -> стемы «стелл», «стел», «стэлл» (ловит стелла/стел/стеллочка, но не «стеллаж»)."""
    n = norm(bot_name)
    base = n[:-1] if n.endswith(("а", "я")) else n
    stems = {base}
    if base.endswith("лл"):
        stems.add(base[:-1])
    stems |= {s.replace("е", "э") for s in list(stems)}
    return sorted(stems, key=len, reverse=True)


def _fix_mixed(word: str) -> str:
    if _CYR.search(word) and _LAT.search(word):
        return word.translate(_HOMOGLYPHS)
    return word


def mentions_name(text: str, stems: list[str]) -> bool:
    for word in _WORD.findall(norm(text)):
        word = _fix_mixed(word)
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
    bot_spoke_recently: bool = False,
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
    # она только что говорила в чате, и кто-то другой спрашивает «а ты…?» — возможно, ей (модель решит сама)
    if bot_spoke_recently and not addressed_elsewhere and inc.text and looks_like_question_to_her(inc.text):
        return CONTINUE
    return AMBIENT


_TO_HER = re.compile(r"(^|[^а-яё])(ты|тебя|тебе|тобой|твой|твоя|твое|твои|твою|твоего|сама)([^а-яё]|$)")


def looks_like_question_to_her(text: str) -> bool:
    t = norm(text)
    return bool(_TO_HER.search(t)) or t.rstrip(" )!").endswith("?")


ARGUMENT_MARKERS = re.compile(
    r"(кто прав|спор|поспорим|как думаете|ваше мнение|народ|ребят|девочки|пацаны|кто знает|подскажите|а вы|\?$)",
    re.IGNORECASE,
)


def looks_like_open_question(text: str) -> bool:
    return bool(ARGUMENT_MARKERS.search(text.strip()))
