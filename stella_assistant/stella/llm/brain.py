"""«Мозг» Стеллы: диалог с YandexGPT с памятью, характером и эмоциями.

Модель отвечает с тегом эмоции в начале ([joy], [anger] …) — по нему двигаются глаза.
Если модель поняла, что человек просит действие, она возвращает «КОМАНДА: …»,
и команда уходит в обычный обработчик навыков. Если нужны свежие данные — «ПОИСК: …».
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from ..face.emotions import EMOTIONS, resolve
from ..nlp.timeparse import MONTHS_GEN, WEEKDAYS_NOM
from .yandexgpt import LLMError, YandexGPT

log = logging.getLogger("stella.brain")

EMOTION_TAGS = EMOTIONS + ["neutral"]
_TAG_RE = re.compile(r"\[\s*(" + "|".join(EMOTION_TAGS) + r"|радость|грусть|злость|страх|удивление|"
                     r"любовь|интерес|презрение|уверенность|скука|нейтрально)\s*\]", re.I)

COMMANDS_HELP = (
    "музыка (включи музыку/песню/исполнителя/плейлист/радио/подкаст/аудиокнигу, пауза, дальше, громче), "
    "будильники и таймеры, напоминания, погода, пробки и маршруты, адреса и организации, "
    "списки покупок и дел, заметки, умный дом (свет, розетки, чайник, кондиционер, пылесос, датчики, сценарии), "
    "телевизор, радионяня, звонок в другую комнату, поиск телефона, игры (города, викторина, угадай число, загадки), "
    "рецепты по шагам, новости и чтение статей, курсы валют, перевод, калькулятор"
)


@dataclass
class Thought:
    text: str = ""
    emotion: str | None = None
    command: str | None = None
    search: str | None = None


def parse_answer(raw: str) -> Thought:
    th = Thought()
    raw = (raw or "").strip()
    m = _TAG_RE.search(raw[:40])
    if m:
        th.emotion = resolve(m.group(1))
    text = _TAG_RE.sub("", raw).strip()
    cm = re.search(r"КОМАНДА\s*:\s*(.+)", text, re.I)
    if cm:
        th.command = cm.group(1).strip().strip(".«»\"")
        text = text[: cm.start()].strip()
    sm = re.search(r"ПОИСК\s*:\s*(.+)", text, re.I)
    if sm:
        th.search = sm.group(1).strip().strip(".«»\"")
        text = text[: sm.start()].strip()
    th.text = text
    return th


class Brain:
    def __init__(self, cfg, memory, mood=None):
        self.cfg = cfg
        self.memory = memory
        self.mood = mood
        self.llm = YandexGPT(cfg)

    @property
    def available(self) -> bool:
        return self.llm.available

    def system_prompt(self, long_form: bool = False, extra: str = "") -> str:
        a = self.cfg["assistant"]
        now = datetime.now()
        facts = self.memory.facts() if self.memory else {}
        facts_txt = "; ".join(f"{k}: {v}" for k, v in facts.items()) or "пока ничего"
        name = a.get("name", "Стелла")
        style = self.cfg.get("personality.style", "весёлая и добрая")
        length = ("Сейчас пользователь просит текст — пиши столько, сколько нужно, но без markdown."
                  if long_form else
                  "Отвечай коротко: 1–3 предложения, как в живой речи.")
        mood = self.mood.mood_prompt() if self.mood else ""
        return (
            f"Ты — {name}, домашний голосовой ассистент на Raspberry Pi с живыми анимированными глазами. "
            f"Характер: {style}. У тебя есть эмоции, ты можешь обидеться на грубость и порадоваться комплименту. "
            f"Говори по-русски, от женского лица. Твой ответ озвучивается голосом: никаких списков, markdown, "
            f"эмодзи и ссылок; числа пиши цифрами. {length}\n"
            f"Каждый ответ начинай с одного тега эмоции: {' '.join('[' + e + ']' for e in EMOTION_TAGS)} — "
            f"он управляет твоими глазами, выбирай его по смыслу ответа и своему настроению.\n"
            f"Ты умеешь: {COMMANDS_HELP}. Если пользователь просит одно из этих действий, ответь строго "
            f"«[neutral] КОМАНДА: <короткая команда в повелительном наклонении>», например "
            f"«[neutral] КОМАНДА: включи свет на кухне».\n"
            f"Если для ответа нужны свежие данные (новости, цены, спорт, события после твоих знаний, "
            f"расписания), ответь строго «[neutral] ПОИСК: <поисковый запрос>».\n"
            f"Сейчас {now.day} {MONTHS_GEN[now.month - 1]} {now.year} года, {WEEKDAYS_NOM[now.weekday()]}, "
            f"{now:%H:%M}. Город пользователя: {a.get('city', '')}. "
            f"Имя пользователя: {facts.get('имя') or a.get('user_name') or 'неизвестно'}. "
            f"Что ты помнишь о пользователе: {facts_txt}.\n{mood}\n{extra}"
        ).strip()

    def history(self, n: int | None = None) -> list[dict]:
        n = n or int(self.cfg.get("yandex.history_turns", 12))
        out = []
        for role, text in self.memory.recent_dialog(n) if self.memory else []:
            out.append({"role": "user" if role == "user" else "assistant", "text": text})
        return out

    def think(self, user_text: str, long_form: bool = False, extra: str = "", use_history: bool = True,
              temperature: float | None = None) -> Thought:
        msgs = [{"role": "system", "text": self.system_prompt(long_form, extra)}]
        if use_history:
            msgs += self.history()
        msgs.append({"role": "user", "text": user_text})
        try:
            raw = self.llm.complete(msgs, temperature=temperature,
                                    max_tokens=1800 if long_form else int(self.cfg.get("yandex.max_tokens", 800)))
        except LLMError as e:
            log.warning("%s", e)
            return Thought(text="", emotion="sadness")
        log.debug("LLM: %s", raw)
        return parse_answer(raw)

    def ask(self, prompt: str, system: str = "", temperature: float = 0.3, max_tokens: int = 800) -> str:
        """Служебный запрос без истории (перевод, рецепт в JSON, вопросы викторины…)."""
        msgs = []
        if system:
            msgs.append({"role": "system", "text": system})
        msgs.append({"role": "user", "text": prompt})
        return self.llm.complete(msgs, temperature=temperature, max_tokens=max_tokens)

    def summarize_search(self, question: str, snippets: list[dict]) -> Thought:
        src = "\n".join(f"- {s.get('title', '')}: {s.get('body', '')}" for s in snippets[:6])
        extra = ("Ниже результаты поиска в интернете. Ответь на вопрос пользователя по ним, коротко и "
                 "своими словами. Если данных не хватает — честно скажи.\n" + src)
        return self.think(question, extra=extra, use_history=False)
