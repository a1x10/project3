#!/usr/bin/env bash
# Stella Cloud installer for Ubuntu / Debian servers.
#   curl -fsSL https://raw.githubusercontent.com/a1x10/project3/claude/happy-ritchie-vx32ws/stella-cloud/install.sh | sudo bash
# Optional:  DOMAIN=stella.example.com  (otherwise <your-ip>.sslip.io is used, HTTPS via Let's Encrypt)
#            DUCKDNS=myname   (free name myname.duckdns.org; the token is asked for, hidden)
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

say "Docker: отдельный контейнер для каждого аккаунта"
if ! command -v docker >/dev/null; then $APT install -y -q docker.io && systemctl enable --now docker; fi
if docker info >/dev/null 2>&1; then
  docker build -q -t stella-agent:latest "$APP/docker" && echo "Образ stella-agent готов" \
    || echo "ВНИМАНИЕ: образ не собрался — агенты будут работать без Docker (отдельные Linux-пользователи)"
else
  echo "ВНИМАНИЕ: Docker не запущен — агенты будут работать без Docker (отдельные Linux-пользователи)"
fi

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
# auto = Docker container per account when available
STELLA_SANDBOX=auto
# seconds to wait for a vanished PC before its running task moves to the server
STELLA_FAILOVER_SEC=45
EOF
  chmod 600 "$ENVF"
fi
INVITE=$(grep '^STELLA_INVITE=' "$ENVF" | cut -d= -f2)

# --- free local port for Stella (another program may already use 8787) ---
systemctl stop stella-cloud 2>/dev/null || true
port_busy() { ss -ltnH "( sport = :$1 )" 2>/dev/null | grep -q .; }
PORT=$(grep '^PORT=' "$ENVF" | cut -d= -f2); PORT=${PORT:-8787}
if port_busy "$PORT"; then
  echo "Порт $PORT занят другой программой — ищу свободный…"
  for p in $(seq 18787 18887); do if ! port_busy "$p"; then PORT=$p; break; fi; done
  sed -i "s/^PORT=.*/PORT=$PORT/" "$ENVF"
  echo "Stella будет работать на 127.0.0.1:$PORT"
fi

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
systemctl enable stella-cloud >/dev/null
systemctl restart stella-cloud
for i in $(seq 1 20); do curl -fsS "http://127.0.0.1:$PORT/api/info" >/dev/null 2>&1 && break; sleep 1; done
if curl -fsS "http://127.0.0.1:$PORT/api/info" >/dev/null 2>&1; then echo "Stella запущена на 127.0.0.1:$PORT"
else echo "ВНИМАНИЕ: Stella не отвечает. Логи: journalctl -u stella-cloud -n 50 --no-pager"; fi

# ---------- domain: DuckDNS / own domain / <ip>.sslip.io ----------
DDF=/etc/stella-duckdns.env
if [ -n "${DUCKDNS:-}" ]; then
  DUCKDNS="${DUCKDNS%.duckdns.org}"
  if [ -z "${DUCKDNS_TOKEN:-}" ] && [ -f "$DDF" ] && grep -q "^DUCKDNS=$DUCKDNS$" "$DDF"; then DUCKDNS_TOKEN=$(grep '^DUCKDNS_TOKEN=' "$DDF" | cut -d= -f2); fi
  if [ -z "${DUCKDNS_TOKEN:-}" ]; then read -rsp "DuckDNS token (с duckdns.org, ввод скрыт): " DUCKDNS_TOKEN < /dev/tty; echo; fi
  printf 'DUCKDNS=%s\nDUCKDNS_TOKEN=%s\n' "$DUCKDNS" "$DUCKDNS_TOKEN" > "$DDF"; chmod 600 "$DDF"
  R=$(curl -fsS --max-time 15 "https://www.duckdns.org/update?domains=$DUCKDNS&token=$DUCKDNS_TOKEN&ip=" || true)
  if [ "$R" = "OK" ]; then echo "DuckDNS: $DUCKDNS.duckdns.org → IP этого сервера"; else echo "ВНИМАНИЕ: DuckDNS ответил «$R» — проверьте имя и токен"; fi
  cat > /etc/cron.d/stella-duckdns <<'CRON'
