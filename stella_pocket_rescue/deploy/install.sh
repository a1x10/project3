#!/bin/bash

SELF="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")"
SRC="$(cd "$(dirname "$SELF")/.." 2>/dev/null && pwd)"
DST=/opt/stella
ETC_DIR=/etc/stella
ENV_FILE="$ETC_DIR/stella.env"
STATE_DIR=/var/lib/stella
LOG=/var/log/stella-install.log
LOG_MAX=5242880
LAST="$STATE_DIR/install.last"
LOCK=/run/stella-install.lock
BG_UNIT=stella-install
PY="$DST/venv/bin/python"
UV="$DST/uv/uv"
LLAMA_DIR="$DST/llama.cpp"
LLAMA_BIN="$LLAMA_DIR/build/bin/llama-server"
MODELS="$DST/models"
SMALL_MODEL="$MODELS/model-0.5b.gguf"
MAIN_MODEL="$MODELS/model.gguf"
NM_CONF=/etc/NetworkManager/conf.d/stella-unmanaged.conf
UNIT_DIR=/etc/systemd/system
BIN_DIR=/usr/local/bin
NGINX_DIR=/etc/nginx
HOSTAPD_CONF=/etc/hostapd/hostapd.conf
HOSTAPD_DEFAULT=/etc/default/hostapd
DNSMASQ_CONF=/etc/dnsmasq.d/stella.conf
DNSMASQ_DEFAULT=/etc/default/dnsmasq
POLICY_RC=/usr/sbin/policy-rc.d
HF_BASE="${STELLA_HF_BASE:-https://huggingface.co}"
HF_BASE="${HF_BASE%/}"
URL_SMALL="$HF_BASE/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
URL_MAIN="$HF_BASE/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
MIN_SMALL=300000000
MIN_MAIN=800000000
PACKAGES=(hostapd dnsmasq nginx iptables iw python3-venv python3-pip git cmake build-essential curl util-linux unzip ca-certificates)
STEPS=10

MODEL="$(printf '%s' "${MODEL:-0.5b}" | tr '[:upper:]' '[:lower:]')"
JOBS="${JOBS:-2}"
OVER_WIFI="${STELLA_OVER_WIFI:-0}"

QUICK=0
ONLINE=0
NET_PYPI=0
NET_HF=0
FIRST_INSTALL=0
STARTED=0
LOCKED=0
SYNCED=0
FINISHED=0
POLICY_CREATED=0
STEP="подготовка"
STEP_NO=0
VERSION="?"
OLD_NET_SUM=""
NEW_PIN=""
BG_PID=""
TEE_PID=""
WARNINGS=()
DONE=()
CHANGED=()

