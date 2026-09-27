#!/bin/bash

SYSFS="${STELLA_SYSFS_CPU:-/sys/devices/system/cpu}"
STATE_DIR="${STELLA_STATE_DIR:-/var/lib/stella}"
POWER_FILE="${STELLA_POWER_FILE:-$STATE_DIR/power.json}"
BOOT_ID_FILE="${STELLA_BOOT_ID_FILE:-/proc/sys/kernel/random/boot_id}"
BIG_CPU="${STELLA_BIG_CPU:-4}"
CAP_KHZ="${STELLA_CPU_MAX_KHZ:-1416000}"

say() { echo "stella-power: $*"; }

is_num() { [[ "$1" =~ ^[0-9]+$ ]]; }

json_str() {
  [ -r "$1" ] || return 1
  sed -n "/\"$2\"[[:space:]]*:/{s/.*\"$2\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p;q;}" "$1" 2>/dev/null
}

read_one() {
  local value=""
  [ -r "$1" ] && read -r value 2>/dev/null < "$1"
  echo "$value"
}

words() {
  local -a list=()
  [ -r "$1" ] && read -ra list 2>/dev/null < "$1"
  printf '%s\n' "${list[@]}"
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

resolve_profile() {
  local arg="$1" file manual
  case "$arg" in
    normal|safe|off) echo "$arg"; return ;;
    "") ;;
    *) say "неизвестный профиль «$arg» — беру безопасный safe" >&2; echo safe; return ;;
  esac
  file=$(file_profile)
  manual=$(printf '%s' "${STELLA_POWER:-auto}" | tr '[:upper:]' '[:lower:]')
  if [ -n "$file" ] && file_is_current; then echo "$file"; return; fi
  case "$manual" in normal|safe|off) echo "$manual"; return ;; esac
  if [ "$file" = off ]; then echo off; return; fi
  echo safe
}

big_policy() {
  local p c
  for p in "$SYSFS"/cpufreq/policy*; do
    [ -r "$p/related_cpus" ] || continue
    for c in $(words "$p/related_cpus"); do
      if [ "$c" = "$BIG_CPU" ]; then echo "$p"; return 0; fi
    done
  done
  for p in "$SYSFS/cpufreq/policy$BIG_CPU" "$SYSFS/cpu$BIG_CPU/cpufreq"; do
    if [ -d "$p" ]; then echo "$p"; return 0; fi
  done
  return 1
}

capped_freq() {
  local policy="$1" cap="$2" f best="" lowest="" max min
  for f in $(words "$policy/scaling_available_frequencies"); do
    is_num "$f" || continue
    if [ -z "$lowest" ] || [ "$f" -lt "$lowest" ]; then lowest="$f"; fi
    if [ "$f" -le "$cap" ] && { [ -z "$best" ] || [ "$f" -gt "$best" ]; }; then best="$f"; fi
  done
  if [ -n "$best" ]; then echo "$best"; return; fi
  if [ -n "$lowest" ]; then echo "$lowest"; return; fi
  max=$(read_one "$policy/cpuinfo_max_freq")
  min=$(read_one "$policy/cpuinfo_min_freq")
  if is_num "$max" && [ "$max" -lt "$cap" ]; then echo "$max"; return; fi
  if is_num "$min" && [ "$cap" -lt "$min" ]; then echo "$min"; return; fi
  echo "$cap"
}

full_freq() {
  local policy="$1" f best=""
  best=$(read_one "$policy/cpuinfo_max_freq")
  if is_num "$best"; then echo "$best"; return; fi
  best=""
  for f in $(words "$policy/scaling_available_frequencies"); do
    is_num "$f" || continue
    if [ -z "$best" ] || [ "$f" -gt "$best" ]; then best="$f"; fi
  done
  echo "$best"
}

mhz() {
  if is_num "$1"; then echo "$(( $1 / 1000 )) МГц"; else echo "?"; fi
}

main() {
  local profile policy target before after cpus
  if ! is_num "$CAP_KHZ" || [ "$CAP_KHZ" -lt 200000 ]; then CAP_KHZ=1416000; fi
  profile=$(resolve_profile "${1:-}")
  if ! policy=$(big_policy); then
    say "профиль $profile: управление частотой недоступно ($SYSFS/cpufreq) — пропускаю"
    return 0
  fi
  cpus=$(read_one "$policy/related_cpus")
  before=$(read_one "$policy/scaling_max_freq")
  if [ "$profile" = normal ]; then
    target=$(full_freq "$policy")
  else
    target=$(capped_freq "$policy" "$CAP_KHZ")
  fi
  if ! is_num "$target"; then
    say "профиль $profile: не удалось узнать частоты в $policy — пропускаю"
    return 0
  fi
  if [ "$before" = "$target" ]; then
    say "профиль $profile: большие ядра (${cpus:-CPU $BIG_CPU}) уже до $(mhz "$target")"
    return 0
  fi
  if ! { echo "$target" > "$policy/scaling_max_freq"; } 2>/dev/null; then
    say "профиль $profile: не могу записать $policy/scaling_max_freq (нужен root) — частота не изменена"
    return 0
  fi
  after=$(read_one "$policy/scaling_max_freq")
  if [ "$profile" = normal ]; then
    say "профиль normal: большие ядра (${cpus:-CPU $BIG_CPU}) на полной частоте $(mhz "${after:-$target}") (было $(mhz "$before"))"
  else
    say "профиль $profile: большие ядра (${cpus:-CPU $BIG_CPU}) ограничены до $(mhz "${after:-$target}") (было $(mhz "$before")) — бережём питание"
  fi
  return 0
}

main "$@"
exit 0
