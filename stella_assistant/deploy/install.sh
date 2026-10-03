#!/usr/bin/env bash
# Установка Стеллы на Raspberry Pi 4 (Raspberry Pi OS Bookworm, 64-бит).
#   bash deploy/install.sh            — всё поставить и включить автозапуск
#   bash deploy/install.sh --no-autostart
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
AUTOSTART=1
[[ "${1:-}" == "--no-autostart" ]] && AUTOSTART=0

echo "==> Системные пакеты"
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev python3-pip libportaudio2 portaudio19-dev \
  libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 libsdl2-ttf-2.0-0 \
  mpv ffmpeg espeak-ng alsa-utils v4l-utils openssl curl unzip libopenblas0
# необязательное: ТВ на Android (adb), SIP-звонки (baresip), мультирум (snapclient), камера (opencv)
sudo apt-get install -y adb baresip snapclient python3-opencv 2>/dev/null || true

echo "==> Python-окружение"
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt

echo "==> Модели речи"
mkdir -p models/piper
if [ ! -d models/vosk-model-small-ru-0.22 ]; then
  curl -L -o /tmp/vosk.zip https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
  unzip -q /tmp/vosk.zip -d models && rm /tmp/vosk.zip
fi
VOICE=ru_RU-irina-medium
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium
[ -f models/piper/$VOICE.onnx ] || curl -L -o models/piper/$VOICE.onnx "$BASE/$VOICE.onnx"
[ -f models/piper/$VOICE.onnx.json ] || curl -L -o models/piper/$VOICE.onnx.json "$BASE/$VOICE.onnx.json"

echo "==> Настройки"
[ -f config.yaml ] || cp config.example.yaml config.yaml
[ -f scenarios.yaml ] || cp scenarios.example.yaml scenarios.yaml
mkdir -p data ~/Music ~/Audiobooks
sudo usermod -aG audio,video,input,render,plugdev "$USER" || true

if [ "$AUTOSTART" = 1 ]; then
  if [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ] || [ -d /etc/xdg/labwc ] || [ -d /etc/xdg/autostart ]; then
    echo "==> Автозапуск в графической сессии"
    mkdir -p ~/.config/autostart
    sed "s|@DIR@|$DIR|g" deploy/stella.desktop > ~/.config/autostart/stella.desktop
  else
    echo "==> Автозапуск как пользовательская служба systemd (без рабочего стола)"
    mkdir -p ~/.config/systemd/user
    sed "s|@DIR@|$DIR|g" deploy/stella.service > ~/.config/systemd/user/stella.service
    sudo loginctl enable-linger "$USER"
    systemctl --user daemon-reload
    systemctl --user enable --now stella.service
  fi
fi

cat <<MSG

Готово! Дальше:
  1) Откройте $DIR/config.yaml и впишите город, ключи (YandexGPT, Яндекс Музыка, умный дом, Telegram) — по желанию.
  2) Проверка: $DIR/.venv/bin/python $DIR/main.py --windowed
     Без экрана/микрофона:  .venv/bin/python main.py --text --no-face
  3) Веб-панель: http://$(hostname -I | awk '{print $1}'):8765
После перезагрузки Стелла запустится сама.
MSG