*/5 * * * * root . /etc/stella-duckdns.env && curl -fsS --max-time 15 "https://www.duckdns.org/update?domains=$DUCKDNS&token=$DUCKDNS_TOKEN&ip=" >/dev/null 2>&1
CRON
  DOMAIN="$DUCKDNS.duckdns.org"
elif [ -z "${DOMAIN:-}" ] && [ -f "$DDF" ]; then
  DOMAIN="$(grep '^DUCKDNS=' "$DDF" | cut -d= -f2).duckdns.org"
fi
if [ -z "${DOMAIN:-}" ]; then
  IP=$(curl -fsS4 --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')
  DOMAIN="${IP//./-}.sslip.io"
fi
# agents inside containers reach Stella (WhatsApp tools) through the public HTTPS address
if grep -q '^STELLA_PUBLIC_URL=' "$ENVF"; then sed -i "s|^STELLA_PUBLIC_URL=.*|STELLA_PUBLIC_URL=https://$DOMAIN|" "$ENVF"; else echo "STELLA_PUBLIC_URL=https://$DOMAIN" >> "$ENVF"; fi
systemctl restart stella-cloud

WEB=$(ss -ltnpH '( sport = :80 or sport = :443 )' 2>/dev/null || true)
if echo "$WEB" | grep -q nginx; then
  # ---------- nginx already serves 80/443: add a separate site for Stella + certbot ----------
  say "HTTPS через ваш nginx ($DOMAIN)"
  if systemctl is-enabled caddy >/dev/null 2>&1; then systemctl disable --now caddy >/dev/null 2>&1 || true; fi
  if [ -d /etc/nginx/sites-available ]; then CONF=/etc/nginx/sites-available/stella-cloud.conf; else CONF=/etc/nginx/conf.d/stella-cloud.conf; fi
  cat > "$CONF" <<EOF
# Stella Cloud — only for $DOMAIN, other sites are not touched
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    client_max_body_size 20m;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
EOF
  if [ -d /etc/nginx/sites-enabled ]; then ln -sf "$CONF" /etc/nginx/sites-enabled/stella-cloud.conf; fi
  nginx -t && systemctl reload nginx
  command -v certbot >/dev/null || $APT install -y -q certbot python3-certbot-nginx
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect --keep-until-expiring \
    || echo "ВНИМАНИЕ: сертификат не выдан. Проверьте, что порт 80 открыт снаружи, и запустите установку ещё раз."
  nginx -t && systemctl reload nginx
else
  # ---------- Caddy (automatic HTTPS) ----------
  say "HTTPS (Caddy)"
  if [ -n "$WEB" ] && ! echo "$WEB" | grep -q caddy; then
    echo "ВНИМАНИЕ: порты 80/443 заняты другой программой:"; echo "$WEB"
    echo "Настройте её проксировать $DOMAIN на 127.0.0.1:$PORT (с поддержкой WebSocket) или освободите порты."
  fi
  if ! command -v caddy >/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    $APT update -q && $APT install -y -q caddy
  fi
  cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN {
  encode gzip
  reverse_proxy 127.0.0.1:$PORT
}
EOF
  systemctl enable caddy >/dev/null 2>&1 || true
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
fi
if command -v ufw >/dev/null && ufw status | grep -q active; then ufw allow 80/tcp; ufw allow 443/tcp; fi

sleep 2
say "Done!"
echo "  Открой на телефоне:   https://$DOMAIN"
echo "  Код приглашения:      $INVITE   (зарегистрируйтесь ПЕРВЫМ — первый аккаунт = администратор)"
echo "  Друзей/клиентов:      Stella на телефоне → Ещё → «Друзья и клиенты» → создать приглашение"
echo "  Общий ключ Gemini:    по желанию — STELLA_GEMINI_API_KEY в /etc/stella-cloud.env, затем systemctl restart stella-cloud"
echo "  Логи:                 journalctl -u stella-cloud -f"
echo "  Обновить:             запусти эту же команду ещё раз"
