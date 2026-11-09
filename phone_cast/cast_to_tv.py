"""
cast_to_tv.py — автоматически подключает экран Android-телефона к телевизору.

Что делает (через ADB):
  1. Нажимает кнопку «Домой».
  2. Опускает шторку (быстрые настройки).
  3. Находит плитку «Трансляция» / «Cast» / «Smart View» и нажимает её.
  4. Ждёт, пока в списке появится телевизор, и нажимает на него.
  5. Если телефон спросит «Начать трансляцию?» — подтверждает.

Запуск:
    python cast_to_tv.py                    # ищет телевизор по слову "TV"
    python cast_to_tv.py --tv "Xiaomi TV"   # указать имя телевизора
    python cast_to_tv.py --serial 192.168.1.50:5555   # если устройств несколько / по Wi-Fi

Нужно: установленный ADB (platform-tools) и включённая отладка по USB на телефоне.
"""

import argparse
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

# Как может называться плитка трансляции на разных телефонах / языках
CAST_TILE_NAMES = [
    "Трансляция", "Трансляция экрана", "Дублирование экрана", "Передать экран",
    "Беспроводной дисплей", "Smart View", "Screen Cast", "Cast", "Screen mirroring",
    "Wireless display", "Mirroring", "Screencast",
]

# Кнопки подтверждения в диалогах
CONFIRM_NAMES = [
    "Начать", "Начать сейчас", "Разрешить", "ОК", "OK", "Подключить",
    "Start now", "Start", "Allow", "Connect",
]

ADB = "adb"
SERIAL = None


def adb(*args, capture=True):
    cmd = [ADB] + (["-s", SERIAL] if SERIAL else []) + list(args)
    res = subprocess.run(cmd, capture_output=capture, text=True, encoding="utf-8", errors="ignore")
    return res.stdout if capture else ""


def shell(*args):
    return adb("shell", *args)


def log(msg):
    print(f"[cast] {msg}", flush=True)


def check_device():
    try:
        out = adb("devices")
    except FileNotFoundError:
        sys.exit("ADB не найден. Скачай platform-tools и добавь папку в PATH (см. README).")
    devices = [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("device")]
    if not devices:
        sys.exit("Телефон не найден. Подключи кабель, включи «Отладку по USB» и разреши доступ на экране телефона.")
    if len(devices) > 1 and not SERIAL:
        sys.exit(f"Подключено несколько устройств: {devices}. Укажи нужное через --serial")
    log(f"Телефон найден: {SERIAL or devices[0]}")


def dump_ui():
    """Возвращает список элементов экрана: (текст, x, y, clickable)."""
    shell("uiautomator", "dump", "/sdcard/cast_ui.xml")
    xml = adb("exec-out", "cat", "/sdcard/cast_ui.xml")
    start = xml.find("<?xml")
    if start < 0:
        return []
    try:
        root = ET.fromstring(xml[start:])
    except ET.ParseError:
        return []
    nodes = []
    for n in root.iter("node"):
        label = (n.get("text") or "").strip() or (n.get("content-desc") or "").strip()
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds", ""))
        if not label or not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        nodes.append((label, (x1 + x2) // 2, (y1 + y2) // 2))
    return nodes


def find(nodes, names, exact=False):
    names_l = [s.lower() for s in names]
    # сначала точное совпадение, потом «содержит»
    for label, x, y in nodes:
        if label.lower() in names_l:
            return label, x, y
    if exact:
        return None
    for label, x, y in nodes:
        low = label.lower()
        if any(n in low for n in names_l):
            return label, x, y
    return None


def tap(x, y):
    shell("input", "tap", str(x), str(y))


def screen_size():
    m = re.search(r"(\d+)x(\d+)", shell("wm", "size"))
    return (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)


def open_cast_menu():
    log("Нажимаю «Домой»")
    shell("input", "keyevent", "KEYCODE_HOME")
    time.sleep(1)

    log("Опускаю шторку")
    shell("cmd", "statusbar", "expand-settings")
    time.sleep(1.5)

    w, h = screen_size()
    for page in range(4):  # плитка может быть на другой странице быстрых настроек
        hit = find(dump_ui(), CAST_TILE_NAMES)
        if hit:
            log(f"Нажимаю плитку «{hit[0]}»")
            tap(hit[1], hit[2])
            return True
        log("Плитка не видна, листаю шторку…")
        if page == 0:
            # на некоторых прошивках первая команда открывает только уведомления
            shell("input", "swipe", str(w // 2), str(h // 10), str(w // 2), str(h * 7 // 10), "300")
        else:
            shell("input", "swipe", str(w * 4 // 5), str(h // 4), str(w // 5), str(h // 4), "300")
        time.sleep(1)

    log("Плитку не нашёл — открываю меню трансляции через настройки")
    shell("cmd", "statusbar", "collapse")
    shell("am", "start", "-a", "android.settings.CAST_SETTINGS")
    return True


def connect_to_tv(tv_name, timeout):
    log(f"Ищу телевизор «{tv_name}» (до {timeout} c)…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        nodes = dump_ui()
        hit = find(nodes, [tv_name])
        if hit:
            log(f"Подключаюсь к «{hit[0]}»")
            tap(hit[1], hit[2])
            time.sleep(2)
            confirm = find(dump_ui(), CONFIRM_NAMES, exact=True)
            if confirm:
                log(f"Подтверждаю: «{confirm[0]}»")
                tap(confirm[1], confirm[2])
            return True
        time.sleep(1.5)
    return False


def main():
    global SERIAL, ADB
    p = argparse.ArgumentParser(description="Подключить телефон к телевизору одной командой")
    p.add_argument("--tv", default="TV", help="имя телевизора или его часть (по умолчанию 'TV')")
    p.add_argument("--serial", help="серийник телефона или IP:порт (если устройств несколько)")
    p.add_argument("--adb", default="adb", help="путь к adb.exe, если его нет в PATH")
    p.add_argument("--timeout", type=int, default=25, help="сколько секунд ждать телевизор")
    a = p.parse_args()
    SERIAL, ADB = a.serial, a.adb

    check_device()
    shell("input", "keyevent", "KEYCODE_WAKEUP")
    open_cast_menu()
    time.sleep(2)
    if connect_to_tv(a.tv, a.timeout):
        log("Готово ✅")
    else:
        names = [n[0] for n in dump_ui()]
        log("Телевизор не найден ❌. Что видно на экране: " + ", ".join(names[:30]))
        log("Проверь, что ТВ включён и в той же Wi-Fi сети, или укажи точное имя через --tv")
        sys.exit(1)


if __name__ == "__main__":
    main()
