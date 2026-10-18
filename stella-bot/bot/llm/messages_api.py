"""Бэкенд v2 (после окончания промокредитов): обычный Anthropic Messages API, по умолчанию Haiku.

Те же инструменты через tool use (ручной цикл), история чата приходит в prompt из нашей БД.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from .base import Image, LLMError, LLMRefusal, LLMReply, ToolSpec

log = logging.getLogger("stella.llm.messages_api")

# $ за 1M токенов (вход, выход) — для учёта расходов в логах/бюджете
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
# Модели, у которых есть серверный фолбэк при отказе классификатора
SERVER_FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def estimate_cost(model: str, usage: Any) -> float:
    price_in, price_out = PRICES.get(model, (2.00, 10.00))
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (inp * price_in + cache_read * price_in * 0.1 + cache_write * price_in * 1.25 + out * price_out) / 1e6


class MessagesApiLLM:
    name = "messages_api"

    def __init__(self, default_model: str, effort: str | None = "low", timeout: float = 90, client: Any = None):
        import anthropic

        self.default_model = default_model
        self.effort = effort or None
        self.client = client or anthropic.AsyncAnthropic(timeout=timeout, max_retries=2)

    async def _create(self, model: str, effort: str | None = None, **kwargs: Any) -> Any:
        if effort or self.effort:
            kwargs["output_config"] = {"effort": effort or self.effort}
        if model.startswith(SERVER_FALLBACK_MODELS):
            return await self.client.beta.messages.create(
                model=model, betas=[FALLBACK_BETA], fallbacks="default", **kwargs
            )
        return await self.client.messages.create(model=model, **kwargs)

    async def ask(self, *, system: str, prompt: str, tools: Sequence[ToolSpec] = (), model: str | None = None,
                  max_turns: int = 5, images: Sequence[Image] = (), effort: str | None = None) -> LLMReply:
        import anthropic

        model = model or self.default_model
        by_name = {t.name: t for t in tools}
        tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        content: Any = [*(img.block() for img in images), {"type": "text", "text": prompt}] if images else prompt
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        # Персона и инструменты не меняются между запросами -> кешируются
        system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        cost = 0.0
        texts: list[str] = []

        for _ in range(max(1, max_turns)):
            # обдумывание (на effort high и выше — длинное) тоже расходует max_tokens; без потока SDK пускает
            # не больше ~21k — берём 20k и для инструментов, и для фоновой памяти
            kwargs: dict[str, Any] = {"max_tokens": 20000, "system": system_blocks, "messages": messages}
            if tool_defs:
                kwargs["tools"] = tool_defs
            try:
                response = await self._create(model, effort, **kwargs)
            except anthropic.RateLimitError as exc:
                raise LLMError("rate limited") from exc
            except anthropic.APIStatusError as exc:
                raise LLMError(f"api {exc.status_code}: {exc.message}") from exc
            except anthropic.APIConnectionError as exc:
                raise LLMError("api connection error") from exc

            cost += estimate_cost(model, response.usage)
            if response.stop_reason == "refusal":
                raise LLMRefusal(str(getattr(response.stop_details, "category", "") or "refusal"))

            turn = [b.text for b in response.content if b.type == "text"]
            if turn:  # последний ход после инструментов бывает пустым — тогда ответ в предыдущем
                texts = turn
            cut_tool = response.stop_reason == "max_tokens" and any(b.type == "tool_use" for b in response.content)
            if response.stop_reason != "tool_use" and not cut_tool:
                break

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                spec = by_name.get(block.name)
                if cut_tool:  # вызов оборвался на полуслове — пусть сделает короче
                    results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                    "content": "слишком длинно получилось — сделай короче и проще"})
                    continue
                try:
                    args = block.input if isinstance(block.input, dict) else json.loads(block.input or "{}")
                except ValueError:
                    args = {}
                if spec is None:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"нет такого инструмента: {block.name}", "is_error": True})
                    continue
                try:
                    out = await spec.handler(args)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
                except Exception as exc:
                    log.exception("tool %s failed", block.name)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"ошибка: {exc}", "is_error": True})
            messages.append({"role": "user", "content": results})

        return LLMReply(text="\n".join(texts), cost_usd=cost, model=model)
