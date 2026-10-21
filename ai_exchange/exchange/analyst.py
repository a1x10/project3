"""ИИ-аналитик (необязательно): раз в минуту отправляет статистику в Claude API и показывает комментарий.
Нет ключа / нет интернета / ошибка — блок просто скрыт, остальная система не страдает."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable, Optional

log = logging.getLogger("analyst")

PROMPT = (
    "Ты — спокойный аналитик на демонстрации торговой симуляции (учебная биржа, все данные синтетические). "
    "Ниже — статистика ИИ-маркет-мейкера за последние минуты. Напиши по-русски краткий комментарий для руководителей: "
    "2–3 предложения, без списков и эмодзи, простыми словами: что происходит на рынке, как ведёт себя ИИ, "
    "в чём его преимущество над простым «купи и держи». Не давай инвестиционных советов и не выдумывай чисел — "
    "используй только те, что есть в данных.\n\nДанные:\n"
)


class Analyst:
    def __init__(self, interval: float = 60.0):
        self.interval = interval
        self.key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
        self.text: Optional[str] = None
        self.updated: float = 0.0
        self.failures = 0
        self.enabled = bool(self.key)
        self._client = None
        self._last_run = time.time()
        self.running = False
        if self.enabled:
            try:
                import anthropic  # noqa: F401
            except Exception:
                self.enabled = False

    def due(self) -> bool:
        return self.enabled and not self.running and time.time() - self._last_run >= self.interval

    async def run(self, stats_fn: Callable[[], dict]) -> None:
        self.running = True
        self._last_run = time.time()
        try:
            import anthropic
            if self._client is None:
                self._client = anthropic.AsyncAnthropic(api_key=self.key, timeout=25.0, max_retries=0)
            payload = json.dumps(stats_fn(), ensure_ascii=False, indent=1)
            msg = await self._client.messages.create(
                model=self.model, max_tokens=300,
                messages=[{"role": "user", "content": PROMPT + payload}])
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
            if text:
                self.text, self.updated, self.failures = text, time.time(), 0
        except Exception as e:  # нет интернета, неверный ключ и т.п.
            self.failures += 1
            log.warning("Аналитик недоступен (%s): %s", type(e).__name__, str(e)[:120])
            if self.failures >= 3:
                self.text = None  # блок скрывается
        finally:
            self.running = False

    def view(self) -> dict:
        return {"enabled": self.enabled and self.text is not None, "text": self.text, "ts": self.updated}