say() { printf '%s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { WARNINGS+=("$*"); printf '!!! %s\n' "$*"; }
note() { DONE+=("$*"); }
die() { printf '\n!!! ОШИБКА: %s\n' "$*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
is_num() { [[ "$1" =~ ^[0-9]+$ ]]; }
changed() { [[ " ${CHANGED[*]} " == *" $1 "* ]]; }

step() {
  STEP_NO=$((STEP_NO + 1))
  STEP="$*"
  printf '\n==> [%s/%s] %s\n' "$STEP_NO" "$STEPS" "$*"
}

file_size() {
  local n
  n=$(stat -c %s "$1" 2>/dev/null) || n=0
  if is_num "$n"; then echo "$n"; else echo 0; fi
}

human() {
  local b="${1:-0}"
  is_num "$b" || b=0
  if [ "$b" -ge 1073741824 ]; then
    printf '%s,%s ГБ' $((b / 1073741824)) $(((b % 1073741824) * 10 / 1073741824))
  else
    printf '%s МБ' $((b / 1048576))
  fi
}

is_gguf() {
  [ -f "$1" ] && [ -r "$1" ] && [ "$(head -c 4 "$1" 2>/dev/null | tr -d '\000')" = GGUF ]
}

model_ok() {
  is_gguf "$1" && [ "$(file_size "$1")" -ge "$2" ]
}

sum_of() {
  cksum 2>/dev/null < "$1" || true
}

version_of() {
  sed -n 's/^VERSION = "\([^"]*\)".*/\1/p' "$1/app/config.py" 2>/dev/null || true
}

env_value() {
  local file="$1" key="$2" line value=""
  [ -r "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in "$key="*) value="${line#"$key="}" ;; esac
  done < "$file"
  value="${value#\"}"
  value="${value%\"}"
  printf '%s' "$value"
}

env_put() {
  local file="$1" key="$2" value="$3" tmp
  tmp=$(mktemp "$(dirname "$file")/.stella.env.XXXXXX") || return 1
  if ! KEY="$key" VALUE="$value" awk '
      BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["VALUE"]; done = 0 }
      { line = $0; sub(/\r$/, "", line) }
      index(line, k "=") == 1 { if (!done) print k "=" v; done = 1; next }
      { print line }
      END { if (!done) print k "=" v }
    ' "$file" > "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  chmod --reference="$file" "$tmp" 2>/dev/null || chmod 640 "$tmp"
  chown --reference="$file" "$tmp" 2>/dev/null || true
  mv -f "$tmp" "$file"
}

merge_env() {
  local example="$1" target="$2" line key tmp
  local -a added=()
  [ -r "$example" ] && [ -f "$target" ] || return 1
  tmp=$(mktemp "$(dirname "$target")/.stella.env.XXXXXX") || return 1
  if ! cp -p "$target" "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  if [ -s "$tmp" ] && [ -n "$(tail -c 1 "$tmp")" ]; then
    printf '\n' >> "$tmp"
  fi
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)= ]] || continue
    key="${BASH_REMATCH[1]}"
    if ! grep -q "^[[:space:]]*${key}=" "$tmp"; then
      printf '%s\n' "$line" >> "$tmp"
      added+=("$key")
    fi
  done < "$example"
  if ! mv -f "$tmp" "$target"; then
    rm -f "$tmp"
    return 1
  fi
  if [ ${#added[@]} -gt 0 ]; then
    printf '%s\n' "${added[@]}"
  fi
}

new_pin() {
  local n
  n=$(shuf -i 100000-999999 -n 1 --random-source=/dev/urandom 2>/dev/null) || n=""
  if ! [[ "$n" =~ ^[0-9]{6}$ ]]; then
    n=$(od -An -N4 -tu4 /dev/urandom 2>/dev/null | tr -d ' ') || n=""
    is_num "$n" || n=$((RANDOM * 32768 + RANDOM))
    n=$((100000 + n % 900000))
  fi
  echo "$n"
}

cable_ip() {
  ip -o -4 addr show 2>/dev/null | awk '$2 ~ /^(eth|end|enp|enx|usb)/ {print $4; exit}' || true
}

rotate_log() {
  if [ -f "$LOG" ] && [ "$(file_size "$LOG")" -gt "$LOG_MAX" ]; then
    mv -f "$LOG" "$LOG.1" 2>/dev/null || true
  fi
}

probe_url() {
  local code
  have curl || return 1
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$1" 2>/dev/null) || true
  [ -n "$code" ] && [ "$code" != 000 ]
}

venv_usable() {
  [ -x "$PY" ] && "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

py_version() {
  "$1" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo "?"
}

sys_python_ok() {
  have python3 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

block_service_autostart() {
  local ours
  ours=$(printf '#!/bin/sh\nexit 101')
  if [ -e "$POLICY_RC" ]; then
    if [ "$(cat "$POLICY_RC" 2>/dev/null)" = "$ours" ]; then
      POLICY_CREATED=1
    fi
    return 0
  fi
  if printf '%s\n' "$ours" > "$POLICY_RC" && chmod +x "$POLICY_RC"; then
    POLICY_CREATED=1
  fi
}

unblock_service_autostart() {
  if [ "$POLICY_CREATED" = 1 ]; then
    rm -f "$POLICY_RC"
    POLICY_CREATED=0
  fi
}

write_last() {
  local mode=full tmp
  [ "$QUICK" = 1 ] && mode=quick
  mkdir -p "$STATE_DIR" 2>/dev/null || return 0
  tmp="$LAST.tmp"
  {
    echo "when=$(date '+%Y-%m-%d %H:%M')"
    echo "result=$1"
    echo "mode=$mode"
    echo "version=$VERSION"
    echo "warnings=${#WARNINGS[@]}"
    echo "step=$STEP"
  } > "$tmp" 2>/dev/null && mv -f "$tmp" "$LAST" 2>/dev/null
  return 0
}

on_err() {
  local rc=$? line="$1" cmd="$2"
  printf '!!! Команда завершилась с ошибкой (код %s, строка %s): %s\n' "$rc" "$line" "$cmd"
}

on_exit() {
  local rc=$?
  set +e
  trap - ERR
  unblock_service_autostart
  if [ "$rc" -ne 0 ] && [ "$STARTED" = 1 ] && [ "$FINISHED" != 1 ]; then
    say ""
    say "!!! Установка остановилась на шаге «$STEP» (код $rc)."
    say "!!! Подробности — строками выше и в журнале: $LOG"
    if [ "$SYNCED" = 1 ] && have systemctl; then
      systemctl restart stella-app stella-hw >/dev/null 2>&1
    fi
    if have systemctl && systemctl is-active --quiet hostapd 2>/dev/null; then
      say "!!! Сеть SOS-STELLA-RESCUE работает, плата не перезагружается."
    fi
    say "!!! Исправьте причину (чаще всего — нет интернета) и повторите: sudo stella update"
    if [ "$LOCKED" = 1 ]; then
      write_last fail
    fi
  fi
  flush_log
}

flush_log() {
  [ -n "$TEE_PID" ] || return 0
  exec 1>&- 2>&-
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    kill -0 "$TEE_PID" 2>/dev/null || return 0
    sleep 0.1
  done
}

bg_running() {
  local state
  if [ -z "$BG_PID" ]; then
    state=$(systemctl is-active "$BG_UNIT" 2>/dev/null) || true
    [ "$state" = active ] || [ "$state" = activating ]
  else
    kill -0 "$BG_PID" 2>/dev/null
  fi
}

follow_background() {
  local offset="$1" tail_pid
  tail -c "+$((offset + 1))" -F "$LOG" 2>/dev/null &
  tail_pid=$!
  trap 'kill "$tail_pid" 2>/dev/null; printf "\nПерестал показывать журнал. Установка идёт дальше: sudo tail -f %s\n" "$LOG"; exit 0' INT TERM
  sleep 2
  while bg_running; do
    sleep 2
  done
  sleep 1
  kill "$tail_pid" 2>/dev/null || true
  wait "$tail_pid" 2>/dev/null || true
  trap - INT TERM
}

run_background() {
  local offset started=0 t0
  local -a envs=(STELLA_OVER_WIFI=1 "MODEL=$MODEL" "JOBS=$JOBS")
  [ -n "${STELLA_QUICK:-}" ] && envs+=("STELLA_QUICK=$STELLA_QUICK")
  [ -n "${STELLA_HF_BASE:-}" ] && envs+=("STELLA_HF_BASE=$STELLA_HF_BASE")
  [ -n "${STELLA_REBOOT:-}" ] && envs+=("STELLA_REBOOT=$STELLA_REBOOT")
  rotate_log
  offset=$(file_size "$LOG")
  t0=$(date +%s)
  if have systemd-run && [ -d /run/systemd/system ]; then
    if systemctl is-active --quiet "$BG_UNIT" 2>/dev/null; then
      say "Установка уже идёт в фоне. Смотреть ход: sudo tail -f $LOG"
      exit 0
    fi
    systemctl reset-failed "$BG_UNIT" >/dev/null 2>&1 || true
    if systemd-run --quiet --collect --unit "$BG_UNIT" --description "Stella Pocket: установка" \
        "$(command -v env)" "${envs[@]}" /bin/bash "$SELF"; then
      started=1
    fi
  fi
  if [ "$started" = 0 ]; then
    env "${envs[@]}" setsid nohup /bin/bash "$SELF" > /dev/null 2>&1 < /dev/null &
    BG_PID=$!
  fi
  say "Показываю ход установки. Ctrl+C — перестать смотреть (установка продолжится)."
  say "Открыть журнал снова: sudo tail -f $LOG"
  follow_background "$offset"
  if [ -r "$LAST" ] && [ "$(stat -c %Y "$LAST" 2>/dev/null || echo 0)" -ge "$t0" ]; then
    say ""
    say "Итог: $(sed -n 's/^result=//p' "$LAST" 2>/dev/null) ($(sed -n 's/^when=//p' "$LAST" 2>/dev/null))"
  fi
  exit 0
}

need_root() {
  if [ "$(id -u)" != 0 ]; then
    say "Нужны права администратора. Запустите так:  sudo bash $SELF"
    exit 1
  fi
}

check_source() {
  if [ ! -f "$SRC/app/main.py" ] || [ ! -f "$SRC/requirements.txt" ] || [ ! -f "$SRC/deploy/stella.env.example" ] || [ ! -d "$SRC/deploy/systemd" ]; then
    die "рядом нет файлов программы ($SRC/app, $SRC/deploy). Запускайте из распакованного архива: sudo bash stella_pocket_rescue/deploy/install.sh — или просто: sudo stella update"
  fi
}

check_args() {
  case "$MODEL" in
    0.5b|1.5b) ;;
    *) die "MODEL должен быть 0.5b или 1.5b (сейчас: $MODEL)" ;;
  esac
  if ! is_num "$JOBS" || [ "$JOBS" -lt 1 ] || [ "$JOBS" -gt 16 ]; then
    JOBS=2
  fi
}

guard_wifi() {
  [ "$OVER_WIFI" = 1 ] && return 0
  [ "${STELLA_FOREGROUND:-0}" = 1 ] && return 0
  [ -n "$(cable_ip)" ] && return 0
  say "Плата подключена только по Wi-Fi (кабеля нет)."
  say "Установка может оборвать Wi-Fi и SSH, поэтому она продолжится в фоне сама по себе."
  say "Если SSH отключится — ничего страшного: подождите 3–5 минут и подключитесь к сети SOS-STELLA-RESCUE."
  OVER_WIFI=1
  run_background
}

start_log() {
  rotate_log
  if touch "$LOG" 2>/dev/null; then
    chmod 640 "$LOG" 2>/dev/null || true
    exec > >(trap '' HUP INT; exec tee -a "$LOG") 2>&1
    TEE_PID="${!:-}"
  fi
  STARTED=1
  say ""
  say "===== Stella Pocket: установка $(date '+%Y-%m-%d %H:%M:%S') ====="
  info "источник: $SRC"
}

take_lock() {
  have flock || { LOCKED=1; return 0; }
  if ! { exec 9>"$LOCK"; } 2>/dev/null; then
    LOCKED=1
    return 0
  fi
  if ! flock -n 9; then
    die "уже идёт другая установка. Дождитесь её конца (sudo tail -f $LOG) и повторите"
  fi
  LOCKED=1
}

detect_net() {
  local p1 p2
  { if probe_url "https://pypi.org/simple/"; then exit 0; else exit 1; fi; } &
  p1=$!
  { if probe_url "$HF_BASE"; then exit 0; else exit 1; fi; } &
  p2=$!
  if wait "$p1"; then NET_PYPI=1; fi
  if wait "$p2"; then NET_HF=1; fi
  if [ "$NET_PYPI" = 1 ] || [ "$NET_HF" = 1 ]; then ONLINE=1; fi
}

choose_mode() {
  local want
  want=$(printf '%s' "${STELLA_QUICK:-auto}" | tr '[:upper:]' '[:lower:]')
  case "$want" in
    1|yes|true|on|quick)
      if venv_usable; then
        QUICK=1
      elif [ "$ONLINE" = 1 ]; then
        warn "быстрый режим невозможен: нет готового окружения Python — делаю полную установку"
      else
        die "нет интернета и нет готового окружения Python. Первая установка требует интернет: подключите плату кабелем к роутеру и повторите"
      fi
      ;;
    0|no|false|off|full) QUICK=0 ;;
    *)
      if [ "$ONLINE" = 1 ]; then
        QUICK=0
      elif venv_usable; then
        QUICK=1
      else
        die "нет интернета, а Stella на этой плате ещё не установлена. Подключите плату кабелем к роутеру (или sudo stella home \"ИМЯ_WIFI\" \"ПАРОЛЬ\") и повторите"
      fi
      ;;
  esac
}

