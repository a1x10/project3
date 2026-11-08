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
  install --box-domain Д --promo-domain Д --box-key 'КЛЮЧ' [--email E] [--http-port 18080]
          [--ssh-host ИМЯ] [--ssh-port ПОРТ]  (куда коробка подключается по SSH, если не box-domain:22)
          [--no-tls]   (без HTTPS, только для проверки) [--dry-run] (показать конфиг и выйти)
  key 'КЛЮЧ'      заменить ключ коробки (например, после переустановки коробки)
  promo           обновить рекламный сайт из папки site/ рядом со скриптом
  pair            снова напечатать строку STELLA-PAIR
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
  check_key
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
  ensure_user
  install_key
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
  print_pair
}

cmd_key() {
  need_root
  load_conf || die "сначала: stella-server.sh install"
  BOX_KEY="${1:-}"
  check_key
  install_key
  say "Ключ заменен. На коробке: sudo stella remote on"
}

cmd_status() {
  load_conf || { say "Не настроено. См.: sudo bash $0 help"; return 1; }
  say "Домен коробки: $BOX   домен сайта: ${PROMO:-нет}   порт туннеля: 127.0.0.1:$HTTP_PORT"
  if have ss && ss -ltn 2>/dev/null | grep -q "127.0.0.1:$HTTP_PORT "; then ok "коробка на связи (туннель открыт)"
  else warn "коробка сейчас не подключена"; fi
  if [ -r "$TUNNEL_HOME/certs/fullchain.pem" ] && have openssl; then
    ok "сертификат для коробки до $(openssl x509 -noout -enddate -in "$TUNNEL_HOME/certs/fullchain.pem" | cut -d= -f2)"
  fi
}

cmd_uninstall() {
  need_root
  load_conf || true
  [ -n "$NGINX_LINK" ] && rm -f "$NGINX_LINK"
  [ -n "$NGINX_FILE" ] && rm -f "$NGINX_FILE"
  if have nginx && nginx -t > /dev/null 2>&1; then systemctl reload nginx 2>/dev/null || nginx -s reload; fi
  pkill -u "$TUNNEL_USER" 2>/dev/null || true
  id "$TUNNEL_USER" > /dev/null 2>&1 && userdel -r "$TUNNEL_USER" 2>/dev/null
  rm -rf "$LIB" "$ACME_ROOT" "$BOX_ROOT" "$SITE_ROOT" "$TUNNEL_HOME" "$CONF"
  say "Убрано. Сертификат остался: удалить можно командой certbot delete --cert-name $CERT_NAME"
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
    *) usage; return 1 ;;
  esac
}

if [ "${STELLA_SERVER_LIB:-0}" != 1 ]; then
  main "$@"
  exit $?
fi
