"""Поиск обращения «Стелла» в расшифровке: Whisper часто пишет Стела/Стэлла/Эстелла/Стеллу."""
import difflib
import re

NAME = "стела"
STOP = {"стена", "стены", "стене", "стену", "степь", "стелька", "стекло", "стелет", "сталь", "стала", "стали"}
_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё]+")


def _norm(w: str) -> str:
    w = w.lower().replace("э", "е").replace("ё", "е")
    w = re.sub(r"(.)\1+", r"\1", w)          # ллл -> л
    for a, b in (("stel", "стел"), ("estel", "стел"), ("эстел", "стел")):
        w = w.replace(a, b)
    return w.replace("a", "а")


def _is_name(tok: str) -> bool:
    n = _norm(tok)
    if n in STOP or len(n) < 4:
        return False
    if n.startswith(("стел", "естел")):
        return True
    return difflib.SequenceMatcher(None, n, NAME).ratio() >= 0.8


def split(text: str):
    """(есть_обращение, команда без имени). Имя ищем среди первых трёх и последних двух слов."""
    toks = list(_TOKEN.finditer(text))
    cand = toks[:3] + toks[-2:]
    for t in cand:
        if _is_name(t.group()):
            rest = (text[:t.start()] + " " + text[t.end():]).strip(" ,.!?-:;")
            return True, re.sub(r"\s+", " ", rest)
    return False, text.strip()
