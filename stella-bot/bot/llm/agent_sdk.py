"""Бэкенд v1: Claude Agent SDK (расходует промокредиты Anthropic, которые работают только через SDK).

Безопасность: пишут посторонние люди, поэтому у агента НЕТ встроенных инструментов Claude Code
(tools=[] + disallowed_tools), нет настроек/CLAUDE.md с диска, cwd — пустая папка-песочница,
разрешены только наши инструменты из in-process MCP-сервера.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Sequence

from .base import Image, LLMError, LLMRefusal, LLMReply, ToolSpec

log = logging.getLogger("stella.llm.agent_sdk")

SERVER_NAME = "stella"
BUILTIN_TOOLS = [
    "Bash", "BashOutput", "KillShell", "KillBash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "Glob", "Grep", "LS", "WebFetch", "WebSearch", "Task", "Agent", "TodoWrite", "ExitPlanMode",
    "SlashCommand", "Skill", "ListMcpResourcesTool", "ReadMcpResourceTool", "Monitor", "CronCreate",
]


async def _with_images(prompt: str, images: Sequence[Image]):
    """Картинки передаются в «потоковом» режиме SDK: одно сообщение пользователя с блоками image + text."""
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": [*(img.block() for img in images), {"type": "text", "text": prompt}]},
        "parent_tool_use_id": None,
    }


class AgentSdkLLM:
    name = "agent_sdk"

    def __init__(self, default_model: str, effort: str | None = "low", sandbox_dir: str = "data/agent_sandbox",
                 max_budget_usd: float | None = 1.5, timeout: float = 180, web_search: bool = False):
        self.default_model = default_model
        self.effort = effort or None
        # WebSearch выполняется на стороне Anthropic: доступа к серверу не даёт. WebFetch не включаем —
        # он ходил бы по ссылкам с нашего сервера (а там внутренние адреса docker-сети).
        self.web_search = web_search
        self.sandbox_dir = os.path.abspath(sandbox_dir)
        self.max_budget_usd = max_budget_usd
        self.timeout = timeout
        os.makedirs(self.sandbox_dir, exist_ok=True)

    def _options(self, system: str, tools: Sequence[ToolSpec], model: str, max_turns: int,
                 effort: str | None = None) -> Any:
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool

        sdk_tools = []
        for spec in tools:
            def make(spec: ToolSpec):
                async def handler(args: dict[str, Any]) -> dict[str, Any]:
                    try:
                        text = await spec.handler(args or {})
                        return {"content": [{"type": "text", "text": text}]}
                    except Exception as exc:  # ошибка инструмента -> модель увидит и ответит по-человечески
                        log.exception("tool %s failed", spec.name)
                        return {"content": [{"type": "text", "text": f"ошибка: {exc}"}], "is_error": True}

                return tool(spec.name, spec.description, spec.input_schema)(handler)

            sdk_tools.append(make(spec))

        mcp_servers = {SERVER_NAME: create_sdk_mcp_server(SERVER_NAME, tools=sdk_tools)} if sdk_tools else {}
        builtin = ["WebSearch"] if self.web_search and tools else []  # фоновой памяти поиск не нужен
        return ClaudeAgentOptions(
            system_prompt=system,
            model=model,
            tools=builtin,  # из встроенных инструментов Claude Code — максимум поиск в интернете
            disallowed_tools=[t for t in BUILTIN_TOOLS if t not in builtin],
            allowed_tools=builtin + [f"mcp__{SERVER_NAME}__{t.name}" for t in tools],
            mcp_servers=mcp_servers,
            strict_mcp_config=True,
            permission_mode="dontAsk",  # всё, что не разрешено явно, — запрещено
            setting_sources=[],  # не читать ~/.claude, .claude/, CLAUDE.md
            cwd=self.sandbox_dir,
            max_turns=max_turns,
            effort=effort or self.effort,  # type: ignore[arg-type]
            max_budget_usd=self.max_budget_usd,
            extra_args={"no-session-persistence": None},  # не копить файлы сессий на диске
            env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1"},
        )

    async def ask(self, *, system: str, prompt: str, tools: Sequence[ToolSpec] = (), model: str | None = None,
                  max_turns: int = 5, images: Sequence[Image] = (), effort: str | None = None) -> LLMReply:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, query

        model = model or self.default_model
        options = self._options(system, tools, model, max_turns, effort)
        last_text: list[str] = []
        result: Any = None
        refused = False

        async def run() -> None:
            nonlocal result, last_text, refused
            async for msg in query(prompt=_with_images(prompt, images) if images else prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    refused = refused or getattr(msg, "stop_reason", None) == "refusal"
                    texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
                    if texts:
                        last_text = texts
                elif isinstance(msg, ResultMessage):
                    result = msg

        try:
            await asyncio.wait_for(run(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise LLMError("agent sdk timeout") from exc
        except LLMError:
            raise
        except Exception as exc:
            # при ошибке (например, кончились ходы) CLI сначала отдаёт результат, а потом падает —
            # тогда разбираем результат, иначе готовый текст ответа потеряется
            if result is None:
                raise LLMError(f"agent sdk: {type(exc).__name__}: {exc}") from exc
            log.info("agent sdk завершился с ошибкой после результата: %s", exc)

        if result is None:
            raise LLMError("agent sdk: нет результата")
        cost = float(result.total_cost_usd or 0.0)
        if refused or getattr(result, "stop_reason", None) == "refusal":
            raise LLMRefusal("refusal")
        if result.is_error:
            if result.subtype == "error_max_turns" and last_text:
                return LLMReply(text="\n".join(last_text), cost_usd=cost, model=model)
            raise LLMError(f"agent sdk: {result.subtype} {result.api_error_status or ''} {result.errors or ''}")
        text = result.result if isinstance(result.result, str) and result.result.strip() else "\n".join(last_text)
        return LLMReply(text=text or "", cost_usd=cost, model=model)
