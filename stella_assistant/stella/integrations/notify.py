"""Уведомления на телефон: Telegram-бот и/или ntfy.sh (push с высоким приоритетом)."""
from __future__ import annotations

import logging
import threading

import requests

log = logging.getLogger("stella.notify")


class Notifier:
    def __init__(self, cfg):
        self.cfg = cfg
        self.telegram = None  # заполняется, когда стартует бот (integrations.telegram_bot)

    def chats(self) -> list[int]:
        chat = self.cfg.get("telegram.notify_chat")
        if chat:
            return [int(chat)]
        return [int(u) for u in self.cfg.get("telegram.allowed_users") or []]

    def send(self, text: str, title: str | None = None, urgent: bool = False, wait: bool = False):
        t = threading.Thread(target=self._send, args=(text, title, urgent), daemon=True)
        t.start()
        if wait:
            t.join(15)

    def _send(self, text, title, urgent):
        sent = False
        token = self.cfg.get("telegram.token")
        if token:
            body = f"<b>{_esc(title)}</b>\n{_esc(text)}" if title else _esc(text)
            for chat in self.chats():
                try:
                    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                  data={"chat_id": chat, "text": body, "parse_mode": "HTML"}, timeout=10)
                    sent = True
                except requests.RequestException as e:
                    log.warning("Telegram: %s", e)
        topic = self.cfg.get("notify.ntfy_topic")
        if topic:
            server = self.cfg.get("notify.ntfy_server", "https://ntfy.sh").rstrip("/")
            try:  # JSON-публикация: кириллица в заголовках HTTP не допускается
                requests.post(server + "/", json={"topic": topic, "title": title or "Стелла", "message": text,
                                                  "priority": 5 if urgent else 3,
                                                  "tags": ["rotating_light"] if urgent else ["robot"]}, timeout=10)
                sent = True
            except requests.RequestException as e:
                log.warning("ntfy: %s", e)
        if not sent:
            log.info("Уведомление (некуда отправить): %s %s", title or "", text)
        return sent

    @property
    def configured(self) -> bool:
        return bool((self.cfg.get("telegram.token") and self.chats()) or self.cfg.get("notify.ntfy_topic"))


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
