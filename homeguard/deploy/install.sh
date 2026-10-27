#!/usr/bin/env bash
# Установка HomeGuard как системной службы (Debian / Ubuntu / Raspberry Pi OS).
#   sudo ./deploy/install.sh
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Запусти через sudo"; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST=/opt/homeguard

echo "→ Пакеты"
apt-get update -qq
apt-get install -y -qq python3 python3-venv iptables wireguard-tools openvpn clamav >/dev/null

echo "→ Копирую в $DST"
mkdir -p "$DST"
rsync -a --delete --exclude data/ --exclude .venv/ --exclude __pycache__/ "$SRC"/ "$DST"/
mkdir -p "$DST/data"
cp -rn "$SRC/data/blocklists" "$DST/data/" 2>/dev/null || true

echo "→ Python-окружение"
python3 -m venv "$DST/.venv"
"$DST/.venv/bin/pip" install -q -r "$DST/requirements.txt"

if [[ ! -f /etc/homeguard.env ]]; then
  LAN_IP=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
  cat > /etc/homeguard.env <<ENV
# Настройки HomeGuard. После правки: sudo systemctl restart homeguard
HG_DNS_PORT=53
HG_WEB_PORT=80
HG_BLOCK_IP=${LAN_IP}
HG_UPSTREAM=1.1.1.1
# Токен бота можно ввести в панели при первом запуске, либо здесь:
# HG_TG_TOKEN=
# Ключи антивируса (можно и в панели):
# HG_GSB_KEY=
# HG_VT_KEY=
ENV
  chmod 600 /etc/homeguard.env
  echo "→ Создан /etc/homeguard.env (IP этой машины: ${LAN_IP})"
fi

# systemd-resolved занимает 53 порт — отключаем его заглушку
if systemctl is-active -q systemd-resolved; then
  mkdir -p /etc/systemd/resolved.conf.d
  printf '[Resolve]\nDNSStubListener=no\n' > /etc/systemd/resolved.conf.d/homeguard.conf
  systemctl restart systemd-resolved
fi

echo "→ Обновляю базы (может занять минуту)"
"$DST/.venv/bin/python" "$DST/scripts/update_blocklists.py" || echo "  базы не скачались — попробую позже по таймеру"
systemctl stop clamav-freshclam 2>/dev/null; freshclam -q || true; systemctl start clamav-freshclam 2>/dev/null || true

echo "→ Службы"
cp "$DST"/deploy/homeguard*.service "$DST"/deploy/homeguard*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now homeguard.service homeguard-blocklists.timer

source /etc/homeguard.env
echo
echo "✅ Готово. Панель: http://${HG_BLOCK_IP}/"
echo "   Логи:    journalctl -u homeguard -f"
echo "   Дальше: в роутере укажи DNS = ${HG_BLOCK_IP}"
