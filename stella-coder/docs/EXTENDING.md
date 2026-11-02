# Расширение STELLA

## Skills

Навык — каталог с `SKILL.md` (Markdown + frontmatter) и ресурсами:

```
.stella/skills/pdf-report/
  SKILL.md
  references/format.md
  scripts/render.py
```

```markdown
---
name: pdf-report
description: Генерация PDF-отчётов из CSV
when_to_use: пользователь просит отчёт, PDF, выгрузку
allowed-tools: Read, Bash, Write
disable-model-invocation: false   # true — только вручную через /pdf-report
user-invocable: true              # доступен как /pdf-report
---
Инструкции… Скрипты лежат в ${SKILL_DIR}/scripts. $ARGUMENTS — аргументы вызова.
```

Где ищутся: встроенные (`builtin/skills`: react, python, backend, frontend, database, testing, security-audit, devops, documentation) → `~/.stella/skills` → плагины → `.stella/skills` (проектные перекрывают остальные). Модель видит список навыков в системном промпте и загружает подходящий инструментом `Skill`; при явном совпадении запроса с описанием STELLA дополнительно подсказывает навык. Управление: `/skills list|show|create|delete|reload`.

## Slash-команды

`.stella/commands/<имя>.md` или `~/.stella/commands/<имя>.md`:

```markdown
---
description: Сгенерировать миграцию
argument-hint: <название>
---
Создай миграцию БД "$ARGUMENTS" инструментом проекта, проверь up/down и запусти тесты.
```

Вызов: `/имя аргументы`. Поддерживаются `$ARGUMENTS`, `$1`, `$2`…

## Субагенты

`.stella/agents/<имя>.md`:

```markdown
---
name: migrator
description: Пишет и проверяет миграции БД
tools: Read, Grep, Glob, Write, Edit, Bash
model: sonnet              # или inherit
permissionMode: acceptEdits
maxTurns: 40
---
Ты — специалист по миграциям…
```

Встроенные: `general`, `explorer`, `planner`, `coder`, `debugger`, `tester`, `reviewer`, `security-auditor`, `docs`. Главный агент вызывает их через `Task` (несколько вызовов в одном ответе выполняются параллельно). `/agents list|runs|cancel <id>|create <имя> <описание>`.

## Hooks

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [{ "type": "command", "command": "node .stella/hooks/guard.cjs", "timeout": 10 }] }
    ],
    "PostToolUse": [
      { "matcher": "Edit|Write|MultiEdit", "hooks": [{ "type": "command", "command": "node .stella/hooks/format.cjs" }] }
    ],
    "Stop": [{ "hooks": [{ "type": "command", "command": "npm run lint --silent || (echo 'lint failed' >&2; exit 2)" }] }]
  }
}
```

События: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolFailure`, `PermissionRequest`, `Notification`, `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PostCompact`. `matcher` — регулярное выражение по имени инструмента (для инструментальных событий).

Протокол: JSON с `hook_event_name`, `session_id`, `cwd`, `project_dir`, `tool_name`, `tool_input`, `tool_response`, `prompt`… приходит в stdin. Переменные окружения: `STELLA_PROJECT_DIR`, `STELLA_HOOK_EVENT`.

| Результат | Эффект |
|---|---|
| exit 0, пустой вывод | продолжить |
| exit 0, текст | для `UserPromptSubmit`/`SessionStart`/`PostToolUse` — дополнительный контекст модели, иначе сообщение пользователю |
| exit 0, JSON | `decision`: `block`/`deny`/`approve`/`allow`/`ask`, `reason`, `additionalContext`, `systemMessage`, `continue:false`, `updatedInput` (PreToolUse) |
| exit 2 | блокировка; stderr передаётся модели (для `Stop` — агент продолжит работу) |
| другой код | неблокирующая ошибка, показывается пользователю |

Таймаут по умолчанию 60 с (максимум 600). Хуки из проектных настроек работают только в доверенной папке (`/trust`, `--trust`). Журнал: `/hooks history`.

## MCP

```bash
stella mcp add github -- npx -y @modelcontextprotocol/server-github
stella mcp add docs --url https://mcp.example.com/mcp --header 'Authorization: Bearer ${DOCS_TOKEN}'   # раскрывается при подключении
stella mcp list
stella mcp test github
```

Или в настройках / `.mcp.json` проекта:

```json
{
  "mcpServers": {
    "fs": { "type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."], "env": { "DEBUG": "0" } },
    "remote": { "type": "http", "url": "https://mcp.example.com/mcp", "headers": { "Authorization": "Bearer ${MCP_TOKEN}" } },
    "legacy": { "type": "sse", "url": "https://old.example.com/sse" }
  }
}
```

`${VAR}` и `${VAR:-default}` раскрываются из окружения. Инструменты появляются как `mcp__<сервер>__<инструмент>` и проходят ту же систему разрешений (по умолчанию — с подтверждением; разрешить сервер целиком: `mcp__<сервер>`). Серверы из проекта (`.mcp.json`, проектные настройки) подключаются только в доверенной папке.

## Плагины

`~/.stella/plugins/<имя>/plugin.json` или `.stella/plugins/<имя>/plugin.json`:

```json
{
  "name": "acme-tools",
  "version": "1.0.0",
  "description": "Навыки, команды и MCP команды ACME",
  "skills": "skills",
  "commands": "commands",
  "agents": "agents",
  "hooks": { "PostToolUse": [{ "matcher": "Write", "hooks": [{ "type": "command", "command": "${PLUGIN_DIR}/bin/scan" }] }] },
  "mcpServers": { "tracker": { "command": "${PLUGIN_DIR}/bin/tracker-mcp" } }
}
```

`enabledPlugins` в настройках ограничивает набор. Проектные плагины требуют доверия к папке.

## Программный API

```ts
import { Runtime } from 'stella-coder';

const rt = await Runtime.create({ cwd: '/path/to/project', model: 'sonnet', permissionMode: 'acceptEdits' });
rt.events.on('event', (e) => e.type === 'text_delta' && process.stdout.write(e.text));
rt.handlers.permission = async (req) => ({ decision: req.descriptor.risk === 'high' ? 'deny' : 'allow_once' });
const result = await rt.submit('Добавь валидацию email в форму регистрации и тесты');
console.log(result?.text, rt.session.costUsd);
await rt.shutdown();
```
