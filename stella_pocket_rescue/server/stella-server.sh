#!/bin/bash
# Stella Pocket: настройка вашего сервера, чтобы коробка открывалась из интернета по домену.
#
#   ДОМЕН_КОРОБКИ  -> nginx (HTTPS) -> 127.0.0.1:18080 -> обратный SSH-туннель -> коробка
#   ДОМЕН_САЙТА    -> nginx (HTTPS) -> статичная копия рекламного сайта (папка site/)
#
# Скрипт ничего не трогает в чужих настройках: пишет только свои файлы, перед перезагрузкой nginx
# проверяет конфиг (nginx -t), сертификат получает отдельно (certbot certonly --webroot).
# Запуск из папки проекта:  sudo bash server/stella-server.sh help
set -u

SELF="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")"
HERE="$(dirname "$SELF")"
CONF=/etc/stella-server.conf
TUNNEL_USER=stella-tunnel
TUNNEL_HOME=/var/lib/stella-tunnel
LIB=/usr/local/lib/stella-tunnel
CERT_NAME=stella-rescue
ACME_ROOT=/var/www/stella-acme
SITE_ROOT=/var/www/stella-site
BOX_ROOT=/var/www/stella-box
DOMAIN_RX='^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}[a-z0-9]$'
KEY_RX='^(ssh-ed25519|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|ssh-rsa) [A-Za-z0-9+/=]{40,800}( [^[:cntrl:]]{0,100})?$'

BOX="" PROMO="" BOX_KEY="" EMAIL="" HTTP_PORT=18080 SSH_FWD_PORT=18022 SSH_HOST="" SSH_PORT="" NO_TLS=0 DRY=0
NGINX_FILE="" NGINX_LINK=""

say() { printf '%s\n' "$*"; }
ok() { printf '  [ok] %s\n' "$*"; }
warn() { printf '  [!]  %s\n' "$*"; }
die() { printf '\nОШИБКА: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" > /dev/null 2>&1; }

usage() {
  cat <<'EOF'
stella-server.sh: доступ к коробке Stella Pocket через ваш сервер и домен.

Порядок:
  1) на коробке:  sudo stella remote key            (покажет ключ коробки)
  2) здесь:       sudo bash server/stella-server.sh install --box-domain box.example.kz \
                       --promo-domain example.kz --box-key 'КЛЮЧ_КОРОБКИ' [--email you@mail.kz]
  3) на коробке:  sudo stella remote pair 'STELLA-PAIR строка'   и   sudo stella remote on

Команды:
  check   --box-domain Д --promo-domain Д   только проверить сервер, ничего не менять
  install --box-domain Д --promo-domain Д [--box-key 'КЛЮЧ'] [--email E] [--http-port 18080]
          [--ssh-host ИМЯ] [--ssh-port ПОРТ]  (куда коробка подключается по SSH, если не box-domain:22)
          [--no-tls]   (без HTTPS, только для проверки) [--dry-run] (показать конфиг и выйти)
  key 'КЛЮЧ'      заменить ключ коробки (например, после переустановки коробки)
  promo           обновить рекламный сайт из папки site/ рядом со скриптом
  pair            снова напечатать строку STELLA-PAIR
  demo on|off     тестовая версия на сервере без коробки: учебные вызовы, ИИ по правилам
  demo status     адреса, PIN консоли и пароль настроек тестовой версии
  status          что настроено и на связи ли коробка
  uninstall       убрать все, что поставил этот скрипт (сертификат остается)
EOF
}

need_root() { [ "$(id -u)" = 0 ] || die "запустите через sudo"; }

load_conf() {
  [ -r "$CONF" ] || return 1
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in \#*|"") continue ;; esac
    key="${line%%=*}" value="${line#*=}"
    case "$key" in
      BOX|PROMO|HTTP_PORT|SSH_FWD_PORT|SSH_HOST|SSH_PORT|NO_TLS|EMAIL|NGINX_FILE|NGINX_LINK) printf -v "$key" '%s' "$value" ;;
    esac
  done < "$CONF"
}

