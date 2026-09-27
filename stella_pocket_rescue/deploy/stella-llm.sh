#!/bin/bash
set -u

STATE_DIR="${STELLA_STATE_DIR:-/var/lib/stella}"
POWER_FILE="${STELLA_POWER_FILE:-$STATE_DIR/power.json}"
MODELS_DIR="${STELLA_MODELS_DIR:-/opt/stella/models}"
LLAMA_BIN="${STELLA_LLAMA_BIN:-/opt/stella/llama.cpp/build/bin/llama-server}"
UPTIME_FILE="${STELLA_UPTIME_FILE:-/proc/uptime}"
BOOT_ID_FILE="${STELLA_BOOT_ID_FILE:-/proc/sys/kernel/random/boot_id}"
TASKSET="${STELLA_TASKSET-taskset}"
POWER_WAIT="${STELLA_POWER_WAIT:-30}"
START_DELAY="${STELLA_LLM_START_DELAY:-45}"
SMALL_MODEL="$MODELS_DIR/model-0.5b.gguf"
MAIN_MODEL="${LLAMA_MODEL:-$MODELS_DIR/model.gguf}"

say() { echo "stella-llm: $*"; }

is_num() { [[ "$1" =~ ^[0-9]+$ ]]; }

in_range() { is_num "$1" && [ "$1" -ge "$2" ] && [ "$1" -le "$3" ]; }

json_str() {
  [ -r "$1" ] || return 1
  sed -n "/\"$2\"[[:space:]]*:/{s/.*\"$2\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p;q;}" "$1" 2>/dev/null
}

read_one() {
  local value=""
  [ -r "$1" ] && read -r value 2>/dev/null < "$1"
  echo "$value"
}

uptime_s() {
  local up
  up=$(read_one "$UPTIME_FILE")
  up="${up%% *}"
  up="${up%%.*}"
  if is_num "$up"; then echo "$up"; else echo 999999; fi
}

file_profile() {
  local p
  p=$(json_str "$POWER_FILE" profile)
  case "$p" in normal|safe|off) echo "$p" ;; *) return 1 ;; esac
}

file_is_current() {
  local mine now
  mine=$(json_str "$POWER_FILE" boot_id)
  now=$(read_one "$BOOT_ID_FILE")
  [ -z "$mine" ] || [ -z "$now" ] || [ "$mine" = "$now" ]
}

is_gguf() {
  [ -f "$1" ] && [ -r "$1" ] && [ "$(head -c 4 "$1" 2>/dev/null | tr -d '\000')" = GGUF ]
}

early_boot_pause() {
  local up delay="$START_DELAY"
  in_range "$delay" 0 600 || delay=45
  up=$(uptime_s)
  if [ "$up" -lt 180 ] && [ "$delay" -gt 0 ]; then
    say "плата включилась ${up} с назад — жду ${delay} с, пока установится питание"
    sleep "$delay"
  fi
}

wait_profile() {
  local waited=0 limit="$POWER_WAIT" p manual
  in_range "$limit" 0 600 || limit=30
  while :; do
    if p=$(file_profile) && file_is_current; then
      echo "$p guard"
      return
    fi
    [ "$waited" -ge "$limit" ] && break
    sleep 1
    waited=$((waited + 1))
  done
  p=$(file_profile)
  manual=$(printf '%s' "${STELLA_POWER:-auto}" | tr '[:upper:]' '[:lower:]')
  case "$manual" in
    normal|safe|off)
      say "нет свежего $POWER_FILE за ${limit} с — беру профиль из настроек: $manual" >&2
      echo "$manual manual"
      return
      ;;
  esac
  if [ "$p" = off ]; then
    say "сторож питания не ответил за ${limit} с, последний вердикт — off" >&2
    echo "off guard"
    return
  fi
  say "сторож питания не ответил за ${limit} с — на всякий случай беру безопасный профиль safe" >&2
  echo "safe fallback"
}

pick_model() {
  local m
  for m in "$@"; do
    if is_gguf "$m"; then echo "$m"; return 0; fi
    if [ -e "$m" ]; then say "файл $m повреждён или не GGUF — пропускаю" >&2; fi
  done
  return 1
}

main() {
  local profile source threads cpus ctx model reason
  local -a extra=() cmd=()
  early_boot_pause
  read -r profile source <<< "$(wait_profile)"
  case "$profile" in
    off)
      if [ "$source" = manual ]; then
        say "локальный ИИ выключен настройкой STELLA_POWER=off"
        say "чат работает: отвечают облачный или резервный ИИ. Включить снова: sudo stella power auto"
      else
        reason=$(json_str "$POWER_FILE" reason)
        say "локальный ИИ выключен сторожем питания${reason:+: $reason}"
        say "чат работает: отвечают облачный или резервный ИИ. Включить снова: sudo stella power reset"
      fi
      exit 0
      ;;
    safe)
      threads=1
      cpus=4
      ctx=1024
      extra=(--no-warmup)
      model=$(pick_model "$SMALL_MODEL" "$MAIN_MODEL")
      ;;
    *)
      profile=normal
      threads="${LLAMA_THREADS:-2}"
      cpus="${LLAMA_CPUS:-4,5}"
      ctx="${LLAMA_CTX:-2048}"
      in_range "$threads" 1 16 || { say "LLAMA_THREADS=$threads неверно — беру 2"; threads=2; }
      [[ "$cpus" =~ ^[0-9]+([,-][0-9]+)*$ ]] || { say "LLAMA_CPUS=$cpus неверно — беру 4,5"; cpus=4,5; }
      in_range "$ctx" 256 32768 || { say "LLAMA_CTX=$ctx неверно — беру 2048"; ctx=2048; }
      model=$(pick_model "$MAIN_MODEL" "$SMALL_MODEL")
      ;;
  esac
  if [ -z "$model" ]; then
    say "нет исправной модели ($SMALL_MODEL, $MAIN_MODEL) — локальный ИИ не запускаю"
    say "чат работает на облачном и резервном ИИ. Скачать модель: sudo stella update (нужен интернет)"
    exit 0
  fi
  if [ ! -x "$LLAMA_BIN" ]; then
    say "нет $LLAMA_BIN — llama.cpp не собрана, локальный ИИ не запускаю"
    say "чат работает на облачном и резервном ИИ. Собрать: sudo stella update (нужен интернет)"
    exit 0
  fi
  cmd=("$LLAMA_BIN" -m "$model" --host 127.0.0.1 --port 8081 -c "$ctx" -t "$threads" --parallel 1 "${extra[@]}")
  if [ -n "$TASKSET" ] && command -v "$TASKSET" >/dev/null 2>&1; then
    if "$TASKSET" -c "$cpus" true >/dev/null 2>&1; then
      cmd=("$TASKSET" -c "$cpus" "${cmd[@]}")
    else
      say "ядра $cpus недоступны на этой плате — запускаю без привязки к ядрам"
    fi
  else
    say "нет taskset — запускаю без привязки к ядрам"
  fi
  say "профиль $profile: модель $(basename "$model"), потоков $threads, ядра $cpus, контекст $ctx"
  exec "${cmd[@]}"
}

main "$@"
