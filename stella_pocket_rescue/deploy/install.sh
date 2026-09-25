#!/bin/bash
# Установка Stella Pocket Rescue на Orange Pi 4 LTS (Armbian / Orange Pi OS Debian/Ubuntu, arm64).
# Запускать ОДИН раз, пока плата подключена к интернету по Ethernet:
#   sudo ./deploy/install.sh            # модель 1.5B (рекомендуется для 4 ГБ)
#   sudo MODEL=0.5b ./deploy/install.sh # быстрее, но хуже по-русски
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "Запустите через sudo"; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST=/opt/stella
MODEL="${MODEL:-1.5b}"

case "$MODEL" in
  0.5b) MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf" ;;
  1.5b) MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf" ;;
  *) echo "MODEL должен быть 0.5b или 1.5b"; exit 1 ;;
esac

echo "==> Пакеты"
apt-get update
# Не даём пакетам запускать службы во время установки (dnsmasq может упасть,
# если порт 53 занят, и тогда весь скрипт остановится)
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d; chmod +x /usr/sbin/policy-rc.d
trap 'rm -f /usr/sbin/policy-rc.d' EXIT
apt-get install -y hostapd dnsmasq nginx iptables iw python3-venv python3-pip \
    git cmake build-essential curl util-linux

echo "==> Пользователь и файлы"
id stella >/dev/null 2>&1 || useradd --system --home "$DST" --shell /usr/sbin/nologin stella
mkdir -p "$DST" /var/lib/stella /etc/stella "$DST/models"
cp -r "$SRC/app" "$SRC/deploy" "$SRC/requirements.txt" "$DST/"
chown -R stella:stella /var/lib/stella

if [ ! -f /etc/stella/stella.env ]; then
  PIN=$(shuf -i 100000-999999 -n 1)
  sed "s/^STELLA_RESCUER_PIN=.*/STELLA_RESCUER_PIN=$PIN/" "$SRC/deploy/stella.env.example" > /etc/stella/stella.env
  chmod 640 /etc/stella/stella.env && chgrp stella /etc/stella/stella.env
  echo "PIN спасателей: $PIN  (хранится в /etc/stella/stella.env)"
fi

echo "==> Python-окружение"
# Проекту нужен Python 3.10+. На старых образах (Ubuntu 20.04 от Orange Pi — Python 3.8)
# ставим отдельный Python 3.11 через uv, системный Python не трогаем.
if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  rm -rf "$DST/venv"; python3 -m venv "$DST/venv"
  "$DST/venv/bin/pip" install --upgrade pip
  "$DST/venv/bin/pip" install -r "$DST/requirements.txt"
else
  echo "    системный Python $(python3 -V 2>&1 | cut -d' ' -f2) слишком старый — ставлю Python 3.11 через uv"
  export UV_INSTALL_DIR=/opt/stella/uv UV_PYTHON_INSTALL_DIR=/opt/stella/python
  [ -x /opt/stella/uv/uv ] || curl -LsSf https://astral.sh/uv/install.sh | env INSTALLER_NO_MODIFY_PATH=1 sh
  rm -rf "$DST/venv"
  /opt/stella/uv/uv venv --python 3.11 "$DST/venv"
  /opt/stella/uv/uv pip install --python "$DST/venv/bin/python" -r "$DST/requirements.txt"
fi
"$DST/venv/bin/python" -c "import fastapi, uvicorn, httpx; print('    Python OK:', __import__('sys').version.split()[0])"

echo "==> llama.cpp (сборка ~15–25 минут на RK3399)"
LLM_OK=1
if [ ! -x "$DST/llama.cpp/build/bin/llama-server" ]; then
  # На Ubuntu 20.04 штатный g++ 9 слишком старый — берём g++-10, если есть
  CCX=""; if g++ -dumpversion | awk -F. '{exit !($1<10)}'; then apt-get install -y g++-10 gcc-10 && CCX="-DCMAKE_C_COMPILER=gcc-10 -DCMAKE_CXX_COMPILER=g++-10"; fi
  [ -d "$DST/llama.cpp" ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp "$DST/llama.cpp"
  # Сборка нейросети не должна ронять всю установку: без неё работает резервный диспетчер
  if ! { cmake -S "$DST/llama.cpp" -B "$DST/llama.cpp/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF $CCX \
        && cmake --build "$DST/llama.cpp/build" --target llama-server llama-bench -j "${JOBS:-3}"; }; then
    LLM_OK=0
    echo "!!! llama.cpp не собралась. Сайт и сортировка будут работать, отвечать будет резервный диспетчер."
    echo "!!! Пришлите последние строки ошибки сборки — поправим отдельно."
  fi
fi

echo "==> Модель ($MODEL)"
if [ ! -f "$DST/models/model.gguf" ]; then
  curl -L --fail -o "$DST/models/model.gguf.part" "$MODEL_URL"
  mv "$DST/models/model.gguf.part" "$DST/models/model.gguf"
fi
chown -R stella:stella "$DST"

echo "==> Сеть: wlan0 превращается в точку доступа"
if systemctl is-active --quiet NetworkManager; then
  mkdir -p /etc/NetworkManager/conf.d
  printf '[keyfile]\nunmanaged-devices=interface-name:wlan0\n' > /etc/NetworkManager/conf.d/stella-unmanaged.conf
  systemctl reload NetworkManager || true
fi
install -m 644 "$SRC/deploy/hostapd.conf" /etc/hostapd/hostapd.conf
[ -f /etc/default/hostapd ] && sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
install -m 644 "$SRC/deploy/dnsmasq-stella.conf" /etc/dnsmasq.d/stella.conf
# Не регистрировать dnsmasq как DNS самой платы, иначе apt и git перестанут работать
if [ -f /etc/default/dnsmasq ]; then
  grep -q '^DNSMASQ_EXCEPT=' /etc/default/dnsmasq && sed -i 's/^DNSMASQ_EXCEPT=.*/DNSMASQ_EXCEPT="lo"/' /etc/default/dnsmasq \
    || echo 'DNSMASQ_EXCEPT="lo"' >> /etc/default/dnsmasq
fi
install -m 644 "$SRC/deploy/nginx-stella.conf" /etc/nginx/sites-available/stella
ln -sf /etc/nginx/sites-available/stella /etc/nginx/sites-enabled/stella
rm -f /etc/nginx/sites-enabled/default
nginx -t

echo "==> Службы"
install -m 644 "$SRC"/deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl unmask hostapd
systemctl enable stella-net hostapd dnsmasq nginx stella-app
[ -x "$DST/llama.cpp/build/bin/llama-server" ] && systemctl enable stella-llm || echo "    stella-llm не включена (нет llama-server)"

cat <<MSG

Готово. Перезагрузите плату: sudo reboot
После загрузки появится открытая сеть "SOS-STELLA-RESCUE".
  Пострадавшие: подключаются к сети — чат открывается сам (или http://10.42.0.1/)
  Спасатели:    http://10.42.0.1/rescuer  (PIN в /etc/stella/stella.env)
Проверка скорости модели:  $DST/llama.cpp/build/bin/llama-bench -m $DST/models/model.gguf -t 2
MSG
