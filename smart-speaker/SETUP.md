# Полная установка: от прошивки до запуска

## 1. Прошивка Orange Pi 4 LTS
Понадобятся: microSD от 16 ГБ, картридер, компьютер.
1. Скачайте образ **Armbian** для Orange Pi 4 LTS (armbian.com), лучше Debian Bookworm minimal/CLI.
2. Запишите образ на карту через **balenaEtcher**.
3. Подключите плату Ethernet-кабелем к роутеру (Wi-Fi настроим позже). Питание 5V 3A.
4. Через 1-2 минуты найдите IP платы в списке клиентов роутера.

## 2. Подключение с телефона через Termux
```bash
pkg update && pkg install openssh
ssh root@IP_ПЛАТЫ      # пароль по умолчанию: 1234
```
Armbian попросит сменить пароль и создать обычного пользователя. Дальше: `ssh user@IP_ПЛАТЫ`.

## 3. Подключение к Wi-Fi
```bash
sudo nmcli device wifi list
sudo nmcli device wifi connect "ИМЯ_СЕТИ" password "ПАРОЛЬ"
ip a
```
Или интерактивно: `sudo armbian-config` -> Network -> Wireless.

## 4. Установка проекта
```bash
sudo apt update && sudo apt install -y git python3-venv python3-dev portaudio19-dev libasound2-dev pulseaudio pulseaudio-module-bluetooth bluez
git clone <URL_РЕПОЗИТОРИЯ>
cd project3/smart-speaker
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env      # вставьте API Key и Agent ID
```

## 5. Микрофон DJI (USB-приёмник)
1. Включите передатчик, вставьте приёмник в USB платы.
2. `arecord -l` — должна появиться карта DJI.
3. Тест: `arecord -D plughw:1,0 -f S16_LE -r 16000 -c 1 -d 5 t.wav && aplay t.wav` (цифры карты из `arecord -l`).
4. `python speaker.py --list-devices` — найдите индекс DJI, впишите `INPUT_DEVICE_INDEX` в `.env`.

Микрофон DJI, работающий только по Bluetooth напрямую с телефоном, к Orange Pi обычно не подключается; используйте USB-приёмник.

## 6. Bluetooth-колонка
```bash
pulseaudio --start
bluetoothctl
  power on
  agent on
  default-agent
  scan on            # колонка в режиме сопряжения, ждём её MAC
  pair AA:BB:CC:DD:EE:FF
  trust AA:BB:CC:DD:EE:FF
  connect AA:BB:CC:DD:EE:FF
  exit
pactl list short sinks
pactl set-default-sink bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink
paplay /usr/share/sounds/alsa/Front_Center.wav
```
`trust` нужен для автоподключения после перезагрузки. Микрофон по USB + колонка по Bluetooth: так звук не уходит в плохой профиль HFP. В `.env` для `OUTPUT_DEVICE_INDEX` выберите устройство `pulse` или `default` из `--list-devices`.

## 7. Запуск
```bash
cd ~/project3/smart-speaker && . .venv/bin/activate
python speaker.py
```

Автозапуск: `~/.config/systemd/user/speaker.service`
```ini
[Unit]
Description=Smart speaker
After=network-online.target sound.target

[Service]
ExecStart=%h/project3/smart-speaker/.venv/bin/python %h/project3/smart-speaker/speaker.py
WorkingDirectory=%h/project3/smart-speaker
Restart=always

[Install]
WantedBy=default.target
```
```bash
systemctl --user daemon-reload
systemctl --user enable --now speaker
sudo loginctl enable-linger $USER
```
