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

# "https://Example.com/" -> "example.com"
clean_domain() { printf '%s' "$1" | sed -E 's#^[a-zA-Z]+://##; s#/.*$##; s#[[:space:]]##g' | tr 'A-Z' 'a-z'; }
set_env() { # set_env KEY VALUE  (in .env)
  if grep -q "^$1=" .env; then sed -i "s#^$1=.*#$1=$2#" .env; else echo "$1=$2" >> .env; fi
}
port_busy() { ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]$1\$"; }
free_port() { local p=$1; while port_busy "$p"; do p=$((p+1)); done; echo "$p"; }

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
  DOMAIN="$(clean_domain "$DOMAIN")"
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

# fix a domain entered with https:// or a trailing slash in an existing .env
CUR_DOMAIN="$(grep -E '^DOMAIN=' .env | cut -d= -f2-)"
if [ -n "$CUR_DOMAIN" ] && [ "$CUR_DOMAIN" != ":80" ]; then
  FIXED="$(clean_domain "$CUR_DOMAIN")"
  if [ "$FIXED" != "$CUR_DOMAIN" ] || ! grep -q "^PUBLIC_URL=https://$FIXED\$" .env; then
    set_env DOMAIN "$FIXED"; set_env PUBLIC_URL "https://$FIXED"
    say "Домен исправлен: $FIXED"
  fi
fi

# free our own ports first (re-run), then pick free local ports for the API and the router dashboard
docker compose down --remove-orphans >/dev/null 2>&1 || true
for p in 80 443; do
  if port_busy "$p"; then
    echo; ss -ltnp 2>/dev/null | grep -E "[:.]$p " || true
    die "Порт $p занят другой программой (см. выше). Остановите её (например: sudo systemctl stop nginx apache2 caddy) или освободите порт, и запустите deploy.sh снова."
  fi
done
STELLA_HOST_PORT="$(grep -E '^STELLA_HOST_PORT=' .env | cut -d= -f2- || true)"
STELLA_HOST_PORT="$(free_port "${STELLA_HOST_PORT:-8080}")"
ROUTER_HOST_PORT="$(grep -E '^ROUTER_HOST_PORT=' .env | cut -d= -f2- || true)"
ROUTER_HOST_PORT="$(free_port "${ROUTER_HOST_PORT:-3001}")"
set_env STELLA_HOST_PORT "$STELLA_HOST_PORT"
set_env ROUTER_HOST_PORT "$ROUTER_HOST_PORT"
[ "$STELLA_HOST_PORT" = 8080 ] || say "Порт 8080 занят — Stella Cloud будет на 127.0.0.1:$STELLA_HOST_PORT"
[ "$ROUTER_HOST_PORT" = 3001 ] || say "Порт 3001 занят — панель FreeLLMAPI будет на 127.0.0.1:$ROUTER_HOST_PORT"

say "Собираю и запускаю контейнеры…"
docker compose up -d --build

say "Жду запуска…"
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:$STELLA_HOST_PORT/api/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1:$STELLA_HOST_PORT/api/health >/dev/null || { docker compose logs --tail 50; die "Stella Cloud не ответила"; }

. ./.env
echo
say "Готово!"
echo "  Сайт:        $PUBLIC_URL"
echo "  API:         $PUBLIC_URL/v1"
echo "  Бот:         напишите своему боту /start — вы станете администратором"
echo
echo "  Панель FreeLLMAPI (ключи провайдеров и модели) — только через SSH-туннель:"
echo "    ssh -L 3001:127.0.0.1:$ROUTER_HOST_PORT $(logname 2>/dev/null || echo root)@<IP-сервера>   → откройте http://localhost:3001"
echo "    логин: $ROUTER_ADMIN_EMAIL   пароль: $ROUTER_ADMIN_PASSWORD"
echo
echo "  Логи: docker compose logs -f stella-cloud    Обновить: git pull && docker compose up -d --build"
