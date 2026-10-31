#!/usr/bin/env bash
# Development server launcher — one backend, one DB per environment.
# Usage: bash scripts/dev_server.sh
# - Loads .env from the repo root (GROQ_API_KEY stays server-side only)
# - Exits with clear error if ECHO_DB_PATH is not set
# - Launches uvicorn on 127.0.0.1:8000
# - Meant to be run on the dev machine only; emulator and physical devices
#   connect via 10.0.2.2 (emulator) or adb reverse (physical Android).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$ROOT/.env" ]; then
  # Export every KEY=VALUE line without echoing values. `set -a` makes the
  # shell export them to the server process only; the key never leaves it.
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

if [ -z "${ECHO_DB_PATH:-}" ]; then
  echo "ERROR: ECHO_DB_PATH must be set to a SQLite database path" >&2
  echo "Example: ECHO_DB_PATH=/path/to/dev.db bash $0" >&2
  exit 1
fi

export ECHO_ENV=development
export ECHO_DB_PATH="$ECHO_DB_PATH"
export ECHO_UPLOAD_DIR="${ECHO_UPLOAD_DIR:-/tmp/opencode/uploads}"
export ECHO_EMAIL_OUTBOX="${ECHO_EMAIL_OUTBOX:-/tmp/opencode/outbox}"

# Fail closed if Groq is selected without a key. Never print the value.
if [ "${ECHO_LLM_PROVIDER:-groq}" = "groq" ] && [ -z "${GROQ_API_KEY:-}" ]; then
  echo "ERROR: ECHO_LLM_PROVIDER=groq but GROQ_API_KEY is not set" >&2
  exit 1
fi

echo "Starting Echo dev backend with DB: $ECHO_DB_PATH"
echo "LLM provider: ${ECHO_LLM_PROVIDER:-groq} model: ${GROQ_MODEL:-openai/gpt-oss-120b}"
exec python3 -m uvicorn server.app.main:app --host 127.0.0.1 --port 8000
