#!/usr/bin/env bash
# Stella Cloud — one-command deployment on a Linux VPS (Ubuntu/Debian).
#   git clone -b claude/elegant-bell-3a87rj https://github.com/a1x10/project3.git && cd project3/cloud && sudo bash deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\033[1;35m▸\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

if ! command -v docker >/dev/null 2>&1; then
  say "Устанавливаю Docker…"
  [ "$(id -u)" = 0 ] || die "Запустите с sudo, чтобы установить Docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || die "Нужен Docker Compose v2 (docker compose)"

rand() { openssl rand -hex "$1" 2>/dev/null || head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
ask() { # ask VAR "question" [default]
  local cur="${!1:-}" def="${3:-}" ans
  [ -n "$cur" ] && return
  read -r -p "$2${def:+ [$def]}: " ans </dev/tty || true
  printf -v "$1" '%s' "${ans:-$def}"
}

if [ -f .env ]; then
  say "Найден .env — использую его (удалите файл, чтобы настроить заново)"
else
  TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"; ADMIN_TELEGRAM_IDS="${ADMIN_TELEGRAM_IDS:-}"; DOMAIN="${DOMAIN:-}"
  echo "Создайте бота у @BotFather (/newbot) и скопируйте токен."
  ask TELEGRAM_BOT_TOKEN "Токен Telegram-бота"
  echo "Ваш числовой Telegram ID можно узнать у @userinfobot."
  ask ADMIN_TELEGRAM_IDS "Telegram ID администратора"
  ask DOMAIN "Домен сайта (A-запись на этот сервер) или пусто — работать по IP" ""
  [ -n "$TELEGRAM_BOT_TOKEN" ] || die "Без токена бота регистрация не будет работать"
  if [ -n "$DOMAIN" ]; then PUBLIC_URL="https://$DOMAIN"; else
    IP="$(curl -fsS4 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
    DOMAIN=":80"; PUBLIC_URL="http://$IP"
  fi
  umask 077
  cat > .env <<ENV
DOMAIN=$DOMAIN
PUBLIC_URL=$PUBLIC_URL
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
ADMIN_TELEGRAM_IDS=$ADMIN_TELEGRAM_IDS
ROUTER_ADMIN_EMAIL=admin@stella.local
ROUTER_ADMIN_PASSWORD=$(rand 16)
FREELLMAPI_ENCRYPTION_KEY=$(rand 32)
SYSTEM_PROMPT=
DEFAULT_MODEL=auto:smart
UPSTREAM_BASE_URL=
UPSTREAM_API_KEY=
ENV
  say "Создан .env (секреты сгенерированы)"
fi

say "Собираю и запускаю контейнеры…"
docker compose up -d --build

say "Жду запуска…"
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1:8080/api/health >/dev/null || { docker compose logs --tail 50; die "Stella Cloud не ответила"; }

. ./.env
echo
say "Готово!"
echo "  Сайт:        $PUBLIC_URL"
echo "  API:         $PUBLIC_URL/v1"
echo "  Бот:         напишите своему боту /start — вы станете администратором"
echo
echo "  Панель FreeLLMAPI (ключи провайдеров и модели) — только через SSH-туннель:"
echo "    ssh -L 3001:127.0.0.1:3001 root@<IP-сервера>   → откройте http://localhost:3001"
echo "    логин: $ROUTER_ADMIN_EMAIL   пароль: $ROUTER_ADMIN_PASSWORD"
echo
echo "  Логи: docker compose logs -f stella-cloud    Обновить: git pull && docker compose up -d --build"
