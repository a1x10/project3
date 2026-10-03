"""Рецепты по шагам: Стелла читает ингредиенты и шаги, ждёт «дальше», умеет «повтори»/«назад»
и сама предлагает поставить таймер, если в шаге есть время («варить 10 минут»)."""
from __future__ import annotations

import json
import re
import time

from ..nlp.numbers import plural
from ..nlp.text import best_match
from ..nlp.timeparse import describe_duration, parse_duration
from .base import Reply, Skill, intent

BUILTIN = {
    "блины": {
        "title": "Блины на молоке",
        "ingredients": ["молоко — 500 мл", "яйца — 2 штуки", "мука — 200 грамм", "сахар — 1 столовая ложка",
                        "соль — щепотка", "растительное масло — 2 столовые ложки"],
        "steps": ["Взбейте яйца с сахаром и солью.", "Влейте половину молока и перемешайте.",
                  "Постепенно всыпьте муку, размешивая венчиком, чтобы не было комков.",
                  "Влейте остальное молоко и масло. Тесто должно быть жидким, как сливки. Дайте ему постоять 15 минут.",
                  "Разогрейте сковороду и смажьте маслом.",
                  "Наливайте тесто тонким слоем и жарьте примерно по 1 минуте с каждой стороны до золотистого цвета.",
                  "Готово! Подавайте со сметаной, мёдом или вареньем."],
    },
    "омлет": {
        "title": "Пышный омлет",
        "ingredients": ["яйца — 3 штуки", "молоко — 100 мл", "соль — по вкусу", "сливочное масло — 10 грамм"],
        "steps": ["Слегка взбейте яйца с молоком и солью вилкой.", "Растопите масло на сковороде на среднем огне.",
                  "Вылейте смесь, накройте крышкой и готовьте на слабом огне 5 минут.",
                  "Не открывайте крышку ещё 2 минуты — омлет станет пышным. Приятного аппетита!"],
    },
    "гречка": {
        "title": "Рассыпчатая гречка",
        "ingredients": ["гречка — 1 стакан", "вода — 2 стакана", "соль — по вкусу", "сливочное масло — по вкусу"],
        "steps": ["Переберите и промойте гречку.", "Обжарьте её на сухой сковороде 3 минуты — так она будет ароматнее.",
                  "Залейте кипящей подсоленной водой, накройте крышкой и варите на слабом огне 15 минут.",
                  "Снимите с огня, добавьте масло и дайте постоять под крышкой 10 минут."],
    },
    "борщ": {
        "title": "Борщ",
        "ingredients": ["говядина на кости — 500 грамм", "свёкла — 1 штука", "капуста — 300 грамм",
                        "картофель — 3 штуки", "морковь — 1 штука", "лук — 1 штука", "томатная паста — 2 ложки",
                        "чеснок, соль, лавровый лист — по вкусу"],
        "steps": ["Залейте мясо водой, доведите до кипения, снимите пену и варите бульон 1 час.",
                  "Нарежьте картофель кубиками и добавьте в бульон, варите 10 минут.",
                  "Добавьте нашинкованную капусту.",
                  "Обжарьте лук и морковь, затем добавьте тёртую свёклу и томатную пасту, тушите 10 минут.",
                  "Переложите зажарку в кастрюлю, посолите, добавьте лавровый лист и варите ещё 10 минут.",
                  "Добавьте чеснок, выключите огонь и дайте борщу настояться 20 минут. Подавайте со сметаной!"],
    },
}