prepare() {
  local yes_no_pypi="нет" yes_no_hf="нет"
  VERSION=$(version_of "$SRC")
  [ -n "$VERSION" ] || VERSION="?"
  if venv_usable && [ -f "$ENV_FILE" ]; then FIRST_INSTALL=0; else FIRST_INSTALL=1; fi
  info "проверяю интернет (pypi.org, ${HF_BASE#https://})…"
  detect_net
  [ "$NET_PYPI" = 1 ] && yes_no_pypi="есть"
  [ "$NET_HF" = 1 ] && yes_no_hf="есть"
  choose_mode
  OLD_NET_SUM=$(sum_of "$DST/deploy/stella-net.sh")
  info "версия: $VERSION"
  info "интернет: библиотеки Python — $yes_no_pypi, модели — $yes_no_hf"
  if [ "$QUICK" = 1 ]; then
    info "режим: БЫСТРЫЙ — только файлы программы, настройки и службы (пакеты, библиотеки и модели не трогаю)"
  else
    info "режим: ПОЛНЫЙ — пакеты, библиотеки, llama.cpp (если нет), модели"
  fi
  if [ "$FIRST_INSTALL" = 1 ]; then info "это первая установка на эту плату"; fi
  if [ "$OVER_WIFI" = 1 ]; then info "связь с платой по Wi-Fi: сеть в конце может перезапуститься"; fi
}

