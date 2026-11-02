# ✦ STELLA CODER

**Автономный AI-агент для разработки, работающий прямо в терминале.** STELLA исследует кодовую базу, планирует, читает и редактирует файлы, запускает команды и тесты, разбирает ошибки, исправляет их и проверяет результат — в цикле, пока задача не будет решена. Каждый вызов инструмента реально выполняется на вашей машине, под контролем системы разрешений.

```
  ███████╗████████╗███████╗██╗     ██╗      █████╗
  ██╔════╝╚══██╔══╝██╔════╝██║     ██║     ██╔══██╗
  ███████╗   ██║   █████╗  ██║     ██║     ███████║
  ╚════██║   ██║   ██╔══╝  ██║     ██║     ██╔══██║
  ███████║   ██║   ███████╗███████╗███████╗██║  ██║
  ╚══════╝   ╚═╝   ╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝
```

- **Agent loop**: запрос → сбор контекста → план → инструменты (параллельно, где безопасно) → анализ результата → следующий шаг → проверка → отчёт. Ретраи при 429/5xx, прерывание по `Esc`, сообщения «на ходу», авто-компрессия контекста.
- **40+ инструментов**: файлы (Read/Write/Edit/MultiEdit/Delete/Move/Copy/FileInfo/DirectoryTree), поиск (Glob/Grep/SymbolSearch/ReferenceSearch/SemanticSearch/DependencySearch), терминал (Bash/PowerShell/Cmd/RunCommand/RunScript/StartProcess/ProcessStatus/StopProcess), Git, WebFetch/WebSearch, TestRunner/Linter/Formatter/Diagnostics/PackageManager, Task (субагенты), TodoWrite, Skill, Memory, Plan Mode, AskUserQuestion, плюс любые MCP-инструменты.
- **Любые модели**: FreeLLMAPI (по умолчанию, бесплатные модели через один роутер), Anthropic (официальный SDK, prompt caching, effort, server-side fallbacks), OpenAI, OpenRouter, Groq, Ollama, LM Studio/vLLM и любой OpenAI-совместимый endpoint, Google Gemini (нативный API). Переключение модели посреди сессии.
- **Безопасность по умолчанию**: 5 режимов разрешений, allow/ask/deny-правила, анализ shell-команд (цепочки, подстановки, вложенные интерпретаторы), защита от path traversal и symlink-escape, конфиденциальные файлы, блокировка катастрофических команд даже в bypass-режиме, доверие к папке для проектных хуков/MCP, аудит-лог с маскировкой секретов.
- **Сессии, чекпоинты, память**: JSONL-сессии с возобновлением, `/rewind` откатывает файлы к состоянию до любого шага (с проверкой конфликтов), долговременная память пяти типов, иерархия `STELLA.md`.
- **Расширяемость**: Skills (`SKILL.md`), пользовательские slash-команды, субагенты (`.stella/agents/*.md`), хуки на 12 событий, MCP (stdio / Streamable HTTP / SSE), плагины.

## Установка

Требуется Node.js ≥ 20.10. Работает в Windows Terminal / PowerShell / CMD, Linux, macOS, по SSH и в терминале VS Code.

```bash
cd stella-coder
npm install
npm run build
npm link            # команда `stella` станет доступна глобально
```

### Модель по умолчанию: FreeLLMAPI

