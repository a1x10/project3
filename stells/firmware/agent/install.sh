#!/usr/bin/env bash
# Установка STELLS Agent на плату (Raspberry Pi OS, Ubuntu, Debian, Armbian, DietPi…)
# Запуск на плате:  cd stells-firmware/agent && sudo bash install.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$DIR")"
TARGET=/opt/stells
USER_NAME="${SUDO_USER:-$(whoami)}"

echo "== STELLS: установка агента в $TARGET"
if command -v apt-get >/dev/null; then
  apt-get update
  apt-get install -y python3 python3-venv python3-pip python3-opencv libatlas-base-dev || \
  apt-get install -y python3 python3-venv python3-pip
fi

mkdir -p "$TARGET/models"
cp -r "$DIR"/* "$TARGET/"
cp "$ROOT/stells-config.json" "$TARGET/stells-config.json" 2>/dev/null || true

python3 -m venv --system-site-packages "$TARGET/venv"
"$TARGET/venv/bin/pip" install --upgrade pip
"$TARGET/venv/bin/pip" install -r "$TARGET/requirements.txt" || echo "!! Часть пакетов не установилась — агент запустится с ограниченными функциями"

# Доступ к камере, GPIO и UART
for g in video gpio dialout i2c spi; do getent group $g >/dev/null && usermod -aG $g "$USER_NAME" || true; done

cat > /etc/systemd/system/stells-agent.service <<EOF
[Unit]
Description=STELLS Agent (управление платой и машинное зрение)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$TARGET
ExecStart=$TARGET/venv/bin/python $TARGET/stells_agent.py --config $TARGET/stells-config.json
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now stells-agent
IP=$(hostname -I | awk '{print $1}')
echo
echo "== Готово! Агент запущен и будет стартовать при включении платы."
echo "   Адрес для приложения STELLS: $IP  (порт 8765)"
echo "   Видео: http://$IP:8766/stream"
echo "   Логи:  journalctl -u stells-agent -f"
echo "   Если что-то не получается — служба поддержки: WhatsApp +7 702 538 97 49, Telegram @Stells_help"
