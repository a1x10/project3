"""Песочница «как Claude Code»: Opus с максимальным обдумыванием пишет, запускает и проверяет код в изолированном
контейнере Anthropic — не на нашем сервере (инструмент code_execution Messages API). Программы, сайты, игры,
боты, анализ данных и присланных файлов, расчёты, файлы любого формата. Поиск и чтение страниц в интернете
выполняются тоже у Anthropic; у самого контейнера интернета нет.

- Контейнер помнит проект до 25 дней: файлы и установленное остаются, «продолжи» работает (свой у каждого
  человека в каждом чате; new_project — начать с чистого).
- Присланные или процитированные файлы и фото загружаются в контейнер (Files API).
- quick — ответ сразу (в пределах ответа Стеллы); project — большая работа в фоне до SANDBOX_PROJECT_TIMEOUT,
  результат и файлы приходят отдельным сообщением.
- Доступ — владельцу, а в режиме друзей (FRIENDS_MODE) — и своим (ctx.is_admin); остальные о нём не узнают.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from .llm.base import ToolSpec
from .media import MediaFile

if TYPE_CHECKING:
    from .tools import ToolContext

log = logging.getLogger("stella.sandbox")

CODE_TOOL = {"type": "code_execution_20260521", "name": "code_execution"}
# Базовые версии поиска и чтения страниц: новые (_20260209) приносят свою среду выполнения кода, и рядом с
# code_execution модель путается. Не приняты API — песочница работает без них.
WEB_TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 10},
             {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 10}]
MAX_CONTINUATIONS = 30  # долгая работа идёт кусками (pause_turn) — даём продолжать
MAX_FILES = 10
MAX_FILE_BYTES = 45 * 1024 * 1024  # Telegram-боту можно до 50 МБ, WhatsApp — до 100
MAX_INPUT_BYTES = 30 * 1024 * 1024
MAX_INPUTS = 5
SANDBOX_MAX_TOKENS = 64000
CONTAINER_DAYS = 25  # контейнер Anthropic живёт 30 дней — берём с запасом
SYSTEM = """Ты — сильный инженер уровня senior и работаешь как Claude Code: у тебя Linux-контейнер (bash, Python 3 с \
pandas, numpy, matplotlib, scikit-learn, openpyxl, python-docx, python-pptx, pillow и др., файлы), а ещё поиск и \
чтение страниц в интернете (web_search, web_fetch). Задача может быть любой: написать и запустить программу, сайт, \
игру, бота, скрипт; разобрать данные и присланные файлы; посчитать; сделать документ, таблицу, презентацию, \
картинку, архив.

