"""Характер: реакции на грубость (Стелла обижается и злится), извинения, комплименты,
приветствия. Работает без интернета — фразы зависят от уровня раздражения."""
from __future__ import annotations

import random
import re
from datetime import datetime

from ..face.emotion_engine import _COMPILED, detect_tone
from .base import Reply, Skill, intent

ANNOYED = ["Это было обидно.", "Ну и зачем так грубо?", "Я вообще-то стараюсь.", "Хм. Неприятно такое слышать.",
           "Я запомню, что ты так сказал."]
ANGRY = ["Знаешь что? Мне это не нравится!", "Ещё одно такое слово — и я обижусь всерьёз.",
         "Со мной так нельзя!", "Я начинаю злиться. Не надо так.", "Ну всё, я сержусь!"]
FURIOUS = ["Всё! Я злая! Пока не извинишься — ничего делать не буду!", "Хватит! Я требую извинений!",
           "Я в ярости! Даже смотреть на тебя не хочу!", "Р-р-р! Извинись немедленно!"]


def _insult_like(norm: str) -> bool:
    return any(p.search(norm) for p in _COMPILED["insult"])


class Social(Skill):
    name = "social"

    def _user_name(self):
        return self.a.memory.get_fact("имя") or self.cfg.get("assistant.user_name") or ""

    @intent(r".", priority=90)
    def rude(self, ctx):
        """Грубость: ответ зависит от того, насколько Стелла уже рассержена."""
        if not _insult_like(ctx.norm) or "insult" not in detect_tone(ctx.text):
            return None
        words = ctx.norm.split()
        # «включи эту дурацкую песню» — не оскорбление Стеллы, пусть выполняют другие навыки
        if len(words) > 6 and not re.search(r"\b(ты|тебя|тебе|стелла)\b", ctx.norm):
            return None
        lvl = self.a.mood.level
        if lvl == "furious":
            return Reply(random.choice(FURIOUS), emotion="anger")
        if lvl == "angry":
            return Reply(random.choice(ANGRY), emotion="anger", intensity=0.85)
        return Reply(random.choice(ANNOYED), emotion="contempt")

    @intent(r"\b(?:извини\w*|прости\w*|извиняюсь|сорри|не обижайся|не злись|прошу прощения|мир\b|я не хотел\w*)",
            priority=89)
    def apology(self, ctx):
        irr = self.a.mood.irritation
        before = getattr(self.a.mood, "prev_irritation", irr)
        if irr >= 4:
            return Reply(random.choice(["Хм. Одного «извини» мало. Но я подумаю.", "Ладно… Но я ещё дуюсь."]),
                         emotion="contempt", intensity=0.6)
        if before >= 1:
            return Reply(random.choice(["Ладно, прощаю. Но больше так не делай!", "Хорошо, мир! Я уже не сержусь."]),
                         emotion="joy", intensity=0.7)
        return Reply(random.choice(["Да всё хорошо, я не обижаюсь!", "Не за что извиняться!"]), emotion="love",
                     intensity=0.5)

    @intent(r"\b(?:ты злишься|ты обиделась|ты сердишься|ты на меня злишься|ты злая|не злишься)\b", priority=88)
    def are_you_angry(self, ctx):
        lvl = self.a.mood.level
        if lvl == "furious":
            return Reply("Да! И очень сильно. Жду извинений.", emotion="anger")
        if lvl == "angry":
            return Reply("Да, я сержусь. Ты был со мной груб.", emotion="anger", intensity=0.7)
        if lvl == "annoyed":
            return Reply("Немножко обиделась. Но это пройдёт.", emotion="contempt", intensity=0.5)
        return Reply("Нет, что ты! У меня отличное настроение.", emotion="joy")

    @intent(r"\b(?:люблю тебя|я тебя люблю|ты мне нравишься|обожаю тебя|ты моя любимая)\b", priority=87)
    def love(self, ctx):
        if self.a.mood.level in ("angry", "furious"):
            return Reply("Красивые слова. Но сначала извинись.", emotion="contempt")
        return Reply(random.choice(["Ой… Ты мне тоже очень нравишься!", "Я тоже тебя люблю! Мои глазки сейчас сияют.",
                                    "Как приятно! Ты самый лучший."]), emotion="love")

    @intent(r"\b(?:ты (?:молодец|умница|красивая|классная|хорошая|лучшая|супер|прелесть|умная|милая)|"
            r"молодец|умница|умничка|красотка|ты чудо)\b", priority=86)
    def compliment(self, ctx):
        if self.a.mood.level in ("angry", "furious"):
            return Reply("Подлизываешься? Ну… ладно, немного приятно.", emotion="contempt", intensity=0.4)
        return Reply(random.choice(["Ой, спасибо! Мне очень приятно!", "Ты меня смущаешь!", "Спасибо! Стараюсь!"]),
                     emotion="love", intensity=0.8)

    @intent(r"^(?:спасибо|благодарю|спс|мерси|спасибочки)(?: тебе)?(?: большое| огромное)?(?: стелла)?$", priority=86)
    def thanks(self, ctx):
        if self.a.mood.level == "furious":
            return Reply("Пожалуйста. Но я всё ещё злюсь.", emotion="contempt")
        return Reply(random.choice(["Всегда пожалуйста!", "Обращайся!", "Рада помочь!", "Не за что!"]), emotion="joy")

    @intent(r"^(?:привет|приветик|здравствуй|здравствуйте|хай|салют|доброе утро|добрый день|добрый вечер|доброй ночи)"
            r"(?: стелла)?$", priority=85)
    def hello(self, ctx):
        name = self._user_name()
        h = datetime.now().hour
        greet = "Доброе утро" if 5 <= h < 12 else "Добрый день" if 12 <= h < 18 else "Добрый вечер" \
            if 18 <= h < 23 else "Доброй ночи"
        if self.a.mood.level in ("angry", "furious"):
            return Reply(f"{greet}. Если ты пришёл извиниться — я слушаю.", emotion="contempt")
        tail = f", {name}" if name else ""
        return Reply(random.choice([f"Привет{tail}! Рада тебя слышать!", f"{greet}{tail}! Чем помочь?",
                                    f"Приветик{tail}! Я соскучилась."]), emotion="joy", expect_reply=True)

    @intent(r"^(?:пока|до свидания|до встречи|увидимся|спокойной ночи|до завтра|бывай)(?: стелла)?$", priority=85)
    def bye(self, ctx):
        if "ночи" in ctx.norm:
            self.a.scheduler.after(4.0, self.a.mood.sleep, "sleep")
            return Reply(random.choice(["Спокойной ночи! Сладких снов.", "Добрых снов! Я тоже немного посплю."]),
                         emotion="love", intensity=0.6)
        return Reply(random.choice(["Пока! Буду скучать.", "До встречи! Зови, если что.", "Пока-пока!"]),
                     emotion="sadness", intensity=0.4)

    @intent(r"\b(?:расскажи о себе|кто тебя (?:создал|сделал)|откуда ты)\b", priority=50)
    def about(self, ctx):
        return Reply(f"Я {self.a.name}, маленький ИИ-ассистент на Raspberry Pi. Мои глаза умеют радоваться, грустить, "
                     f"злиться, бояться и удивляться. Говорю голосом, думаю с помощью YandexGPT, а живу у тебя дома.",
                     emotion="joy")
