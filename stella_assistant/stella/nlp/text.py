"""Нормализация текста, стемминг (Портер для русского) и нечёткое сравнение."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache

from .numbers import normalize_numbers

_PUNCT_RE = re.compile(r"[^\w\s:.+\-*/%^]", re.UNICODE)


def clean(text: str) -> str:
    """Нижний регистр, ё->е, без лишней пунктуации и пробелов."""
    text = (text or "").lower().replace("ё", "е")
    text = _PUNCT_RE.sub(" ", text)
    text = re.sub(r"(?<!\d)[.:](?!\d)", " ", text)  # точки/двоеточия только внутри чисел
    return re.sub(r"\s+", " ", text).strip()


def norm(text: str) -> str:
    """clean + числительные словами -> цифры. Это основной вид текста для навыков."""
    return clean(normalize_numbers(clean(text)))


def strip_words(text: str, *words: str) -> str:
    """Убирает из текста служебные слова/фразы (целиком)."""
    for w in sorted(words, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(w) + r"(?!\w)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- стеммер ---
_PERFECTIVE = re.compile(r"((ив|ивши|ившись|ыв|ывши|ывшись)|((?<=[ая])(в|вши|вшись)))$")
_REFLEXIVE = re.compile(r"(с[яь])$")
_ADJECTIVE = re.compile(r"(ее|ие|ые|ое|ими|ыми|ей|ий|ый|ой|ем|им|ым|ом|его|ого|ему|ому|их|ых|ую|юю|ая|яя|ою|ею)$")
_PARTICIPLE = re.compile(r"((ивш|ывш|ующ)|((?<=[ая])(ем|нн|вш|ющ|щ)))$")
_VERB = re.compile(r"((ила|ыла|ена|ейте|уйте|ите|или|ыли|ей|уй|ил|ыл|им|ым|ен|ило|ыло|ено|ят|ует|уют|ит|ыт|ены|ить|ыть|ишь|ую|ю)|((?<=[ая])(ла|на|ете|йте|ли|й|л|ем|н|ло|но|ет|ют|ны|ть|ешь|нно)))$")
_NOUN = re.compile(r"(а|ев|ов|ие|ье|е|иями|ями|ами|еи|ии|и|ией|ей|ой|ий|й|иям|ям|ием|ем|ам|ом|о|у|ах|иях|ях|ы|ь|ию|ью|ю|ия|ья|я)$")
_RVRE = re.compile(r"^(.*?[аеиоуыэюя])(.*)$")
_DERIVATIONAL = re.compile(r".*[^аеиоуыэюя]+[аеиоуыэюя].*ость?$")
_DER = re.compile(r"ость?$")
_SUPERLATIVE = re.compile(r"(ейше|ейш)$")


@lru_cache(maxsize=20000)
def stem(word: str) -> str:
    word = word.lower().replace("ё", "е")
    if not re.fullmatch(r"[а-я]+", word) or len(word) < 3:
        return word
    m = _RVRE.match(word)
    if not m:
        return word
    pre, rv = m.groups()
    temp = _PERFECTIVE.sub("", rv, 1)
    if temp == rv:
        rv = _REFLEXIVE.sub("", rv, 1)
        temp = _ADJECTIVE.sub("", rv, 1)
        if temp != rv:
            rv = _PARTICIPLE.sub("", temp, 1)
        else:
            temp = _VERB.sub("", rv, 1)
            rv = _NOUN.sub("", rv, 1) if temp == rv else temp
    else:
        rv = temp
    rv = re.sub(r"и$", "", rv)
    if _DERIVATIONAL.match(rv):
        rv = _DER.sub("", rv)
    temp = re.sub(r"ь$", "", rv)
    if temp == rv:
        rv = _SUPERLATIVE.sub("", rv)
        rv = re.sub(r"нн$", "н", rv)
    else:
        rv = temp
    return pre + rv


def stems(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"\w+", clean(text))]


def has_stem(text: str, *words: str) -> bool:
    """Есть ли в тексте слово с той же основой, что у любого из words."""
    st = set(stems(text))
    return any(stem(w) in st for w in words)


def similarity(a: str, b: str) -> float:
    """0..1: насколько строка a похожа на b (с учётом словоформ)."""
    a, b = clean(a), clean(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    sa, sb = set(stems(a)), set(stems(b))
    overlap = len(sa & sb) / max(1, len(sb))
    ratio = SequenceMatcher(None, " ".join(sorted(sa)), " ".join(sorted(sb))).ratio()
    return max(overlap * 0.95, ratio * 0.9)


def contains_phrase(text: str, phrase: str) -> bool:
    """Все слова фразы (по основам) встречаются в тексте."""
    st = set(stems(text))
    ps = stems(phrase)
    return bool(ps) and all(p in st for p in ps)


def best_match(query: str, candidates, key=lambda x: x, threshold: float = 0.6):
    """Лучший кандидат по similarity(query, key(c)); ищем и «название внутри фразы»."""
    best, best_score = None, 0.0
    for c in candidates:
        name = key(c)
        if not name:
            continue
        score = similarity(query, name)
        if contains_phrase(query, name):
            score = max(score, 0.85 + 0.01 * min(10, len(stems(name))))
        if score > best_score:
            best, best_score = c, score
    return (best, best_score) if best_score >= threshold else (None, best_score)


def first_sentence(text: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    m = re.match(r"(.{20,%d}?[.!?])(\s|$)" % limit, text)
    return m.group(1) if m else text[:limit]


def strip_markdown(text: str) -> str:
    """Убирает разметку перед озвучкой."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M)
    text = re.sub(r"[*_~]{1,3}([^*_~\n]+)[*_~]{1,3}", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def split_for_tts(text: str, max_len: int = 240) -> list[str]:
    """Режет длинный текст на куски по предложениям для синтеза речи."""
    sentences = re.split(r"(?<=[.!?…])\s+|\n+", text.strip())
    chunks, cur = [], ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        while len(s) > max_len:
            cut = s.rfind(",", 0, max_len)
            cut = cut if cut > max_len // 3 else s.rfind(" ", 0, max_len)
            cut = cut if cut > 0 else max_len
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(s[: cut + 1].strip())
            s = s[cut + 1:].strip()
        if len(cur) + len(s) + 1 <= max_len:
            cur = (cur + " " + s).strip()
        else:
            if cur:
                chunks.append(cur)
            cur = s
    if cur:
        chunks.append(cur)
    return chunks