class Recipes(Skill):
    name = "recipes"

    def __init__(self, a):
        super().__init__(a)
        self.r = None
        self.i = -1
        self.pending_timer = None

    def _from_llm(self, dish: str):
        if not self.a.brain.available:
            return None
        try:
            raw = self.a.brain.ask(
                f"Дай простой домашний рецепт: {dish}. Ответь строго JSON без пояснений: "
                "{\"title\": \"название\", \"ingredients\": [\"ингредиент — количество\", …], "
                "\"steps\": [\"короткий шаг\", …]}. Шагов 4–9, в шагах указывай время приготовления цифрами.",
                temperature=0.4, max_tokens=1200)
            m = re.search(r"\{.*\}", raw, re.S)
            d = json.loads(m.group(0))
            if d.get("steps"):
                return d
        except Exception as e:
            self.log.warning("рецепт от GPT: %s", e)
        return None

    @intent(r"\b(?:как (?:приготовить|сделать|испечь|сварить|пожарить)|рецепт\w*|давай (?:приготовим|готовить)|"
            r"научи (?:готовить|меня готовить))\s+(.+)$", priority=57)
    def begin(self, ctx):
        dish = re.sub(r"^(?:мне|нам)\s+", "", ctx.raw_group(1))
        hit, score = best_match(dish, list(BUILTIN.keys()), threshold=0.6)
        recipe = BUILTIN[hit] if hit else None
        if recipe is None:
            if ctx.source == "voice":
                ctx.say("Сейчас найду рецепт…", emotion="interest")
            recipe = self._from_llm(dish)
        if recipe is None:
            return Reply(f"Не знаю рецепт «{dish}». Я умею: {', '.join(BUILTIN)}. А с ИИ — что угодно.",
                         emotion="sadness")
        self.r, self.i = recipe, -1
        self.a.start_session(self, self._session, "рецепт", timeout=45 * 60,  # готовят долго
                             exit_words=("хватит", "стоп", "выход", "закончи", "закончим", "конец", "отмена"))
        n = len(recipe["ingredients"])
        return Reply(f"{recipe['title']}. Понадобится {n} {plural(n, 'ингредиент', 'ингредиента', 'ингредиентов')} "
                     f"и {len(recipe['steps'])} {plural(len(recipe['steps']), 'шаг', 'шага', 'шагов')}. "
                     f"Перечислить ингредиенты или начинаем?", emotion="joy", expect_reply=True,
                     card=recipe["title"] + "\n\n" + "\n".join("• " + x for x in recipe["ingredients"]) + "\n\n" +
                     "\n".join(f"{k + 1}. {s}" for k, s in enumerate(recipe["steps"])))

    def _step(self, idx: int) -> Reply:
        steps = self.r["steps"]
        self.i = max(0, min(idx, len(steps) - 1))
        text = f"Шаг {self.i + 1}. {steps[self.i]}"
        sec, _ = parse_duration(steps[self.i])
        if sec and sec >= 60:
            self.pending_timer = (sec, self.r["title"])
            text += f" Поставить таймер на {describe_duration(sec)}?"
        else:
            self.pending_timer = None
            text += " Скажи «дальше», когда будешь готов." if self.i < len(steps) - 1 else " Это был последний шаг. Приятного аппетита!"
        if self.i == len(steps) - 1 and not self.pending_timer:
            self.a.end_session()
        return Reply(text, expect_reply=self.i < len(steps) - 1 or bool(self.pending_timer), emotion="interest",
                     intensity=0.4)

    def _session(self, ctx):
        n = ctx.norm
        if self.pending_timer and re.search(r"^(?:да|давай|поставь|ага|конечно|угу|хорошо)\b", n):
            sec, title = self.pending_timer
            self.pending_timer = None
            self.a.memory.alarm_add("timer", time.time() + sec, title.lower())
            done = self.i >= len(self.r["steps"]) - 1
            if done:
                self.a.end_session()
            return Reply(f"Засекла {describe_duration(sec)}. " + ("Приятного аппетита!" if done else
                                                                     "Скажи «дальше», когда будешь готов."),
                         expect_reply=not done, emotion="confidence", intensity=0.4)
        if self.pending_timer and re.search(r"^(?:нет|не надо|не нужно)\b", n):
            self.pending_timer = None
            return Reply("Хорошо. Скажи «дальше», когда будешь готов.", expect_reply=True)
        if re.search(r"\bингредиент\w*|^(?:перечисли|что нужно|какие продукты)\b", n):
            return Reply("Ингредиенты: " + "; ".join(self.r["ingredients"]) + ". Начинаем?", expect_reply=True)
        # «дальше», «да, готово», «следующий шаг» — но не «следующая песня» и не «давай включим радио»
        if _only(n, _NEXT, _FILLER | {"шаг"}):
            return self._step(self.i + 1)
        if _only(n, {"повтори", "еще", "раз", "расслышал", "расслышала"}, _FILLER | {"шаг", "не", "этот"}):
            return self._step(max(0, self.i))
        if _only(n, {"назад", "предыдущий", "вернись", "прошлый"}, _FILLER | {"шаг", "на", "обратно"}):
            return self._step(self.i - 1)
        if re.search(r"^сколько (?:еще )?(?:шагов|осталось)(?: шагов)?$", n):
            left = len(self.r["steps"]) - self.i - 1
            return Reply(f"Осталось {left} {plural(left, 'шаг', 'шага', 'шагов')}.", expect_reply=True)
        return None  # другая команда (например, «поставь таймер») — пусть обработают навыки


_NEXT = {"дальше", "далее", "следующий", "следующая", "следующее", "готово", "готов", "готова", "начинаем", "начнем",
         "начинай", "давай", "поехали", "да", "сделал", "сделала", "сделали", "продолжай", "продолжим"}
_FILLER = {"ну", "так", "хорошо", "ок", "окей", "ладно", "пожалуйста", "все", "я", "уже", "можно", "а", "и"}


def _only(text: str, triggers: set, allowed: set) -> bool:
    """Фраза состоит только из этих слов и есть хотя бы одно слово-команда."""
    words = text.split()
    return bool(words) and any(w in triggers for w in words) and all(w in triggers or w in allowed for w in words)