save_conf() {
  umask 022
  cat > "$CONF" <<EOF
# Настройки stella-server.sh (не секрет)
BOX=$BOX
PROMO=$PROMO
HTTP_PORT=$HTTP_PORT
SSH_FWD_PORT=$SSH_FWD_PORT
SSH_HOST=$SSH_HOST
SSH_PORT=$SSH_PORT
NO_TLS=$NO_TLS
EMAIL=$EMAIL
NGINX_FILE=$NGINX_FILE
NGINX_LINK=$NGINX_LINK
EOF
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --box-domain) shift; BOX="${1:-}" ;;
      --promo-domain) shift; PROMO="${1:-}" ;;
      --box-key) shift; BOX_KEY="${1:-}" ;;
      --email) shift; EMAIL="${1:-}" ;;
      --http-port) shift; HTTP_PORT="${1:-}" ;;
      --ssh-host) shift; SSH_HOST="${1:-}" ;;
      --ssh-port) shift; SSH_PORT="${1:-}" ;;
      --no-tls) NO_TLS=1 ;;
      --dry-run) DRY=1 ;;
      *) die "непонятный параметр: $1 (см. help)" ;;
    esac
    shift
  done
  BOX=$(printf '%s' "$BOX" | tr '[:upper:]' '[:lower:]')
  PROMO=$(printf '%s' "$PROMO" | tr '[:upper:]' '[:lower:]')
  [[ "$BOX" =~ $DOMAIN_RX ]] || die "нужен --box-domain, например box.example.kz"
  if [ -n "$PROMO" ] && ! [[ "$PROMO" =~ $DOMAIN_RX ]]; then die "неверный --promo-domain"; fi
  [ "$BOX" != "$PROMO" ] || die "домен коробки и домен сайта должны быть разными"
  [[ "$HTTP_PORT" =~ ^[0-9]{4,5}$ ]] && [ "$HTTP_PORT" -ge 1024 ] && [ "$HTTP_PORT" -le 65535 ] || die "неверный --http-port"
  SSH_FWD_PORT=$((HTTP_PORT == 18022 ? 18023 : 18022))
  if [ -n "$EMAIL" ] && ! [[ "$EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then die "неверный --email"; fi
  if [ -n "$SSH_HOST" ] && ! [[ "$SSH_HOST" =~ ^[A-Za-z0-9.:-]+$ ]]; then die "неверный --ssh-host"; fi
  if [ -n "$SSH_PORT" ] && ! [[ "$SSH_PORT" =~ ^[0-9]{1,5}$ ]]; then die "неверный --ssh-port"; fi
  SSH_HOST="${SSH_HOST:-$BOX}"
}

check_key() {
  BOX_KEY=$(printf '%s' "$BOX_KEY" | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
  [[ "$BOX_KEY" =~ $KEY_RX ]] || die "ключ коробки не похож на открытый ключ SSH (его печатает: sudo stella remote key)"
}

# ---------------------------------------------------------------- проверки

claimed_by_others() {
  # Какие конфиги nginx, кроме наших, уже отвечают на этот домен
  local domain="$1"
  nginx -T 2>/dev/null | awk -v d="$domain" -v mine="$NGINX_FILE" '
    /^# configuration file / { file = $4; sub(/:$/, "", file); next }
    $1 == "server_name" {
      for (i = 2; i <= NF; i++) { n = $i; sub(/;$/, "", n); if (n == d && file != mine) print file }
    }' | sort -u
}

pick_nginx_file() {
  if [ -n "$NGINX_FILE" ]; then return; fi
  if [ -d /etc/nginx/sites-enabled ] && nginx -T 2>/dev/null | grep -q 'include /etc/nginx/sites-enabled/'; then
    NGINX_FILE=/etc/nginx/sites-available/stella-rescue.conf
    NGINX_LINK=/etc/nginx/sites-enabled/stella-rescue.conf
  else
    NGINX_FILE=/etc/nginx/conf.d/stella-rescue.conf
    NGINX_LINK=""
  fi
}

sshd_value() {
  local key="$1"
  sshd -T -C "user=$TUNNEL_USER,host=$BOX,addr=127.0.0.1" 2>/dev/null | awk -v k="$key" '$1 == k { $1 = ""; sub(/^ /, ""); print; exit }'
}

checks() {
  local errors=0 v ip ips owners
  say "Проверяю сервер"
  have nginx || { warn "nginx не установлен: sudo apt install nginx"; errors=$((errors + 1)); }
  if have nginx; then
    if nginx -t > /dev/null 2>&1; then ok "nginx работает, конфиг в порядке"; else warn "текущий конфиг nginx уже с ошибкой (nginx -t): сначала почините его"; errors=$((errors + 1)); fi
  fi
  if have docker && have ss && ss -ltnp 2>/dev/null | grep -E ':(80|443) ' | grep -q docker-proxy; then
    warn "порты 80/443 держит Docker: этот скрипт рассчитан на nginx прямо на сервере (см. README, раздел про Docker)"
    errors=$((errors + 1))
  fi
  pick_nginx_file
  for v in "$BOX" "$PROMO"; do
    [ -n "$v" ] || continue
    owners=$(claimed_by_others "$v")
    if [ -n "$owners" ]; then
      warn "домен $v уже настроен в: $(printf '%s' "$owners" | tr '\n' ' ')"
      warn "  уберите его оттуда или настройте вручную по README (раздел «домен уже настроен»)"
      errors=$((errors + 1))
    else
      ok "домен $v свободен в nginx"
    fi
  done
  ips=" $(hostname -I 2>/dev/null) "
  for v in "$BOX" "$PROMO"; do
    [ -n "$v" ] || continue
    ip=$(getent ahostsv4 "$v" 2>/dev/null | awk 'NR == 1 { print $1 }')
    if [ -z "$ip" ]; then warn "домен $v не находится в DNS: добавьте запись A с адресом этого сервера"
    elif [[ "$ips" == *" $ip "* ]]; then ok "DNS: $v указывает на этот сервер ($ip)"
    else warn "DNS: $v указывает на $ip, а у сервера адреса$ips(за NAT это нормально, иначе сертификат не выдадут)"
    fi
  done
  if have sshd; then
    v=$(ssh -V 2>&1 | sed -n 's/^OpenSSH_\([0-9]*\)\.\([0-9]*\).*/\1 \2/p')
    if [ -n "$v" ] && { [ "${v% *}" -gt 7 ] || { [ "${v% *}" = 7 ] && [ "${v#* }" -ge 8 ]; }; }; then ok "OpenSSH ${v/ /.}"
    else warn "нужен OpenSSH 7.8 или новее (permitlisten)"; errors=$((errors + 1)); fi
    case "$(sshd_value allowtcpforwarding)" in
      no|local) warn "в sshd запрещен проброс портов (AllowTcpForwarding). Разрешите хотя бы для пользователя $TUNNEL_USER, см. README"; errors=$((errors + 1)) ;;
      *) ok "sshd разрешает обратный проброс" ;;
    esac
    if [ "$(sshd_value disableforwarding)" = yes ]; then warn "в sshd включен DisableForwarding"; errors=$((errors + 1)); fi
    if sshd -T 2>/dev/null | grep -qE '^(allowusers|allowgroups) '; then
      warn "в sshd задан AllowUsers или AllowGroups: добавьте туда $TUNNEL_USER, иначе коробка не войдет"
    fi
  else
    warn "на сервере нет sshd"; errors=$((errors + 1))
  fi
  if [ "$NO_TLS" = 0 ] && ! have certbot; then warn "нет certbot: поставлю его (apt install certbot)"; fi
  return "$errors"
}

