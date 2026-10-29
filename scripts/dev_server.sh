#!/usr/bin/env bash
# Development server launcher — one backend, one DB per environment.
# Usage: bash scripts/dev_server.sh
# - Exits with clear error if ECHO_DB_PATH is not set
# - Exports all ECHO_* env vars the Flutter app expects
# - Launches uvicorn on 127.0.0.1:8000
# - Meant to be run on the dev machine only; emulator and physical devices
#   connect via 10.0.2.2 (emulator) or adb reverse (physical Android).

set -euo pipefail

if [ -z "${ECHO_DB_PATH:-}" ]; then
  echo "ERROR: ECHO_DB_PATH must be set to a SQLite database path" >&2
  echo "Example: ECHO_DB_PATH=/path/to/dev.db bash $0" >&2
  exit 1
fi

export ECHO_ENV=development
export ECHO_DB_PATH="$ECHO_DB_PATH"
export ECHO_UPLOAD_DIR="${ECHO_UPLOAD_DIR:-/tmp/opencode/uploads}"
export ECHO_EMAIL_OUTBOX="${ECHO_EMAIL_OUTBOX:-/tmp/opencode/outbox}"

echo "Starting Echo dev backend with DB: $ECHO_DB_PATH"
exec python3 -m uvicorn server.app.main:app --host 127.0.0.1 --port 8000