# Архитектура STELLA CODER

```
                ┌──────────────────────────── CLI Engine (src/cli) ─────────────────────────────┐
                │ main.ts (флаги, -p, подкоманды) · App.tsx (Ink UI) · commands.ts (slash)       │
                │ Input (история, автодополнение, многострочность) · Dialogs (разрешения, план)   │
                └───────────────▲───────────────────────────────┬──────────────────────────────┘
                     AgentEvent │ (Streaming Engine)            │ submit / interrupt / команды
                ┌───────────────┴─────────────── Runtime (src/agent/runtime.ts) ───────────────┐
                │ создаёт и связывает все подсистемы, владеет главным агентом и сессией         │
                └──┬────────┬─────────┬────────┬────────┬────────┬────────┬────────┬───────────┘
                   │        │         │        │        │        │        │        │
               Agent Core  Providers  Tools  Context  Permissions Hooks  Sessions  Subagents
               agent.ts    registry   fs     index    engine     engine  store     manager
                           anthropic  search project  shell      (12     checkpts  locks
                           openai     shell  instr.   paths      событий) memory   builtin
                           gemini     git    ignore                       MCP      plugins
                           retry/sse  web    walk                         Skills
                                      dev/meta
```

## Модули

| Модуль | Путь | Ответственность |
|---|---|---|
| CLI Engine | `src/cli` | Ink-интерфейс, неинтерактивный режим, slash-команды, @-упоминания, рендер Markdown |
| Agent Core | `src/agent/agent.ts` | Цикл агента, выполнение инструментов, разрешения, хуки, ретраи, компрессия |
| Runtime | `src/agent/runtime.ts` | Композиция подсистем, сессия, системный промпт, доверие к папке |
| LLM Providers | `src/providers` | Адаптеры (Anthropic SDK, OpenAI wire, Gemini), каталог моделей, цены, ретраи |
| Tool Engine | `src/tools` | Типизированные инструменты (Zod → JSON Schema), описание риска, выполнение |
| Context Engine | `src/context` | Индекс файлов/символов/импортов (инкрементальный, кэш), BM25-поиск, профиль проекта, STELLA.md |
| File System | `src/tools/fs.ts` | Чтение/запись/правки с проверкой свежести, блокировками и чекпоинтами |
| Shell | `src/tools/shell.ts`, `process.ts` | Bash/PowerShell/cmd, стриминг, таймауты, kill дерева процессов, фоновые процессы |
| Permissions | `src/permissions` | Режимы, правила, анализ shell-команд, уровни риска, журнал |
| Security | `src/security` | Разрешение путей (symlink, traversal), системные каталоги, конфиденциальные файлы, экранирование |
| Sessions | `src/sessions` | JSONL-журнал, метаданные, поиск, восстановление транскрипта |
| Memory | `src/memory` | user/project/technical/task/session память, дедупликация, запрет секретов |
| Subagents | `src/subagents` | Определения агентов, параллельный запуск с лимитами, владение файлами |
| MCP | `src/mcp` | Клиенты stdio/Streamable HTTP/SSE, обнаружение и вызов инструментов |
| Skills | `src/skills` | SKILL.md, ресурсы навыка, пользовательские команды, подсказка релевантного навыка |
| Hooks | `src/hooks` | Команды на события, JSON в stdin, решения block/allow/ask, таймауты |
| Git | `src/git`, `src/tools/git.ts` | status/diff/log/branch/commit через аргументы (без shell) |
| Recovery | `src/recovery` | Контент-адресуемые снимки файлов, diff, откат с проверкой конфликтов |
| Plugins | `src/plugins` | Пакеты skills+commands+agents+hooks+MCP с `plugin.json` |

## Agent loop

