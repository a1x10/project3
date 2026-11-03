# Stella Cloud — ваш сервер для STELLA CODER и Vibing AI Studio

Stella Cloud — это сервер, через который работают оба приложения:

- **Telegram-бот.** Через него проходит регистрация и вход. Пароли не нужны: при первом `/start` создаётся аккаунт, а вход в сайт, студию или терминал подтверждается кнопкой в чате.
- **Шлюз моделей** (OpenAI-совместимый `/v1`). Он добавляет **ваш системный промпт** к каждому запросу, следит за тарифами и дневными лимитами, считает расход и передаёт запрос в FreeLLMAPI. Для приложений это выглядит как одна модель `auto`.
- **Сайт.** Он открывается в браузере: лендинг со ссылками на скачивание, личный кабинет (тариф, лимиты, ключи API, график запросов, удаление аккаунта) и **админ-панель**: пользователи, поиск, тарифы, роль, блокировка, удаление, промпт, модели, тарифные планы, состояние FreeLLMAPI.
- **FreeLLMAPI**. Он работает в соседнем контейнере. Ключи провайдеров и модели вы настраиваете в его дашборде сами.

```
STELLA CODER ─┐                    ┌─ Telegram-бот (регистрация, вход, админ-команды)
Studio (.exe) ├─► Stella Cloud ────┤─ сайт: кабинет + админка
OpenAI-клиент ┘   (промпт, лимиты) └─► FreeLLMAPI ─► бесплатные провайдеры (ваши ключи)
```

## Установка на VPS (Ubuntu/Debian, 1 ГБ RAM достаточно)

