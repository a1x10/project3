"""Базовые команды: стоп, время, дата, кто ты, что умеешь, повтори, сон, шёпот, эмоции."""
from __future__ import annotations

import random
import socket
import time
from datetime import datetime

from ..core.events import bus
from ..face.emotions import EMOTION_NAMES_RU, EMOTIONS, resolve
from ..nlp.timeparse import MONTHS_GEN, WEEKDAYS_NOM
from .base import Reply, Skill, intent

CAPABILITIES = (
    "Я умею включать музыку из Яндекс Музыки, радио, подкасты и аудиокниги, узнавать, что за песня играет, "
    "ставить будильники, таймеры и напоминания, вести списки покупок и заметки, рассказывать погоду, "
    "про пробки и дорогу, искать организации, управлять умным домом и телевизором, считать, переводить, "
    "отвечать на вопросы и сочинять тексты, читать новости и рецепты, играть в города и викторины, "
    "работать радионяней и звонить в другие комнаты. А ещё у меня есть характер — не обижай меня!"
)


def local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class System(Skill):
    name = "system"

    @intent(r"^(?:стоп|хватит|замолчи|тихо|перестань|остановись|прекрати|отмена|отмени|достаточно|помолчи|"
            r"выключи будильник|выключи таймер|выключись|все хватит)(?: пожалуйста)?$", priority=100)
    def stop_cmd(self, ctx):
        a = self.a
        if a.ringing:
            a.ringing.stop()
            return Reply("", speak=False, emotion="neutral")
        if a.speaker.speaking:
            a.speaker.stop()
        if a.player.is_playing():
            a.player.pause()
        a.end_session()
        return Reply("", speak=False, emotion="neutral")

    @intent(r"\b(?:который час|сколько (?:сейчас )?времени|какое (?:сейчас )?время|время сейчас|скажи время)\b",
            priority=60)
    def time_now(self, ctx):
        now = datetime.now()
        return Reply(f"Сейчас {now.hour}:{now.minute:02d}.")

    @intent(r"\b(?:какое (?:сегодня )?число|какая (?:сегодня )?дата|какой (?:сегодня )?день(?: недели)?|"
            r"сегодня какое число|какое число сегодня)\b", priority=60)
    def date_now(self, ctx):
        now = datetime.now()
        return Reply(f"Сегодня {WEEKDAYS_NOM[now.weekday()]}, {now.day} {MONTHS_GEN[now.month - 1]}.")

    @intent(r"\b(?:как тебя зовут|кто ты такая|кто ты|ты кто|твое имя|представься)\b", priority=55)
    def who(self, ctx):
        return Reply(f"Я {self.a.name} — домашний помощник с живыми глазами. Могу помочь с музыкой, "
                     f"погодой, будильниками и умным домом. А ещё я умею радоваться и обижаться!", emotion="joy")

    @intent(r"\bчто ты (?:умеешь|можешь)(?: делать)?$|\bтвои (?:возможности|функции|навыки)\b|"
            r"^(?:помощь|справка|помоги разобраться)$", priority=55)
    def help(self, ctx):
        return Reply(CAPABILITIES, emotion="confidence")

    @intent(r"^(?:ну |а |привет )?(?:как (?:у тебя )?дела|как ты|как настроение|как поживаешь|как жизнь|"
            r"как твои дела|как ты себя чувствуешь)(?: стелла)?$", priority=52)
    def how_are_you(self, ctx):
        lvl = self.a.mood.level
        if lvl == "furious":
            return Reply("Плохо. Меня обидели, и я до сих пор злюсь.", emotion="anger")
        if lvl in ("angry", "annoyed"):
            return Reply("Было бы лучше, если бы со мной разговаривали вежливо.", emotion="contempt")
        if self.a.mood.is_night():
            return Reply("Немного сонно, но для тебя я всегда на связи.", emotion="boredom", intensity=0.5)
        return Reply(random.choice([
            "Отлично! Глазки блестят, микрофон слышит. А у тебя как?",
            "Прекрасно! Готова помогать. Как твои дела?",
            "Хорошо! Только немного скучала без тебя. Как ты?",
        ]), emotion="joy", expect_reply=True)

    @intent(r"^(?:повтори|еще раз|что ты сказала|не расслышал\w*|повтори пожалуйста|скажи еще раз)$", priority=70)
    def repeat(self, ctx):
        return Reply(self.a.last_reply or "Я пока ничего не говорила.")

    @intent(r"\b(?:спи|засыпай|иди спать|режим сна|усни|поспи)\b", priority=58)
    def sleep(self, ctx):
        self.a.scheduler.after(3.0, self.a.mood.sleep, "sleep")
        return Reply(random.choice(["Сладких снов! Если что — зови.", "Хорошо, я посплю. Зови, если понадоблюсь."]),
                     emotion="love", intensity=0.5)

    @intent(r"\b(?:проснись|просыпайся|подъем|не спи)\b", priority=58)
    def wake(self, ctx):
        self.a.mood.wake()
        return Reply("Я тут! Уже проснулась.", emotion="surprise")

    @intent(r"\b(?:говори|разговаривай|отвечай)\s+(?:шепотом|шепчи|тише|тихо)\b|\bрежим шепота\b|^шепотом$",
            priority=65)
    def whisper_on(self, ctx):
        self.a.whisper_mode = True
        return Reply("Хорошо, буду говорить шёпотом.", whisper=True, emotion="love", intensity=0.4)

    @intent(r"\b(?:говори|разговаривай|отвечай)\s+(?:нормально|громко|обычно|в полный голос|нормальным голосом)\b|"
            r"\bвыключи режим шепота\b", priority=65)
    def whisper_off(self, ctx):
        self.a.whisper_mode = False
        self.a.last_whisper = False
        return Reply("Хорошо, снова говорю нормально.", whisper=False, emotion="joy")

    @intent(r"\b(?:покажи|изобрази|сделай|сыграй)\s+(?:все\s+)?(?:эмоции|эмоцию|лицо|мордочку|глаза)\s*(\w*)",
            r"\b(?:покажи|изобрази|сыграй)\s+(радость|счастье|грусть|печаль|злость|гнев|ярость|страх|испуг|"
            r"удивление|любовь|влюбленность|симпатию|интерес|любопытство|презрение|отвращение|уверенность|"
            r"скуку|усталость)\b", priority=62)
    def show_emotion(self, ctx):
        word = ctx.group(1)
        if not word or ("все" in ctx.norm.split() and "эмоции" in ctx.norm):
            if self.a.face:
                self.a.face.demo = True
                self.a.scheduler.after(len(EMOTIONS) * 4 + 8, lambda: setattr(self.a.face, "demo", False), "demo")
            return Reply("Смотри! Радость, грусть, злость, страх, удивление, симпатия, интерес, презрение, "
                         "уверенность и скука.", emotion="joy")
        name = resolve(word)
        if name == "neutral":
            return Reply(f"Я не знаю эмоцию «{word}». Попробуй: радость, грусть, злость, страх или удивление.")
        bus.emit("emotion", name=name, intensity=1.0, hold=8)
        phrases = {
            "joy": "Вот так я радуюсь!", "sadness": "А так я грущу…", "anger": "Р-р-р! Вот так я злюсь!",
            "fear": "Ой! Мне страшно!", "surprise": "Ого! Вот это да!", "love": "А так я смотрю на тех, кто мне нравится.",
            "interest": "Мне очень интересно!", "contempt": "Фи. Вот так — с презрением.",
            "confidence": "Смотрю прямо в глаза. Я уверена в себе.", "boredom": "Скучно-о-о…",
        }
        return Reply(phrases.get(name, EMOTION_NAMES_RU.get(name, name)), emotion=name)

    @intent(r"\b(?:какой (?:у тебя )?(?:ip|айпи)(?: адрес)?|адрес (?:веб )?панели|(?:веб|web) панель|как тебя настроить)\b",
            priority=55)
    def ip(self, ctx):
        port = self.cfg.get("web.port", 8765)
        proto = "https" if self.cfg.get("web.https") else "http"
        ip = local_ip()
        return Reply(f"Моя панель управления: {proto}://{ip}:{port}. Открой её в браузере телефона или компьютера.",
                     card=f"{proto}://{ip}:{port}")

    @intent(r"\b(?:сколько ты работаешь|аптайм|время работы)\b", priority=50)
    def uptime(self, ctx):
        try:
            secs = float(open("/proc/uptime").read().split()[0])
        except OSError:
            secs = time.monotonic()
        h, m = int(secs // 3600), int(secs % 3600 // 60)
        return Reply(f"Работаю без перерыва {h} ч {m} мин.")
