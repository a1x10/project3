"""Поиск обращения «Стелла» в расшифровке.
Сильные варианты (Стела/Эстелла/Стеллу…) ловим среди первых трёх и последних двух слов.
Слабые (стала, стол, что, сто… — так Whisper часто слышит имя) — только как ПЕРВОЕ слово, и решение
о том, что обращались к ней, принимает мозг (см. agent.ask(weak=True))."""
import difflib
import re

from . import config

NAME = "стела"
STOP = {"стена", "стены", "стене", "стену", "степь", "стелька", "стекло", "стелет", "сталь"}
FILLERS = {"эй", "ну", "окей", "ок", "слушай", "привет", "хей", "hey", "ok", "эм", "так"}
# слабые варианты (нормализованные: э->е, ё->е, повторы букв схлопнуты)
WEAK_EXACT = {"стала", "стало", "стоило", "стола", "тела", "столу", "сто", "столов", "устава", "стал", "стрелой",
              "столах", "стен", "стол", "столба", "стрела", "что", "стрелу", "столы", "стали"}
WEAK_PREFIX = ("стол", "стал", "стрел", "стен", "сто ")
_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё]+")


def _norm(w: str) -> str:
    w = w.lower().replace("э", "е").replace("ё", "е")
    w = re.sub(r"(.)\1+", r"\1", w)
    for a, b in (("stel", "стел"), ("estel", "стел"), ("эстел", "стел")):
        w = w.replace(a, b)
    return w.replace("a", "а")


_FILLERS = None


def _is_weak(n: str) -> bool:
    return n in WEAK_EXACT or n.startswith(WEAK_PREFIX[:4])


def _is_name(tok: str) -> bool:
    n = _norm(tok)
    if n in STOP or len(n) < 4 or _is_weak(n):     # «стала», «стол»… — только слабым путём
        return False
    if n.startswith(("стел", "естел")):
        return True
    return difflib.SequenceMatcher(None, n, NAME).ratio() >= 0.8


_FILLERS = {_norm(w) for w in FILLERS}


def split(text: str):
    """(уровень, команда): 0 — не к ней, 1 — обратились, 2 — возможно обратились (слабый вариант)."""
    toks = list(_TOKEN.finditer(text))
    for t in toks[:3] + toks[-2:]:
        if _is_name(t.group()):
            rest = (text[:t.start()] + " " + text[t.end():]).strip(" ,.!?-:;")
            return 1, re.sub(r"\s+", " ", rest)
    if config.WAKE_WEAK and toks:
        i = 0
        while i < len(toks) - 1 and _norm(toks[i].group()) in _FILLERS:
            i += 1
        first = _norm(toks[i].group())
        two = first + " " + _norm(toks[i + 1].group()) if i + 1 < len(toks) else ""
        if _is_weak(first) or two in ("из целое", "из целого", "изцелое"):
            return 2, text.strip()          # целиком: слово «что» может быть и началом вопроса
    return 0, text.strip()
