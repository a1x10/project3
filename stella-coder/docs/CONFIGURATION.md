# Конфигурация

## Слои настроек

| Файл | Назначение |
|---|---|
| `~/.stella/settings.json` | Глобальные настройки пользователя (хуки и MCP здесь всегда доверенные) |
| `<проект>/.stella/settings.json` | Настройки проекта, коммитятся в git |
| `<проект>/.stella/settings.local.json` | Личные настройки проекта (добавьте в `.gitignore`); сюда пишут `/permissions`, «Always allow», `/mcp add` |
| флаги CLI | `--model`, `--permission-mode`, `--allowedTools`, `--disallowedTools`, … |

Объекты сливаются, массивы правил объединяются, скаляры перекрываются. Ошибки схемы показываются при запуске и в `/doctor`. `STELLA_HOME` меняет каталог `~/.stella`.

## Все ключи

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `model` | string | `freellmapi:auto:smart` | Модель: алиас, `provider:model` или id из каталога. Также `STELLA_MODEL` |
| `effort` | `low…max` | `high` | Глубина рассуждений для моделей, которые это поддерживают |
| `maxOutputTokens` | number | 64000 | Потолок вывода за ход (ограничивается возможностями модели) |
| `anthropicFallbacks` | bool | `true` | Server-side fallbacks (`fallbacks: "default"`) для поддерживающих моделей Anthropic |
| `providers` | object | — | Свои провайдеры/переопределения: `type` (`anthropic`/`openai`/`gemini`), `baseUrl`, `apiKeyEnv`, `apiKey`, `headers`, `models[]` |
| `modelAliases` | object | — | `{"fast": "groq:llama-3.3-70b-versatile"}` |
| `permissions.defaultMode` | режим | `default` | Стартовый режим |
| `permissions.allow/ask/deny` | string[] | — | Правила, см. ниже |
| `permissions.confidential` | glob[] | — | Дополнительно к встроенным (`.env*`, `*.pem`, `*.key`, `id_rsa*`, `credentials.json`, …) |
| `permissions.additionalDirectories` | string[] | — | Каталоги за пределами проекта, считающиеся рабочей областью |
| `hooks` | object | — | См. [EXTENDING.md](EXTENDING.md#hooks) |
| `mcpServers` | object | — | См. [EXTENDING.md](EXTENDING.md#mcp) |
| `ignore` | glob[] | — | Дополнительные исключения индексации/поиска (вместе с `.gitignore`, `.stellaignore`) |
| `env` | object | — | Переменные окружения для команд, хуков и MCP |
| `maxSubagents` | number | 4 | Параллельные субагенты |
| `maxTurns` | number | 200 | Лимит ходов модели на один запрос |
| `autoCompactThreshold` | 0.1–0.99 | 0.8 | Доля окна контекста, после которой включается авто-компрессия |
| `webSearch` | object | DuckDuckGo | `{"provider": "brave", "apiKeyEnv": "BRAVE_API_KEY"}` или `tavily` |
| `shell` | string | `$SHELL`/bash/Git Bash | Путь к bash-совместимой оболочке |
| `commandTimeoutMs` | number | 120000 | Таймаут команд по умолчанию (максимум 600000) |
| `enabledPlugins` | string[] | все | Белый список плагинов |

## Модели и провайдеры

Встроенные провайдеры: `freellmapi` (`FREELLMAPI_API_KEY`, `FREELLMAPI_BASE_URL`, по умолчанию `http://localhost:3001/v1`), `anthropic` (`ANTHROPIC_API_KEY`, также `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`), `openai` (`OPENAI_API_KEY`), `openrouter` (`OPENROUTER_API_KEY`), `groq` (`GROQ_API_KEY`), `gemini` (`GEMINI_API_KEY`), `ollama` (`http://localhost:11434/v1`, без ключа).

Алиасы: `free` (`freellmapi:auto:smart`), `free-fast` (`freellmapi:auto:fast`), `opus`, `sonnet`, `haiku`, `fable`, `gpt`, `gpt-mini`, `gemini`, `flash`, `groq`. Любая модель провайдера доступна как `provider:model-id`, например `openrouter:anthropic/claude-sonnet-4.5`, `ollama:qwen2.5-coder:14b`. Для моделей вне каталога лимиты и цены берутся по умолчанию — задайте их в `providers.<name>.models`:

```json
{
  "providers": {
    "ollama": { "type": "openai", "baseUrl": "http://localhost:11434/v1",
      "models": [{ "id": "qwen2.5-coder:14b", "contextWindow": 32768, "maxOutput": 8192, "toolCalling": true }] },
    "company": { "type": "openai", "baseUrl": "https://llm.internal/v1", "apiKeyEnv": "COMPANY_LLM_KEY",
      "headers": { "X-Team": "platform" },
      "models": [{ "id": "coder-xl", "contextWindow": 200000, "inputPrice": 1.5, "outputPrice": 6 }] }
  }
}
```

Если модель не поддерживает вызов инструментов (`toolCalling: false`), STELLA работает с ней как с чатом и не имитирует инструменты.

Ключи можно хранить в `~/.stella/credentials.json` (создаётся с правами 600): `stella auth set <provider> <key>`, `stella auth status`, `stella auth remove <provider>`. Ключи маскируются во всех логах и в `/config`.

## Правила разрешений

| Правило | Значение |
|---|---|
| `Read` / `Edit` / `Bash` | весь класс инструментов (`Edit` покрывает Write/MultiEdit/Delete/Move/Copy, `Bash` — PowerShell/Cmd/StartProcess) |
| `Bash(npm test:*)` | команды, начинающиеся с `npm test` |
| `Bash(git log *)` | glob по команде |
| `Bash(make build)` | точное совпадение |
| `Edit(src/**)` | glob относительно корня проекта |
| `Read(//etc/hosts)`, `Read(~/notes/**)` | абсолютные пути и домашний каталог |
| `WebFetch(domain:docs.rs)` | домен и поддомены |
| `mcp__github`, `mcp__github__create_issue` | все инструменты MCP-сервера или один |

Порядок: deny → запрет записи в системные каталоги → блокировка катастрофических команд → plan-режим → ask → allow → bypass → умолчания режима.

## Неинтерактивный режим

```bash
stella -p "задача" --output-format json --allowedTools "Edit,Bash(npm test:*)" --max-turns 30
```

Без пользователя все действия, требующие подтверждения, отклоняются — заранее разрешите нужное правилами или выберите режим (`--permission-mode acceptEdits`). Коды выхода: 0 — успех, 1 — ошибка, 2 — неверные аргументы, 3 — отказ модели.