STELLA по умолчанию работает через [FreeLLMAPI](https://freellmapi.co) — самохостящийся OpenAI-совместимый роутер, который распределяет запросы по бесплатным моделям десятков провайдеров (с автоматическим фолбэком при 429/5xx).

```bash
curl -fsSL https://freellmapi.co/install.sh | bash      # поднимет роутер на http://localhost:3001
# в дашборде роутера добавьте ключи провайдеров, скопируйте единый ключ freellmapi-…
export FREELLMAPI_API_KEY=freellmapi-...
stella                                                  # модель freellmapi:auto:smart
```

| Модель | Что делает |
|---|---|
| `free` = `freellmapi:auto:smart` | роутер выбирает самую сильную доступную модель (по умолчанию) |
| `free-fast` = `freellmapi:auto:fast` | самую быструю |
| `freellmapi:auto` | стратегия роутера по умолчанию |
| `freellmapi:<id>` | конкретная модель из каталога, например `freellmapi:qwen/qwen3.8-max:free` |

Адрес роутера меняется переменной `FREELLMAPI_BASE_URL` (по умолчанию `http://localhost:3001/v1`). Какую модель роутер реально выбрал, видно в статус-строке (`FreeLLMAPI auto:smart → groq/llama-3.3-70b`). Для агентной работы выбирайте модели с поддержкой tools.

### Другие провайдеры

Укажите ключ нужного провайдера:

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # или OPENAI_API_KEY / OPENROUTER_API_KEY / GROQ_API_KEY / GEMINI_API_KEY
# либо сохраните ключ в ~/.stella/credentials.json (права 600):
stella auth set anthropic sk-ant-...
```

Локальная модель без ключа: `stella -m ollama:qwen2.5-coder:14b`.

## Быстрый старт

```bash
cd ~/my-project
stella                                   # интерактивная сессия
stella "почини падающие тесты"            # сессия с первым запросом
stella -p "объясни архитектуру проекта"   # неинтерактивно, вывод в stdout
cat error.log | stella -p "почему падает?"
stella -c                                # продолжить последнюю сессию
stella --plan "добавь OAuth-логин"        # сначала план, потом реализация
```

В сессии: `/init` создаст `STELLA.md` с описанием проекта, `@src/app.ts` прикрепит файл, `!npm test` выполнит команду сами, `Shift+Tab` переключает режимы, `Esc` прерывает агента.

## Режимы разрешений

| Режим | Поведение |
|---|---|
| `default` | Чтение внутри проекта — без вопросов; правки, команды, сеть — с подтверждением |
| `plan` | Только чтение и анализ; агент показывает план через `ExitPlanMode`, вы одобряете/правите/отклоняете |
| `acceptEdits` | Правки файлов в проекте автоматически; команды и удаления — с подтверждением |
| `auto` | Низкий и средний риск — автоматически; высокий (удаление, установка пакетов, push…) — с подтверждением |
| `bypassPermissions` | Всё без вопросов, кроме катастрофических команд. Только для одноразовых окружений (`--dangerously-skip-permissions`) |

Правила (`settings.json` → `permissions`):

```json
{
  "permissions": {
    "allow": ["Bash(npm test:*)", "Bash(git diff:*)", "Edit(src/**)", "WebFetch(domain:docs.python.org)", "mcp__github"],
    "ask":   ["Bash(git commit:*)"],
    "deny":  ["Bash(git push:*)", "Read(./secrets/**)"],
    "confidential": ["config/prod/**"],
    "additionalDirectories": ["../shared-lib"]
  }
}
```

Allow-правило для Bash должно покрывать **каждую** часть цепочки (`npm test && rm -rf src` не пройдёт по `Bash(npm test:*)`) и никогда не разрешает `$(…)`, обратные кавычки, `bash -c`, `eval`, `xargs` и т. п.

## Slash-команды

`/help` `/clear` `/compact [инструкции]` `/config` `/model [модель]` `/effort` `/status` `/cost` `/context` `/doctor` `/memory` `/agents` `/skills` `/hooks` `/mcp` `/permissions` `/plan` `/resume` `/sessions` `/rename` `/rewind` `/diff` `/todos` `/processes` `/review` `/security-review` `/init` `/commit` `/trust` `/add-dir` `/login` `/reload` `/export` `/exit` — плюс ваши команды из `.stella/commands/*.md` и навыки как `/имя-навыка`.

## Конфигурация

Слои (каждый следующий перекрывает предыдущий): `~/.stella/settings.json` → `<проект>/.stella/settings.json` (в git) → `<проект>/.stella/settings.local.json` (личное) → флаги CLI. Подробно — [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

```json
{
  "model": "sonnet",
  "effort": "high",
  "providers": {
    "lmstudio": { "type": "openai", "baseUrl": "http://localhost:1234/v1",
                  "models": [{ "id": "qwen2.5-coder-32b", "contextWindow": 32768 }] }
  },
  "modelAliases": { "local": "lmstudio:qwen2.5-coder-32b" },
  "autoCompactThreshold": 0.8,
  "maxSubagents": 4
}
```

## Документация

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — модули, agent loop, протоколы
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — настройки, модели, провайдеры
- [docs/EXTENDING.md](docs/EXTENDING.md) — Skills, команды, субагенты, хуки, MCP, плагины
- [docs/SECURITY.md](docs/SECURITY.md) — модель угроз и защиты
- [examples/](examples) — готовые конфигурации

## Разработка

```bash
npm run dev          # запуск из исходников (tsx)
npm run typecheck
npm test             # unit + integration (временные проекты, реальные инструменты)
npm run build
```

Тесты не подделывают выполнение инструментов: «модель» заменяется скриптом, который отвечает по настоящим протоколам OpenAI / Anthropic / Gemini (SSE) через локальный HTTP-сервер, а файлы, команды, git и MCP-серверы работают по-настоящему во временных каталогах. CI гоняет набор на Linux, Windows и macOS (Node 20 и 22).
