"""Русские числительные -> цифры.

Vosk отдаёт текст словами («поставь таймер на двадцать пять минут»),
а навыкам удобнее работать с цифрами («... на 25 минут»).

    >>> normalize_numbers("разбуди меня в семь тридцать")
    'разбуди меня в 7 30'
    >>> normalize_numbers("сколько будет две тысячи двадцать шесть плюс полтора")
    'сколько будет 2026 плюс 1.5'
    >>> normalize_numbers("три целых пять десятых")
    '3.5'
    >>> normalize_numbers("двадцать пятого октября")
    '25 октября'
"""
from __future__ import annotations

import re

# --- количественные --------------------------------------------------------
_UNITS = {
    "ноль": 0, "нуль": 0, "нуля": 0,
    "один": 1, "одна": 1, "одно": 1, "одну": 1, "одного": 1, "одной": 1, "одному": 1,
    "два": 2, "две": 2, "двух": 2, "двум": 2, "двумя": 2,
    "три": 3, "трех": 3, "трем": 3, "тремя": 3,
    "четыре": 4, "четырех": 4, "четырем": 4, "четырьмя": 4,
    "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6, "шестью": 6,
    "семь": 7, "семи": 7,  # «семью» не берём: чаще это «семья»
    "восемь": 8, "восьми": 8, "восемью": 8, "восьмью": 8,
    "девять": 9, "девяти": 9, "девятью": 9,
}
_TEENS = {
    "десять": 10, "десяти": 10, "десятью": 10,
    "одиннадцать": 11, "одиннадцати": 11,
    "двенадцать": 12, "двенадцати": 12,
    "тринадцать": 13, "тринадцати": 13,
    "четырнадцать": 14, "четырнадцати": 14,
    "пятнадцать": 15, "пятнадцати": 15,
    "шестнадцать": 16, "шестнадцати": 16,
    "семнадцать": 17, "семнадцати": 17,
    "восемнадцать": 18, "восемнадцати": 18,
    "девятнадцать": 19, "девятнадцати": 19,
}
_TENS = {
    "двадцать": 20, "двадцати": 20, "двадцатью": 20,
    "тридцать": 30, "тридцати": 30, "тридцатью": 30,
    "сорок": 40, "сорока": 40,
    "пятьдесят": 50, "пятидесяти": 50,
    "шестьдесят": 60, "шестидесяти": 60,
    "семьдесят": 70, "семидесяти": 70,
    "восемьдесят": 80, "восьмидесяти": 80,
    "девяносто": 90, "девяноста": 90,
}
_HUNDREDS = {
    "сто": 100, "ста": 100, "сотни": 100, "сотню": 100,
    "двести": 200, "двухсот": 200,
    "триста": 300, "трехсот": 300,
    "четыреста": 400, "четырехсот": 400,
    "пятьсот": 500, "пятисот": 500,
    "шестьсот": 600, "шестисот": 600,
    "семьсот": 700, "семисот": 700,
    "восемьсот": 800, "восьмисот": 800,
    "девятьсот": 900, "девятисот": 900,
}
_MULT = {}
for _forms, _val in (
    (("тысяча", "тысячи", "тысяч", "тысячу", "тысячей", "тыща", "тыщи", "тыщ", "тыщу"), 10 ** 3),
    (("миллион", "миллиона", "миллионов", "миллионом", "лям", "ляма", "лямов"), 10 ** 6),
    (("миллиард", "миллиарда", "миллиардов", "миллиардом"), 10 ** 9),
    (("триллион", "триллиона", "триллионов"), 10 ** 12),
):
    for _f in _forms:
        _MULT[_f] = _val

_SPECIAL = {"полтора": 1.5, "полторы": 1.5, "полутора": 1.5, "полтораста": 150, "пара": 2, "пару": 2}

