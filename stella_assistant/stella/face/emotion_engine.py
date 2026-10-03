"""Характер Стеллы: настроение, обида и злость, симпатия, скука и сон.

* Грубость, мат и тыканье пальцем в экран копят «раздражение» (0..10).
  Сначала Стелла смотрит с презрением, потом хмурится, потом злится всерьёз
  (красное свечение, значок 💢) и может отказаться выполнять просьбы, пока
  перед ней не извинятся. Со временем она остывает сама.
* Комплименты и «спасибо» копят симпатию — взгляд становится теплее.
* Долго никто не разговаривает — скучает, зевает, потом засыпает.
"""
from __future__ import annotations

import logging
import random
import re
import time
from collections import deque
from datetime import datetime

from ..core.events import bus
from ..nlp.text import clean

log = logging.getLogger("stella.mood")

# Мат определяем только с начала слова: иначе «рублях» содержит «бля», а «требуется» — «ебу».
_SWEAR = (r"\b(?:ху[йяеёию]\w*|о?ху[её]\w*|на ?хуй|по ?хуй\w*|хер(?:ня|ов\w*|ово)|пизд\w*|распизд\w*|[её]б[ауи]\w*|"
          r"(?:за|у|на|вы|до|от|раз|под|пере)[ъь]?[её]б\w*|бля\w*|сук[аиу]\b|сучк\w*|мудак\w*|мудил\w*|говн\w*|"
          r"жоп\w*|гандон\w*|долбо[её]б\w*|залуп\w*|шлюх\w*|чмо\w*)")
TONE_PATTERNS = {
    # всегда грубость (обзывательства и мат)
    "insult": [
        r"\bдур[аеоы]\w*", r"\bтуп(?:ая|ой|ица|ые|орыл)", r"\bидиот\w*", r"\bбестолков\w*", r"\bзаткнись\b",
        r"\bотвали\b", r"\bжелезяк\w*", r"\bведро с болтами\b", r"\bкусок железа\b", r"\bбесишь\b",
        r"\bлузер\w*", r"\bдебил\w*", r"\bкретин\w*", r"\bничтожеств\w*", r"\bуродин\w*", _SWEAR,
    ],
    # грубость, только если сказано Стелле: «ты ужасная», «ты меня достала», просто «надоела!»,
    # но не «какая ужасная погода», «мне надоела эта песня», «я достала молоко»
    "insult_if_addressed": [
        r"\bглуп(?:ая|ый)\b", r"\bбесполезн\w*", r"\bотстань\b", r"\bненавижу\b", r"\bужасн(?:ая|ый)\b",
        r"\bотстой\w*", r"\bдостала\b", r"\bнадоела\b", r"\bкорыто\b", r"\bтормоз\b", r"\bкривая\b",
    ],
    "apology": [r"\bизвини\w*", r"\bпрости\w*", r"\bизвиняюсь\b", r"\bсорри\b", r"\bне обижайся\b",
                r"\bне злись\b", r"^(?:ну |давай )?мир(?: дружба)?$", r"\bя не хотел\w*", r"\bпрошу прощения\b",
                r"\bвиноват\w*"],
    "compliment": [r"\bумниц\w*", r"\bмолодец\b", r"\bкрасив\w*", r"\bклассн\w*", r"\bлучш(?:ая|ий)\b",
                   r"\bсупер\b", r"\bпрелесть\b", r"\bчудо\b", r"\bгениальн\w*", r"\bумная\b", r"\bхорошая\b",
                   r"\bмилая\b", r"\bсолнышко\b", r"\bзайка\b", r"\bкрасотка\b"],
    "thanks": [r"\bспасибо\b", r"\bблагодар\w*", r"\bспс\b", r"\bмерси\b"],
    "love": [r"\bлюблю тебя\b", r"\bя тебя люблю\b", r"\bты мне нравишься\b", r"\bобожаю тебя\b",
             r"\bобнимаю\b", r"\bцелую\b", r"\bвлюбил\w*", r"\bвыходи за меня\b"],
    "sad": [r"\bгрустно\b", r"\bпечальн\w*", r"\bтоскливо\b", r"\bодиноко\b", r"\bмне плохо\b", r"\bумер\w*",
            r"\bпогиб\w*", r"\bболею\b", r"\bзаболел\w*", r"\bплачу\b", r"\bрасстро\w*", r"\bгрущу\b"],
    "fear": [r"\bстрашно\b", r"\bбоюсь\b", r"\bужас\b", r"\bпаук\w*", r"\bмонстр\w*", r"\bпривидени\w*",
             r"\bзомби\b", r"\bгроз[аы]\b", r"\bбу+\b", r"\bнапугал\w*"],
    "surprise": [r"\bпредставляешь\b", r"\bприкинь\b", r"\bвау\b", r"\bого\b", r"\bничего себе\b",
                 r"\bневероятно\b", r"\bне может быть\b", r"\bофигеть\b", r"\bобалдеть\b"],
    "bored": [r"\bскучно\b", r"\bскукота\b", r"\bнечего делать\b", r"\bзевота\b"],
    "challenge": [r"\bспорим\b", r"\bслабо\b", r"\bты не сможешь\b", r"\bкто кого\b", r"\bвызов\b",
                  r"\bдавай поспорим\b", r"\bя умнее тебя\b", r"\bкто умнее\b"],
    "disgust": [r"\bфу+\b", r"\bгадост\w*", r"\bмерзост\w*", r"\bпротивно\b", r"\bотвратительн\w*",
                r"\bтошнит\b", r"\bвонюч\w*"],
    "happy": [r"\bура+\b", r"\bкласс\b", r"\bздорово\b", r"\bотлично\b", r"\bкруто\b", r"\bвесело\b",
              r"\bрадост\w*", r"\bсчастлив\w*", r"\bпобедил\w*", r"\bполучилось\b", r"\bпраздник\b"],
}
_COMPILED = {k: [re.compile(p) for p in v] for k, v in TONE_PATTERNS.items()}
_ADDRESSED_WORDS = [re.compile(p.replace("\\b", "")) for p in TONE_PATTERNS["insult_if_addressed"]]

