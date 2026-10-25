# Stella Core

Сервер-мозг Стеллы (FastAPI + SQLite). Очки и телефон — клиенты этого сервера.

## Деплой на VPS
```
cp .env.example .env     # заполнить STELLA_API_KEY и OPENROUTER_API_KEY
docker compose up -d --build
```
Порт слушается только на 127.0.0.1:8000 — выставьте наружу через nginx/Caddy с HTTPS.
RAM: Whisper `base` для VPS 2 ГБ, `small` (~1–1,5 ГБ) для 4 ГБ+.

Все эндпоинты требуют `Authorization: Bearer $STELLA_API_KEY` (для SSE допустим `?key=`).

| Эндпоинт | Назначение |
|---|---|
| `POST /chat` `{text}` | диалог (текст) |
| `POST /voice` (файл `audio`) | Whisper -> диалог |
| `GET /events` | SSE-канал пушей: `hud speak action scan photo card suggest` |
| `POST /notify` `{app,sender,text,key}` | уведомление с телефона (важность, ночной режим) |
| `POST /alert` `{source,text,speak}` | алерты ботов, см. `scripts/send_alert.py` |
| `POST /vision/look` (файл `image`) | зрение без слов |
| `POST /vision/remember` (файл `image`) | визуальная память («где ключи?» — через `/chat`) |
| `POST /faces/identify` (файл `image`) | кто это (только база из `/admin`) |
| `GET /admin` | загрузка лиц, обязательна галочка согласия |
| `POST /home/act` | прямое управление домом (для кнопки «сделать» в `suggest`) |
| `POST /v1/chat/completions` | OpenAI-формат для AIUI Studio |

Событие `action` `{action:"reply", key, sender, text}` — телефон отвечает на уведомление `key`.

## Календарь
На ПК: `python scripts/google_auth.py credentials.json`, затем положите `google_token.json` в `data/`.

## Home Assistant
Заполните `HA_URL`, `HA_TOKEN`, `HOME_ALIASES`. Замки (`lock.*`) и `CONFIRM_ENTITIES` (стиралка)
выполняются только после подтверждения: сервер сам запоминает запрос и принимает `confirmed=true`
лишь в течение 2 минут после него.

## Заметки
- Лица считаются локально (OpenCV YuNet+SFace, модели скачиваются в `data/models` при первом запуске).
- Привычки: смена состояний пишется раз в минуту; ≥4 дней из 14 около одного времени (±20 мин) → предложение за 20 мин.
- Настоящее голосовое в WhatsApp и приложения телефона/очков — следующие этапы.
