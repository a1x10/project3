# Умная колонка (Orange Pi 4 LTS + ElevenLabs Conversational AI)

Полная инструкция от прошивки до запуска, подключение DJI-микрофона и Bluetooth-колонки: см. [SETUP.md](SETUP.md).

Кратко:
1. Создайте агента в ElevenLabs (Conversational AI), скопируйте Agent ID и API Key.
2. `pip install -r requirements.txt`, `cp .env.example .env`, впишите ключи.
3. `python speaker.py --list-devices`, затем `python speaker.py`.