# реакции лица на тон собеседника
TONE_EMOTION = {
    "compliment": ("joy", 1.0), "thanks": ("joy", 0.8), "love": ("love", 1.0), "sad": ("sadness", 0.8),
    "fear": ("fear", 0.8), "surprise": ("surprise", 1.0), "bored": ("interest", 0.8),
    "challenge": ("confidence", 1.0), "disgust": ("contempt", 0.9), "happy": ("joy", 0.9),
}


# слова, которые могут стоять рядом с «надоела» и т.п., не превращая фразу в разговор о чём-то другом
_FILLER = {"ну", "ты", "же", "просто", "совсем", "очень", "какая", "какой", "такая", "такой", "вообще", "как", "ой",
           "блин", "уже", "меня", "мне", "так", "все", "всё", "реально", "прям", "прямо", "а", "и", "стелла"}
_ADDRESSED = re.compile(r"\b(?:ты|тебя|тебе|тобой|стелла)\b")
# короткие команды управления: повторять их — нормально («дальше», «громче»), это не надоедание
_CONTROL = re.compile(r"^(?:ну |еще |ещё |сделай |а )?(?:дальше|далее|еще|ещё|громче|тише|погромче|потише|следующ\w*|"
                      r"предыдущ\w*|назад|вперед|стоп|пауза|продолжи\w*|да|нет|ага|угу|повтори|включи|выключи|"
                      r"перемотай|пропусти|\d+)(?: \w+)?$")


def detect_tone(text: str) -> list[str]:
    t = clean(text)
    found = []
    for tone, pats in _COMPILED.items():
        if any(p.search(t) for p in pats):
            found.append(tone)
    if "insult_if_addressed" in found:
        found.remove("insult_if_addressed")
        hits = {w for w in t.split() if any(p.fullmatch(w) for p in _ADDRESSED_WORDS)}
        if _ADDRESSED.search(t) or all(w in _FILLER or w in hits for w in t.split()):
            if "insult" not in found:
                found.append("insult")
    # «не дура» / «ты не глупая» — это не оскорбление
    if "insult" in found and re.search(r"\bне (?:дура|глупая|тупая|бесполезная)\b", t):
        found.remove("insult")
    if "insult" in found and "apology" in found:
        found.remove("insult")
    return found


