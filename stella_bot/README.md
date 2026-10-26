# ✦ Stella — бот проекта STELLS

Telegram-бот на базе **ElevenLabs API**. Доступ открывается только по ключу бета-тестирования,
дальше с пользователем знакомится Стелла — ИИ проекта STELLS — и открывает лабораторию функций.

## Что умеет

| Раздел | Что делает | API ElevenLabs |
|---|---|---|
| 🤖 ИИ-агенты | чат со Стеллой, создание своих агентов (имя, характер, приветствие, голос), чат текстом и голосовыми, голосовые ответы | Agents + WebSocket |
| 🎵 Песни | песня по описанию (с вокалом или инструментал), музыка к видео с наложением на ролик, разделение трека на стемы | Music |
| 🎬 Видео | видео по описанию (Veo 3.1 / Seedance 2), оживление фото, говорящий аватар с синхронизацией губ | Image & Video |
| 🖼 Изображения | генерация и редактирование фото (Nano Banana, GPT Image 2, Seedream) | Image & Video |
| 🗣 Озвучка | текст в речь (Multilingual v2, v3, v4, Flash), теги эмоций | Text to Speech |
| 🎭 Диалоги | сцены на несколько голосов в формате `Имя: реплика` | Text to Dialogue |
| 💥 Звуки | звуковые эффекты по описанию | Sound Effects |
| 🎙 Смена голоса | голос в голос с сохранением эмоций | Voice Changer |
| 📝 Расшифровка | речь в текст, 90+ языков, разделение по спикерам | Speech to Text |
| 🎧 Очистка | удаление шума и музыки из записи | Voice Isolator |
| 🧬 Дизайн голоса | новый голос по текстовому описанию, 3 варианта на выбор | Voice Design |
| 🧪 Клон голоса | мгновенное клонирование по образцам | Instant Voice Cloning |
| 🌍 Дубляж | перевод и озвучка видео/аудио на 15 языков + субтитры | Dubbing |
| 📚 Голоса | библиотека с прослушиванием, поиском и выбором голоса | Voices |
| ⚙️ Настройки | модели, стабильность, скорость, длина треков, формат и качество видео и т.д. | — |
| 👤 Профиль | вход по тому же ключу, статистика, кредиты ElevenLabs, история, свой API-ключ | User |

Оформление: фирменные баннеры для каждого раздела (меню редактируется на месте), цветные кнопки,
загрузочная анимация терминала при старте, эффект «печатной машинки» у Стеллы, эффекты сообщений 🎉🔥❤️
и **своя анимированная загрузка для каждой функции** — эквалайзер для музыки, плёнка для видео,
проявляющиеся пиксели для картинок, звуковая волна для озвучки, нейросеть для агентов, ДНК для голосов —
с прогресс-баром, этапами и таймером.

## Запуск

```bash
cd stella_bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # заполните BOT_TOKEN и ELEVENLABS_API_KEY
python bot.py
```

Для склейки музыки/дубляжа с видео нужен установленный **ffmpeg** (без него бот пришлёт отдельные дорожки).

### Важно про тарифы ElevenLabs
* Генерация изображений и видео требует тариф **Pro** и выше.
* Музыка, клонирование голоса и дубляж доступны на платных тарифах.
* Если у функции не хватает тарифа, бот покажет понятную ошибку от ElevenLabs прямо в окне загрузки.

## Куда класть ключи

Все ключи хранятся в файле **`stella_bot/.env`** (рядом с `bot.py`). В git он не попадает (указан в `.gitignore`),
поэтому на сервере его нужно создать вручную из шаблона:

```bash
cp .env.example .env
nano .env
```

| Переменная | Где взять |
|---|---|
| `BOT_TOKEN` | @BotFather → `/newbot` (или `/token` для существующего бота) |
| `ELEVENLABS_API_KEY` | elevenlabs.io → Developers → API Keys → Create key (включите нужные разрешения) |
| `BETA_KEY` | ключ доступа для пользователей, по умолчанию `085213` |
| `SHOP_URL`, `CREATOR_USERNAME` | необязательно: ссылка на магазин и ваш username без `@` |

## Запуск на сервере (Ubuntu/Debian, systemd)

```bash
# 1. Зависимости
sudo apt update && sudo apt install -y git python3 python3-venv ffmpeg

# 2. Код
sudo useradd -r -m -s /usr/sbin/nologin stella
sudo git clone -b claude/stoic-cori-k45kfx https://github.com/a1x10/project3.git /opt/project3
cd /opt/project3/stella_bot

# 3. Окружение и ключи
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env && sudo nano .env      # вписать ключи
sudo chown -R stella:stella /opt/project3
sudo chmod 600 .env

# 4. Автозапуск
sudo cp deploy/stella-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stella-bot

# Логи и управление
sudo journalctl -u stella-bot -f
sudo systemctl restart stella-bot
```

Обновление: `cd /opt/project3 && sudo -u stella git pull && sudo systemctl restart stella-bot`.

## Запуск через Docker

```bash
git clone -b claude/stoic-cori-k45kfx https://github.com/a1x10/project3.git
cd project3/stella_bot
cp .env.example .env && nano .env
docker compose up -d --build
docker compose logs -f
```

> Бот работает через long polling — домен, открытые порты и HTTPS не нужны.
> Запускайте только **один** экземпляр бота с одним токеном, иначе Telegram вернёт ошибку `Conflict`.

## Структура

```
bot.py              точка входа
config.py           настройки из .env
storage.py          пользователи, настройки, статистика (data/users.json)
eleven.py           клиент ElevenLabs API + чат с агентами по WebSocket
media.py            ffmpeg: наложение звука на видео
ui/anim.py          анимации загрузки, печатная машинка, загрузка при старте
ui/screens.py       экраны-баннеры и кнопки
handlers/           онбординг, меню, все функции, настройки, профиль
assets/banners/     баннеры разделов
tools/make_banners.py  генератор баннеров
```
