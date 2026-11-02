#!/usr/bin/env bash
# Development server launcher — one backend, one DB per environment.
# Usage: bash scripts/dev_server.sh
# - Loads .env from the repo root (GROQ_API_KEY stays server-side only)
# - Requires DATABASE_URL for PostgreSQL 16 (there is no SQLite fallback)
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

export ECHO_ENV=development

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set. Copy .env.example to .env and configure the PostgreSQL URL." >&2
  exit 1
fi

# Fail closed if Groq is selected without a key. Never print the value.
if [ "${ECHO_LLM_PROVIDER:-groq}" = "groq" ] && [ -z "${GROQ_API_KEY:-}" ]; then
  echo "ERROR: ECHO_LLM_PROVIDER=groq but GROQ_API_KEY is not set" >&2
  exit 1
fi

echo "Starting Echo dev backend with PostgreSQL (DATABASE_URL configured)"
echo "LLM provider: ${ECHO_LLM_PROVIDER:-groq} model: ${GROQ_MODEL:-openai/gpt-oss-120b}"
exec python3 -m uvicorn server.app.main:app --host 127.0.0.1 --port 8000
