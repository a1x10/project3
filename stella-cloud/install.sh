#!/usr/bin/env bash
# Stella Cloud installer for Ubuntu / Debian servers.
#   curl -fsSL https://raw.githubusercontent.com/a1x10/project3/claude/happy-ritchie-vx32ws/stella-cloud/install.sh | sudo bash
# Optional:  DOMAIN=stella.example.com  (otherwise <your-ip>.sslip.io is used, HTTPS via Let's Encrypt)
set -euo pipefail

REPO="${STELLA_REPO:-https://github.com/a1x10/project3.git}"
BRANCH="${STELLA_BRANCH:-claude/happy-ritchie-vx32ws}"
APP=/opt/stella-cloud
DATA=/var/lib/stella
HOMES=/home/stella
PORT=8787

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
[ "$(id -u)" = 0 ] || { echo "Run as root: curl ... | sudo bash"; exit 1; }
command -v apt-get >/dev/null || { echo "This installer supports Ubuntu/Debian (apt)."; exit 1; }

say "System packages"
export DEBIAN_FRONTEND=noninteractive
APT="apt-get -o DPkg::Lock::Timeout=600"
$APT update -q
$APT install -y -q curl ca-certificates git build-essential python3 debian-keyring debian-archive-keyring apt-transport-https gnupg

if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  say "Node.js 22"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  $APT install -y -q nodejs
fi

say "Stella Cloud code -> $APP"
TMP=$(mktemp -d)
git clone -q --depth 1 --branch "$BRANCH" --filter=blob:none --sparse "$REPO" "$TMP/src"
git -C "$TMP/src" sparse-checkout set stella-cloud
mkdir -p "$APP"
cp -a "$TMP/src/stella-cloud/." "$APP/"
rm -rf "$TMP"
cd "$APP"
npm ci --omit=dev --no-audit --no-fund 2>/dev/null || npm install --omit=dev --no-audit --no-fund
chmod -R a+rX "$APP"

say "Antigravity CLI (agy)"
if [ ! -x /usr/local/bin/agy ]; then
  curl -fsSL https://antigravity.google/cli/install.sh | bash || true
  for p in /root/.local/bin/agy /root/.antigravity/bin/agy; do
    if [ -x "$p" ]; then install -m 755 "$(readlink -f "$p")" /usr/local/bin/agy && break; fi
  done
fi
if [ -x /usr/local/bin/agy ]; then /usr/local/bin/agy --version || true
else echo "agy will be installed into each account's home on registration."; fi

say "Settings"
mkdir -p "$DATA" "$HOMES"; chmod 700 "$DATA"; chmod 711 "$HOMES"
ENVF=/etc/stella-cloud.env
if [ ! -f "$ENVF" ]; then
  INVITE=$(head -c 9 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 10)
  cat > "$ENVF" <<EOF
PORT=$PORT
HOST=127.0.0.1
STELLA_DATA=$DATA
STELLA_HOMES=$HOMES
# invite | open | closed
STELLA_SIGNUP=invite
# master invite code (the first account registered becomes the administrator)
STELLA_INVITE=$INVITE
# optional: one shared Gemini API key for all accounts (friends don't need a Google sign-in; usage is billed to you)
# STELLA_GEMINI_API_KEY=
# limits per account
STELLA_MAX_RUNS=2
STELLA_LIMIT_MEM=2G
STELLA_LIMIT_CPU=100%
EOF
  chmod 600 "$ENVF"
fi
INVITE=$(grep '^STELLA_INVITE=' "$ENVF" | cut -d= -f2)

say "systemd service"
cat > /etc/systemd/system/stella-cloud.service <<EOF
[Unit]
Description=Stella Cloud (agents, phone app, WhatsApp)
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=$ENVF
WorkingDirectory=$APP
ExecStart=$(command -v node) $APP/server.js
Restart=always
RestartSec=3
# runs as root: it creates a separate Linux user for every account and starts agents as that user

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now stella-cloud
systemctl restart stella-cloud

say "HTTPS (Caddy)"
if [ -z "${DOMAIN:-}" ]; then
  IP=$(curl -fsS4 --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')
  DOMAIN="${IP//./-}.sslip.io"
fi
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  $APT update -q && $APT install -y -q caddy
fi
# ports 80/443 must be free for Caddy (Let's Encrypt)
BUSY=$(ss -ltnpH '( sport = :80 or sport = :443 )' 2>/dev/null | grep -v caddy || true)
if [ -n "$BUSY" ]; then
  echo "ВНИМАНИЕ: порты 80/443 уже заняты другой программой:"; echo "$BUSY"
  echo "Caddy не сможет выдать HTTPS. Освободите порты (или настройте свой веб-сервер проксировать на 127.0.0.1:$PORT) и запустите установку ещё раз."
fi
cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN {
  encode gzip
  reverse_proxy 127.0.0.1:$PORT
}
EOF
systemctl reload caddy || systemctl restart caddy
if command -v ufw >/dev/null && ufw status | grep -q active; then ufw allow 80/tcp; ufw allow 443/tcp; fi

sleep 2
say "Done!"
echo "  Открой на телефоне:   https://$DOMAIN"
echo "  Код приглашения:      $INVITE   (зарегистрируйтесь ПЕРВЫМ — первый аккаунт = администратор)"
echo "  Друзей/клиентов:      Stella на телефоне → Ещё → «Друзья и клиенты» → создать приглашение"
echo "  Общий ключ Gemini:    по желанию — STELLA_GEMINI_API_KEY в /etc/stella-cloud.env, затем systemctl restart stella-cloud"
echo "  Логи:                 journalctl -u stella-cloud -f"
echo "  Обновить:             запусти эту же команду ещё раз"
