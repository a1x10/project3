#!/usr/bin/env bash
cd "$(dirname "$0")"
if ! command -v node >/dev/null 2>&1; then
  echo "[!] Не найден Node.js. Установите LTS-версию с https://nodejs.org и запустите снова."
  exit 1
fi
if [ ! -d node_modules ]; then
  echo "Первый запуск: устанавливаю зависимости (1-3 минуты)..."
  npm install || { echo "[!] Ошибка установки"; exit 1; }
fi
if [ "$(uname)" = "Linux" ] && ! command -v xdotool >/dev/null 2>&1; then
  echo "Подсказка: для управления мышью и клавиатурой установите xdotool и wmctrl: sudo apt install xdotool wmctrl"
fi
npm start
