"""Выбор модели через .env: LLM_BACKEND=agent_sdk | messages_api.

LLM_SWITCH_AT=2026-10-23 — с этой даты автоматически используется LLM_BACKEND_AFTER/LLM_MODEL_AFTER
(промокредиты закончились): off — модель выключена, свой баланс не тратится; messages_api — дальше за свой баланс.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Callable, Sequence

from ..config import Settings
from .base import LLM, Image, LLMError, LLMOff, LLMRefusal, LLMReply, ToolSpec

__all__ = ["LLM", "Image", "LLMError", "LLMOff", "LLMRefusal", "LLMReply", "ToolSpec", "SwitchingLLM",
           "make_backend"]

log = logging.getLogger("stella.llm")


def make_backend(kind: str, model: str, settings: Settings) -> LLM:
    if kind == "agent_sdk":
        from .agent_sdk import AgentSdkLLM

        return AgentSdkLLM(
            default_model=model,
            effort=settings.llm_effort,
            sandbox_dir=os.path.join(settings.data_dir, "agent_sandbox"),
            timeout=settings.llm_timeout,
            max_budget_usd=settings.llm_max_call_usd,
            web_search=settings.llm_web_search,
        )
    if kind == "messages_api":
        from .messages_api import MessagesApiLLM

        return MessagesApiLLM(default_model=model, effort=settings.llm_effort, timeout=settings.llm_timeout)
    from ..keys import PROVIDERS, STORE

    if kind in PROVIDERS:  # Groq, OpenRouter, Gemini, OpenAI — ключи из панели
        from .openai_compat import OpenAICompatLLM

        return OpenAICompatLLM(kind, model, STORE, effort=settings.llm_effort, timeout=settings.llm_timeout)
    raise ValueError(f"неизвестный LLM_BACKEND: {kind}")


class SwitchingLLM:
    """Обёртка: выбирает бэкенд по дате (LLM_SWITCH_AT)."""

    def __init__(self, settings: Settings, today: Callable[[], date] | None = None,
                 factory: Callable[[str, str, Settings], LLM] = make_backend):
        self.settings = settings
        self.today = today or settings.local_today
        self.factory = factory
        self._cache: dict[tuple, LLM] = {}

    @property
    def name(self) -> str:
        kind, model = self.settings.backend_for(self.today())
        return f"{kind}:{model}"

    def _backend(self) -> tuple[LLM, str, str]:
        kind, model = self.settings.backend_for(self.today())
        if kind == "off":
            raise LLMOff("модель выключена (LLM_BACKEND_AFTER=off) — запрос не отправлен")
        # настройки можно менять на лету из панели — тогда бэкенд пересоздаётся
        key = (kind, model, self.settings.llm_effort, self.settings.llm_web_search, self.settings.llm_timeout,
               self.settings.llm_max_call_usd)
        if key not in self._cache:
            log.info("модель: %s / %s", kind, model)
            self._cache[key] = self.factory(kind, model, self.settings)
        return self._cache[key], kind, model

    async def ask(self, *, system: str, prompt: str, tools: Sequence[ToolSpec] = (), model: str | None = None,
                  max_turns: int = 5, images: Sequence[Image] = (), effort: str | None = None) -> LLMReply:
        backend, _, default_model = self._backend()
        kwargs: dict[str, Any] = {"images": images} if images else {}
        if effort:
            kwargs["effort"] = effort
        return await backend.ask(system=system, prompt=prompt, tools=tools, model=model or default_model,
                                 max_turns=max_turns, **kwargs)
