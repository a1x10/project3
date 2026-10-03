#!/usr/bin/env python3
"""Получить OAuth-токен для управления умным домом Яндекса (права iot:view и iot:control).

1. Зарегистрируйте приложение: https://oauth.yandex.ru/client/new/
   тип «Для доступа к API или отладки», доступы: «Умный дом Яндекса» → просмотр и управление (iot:view, iot:control).
2. Запустите:  .venv/bin/python deploy/yandex_iot_token.py <ClientID> <Client secret>
3. Откройте показанную ссылку, введите код — токен появится здесь. Впишите его в smarthome.yandex_token.
"""
import sys
import time

import requests


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    client_id, secret = sys.argv[1], sys.argv[2]
    r = requests.post("https://oauth.yandex.ru/device/code",
                      data={"client_id": client_id, "device_name": "Stella", "scope": "iot:view iot:control"},
                      timeout=15)
    r.raise_for_status()
    d = r.json()
    print(f"\nОткройте {d['verification_url']} и введите код: {d['user_code']}\n")
    deadline = time.time() + int(d.get("expires_in", 300))
    while time.time() < deadline:
        time.sleep(int(d.get("interval", 5)))
        t = requests.post("https://oauth.yandex.ru/token", data={"grant_type": "device_code", "code": d["device_code"],
                                                                 "client_id": client_id, "client_secret": secret},
                          timeout=15).json()
        if "access_token" in t:
            print("Токен умного дома:\n", t["access_token"])
            return
        if t.get("error") not in ("authorization_pending", "slow_down"):
            print("Ошибка:", t)
            return
    print("Время ожидания истекло, попробуйте ещё раз.")


if __name__ == "__main__":
    main()