# ---------------------------------------------------------------- файлы

nginx_conf() {
  # mode: acme (только проверка домена для сертификата), tls (HTTPS), plain (без HTTPS, для проверки)
  local mode="$1" v6="" listen listen6 ssl="" proto=http root80
  if nginx -T 2>/dev/null | grep -qE '^[[:space:]]*listen[[:space:]]+\[::\]'; then v6=1; fi
  cat <<EOF
# Stella Pocket (stella-server.sh). Файл перезаписывается скриптом, правьте stella-server.sh.
limit_req_zone \$binary_remote_addr zone=stella_srv_chat:10m rate=1r/s;
limit_req_zone \$binary_remote_addr zone=stella_srv_box:10m rate=10r/s;
EOF
  if [ "$mode" != plain ]; then
    root80='return 404;'
    [ "$mode" = tls ] && root80='return 301 https://$host$request_uri;'
    cat <<EOF

server {
    listen 80;
${v6:+    listen [::]:80;
}    server_name $BOX${PROMO:+ $PROMO};
    location /.well-known/acme-challenge/ { root $ACME_ROOT; }
    location / { $root80 }
}
EOF
  fi
  [ "$mode" = acme ] && return 0
  if [ "$mode" = tls ]; then
    listen="listen 443 ssl http2;" listen6="listen [::]:443 ssl http2;" proto=https
    ssl="    ssl_certificate /etc/letsencrypt/live/$CERT_NAME/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$CERT_NAME/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;"
  else
    listen="listen 80;" listen6="listen [::]:80;"
    ssl="    location /.well-known/acme-challenge/ { root $ACME_ROOT; }"
  fi
  cat <<EOF

# Коробка через туннель. Журнал выключен: в адресах чата есть номер сессии.
server {
    $listen
${v6:+    $listen6
}    server_name $BOX;
$ssl

    access_log off;
    client_max_body_size 16k;
    limit_req_status 429;
    add_header X-Robots-Tag "noindex, nofollow" always;

    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-Proto $proto;
    proxy_set_header X-Stella-Via tunnel;
    proxy_connect_timeout 5s;
    proxy_read_timeout 130s;

    error_page 502 504 /stella-offline.html;
    location = /stella-offline.html { root $BOX_ROOT; internal; }

    location = /api/session { limit_req zone=stella_srv_chat burst=5 nodelay; proxy_pass http://127.0.0.1:$HTTP_PORT; }
    location = /api/chat { limit_req zone=stella_srv_chat burst=5 nodelay; proxy_pass http://127.0.0.1:$HTTP_PORT; }
    location / { limit_req zone=stella_srv_box burst=40 nodelay; proxy_pass http://127.0.0.1:$HTTP_PORT; }
}
EOF
  if [ -n "$PROMO" ]; then
    cat <<EOF

# Рекламный сайт
server {
    $listen
${v6:+    $listen6
}    server_name $PROMO;
$ssl

    root $SITE_ROOT;
    index index.html;
    location / { try_files \$uri \$uri/ =404; }
}
EOF
  fi
}

write_nginx() {
  local mode="$1" backup=""
  if [ -f "$NGINX_FILE" ]; then backup=$(mktemp) && cp -p "$NGINX_FILE" "$backup"; fi
  mkdir -p "$(dirname "$NGINX_FILE")"
  nginx_conf "$mode" > "$NGINX_FILE.new" && mv -f "$NGINX_FILE.new" "$NGINX_FILE"
  if [ -n "$NGINX_LINK" ]; then ln -sf "$NGINX_FILE" "$NGINX_LINK"; fi
  if nginx -t > /dev/null 2>&1; then
    systemctl reload nginx 2>/dev/null || nginx -s reload
    [ -n "$backup" ] && rm -f "$backup"
    return 0
  fi
  nginx -t 2>&1 | sed 's/^/    /'
  if [ -n "$backup" ]; then cp -p "$backup" "$NGINX_FILE"; rm -f "$backup"; else rm -f "$NGINX_FILE" "$NGINX_LINK"; fi
  die "nginx не принял конфиг, вернул как было"
}

deploy_promo() {
  local src="$HERE/../site"
  [ -n "$PROMO" ] || return 0
  if [ ! -f "$src/index.html" ]; then warn "нет папки site/ рядом со скриптом: рекламный сайт не обновлен"; return 0; fi
  mkdir -p "$SITE_ROOT.new"
  cp -a "$src/." "$SITE_ROOT.new/"
  rm -f "$SITE_ROOT.new/verify.html"
  rm -rf "$SITE_ROOT.old"
  [ -d "$SITE_ROOT" ] && mv "$SITE_ROOT" "$SITE_ROOT.old"
  mv "$SITE_ROOT.new" "$SITE_ROOT"
  rm -rf "$SITE_ROOT.old"
  chmod -R a+rX "$SITE_ROOT"
  ok "рекламный сайт скопирован в $SITE_ROOT"
}

ensure_user() {
  if ! id "$TUNNEL_USER" > /dev/null 2>&1; then
    useradd --system --create-home --home-dir "$TUNNEL_HOME" --shell /bin/sh "$TUNNEL_USER" || die "не удалось создать пользователя"
  fi
  usermod -p '*' "$TUNNEL_USER"
  chown root:"$TUNNEL_USER" "$TUNNEL_HOME"
  chmod 750 "$TUNNEL_HOME"
  install -d -o root -g "$TUNNEL_USER" -m 750 "$TUNNEL_HOME/.ssh" "$TUNNEL_HOME/certs"
  ok "пользователь $TUNNEL_USER (вход только по ключу коробки, без пароля и без оболочки)"
}

install_key() {
  local opts
  opts="restrict,port-forwarding,permitlisten=\"127.0.0.1:$HTTP_PORT\",permitlisten=\"127.0.0.1:$SSH_FWD_PORT\""
  opts="$opts,permitopen=\"127.0.0.1:9\",command=\"$LIB/cmd\""
  printf '%s %s\n' "$opts" "$BOX_KEY" > "$TUNNEL_HOME/.ssh/authorized_keys.new"
  chown root:"$TUNNEL_USER" "$TUNNEL_HOME/.ssh/authorized_keys.new"
  chmod 640 "$TUNNEL_HOME/.ssh/authorized_keys.new"
  mv -f "$TUNNEL_HOME/.ssh/authorized_keys.new" "$TUNNEL_HOME/.ssh/authorized_keys"
  ok "ключ коробки добавлен: она может только держать туннель на 127.0.0.1:$HTTP_PORT"
}

install_files() {
  install -d -m 755 "$LIB" "$ACME_ROOT" "$BOX_ROOT"
  install -m 755 "$HERE/stella-tunnel-cmd" "$LIB/cmd"
  install -m 755 "$HERE/certbot-deploy-hook" "$LIB/deploy-hook"
  install -m 644 "$HERE/offline.html" "$BOX_ROOT/stella-offline.html"
}

get_cert() {
  local -a mail=(--register-unsafely-without-email)
  if ! have certbot; then
    have apt-get || die "нет certbot и apt-get: поставьте certbot вручную"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q certbot > /dev/null || die "не удалось поставить certbot"
  fi
  [ -n "$EMAIL" ] && mail=(-m "$EMAIL")
  say "Получаю сертификат Let's Encrypt для $BOX${PROMO:+ и $PROMO}"
  if ! certbot certonly --webroot -w "$ACME_ROOT" --cert-name "$CERT_NAME" -d "$BOX" ${PROMO:+-d "$PROMO"} \
      --non-interactive --agree-tos "${mail[@]}" --keep-until-expiring --expand --deploy-hook "$LIB/deploy-hook"; then
    die "сертификат не выдан. Чаще всего домен еще не указывает на этот сервер (DNS) или закрыт порт 80"
  fi
  RENEWED_LINEAGE="/etc/letsencrypt/live/$CERT_NAME" "$LIB/deploy-hook" || warn "не удалось скопировать сертификат для коробки"
  ok "сертификат получен и будет продлеваться сам (certbot renew)"
}

host_keys() {
  local f
  for f in /etc/ssh/ssh_host_ed25519_key.pub /etc/ssh/ssh_host_ecdsa_key.pub; do
    [ -r "$f" ] && awk '{ print $1 " " $2 }' "$f"
  done
}

pair_line() {
  local port keys json
  port="$SSH_PORT"
  [ -n "$port" ] || port=$(sshd -T 2>/dev/null | awk '$1 == "port" { print $2; exit }')
  port="${port:-22}"
  keys=$(host_keys)
  [ -n "$keys" ] || die "не нашел ключи сервера в /etc/ssh"
  json=$(SSH_HOST="$SSH_HOST" PORT="$port" HTTP="$HTTP_PORT" SSHF="$SSH_FWD_PORT" BOX="$BOX" PROMO="$PROMO" KEYS="$keys" \
    TUNNEL_USER="$TUNNEL_USER" python3 -I -c '
import json, os
print(json.dumps({"v": 1, "host": os.environ["SSH_HOST"], "port": int(os.environ["PORT"]), "user": os.environ["TUNNEL_USER"],
                  "http": int(os.environ["HTTP"]), "ssh": int(os.environ["SSHF"]), "box": os.environ["BOX"],
                  "promo": os.environ["PROMO"], "hostkeys": [k for k in os.environ["KEYS"].splitlines() if k.strip()]},
                 separators=(",", ":")))') || die "нужен python3"
  printf 'STELLA-PAIR %s\n' "$(printf '%s' "$json" | base64 -w0)"
}

print_pair() {
  say ""
  say "Готово. На коробке выполните (одной строкой, в кавычках):"
  say ""
  say "  sudo stella remote pair '$(pair_line)'"
  say "  sudo stella remote on"
  say ""
  say "Потом откройте https://$BOX/admin . Пока коробка не в сети, там будет страница «коробка не в сети»."
  [ -n "$PROMO" ] && say "Рекламный сайт: https://$PROMO/"
}

# ---------------------------------------------------------------- команды

cmd_install() {
  local tls=1
  parse_args "$@"
  [ -n "$BOX_KEY" ] && check_key
  [ "$NO_TLS" = 1 ] && tls=0
  if [ "$DRY" = 1 ]; then
    pick_nginx_file
    say "# $NGINX_FILE"
    if [ "$tls" = 1 ]; then nginx_conf tls; else nginx_conf plain; fi
    return 0
  fi
  need_root
  checks || die "исправьте замечания выше и запустите снова (ничего не изменено)"
  install_files
  if [ -n "$BOX_KEY" ]; then
    ensure_user
    install_key
  fi
  deploy_promo
  save_conf
  if [ "$tls" = 1 ]; then
    write_nginx acme
    ok "nginx: временный конфиг для проверки домена"
    get_cert
    write_nginx tls
    ok "nginx: HTTPS для $BOX${PROMO:+ и $PROMO}"
  else
    write_nginx plain
    warn "без HTTPS: коробка на http://$BOX/ (вход администратора из интернета работать не будет)"
  fi
  if [ -n "$BOX_KEY" ]; then
    print_pair
  else
    say ""
    say "Домены настроены. Тестовая версия без коробки:  sudo bash server/stella-server.sh demo on"
    say "Настоящую коробку потом подключите так: на коробке sudo stella remote key, здесь"
    say "  sudo bash server/stella-server.sh key 'КЛЮЧ_КОРОБКИ'  и  sudo bash server/stella-server.sh pair"
  fi
}

cmd_key() {
  need_root
  load_conf || die "сначала: stella-server.sh install"
  BOX_KEY="${1:-}"
  check_key
  install_files
  ensure_user
  install_key
  say "Ключ заменен. На коробке: sudo stella remote on"
}

cmd_status() {
  load_conf || { say "Не настроено. См.: sudo bash $0 help"; return 1; }
  say "Домен коробки: $BOX   домен сайта: ${PROMO:-нет}   порт туннеля: 127.0.0.1:$HTTP_PORT"
  case "$(port_owner)" in
    sshd*) ok "коробка на связи (туннель открыт)" ;;
    python*|uvicorn*) ok "работает тестовая версия (sudo bash $0 demo status)" ;;
    *) warn "коробка сейчас не подключена" ;;
  esac
  if [ -r "$TUNNEL_HOME/certs/fullchain.pem" ] && have openssl; then
    ok "сертификат для коробки до $(openssl x509 -noout -enddate -in "$TUNNEL_HOME/certs/fullchain.pem" | cut -d= -f2)"
  fi
}

cmd_uninstall() {
  need_root
  load_conf || true
  demo_remove > /dev/null 2>&1 || true
  [ -n "$NGINX_LINK" ] && rm -f "$NGINX_LINK"
  [ -n "$NGINX_FILE" ] && rm -f "$NGINX_FILE"
  if have nginx && nginx -t > /dev/null 2>&1; then systemctl reload nginx 2>/dev/null || nginx -s reload; fi
  pkill -u "$TUNNEL_USER" 2>/dev/null || true
  id "$TUNNEL_USER" > /dev/null 2>&1 && userdel -r "$TUNNEL_USER" 2>/dev/null
  rm -rf "$LIB" "$ACME_ROOT" "$BOX_ROOT" "$SITE_ROOT" "$TUNNEL_HOME" "$CONF"
  say "Убрано. Сертификат остался: удалить можно командой certbot delete --cert-name $CERT_NAME"
}

# ---------------------------------------------------------------- тестовая версия на сервере

DEMO_USER=stella-demo
DEMO_DIR=/opt/stella-demo
DEMO_STATE=/var/lib/stella-demo
DEMO_ENV=/etc/stella-demo.env
DEMO_PASS=/etc/stella-demo.pass
DEMO_UNIT=/etc/systemd/system/stella-demo.service
DEMO_LAT=43.2389
DEMO_LON=76.8897

demo_python_ok() {
  have python3 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

port_owner() {
  # Кто слушает 127.0.0.1:ПОРТ: stella-demo, туннель коробки (sshd) или никто
  have ss || return 0
  ss -ltnpH 2>/dev/null | awk -v p="127.0.0.1:$HTTP_PORT" '$4 == p { print $6 }' | sed -n 's/.*(("\([^"]*\)".*/\1/p' | head -n 1
}

demo_env() {
  local pin pass hash secret
  if [ -s "$DEMO_ENV" ] && [ -s "$DEMO_PASS" ]; then
    sed -i "s/^STELLA_BOX_DOMAIN=.*/STELLA_BOX_DOMAIN=$BOX/" "$DEMO_ENV"
    return 0
  fi
  pin=$(python3 -I -c 'import secrets; print("%06d" % (100000 + secrets.randbelow(900000)))')
  pass=$(python3 -I -c 'import secrets; a="abcdefghjkmnpqrstuvwxyz23456789"; print("-".join("".join(secrets.choice(a) for _ in range(4)) for _ in range(4)))')
  hash=$(printf '%s\n' "$pass" | python3 -I -c '
import hashlib, secrets, sys
p = sys.stdin.readline().rstrip("\n").encode("utf-8")
s = secrets.token_bytes(16)
print("pbkdf2:200000:%s:%s" % (s.hex(), hashlib.pbkdf2_hmac("sha256", p, s, 200000).hex()))')
  secret=$(python3 -I -c 'import secrets; print(secrets.token_hex(32))')
  [ -n "$pin" ] && [ -n "$hash" ] && [ -n "$secret" ] || die "не удалось создать пароль тестовой версии"
  umask 027
  cat > "$DEMO_ENV" <<EOF
# Тестовая версия Stella Pocket на сервере (stella-server.sh demo). Не секрет только STELLA_BOX_DOMAIN.
STELLA_DEMO=1
STELLA_BOX_DOMAIN=$BOX
STELLA_DB=$DEMO_STATE/stella.db
STELLA_STATE_DIR=$DEMO_STATE
STELLA_MODE_FILE=$DEMO_STATE/mode.json
STELLA_HW_STATE=$DEMO_STATE/hw.json
STELLA_SITE_DIR=$DEMO_DIR/site
STELLA_RESCUER_PIN=$pin
STELLA_ADMIN_HASH=$hash
STELLA_SESSION_SECRET=$secret
STELLA_AI_MODE=offline
STELLA_LLM_ENABLED=0
STELLA_HUB_LAT=$DEMO_LAT
STELLA_HUB_LON=$DEMO_LON
STELLA_HUB_MODE=demo
STELLA_ADMIN_HELPER=/nonexistent
STELLA_TUNNEL_ENV=/nonexistent
STELLA_REMOTE_CHAT=1
EOF
  chown root:"$DEMO_USER" "$DEMO_ENV"
  chmod 640 "$DEMO_ENV"
  (umask 077 && printf '%s\n' "$pass" > "$DEMO_PASS")
  umask 022
}

demo_unit() {
  cat > "$DEMO_UNIT" <<EOF
[Unit]
Description=Stella Pocket: тестовая версия на сервере (учебные вызовы, без коробки)
After=network.target

[Service]
User=$DEMO_USER
Group=$DEMO_USER
WorkingDirectory=$DEMO_DIR
EnvironmentFile=$DEMO_ENV
# каждый запуск с чистой базой: учебные вызовы появляются заново, чужие сообщения исчезают
ExecStartPre=/bin/sh -c 'rm -f $DEMO_STATE/stella.db $DEMO_STATE/stella.db-wal $DEMO_STATE/stella.db-shm $DEMO_STATE/mode.json $DEMO_STATE/demo.json'
ExecStart=$DEMO_DIR/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $HTTP_PORT --workers 1
Restart=always
RestartSec=3
RuntimeMaxSec=1d
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$DEMO_STATE
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LockPersonality=yes

[Install]
WantedBy=multi-user.target
EOF
}

demo_links() {
  say "  Чат:            https://$BOX/"
  say "  Консоль:        https://$BOX/rescuer    PIN: $(sed -n 's/^STELLA_RESCUER_PIN=//p' "$DEMO_ENV" 2>/dev/null)"
  say "  Настройки:      https://$BOX/admin      пароль: $(head -n 1 "$DEMO_PASS" 2>/dev/null)"
  say "  Проверка узла:  https://$BOX/verify"
  [ -n "$PROMO" ] && say "  Рекламный сайт: https://$PROMO/"
}

demo_on() {
  local src="$HERE/.." owner code
  need_root
  load_conf || die "сначала настройте домены: sudo bash server/stella-server.sh install --box-domain ДОМЕН --promo-domain ДОМЕН"
  [ -f "$src/app/main.py" ] && [ -f "$src/requirements.txt" ] || die "рядом со скриптом нет папок app/ и requirements.txt: запускайте из папки проекта"
  owner=$(port_owner)
  case "$owner" in
    ""|python*|uvicorn*) ;;
    sshd*) die "к адресу $BOX сейчас подключена настоящая коробка (туннель). Тестовая версия не нужна, она заняла бы ее место" ;;
    *) die "порт 127.0.0.1:$HTTP_PORT занят программой $owner" ;;
  esac
  if ! demo_python_ok; then
    die "нужен Python 3.10 или новее (Ubuntu 22.04+, Debian 12+). Сейчас: $(python3 --version 2>&1)"
  fi
  if ! python3 -c 'import ensurepip, venv' 2>/dev/null; then
    have apt-get || die "нет модуля venv: поставьте python3-venv"
    say "Ставлю python3-venv"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv > /dev/null || die "не удалось поставить python3-venv"
  fi
  if ! id "$DEMO_USER" > /dev/null 2>&1; then
    useradd --system --user-group --home-dir "$DEMO_STATE" --no-create-home --shell /usr/sbin/nologin "$DEMO_USER" \
      || die "не удалось создать пользователя $DEMO_USER"
  fi
  install -d -o "$DEMO_USER" -g "$DEMO_USER" -m 750 "$DEMO_STATE"
  say "Копирую программу в $DEMO_DIR"
  rm -rf "$DEMO_DIR.new"
  mkdir -p "$DEMO_DIR.new"
  cp -a "$src/app" "$src/requirements.txt" "$DEMO_DIR.new/"
  [ -d "$src/site" ] && cp -a "$src/site" "$DEMO_DIR.new/"
  rm -f "$DEMO_DIR.new/site/verify.html"
  find "$DEMO_DIR.new" -name __pycache__ -prune -exec rm -rf {} +
  if [ -x "$DEMO_DIR/venv/bin/python" ]; then mv "$DEMO_DIR/venv" "$DEMO_DIR.new/venv"; fi
  rm -rf "$DEMO_DIR"
  mv "$DEMO_DIR.new" "$DEMO_DIR"
  if [ ! -x "$DEMO_DIR/venv/bin/python" ]; then
    python3 -m venv "$DEMO_DIR/venv" || die "не удалось создать окружение Python"
  fi
  say "Ставлю библиотеки Python (1-2 минуты)"
  "$DEMO_DIR/venv/bin/pip" install -q --disable-pip-version-check -r "$DEMO_DIR/requirements.txt" \
    || die "не удалось поставить библиотеки (нужен интернет у сервера)"
  "$DEMO_DIR/venv/bin/python" -m compileall -q "$DEMO_DIR/app" > /dev/null 2>&1 || true
  chown -R root:root "$DEMO_DIR"
  chmod -R a+rX,go-w "$DEMO_DIR"
  demo_env
  demo_unit
  systemctl daemon-reload
  systemctl enable --now stella-demo > /dev/null 2>&1 || systemctl restart stella-demo
  systemctl restart stella-demo
  for _ in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 3 -H "Host: $BOX" "http://127.0.0.1:$HTTP_PORT/api/health" 2>/dev/null) || code=000
    [ "$code" = 200 ] && break
    sleep 1
  done
  [ "$code" = 200 ] || die "тестовая версия не запустилась: journalctl -u stella-demo -n 50"
  ok "тестовая версия работает (4 учебных вызова, ИИ отвечает по правилам, каждые сутки начинается заново)"
  say ""
  demo_links
  say ""
  say "Когда подключите настоящую коробку, сначала выключите тест: sudo bash server/stella-server.sh demo off"
}

