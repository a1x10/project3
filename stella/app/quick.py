"""Простые команды без обращения к LLM: быстро и надёжно (громче/тише/без звука)."""
import re

_NUM = re.compile(r"(?:громкост[ьи]|звук)\D{0,12}?(\d{1,3})|(?:на|до)\s*(\d{1,3})\s*(?:процент\w*|%)")
_BIG = re.compile(r"намного|сильно|гораздо|в разы|очень|значительно|резко|ещё сильнее|еще сильнее", re.I)
_UP = re.compile(r"\b(по)?громче\b|прибавь|увеличь\s+(звук|громкость)|добавь\s+(звук|громкость)|звук\s+(больше|выше)|плохо слышно|не слышно", re.I)
_DOWN = re.compile(r"\b(по)?тише\b|убавь|уменьши\s+(звук|громкость)|звук\s+(меньше|ниже)|слишком громко|орёт|орет", re.I)
_MUTE = re.compile(r"без звука|выключи звук|отключи звук|включи звук|верни звук|мьют|mute|заглуши", re.I)


def match(text: str):
    """-> (команда ТВ, значение, подпись на экран) или None."""
    t = text.lower().strip(" .!?")
    if len(t.split()) > 9:
        return None
    if _MUTE.search(t):
        return "mute", "", "🔇 звук"
    n = _NUM.search(t)
    if n and re.search(r"громкост|звук", t):
        v = int(next(g for g in n.groups() if g))
        if 0 <= v <= 100:
            return "volume_set", str(v), f"🔊 {v}"
    if _UP.search(t):
        v = 15 if _BIG.search(t) else 5
        return "volume_up", str(v), f"🔊 +{v}"
    if _DOWN.search(t):
        v = 15 if _BIG.search(t) else 5
        return "volume_down", str(v), f"🔉 -{v}"
    return None
