"""Бэкенд для Groq, OpenRouter, Gemini, OpenAI — у всех один формат (OpenAI Chat Completions).

Ключи берутся из панели (bot/keys.py): несколько ключей одного провайдера — по очереди; лимит (429) или
перегрузка — пауза ключу и сразу следующий; ключ не принят (401/403) — следующий.
Инструменты — те же (function calling), ручной цикл как в messages_api.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

import httpx

from .base import Image, LLMError, LLMReply, ToolSpec

log = logging.getLogger("stella.llm.openai_compat")

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


def _retry_after(resp: httpx.Response) -> float:
    for name in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        raw = resp.headers.get(name, "")
        try:
            return float(raw.rstrip("s")) if raw else 0.0
        except ValueError:
            continue
    return 0.0


def _error_text(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
        msg = err.get("message") if isinstance(err, dict) else err
    except ValueError:
        msg = resp.text
    return f"{resp.status_code}: {str(msg or '')[:160]}"


class OpenAICompatLLM:
    def __init__(self, provider: str, default_model: str, store: Any, effort: str | None = None,
                 timeout: float = 120, transport: httpx.AsyncBaseTransport | None = None):
        from ..keys import PROVIDERS

        self.provider = PROVIDERS[provider]
        self.name = provider
        self.default_model = (default_model if default_model and not default_model.startswith("claude")
                              else self.provider.default_model)
        self.store = store
        self.effort = effort
        self.timeout = timeout
        self.transport = transport

    def _model(self, model: str | None) -> str:
        # модели Anthropic (память, страницы) этим провайдерам не подходят — тогда своя модель по умолчанию
        if not model or model.startswith("claude"):
            return self.default_model
        return model

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        keys = self.store.candidates(self.provider.id)
        if not keys:
            raise LLMError(f"нет ключей {self.provider.name} — добавь в панели («Ключи»)")
        errors = []
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as http:
            for item in keys:
                try:
                    resp = await http.post(f"{self.provider.base_url}/chat/completions", json=body,
                                           headers={"Authorization": f"Bearer {item.key}"})
                except httpx.HTTPError as exc:
                    errors.append(f"связь: {type(exc).__name__}")
                    await self.store.failed(item, f"нет связи ({type(exc).__name__})", 30)
                    continue
                if resp.status_code == 200:
                    await self.store.used(item)
                    return resp.json()
                text = _error_text(resp)
                errors.append(text)
                if resp.status_code in RETRY_STATUS:  # лимит или перегрузка — этому ключу пауза, берём следующий
                    await self.store.failed(item, f"лимит/перегрузка ({text})", _retry_after(resp) or 60)
                    continue
                if resp.status_code in (401, 403):
                    await self.store.failed(item, f"ключ не принят ({text})")
                    continue
                if resp.status_code == 400 and "image" in text.lower() and _has_images(body):
                    raise _NoImages()
                raise LLMError(f"{self.provider.name} {text}")
        raise LLMError(f"{self.provider.name}: все ключи не сработали — " + "; ".join(errors)[:300])

    async def ask(self, *, system: str, prompt: str, tools: Sequence[ToolSpec] = (), model: str | None = None,
                  max_turns: int = 5, images: Sequence[Image] = (), effort: str | None = None) -> LLMReply:
        model = self._model(model)
        by_name = {t.name: t for t in tools}
        tool_defs = [{"type": "function", "function": {"name": t.name, "description": t.description[:1024],
                                                       "parameters": t.input_schema}} for t in tools]
        if images:
            content: Any = [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": f"data:{i.media_type};base64,{i.data_b64}"}}
                for i in images]
        else:
            content = prompt
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        text = ""
        for _ in range(max(1, max_turns)):
            body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 4096}
            if tool_defs:
                body["tools"] = tool_defs
            level = effort or self.effort
            if level and "gpt-oss" in model:  # у gpt-oss есть глубина обдумывания: low / medium / high
                body["reasoning_effort"] = {"xhigh": "high", "max": "high"}.get(level, level)
            try:
                data = await self._post(body)
            except _NoImages:  # модель не видит картинки — без них, но с пометкой
                messages[1]["content"] = prompt + "\n\n(Фото приложены, но эта модель их не видит — скажи об этом.)"
                data = await self._post(body | {"messages": messages})
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            if msg.get("content"):
                text = msg["content"]
            calls = msg.get("tool_calls") or []
            if not calls:
                break
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for call in calls:
                fn = call.get("function") or {}
                spec = by_name.get(fn.get("name", ""))
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                if spec is None:
                    out = f"нет такого инструмента: {fn.get('name')}"
                else:
                    try:
                        out = await spec.handler(args if isinstance(args, dict) else {})
                    except Exception as exc:
                        log.exception("tool %s failed", fn.get("name"))
                        out = f"ошибка: {exc}"
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": str(out)})
        return LLMReply(text=text.strip(), cost_usd=0.0, model=f"{self.provider.id}:{model}")


class _NoImages(Exception):
    pass


def _has_images(body: dict[str, Any]) -> bool:
    return any(isinstance(m.get("content"), list) for m in body.get("messages", []))


async def check_key(provider: str, key: str, transport: httpx.AsyncBaseTransport | None = None) -> tuple[bool, str,
                                                                                                         list[str]]:
    """Проверить ключ: список моделей провайдера (бесплатно, без генерации). -> (ok, пояснение, модели)."""
    from ..keys import PROVIDERS

    p = PROVIDERS[provider]
    try:
        async with httpx.AsyncClient(timeout=20, transport=transport) as http:
            resp = await http.get(f"{p.base_url}/models", headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        return False, f"нет связи с {p.name} ({type(exc).__name__})", []
    if resp.status_code != 200:
        return False, f"{p.name} не принял ключ — {_error_text(resp)}", []
    try:
        ids = sorted(str(m.get("id")) for m in resp.json().get("data", []) if m.get("id"))
    except (ValueError, AttributeError):
        ids = []
    return True, f"ключ работает{f', моделей: {len(ids)}' if ids else ''}", ids[:300]
