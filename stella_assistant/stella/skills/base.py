"""Каркас навыков.

Навык — класс с методами-обработчиками, помеченными декоратором @intent(регулярки…).
Регулярки проверяются на нормализованном тексте (нижний регистр, ё→е, числа цифрами):

    class Coin(Skill):
        @intent(r"\\bподбрось монет", fun=True)
        def coin(self, ctx):
            return Reply(random.choice(["Орёл!", "Решка!"]), emotion="joy")

Обработчик может вернуть Reply, строку или None (None = «это не мне», роутер ищет дальше).
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover
    from ..core.assistant import Assistant

log = logging.getLogger("stella.skills")


@dataclass
class Reply:
    text: str = ""
    emotion: str | None = None
    intensity: float = 1.0
    expect_reply: bool = False      # Стелла задала вопрос — слушаем ответ без «Стелла»
    speak: bool = True
    card: str | None = None         # длинный текст для Telegram/веба (стих, список…)
    lang: str = "ru"
    whisper: bool | None = None
    data: dict = field(default_factory=dict)


@dataclass
class Context:
    text: str                   # как сказали
    norm: str                   # нормализованный текст
    source: str = "voice"       # voice / telegram / web / scenario / peer
    whisper: bool = False
    user: str | None = None
    assistant: "Assistant" = None
    match: re.Match | None = None
    chat_id: int | None = None

    def say(self, text: str, emotion: str | None = None):
        """Сказать что-то по ходу дела («Сейчас поищу…»)."""
        if self.assistant and self.source == "voice":
            self.assistant.say(text, emotion=emotion)

    def group(self, i=1, default=""):
        try:
            return (self.match.group(i) or default).strip() if self.match else default
        except (IndexError, AttributeError):
            return default

    def raw_group(self, i=1, default=""):
        """Та же группа, но из текста без замены числительных («семь сорок», «первый айфон»)."""
        if not self.match:
            return default
        light = re.sub(r"\s+", " ", re.sub(r"[^\w\s:.+\-]", " ", self.text.lower().replace("ё", "е"))).strip()
        m = self.match.re.search(light)
        try:
            if m and m.group(i):
                return m.group(i).strip()
        except IndexError:
            pass
        return self.group(i, default)


@dataclass
class Intent:
    patterns: list
    handler: Callable
    priority: int = 50
    fun: bool = False
    skill: "Skill" = None
    name: str = ""


def intent(*patterns: str, priority: int = 50, fun: bool = False):
    def deco(fn):
        fn._stella_intent = ([re.compile(p) for p in patterns], priority, fun)
        return fn
    return deco


class Skill:
    name = "skill"
    description = ""

    def __init__(self, assistant: "Assistant"):
        self.a = assistant
        self.cfg = assistant.cfg
        self.log = logging.getLogger(f"stella.skill.{self.name}")

    def intents(self) -> list[Intent]:
        out = []
        for attr in dir(self):
            fn = getattr(self, attr, None)
            spec = getattr(fn, "_stella_intent", None)
            if spec:
                pats, prio, fun = spec
                out.append(Intent(pats, fn, prio, fun, self, f"{self.name}.{attr}"))
        return out

    def start(self):
        """Вызывается после запуска ассистента (фоновые задачи навыка)."""

    def stop(self):
        pass


class SessionHandler:
    """Активная «сессия» навыка (игра, рецепт, внешний навык): получает реплики первой.
    Заканчивается сама, если с ней не разговаривали дольше timeout секунд."""

    def __init__(self, skill: Skill, handler: Callable[[Context], Reply | str | None], name: str,
                 exit_words=("хватит", "стоп", "выход", "выйди", "закончи", "закончим", "надоело"),
                 timeout: float = 180):
        self.skill = skill
        self.handler = handler
        self.name = name
        self.exit_words = exit_words
        self.timeout = timeout
        self.last_used = time.time()

    def touch(self):
        self.last_used = time.time()

    def expired(self) -> bool:
        return time.time() - self.last_used > self.timeout


def as_reply(r) -> Reply | None:
    if r is None:
        return None
    if isinstance(r, Reply):
        return r
    if isinstance(r, str):
        return Reply(r)
    if isinstance(r, tuple):
        return Reply(*r)
    raise TypeError(f"Навык вернул {type(r)}")
