"""Telegram-бот: Стелла в телефоне откуда угодно — текстом и голосовыми сообщениями,
плюс уведомления (будильники, напоминания, радионяня, «найди телефон»)."""
from __future__ import annotations

import logging
import threading
import time

import requests

from ..audio.stt import decode_audio_file, encode_ogg_opus, recognize_pcm

log = logging.getLogger("stella.telegram")

HELP = ("Я Стелла 🙂 Пиши мне как голосом дома: «включи музыку», «что купить», «напомни завтра в 9 позвонить маме», "
        "«какая погода», «скажи на кухне: ужин готов». Голосовые сообщения тоже понимаю.\n\n"
        "/list — список покупок\n/todo — дела\n/notes — заметки\n/alarms — будильники и напоминания\n"
        "/say текст — сказать вслух дома\n/status — как дела у Стеллы")


class TelegramBot(threading.Thread):
    def __init__(self, assistant):
        super().__init__(daemon=True, name="telegram")
        self.a = assistant
        self.cfg = assistant.cfg
        self.token = self.cfg.get("telegram.token")
        self.allowed = {int(x) for x in (self.cfg.get("telegram.allowed_users") or [])}
        self.base = f"https://api.telegram.org/bot{self.token}"
        self.http = requests.Session()
        self.offset = 0
        assistant.notifier.telegram = self

    def api(self, method: str, timeout: float = 30, files=None, **params):
        r = self.http.post(f"{self.base}/{method}", data=params, files=files, timeout=timeout)
        d = r.json()
        if not d.get("ok"):
            raise RuntimeError(d.get("description"))
        return d["result"]

    def send(self, chat_id: int, text: str):
        for i in range(0, len(text), 4000):
            try:
                self.api("sendMessage", chat_id=chat_id, text=text[i:i + 4000])
            except Exception as e:
                log.warning("sendMessage: %s", e)

    def run(self):
        log.info("Telegram-бот запущен")
        while not self.a.stop_event.is_set():
            try:
                updates = self.http.get(f"{self.base}/getUpdates",  # долгий опрос: ответ приходит сразу при сообщении
                                        params={"timeout": 50, "offset": self.offset,
                                                "allowed_updates": '["message"]'}, timeout=60).json()
                if not updates.get("ok"):
                    log.warning("Telegram: %s", updates.get("description"))
                    time.sleep(10)
                    continue
                for upd in updates["result"]:
                    self.offset = upd["update_id"] + 1
                    msg = upd.get("message")
                    if msg:
                        threading.Thread(target=self.handle, args=(msg,), daemon=True).start()
            except requests.RequestException as e:
                log.info("Telegram: нет связи (%s)", e)
                time.sleep(5)
            except Exception:
                log.exception("Telegram")
                time.sleep(5)

    def handle(self, msg: dict):
        chat = msg["chat"]["id"]
        user = msg.get("from", {})
        uid = user.get("id")
        if uid not in self.allowed:
            if (msg.get("text") or "").startswith("/start"):
                self.send(chat, f"Привет! Твой Telegram ID: {uid}. Добавь его в config.yaml (telegram.allowed_users), "
                                f"чтобы я тебя слушалась.")
            log.warning("Telegram: сообщение от неизвестного пользователя %s (%s)", uid, user.get("username"))
            return
        text = (msg.get("text") or "").strip()
        voice = msg.get("voice") or msg.get("audio")
        heard_voice = False
        if voice:
            text = self._recognize(voice)
            heard_voice = True
            if not text:
                self.send(chat, "Не разобрала голосовое 😔")
                return
            self.send(chat, f"🎙 {text}")
        if not text:
            return
        if text.startswith("/"):
            self._command(chat, text)
            return
        reply = self.a.ask(text, source="telegram", chat_id=chat, timeout=120)
        answer = reply.card if reply.card and len(reply.card) > len(reply.text or "") else reply.text
        if heard_voice and self.cfg.get("telegram.voice_replies", True) and reply.text:
            if self._send_voice(chat, reply.text, reply.emotion):
                if reply.card and reply.card != reply.text:
                    self.send(chat, reply.card)
                return
        self.send(chat, answer or "👌")

    def _recognize(self, voice: dict) -> str:
        try:
            info = self.api("getFile", file_id=voice["file_id"])
            data = self.http.get(f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}", timeout=30).content
            pcm = decode_audio_file(data)
            return recognize_pcm(self.cfg, pcm) if pcm is not None else ""
        except Exception as e:
            log.warning("голосовое: %s", e)
            return ""

    def _send_voice(self, chat: int, text: str, emotion) -> bool:
        samples, sr = self.a.tts.synth(text, emotion or "neutral")
        if samples is None:
            return False
        ogg = encode_ogg_opus(samples, sr)
        if not ogg:
            return False
        try:
            self.api("sendVoice", files={"voice": ("reply.ogg", ogg, "audio/ogg")}, chat_id=chat)
            return True
        except Exception as e:
            log.warning("sendVoice: %s", e)
            return False

    def _command(self, chat: int, text: str):
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        m = self.a.memory
        if cmd in ("/start", "/help"):
            self.send(chat, HELP)
        elif cmd == "/list":
            items = m.list_items("покупки")
            self.send(chat, "🛒 Покупки:\n" + "\n".join("• " + i["text"] for i in items) if items else "Список покупок пуст.")
        elif cmd == "/todo":
            items = m.list_items("дела")
            self.send(chat, "✅ Дела:\n" + "\n".join("• " + i["text"] for i in items) if items else "Дел нет.")
        elif cmd == "/notes":
            notes = m.notes(20)
            self.send(chat, "📝 Заметки:\n" + "\n".join("• " + n["text"] for n in notes) if notes else "Заметок нет.")
        elif cmd == "/alarms":
            r = self.a.ask("какие будильники", source="telegram")
            r2 = self.a.ask("какие напоминания", source="telegram")
            self.send(chat, f"{r.text}\n{r2.card or r2.text}")
        elif cmd == "/say" and arg:
            threading.Thread(target=self.a.say, args=(arg,), daemon=True).start()
            self.send(chat, "🔊 Сказала дома.")
        elif cmd == "/status":
            mood = self.a.mood
            self.send(chat, f"Настроение: {mood.level}, раздражение {mood.irritation:.1f}/10, "
                            f"симпатия {mood.affection:.1f}/10.")
        else:
            self.send(chat, HELP)