```
run(prompt)
  ├─ checkpoints.beginTurn
  ├─ hook UserPromptSubmit  (может заблокировать или добавить контекст)
  ├─ подсказка навыка по релевантности
  └─ while turns < maxTurns:
       ├─ авто-компрессия, если контекст > порога
       ├─ provider.stream(system, messages, tools)   ← ретраи 429/5xx/сеть
       │     события: text_delta · tool_start · usage
       ├─ refusal → стоп · max_tokens без tools → «продолжи»
       ├─ нет tool_use → (очередь сообщений?) → hook Stop → конец
       └─ для каждого tool_use (concurrency-safe — параллельно, остальные — по порядку):
            валидация Zod → describe() (риск, пути, команда)
            → hook PreToolUse (block / allow / updatedInput)
            → PermissionEngine.check → ask? → hook PermissionRequest → диалог пользователя
            → tool.run (abort-signal, стрим прогресса)
            → hook PostToolUse / PostToolFailure
          → tool_result (+ сообщения пользователя, набранные во время работы)
```

Транскрипт всегда валиден: прерывание во время инструмента даёт `tool_result` с ошибкой «interrupted», а при загрузке сессии висящие `tool_use` закрываются синтетическими результатами (`repairTranscript`).

## Протокол событий

`AgentEvent` (см. `src/agent/events.ts`) — единственный канал от агента к интерфейсу: `turn_start`, `status`, `text_delta`, `tool_start`, `tool_call`, `tool_progress`, `tool_result`, `permission`, `usage`, `compact`, `notification`, `subagent`, `todos`, `mode`, `turn_end`. Неинтерактивный режим `--output-format stream-json` выдаёт эти же события как NDJSON.

## Провайдеры

`LLMProvider.stream(req)` возвращает нейтральные события и итоговое сообщение. Нейтральный формат (`src/types.ts`) — блоки `text`, `tool_use`, `tool_result`, `image`. Для Anthropic исходный `content` ответа хранится в `message.raw` и отправляется обратно без изменений (подписанные thinking-блоки), история только дописывается; компрессия заменяет её целиком сводкой. OpenAI-совместимый адаптер покрывает OpenAI, OpenRouter, Groq, Ollama, LM Studio, vLLM. Gemini — нативный `streamGenerateContent` с очисткой JSON Schema.

## Контекст

- Системный промпт: ядро поведения → окружение → режим → git → профиль проекта → STELLA.md → память → навыки → типы субагентов. Кэшируется и пересобирается только при смене режима/модели/компрессии/памяти — это сохраняет prompt cache провайдера.
- Индекс: обход с учётом `.gitignore`/`.stellaignore`/дефолтных исключений, до 50 000 файлов, символы и импорты для 20+ языков регулярными выражениями, кэш с инвалидацией по mtime/size, точечная инвалидация после правок агента. BM25 по чанкам ~50 строк с разбиением идентификаторов (`getUserName` → get, user, name) строится лениво.
- Компрессия: модель пишет структурированную сводку (запрос, решения, файлы, ошибки, состояние, следующие шаги); история заменяется сводкой и списком затронутых файлов; события `PreCompact`/`PostCompact`; при ошибке «context too long» — компрессия и повтор.

## Субагенты

`Task` запускает отдельного `Agent` со своим контекстом, промптом, набором инструментов и режимом (не более разрешающим, чем у сессии). Параллелизм ограничен семафором (`maxSubagents`), у каждого — лимит ходов и таймаут. Первый агент, изменивший файл, владеет им до завершения; попытка другого агента править тот же файл получает ошибку координации. Субагенты не могут порождать субагентов.

## Хранение

```
~/.stella/
  settings.json  credentials.json (600)  trusted.json  memory.json  history.jsonl  STELLA.md
  skills/  commands/  agents/  plugins/
  projects/<имя>-<хеш>/
    sessions/<id>.jsonl + <id>.meta.json
    checkpoints/<session>/index.json + blobs/<sha256>
    memory/memory.json   index.json   audit.jsonl
<проект>/STELLA.md  STELLA.local.md  .mcp.json  .stellaignore
<проект>/.stella/settings.json  settings.local.json  skills/  commands/  agents/  plugins/
```
