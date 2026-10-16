"""Выбор модели через .env: LLM_BACKEND=agent_sdk | messages_api.

LLM_SWITCH_AT=2026-10-23 — с этой даты автоматически используется LLM_BACKEND_AFTER/LLM_MODEL_AFTER
(промокредиты закончились -> дешёвый Haiku через Messages API), чтобы не забыть переключить руками.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Callable, Sequence

from ..config import Settings
from .base import LLM, Image, LLMError, LLMRefusal, LLMReply, ToolSpec

__all__ = ["LLM", "Image", "LLMError", "LLMRefusal", "LLMReply", "ToolSpec", "SwitchingLLM", "make_backend"]

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
    raise ValueError(f"неизвестный LLM_BACKEND: {kind}")


class SwitchingLLM:
    """Обёртка: выбирает бэкенд по дате (LLM_SWITCH_AT)."""

    def __init__(self, settings: Settings, today: Callable[[], date] = date.today,
                 factory: Callable[[str, str, Settings], LLM] = make_backend):
        self.settings = settings
        self.today = today
        self.factory = factory
        self._cache: dict[tuple, LLM] = {}

    @property
    def name(self) -> str:
        kind, model = self.settings.backend_for(self.today())
        return f"{kind}:{model}"

    def _backend(self) -> tuple[LLM, str, str]:
        kind, model = self.settings.backend_for(self.today())
        # настройки можно менять на лету из панели — тогда бэкенд пересоздаётся
        key = (kind, model, self.settings.llm_effort, self.settings.llm_web_search, self.settings.llm_timeout,
               self.settings.llm_max_call_usd)
        if key not in self._cache:
            log.info("модель: %s / %s", kind, model)
            self._cache[key] = self.factory(kind, model, self.settings)
        return self._cache[key], kind, model

    async def ask(self, *, system: str, prompt: str, tools: Sequence[ToolSpec] = (), model: str | None = None,
                  max_turns: int = 5, images: Sequence[Image] = ()) -> LLMReply:
        backend, _, default_model = self._backend()
        kwargs = {"images": images} if images else {}
        return await backend.ask(system=system, prompt=prompt, tools=tools, model=model or default_model,
                                 max_turns=max_turns, **kwargs)
