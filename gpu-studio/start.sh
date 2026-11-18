#!/usr/bin/env bash
cd "$(dirname "$0")"
command -v node >/dev/null || { echo "Установите Node.js 20+ (https://nodejs.org)"; exit 1; }
[ -d node_modules ] || npm install --omit=dev
exec node launch.js