step_packages() {
  step "Системные пакеты"
  if [ "$QUICK" = 1 ]; then
    info "быстрый режим — пропускаю"
    return 0
  fi
  if ! have apt-get; then
    warn "нет apt-get — системные пакеты не ставлю"
    check_commands
    return 0
  fi
  export DEBIAN_FRONTEND=noninteractive
  block_service_autostart
  dpkg --configure -a > /dev/null 2>&1 || true
  if ! apt-get -q -o DPkg::Lock::Timeout=300 update; then
    warn "apt-get update завершился с ошибкой (нет интернета или сломан список источников) — ставлю из того, что есть"
  fi
  if apt-get install -y -q -o DPkg::Lock::Timeout=300 \
      -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "${PACKAGES[@]}"; then
    note "системные пакеты на месте"
  else
    warn "не все системные пакеты установились — проверяю самое нужное"
  fi
  unblock_service_autostart
  check_commands
}

check_commands() {
  local c
  local -a missing=()
  for c in hostapd dnsmasq nginx iptables python3 curl; do
    have "$c" || missing+=("$c")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    die "не хватает программ: ${missing[*]}. Нужен интернет: подключите плату кабелем к роутеру и повторите"
  fi
}

ensure_user() {
  if ! getent group stella > /dev/null 2>&1; then
    groupadd --system stella || die "не удалось создать группу stella"
  fi
  if ! id stella > /dev/null 2>&1; then
    useradd --system --gid stella --home-dir "$DST" --no-create-home --shell /usr/sbin/nologin stella \
      || die "не удалось создать пользователя stella"
  fi
}

same_dir() {
  local a b
  a=$(cd "$1" 2>/dev/null && pwd -P) || return 1
  b=$(cd "$2" 2>/dev/null && pwd -P) || return 1
  [ "$a" = "$b" ]
}

sync_dir() {
  local from="$1" to="$2" tmp="$2.new.$$" old="$2.old.$$"
  rm -rf "$tmp"
  if ! cp -a "$from" "$tmp"; then
    rm -rf "$tmp"
    die "не удалось скопировать $from в $DST (закончилось место на карте?)"
  fi
  find "$tmp" \( -name __pycache__ -o -name '*.pyc' -o -name '*.tmp' \) -prune -exec rm -rf {} + 2>/dev/null || true
  if [ -e "$to" ] && ! mv "$to" "$old"; then
    rm -rf "$tmp"
    die "не удалось заменить $to"
  fi
  if ! mv "$tmp" "$to"; then
    [ -e "$old" ] && mv "$old" "$to"
    die "не удалось заменить $to"
  fi
  rm -rf "$old"
}

fix_line_endings() {
  local f
  for f in "$1"/*.sh "$1"/stella "$1"/*.conf "$1"/*.example "$1"/systemd/*.service; do
    [ -f "$f" ] || continue
    if grep -q $'\r' "$f" 2>/dev/null; then
      sed -i 's/\r$//' "$f" && info "исправлены окончания строк Windows: $(basename "$f")"
    fi
  done
}

step_files() {
  local d
  step "Файлы программы в $DST"
  ensure_user
  mkdir -p "$DST" "$STATE_DIR" "$ETC_DIR" "$MODELS"
  rm -rf "$DST"/app.new.* "$DST"/app.old.* "$DST"/deploy.new.* "$DST"/deploy.old.*
  if same_dir "$SRC" "$DST"; then
    info "запуск из $DST — копировать нечего"
  else
    for d in app deploy; do
      sync_dir "$SRC/$d" "$DST/$d"
    done
    install -m 644 "$SRC/requirements.txt" "$DST/requirements.txt"
    info "app/ и deploy/ заменены целиком (лишние старые файлы удалены)"
    note "файлы программы обновлены до версии $VERSION"
  fi
  SYNCED=1
  fix_line_endings "$DST/deploy"
  chmod 755 "$DST"/deploy/*.sh "$DST/deploy/stella" 2>/dev/null || true
  chown -R stella:stella "$STATE_DIR" 2>/dev/null || warn "не удалось выдать права на $STATE_DIR"
}

step_env() {
  local pin added
  step "Настройки $ENV_FILE"
  if [ ! -s "$ENV_FILE" ]; then
    pin=$(new_pin)
    (umask 027 && sed "s/^STELLA_RESCUER_PIN=.*/STELLA_RESCUER_PIN=$pin/" "$DST/deploy/stella.env.example" > "$ENV_FILE.tmp")
    mv -f "$ENV_FILE.tmp" "$ENV_FILE"
    NEW_PIN="$pin"
    info "создан новый файл настроек"
    note "создан файл настроек с новым PIN"
  else
    cp -p "$ENV_FILE" "$ENV_FILE.bak" 2>/dev/null || true
    if added=$(merge_env "$DST/deploy/stella.env.example" "$ENV_FILE"); then
      if [ -n "$added" ]; then
        info "добавлены новые настройки: $(printf '%s' "$added" | tr '\n' ' ')"
        note "в настройки добавлено: $(printf '%s' "$added" | tr '\n' ' ')"
      else
        info "все настройки на месте, ваши значения не менялись"
      fi
    else
      warn "не удалось дополнить $ENV_FILE — старые настройки оставлены как есть"
    fi
    pin=$(env_value "$ENV_FILE" STELLA_RESCUER_PIN)
    if [ -z "$pin" ] || [ "$pin" = 000000 ]; then
      pin=$(new_pin)
      if env_put "$ENV_FILE" STELLA_RESCUER_PIN "$pin"; then
        NEW_PIN="$pin"
        note "PIN спасателя был пустым — задан новый"
      else
        warn "PIN спасателя пустой, а записать новый не удалось"
      fi
    fi
  fi
  chown root:stella "$ENV_FILE" 2>/dev/null || warn "не удалось сменить владельца $ENV_FILE"
  chmod 640 "$ENV_FILE" 2>/dev/null || true
}

install_uv() {
  local script
  [ -x "$UV" ] && return 0
  info "ставлю uv (менеджер Python) в $DST/uv"
  script=$(mktemp) || return 1
  if ! curl -fsSL --max-time 180 --retry 3 -o "$script" https://astral.sh/uv/install.sh; then
    rm -f "$script"
    return 1
  fi
  env UV_INSTALL_DIR="$DST/uv" INSTALLER_NO_MODIFY_PATH=1 sh "$script" || true
  rm -f "$script"
  [ -x "$UV" ]
}

