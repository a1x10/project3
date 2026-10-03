"""Сторонние навыки: любые навыки по протоколу Яндекс Диалогов (webhook), гороскоп,
такси и доставка еды (Стелла присылает ссылку на приложение), плагины из папки plugins/."""
from __future__ import annotations

import random
import re
import uuid
import xml.etree.ElementTree as ET

from ..nlp.text import best_match, contains_phrase
from .base import Reply, Skill, intent

SIGNS = {"овен": "aries", "овн": "aries", "телец": "taurus", "тельц": "taurus", "близнец": "gemini", "рак": "cancer",
         "лев": "leo", "льв": "leo", "дев": "virgo", "весы": "libra", "весов": "libra", "скорпион": "scorpio",
         "стрел": "sagittarius", "козерог": "capricorn", "водоле": "aquarius", "рыб": "pisces"}


class WebhookSession:
    """Сессия внешнего навыка (протокол Яндекс Диалогов: request/response JSON)."""

    def __init__(self, skill, cfg: dict):
        self.skill = skill
        self.cfg = cfg
        self.session_id = str(uuid.uuid4())
        self.message_id = 0
        self.state: dict = {}

    def send(self, text: str, original: str, new: bool = False) -> dict:
        body = {
            "meta": {"locale": "ru-RU", "timezone": "Europe/Moscow", "client_id": "stella/1.0",
                     "interfaces": {}},
            "session": {"message_id": self.message_id, "session_id": self.session_id, "skill_id": "stella-local",
                        "user_id": "stella-user", "user": {"user_id": "stella-user"},
                        "application": {"application_id": "stella-device"}, "new": new},
            "request": {"command": text, "original_utterance": original, "type": "SimpleUtterance",
                        "nlu": {"tokens": text.split(), "entities": [], "intents": {}},
                        "markup": {"dangerous_context": False}},
            "state": {"session": self.state, "user": {}, "application": {}},
            "version": "1.0",
        }
        self.message_id += 1
        r = self.skill.a.http.post(self.cfg["url"], json=body, timeout=10)
        r.raise_for_status()
        d = r.json()
        self.state = d.get("session_state") or self.state
        return d.get("response", {})


class External(Skill):
    name = "external"

    def __init__(self, a):
        super().__init__(a)
        self.webhooks = self.cfg.get("skills.webhooks") or []
        self.current: WebhookSession | None = None

    # ---------------------------------------------------- навыки Диалогов --
    def _reply_from(self, resp: dict) -> Reply:
        text = resp.get("text") or ""
        buttons = [b.get("title") for b in resp.get("buttons", []) if b.get("title")]
        end = bool(resp.get("end_session"))
        if end:
            self.a.end_session()
            self.current = None
        card = text + ("\n\nВарианты: " + ", ".join(buttons) if buttons else "")
        return Reply(re.sub(r"\s+", " ", text), expect_reply=not end, card=card)

    def _session(self, ctx):
        if not self.current:
            self.a.end_session()
            return None
        try:
            return self._reply_from(self.current.send(ctx.norm, ctx.text))
        except Exception as e:
            self.a.end_session()
            self.current = None
            return Reply(f"Навык перестал отвечать: {e}", emotion="sadness")

    @intent(r"\b(?:запусти|открой|включи|позови)\s+навык\s+(.+)$", r".", priority=46)
    def launch(self, ctx):
        if not self.webhooks:
            return None
        name = ctx.match.group(1) if ctx.match.lastindex else None
        hook = None
        if name:
            hook, _ = best_match(name, self.webhooks, key=lambda h: h.get("name", ""), threshold=0.6)
        else:
            for h in self.webhooks:
                if any(contains_phrase(ctx.norm, p) for p in h.get("activation", [])):
                    hook = h
                    break
        if not hook:
            return Reply(f"Навык «{name}» не подключён.") if name else None
        self.current = WebhookSession(self, hook)
        self.a.start_session(self, self._session, f"навык {hook.get('name')}")
        try:
            return self._reply_from(self.current.send("", ctx.text, new=True))
        except Exception as e:
            self.a.end_session()
            return Reply(f"Навык «{hook.get('name')}» недоступен: {e}", emotion="sadness")

    # --------------------------------------------------------------- гороскоп --
    @intent(r"\bгороскоп\w*(?:\s+(?:для|на))?\s*(\w+)?(?:\s+(?:на\s+)?(сегодня|завтра))?", priority=55, fun=True)
    def horoscope(self, ctx):
        n = ctx.norm
        sign = None
        for k, v in SIGNS.items():
            if re.search(rf"\b{k}\w*", n):
                sign = v
                break
        if not sign:
            saved = self.a.memory.get_fact("знак зодиака")
            sign = next((v for k, v in SIGNS.items() if saved and saved.lower().startswith(k)), None)
        if not sign:
            return Reply("Для какого знака зодиака?", expect_reply=True, emotion="interest")
        day = "tomorrow" if "завтра" in n else "today"
        try:
            r = self.a.http.get("https://ignio.com/r/export/utf/xml/daily/com.xml", timeout=10)
            root = ET.fromstring(r.content)
            text = (root.findtext(f"{sign}/{day}") or "").strip()
        except Exception as e:
            self.log.warning("гороскоп: %s", e)
            text = ""
        if not text and self.a.brain.available:
            text = self.a.brain.think(f"Составь шуточный добрый гороскоп для знака {sign} на {day}, 2 предложения.",
                                      use_history=False).text
        if not text:
            return Reply("Звёзды сегодня молчат — гороскоп недоступен.", emotion="sadness")
        return Reply(text, emotion=random.choice(["joy", "interest", "surprise"]), intensity=0.5)

    # ----------------------------------------------------------- такси и еда --
    @intent(r"\b(?:вызови|закажи|нужно)\s+такси\b(?:\s+(?:до|на|в)\s+(.+))?", priority=56)
    def taxi(self, ctx):
        dest = ctx.raw_group(1)
        lat, lon, _ = self.a.location()
        link = f"https://3.redirect.appmetrica.yandex.com/route?start-lat={lat}&start-lon={lon}" \
               f"&appmetrica_tracking_id=1178268795219780156&ref=stella"
        if dest:
            maps = self.a.skill("maps")
            target = maps.geocode(dest) if maps else None
            if target:
                link += f"&end-lat={target[0]}&end-lon={target[1]}"
        if self.a.notifier.configured:
            self.a.notify(f"Такси{' до ' + dest if dest else ''}: {link}", title="🚕 Яндекс Go")
            return Reply("Отправила ссылку на заказ такси в Telegram — откроется Яндекс Go с готовым маршрутом.",
                         emotion="confidence", intensity=0.5, card=link)
        return Reply("Сама заказать такси я не могу — у сервисов нет открытого API. Подключи Telegram, и я пришлю "
                     "ссылку с готовым маршрутом в приложение.", card=link)

    @intent(r"\b(?:закажи|заказать|хочу заказать)\s+(?:еду|пиццу|суши|роллы|обед|ужин|продукты|бургер\w*)\b", priority=56)
    def food(self, ctx):
        link = "https://eda.yandex.ru/" if not re.search(r"\bпродукт", ctx.norm) else "https://lavka.yandex.ru/"
        if self.a.notifier.configured:
            self.a.notify(f"Заказ: {link}", title="🍕 Доставка")
            return Reply("Отправила ссылку на доставку в Telegram. Приятного аппетита!", emotion="joy", intensity=0.5)
        return Reply("Заказать сама не могу, но вот где это сделать: Яндекс Еда или Лавка.", card=link)
