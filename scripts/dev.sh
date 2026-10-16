#!/usr/bin/env bash
# Start the API and the dashboard together. Ctrl+C stops both.
# Ports come from .env: STARK_WEB_PORT (dashboard, default 3000) and STARK_PORT (API, default 8000).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/.env" ] || { echo "No .env yet: run 'make setup' (or python3 scripts/setup.py)"; exit 1; }

# read one KEY=value from .env without executing it
env_get() { grep -E "^$1=" "$ROOT/.env" | tail -n1 | cut -d= -f2- | tr -d '"'"'"' ' || true; }
WEB_PORT="${STARK_WEB_PORT:-$(env_get STARK_WEB_PORT)}"; WEB_PORT="${WEB_PORT:-3000}"
API_PORT="${STARK_PORT:-$(env_get STARK_PORT)}"; API_PORT="${API_PORT:-8000}"
case "$WEB_PORT$API_PORT" in *[!0-9]*) echo "STARK_WEB_PORT and STARK_PORT must be numbers"; exit 1;; esac

for p in "$WEB_PORT" "$API_PORT"; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null; then
    echo "Port $p is already in use by another program. Set STARK_WEB_PORT / STARK_PORT in .env to free ports."
    exit 1
  fi
done

export STARK_PORT="$API_PORT"
export STARK_WEB_ORIGIN="http://localhost:$WEB_PORT"  # the API only accepts the dashboard on this port
export NEXT_PUBLIC_STARK_API_URL="http://127.0.0.1:$API_PORT"

[ -x "$ROOT/services/api/.venv/bin/python" ] || { echo "API not installed yet: run 'make setup' first"; exit 1; }
[ -d "$ROOT/apps/web/node_modules" ] || { echo "Dashboard not installed yet: run 'make setup' first"; exit 1; }

trap 'kill 0' EXIT
( cd "$ROOT/services/api" && .venv/bin/python -m stark.main ) &
( cd "$ROOT/apps/web" && npx next dev -H 127.0.0.1 -p "$WEB_PORT" ) &
for _ in $(seq 1 40); do  # wait until the API answers, so a startup error is visible right away
  curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done
if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then
  echo "STARK OS ready: open http://localhost:$WEB_PORT  (API http://127.0.0.1:$API_PORT)"
else
  echo "The API did not start on port $API_PORT. See the error above, or run: make api"
fi
wait
