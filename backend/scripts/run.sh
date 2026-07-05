#!/usr/bin/env bash
# Run the Lattice backend, killing anything already on the port first.
# Usage: bash scripts/run.sh [--port 8020]
set -euo pipefail

PORT=8020
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

cd "$(dirname "$0")/.."

PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
if [[ -n "$PIDS" ]]; then
  echo "Port $PORT in use by PID(s): $PIDS — killing…"
  kill $PIDS 2>/dev/null || true
  sleep 1
  PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
  if [[ -n "$PIDS" ]]; then
    kill -9 $PIDS 2>/dev/null || true
    sleep 1
  fi
fi

if [[ -z "${VIRTUAL_ENV:-}" && -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi

echo "Starting Lattice backend on port ${PORT}…"
exec python3 -m uvicorn app.main:app --reload --port "$PORT"