create_venv() {
  local aside="" ok=0
  if [ -e "$DST/venv" ]; then
    aside="$DST/venv.old.$(date +%s)"
    mv "$DST/venv" "$aside"
    info "старое окружение не подходит (Python < 3.10 или сломано) — откладываю в $aside"
  fi
  if sys_python_ok; then
    info "создаю окружение на системном Python $(py_version python3)"
    python3 -m venv "$DST/venv" && ok=1
  else
    info "системный Python $(py_version python3) слишком старый — ставлю Python 3.11 через uv"
    export UV_PYTHON_INSTALL_DIR="$DST/python"
    if install_uv; then
      "$UV" venv --seed --python 3.11 "$DST/venv" && ok=1
      if [ "$ok" = 0 ]; then
        rm -rf "$DST/venv"
        "$UV" venv --python 3.11 "$DST/venv" && ok=1
      fi
    fi
  fi
  if [ "$ok" = 1 ] && venv_usable; then
    [ -n "$aside" ] && rm -rf "$aside"
    note "создано окружение Python $(py_version "$PY")"
    return 0
  fi
  rm -rf "$DST/venv"
  if [ -n "$aside" ]; then mv "$aside" "$DST/venv"; fi
  return 1
}

pip_install() {
  if "$PY" -m pip --version > /dev/null 2>&1; then
    "$PY" -m pip install -q --upgrade pip --timeout 30 --retries 2 > /dev/null 2>&1 || true
    "$PY" -m pip install --prefer-binary --timeout 30 --retries 3 "$@"
  elif [ -x "$UV" ]; then
    UV_HTTP_TIMEOUT=60 "$UV" pip install --python "$PY" "$@"
  else
    "$PY" -m ensurepip > /dev/null 2>&1 && "$PY" -m pip install --prefer-binary --timeout 30 --retries 3 "$@"
  fi
}

step_python() {
  local ver
  step "Python и библиотеки"
  if venv_usable; then
    info "окружение $DST/venv уже есть (Python $(py_version "$PY")) — использую его"
  elif [ "$QUICK" = 1 ]; then
    warn "окружение Python сломано, а интернета нет — сайт может не запуститься"
  elif ! create_venv; then
    die "не удалось создать окружение Python в $DST/venv (нужен интернет). Подключите интернет и повторите"
  fi
  if [ "$QUICK" = 1 ]; then
    info "быстрый режим — библиотеки не обновляю"
  elif [ "$NET_PYPI" != 1 ]; then
    warn "нет доступа к pypi.org — библиотеки Python не обновлены"
  elif pip_install -r "$DST/requirements.txt"; then
    note "библиотеки Python установлены"
  else
    warn "не удалось установить библиотеки Python (обрыв интернета?). Облачный ИИ заработает после обновления с интернетом: sudo stella update"
  fi
  if ! "$PY" -c 'import fastapi, uvicorn, httpx' > /dev/null 2>&1; then
    if [ "$QUICK" = 1 ]; then
      warn "в окружении нет fastapi/uvicorn/httpx — сайт не запустится, пока не обновитесь с интернетом"
    else
      die "не установлены основные библиотеки (fastapi, uvicorn, httpx) — сайт не запустится. Подключите интернет и повторите"
    fi
  else
    info "основные библиотеки: в порядке"
  fi
  if ver=$("$PY" -c 'import anthropic; print(anthropic.__version__)' 2>/dev/null); then
    info "облачный ИИ: библиотека anthropic $ver"
  else
    warn "нет библиотеки anthropic — облачный ИИ (Claude) недоступен, пока не обновитесь с интернетом (sudo stella update)"
  fi
}

gcc_major() {
  local v
  v=$(g++ -dumpversion 2>/dev/null) || v=0
  v="${v%%.*}"
  if is_num "$v"; then echo "$v"; else echo 0; fi
}

cmake_ok() {
  local out
  out=$("$1" --version 2>/dev/null) || return 1
  [[ "$out" =~ version\ ([0-9]+)\.([0-9]+) ]] || return 1
  [ "${BASH_REMATCH[1]}" -gt 3 ] || { [ "${BASH_REMATCH[1]}" -eq 3 ] && [ "${BASH_REMATCH[2]}" -ge 18 ]; }
}

build_llama() {
  local cmake_bin=cmake
  local -a cc=()
  if [ -x "$DST/deploy/stella-power.sh" ]; then
    info "на время сборки ограничиваю частоту больших ядер, чтобы не просело питание"
    "$DST/deploy/stella-power.sh" safe || true
  fi
  if [ "$(gcc_major)" -lt 10 ]; then
    info "компилятор старше 10 — ставлю g++-10"
    if apt-get install -y -q -o DPkg::Lock::Timeout=300 g++-10 gcc-10 && have g++-10; then
      cc=(-DCMAKE_C_COMPILER=gcc-10 -DCMAKE_CXX_COMPILER=g++-10)
    else
      warn "g++-10 не установился — пробую собрать стандартным компилятором"
    fi
  fi
  if [ ! -f "$LLAMA_DIR/CMakeLists.txt" ]; then
    rm -rf "$LLAMA_DIR"
    info "скачиваю исходники llama.cpp"
    GIT_TERMINAL_PROMPT=0 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=60 \
      clone --depth 1 https://github.com/ggml-org/llama.cpp "$LLAMA_DIR" || return 1
  fi
  if ! cmake_ok cmake; then
    info "cmake старше 3.18 — ставлю свежий cmake в окружение Python"
    pip_install cmake || return 1
    cmake_bin="$DST/venv/bin/cmake"
    cmake_ok "$cmake_bin" || return 1
  fi
  rm -rf "$LLAMA_DIR/build"
  nice -n 10 "$cmake_bin" -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF "${cc[@]}" || return 1
  nice -n 10 "$cmake_bin" --build "$LLAMA_DIR/build" --target llama-server llama-bench -j "$JOBS" || return 1
  [ -x "$LLAMA_BIN" ]
}

