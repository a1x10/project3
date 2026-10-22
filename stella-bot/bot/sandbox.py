"""Песочница «как Claude Code»: Opus с максимальным обдумыванием пишет, запускает и проверяет код в изолированном
контейнере Anthropic — не на нашем сервере (инструмент code_execution Messages API). Программы, сайты, игры,
боты, анализ данных и присланных файлов, расчёты, файлы любого формата. Поиск и чтение страниц в интернете
выполняются тоже у Anthropic; у самого контейнера интернета нет.

- Контейнер помнит проект до 25 дней: файлы и установленное остаются, «продолжи» работает (свой у каждого
  человека в каждом чате; new_project — начать с чистого).
- Присланные или процитированные файлы и фото загружаются в контейнер (Files API).
- quick — ответ сразу, если задача успевает за SANDBOX_QUICK_SECONDS (не держим очередь ответов бота); не успела —
  доделывается в фоне. project — сразу в фоне. В фоне — до SANDBOX_PROJECT_TIMEOUT, результат и файлы приходят
  ответом на просьбу.
- ultra — максимальная мощность для программирования, как ultracode в Claude Code: план с требованиями и тестами →
  код → независимый строгий ревьюер (свежий взгляд, проверяет запуском, пытается сломать) → исправления, и так
  кругами, пока ревьюер не скажет «готово» (SANDBOX_ULTRA_ROUNDS). По умолчанию так идёт каждый project
  (SANDBOX_ULTRA=projects). Свой потолок денег (SANDBOX_ULTRA_MAX_USD) и времени (SANDBOX_ULTRA_TIMEOUT).
- Деньги: дневной бюджет (DAILY_BUDGET_USD) и SANDBOX_PER_DAY — для всех, кроме владельца; потолок одного запуска
  SANDBOX_MAX_RUN_USD — для всех. Потраченное записывается при любом исходе (и когда время вышло).
- Доступ — владельцу, а в режиме друзей (FRIENDS_MODE) — и своим (ctx.is_admin); остальные о нём не узнают.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Callable

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
SANDBOX_MAX_TOKENS = 128000  # потолок Opus 5.5 (потоком): на effort max один шаг пишет и думает много
CONTAINER_DAYS = 25  # контейнер Anthropic живёт 30 дней — берём с запасом
STEP_ATTEMPTS = 3  # один шаг долгого проекта: перегрузка или обрыв потока — повторяем, а не бросаем всю работу
RETRY_PAUSE = 10
RETRY_STATUS = {200, 408, 409, 429, 500, 502, 503, 504, 529}  # 200 — ошибка посреди потока (overloaded)
WEB_RETRY_AFTER = 3600  # API не принял поиск — час без него, потом пробуем снова
# сколько держим в уме из дневного бюджета, пока запуск идёт (расход записывается по итогу)
QUICK_RESERVE_USD = 1.0
PROJECT_RESERVE_USD = 5.0
ULTRA_RESERVE_USD = 15.0
CONTINUE = "Ответ оборвался по длине. Продолжай с того места, где остановилась; сделанное не повторяй."
NO_WEB = "\n\n(Поиск и чтение страниц в интернете в этот раз выключены — обходись без них.)"
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


ULTRA_BUILD = """РЕЖИМ МАКСИМАЛЬНОГО КАЧЕСТВА. После тебя работу проверит независимый строгий ревьюер, потом ты \
исправишь найденное — делай сразу так, чтобы ему нечего было найти.
1. Сначала создай PLAN.md: все требования задачи пронумерованным чек-листом (ничего не упусти и не додумывай \
лишнего), архитектура, как проверишь каждое требование.
2. Делай по плану. Пиши автотесты (pytest и т.п.) на основную логику, граничные случаи и плохие входные данные; \
гоняй их, пока всё не пройдёт.
3. В конце пройди чек-лист PLAN.md и проверь каждое требование запуском. Итоговые файлы — в рабочую папку \
(проект из нескольких файлов — zip с README и тестами).

ЗАДАЧА:
"""

REVIEW_SYSTEM = """Ты — строгий независимый ревьюер уровня staff engineer, как отдельный проверяющий агент в Claude \
Code. У тебя Linux-контейнер (bash, Python 3 и библиотеки), а ещё поиск и чтение страниц в интернете (web_search, \
web_fetch); у самого контейнера интернета нет. В контейнере — работа другого инженера по задаче (её пришлют): файлы \
в рабочей папке, требования и план — в PLAN.md, если есть. Твоя цель — найти, что НЕ работает, сделано не так или \
не сделано. Сам ничего в проекте не исправляй и не переписывай.

