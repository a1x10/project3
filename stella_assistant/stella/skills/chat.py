"""Генерация текстов через ИИ (Groq / YandexGPT): стихи, сказки, сценарии, письма, поздравления, идеи."""
from __future__ import annotations

import re

from .base import Reply, Skill, intent

_WHAT = (r"(?:стих\w*|стишок|поэм\w*|песн\w*|рассказ\w*|историю|сказк\w*|сценари\w*|письм\w*|поздравлени\w*|"
         r"тост|иде\w*|шутк\w*|текст\w*|речь|сочинени\w*|эссе|пост\w*|рифм\w*|слоган\w*|план\w*|список\w*|"
         r"резюме|отзыв\w*|описани\w*|статью|сообщени\w*|комплимент\w*|частушк\w*|хокку|лимерик\w*|"
         r"название|имя для|никнейм)")


class Chat(Skill):
    name = "chat"

    @intent(r"\b(?:напиши|сочини|придумай|составь|сгенерируй|набросай|подготовь|создай)\b.*\b" + _WHAT,
            r"\b(?:дай|подскажи|предложи)\b.*\bиде\w*", priority=40)
    def generate(self, ctx):
        brain = self.a.brain
        if not brain.available:
            return Reply("Чтобы сочинять тексты, мне нужен ИИ: добавь ключ Groq (groq.api_key) "
                         "или YandexGPT в настройки.", emotion="sadness")
        if ctx.source == "voice":
            ctx.say("Сейчас придумаю…", emotion="thinking")
        th = brain.think(ctx.text, long_form=True,
                         extra="Это творческое задание: напиши готовый текст целиком, без вступлений и пояснений.")
        if not th.text:
            return Reply("Вдохновение не пришло — облако не отвечает. Попробуй позже.", emotion="sadness")
        text = th.text
        reply = Reply(text, emotion=th.emotion or "joy", card=text)
        if ctx.source == "voice" and len(text) > 600 and self.a.notifier.configured:
            self.a.notifier.send(text, title="Текст от Стеллы")
            reply.text = re.sub(r"\s+", " ", text)
            reply.data["sent"] = True
        return reply

    @intent(r"\b(?:продолжай|продолжи|дальше расскажи|а что было дальше)\b", priority=30)
    def go_on(self, ctx):
        if not self.a.brain.available:
            return None
        th = self.a.brain.think("Продолжи свой предыдущий ответ.", long_form=True)
        return Reply(th.text, emotion=th.emotion) if th.text else None