# --- порядковые («двадцать пятого», «третье») -------------------------------
_ORD_STEMS = {
    "перв": 1, "втор": 2, "трет": 3, "четверт": 4, "пят": 5, "шест": 6, "седьм": 7,
    "восьм": 8, "девят": 9, "десят": 10, "одиннадцат": 11, "двенадцат": 12,
    "тринадцат": 13, "четырнадцат": 14, "пятнадцат": 15, "шестнадцат": 16,
    "семнадцат": 17, "восемнадцат": 18, "девятнадцат": 19, "двадцат": 20,
    "тридцат": 30, "сороков": 40, "пятидесят": 50, "шестидесят": 60,
    "семидесят": 70, "восьмидесят": 80, "девяност": 90, "сот": 100,
}
_ORD_ENDINGS = ("ый", "ой", "ий", "ое", "ее", "ого", "его", "ому", "ему", "ая", "яя", "ую", "юю",
                "ые", "ие", "ых", "их", "ым", "им", "ыми", "ими", "ом", "ем", "ей")
_ORD_THIRD = ("третий", "третье", "третьего", "третьему", "третья", "третью", "третьей",
              "третьи", "третьих", "третьим", "третьими", "третьем")
_ORDINALS: dict[str, int] = {}
for _stem, _val in _ORD_STEMS.items():
    if _stem == "трет":
        continue
    for _end in _ORD_ENDINGS:
        _ORDINALS[_stem + _end] = _val
for _f in _ORD_THIRD:
    _ORDINALS[_f] = 3
# слова, которые случайно совпали с формами порядковых, но ими не являются
for _bad in ("пятой", "сотом", "стой"):
    _ORDINALS.pop(_bad, None)

_PUNCT = ".,!?;:«»\"()…"


def _classify(word: str):
    """-> (класс, значение, порядковое?) или None."""
    if word in _UNITS:
        return "u", _UNITS[word], False
    if word in _TEENS:
        return "teen", _TEENS[word], False
    if word in _TENS:
        return "t", _TENS[word], False
    if word in _HUNDREDS:
        return "h", _HUNDREDS[word], False
    if word in _MULT:
        return "m", _MULT[word], False
    if word in _ORDINALS:
        v = _ORDINALS[word]
        cls = "u" if v < 10 else "teen" if v < 20 else "t" if v < 100 else "h"
        return cls, v, True
    return None


class _Number:
    """Накопитель одного числа: «две тысячи двадцать шесть» -> 2026."""

    def __init__(self):
        self.total = 0
        self.group = 0
        self.last = None
        self.words = 0
        self.mults: list[int] = []

    def can_take(self, cls: str, val: int) -> bool:
        if self.words == 0:
            return True
        if self.last == "zero":
            return False
        if cls == "h":
            return self.group == 0 and self.last in (None, "m")
        if cls in ("t", "teen"):
            return self.group % 100 == 0 and self.last in (None, "h", "m")
        if cls == "u":
            if val == 0:
                return False
            return self.group % 10 == 0 and self.last in (None, "h", "t", "m")
        if cls == "m":
            return self.last != "m" and (not self.mults or val < min(self.mults))
        return False

    def take(self, cls: str, val: int):
        if cls == "m":
            self.total += (self.group or 1) * val
            self.group = 0
            self.mults.append(val)
        else:
            self.group += val
        self.last = "zero" if (cls == "u" and val == 0) else cls
        self.words += 1

    def value(self) -> int:
        return self.total + self.group


def _fmt(v) -> str:
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return ("%.6f" % v).rstrip("0").rstrip(".")
    return str(v)


def _split_punct(tok: str):
    core = tok.strip(_PUNCT)
    if not core:
        return tok, "", ""
    i = tok.index(core)
    return tok[:i], core, tok[i + len(core):]


