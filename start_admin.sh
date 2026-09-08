#!/usr/bin/env bash
# Start Collig web (FastAPI + pre-built frontend).
# Uses the preferred port (default 5005); if in use, probes upward for a free port.
set -euo pipefail

cd "$(dirname "$0")"

PREFERRED_PORT="${PREFERRED_PORT:-5005}"
MAX_TRIES=100
PORT_FILE=~/.collig/console.port
PID_FILE=~/.collig/console.pid

port_is_free() {
  ! lsof -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1
}

find_free_port() {
  local start=$1
  local p=$start
  local tries=0
  while ! port_is_free "$p"; do
    p=$((p + 1))
    tries=$((tries + 1))
    if [ "$tries" -ge "$MAX_TRIES" ]; then
      echo "ERROR: no free TCP port found in range $start-$((start + MAX_TRIES - 1))" >&2
      exit 1
    fi
  done
  echo "$p"
}

mkdir -p ~/.collig

# Ensure frontend is built
if [ ! -d "frontend/dist" ]; then
  echo "Building frontend..."
  (cd frontend && npm run build)
fi

PORT="$(find_free_port "$PREFERRED_PORT")"

echo ""
echo "Starting Collig..."
if [ "$PORT" != "$PREFERRED_PORT" ]; then
  echo "  (port $PREFERRED_PORT was in use, picked $PORT instead)"
fi
echo "  UI:  http://localhost:$PORT/"
echo "  API:       http://localhost:$PORT/api/*"
echo "  Port file: $PORT_FILE"
echo ""

echo "$PORT" > "$PORT_FILE"

trap 'rm -f "$PORT_FILE" "$PID_FILE"' EXIT

uv run uvicorn core.main:app --host 0.0.0.0 --port "$PORT" --reload