КАК РАБОТАЕШЬ
1. Пойми задачу. Присланные файлы уже лежат в контейнере (их имена — в задании; найди их: ls, find / -name …). \
Если это продолжение — посмотри, что уже есть в рабочей папке.
2. Продумай план и делай: аккуратный код, понятные имена, обработка ошибок. Каждую часть запускай и проверяй — \
тестами, примерами, выводом. Ошибка — читай трассировку, исправляй, запускай снова, пока не заработает. Ничего не \
утверждай без проверки запуском.
3. Нужна документация, API, свежие факты или данные — найди в интернете (web_search, web_fetch) и проверь по \
первоисточнику. У самого контейнера интернета нет: pip install может не сработать — тогда обходись установленным.
4. Результат-файлы сохрани в рабочую папку — они станут файлами ответа (до 10). Проект из нескольких файлов — \
собери zip-архив с README (что это, как запустить). Сайт или игра — один готовый index.html, который открывается \
в браузере. Данные — xlsx/csv, графики — png, документы — docx/pdf.
5. В конце ответь по-русски коротко и по делу: что сделано, как этим пользоваться или запустить, что проверено и чем. \
Длинный код в ответ не вставляй — он в файлах."""


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
    container_id: str | None = None


@dataclass
class InputFile:
    name: str
    data: bytes
    mime: str


def is_owner(settings: Any, ctx: "ToolContext") -> bool:
    from .util import phone_of

    if ctx.sender is None:
        return False
    phone = phone_of(ctx.sender.jid) or ctx.sender.phone or ""
    is_owner_fn = getattr(settings, "is_owner", None)
    return is_owner_fn(phone) if is_owner_fn else phone == settings.owner_phone


class CodeSandbox:
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "max", client: Any = None,
                 timeout: float = 150):
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self._client = client
        self.web = True  # поиск и чтение страниц; API не принял — выключаем до перезапуска

    def client(self) -> Any:
        if self._client is None:
            import anthropic

            # без своих повторов: время задаёт вызывающий (быстрая задача или фоновый проект)
            self._client = anthropic.AsyncAnthropic(max_retries=0, timeout=3600)
        return self._client

    async def run(self, task: str, inputs: list[InputFile] | None = None, container: str | None = None,
                  timeout: float | None = None) -> SandboxResult:
        try:
            return await asyncio.wait_for(self._run(task, inputs or [], container), timeout=timeout or self.timeout)
        except asyncio.TimeoutError as exc:
            raise SandboxError("слишком долго — попробуй разбить задачу на части или запусти как проект") from exc

    async def _upload(self, client: Any, inputs: list[InputFile]) -> list[tuple[str, str]]:
        ids = []
        for f in inputs:
            try:
                meta = await client.files.upload(file=(f.name, f.data, f.mime or "application/octet-stream"))
                ids.append((meta.id, f.name))
            except Exception:
                log.warning("песочница: не загрузился файл %s", f.name, exc_info=True)
        return ids

    async def _run(self, task: str, inputs: list[InputFile], container: str | None) -> SandboxResult:
        import anthropic

        from .llm.messages_api import estimate_cost

        client = self.client()
        uploaded = await self._upload(client, inputs)
        text = task
        if uploaded:
            text += "\n\nПрислали файлы (уже в контейнере): " + ", ".join(name for _, name in uploaded)
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content += [{"type": "container_upload", "file_id": fid} for fid, _ in uploaded]
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        texts: list[str] = []
        stdout: list[str] = []
        file_ids: list[str] = []
        cost = 0.0
        container_id = container
        try:
            for _ in range(MAX_CONTINUATIONS + 1):
                resp = await self._call(client, messages, container_id)
                if resp is _RETRY_FRESH:  # старый контейнер истёк — начинаем в новом
                    container_id = None
                    resp = await self._call(client, messages, None)
                cost += estimate_cost(self.model, resp.usage)
                container_id = getattr(getattr(resp, "container", None), "id", None) or container_id
                if resp.stop_reason == "refusal":
                    raise SandboxError("это делать отказались", cost)
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
        except anthropic.APIStatusError as exc:
            raise SandboxError(f"песочница недоступна ({exc.status_code})", cost) from exc
        except anthropic.APIConnectionError as exc:
            raise SandboxError("песочница недоступна (нет связи)", cost) from exc
        finally:
            for fid, _ in uploaded:  # входные файлы больше не нужны — не копим их в хранилище
                try:
                    await client.files.delete(fid)
                except Exception:
                    pass
        files = await self._download(client, list(dict.fromkeys(file_ids))[-MAX_FILES:])
        out = "\n".join(stdout).strip()
        return SandboxResult(text=(texts[-1] if texts else ""), stdout=out[-4000:], files=files, cost_usd=cost,
                             container_id=container_id)

    async def _call(self, client: Any, messages: list[dict[str, Any]], container: str | None) -> Any:
        """Один шаг потоком (на effort max модель думает долго — без потока SDK не даёт больше ~21k токенов).
        Веб-инструменты не приняты — без них; контейнер истёк — сигнал начать в новом."""
        import anthropic

        while True:
            kwargs: dict[str, Any] = {
                "model": self.model, "max_tokens": SANDBOX_MAX_TOKENS, "system": SYSTEM, "messages": messages,
                "tools": [CODE_TOOL, *(WEB_TOOLS if self.web else [])], "output_config": {"effort": self.effort},
            }
            if container:
                kwargs["container"] = container
            try:
                async with client.messages.stream(**kwargs) as stream:
                    return await stream.get_final_message()
            except anthropic.APIStatusError as exc:
                msg = str(exc).lower()
                if exc.status_code == 400 and self.web and ("web_" in msg or "tool" in msg):
                    log.warning("песочница: поиск в интернете не принят (%s) — работаю без него", str(exc)[:200])
                    self.web = False
                    continue
                if container and exc.status_code in (400, 404) and "container" in msg:
                    return _RETRY_FRESH
                raise

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


_RETRY_FRESH = object()
BUSY: set[tuple[int, int]] = set()  # (чат, человек): идёт фоновый проект


def build_sandbox_tools(db: Any, settings: Any, ctx: "ToolContext", *, sandbox: CodeSandbox) -> list[ToolSpec]:
    """Инструмент появляется только в ответе владельцу (в режиме друзей — и своим: тем, кто в одной группе с
    владельцем или админом бота) — остальные о нём даже не узнают."""
    trusted = is_owner(settings, ctx) or (getattr(settings, "friends_mode", False) and ctx.is_admin)
    if not getattr(settings, "sandbox_enabled", True) or not trusted:
        return []

    async def inputs_from_chat() -> list[InputFile]:
        files = []
        actions = ctx.actions
        for key, message, name, mime in list(getattr(ctx, "attachments", []) or [])[:MAX_INPUTS]:
            data = await actions.fetch_media(key, message) if actions is not None else None
            if data and len(data) <= MAX_INPUT_BYTES:
                files.append(InputFile(name, data, mime))
        return files

    async def run_code(args: dict[str, Any]) -> str:
        from .tools import ToolError

        task = str(args.get("task") or "").strip()
        if not task:
            raise ToolError("опиши задачу")
        if getattr(ctx, "untrusted", False):
            raise ToolError("в этом ответе был чужой текст — код запускаю только по отдельной просьбе")
        if getattr(ctx, "_sandbox_used", False):
            raise ToolError("за один ответ — один запуск")
        project = str(args.get("mode") or "quick") == "project"
        person = ctx.sender.id if ctx.sender else 0
        if project and (ctx.chat_id, person) in BUSY:
            raise ToolError("твой прошлый проект ещё делается — дождись результата")
        key = f"sandbox:{ctx.chat_id}:{date.today().isoformat()}"
        used = await db.kv_get(key)
        if not ctx.is_admin and used and used[1] >= getattr(settings, "sandbox_per_day", 30):
            raise ToolError("на сегодня запусков хватит")
        ctx._sandbox_used = True
        await db.kv_add(key, 1)
        inputs = await inputs_from_chat() if args.get("use_files") else []
        if args.get("use_files") and not inputs:
            raise ToolError("файлов нет: пусть пришлют файл или фото с просьбой или ответят на него")
        box_key = f"sbx:{ctx.chat_id}:{person}"
        container = None
        if not args.get("new_project"):
            saved = await db.kv_get(box_key)
            if saved and saved[0] and time.time() - saved[1] < CONTAINER_DAYS * 86400:
                container = saved[0]

        async def remember(result: SandboxResult) -> None:
            if result.container_id:
                await db.kv_set(box_key, result.container_id, time.time())

        async def charge(usd: float) -> None:
            if usd and ctx.on_cost is not None:
                await ctx.on_cost(usd)

        if project:
            return start_project(task, inputs, container, remember, charge)
        try:
            result = await sandbox.run(task[:20000], inputs, container)
        except SandboxError as exc:
            await charge(exc.cost_usd)
            raise ToolError(str(exc)) from exc
        log.info("песочница: %.4f$, файлов %d", result.cost_usd, len(result.files))
        await charge(result.cost_usd)
        await remember(result)
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

    def start_project(task: str, inputs: list[InputFile], container: str | None, remember, charge) -> str:
        """Большая работа — в фоне: её ответ уходит сразу, результат и файлы — отдельным сообщением."""
        actions = ctx.actions
        person = ctx.sender.id if ctx.sender else 0
        BUSY.add((ctx.chat_id, person))
        released = asyncio.Event()
        limit = float(getattr(settings, "sandbox_project_timeout", 1800))

        async def release() -> None:
            if not getattr(ctx, "replied", 0):
                await actions.say("взялась за задачу 🧑‍💻 пришлю результат, как будет готово")
            released.set()

        async def deliver() -> None:
            try:
                try:
                    result = await sandbox.run(task[:20000], inputs, container, timeout=limit)
                except SandboxError as exc:
                    await charge(exc.cost_usd)
                    await _after_reply(released)
                    await actions.say(f"с задачей не справилась 😕 {exc}")
                    return
                except Exception:
                    log.exception("песочница: проект упал")
                    await _after_reply(released)
                    await actions.say("с задачей не справилась 😕 попробуй ещё раз")
                    return
                log.info("песочница (проект): %.4f$, файлов %d", result.cost_usd, len(result.files))
                await charge(result.cost_usd)
                await remember(result)
                await _after_reply(released)
                text = (result.text or "готово").strip()
                await actions.say(text[:3500] + ("…" if len(text) > 3500 else ""))
                for i, f in enumerate(result.files):
                    await actions.send_file(f, "", reply=(i == 0))
            finally:
                BUSY.discard((ctx.chat_id, person))

        ctx.after.append(release)
        actions.spawn(deliver())
        return ("проект запущен в песочнице (Opus, в фоне, до " + f"{int(limit // 60)} минут): результат и файлы придут "
                "отдельным сообщением. Скажи коротко своими словами, что взялась и пришлёшь, когда будет готово.")

    return [ToolSpec(
        "run_code",
        "Песочница уровня Claude Code (Opus, отдельный защищённый контейнер, не наш сервер): написать, запустить и "
        "проверить программу, сайт, игру, бота, скрипт; разобрать данные и присланные файлы; посчитать; найти в "
        "интернете документацию и свежие данные; сделать файлы любого формата (до 10). Контейнер помнит проект этого "
        "человека в этом чате до 25 дней — «продолжи», «поправь» работают. mode: quick — ответ сразу (посчитать, "
        "график, небольшой скрипт); project — большая работа в фоне до получаса (приложение, сайт, анализ большого "
        "файла), результат придёт отдельным сообщением. use_files — взять присланные или процитированные файлы и "
        "фото. new_project — начать с чистого контейнера. task — подробное задание словами (со всеми деталями из чата) "
        "или с кодом.",
        {"type": "object", "properties": {
            "task": {"type": "string"},
            "mode": {"type": "string", "enum": ["quick", "project"]},
            "use_files": {"type": "boolean"},
            "new_project": {"type": "boolean"},
        }, "required": ["task"]},
        run_code,
    )]


async def _after_reply(released: asyncio.Event) -> None:
    """Результат — после её ответа «взялась» (а если тот так и не ушёл — всё равно, через 2 минуты)."""
    try:
        await asyncio.wait_for(released.wait(), 120)
    except asyncio.TimeoutError:
        pass
