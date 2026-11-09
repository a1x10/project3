"""
podklyuchis.py — нажимает ТОЛЬКО кнопку «Подключиться» (или телевизор в списке)
в окне телефона на экране компьютера.

Один раз запомни место кнопки:
    py podklyuchis.py zapis
Потом каждый раз:
    py podklyuchis.py
"""

import json
import os
import sys
import time

try:
    import pyautogui
except ImportError:
    sys.exit("Нет библиотеки pyautogui. Установи командой:  py -m pip install pyautogui")

FAIL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knopka.json")

if len(sys.argv) > 1 and sys.argv[1] == "zapis":
    input("Наведи мышку на кнопку «Подключиться» и нажми Enter… ")
    x, y = pyautogui.position()
    with open(FAIL, "w", encoding="utf-8") as f:
        json.dump([x, y], f)
    print(f"Запомнил: x={x}, y={y}. Теперь запускай:  py podklyuchis.py")
else:
    if not os.path.exists(FAIL):
        sys.exit("Сначала запомни кнопку:  py podklyuchis.py zapis")
    with open(FAIL, encoding="utf-8") as f:
        x, y = json.load(f)
    print("Нажимаю через 2 секунды…")
    time.sleep(2)
    pyautogui.click(x, y)
    print("Нажал ✅")
