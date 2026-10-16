"""Запуск кода — ТОЛЬКО по просьбе владельца (OWNER_PHONE).

Код выполняется не на нашем сервере, а в песочнице Anthropic (инструмент code_execution Messages API):
посчитать, построить график, обработать данные, сделать файл любого формата. Готовые файлы скачиваются
через Files API и уходят в чат.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from .media import MediaFile
from .llm.base import ToolSpec

if TYPE_CHECKING:
    from .tools import ToolContext

log = logging.getLogger("stella.sandbox")

CODE_TOOL = {"type": "code_execution_20260521", "name": "code_execution"}
MAX_CONTINUATIONS = 5
MAX_FILES = 3
MAX_FILE_BYTES = 15 * 1024 * 1024
SYSTEM = (
    "Ты помощник, который решает задачу, запуская Python в песочнице. Напиши и выполни код, проверь результат. "
    "Если нужен график, таблица, документ или другой файл — сохрани его в рабочую папку, чтобы он стал файлом "
    "результата (не больше трёх файлов). В конце ответь по-русски очень коротко: что получилось, без кода."
)


class SandboxError(Exception):
    def __init__(self, message: str, cost_usd: float = 0.0):
        super().__init__(message)
        self.cost_usd = cost_usd  # сколько успели потратить до ошибки


@dataclass
class SandboxResult:
    text: str
    stdout: str
    files: list[MediaFile] = field(default_factory=list)
    cost_usd: float = 0.0


def is_owner(settings: Any, ctx: "ToolContext") -> bool:
    from .util import phone_of

    if ctx.sender is None or not getattr(settings, "owner_phone", ""):
        return False
    phone = phone_of(ctx.sender.jid) or ctx.sender.phone or ""
    is_owner_fn = getattr(settings, "is_owner", None)
    return is_owner_fn(phone) if is_owner_fn else phone == settings.owner_phone


class CodeSandbox:
    def __init__(self, model: str = "claude-sonnet-5-5", effort: str = "medium", client: Any = None,
                 timeout: float = 150):
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self._client = client

    def client(self) -> Any:
        if self._client is None:
            import anthropic

            # без своих повторов и с тем же лимитом, что и весь запуск — иначе повторы съели бы всё время
            self._client = anthropic.AsyncAnthropic(max_retries=0, timeout=self.timeout)
        return self._client

    async def run(self, task: str) -> SandboxResult:
        try:
            return await asyncio.wait_for(self._run(task), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise SandboxError("слишком долго считается — попробуй задачу попроще") from exc

    async def _run(self, task: str) -> SandboxResult:
        import anthropic

        from .llm.messages_api import estimate_cost

        client = self.client()
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        texts: list[str] = []
        stdout: list[str] = []
        file_ids: list[str] = []
        cost = 0.0
        for _ in range(MAX_CONTINUATIONS + 1):
            try:
                resp = await client.messages.create(
                    model=self.model, max_tokens=16000, system=SYSTEM, messages=messages, tools=[CODE_TOOL],
                    output_config={"effort": self.effort},
                )
            except anthropic.APIStatusError as exc:
                raise SandboxError(f"песочница недоступна ({exc.status_code})") from exc
            except anthropic.APIConnectionError as exc:
                raise SandboxError("песочница недоступна (нет связи)") from exc
            cost += estimate_cost(self.model, resp.usage)
            if resp.stop_reason == "refusal":
                raise SandboxError("это запускать отказались", cost)
            for block in resp.content:
                kind = getattr(block, "type", "")
                if kind == "text" and block.text.strip():
                    texts.append(block.text.strip())
                elif kind == "bash_code_execution_tool_result":
                    result = block.content
                    if getattr(result, "type", "") != "bash_code_execution_result":
                        stdout.append(f"ошибка песочницы: {getattr(result, 'error_code', '?')}")
                        continue
                    if result.stdout:
                        stdout.append(result.stdout)
                    if result.return_code and result.stderr:
                        stdout.append("ошибка: " + result.stderr[-1500:])
                    for ref in result.content or []:
                        if getattr(ref, "type", "") == "bash_code_execution_output":
                            file_ids.append(ref.file_id)
            if resp.stop_reason != "pause_turn":
                break
            # песочница взяла паузу: отправляем её ответ обратно — сервер продолжит сам
            messages.append({"role": "assistant", "content": resp.content})
        files = await self._download(client, file_ids[-MAX_FILES:])
        out = "\n".join(stdout).strip()
        return SandboxResult(text=(texts[-1] if texts else ""), stdout=out[-4000:], files=files, cost_usd=cost)

    async def _download(self, client: Any, file_ids: list[str]) -> list[MediaFile]:
        files = []
        for fid in file_ids:
            try:
                meta = await client.files.retrieve_metadata(fid)
                if (getattr(meta, "size_bytes", 0) or 0) > MAX_FILE_BYTES:
                    continue
                resp = await client.files.download(fid)
                data = await resp.read()
            except Exception:
                log.warning("не удалось скачать файл из песочницы", exc_info=True)
                continue
            name = os.path.basename(getattr(meta, "filename", "") or "") or "result"
            if name in (".", ".."):
                name = "result"
            mime = getattr(meta, "mime_type", "") or "application/octet-stream"
            kind = "image" if mime in ("image/png", "image/jpeg") else "document"
            files.append(MediaFile(kind, data, mime, name[:80]))
        return files


def build_sandbox_tools(db: Any, settings: Any, ctx: "ToolContext", *, sandbox: CodeSandbox) -> list[ToolSpec]:
    """Инструмент появляется только в ответе владельцу — остальные о нём даже не узнают."""
    if not getattr(settings, "sandbox_enabled", True) or not is_owner(settings, ctx):
        return []

    async def run_code(args: dict[str, Any]) -> str:
        from .tools import ToolError

        task = str(args.get("task") or "").strip()
        if not task:
            raise ToolError("опиши задачу")
        if getattr(ctx, "untrusted", False):
            raise ToolError("в этом ответе был чужой текст — код запускаю только по отдельной просьбе")
        if getattr(ctx, "_sandbox_used", False):
            raise ToolError("за один ответ — один запуск")
        key = f"sandbox:{ctx.chat_id}:{date.today().isoformat()}"
        used = await db.kv_get(key)
        if used and used[1] >= getattr(settings, "sandbox_per_day", 30):
            raise ToolError("на сегодня запусков хватит")
        ctx._sandbox_used = True
        await db.kv_add(key, 1)
        try:
            result = await sandbox.run(task[:8000])
        except SandboxError as exc:
            if exc.cost_usd and ctx.on_cost is not None:
                await ctx.on_cost(exc.cost_usd)
            raise ToolError(str(exc)) from exc
        log.info("песочница: %.4f$, файлов %d", result.cost_usd, len(result.files))
        if ctx.on_cost is not None:
            await ctx.on_cost(result.cost_usd)
        actions = ctx.actions
        for file in result.files:
            ctx.media_queued += 1

            async def send(f: MediaFile = file) -> None:
                await actions.send_file(f, "")

            ctx.after.append(send)
        parts = [f"результат: {result.text or '—'}"]
        if result.stdout:
            parts.append(f"вывод:\n{result.stdout}")
        if result.files:
            parts.append(f"файлы ({len(result.files)}) уйдут в чат сразу после твоего сообщения")
        return "\n".join(parts)

    return [ToolSpec(
        "run_code",
        "Запустить код в защищённой песочнице (не на сервере): посчитать, решить задачу численно, построить "
        "график, обработать данные, сделать файл любого формата. Только когда об этом просит владелец. "
        "task — что сделать, словами или с кодом.",
        {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]},
        run_code,
    )]
