#!/usr/bin/env bash
# One-command dev environment for device testing.
#
# Usage:
#   bash scripts/dev_device_up.sh
#   DATABASE_URL=postgresql://... bash scripts/dev_device_up.sh
#
# Prerequisites:
#   - An Android device/emulator is visible to `adb devices`
#
# What it does:
#   1. Starts the dev backend when /api/health is not already available
#   2. Installs `adb reverse tcp:8000 tcp:8000` so the physical device can
#      reach the dev backend at 127.0.0.1:8000 (127.0.0.1 inside the device
#      is the device itself, not the host)
#   3. Prints `adb reverse --list` so you can confirm the mapping
#
# The adb reverse mapping is lost when the USB cable is unplugged or the adb
# server restarts — re-run this script before each device session.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

export ECHO_ENV=development

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set. Copy .env.example to .env and configure PostgreSQL." >&2
  exit 1
fi

if ! command -v adb >/dev/null 2>&1; then
  echo "ERROR: adb is not on PATH (Android platform-tools)" >&2
  exit 1
fi

health_check() {
  curl -fsS --connect-timeout 1 --max-time 3 http://127.0.0.1:8000/api/health 2>/dev/null
}

echo "[1/3] Backend health check at http://127.0.0.1:8000/api/health"
health="$(health_check || true)"
if [ -z "$health" ]; then
  server_log="${TMPDIR:-/tmp}/echo-dev-server.log"
  echo "   Backend is not running; starting scripts/dev_server.sh"
  nohup bash "$ROOT/scripts/dev_server.sh" >"$server_log" 2>&1 &
  server_pid=$!
  health=""
  for _ in $(seq 1 30); do
    health="$(health_check || true)"
    [ -n "$health" ] && break
    if ! kill -0 "$server_pid" 2>/dev/null; then
      echo "ERROR: backend exited before becoming healthy" >&2
      tail -20 "$server_log" >&2 || true
      exit 1
    fi
    sleep 1
  done
  if [ -z "$health" ]; then
    echo "ERROR: backend did not become healthy within 30 seconds" >&2
    echo "Backend log: $server_log" >&2
    exit 1
  fi
fi
echo "   $health"

echo "[2/3] adb devices"
device_list="$(adb devices | awk '$2 == "device" {print $1}')"
if [ -z "$device_list" ]; then
  echo "ERROR: no authorized Android device is available" >&2
  adb devices >&2
  exit 1
fi
device_count="$(printf '%s\n' "$device_list" | wc -l | tr -d ' ')"
if [ "$device_count" -ne 1 ]; then
  echo "ERROR: exactly one authorized Android device is required" >&2
  printf '%s\n' "$device_list" >&2
  exit 1
fi
printf '%s\n' "$device_list"

echo "[3/3] adb reverse tcp:8000 tcp:8000"
adb reverse tcp:8000 tcp:8000

echo "--- adb reverse --list ---"
adb reverse --list

echo
echo "Device dev environment is ready. Point the app at http://127.0.0.1:8000"
echo "(the mapping only applies while this adb session and the cable persist)."
