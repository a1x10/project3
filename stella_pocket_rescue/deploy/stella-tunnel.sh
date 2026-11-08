#!/bin/sh
# Обратный SSH-туннель на сервер: ДОМЕН_КОРОБКИ -> сервер -> 127.0.0.1:8088 на коробочке.
# Настройки пишет команда «stella remote pair» в /etc/stella/tunnel.env, ключ лежит в /etc/stella/tunnel.
set -eu
MODE="${1:-}"
DIR=/etc/stella/tunnel
KEY="$DIR/id_ed25519"
KNOWN="$DIR/known_hosts"

valid_host() { printf '%s' "$1" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$|^[0-9A-Fa-f:]{2,39}$'; }
valid_port() { printf '%s' "$1" | grep -Eq '^[0-9]{1,5}$' && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
valid_user() { printf '%s' "$1" | grep -Eq '^[a-z_][a-z0-9_-]{0,31}$'; }

HOST="${STELLA_TUNNEL_HOST:-}"
PORT="${STELLA_TUNNEL_PORT:-22}"
USER_NAME="${STELLA_TUNNEL_USER:-stella-tunnel}"
HTTP_PORT="${STELLA_TUNNEL_HTTP_PORT:-18080}"
SSH_PORT="${STELLA_TUNNEL_SSH_PORT:-18022}"

valid_host "$HOST" || { echo "stella-tunnel: не задан или неверен STELLA_TUNNEL_HOST (sudo stella remote pair)" >&2; exit 2; }
for p in "$PORT" "$HTTP_PORT" "$SSH_PORT"; do valid_port "$p" || { echo "stella-tunnel: неверный порт $p" >&2; exit 2; }; done
valid_user "$USER_NAME" || { echo "stella-tunnel: неверное имя пользователя на сервере" >&2; exit 2; }

set -- -i "$KEY" -p "$PORT" \
  -o UserKnownHostsFile="$KNOWN" -o GlobalKnownHostsFile=/dev/null -o StrictHostKeyChecking=yes \
  -o BatchMode=yes -o IdentitiesOnly=yes -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o ConnectTimeout=20 -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -o TCPKeepAlive=yes \
  -o ExitOnForwardFailure=yes -o LogLevel=ERROR

case "$MODE" in
  ping|reset|certs)
    exec ssh "$@" -T "$USER_NAME@$HOST" "$MODE"
    ;;
esac

FORWARD="-R 127.0.0.1:$HTTP_PORT:127.0.0.1:8088"
if [ "${STELLA_TUNNEL_SSH:-0}" = 1 ]; then
  FORWARD="$FORWARD -R 127.0.0.1:$SSH_PORT:127.0.0.1:22"
fi
# shellcheck disable=SC2086
exec ssh "$@" -N -T $FORWARD "$USER_NAME@$HOST"
