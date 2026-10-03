"""Память о пользователе: «запомни, что…», «как меня зовут», «что ты обо мне знаешь», «забудь…»."""
from __future__ import annotations

import re

from .base import Reply, Skill, intent

_KEY_PATTERNS = [
    (r"^меня зовут (.+)$", "имя"),
    (r"^мое имя (.+)$", "имя"),
    (r"^я живу (?:в|на) (.+)$", "город"),
    (r"^мой день рождения (.+)$", "день рождения"),
    (r"^у меня день рождения (.+)$", "день рождения"),
    (r"^мне (\d+) (?:лет|год|года)$", "возраст"),
    (r"^(?:мой|моя|мое|мои) любим\w+ (\w+) (?:это |— |- )?(.+)$", None),
    (r"^(?:мою|моего) (собак\w*|кошк\w*|кот\w*|жен\w*|муж\w*|сын\w*|доч\w*|мам\w*|пап\w*) зовут (.+)$", None),
    (r"^(?:мой|моя) (собака|кошка|кот|жена|муж|сын|дочь|мама|папа|брат|сестра) (.+)$", None),
]


def extract_fact(text: str):
    t = text.strip().rstrip(".!")
    for pat, key in _KEY_PATTERNS:
        m = re.match(pat, t)
        if m:
            if key:
                return key, m.group(1).strip()
            if "любим" in pat:
                return f"любимый {m.group(1)}", m.group(2).strip()
            return m.group(1).strip(), m.group(2).strip()
    words = t.split()
    return " ".join(words[:2]) if len(words) > 2 else "факт", t


class MemorySkill(Skill):
    name = "memory"

    @intent(r"\bзапомни(?:,)?(?: пожалуйста)?(?: что)? (.+)$", priority=75)
    def remember(self, ctx):
        fact = ctx.group(1)
        if re.match(r"^(?:эту|этот|это) (?:песню|трек|композицию|мелодию)$", fact):
            return None  # «запомни эту песню» — лайк, если музыка играет
        key, value = extract_fact(fact)
        if key == "имя":
            value = value.split()[0].capitalize()
        self.a.memory.set_fact(key, value)
        if key == "имя":
            return Reply(f"Приятно познакомиться, {value}! Запомнила.", emotion="joy")
        return Reply(f"Запомнила: {fact}.", emotion="interest", intensity=0.6)

    @intent(r"^(?:меня зовут|мое имя|зови меня|называй меня) (\w+)$", priority=74)
    def my_name(self, ctx):
        name = ctx.group(1).capitalize()
        self.a.memory.set_fact("имя", name)
        return Reply(f"Приятно познакомиться, {name}! Буду тебя так называть.", emotion="joy")

    @intent(r"\bкак меня зовут\b|\bты знаешь как меня зовут\b|\bты помнишь мое имя\b", priority=74)
    def whats_my_name(self, ctx):
        name = self.a.memory.get_fact("имя") or self.cfg.get("assistant.user_name")
        if name:
            return Reply(f"Тебя зовут {name}. Я помню!", emotion="joy")
        return Reply("Ты ещё не говорил. Как тебя зовут?", emotion="interest", expect_reply=True)

    @intent(r"\bчто ты (?:знаешь|помнишь) (?:обо мне|про меня)\b", priority=74)
    def what_you_know(self, ctx):
        facts = self.a.memory.facts()
        if not facts:
            return Reply("Пока ничего. Расскажи о себе — скажи «запомни, что…».", emotion="interest")
        items = [f"{k} — {v}" for k, v in facts.items()]
        return Reply("Вот что я помню: " + "; ".join(items) + ".", emotion="love", intensity=0.5,
                     card="\n".join(items))

    @intent(r"\b(?:забудь|очисти|сотри) (?:наш |весь )?(?:разговор|диалог|историю|контекст|переписку)\b", priority=76)
    def forget_dialog(self, ctx):
        self.a.memory.clear_dialog()
        return Reply("Готово, начнём разговор с чистого листа.", emotion="neutral")

    @intent(r"\bзабудь (?:все|всё) (?:обо мне|что знаешь|про меня)\b", priority=76)
    def forget_all(self, ctx):
        self.a.memory.clear_facts()
        return Reply("Хорошо, я всё забыла. Немного грустно…", emotion="sadness", intensity=0.5)

    @intent(r"(?<!\bне )\bзабудь(?: что)? (.+)$", priority=73)
    def forget(self, ctx):
        key = self.a.memory.forget_fact(ctx.group(1))
        if key:
            return Reply(f"Забыла: {key}.")
        return Reply("Я и так этого не помню.", emotion="surprise", intensity=0.4)
