#!/usr/bin/env sh
set -eu
# Simple TCP wait helper for local scripts (Compose healthchecks are preferred).
HOST="${1:-127.0.0.1}"
PORT="${2:-5432}"
TIMEOUT="${3:-60}"
i=0
while [ "$i" -lt "$TIMEOUT" ]; do
  if nc -z "$HOST" "$PORT" >/dev/null 2>&1; then
    echo "$HOST:$PORT is ready"
    exit 0
  fi
  i=$((i + 1))
  sleep 1
done
echo "timeout waiting for $HOST:$PORT" >&2
exit 1
