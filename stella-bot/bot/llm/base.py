"""Интерфейс модели. Остальной код не знает, что внутри: Agent SDK, Messages API или своя модель."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, Sequence

ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema
    handler: ToolHandler


@dataclass(frozen=True)
class Image:
    """Картинка для модели (фото, стикер, скриншот): тип и данные в base64."""
    media_type: str
    data_b64: str

    def block(self) -> dict[str, Any]:
        return {"type": "image", "source": {"type": "base64", "media_type": self.media_type, "data": self.data_b64}}


@dataclass
class LLMReply:
    text: str
    cost_usd: float = 0.0
    model: str = ""


class LLMError(RuntimeError):
    """Модель недоступна / упала / превышен лимит."""


class LLMRefusal(LLMError):
    """Модель отказалась отвечать (stop_reason=refusal)."""


class LLM(Protocol):
    name: str

    async def ask(
        self,
        *,
        system: str,
        prompt: str,
        tools: Sequence[ToolSpec] = (),
        model: str | None = None,
        max_turns: int = 5,
        images: Sequence[Image] = (),
        effort: str | None = None,
    ) -> LLMReply:
        """Один ответ модели (с вызовами наших инструментов внутри). Возвращает итоговый текст.
        images — фото/стикеры, которые модель должна увидеть вместе с текстом. effort — своя глубина обдумывания
        для этого вызова (иначе LLM_EFFORT)."""
        ...
