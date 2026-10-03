"""Простая шина событий между потоками (лицо, звук, навыки, веб-панель)."""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Callable

log = logging.getLogger("stella.events")


class EventBus:
    def __init__(self):
        self._subs: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def on(self, topic: str, fn: Callable) -> Callable:
        with self._lock:
            self._subs[topic].append(fn)
        return fn

    def off(self, topic: str, fn: Callable):
        with self._lock:
            if fn in self._subs.get(topic, []):
                self._subs[topic].remove(fn)

    def emit(self, topic: str, **data):
        with self._lock:
            direct = list(self._subs.get(topic, []))
            wildcard = list(self._subs.get("*", []))
        for fn in direct:
            try:
                fn(**data)
            except Exception:  # подписчик не должен ронять отправителя
                log.exception("Ошибка в обработчике события %s", topic)
        for fn in wildcard:  # «*» получает всё (веб-панель транслирует события в браузер)
            try:
                fn(topic=topic, **data)
            except Exception:
                log.exception("Ошибка в обработчике события %s", topic)


bus = EventBus()

# Темы событий:
#   emotion(name, intensity, hold)      — показать эмоцию
#   state(state)                        — idle / listening / thinking / speaking / sleep
#   mic_level(level)                    — громкость микрофона 0..1 (для анимации)
#   speech_level(level)                 — громкость речи Стеллы 0..1 (рот)
#   heard(text, whisper)                — распознанная фраза
#   reply(text, emotion)                — ответ Стеллы
#   notify(text, title, urgent)         — уведомление в Telegram/ntfy
#   touch(x, y)                         — касание экрана
#   gaze(x, y)                          — куда смотреть (-1..1), например на лицо с камеры
#   face_seen(present)                  — камера увидела/потеряла человека
