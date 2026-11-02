# Установка STELLA CODER и Vibing AI Studio

Установщик ставит один или оба проекта и **сам скачивает, настраивает и запускает роутер [FreeLLMAPI](https://freellmapi.co)**, через который работает ИИ. После установки роутер поднимается автоматически при каждом запуске `stella` и студии.

| | Что это | Запуск после установки |
|---|---|---|
| **1. STELLA CODER** | AI-агент для разработки в терминале | `stella-coder` (или `stella`) в папке вашего проекта |
| **2. Vibing AI Studio** | конструктор сайтов с ИИ в браузере | `cd vibing-studio && npm run dev` → http://localhost:3000 |

## Что нужно заранее

- **Node.js 20.18 или новее** (рекомендуется 22 LTS) — https://nodejs.org
  Windows: `winget install OpenJS.NodeJS.LTS` · macOS: `brew install node@22`
- **git** — чтобы скачать этот репозиторий.
- **Docker Desktop или Podman** — желательно, не обязательно. Если Docker есть, роутер ставится контейнером (как официальный установщик); Docker Desktop установщик запустит сам, если он не запущен. Если Docker нет, роутер собирается из исходников и запускается фоновым процессом — для этого нужен Node.js **20.18–24** (на Node 25+ роутер из исходников не собирается, нужен Docker).

## Установка

Скачайте репозиторий:

```bash
git clone -b claude/elegant-bell-3a87rj https://github.com/a1x10/project3.git
cd project3
```

**Linux / macOS / WSL:**

```bash
./install.sh
```

**Windows:** дважды щёлкните `install.cmd` или выполните в PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

Установщик спросит, что ставить (`1` — STELLA, `2` — студия, `3` — оба), и дальше всё сделает сам:

1. **Роутер FreeLLMAPI** — пишет `~/freellmapi/.env` (со случайным ключом шифрования) и `docker-compose.yml`, скачивает образ `ghcr.io/tashfeenahmed/freellmapi:latest` и запускает контейнер. Без Docker — клонирует исходники в `~/freellmapi/app`, выполняет `npm ci` и `npm run build`, запускает `node server/dist/index.js` в фоне.
2. **Аккаунт дашборда роутера** — создаёт его. Email и пароль можно ввести самому или нажать Enter: тогда пароль сгенерируется и сохранится в `~/freellmapi/dashboard-login.txt` (права 600).
3. **Единый ключ `freellmapi-…`** — получает его от роутера и сохраняет в `~/.stella/credentials.json` (права 600). Этот ключ используют и STELLA, и студия, вводить его вручную не нужно.
4. **Бесплатные провайдеры без ключа** (Kilo Gateway, OVH) — по согласию включает их, чтобы ИИ заработал сразу. ⚠️ Kilo по своим правилам может использовать бесплатные запросы для обучения моделей — не отправляйте через него закрытый код.
5. **Ключи Groq / Google AI Studio / OpenRouter** — предлагает добавить. Они бесплатные, быстрее и надёжнее; можно пропустить и добавить позже в дашборде.
6. **Сборка** — собирает STELLA и регистрирует команду `stella` (`npm link`, либо `~/.local/bin/stella`) и/или собирает студию.

Повторный запуск безопасен: ключ шифрования и аккаунт сохраняются, роутер обновляется.

### Варианты

```bash
./install.sh --stella             # только STELLA CODER (+ роутер)
./install.sh --studio             # только Vibing AI Studio (+ роутер)
./install.sh --yes                # без вопросов (пароль дашборда будет сгенерирован)
./install.sh --router-mode docker # или source — принудительно выбрать способ установки роутера
./install.sh --router-mode skip   # роутер уже стоит отдельно (например, desktop .exe)
./install.sh --no-keyless         # не включать провайдеры без ключа
```

На Windows те же флаги передаются в `install.cmd` / `install.ps1`.

## Запуск

**STELLA CODER:**

```bash
cd ~/мой-проект
stella-coder                       # интерактивная сессия (то же: stella)
stella-coder -p "почини тесты"     # одна задача без интерактива
stella-coder router status         # состояние роутера
```

**Vibing AI Studio:**

```bash
cd project3/vibing-studio
npm run dev                  # http://localhost:3000
```

Первый зарегистрированный в студии пользователь становится администратором.

## Роутер FreeLLMAPI

Роутер стартует сам при запуске `stella` и `npm run dev` / `npm run preview`. Управлять им вручную можно так:

```bash
node tools/freellmapi-router.mjs status    # установлен ли, запущен ли, сохранён ли ключ
node tools/freellmapi-router.mjs start
node tools/freellmapi-router.mjs stop
node tools/freellmapi-router.mjs logs
stella router status                        # то же самое через STELLA
```

Дашборд роутера — http://localhost:3001 (вход по вашему email и паролю; если пароль генерировался — он в `~/freellmapi/dashboard-login.txt`). Там добавляются ключи провайдеров и настраивается порядок фолбэка.

| Переменная | Назначение |
|---|---|
| `FREELLMAPI_DIR` | каталог установки роутера (по умолчанию `~/freellmapi`) |
| `FREELLMAPI_PORT` | порт (по умолчанию 3001; если он занят другой программой, установщик выберет свободный и запомнит его) |
| `FREELLMAPI_API_KEY` | единый ключ (вместо `~/.stella/credentials.json`) |
| `FREELLMAPI_BASE_URL` | адрес API для STELLA (по умолчанию `http://localhost:3001/v1`) |
| `FREELLMAPI_URL` | адрес роутера для студии (по умолчанию `http://localhost:3001`) |
| `STELLA_NO_ROUTER_AUTOSTART=1` | не запускать роутер автоматически |

## Если что-то пошло не так

| Проблема | Что сделать |
|---|---|
| «Нужен Node.js 20.18+» | установите Node 22 LTS и запустите установщик снова |
| Docker установлен, но не запущен | установщик сам запускает Docker Desktop; если не вышло — запустите его вручную, дождитесь «Engine running» и выполните `node install.mjs --router-mode docker` |
| «нужен Node.js 20.18–24» для роутера | у вас Node 25+: используйте Docker (`--router-mode docker`) или поставьте Node 22 LTS |
| На порту 3001 уже работает другая программа (Flowise, Open WebUI…) | установщик это определяет и ставит роутер на следующий свободный порт (3002, …); STELLA и студия берут порт из `~/freellmapi/stella-router.json` |
| `install.ps1` выдаёт ошибки разбора | обновите репозиторий (`git pull`) или запустите напрямую: `node install.mjs` |
| Роутер не отвечает | `node tools/freellmapi-router.mjs logs` |
| `stella: command not found` | откройте новый терминал; на Linux добавьте `~/.local/bin` в `PATH` |
| `stella` запускает другую программу (например, Hermes Agent) | используйте команду `stella-coder` — это та же STELLA CODER с уникальным именем |
| ИИ отвечает ошибкой 401 | ключ устарел: `./install.sh` получит его заново, или `stella auth set freellmapi <ключ>` |
| Все модели заняты / 429 | добавьте ключи Groq / Gemini / OpenRouter в дашборде роутера |

Удаление роутера: `cd ~/freellmapi && docker compose down -v && cd .. && rm -rf ~/freellmapi` (для режима из исходников — `node tools/freellmapi-router.mjs stop` и удалить `~/freellmapi`).
