# STELLS — прошивка для платы

Этот архив скачан из приложения STELLS. В нём программа для платы, которая даёт
компьютеру удалённо управлять платой, моделью и машинным зрением.

## Linux-платы (Raspberry Pi, Banana Pi, ODROID, NanoPi, Orange Pi, Jetson, Radxa…)

1. Скопируйте папку `stells-firmware` на плату (флешка, `scp`, общий диск):
   ```
   scp -r stells-firmware pi@<IP-платы>:~/
   ```
2. На плате выполните:
   ```
   cd ~/stells-firmware/agent
   sudo bash install.sh
   ```
3. Скрипт установит зависимости, создаст службу `stells-agent` (стартует при каждом
   включении платы) и покажет IP-адрес.
4. В приложении STELLS откройте «Плата» → «Найти в сети» (или введите IP вручную).

Модели: положите файл `.onnx` (YOLOv5/v8) и `.txt` с названиями классов в `/opt/stells/models/`
либо загрузите модель из приложения.

Порты: 8765 — управление (WebSocket), 8766 — видео (`/stream`, `/snapshot`, `/detections`),
48765/UDP — автопоиск.

## Микроконтроллеры (Arduino, ESP32, Pico…)

1. Откройте `arduino/stells_arduino/stells_arduino.ino` в Arduino IDE.
2. Выберите свою плату и порт → «Загрузить».
3. Подключите плату к компьютеру по USB → в приложении «Плата» → «USB / Serial».

## Дроны

Полётный контроллер (ArduPilot / PX4) подключается к плате по UART:
TX контроллера → RX платы (GPIO15), RX контроллера → TX платы (GPIO14), GND → GND.
На Raspberry Pi включите UART: `sudo raspi-config` → Interface → Serial (login shell — НЕТ,
hardware — ДА). Порт по умолчанию — `/dev/serial0`, 57600 бод (меняется в `stells-config.json`).

## Свой коннектор

В папке `connectors` — примеры на Python и JavaScript. В приложении есть встроенный
редактор с терминалом: коннектор можно написать на любом языке.

---
Если что-то не получается — обратитесь в службу поддержки:
WhatsApp **+7 702 538 97 49** · Telegram **@Stells_help** · Создатель **@l3xn0**