def _cardinal_pass(text: str) -> str:
    """Количественные числительные -> цифры (одна группа слов -> одно число)."""
    out: list[str] = []
    cur: _Number | None = None
    pending_space = False

    def flush(space_after: bool):
        nonlocal cur, pending_space
        if cur is not None:
            out.append(_fmt(cur.value()))
            if space_after and pending_space:
                out.append(" ")
            cur = None
        pending_space = False

    for tok in re.split(r"(\s+)", text):
        if not tok:
            continue
        if tok.isspace():
            if cur is None:
                out.append(tok)
            else:
                pending_space = True
            continue
        lead, core, trail = _split_punct(tok)
        if lead:
            flush(True)
            out.append(lead)
        if core in _SPECIAL:
            flush(True)
            out.append(_fmt(_SPECIAL[core]) + trail)
            continue
        info = _classify(core)
        if info is None or info[2]:  # не число или порядковое (их обрабатываем отдельно)
            flush(True)
            out.append(core + trail)
            continue
        cls, val, _ = info
        if cur is not None and not cur.can_take(cls, val):
            flush(True)
        if cur is None:
            cur = _Number()
        cur.take(cls, val)
        pending_space = False
        if trail:
            out.append(_fmt(cur.value()) + trail)
            cur = None
    flush(False)
    return "".join(out)


def _ordinal_pass(text: str) -> str:
    """Порядковые -> цифры, «20 пятого» (после первого прохода) -> «25»."""
    out: list[str] = []
    for tok in re.split(r"(\s+)", text):
        if not tok:
            continue
        if tok.isspace():
            out.append(tok)
            continue
        lead, core, trail = _split_punct(tok)
        if core not in _ORDINALS:
            out.append(tok)
            continue
        val = _ORDINALS[core]
        # ищем предыдущее число, к которому можно «прицепить» порядковое
        j = len(out) - 1
        while j >= 0 and out[j].isspace():
            j -= 1
        if not lead and j >= 0 and re.fullmatch(r"\d+", out[j]):
            prev = int(out[j])
            free = 1000 if prev % 1000 == 0 else 100 if prev % 100 == 0 else 10 if prev % 10 == 0 else 0
            if prev and val < free:
                del out[j:]
                out.append(str(prev + val) + trail)
                continue
        out.append(lead + str(val) + trail)
    return "".join(out)


_DEC_DENOM = {"десят": 10, "сот": 100, "тысячн": 1000}


def _decimals_pass(text: str) -> str:
    def repl_whole(m):
        whole, frac, denom = m.group(1), m.group(2), m.group(3)
        d = next(v for k, v in _DEC_DENOM.items() if denom.startswith(k))
        return _fmt(int(whole) + int(frac) / d)

    text = re.sub(r"\b(\d+) (?:целых|целая|целой|и) (\d+) (десят\w*|сот\w*|тысячн\w*)", repl_whole, text)
    text = re.sub(r"\b(\d+) (?:запятая|точка) (\d+)\b", lambda m: f"{m.group(1)}.{m.group(2)}", text)
    return text


def normalize_numbers(text: str, ordinals: bool = True) -> str:
    """Заменяет числительные словами на цифры. Регистр текста приводится к нижнему."""
    if not text:
        return ""
    text = text.lower().replace("ё", "е")
    text = _cardinal_pass(text)
    text = _decimals_pass(text)
    if ordinals:
        text = _ordinal_pass(text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def words_to_number(text: str):
    """Первое число в строке (int/float) или None. Понимает и цифры, и слова."""
    t = normalize_numbers(text)
    m = re.search(r"-?\d+(?:[.,]\d+)?", t)
    if not m:
        return None
    s = m.group(0).replace(",", ".")
    return float(s) if "." in s else int(s)


_SMALL = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
          "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
          "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]


def plural(n, one: str, few: str, many: str) -> str:
    """plural(5, 'минута', 'минуты', 'минут') -> 'минут'."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def fmt_num(x, digits: int = 2) -> str:
    """Красиво для озвучки: 3.0 -> '3', 2.50 -> '2,5', 1234567 -> '1 234 567'."""
    if isinstance(x, float):
        if abs(x) >= 1e15 or (x != 0 and abs(x) < 10 ** (-digits)):
            return ("%.4g" % x).replace(".", ",")
        x = round(x, digits)
        if x.is_integer():
            x = int(x)
    if isinstance(x, int):
        return f"{x:,}".replace(",", " ")
    s = f"{x:,.{digits}f}".rstrip("0").rstrip(".")
    return s.replace(",", " ").replace(".", ",")
