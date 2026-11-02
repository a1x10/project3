# Примеры конфигурации

Скопируйте нужное в свой проект (`.stella/…`) или в `~/.stella/`.

| Файл | Что показывает |
|---|---|
| `.stella/settings.json` | правила разрешений, хуки форматирования и защиты, модель по умолчанию |
| `.stella/hooks/guard.cjs` | PreToolUse-хук: блокирует опасные команды (exit 2) |
| `.stella/hooks/format.cjs` | PostToolUse-хук: прогоняет prettier по изменённому файлу |
| `.stella/agents/migrator.md` | пользовательский субагент |
| `.stella/commands/release.md` | пользовательская slash-команда `/release` |
| `.stella/skills/release-notes/SKILL.md` | навык с инструкциями |
| `.mcp.json` | MCP-серверы проекта |
| `settings.providers.json` | Ollama, LM Studio, OpenRouter, корпоративный endpoint |
| `plugin/acme/` | плагин: команды + хук |
| `STELLA.md` | инструкции проекта для агента |
