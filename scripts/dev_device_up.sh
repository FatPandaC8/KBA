#!/usr/bin/env bash
# One-command dev environment for device testing.
#
# Usage:
#   ECHO_DB_PATH=/path/to/dev.db bash scripts/dev_device_up.sh
#
# Prerequisites:
#   - ECHO_DB_PATH points at the single dev SQLite DB (one DB per environment)
#   - An Android device/emulator is visible to `adb devices`
#
# What it does:
#   1. Confirms the FastAPI backend answers /api/health on the host
#   2. Installs `adb reverse tcp:8000 tcp:8000` so the physical device can
#      reach the dev backend at 127.0.0.1:8000 (127.0.0.1 inside the device
#      is the device itself, not the host)
#   3. Prints `adb reverse --list` so you can confirm the mapping
#
# The adb reverse mapping is lost when the USB cable is unplugged or the adb
# server restarts — re-run this script before each device session.
set -euo pipefail

if [ -z "${ECHO_DB_PATH:-}" ]; then
  echo "ERROR: ECHO_DB_PATH must be set to the dev SQLite database path" >&2
  echo "Example: ECHO_DB_PATH=/home/guts/P2/KBA/server/echo_backend.db bash $0" >&2
  exit 1
fi

if ! command -v adb >/dev/null 2>&1; then
  echo "ERROR: adb is not on PATH (Android platform-tools)" >&2
  exit 1
fi

echo "[1/3] Backend health check at http://127.0.0.1:8000/api/health"
health="$(curl -fsS http://127.0.0.1:8000/api/health 2>/dev/null)" || {
  echo "ERROR: backend is not reachable at http://127.0.0.1:8000/api/health" >&2
  echo "Start it first: ECHO_DB_PATH=$ECHO_DB_PATH bash scripts/dev_server.sh" >&2
  exit 1
}
echo "   $health"

echo "[2/3] adb devices"
adb devices

echo "[3/3] adb reverse tcp:8000 tcp:8000"
adb reverse tcp:8000 tcp:8000

echo "--- adb reverse --list ---"
adb reverse --list

echo
echo "Device dev environment is ready. Point the app at http://127.0.0.1:8000"
echo "(the mapping only applies while this adb session and the cable persist)."
