#!/usr/bin/env python3
"""Получить токен Яндекс Музыки (вход по коду с телефона/компьютера).

    .venv/bin/python deploy/yandex_music_token.py

Откройте показанную ссылку, введите код и разрешите доступ — токен появится здесь.
Вставьте его в config.yaml (yandex_music.token) или в переменную YANDEX_MUSIC_TOKEN.
"""
from yandex_music import Client


def main():
    client = Client()
    token = client.device_auth(on_code=lambda c: print(f"\nОткройте {c.verification_url} и введите код: {c.user_code}\n"))
    print("Токен Яндекс Музыки:\n", token.access_token)


if __name__ == "__main__":
    main()
