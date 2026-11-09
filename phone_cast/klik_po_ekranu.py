"""
klik_po_ekranu.py — подключение телефона к телевизору КЛИКАМИ МЫШКИ
по окну телефона на экране компьютера (окно «Экран телефона» и т.п.).
ADB не нужен.

1) Один раз запомни, куда кликать:
       python klik_po_ekranu.py zapis
   Скрипт по очереди попросит навести мышку на нужное место и нажать Enter.

2) Потом каждый раз просто:
       python klik_po_ekranu.py
   и скрипт сам прокликает всё по порядку.

Важно: окно телефона должно стоять на том же месте и того же размера,
что и во время записи.
"""

import json
import os
import sys
import time

try:
    import pyautogui
except ImportError:
    sys.exit("Нет библиотеки pyautogui. Установи командой:  pip install pyautogui")

FAIL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tochki.json")

# Шаги: (название, тип, сколько ждать после шага в секундах)
SHAGI = [
    ("кнопка «Домой» (кружок внизу окна телефона)", "klik", 1.5),
    ("шторка: ВЕРХ экрана телефона, откуда тянуть вниз", "nachalo_svaipa", 0),
    ("шторка: куда дотянуть (середина экрана телефона)", "konec_svaipa", 1.5),
    ("плитка «Трансляция» в шторке", "klik", 4),
    ("твой телевизор в списке устройств", "klik", 2),
]

pyautogui.FAILSAFE = True  # увёл мышку в левый верхний угол экрана — скрипт остановится


def zapis():
    print("ЗАПИСЬ ТОЧЕК")
    print("Открой окно телефона на компьютере. Для каждого шага открой на телефоне")
    print("нужный экран, наведи мышку на место и нажми Enter в этом окне.\n")
    tochki = []
    for nazvanie, tip, _ in SHAGI:
        input(f"Наведи мышку: {nazvanie} — и нажми Enter… ")
        x, y = pyautogui.position()
        tochki.append([x, y])
        print(f"   запомнил: x={x}, y={y}")
    with open(FAIL, "w", encoding="utf-8") as f:
        json.dump(tochki, f)
    print(f"\nГотово! Точки сохранены в {FAIL}")
    print("Теперь запускай без слова «zapis».")


def zapusk():
    if not os.path.exists(FAIL):
        sys.exit("Точки ещё не записаны. Сначала запусти:  python klik_po_ekranu.py zapis")
    with open(FAIL, encoding="utf-8") as f:
        tochki = json.load(f)

    print("Начинаю через 3 секунды. Не трогай мышку!")
    print("Чтобы остановить — резко уведи мышку в левый верхний угол экрана.")
    time.sleep(3)

    nachalo = None
    for (nazvanie, tip, pauza), (x, y) in zip(SHAGI, tochki):
        print(f"-> {nazvanie}")
        if tip == "klik":
            pyautogui.click(x, y)
        elif tip == "nachalo_svaipa":
            nachalo = (x, y)
        elif tip == "konec_svaipa":
            pyautogui.moveTo(*nachalo)
            pyautogui.dragTo(x, y, duration=0.6, button="left")
        time.sleep(pauza)
    print("Готово ✅")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "zapis":
        zapis()
    else:
        zapusk()
