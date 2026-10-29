# Умная колонка на Orange Pi 4 LTS (ElevenLabs Conversational AI)

## 1. Агент в ElevenLabs
Conversational AI → Create Agent: LLM — Gemini 2.0 Flash, голос — на ваш выбор (модель multilingual_v2),
язык — русский, System Prompt:
«Ты — умная домашняя колонка-ассистент. Отвечай кратко, емко, дружелюбно, живым языком без длинных списков, так как твой текст будет озвучен».
Скопируйте `Agent ID` и `API Key`.

## 2. Установка на Orange Pi (Armbian)
```bash
sudo apt install -y python3-venv portaudio19-dev libasound2-dev
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # впишите ключ и Agent ID
```

## 3. Запуск
```bash
python speaker.py --list-devices   # найти индексы USB-микрофона и колонки
python speaker.py
```
Если слышно эхо (колонка слушает саму себя) — отодвиньте микрофон или используйте наушники/аппаратное эхоподавление.
