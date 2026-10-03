"""Groq: быстрые открытые модели (GPT-OSS 120B, Qwen) и распознавание речи Whisper.

API совместим с OpenAI: https://api.groq.com/openai/v1. Ключ — на console.groq.com (есть бесплатный тариф).
Если Groq недоступен из вашей сети, укажите прокси: groq.proxy: "http://…" или "socks5://…"
(для SOCKS нужен пакет PySocks: pip install "requests[socks]").
"""
from __future__ import annotations

import logging
import re
import time

import requests

from .yandexgpt import LLMError

log = logging.getLogger("stella.groq")

BASE = "https://api.groq.com/openai/v1"
# Проверено на живом API (октябрь 2026): лучше всех держит формат Стеллы (теги эмоций, «КОМАНДА:», «ПОИСК:»)
# и отвечает за ~1 с — gpt-oss-120b. Список моделей аккаунта: GET /openai/v1/models.
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_FALLBACKS = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
GONE = ("model_decommissioned", "model_not_found", "model_not_active")
_HALLUCINATION = re.compile(r"(?i)субтитр|продолжение следует|спасибо за просмотр|подписывайтесь|dimatorzok|"
                            r"редактор субтитров|корректор|^\W*$")


class GroqLLM:
    name = "groq"

    def __init__(self, cfg):
        self.cfg = cfg
        self.session = requests.Session()
        proxy = cfg.get("groq.proxy")
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self._dead_models: set[str] = set()

    @property
    def available(self) -> bool:
        return bool(self.cfg.get("groq.api_key"))

    def _headers(self):
        return {"Authorization": f"Bearer {self.cfg.get('groq.api_key')}"}

    def models(self) -> list[str]:
        main = self.cfg.get("groq.model") or DEFAULT_MODEL
        fallbacks = self.cfg.get("groq.fallback_models")
        if fallbacks is None:
            fallbacks = DEFAULT_FALLBACKS
        out = [main] + [m for m in fallbacks if m != main]
        return [m for m in out if m not in self._dead_models] or [main]

    @staticmethod
    def _body(model: str, messages: list[dict], temperature: float, max_tokens: int) -> dict:
        body = {
            "model": model,
            "messages": [{"role": m["role"], "content": m["text"]} for m in messages if m.get("text")],
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if model.startswith("openai/gpt-oss"):
            # «думающие» модели: для голосового ассистента важнее скорость
            body["reasoning_effort"] = "low"
            body["include_reasoning"] = False
        elif model.startswith("qwen/"):
            body["reasoning_effort"] = "none"  # Qwen3: без режима размышлений
        return body

    def complete(self, messages: list[dict], temperature: float | None = None, max_tokens: int | None = None,
                 model: str | None = None, timeout: float = 25, budget: float = 30) -> str:
        """messages: [{"role": "system"|"user"|"assistant", "text": "..."}] — как у YandexGPT.
        budget — сколько всего секунд можно потратить на повторы и запасные модели: пока ждём Groq,
        Стелла не отвечает на другие команды, а при сбое ещё можно спросить YandexGPT."""
        if not self.available:
            raise LLMError("Groq не настроен: укажите groq.api_key")
        temp = float(self.cfg.get("groq.temperature", 0.7) if temperature is None else temperature)
        mt = int(max_tokens or self.cfg.get("groq.max_tokens", 800))
        deadline = time.monotonic() + budget
        last_err: Exception | None = None
        net_errors = 0
        for name in ([model] if model else self.models()):
            for attempt in range(3):
                left = deadline - time.monotonic()
                if left < 2:
                    raise last_err or LLMError("Groq не ответил вовремя")
                try:
                    r = self.session.post(f"{BASE}/chat/completions", json=self._body(name, messages, temp, mt),
                                          headers=self._headers(), timeout=(3.05, min(timeout, left)))
                except requests.RequestException as e:
                    last_err = LLMError(f"нет связи с Groq: {e}")
                    net_errors += 1
                    if net_errors >= 2:  # сеть, DNS или прокси: другие модели на том же сервере не помогут
                        raise last_err
                    time.sleep(1)
                    continue
                if r.status_code == 429 or r.status_code >= 500:
                    try:
                        wait = float(r.headers.get("retry-after") or 2 * (attempt + 1))
                    except ValueError:
                        wait = 2.0
                    wait = max(0.0, min(10.0, wait, deadline - time.monotonic() - 2))
                    last_err = LLMError(f"Groq {r.status_code}: {r.text[:200]}")
                    log.info("Groq %s, жду %.0f с", r.status_code, wait)
                    time.sleep(wait)
                    continue
                if r.status_code in (400, 404) and any(code in r.text for code in GONE):
                    log.warning("Модель %s больше недоступна в Groq — пробую следующую", name)
                    self._dead_models.add(name)
                    last_err = LLMError(f"модель {name} недоступна")
                    break
                if r.status_code == 401:
                    raise LLMError("Groq: неверный API-ключ (groq.api_key)")
                if r.status_code == 403:
                    raise LLMError("Groq отказал в доступе (403). Возможно, сервис недоступен из вашей страны — "
                                   "укажите прокси в groq.proxy")
                if not r.ok:
                    raise LLMError(f"Groq ответил {r.status_code}: {r.text[:300]}")
                try:
                    msg = r.json()["choices"][0]["message"]
                except (KeyError, IndexError, ValueError):
                    raise LLMError(f"Непонятный ответ Groq: {r.text[:300]}")
                text = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S)
                return text.strip()
        raise last_err or LLMError("Groq недоступен")

    # ------------------------------------------------------------- Whisper --
    def transcribe(self, wav: bytes, language: str = "ru", timeout: float | tuple = (3.05, 8)) -> str | None:
        """Распознавание речи Whisper (WAV/OGG/MP3/WebM…). -> текст или None."""
        if not self.available:
            return None
        model = self.cfg.get("groq.stt_model") or "whisper-large-v3-turbo"
        name = self.cfg.get("assistant.name", "Стелла")
        # подсказка для Whisper: без неё имя слышится как «Села» или «С тела»
        prompt = f"{name} — голосовой помощник. {name}, включи музыку. {name}, какая погода?"
        try:
            r = self.session.post(f"{BASE}/audio/transcriptions", headers=self._headers(), timeout=timeout,
                                  files={"file": ("speech.wav", wav, "audio/wav")},
                                  data={"model": model, "language": language, "response_format": "json",
                                        "temperature": "0", "prompt": prompt})
        except requests.RequestException as e:
            log.warning("Groq Whisper: нет связи (%s)", e)
            return None
        if not r.ok:
            log.warning("Groq Whisper %s: %s", r.status_code, r.text[:200])
            return None
        text = (r.json().get("text") or "").strip()
        if not text or _HALLUCINATION.search(text):
            return None  # на тишине и шуме Whisper иногда «придумывает» титры
        return text