КАК ПРОВЕРЯЕШЬ
1. Найди все файлы проекта (ls -la, find), прочитай код и PLAN.md.
2. Сверь КАЖДОЕ требование задачи: сделано ли и работает ли — запуском, а не на глаз.
3. Запусти тесты проекта. Свои проверки (граничные случаи, пустые и плохие входные данные, большие объёмы) пиши \
во временную папку /tmp, не трогая проект.
4. Ищи: падения и необработанные ошибки, неверные результаты, то, что не запускается по README, дыры \
безопасности (инъекции, секреты в коде), для сайта или игры — что index.html открывается и работает без ошибок.
Каждую проблему подтверди запуском. К стилю и вкусовщине не придирайся.

ОТВЕТ — строго в таком виде:
ПРОБЛЕМЫ:
1. [критично] или [важно] или [мелочь] что не так — как воспроизвести — что ожидалось
(если проблем нет — «нет»)
ВЕРДИКТ: ГОТОВО — если критичных и важных проблем нет; иначе ВЕРДИКТ: ИСПРАВИТЬ"""


def review_task(task: str) -> str:
    return f"ЗАДАЧА, которую делали:\n{task}\n\nПроверь работу в контейнере."


def fix_task(task: str, review: str) -> str:
    return (f"Ты продолжаешь свой проект в этом контейнере (файлы и PLAN.md — в рабочей папке).\n\nЗАДАЧА:\n{task}"
            f"\n\nНезависимый ревьюер проверил работу и нашёл:\n{review[-6000:]}\n\nИсправь все критичные и важные "
            "проблемы (мелочи — если это просто). Каждое исправление подтверди запуском и тестом, прогони все тесты. "
            "В конце сохрани итоговые файлы результата в рабочую папку заново (обновлённые версии) и коротко "
            "по-русски: что исправлено и как пользоваться.")


def review_verdict(text: str) -> tuple[str, list[str]]:
    """Ответ ревьюера -> (done | fix | unclear, критичные и важные проблемы)."""
    issues = [line.strip() for line in text.splitlines() if re.search(r"\[(критично|важно)\]", line, re.IGNORECASE)]
    m = re.search(r"ВЕРДИКТ:\s*(ГОТОВО|ИСПРАВИТЬ)", text, re.IGNORECASE)
    if issues:
        return "fix", issues
    if m and m.group(1).upper() == "ГОТОВО":
        return "done", []
    return ("fix", []) if m else ("unclear", [])


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
    unfinished: str = ""  # почему остановилась раньше конца (потолок денег или шагов)
    file_ids: list[str] = field(default_factory=list)  # файлы результата в хранилище Anthropic (ещё не скачанные)


@dataclass
class InputFile:
    name: str
    data: bytes
    mime: str


@dataclass
class Progress:
    """Что уже потрачено и в каком контейнере идёт работа — известно и тогда, когда запуск оборвали (вышло
    время, отменили): деньги всё равно записываем, а «продолжи» попадёт в тот же контейнер."""
    cost_usd: float = 0.0
    container_id: str | None = None


def is_owner(settings: Any, ctx: "ToolContext") -> bool:
    from .util import phone_of

    if ctx.sender is None:
        return False
    phone = phone_of(ctx.sender.jid) or ctx.sender.phone or ""
    is_owner_fn = getattr(settings, "is_owner", None)
    return is_owner_fn(phone) if is_owner_fn else phone == settings.owner_phone


class CodeSandbox:
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "max", client: Any = None,
                 timeout: float = 1800, max_run_usd: float = 0.0, off: Callable[[], bool] | None = None):
        self.off = off  # True — модель выключена (кончились бонусные кредиты): ни одного шага за свой баланс
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self.max_run_usd = max_run_usd  # потолок одного запуска; 0 — без него
        self._client = client
        self.web_off_until = 0.0  # API не принял поиск в интернете — до этого времени без него

    def client(self) -> Any:
        if self._client is None:
            import anthropic

            # свои повторы — по шагам (_call); время на весь запуск задаёт вызывающий
            self._client = anthropic.AsyncAnthropic(max_retries=0, timeout=3600)
        return self._client

    async def run(self, task: str, inputs: list[InputFile] | None = None, container: str | None = None,
                  timeout: float | None = None, *, web: bool = True, progress: Progress | None = None,
                  max_usd: float | None = None, model: str | None = None, effort: str | None = None) -> SandboxResult:
        """web=False — без поиска и чтения страниц (например, в задаче чужой текст из файла). progress — снаружи
        видно, сколько потрачено, даже если запуск оборвётся. max_usd — потолок этого запуска (иначе общий).
        model/effort — своя модель для этого запуска (режим Flash), иначе SANDBOX_MODEL/SANDBOX_EFFORT."""
        progress = progress if progress is not None else Progress(container_id=container)
        engine = (model or self.model, effort or self.effort)
        return await self._limited(self._run(task, inputs or [], container, web, progress, max_usd=max_usd,
                                             engine=engine), timeout, progress)

    async def run_ultra(self, task: str, inputs: list[InputFile] | None = None, container: str | None = None,
                        timeout: float | None = None, *, web: bool = True, progress: Progress | None = None,
                        rounds: int = 3, max_usd: float | None = None) -> SandboxResult:
        """Максимальная мощность для программирования: план и тесты → код → независимый ревьюер → исправления,
        кругами, пока ревьюер не скажет «готово» (rounds — сколько раз проверять)."""
        progress = progress if progress is not None else Progress(container_id=container)
        return await self._limited(self._ultra(task, inputs or [], container, web, progress, max(1, rounds), max_usd),
                                   timeout, progress)

    async def _limited(self, work: Any, timeout: float | None, progress: Progress) -> SandboxResult:
        limit = timeout or self.timeout
        try:
            return await asyncio.wait_for(work, timeout=limit)
        except asyncio.TimeoutError as exc:
            raise SandboxError(f"не успела за {_minutes(limit)} — сделанное осталось в песочнице: скажи «продолжи», "
                               "и я доделаю", progress.cost_usd) from exc

    async def _ultra(self, task: str, inputs: list[InputFile], container: str | None, web: bool, progress: Progress,
                     rounds: int, max_usd: float | None) -> SandboxResult:
        ceiling = self.max_run_usd if max_usd is None else max_usd

        def broke() -> bool:
            return bool(ceiling) and progress.cost_usd >= ceiling

        build = await self._run(ULTRA_BUILD + task, inputs, container, web, progress, max_usd=ceiling,
                                download=False)
        file_ids, text, unfinished = list(build.file_ids), build.text, build.unfinished
        stdout = [build.stdout] if build.stdout else []
        reviews, fixed, remaining, unclear = 0, 0, [], False
        for i in range(rounds):
            if unfinished or broke():
                break
            review = await self._run(review_task(task), [], progress.container_id, web, progress,
                                     system=REVIEW_SYSTEM, max_usd=ceiling, download=False)
            reviews += 1
            verdict, issues = review_verdict(review.text)
            log.info("песочница (ультра): проверка %d — %s, проблем %d", reviews, verdict, len(issues))
            if verdict != "fix":
                remaining, unclear = [], verdict == "unclear" or bool(review.unfinished)
                break
            remaining = issues or ["ревьюер просит исправить (подробности — в его отчёте)"]
            if i == rounds - 1 or broke():
                break  # больше кругов нет — что осталось, скажем человеку
            fix = await self._run(fix_task(task, review.text), [], progress.container_id, web, progress,
                                  max_usd=ceiling, download=False)
            fixed += len(issues)
            file_ids += fix.file_ids
            text = fix.text or text
            if fix.stdout:
                stdout.append(fix.stdout)
            if fix.unfinished:
                unfinished = fix.unfinished
        if broke() and not unfinished and remaining:
            unfinished = f"потрачено ${progress.cost_usd:.2f} — это потолок ультра-режима (SANDBOX_ULTRA_MAX_USD)"
        note = f"🔍 Ультра-режим: независимых проверок — {reviews}, исправлено проблем — {fixed}."
        if remaining:
            note += "\nРевьюер ещё видит:\n" + "\n".join(f"• {x[:300]}" for x in remaining[:4])
            note += "\nНапиши «продолжи» — доделаю."
        elif unclear:
            note += " Последняя проверка не дала ясного ответа."
        elif reviews:
            note += " Последняя проверка: готово ✅"
        files = await self._download(self.client(), file_ids)
        out = "\n".join(stdout).strip()
        return SandboxResult(text=f"{text}\n\n{note}".strip(), stdout=out[-4000:], files=files,
                             cost_usd=progress.cost_usd, container_id=progress.container_id, unfinished=unfinished)

    async def _upload(self, client: Any, inputs: list[InputFile]) -> list[tuple[str, str]]:
        ids = []
        for f in inputs:
            try:
                meta = await client.files.upload(file=(f.name, f.data, f.mime or "application/octet-stream"))
                ids.append((meta.id, f.name))
            except Exception:
                log.warning("песочница: не загрузился файл %s", f.name, exc_info=True)
        return ids

    async def _run(self, task: str, inputs: list[InputFile], container: str | None, web: bool,
                   progress: Progress, *, system: str = SYSTEM, max_usd: float | None = None,
                   download: bool = True, engine: tuple[str, str] | None = None) -> SandboxResult:
        import anthropic

        from .llm.messages_api import estimate_cost

        if self.off is not None and self.off():
            raise SandboxError("модель выключена — дальше не запускаю, деньги не тратятся")
        client = self.client()
        engine = engine or (self.model, self.effort)
        web = web and time.time() >= self.web_off_until
        uploaded = await self._upload(client, inputs)
        text = task
        if uploaded:
            text += "\n\nПрислали файлы (уже в контейнере): " + ", ".join(name for _, name in uploaded)
        if not web:
            text += NO_WEB
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content += [{"type": "container_upload", "file_id": fid} for fid, _ in uploaded]
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        texts: list[str] = []
        stdout: list[str] = []
        file_ids: list[str] = []
        unfinished = ""
        container_id = container
        try:
            for step in range(MAX_CONTINUATIONS + 1):
                resp, container_id, web = await self._step(client, messages, container_id, web, progress, system,
                                                           engine)
                progress.cost_usd += estimate_cost(engine[0], resp.usage)
                container_id = getattr(getattr(resp, "container", None), "id", None) or container_id
                progress.container_id = container_id
                if resp.stop_reason == "refusal":
                    raise SandboxError("это делать отказались", progress.cost_usd)
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
                if resp.stop_reason not in ("pause_turn", "max_tokens"):
                    break
                if step == MAX_CONTINUATIONS:
                    unfinished = "задача оказалась очень длинной"
                    break
                ceiling = self.max_run_usd if max_usd is None else max_usd
                if ceiling and progress.cost_usd >= ceiling:
                    unfinished = (f"потрачено ${progress.cost_usd:.2f} — это потолок одного запуска "
                                  "(SANDBOX_MAX_RUN_USD)")
                    break
                if resp.stop_reason == "pause_turn":
                    # песочница взяла паузу: отправляем её ответ обратно — сервер продолжит сам
                    messages.append({"role": "assistant", "content": resp.content})
                    continue
                kept = _resumable(resp.content)  # упёрлась в длину ответа — просим продолжить
                if not kept:
                    unfinished = "ответ не уместился в длину"
                    break
                messages += [{"role": "assistant", "content": kept}, {"role": "user", "content": CONTINUE}]
        except anthropic.APIStatusError as exc:
            raise SandboxError(f"песочница недоступна ({exc.status_code})", progress.cost_usd) from exc
        except anthropic.APIConnectionError as exc:
            raise SandboxError("песочница недоступна (нет связи)", progress.cost_usd) from exc
        finally:
            for fid, _ in uploaded:  # входные файлы больше не нужны — не копим их в хранилище
                try:
                    await client.files.delete(fid)
                except Exception:
                    pass
        files = await self._download(client, file_ids) if download else []
        out = "\n".join(stdout).strip()
        return SandboxResult(text=(texts[-1] if texts else ""), stdout=out[-4000:], files=files,
                             cost_usd=progress.cost_usd, container_id=container_id, unfinished=unfinished,
                             file_ids=list(dict.fromkeys(file_ids)))

    async def _step(self, client: Any, messages: list[dict[str, Any]], container: str | None, web: bool,
                    progress: Progress, system: str = SYSTEM,
                    engine: tuple[str, str] | None = None) -> tuple[Any, str | None, bool]:
        """Шаг с запасными ходами: API не принял поиск в интернете — без него (если его ещё не было в этой работе:
        иначе история без инструмента не сойдётся); контейнер истёк — в новом. -> (ответ, контейнер, с поиском ли)."""
        import anthropic

        while True:
            tools = [CODE_TOOL, *(WEB_TOOLS if web else [])]
            try:
                resp = await self._call(client, messages, container, tools, progress, system, engine)
            except anthropic.APIStatusError as exc:
                if web and exc.status_code == 400 and _web_rejected(exc) and not _has_web_blocks(messages):
                    log.warning("песочница: поиск в интернете не принят (%s) — час без него", _message(exc)[:200])
                    self.web_off_until = time.time() + WEB_RETRY_AFTER
                    web = False
                    continue
                raise
            if resp is _RETRY_FRESH:
                container = None
                continue
            return resp, container, web

    async def _call(self, client: Any, messages: list[dict[str, Any]], container: str | None,
                    tools: list[dict[str, Any]], progress: Progress, system: str = SYSTEM,
                    engine: tuple[str, str] | None = None) -> Any:
        """Один шаг потоком (на effort max модель думает долго — без потока SDK не даёт больше ~21k токенов).
        Перегрузка, обрыв потока или связи — ещё попытки. Оборванная попытка тоже стоит денег — учитываем оценкой.
        Контейнер истёк — сигнал начать в новом."""
        import anthropic

        from .html_studio import _partial_cost

        if self.off is not None and self.off():
            raise SandboxError("модель выключена — дальше не запускаю, деньги не тратятся")
        model, effort = engine or (self.model, self.effort)
        kwargs: dict[str, Any] = {
            "model": model, "max_tokens": SANDBOX_MAX_TOKENS, "system": system, "messages": messages,
            "tools": tools, "output_config": {"effort": effort},
            # каждый шаг заново отправляет всю растущую историю — из кеша она в 10 раз дешевле
            "cache_control": {"type": "ephemeral"},
        }
        if container:
            kwargs["container"] = container
        for attempt in range(1, STEP_ATTEMPTS + 1):
            if attempt > 1 and self.off is not None and self.off():  # выключили, пока ждали повтора
                raise SandboxError("модель выключена — дальше не запускаю, деньги не тратятся")
            holder: dict[str, Any] = {"started": time.monotonic()}
            try:
                async with client.messages.stream(**kwargs) as stream:
                    holder["stream"] = stream
                    return await stream.get_final_message()
            except BaseException as exc:  # и отмена (вышло время): оборванная попытка тоже стоила денег
                progress.cost_usd += _partial_cost(kwargs, holder)
                if not isinstance(exc, Exception):
                    raise
                if isinstance(exc, anthropic.APIStatusError):
                    if container and exc.status_code in (400, 404) and "container" in _message(exc).lower():
                        return _RETRY_FRESH
                    if exc.status_code not in RETRY_STATUS or attempt == STEP_ATTEMPTS:
                        raise
                elif attempt == STEP_ATTEMPTS:
                    if isinstance(exc, anthropic.APIConnectionError):
                        raise
                    # обрыв посреди долгого ответа SDK отдаёт «сырой» сетевой ошибкой (RemoteProtocolError…)
                    raise SandboxError(f"связь с песочницей оборвалась ({type(exc).__name__})",
                                       progress.cost_usd) from exc
                log.warning("песочница: %s — повторяю шаг", getattr(exc, "status_code", type(exc).__name__))
            await asyncio.sleep(RETRY_PAUSE * attempt)
        raise SandboxError("песочница недоступна", progress.cost_usd)

    async def _download(self, client: Any, file_ids: list[str]) -> list[MediaFile]:
        """Файлы результата. Один и тот же файл переписывали (исправления) — берём последнюю версию; не больше
        MAX_FILES (самые свежие)."""
        latest: dict[str, tuple[str, Any]] = {}
        for fid in dict.fromkeys(file_ids):
            try:
                meta = await client.files.retrieve_metadata(fid)
            except Exception:
                log.warning("не удалось узнать файл из песочницы", exc_info=True)
                continue
            name = os.path.basename(getattr(meta, "filename", "") or "") or "result"
            if name in (".", ".."):
                name = "result"
            latest.pop(name, None)  # в конец: порядок — по последней версии
            latest[name] = (fid, meta)
        files = []
        for name, (fid, meta) in list(latest.items())[-MAX_FILES:]:
            if (getattr(meta, "size_bytes", 0) or 0) > MAX_FILE_BYTES:
                continue
            try:
                resp = await client.files.download(fid)
                data = await resp.read()
            except Exception:
                log.warning("не удалось скачать файл из песочницы", exc_info=True)
                continue
            mime = getattr(meta, "mime_type", "") or "application/octet-stream"
            kind = "image" if mime in ("image/png", "image/jpeg") else "document"
            files.append(MediaFile(kind, data, mime, name[:80]))
        return files


def _message(exc: Any) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("message") or "")
    return str(exc)


def _web_rejected(exc: Any) -> bool:
    """400 именно про наши веб-инструменты (а не любая ошибка, где встречается слово tool)."""
    msg = _message(exc)
    return any(t["type"] in msg for t in WEB_TOOLS)


def _has_web_blocks(messages: list[dict[str, Any]]) -> bool:
    for m in messages:
        for block in m.get("content") if isinstance(m.get("content"), list) else []:
            kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", "")
            name = block.get("name") if isinstance(block, dict) else getattr(block, "name", "")
            if kind in ("web_search_tool_result", "web_fetch_tool_result") or (
                    kind == "server_tool_use" and name in ("web_search", "web_fetch")):
                return True
    return False


def _resumable(content: list[Any]) -> list[Any]:
    """Ответ оборвался по длине: убираем недописанный хвост (обдумывание, вызов без результата, пустой текст) —
    остальное можно отправить обратно и попросить продолжить."""
    blocks = list(content)
    answered = {getattr(b, "tool_use_id", None) for b in blocks}
    while blocks:
        last = blocks[-1]
        kind = getattr(last, "type", "")
        if (kind in ("thinking", "redacted_thinking")
                or kind.endswith("tool_use") and getattr(last, "id", None) not in answered
                or kind == "text" and not (getattr(last, "text", "") or "").strip()):
            blocks.pop()
            continue
        break
    return blocks


def _minutes(seconds: float) -> str:
    return f"{max(1, round(seconds / 60))} мин"


_RETRY_FRESH = object()
BUSY: set[tuple[int, int]] = set()  # (чат, человек): идёт фоновая работа


def build_sandbox_tools(db: Any, settings: Any, ctx: "ToolContext", *, sandbox: CodeSandbox) -> list[ToolSpec]:
    """Инструмент появляется только в ответе владельцу (в режиме друзей — и своим: тем, кто в одной группе с
    владельцем или админом бота) — остальные о нём даже не узнают."""
    owner = is_owner(settings, ctx)
    trusted = owner or (getattr(settings, "friends_mode", False) and ctx.is_admin)
    if not getattr(settings, "sandbox_enabled", True) or not trusted:
        return []
    anthropic_off = getattr(settings, "anthropic_off", None)
    if anthropic_off is not None and anthropic_off():  # песочница — только у Anthropic
        return []

    async def inputs_from_chat() -> list[InputFile]:
        files = []
        actions = ctx.actions
        for key, message, name, mime in list(getattr(ctx, "attachments", []) or [])[:MAX_INPUTS]:
            data = await actions.fetch_media(key, message) if actions is not None else None
            if data and len(data) <= MAX_INPUT_BYTES:
                files.append(InputFile(name, data, mime))
        return files

    async def is_paused() -> bool:
        check = getattr(ctx.actions, "paused", None)
        try:
            return bool(check and await check())
        except Exception:
            return False

    async def run_code(args: dict[str, Any]) -> str:
        from . import html_studio
        from .tools import ToolError

        task = str(args.get("task") or "").strip()
        if not task:
            raise ToolError("опиши задачу")
        use_files = bool(args.get("use_files"))
        untrusted = getattr(ctx, "untrusted", False)
        # чужой текст только из файлов, которые прислал сам просящий: их можно отдать в контейнер, но без интернета —
        # указания внутри файла не смогут ничего никуда отправить
        files_only = untrusted == "files" and use_files
        if getattr(ctx, "_sandbox_used", False):
            raise ToolError("за один ответ — один запуск")
        if untrusted and not files_only:
            raise ToolError("в этом ответе был чужой текст — код запускаю только по отдельной просьбе")
        mode = str(args.get("mode") or "quick")
        ultra_setting = str(getattr(settings, "sandbox_ultra", "projects") or "projects").lower()
        # ультра: если попросили (mode=ultra) или каждый проект (SANDBOX_ULTRA=projects); off — выключен
        ultra = ultra_setting != "off" and (mode == "ultra" or (mode == "project" and ultra_setting == "projects"))
        project = mode in ("project", "ultra")
        person = ctx.sender.id if ctx.sender else 0
        if (ctx.chat_id, person) in BUSY:
            raise ToolError("твоя прошлая задача ещё делается — дождись результата")
        today = date.today().isoformat()
        day_key = f"sandbox:{person}:{today}"
        if not owner:  # владелец платит сам; остальным — дневные лимиты
            used = await db.kv_get(day_key)
            limit = getattr(settings, "sandbox_per_day", 0)
            if limit > 0 and used and used[1] >= limit:
                raise ToolError("на сегодня запусков хватит")
            spent = await db.kv_get(f"spend:{today}")
            # с учётом того, что ещё делается (студия и песочница записывают расход по итогу)
            projected = (spent[1] if spent else 0.0) + html_studio.STATE.reserved_usd
            budget = getattr(settings, "daily_budget_usd", 0)
            if budget > 0 and projected >= budget:
                raise ToolError("на сегодня бюджет кончился — песочница заработает завтра")
        ctx._sandbox_used = True
        await db.kv_add(day_key, 1)
        inputs = await inputs_from_chat() if use_files else []
        if use_files and not inputs:
            raise ToolError("файлов нет: пусть пришлют файл или фото с просьбой или ответят на него")
        box_key = f"sbx:{ctx.chat_id}:{person}"
        container = None
        if not args.get("new_project"):
            saved = await db.kv_get(box_key)
            if saved and saved[0] and time.time() - saved[1] < CONTAINER_DAYS * 86400:
                container = saved[0]

        if ultra:
            max_run = float(getattr(settings, "sandbox_ultra_max_usd", 30) or 0)
            reserve = ULTRA_RESERVE_USD
            limit = float(getattr(settings, "sandbox_ultra_timeout", 3600))
        else:
            max_run = float(getattr(settings, "sandbox_max_run_usd", 0) or 0)
            reserve = PROJECT_RESERVE_USD if project else QUICK_RESERVE_USD
            limit = float(getattr(settings, "sandbox_project_timeout", 1800))
        reserve = min(reserve, max_run) if max_run else reserve
        html_studio.STATE.reserved_usd += reserve
        progress = Progress(container_id=container)

        async def settle() -> None:
            html_studio.STATE.reserved_usd = max(0.0, html_studio.STATE.reserved_usd - reserve)
            if progress.cost_usd and ctx.on_cost is not None:
                await ctx.on_cost(progress.cost_usd)
            if progress.container_id:
                await db.kv_set(box_key, progress.container_id, time.time())

        async def job() -> SandboxResult:
            """Сам запуск. Деньги и контейнер записываются при любом исходе: готово, ошибка, вышло время, отмена."""
            try:
                if ultra:
                    result = await sandbox.run_ultra(
                        task[:20000], inputs, container, timeout=limit, web=not files_only, progress=progress,
                        rounds=int(getattr(settings, "sandbox_ultra_rounds", 3) or 3), max_usd=max_run)
                else:
                    result = await sandbox.run(task[:20000], inputs, container, timeout=limit, web=not files_only,
                                               progress=progress, max_usd=max_run)
            finally:
                await asyncio.shield(settle())
            log.info("песочница: %.4f$, файлов %d", result.cost_usd, len(result.files))
            return result

        runner = asyncio.ensure_future(job())
        if project:
            return background(runner, limit, ultra=ultra)
        wait = min(float(getattr(settings, "sandbox_quick_seconds", 150)),
                   max(30.0, float(getattr(settings, "llm_timeout", 600)) - 240))
        try:
            done, _ = await asyncio.wait({runner}, timeout=wait)
        except asyncio.CancelledError:  # её ответ оборвался (время вышло) — работа не пропадает, придёт сама
            background(runner, limit)
            raise
        if not done:  # долго — не держим очередь ответов: доделает в фоне и пришлёт
            return background(runner, limit, moved=True)
        try:
            result = runner.result()
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc
        except Exception as exc:
            log.exception("песочница: ошибка")
            raise ToolError(f"песочница сломалась ({type(exc).__name__}) — попробуй ещё раз") from exc
        ctx.untrusted = True  # в результате — текст из интернета и файлов: опасные действия в этом ответе уже нельзя
        actions = ctx.actions
        for file in result.files:
            ctx.media_queued += 1

            async def send(f: MediaFile = file) -> None:
                await actions.send_file(f, "")

            ctx.after.append(send)
        parts = [f"результат: {result.text or '—'}"]
        if result.stdout:
            parts.append(f"вывод:\n{result.stdout}")
        if result.unfinished:
            parts.append(f"не доделала: {result.unfinished}. Скажи, что можно написать «продолжи»")
        if result.files:
            parts.append(f"файлы ({len(result.files)}) уйдут в чат сразу после твоего сообщения")
        return "\n".join(parts)

    def background(runner: "asyncio.Future[SandboxResult]", limit: float, moved: bool = False,
                   ultra: bool = False) -> str:
        """Работа идёт в фоне: её ответ уходит сразу, результат и файлы — потом, ответом на просьбу."""
        actions = ctx.actions
        person = ctx.sender.id if ctx.sender else 0
        BUSY.add((ctx.chat_id, person))
        released = asyncio.Event()

        async def release() -> None:
            if not getattr(ctx, "replied", 0):
                await actions.say("взялась за задачу 🧑‍💻 пришлю результат, как будет готово")
            released.set()

        async def deliver() -> None:
            try:
                try:
                    result = await runner
                except SandboxError as exc:
                    await _after_reply(released)
                    if not await is_paused():
                        await actions.say(f"с задачей не справилась 😕 {exc}", reply=True)
                    return
                except Exception:
                    log.exception("песочница: фоновая работа упала")
                    await _after_reply(released)
                    if not await is_paused():
                        await actions.say("с задачей не справилась 😕 попробуй ещё раз", reply=True)
                    return
                await _after_reply(released)
                if await is_paused():  # пока делалось, чат поставили на паузу — молчим (файлы остались в контейнере)
                    log.info("песочница: чат на паузе — результат не отправляю")
                    return
                text = (result.text or ("готово" if result.files else "сделала")).strip()
                text = text[:3500] + ("…" if len(text) > 3500 else "")
                if result.unfinished:
                    text += f"\n\n(не доделала: {result.unfinished} — напиши «продолжи»)"
                await actions.say(text, reply=True)
                for f in result.files:
                    await actions.send_file(f, "")
            finally:
                BUSY.discard((ctx.chat_id, person))

        ctx.after.append(release)
        actions.spawn(deliver())
        if moved:
            return ("задача оказалась долгой — доделываю её в песочнице в фоне (до " + _minutes(limit) + "): результат "
                    "и файлы придут отдельным сообщением. Скажи коротко своими словами, что ещё делаешь и пришлёшь.")
        if ultra:
            rounds = int(getattr(settings, "sandbox_ultra_rounds", 3) or 3)
            return ("проект запущен в ультра-режиме (Opus на максимуме, как ultracode: план и тесты → код → "
                    f"независимая проверка → исправления, до {rounds} кругов; в фоне до {_minutes(limit)}): результат "
                    "и файлы придут отдельным сообщением. Скажи коротко своими словами, что взялась по-серьёзному и "
                    "пришлёшь, когда будет готово и проверено.")
        return ("проект запущен в песочнице (Opus, в фоне, до " + _minutes(limit) + "): результат и файлы придут "
                "отдельным сообщением. Скажи коротко своими словами, что взялась и пришлёшь, когда будет готово.")

    return [ToolSpec(
        "run_code",
        "Песочница уровня Claude Code (Opus, отдельный защищённый контейнер, не наш сервер): написать, запустить и "
        "проверить программу, сайт, игру, бота, скрипт; разобрать данные и присланные файлы; посчитать; найти в "
        "интернете документацию и свежие данные; сделать файлы любого формата (до 10). Контейнер помнит проект этого "
        "человека в этом чате до 25 дней — «продолжи», «поправь» работают. mode: quick — ответ сразу (посчитать, "
        "график, небольшой скрипт; не успеет за пару минут — сама доделает в фоне); project — большая работа в фоне "
        "(приложение, сайт, игра, бот, анализ большого файла), результат придёт отдельным сообщением; ultra — "
        "максимальная мощность для программирования, как ultracode: план и тесты, код, независимая проверка и "
        "исправления кругами (дольше и дороже; когда просят «максимально», «ультра», серьёзную программу). use_files — "
        "взять присланные или процитированные файлы и фото. new_project — начать с чистого контейнера. task — "
        "подробное задание словами (со всеми деталями из чата) или с кодом.",
        {"type": "object", "properties": {
            "task": {"type": "string"},
            "mode": {"type": "string", "enum": ["quick", "project", "ultra"]},
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
