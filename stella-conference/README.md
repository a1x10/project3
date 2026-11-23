# Stella Conference

Помощник на созвонах для Stella: панель поверх экрана, слушает микрофон и звук звонка (Zoom, Meet, Teams, Telegram…), расшифровывает речь, отвечает на вопросы, объясняет скриншоты.
Запускается из **Stella.exe** — переключатель «Конференция». Работает на моделях Gemini (семейство Antigravity) через ваш сервер Stella: ответы — `gemini-flash-latest`, распознавание речи — `gemini-flash-lite-latest`.

## Происхождение и лицензия

**Stella Conference — изменённая версия [Pluely](https://github.com/iamsrikanthnani/pluely) © Srikanth Nani**, распространяется на условиях **GNU GPL v3.0** (файл [LICENSE](LICENSE)).
Исходный код этой версии: https://github.com/a1x10/project3, папка `stella-conference`. Программа поставляется без каких-либо гарантий.

Изменения относительно Pluely (2026, для Stella):
- название, иконки и идентификатор приложения: Stella Conference;
- встроенные провайдеры «Stella» (чат, OpenAI-совместимый) и «Stella (Gemini)» (распознавание речи) — через сервер Stella с токеном аккаунта; аккаунт передаёт Stella.exe через переменные окружения `STELLA_SERVER`, `STELLA_TOKEN`, `STELLA_USER`;
- отключены: платная лицензия и сервер оригинала, автообновление с сервера оригинала (обновления приходят вместе со Stella.exe), аналитика PostHog;
- отключены функции скрытности: окна видны при демонстрации экрана, иконка в панели задач, курсор видимый;
- новая главная страница со статусом подключения к Stella, блок «О программе» в настройках.

## Сборка

Windows-сборку делает GitHub Actions (`.github/workflows/stella-conference.yml`): `npm ci`, `npx tauri build --no-bundle`, затем `stella-conference.exe` кладётся в `agy-desktop/release/StellaConference.exe`.
Локально: Node 20+, Rust stable, `npm ci && npx tauri build --no-bundle`.
