#!/usr/bin/env bash
# Start the API and the dashboard together. Ctrl+C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/.env" ] || { echo "No .env yet: run 'make setup' (or python3 scripts/setup.py)"; exit 1; }
trap 'kill 0' EXIT
( cd "$ROOT/services/api" && .venv/bin/python -m stark.main ) &
( cd "$ROOT/apps/web" && npm run dev ) &
echo "STARK OS: dashboard http://localhost:3000  ·  API http://127.0.0.1:8000"
wait
