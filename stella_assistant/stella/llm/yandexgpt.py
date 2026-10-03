"""Клиент YandexGPT (Yandex Cloud Foundation Models, синхронный REST API)."""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("stella.llm")

COMPLETION_URL = "https://ai.api.cloud.yandex.net/foundationModels/v1/completion"


class LLMError(RuntimeError):
    pass


class YandexGPT:
    def __init__(self, cfg):
        self.cfg = cfg
        self.session = requests.Session()

    @property
    def available(self) -> bool:
        return bool((self.cfg.get("yandex.api_key") or self.cfg.get("yandex.iam_token"))
                    and self.cfg.get("yandex.folder_id"))

    def _headers(self):
        key, iam = self.cfg.get("yandex.api_key"), self.cfg.get("yandex.iam_token")
        if key:  # API-ключ сервисного аккаунта: каталог берётся из аккаунта
            return {"Authorization": f"Api-Key {key}", "x-data-logging-enabled": "false"}
        return {"Authorization": f"Bearer {iam}", "x-folder-id": self.cfg.get("yandex.folder_id", ""),
                "x-data-logging-enabled": "false"}

    def model_uri(self, model: str | None = None) -> str:
        """yandexgpt-5-lite / yandexgpt-5-pro / yandexgpt-5.1 / aliceai-llm -> gpt://<каталог>/<модель>."""
        model = model or self.cfg.get("yandex.gpt_model", "yandexgpt-5-lite")
        if model.startswith("gpt://"):
            return model
        return f"gpt://{self.cfg.get('yandex.folder_id')}/{model}"

    def complete(self, messages: list[dict], temperature: float | None = None, max_tokens: int | None = None,
                 model: str | None = None, timeout: float = 40) -> str:
        """messages: [{"role": "system"|"user"|"assistant", "text": "..."}]"""
        if not self.available:
            raise LLMError("YandexGPT не настроен: укажите yandex.api_key и yandex.folder_id")
        body = {
            "modelUri": self.model_uri(model),
            "completionOptions": {
                "stream": False,
                "temperature": min(1.0, max(0.0, float(self.cfg.get("yandex.temperature", 0.6)
                                                       if temperature is None else temperature))),
                "maxTokens": str(int(max_tokens or self.cfg.get("yandex.max_tokens", 800))),
            },
            "messages": [m for m in messages if m.get("text")],
        }
        last_err = None
        for attempt in range(3):
            try:
                r = self.session.post(COMPLETION_URL, json=body, headers=self._headers(), timeout=timeout)
            except requests.RequestException as e:
                last_err = e
                time.sleep(1 + attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = LLMError(f"{r.status_code}: {r.text[:200]}")
                time.sleep(1.5 * (attempt + 1))
                continue
            if not r.ok:
                raise LLMError(f"YandexGPT ответил {r.status_code}: {r.text[:300]}")
            data = r.json()
            try:
                alt = data["result"]["alternatives"][0]
            except (KeyError, IndexError):
                raise LLMError(f"Непонятный ответ YandexGPT: {str(data)[:300]}")
            status = alt.get("status", "")
            text = alt.get("message", {}).get("text", "")
            if "CONTENT_FILTER" in status and not text:
                return "[neutral] Давай лучше поговорим о чём-нибудь другом."
            return text.strip()
        raise LLMError(f"YandexGPT недоступен: {last_err}")