demo_off() {
  need_root
  if [ -f "$DEMO_UNIT" ]; then
    systemctl disable --now stella-demo > /dev/null 2>&1 || true
  fi
  ok "тестовая версия выключена. Пока коробка не подключена, домен показывает страницу «коробка не в сети»"
}

demo_remove() {
  demo_off
  rm -f "$DEMO_UNIT"
  systemctl daemon-reload 2>/dev/null || true
  if id "$DEMO_USER" > /dev/null 2>&1; then
    pkill -u "$DEMO_USER" 2>/dev/null && sleep 2
    userdel "$DEMO_USER" 2>/dev/null
  fi
  rm -rf "$DEMO_DIR" "$DEMO_STATE" "$DEMO_ENV" "$DEMO_PASS"
}

cmd_demo() {
  case "${1:-status}" in
    on|install|update) demo_on ;;
    off|stop) demo_off ;;
    remove) need_root; demo_remove; ok "тестовая версия удалена" ;;
    status)
      load_conf || die "сначала install"
      if systemctl is-active --quiet stella-demo 2>/dev/null; then
        ok "тестовая версия работает"
        demo_links
      else
        say "Тестовая версия выключена. Включить: sudo bash server/stella-server.sh demo on"
      fi
      ;;
    *) die "есть: demo on, demo off, demo status, demo remove" ;;
  esac
}

main() {
  local cmd="${1:-help}"
  [ $# -gt 0 ] && shift
  case "$cmd" in
    help|-h|--help) usage ;;
    check) parse_args "$@"; need_root; if checks; then say "Все в порядке, можно install."; else say "Есть замечания, см. выше."; return 1; fi ;;
    install) cmd_install "$@" ;;
    key) cmd_key "$@" ;;
    promo) need_root; load_conf || die "сначала install"; deploy_promo ;;
    pair) need_root; load_conf || die "сначала install"; print_pair ;;
    status) cmd_status ;;
    uninstall) cmd_uninstall ;;
    demo) cmd_demo "$@" ;;
    *) usage; return 1 ;;
  esac
}

if [ "${STELLA_SERVER_LIB:-0}" != 1 ]; then
  main "$@"
  exit $?
fi