step_llama() {
  step "Локальный ИИ: llama.cpp"
  if [ -x "$LLAMA_BIN" ]; then
    info "llama-server уже собран — пропускаю"
    return 0
  fi
  if [ "$QUICK" = 1 ]; then
    warn "llama.cpp не собрана, а интернета нет — локальный ИИ появится после обновления с интернетом"
    return 0
  fi
  info "сборка займёт 15–25 минут (потоков: $JOBS)"
  if build_llama; then
    note "llama.cpp собрана"
  else
    warn "llama.cpp не собралась — сайт, сортировка, облачный и резервный ИИ работают. Если в журнале есть слово Killed, повторите с одним потоком: sudo stella update --jobs 1"
  fi
}

remote_size() {
  local n
  n=$(curl -sIL --max-time 30 "$1" 2>/dev/null | tr -d '\r' |
      awk 'tolower($1) == "x-linked-size:" {x = $2} tolower($1) == "content-length:" {n = $2} END {print (x != "" ? x : n)}') || n=""
  if is_num "$n" && [ "$n" -ge 1000000 ]; then echo "$n"; fi
}

free_bytes() {
  df -PB1 "$1" 2>/dev/null | awk 'NR == 2 {print $4}' || true
}

download() {
  local url="$1" out="$2"
  shift 2
  curl -L --fail --retry 5 --retry-delay 5 --connect-timeout 20 --speed-limit 2048 --speed-time 90 \
    --progress-bar "$@" -o "$out" "$url"
}

fetch_model() {
  local url="$1" dest="$2" min="$3" label="$4" part="$2.part" remote got avail need rc
  if model_ok "$dest" "$min"; then
    info "$label: уже есть ($(human "$(file_size "$dest")")) — оставляю"
    return 0
  fi
  if [ -e "$dest" ]; then
    info "$label: файл повреждён — скачаю заново"
    rm -f "$dest"
  fi
  if [ "$NET_HF" != 1 ]; then
    warn "$label: нет доступа к ${HF_BASE#https://} — не скачана"
    return 1
  fi
  remote=$(remote_size "$url")
  got=$(file_size "$part")
  if [ -n "$remote" ] && [ "$got" -gt "$remote" ]; then
    rm -f "$part"
    got=0
  fi
  avail=$(free_bytes "$MODELS")
  if [ -n "$remote" ] && is_num "$avail"; then
    need=$((remote - got + 104857600))
    if [ "$avail" -lt "$need" ]; then
      warn "$label: мало места на карте (свободно $(human "$avail"), нужно $(human "$need")) — не скачана"
      return 1
    fi
  fi
  if [ -z "$remote" ] || [ "$got" -lt "$remote" ]; then
    if [ "$got" -gt 0 ]; then
      info "$label: докачиваю с $(human "$got")"
    else
      info "$label: скачиваю${remote:+ $(human "$remote")} — если оборвётся, при следующем запуске докачается"
    fi
    rc=0
    download "$url" "$part" -C - || rc=$?
    if [ "$rc" != 0 ] && [ "$(file_size "$part")" -gt 0 ] && { [ "$rc" = 22 ] || [ "$rc" = 33 ] || [ "$rc" = 36 ]; }; then
      if [ -n "$remote" ] && [ "$(file_size "$part")" = "$remote" ]; then
        rc=0
      else
        info "$label: докачка не удалась — начинаю заново"
        rm -f "$part"
        rc=0
        download "$url" "$part" || rc=$?
      fi
    fi
    if [ "$rc" != 0 ]; then
      warn "$label: скачивание прервалось (код curl $rc). Повторите sudo stella update — докачается с места обрыва"
      return 1
    fi
  fi
  got=$(file_size "$part")
  if [ -n "$remote" ] && [ "$got" != "$remote" ]; then
    warn "$label: скачано $(human "$got") из $(human "$remote") — повторите sudo stella update, докачается"
    return 1
  fi
  if ! model_ok "$part" "$min"; then
    rm -f "$part"
    warn "$label: скачанный файл не похож на модель GGUF — удалён. Если сайт заблокирован, попробуйте зеркало: sudo STELLA_HF_BASE=https://hf-mirror.com stella update"
    return 1
  fi
  mv -f "$part" "$dest"
  chown stella:stella "$dest" 2>/dev/null || true
  note "$label скачана"
  info "$label: готово ($(human "$got"))"
}

reuse_small_model() {
  model_ok "$SMALL_MODEL" "$MIN_SMALL" && return 0
  if model_ok "$MAIN_MODEL" "$MIN_SMALL" && [ "$(file_size "$MAIN_MODEL")" -lt 700000000 ]; then
    rm -f "$SMALL_MODEL"
    ln "$MAIN_MODEL" "$SMALL_MODEL" 2>/dev/null || cp -p "$MAIN_MODEL" "$SMALL_MODEL" || return 0
    info "model.gguf — это маленькая модель 0.5B, использую её и как model-0.5b.gguf"
  fi
  return 0
}

step_models() {
  local found=0
  step "Модели локального ИИ"
  mkdir -p "$MODELS"
  reuse_small_model
  if [ "$QUICK" = 1 ]; then
    info "быстрый режим — модели не скачиваю"
  else
    fetch_model "$URL_SMALL" "$SMALL_MODEL" "$MIN_SMALL" "модель 0.5B (≈400 МБ)" || true
    if [ "$MODEL" = 1.5b ]; then
      fetch_model "$URL_MAIN" "$MAIN_MODEL" "$MIN_MAIN" "модель 1.5B (≈1,1 ГБ)" || true
    fi
  fi
  if model_ok "$SMALL_MODEL" "$MIN_SMALL"; then
    info "есть: model-0.5b.gguf ($(human "$(file_size "$SMALL_MODEL")")) — для бережного режима питания"
    found=1
  fi
  if model_ok "$MAIN_MODEL" "$MIN_SMALL"; then
    info "есть: model.gguf ($(human "$(file_size "$MAIN_MODEL")")) — для полного режима питания"
    found=1
  fi
  if [ "$found" = 0 ]; then
    warn "нет ни одной модели — локальный ИИ не запустится (облачный и резервный работают). Скачать: sudo stella update с интернетом"
  fi
  chown -R stella:stella "$MODELS" 2>/dev/null || true
}