1. Создайте бота у [@BotFather](https://t.me/BotFather): `/newbot` → скопируйте токен.
2. Узнайте свой числовой Telegram ID у [@userinfobot](https://t.me/userinfobot). С ним вы станете администратором.
3. (Желательно) Направьте домен на IP сервера (A-запись). Тогда HTTPS настроится сам.
4. На сервере:

```bash
git clone -b claude/elegant-bell-3a87rj https://github.com/a1x10/project3.git
cd project3/cloud && sudo bash deploy.sh
```

Скрипт установит Docker (если его нет) и спросит токен бота, ваш ID и домен. Секреты он сгенерирует сам, запишет `.env` и запустит три контейнера: `freellmapi`, `stella-cloud` и `caddy` (HTTPS через Let's Encrypt). Без домена сайт будет доступен по `http://IP`.

5. Напишите своему боту `/start` — вы станете администратором.

### Ключи провайдеров и модели (FreeLLMAPI)

Дашборд FreeLLMAPI наружу не открыт. Зайти в него можно через SSH-туннель:

```bash
ssh -L 3001:127.0.0.1:3001 root@IP-сервера
```

Затем откройте http://localhost:3001. Логин и пароль показал `deploy.sh`, они также лежат в `cloud/.env` (`ROUTER_ADMIN_EMAIL` / `ROUTER_ADMIN_PASSWORD`). Там на странице **Keys** добавьте ключи Groq, Gemini, OpenRouter и других провайдеров, а также настройте модели и порядок фолбэка. Единый ключ роутера Stella Cloud получает сама.

Сразу после установки сервер включает бесплатные провайдеры без ключа (Kilo Gateway, OVH), чтобы ИИ ответил с первого запроса. Отключить их можно в дашборде или переменной `ROUTER_KEYLESS=` (пусто). ⚠️ Kilo по своим правилам может использовать бесплатные запросы для обучения.

> Условия бесплатных тарифов провайдеров обычно разрешают только личное использование. Перед тем как давать доступ другим людям, проверьте правила каждого провайдера, ключ которого добавляете. Отвечаете за это вы.

## Администрирование

**На сайте** (`/#/admin`, видно только администраторам):
- пользователи: поиск, тариф, роль, блокировка (ключи отзываются, сессии закрываются), удаление, просмотр ключей и графика;
- «Промпт и тарифы»: системный промпт для всех запросов, режим, модель по умолчанию, список разрешённых моделей, тарифы (JSON: `dailyRequests`, `dailyTokens`, `null` = без лимита), тариф для новых пользователей;
- статистика и состояние FreeLLMAPI.

**В Telegram** (команды администратора):

| Команда | Что делает |
|---|---|
| `/stats` | статистика за сегодня |
| `/users [поиск]` | список пользователей |
| `/user ID\|@ник` | карточка с кнопками «Заблокировать» и «Удалить» |
| `/plan ID тариф` | сменить тариф (`free`, `pro`, `unlimited` или ваши) |
| `/ban ID` · `/unban ID` | блокировка |
| `/admin ID` · `/unadmin ID` | права администратора |
| `/deluser ID` | удалить аккаунт (с подтверждением) |
| `/prompt` · `/setprompt ТЕКСТ` | показать или изменить системный промпт (переносы строк сохраняются) |
| `/model ID` | модель по умолчанию |

Пользователям доступны `/me`, `/key [название]`, `/keys` (с отзывом), `/login КОД`, `/delete`.

## Раздача приложений пользователям

Пользователям нужны только сайт и бот: всё остальное они скачивают с вашего сервера.

1. В GitHub → Actions → последний запуск **CI** → **Artifacts** скачайте `stella-coder-package` (агент, `.tgz`) и `VibingAIStudio-Setup` (установщик для Windows). Чтобы в приложение был вшит адрес сервера, заранее задайте переменную репозитория `STELLA_CLOUD_URL` (Settings → Secrets and variables → Actions → Variables) и перезапустите CI.
2. Распакуйте zip-архивы и положите файлы на сервер:
   ```bash
   scp stella-coder-0.1.0.tgz VibingAIStudio-Setup-1.0.0.exe alex@IP-сервера:~/
   cd ~/project3/cloud && sudo docker compose cp ~/stella-coder-0.1.0.tgz stella-cloud:/data/downloads/ && sudo docker compose cp ~/VibingAIStudio-Setup-1.0.0.exe stella-cloud:/data/downloads/
   ```
3. На главной странице сайта появятся кнопка «Скачать Studio для Windows» и команды установки агента:
   - Windows (PowerShell): `irm https://ваш-домен/install.ps1 | iex`
   - Linux / macOS: `curl -fsSL https://ваш-домен/install.sh | bash`

   Команда сама поставит Node.js (Windows, через winget), установит агента и откроет бота для подтверждения входа.

Новая версия — просто положите новый файл: сайт и установщики берут самый свежий `stella-coder*.tgz`.

## Подключение приложений

- **Vibing AI Studio** (Windows): установщик `.exe` положите в том `stella-data` → `/data/downloads/`. Например: `docker compose cp VibingAIStudio-Setup-1.0.0.exe stella-cloud:/data/downloads/`. Он появится на сайте в разделе «Скачать». В приложении нажмите «Войти через Telegram»; адрес сервера спрашивается один раз.
- **STELLA CODER**: `stella-coder login https://ваш-домен`. После подтверждения в Telegram модель по умолчанию станет `cloud:auto`.
- **Любой OpenAI-клиент**: Base URL `https://ваш-домен/v1`, ключ выдаёт бот командой `/key`, модель `auto`.

## Обслуживание

```bash
cd project3/cloud
docker compose logs -f stella-cloud      # логи сервера и бота
git pull && docker compose up -d --build # обновление
docker compose exec stella-cloud sh -c 'cp /data/stella-cloud.db /data/backup-$(date +%F).db'   # резервная копия
```

Данные хранятся в томах Docker: `stella-data` (пользователи, ключи, статистика; SQLite) и `freellmapi-data` (ключи провайдеров FreeLLMAPI в зашифрованном виде).

## Переменные (`cloud/.env`)

| Переменная | Назначение |
|---|---|
| `DOMAIN`, `PUBLIC_URL` | домен для HTTPS и публичный адрес (ссылки в боте) |
| `TELEGRAM_BOT_TOKEN` | токен бота |
| `ADMIN_TELEGRAM_IDS` | ID администраторов через запятую (если пусто — админом становится первый зарегистрированный) |
| `ROUTER_ADMIN_EMAIL`, `ROUTER_ADMIN_PASSWORD`, `FREELLMAPI_ENCRYPTION_KEY` | аккаунт и ключ шифрования FreeLLMAPI (генерируются) |
| `SYSTEM_PROMPT`, `DEFAULT_MODEL` | начальные значения; дальше меняются в админке и боте |
| `ROUTER_KEYLESS` | бесплатные провайдеры без ключа, которые включаются автоматически (по умолчанию `kilo,ovh`) |
| `UPSTREAM_BASE_URL`, `UPSTREAM_API_KEY` | вместо FreeLLMAPI использовать любой другой OpenAI-совместимый API |

## Разработка

```bash
cd cloud/server && npm ci && npm test      # API, бот, шлюз (фейковые Telegram и FreeLLMAPI)
cd cloud/web && npm ci && npm run build    # сайт; затем npm test в server прогонит браузерный e2e
cd cloud/server && TELEGRAM_BOT_TOKEN=… UPSTREAM_BASE_URL=http://localhost:3001/v1 npm run dev
```