def guess_emotion(text: str):
    """Эмоция по тексту (для ответов без явного тега). -> (имя, сила) или None."""
    tones = detect_tone(text)
    for tone in ("love", "fear", "sad", "surprise", "disgust", "challenge", "happy", "compliment", "thanks"):
        if tone in tones:
            return TONE_EMOTION[tone]
    if re.search(r"!\s*$", text or "") and re.search(r"\b(ура|отлично|здорово|рада)\b", clean(text)):
        return "joy", 0.8
    return None


class EmotionEngine:
    def __init__(self, cfg, memory=None):
        self.cfg = cfg
        self.memory = memory
        pers = cfg["personality"]
        self.can_get_angry = bool(pers.get("can_get_angry", True))
        self.can_refuse = bool(pers.get("can_refuse_when_angry", True))
        self.decay = float(pers.get("anger_decay_seconds", 45))
        self.irritation = float(memory.kv_get("irritation", 0.0)) if memory else 0.0
        self.affection = float(memory.kv_get("affection", 2.0)) if memory else 2.0
        self.last_interaction = time.time()
        self.recent = deque(maxlen=8)
        self.taps = deque(maxlen=12)
        self.sleeping = False
        self.prev_irritation = self.irritation
        self._last_tick = time.time()
        self._last_mood = None
        # касания экрана (on_touch) и сброс лица (refresh) сюда передаёт ассистент:
        # если касанием выключили будильник, это не «щекотно»

    # ------------------------------------------------------------ уровни --
    @property
    def level(self) -> str:
        if self.irritation >= 7:
            return "furious"
        if self.irritation >= 4:
            return "angry"
        if self.irritation >= 2:
            return "annoyed"
        return "calm"

    def _change(self, irritation: float = 0.0, affection: float = 0.0):
        if not self.can_get_angry:
            irritation = min(0.0, irritation)
        self.irritation = max(0.0, min(10.0, self.irritation + irritation))
        self.affection = max(0.0, min(10.0, self.affection + affection))
        if self.memory:
            self.memory.kv_set("irritation", round(self.irritation, 2))
            self.memory.kv_set("affection", round(self.affection, 2))
        self._apply_mood()

    # ------------------------------------------------------------ события --
    def on_user_text(self, text: str) -> list[str]:
        """Анализ реплики пользователя. Возвращает найденные «тона»."""
        now = time.time()
        self.last_interaction = now
        self.prev_irritation = self.irritation
        if self.sleeping:
            self.wake()
        tones = detect_tone(text)
        t = clean(text)
        # одно и то же много раз подряд — раздражает (кроме команд вроде «дальше» и «громче»)
        same = sum(1 for (ts, x) in self.recent if x == t and now - ts < 90)
        self.recent.append((now, t))
        if same >= 2 and len(t) > 3 and not _CONTROL.match(t):
            self._change(irritation=0.8)
        if "insult" in tones:
            self._change(irritation=2.5 + (1.0 if re.search(_SWEAR, t) else 0.0), affection=-1.0)
            bus.emit("emotion", name="anger" if self.irritation >= 4 else "contempt", intensity=1.0, hold=8)
        elif "apology" in tones:
            self._change(irritation=-3.5, affection=0.5)
            bus.emit("emotion", name="contempt" if self.irritation >= 3 else "joy", intensity=0.7, hold=5)
        elif tones:
            if "compliment" in tones or "love" in tones:
                self._change(irritation=-1.5, affection=1.5)
            elif "thanks" in tones:
                self._change(irritation=-0.5, affection=0.5)
            for tone in tones:
                if tone in TONE_EMOTION:
                    name, inten = TONE_EMOTION[tone]
                    if self.level in ("angry", "furious") and name in ("joy", "love"):
                        name, inten = "contempt", 0.6  # сердится — так просто не задобрить
                    bus.emit("emotion", name=name, intensity=inten, hold=7)
                    break
        return tones

    def on_touch(self):
        now = time.time()
        self.last_interaction = now
        if self.sleeping:
            self.wake()
            bus.emit("emotion", name="surprise", intensity=0.8, hold=2.5)
            return "wake"
        self.taps.append(now)
        recent = [t for t in self.taps if now - t < 6]
        if len(recent) >= 5:
            self._change(irritation=0.9)
            bus.emit("emotion", name="anger", intensity=0.9, hold=4)
            if len(recent) == 5 or len(recent) % 4 == 0:
                bus.emit("say", text=random.choice([
                    "Ай! Хватит в меня тыкать!", "Ну всё, я обиделась.", "Перестань, мне неприятно!",
                    "Я тебе не кнопка лифта!"]), emotion="anger")
            return "annoyed"
        if len(recent) >= 3:
            bus.emit("emotion", name="contempt", intensity=0.6, hold=2.5)
            return "hmm"
        bus.emit("emotion", name="joy", intensity=0.9, hold=2.0)
        if random.random() < 0.25:
            bus.emit("say", text=random.choice(["Хи-хи, щекотно!", "Ой!", "Привет-привет!"]), emotion="joy")
        return "giggle"

    def on_activity(self):
        self.last_interaction = time.time()
        if self.sleeping:
            self.wake()

    def wake(self):
        self.sleeping = False
        bus.emit("state", state="idle")
        self._apply_mood()

    def sleep(self):
        self.sleeping = True
        bus.emit("state", state="sleep")

    def refresh(self):
        """Заново показать настроение (после демонстрации эмоций лицо сбрасывается)."""
        self._last_mood = None
        if self.sleeping:
            bus.emit("state", state="sleep")
        self._apply_mood()

    # --------------------------------------------------------------- тик --
    def tick(self):
        now = time.time()
        dt = now - self._last_tick
        self._last_tick = now
        if self.irritation > 0:
            self.irritation = max(0.0, self.irritation - dt / self.decay)
        if self.affection > 2:
            self.affection = max(2.0, self.affection - dt / 600)
        idle = now - self.last_interaction
        a = self.cfg["assistant"]
        if not self.sleeping and idle > float(a.get("sleep_after_minutes", 30)) * 60:
            self.sleep()
        self._apply_mood(idle)

    def is_night(self) -> bool:
        q = self.cfg.get("assistant.quiet_hours") or []
        if len(q) != 2:
            return False
        now = datetime.now().strftime("%H:%M")
        start, end = q
        return (start <= now or now < end) if start > end else (start <= now < end)

    def _apply_mood(self, idle: float | None = None):
        if idle is None:
            idle = time.time() - self.last_interaction
        bored_after = float(self.cfg.get("assistant.bored_after_minutes", 5)) * 60
        extra = None
        if self.irritation >= 7:
            mood = ("anger", 1.0)
            extra = {"anger_mark": 1.0, "glow": 0.6}
        elif self.irritation >= 4:
            mood = ("anger", 0.7)
        elif self.irritation >= 2:
            mood = ("contempt", 0.55)
        elif idle > bored_after:
            mood = ("boredom", 0.9 if self.is_night() else 0.75)
        elif self.is_night() and idle > 60:
            mood = ("boredom", 0.45)
        elif self.affection >= 6:
            mood = ("love", 0.35)
        else:
            mood = ("neutral", 1.0)
        key = (mood, tuple(sorted((extra or {}).items())))
        if key != self._last_mood:
            self._last_mood = key
            bus.emit("mood", name=mood[0], intensity=mood[1], extra=extra)

    # ------------------------------------------------------------ для ИИ --
    def should_refuse(self, fun: bool = True) -> bool:
        """Сильно разозлённая Стелла может отказаться от «развлекательных» просьб."""
        if not (self.can_refuse and fun):
            return False
        if self.irritation >= 7:
            return random.random() < 0.7
        if self.irritation >= 5:
            return random.random() < 0.3
        return False

    def mood_prompt(self) -> str:
        lvl = self.level
        if lvl == "furious":
            return ("Сейчас ты очень рассержена на собеседника (он грубил). Отвечай коротко, резко и колко, "
                    "можешь потребовать извинений. Без оскорблений и мата.")
        if lvl == "angry":
            return "Ты раздражена: отвечай сухо и с иронией, без лишней теплоты."
        if lvl == "annoyed":
            return "Ты немного обижена: отвечай вежливо, но прохладно и чуть язвительно."
        if self.affection >= 6:
            return "Тебе очень нравится собеседник: отвечай особенно тепло и игриво."
        if self.is_night():
            return "Сейчас ночь, ты немного сонная: отвечай мягко и спокойно."
        return ""