install_conf() {
  local from="$1" to="$2" tag="$3"
  if [ ! -f "$from" ]; then
    warn "нет файла $from"
    return 0
  fi
  if [ -f "$to" ] && cmp -s "$from" "$to"; then
    return 0
  fi
  if install -D -m 644 "$from" "$to"; then
    CHANGED+=("$tag")
    info "обновлён $to"
  else
    warn "не удалось записать $to"
  fi
}

set_default_var() {
  local file="$1" key="$2" value="$3"
  [ -f "$file" ] || return 0
  if grep -q "^#\?[[:space:]]*$key=" "$file"; then
    sed -i "s|^#\?[[:space:]]*$key=.*|$key=$value|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

nginx_site() {
  local site="$NGINX_DIR/sites-available/stella" backup=""
  if ! have nginx; then
    warn "nginx не установлен — сайт не будет открываться на порту 80"
    return 0
  fi
  if [ -f "$site" ]; then
    backup=$(mktemp) || backup=""
    if [ -n "$backup" ] && ! cp -p "$site" "$backup"; then
      rm -f "$backup"
      backup=""
    fi
  fi
  install_conf "$DST/deploy/nginx-stella.conf" "$site" nginx
  mkdir -p "$NGINX_DIR/sites-enabled"
  ln -sf "$site" "$NGINX_DIR/sites-enabled/stella"
  rm -f "$NGINX_DIR/sites-enabled/default"
  if nginx -t > /dev/null 2>&1; then
    info "nginx: настройки в порядке"
  else
    nginx -t 2>&1 | sed 's/^/    /' || true
    if [ -n "$backup" ]; then
      cp -p "$backup" "$site"
      warn "nginx не принял новые настройки — вернул прежние"
    else
      warn "nginx не принял настройки — сайт может не открываться"
    fi
  fi
  if [ -n "$backup" ]; then rm -f "$backup"; fi
}

nm_unmanaged() {
  local tmp
  if [ ! -d "$(dirname "$(dirname "$NM_CONF")")" ] && ! have nmcli; then
    return 0
  fi
  tmp=$(mktemp) || return 0
  printf '[keyfile]\nunmanaged-devices=interface-name:wlan0\n' > "$tmp"
  install_conf "$tmp" "$NM_CONF" nm
  rm -f "$tmp"
  if changed nm; then
    info "NetworkManager больше не трогает wlan0 (применится после перезагрузки или sudo stella sos)"
  fi
}

step_network() {
  step "Сеть: точка доступа SOS, DHCP/DNS, веб-сервер"
  install_conf "$DST/deploy/hostapd.conf" "$HOSTAPD_CONF" hostapd
  set_default_var "$HOSTAPD_DEFAULT" DAEMON_CONF '"/etc/hostapd/hostapd.conf"'
  install_conf "$DST/deploy/dnsmasq-stella.conf" "$DNSMASQ_CONF" dnsmasq
  set_default_var "$DNSMASQ_DEFAULT" DNSMASQ_EXCEPT '"lo"'
  nginx_site
  nm_unmanaged
  if [ ${#CHANGED[@]} -eq 0 ]; then
    info "сетевые настройки не изменились"
  fi
}

install_cli() {
  local tmp="$BIN_DIR/.stella.new"
  mkdir -p "$BIN_DIR"
  if install -m 755 "$DST/deploy/stella" "$tmp" && mv -f "$tmp" "$BIN_DIR/stella"; then
    info "команда stella обновлена: $BIN_DIR/stella"
  else
    rm -f "$tmp"
    warn "не удалось установить команду stella"
  fi
}

step_services() {
  local unit
  step "Службы и команда stella"
  for unit in "$DST"/deploy/systemd/*.service; do
    if [ -f "$unit" ]; then
      install_conf "$unit" "$UNIT_DIR/$(basename "$unit")" units
    fi
  done
  install_cli
  if ! have systemctl; then
    warn "нет systemctl — службы не настроены"
    return 0
  fi
  systemctl daemon-reload || warn "systemctl daemon-reload завершился с ошибкой"
  systemctl unmask hostapd > /dev/null 2>&1 || true
  if systemctl --quiet enable stella-net hostapd dnsmasq nginx stella-app stella-hw; then
    info "автозапуск: stella-net hostapd dnsmasq nginx stella-app stella-hw"
  else
    warn "не все службы добавились в автозапуск"
  fi
  if [ -x "$LLAMA_BIN" ]; then
    systemctl --quiet enable stella-llm || warn "stella-llm не добавилась в автозапуск"
    systemctl reset-failed stella-llm > /dev/null 2>&1 || true
    info "автозапуск: stella-llm (локальный ИИ под присмотром сторожа питания)"
  else
    systemctl --quiet disable stella-llm > /dev/null 2>&1 || true
    info "stella-llm не включена: нет llama-server"
  fi
}

write_manifest() {
  local tmp="$DST/manifest.json.tmp" count
  if [ -x "$PY" ] && (cd "$DST" && PYTHONDONTWRITEBYTECODE=1 "$PY" -m app.integrity build "$DST") > "$tmp"; then
    mv -f "$tmp" "$DST/manifest.json"
    chmod 644 "$DST/manifest.json"
    count=$(grep -c '": "[0-9a-f]\{64\}"' "$DST/manifest.json" || true)
    info "manifest.json: под контролем $count файлов"
    note "контрольные суммы записаны ($count файлов)"
  else
    rm -f "$tmp"
    warn "manifest.json не записан — страница проверки покажет «целостность неизвестна»"
  fi
}

step_manifest() {
  step "Права доступа и контрольные суммы"
  chown -R stella:stella "$DST" 2>/dev/null || warn "не удалось сменить владельца $DST"
  chmod -R a+rX "$DST/app" 2>/dev/null || true
  chmod 755 "$DST"/deploy/*.sh "$DST/deploy/stella" 2>/dev/null || true
  chown -R stella:stella "$STATE_DIR" 2>/dev/null || true
  if ! chown root:stella "$ENV_FILE" 2>/dev/null || ! chmod 640 "$ENV_FILE" 2>/dev/null; then
    warn "не удалось выставить права на $ENV_FILE (root:stella 640)"
  fi
  write_manifest
}

wait_health() {
  local i body engine
  for i in $(seq 1 25); do
    body=$(curl -s --max-time 3 -H 'Host: 10.42.0.1' http://127.0.0.1:8000/api/health 2>/dev/null) || body=""
    case "$body" in
      *'"ok"'*)
        engine=$(printf '%s' "$body" | sed -n 's/.*"ai"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p')
        info "сайт отвечает (${i} с), сейчас отвечает ИИ: ${engine:-?}"
        return 0
        ;;
    esac
    sleep 1
  done
  warn "сайт не ответил за 25 секунд — посмотрите: sudo stella logs app"
}

restart_services() {
  have systemctl || return 0
  info "перезапускаю службы Stella…"
  systemctl restart stella-hw || warn "stella-hw не перезапустилась: sudo stella logs hw"
  if systemctl is-active --quiet hostapd; then
    if [ "$(sum_of "$DST/deploy/stella-net.sh")" != "$OLD_NET_SUM" ] || changed hostapd; then
      info "настройки Wi-Fi изменились — перезапускаю точку доступа (Wi-Fi пропадёт на 5–10 секунд)"
      systemctl restart stella-net hostapd dnsmasq || warn "точка доступа не перезапустилась — перезагрузите плату: sudo reboot"
    elif changed dnsmasq; then
      systemctl restart dnsmasq || warn "dnsmasq не перезапустился"
    fi
  fi
  if systemctl is-active --quiet nginx; then
    systemctl reload nginx || systemctl restart nginx || warn "nginx не перезапустился"
  else
    systemctl restart nginx || warn "nginx не запустился: sudo stella logs"
  fi
  systemctl restart stella-app || warn "stella-app не запустилась: sudo stella logs app"
  if [ -x "$LLAMA_BIN" ]; then
    systemctl restart stella-llm || warn "stella-llm не запустилась: sudo stella logs llm"
    info "локальный ИИ перезапускается — модель загрузится примерно за минуту"
  else
    systemctl stop stella-llm > /dev/null 2>&1 || true
  fi
  wait_health
  note "службы перезапущены без перезагрузки"
}

finish_action() {
  case "${STELLA_REBOOT:-}" in
    1|yes) echo reboot; return ;;
    0|no) echo restart; return ;;
  esac
  if [ "$FIRST_INSTALL" = 1 ]; then
    if [ "$OVER_WIFI" = 1 ]; then echo reboot; else echo ask-reboot; fi
    return
  fi
  if [ "$OVER_WIFI" = 1 ] && have systemctl && ! systemctl is-active --quiet hostapd; then
    echo reboot
    return
  fi
  echo restart
}

summary() {
  local action="$1" item key mode_text="полная установка"
  [ "$QUICK" = 1 ] && mode_text="быстрое обновление без интернета"
  say ""
  say "======================== ИТОГ ========================"
  say "Stella Pocket $VERSION: $mode_text, заняло $((SECONDS / 60)) мин $((SECONDS % 60)) с"
  if [ ${#DONE[@]} -gt 0 ]; then
    say "Сделано:"
    for item in "${DONE[@]}"; do say "  + $item"; done
  fi
  if [ ${#WARNINGS[@]} -gt 0 ]; then
    say "Обратите внимание (${#WARNINGS[@]}):"
    for item in "${WARNINGS[@]}"; do say "  ! $item"; done
  fi
  say ""
  if [ -n "$NEW_PIN" ]; then
    say "  PIN СПАСАТЕЛЯ: $NEW_PIN   (запишите! показать снова: sudo stella pin)"
  else
    say "  PIN спасателя не менялся, хранится в $ENV_FILE — показать: sudo stella pin"
  fi
  key=$(env_value "$ENV_FILE" ANTHROPIC_API_KEY)
  if [ -z "$key" ]; then
    say "  Облачный ИИ: ключ не задан — sudo stella ai key (работает, когда у платы есть интернет)"
  else
    say "  Облачный ИИ: ключ задан — проверить: sudo stella ai test"
  fi
  say "  Проверить всё: sudo stella status"
  say "  Журнал установки: $LOG"
  say ""
  case "$action" in
    reboot)
      say "Плата перезагрузится через 10 секунд. Через 2–3 минуты подключитесь к Wi-Fi SOS-STELLA-RESCUE:"
      say "  чат http://10.42.0.1/   консоль http://10.42.0.1/rescuer   проверка коробки http://10.42.0.1/verify"
      ;;
    ask-reboot)
      say "Осталось перезагрузить плату:  sudo reboot"
      say "После загрузки появится открытая сеть SOS-STELLA-RESCUE (чат http://10.42.0.1/)."
      ;;
    *)
      if have systemctl && systemctl is-active --quiet hostapd; then
        say "Готово, перезагрузка не нужна. Сеть SOS-STELLA-RESCUE работает."
      else
        say "Готово. Плата сейчас в обычном Wi-Fi/кабеле. Вернуть сеть SOS: sudo stella sos (или sudo reboot)"
      fi
      ;;
  esac
}

step_finish() {
  local action
  step "Запуск"
  action=$(finish_action)
  if [ "$action" = restart ]; then
    restart_services
  else
    info "службы запустятся после перезагрузки"
  fi
  FINISHED=1
  if [ ${#WARNINGS[@]} -gt 0 ]; then write_last warn; else write_last ok; fi
  summary "$action"
  if [ "$action" = reboot ]; then
    sync
    sleep 10
    systemctl reboot || reboot
  fi
}

main() {
  set -Eeuo pipefail
  umask 022
  trap on_exit EXIT
  trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR
  trap '' HUP
  need_root
  check_source
  check_args
  guard_wifi
  start_log
  take_lock
  prepare
  step_packages
  step_files
  step_env
  step_python
  step_llama
  step_models
  step_network
  step_services
  step_manifest
  step_finish
}

if [ "${STELLA_INSTALL_LIB:-0}" != 1 ]; then
  main "$@"
fi
