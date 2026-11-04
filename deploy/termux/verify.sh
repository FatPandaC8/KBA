#!/usr/bin/env bash
# ==============================================================================
# Gusby Read-Only Deployment Verification
# ==============================================================================
# Verifies:
#   1. PM2 process 'gusby-backend' is online
#   2. Backend liveness endpoint (:8081/api/health/live)
#   3. Backend readiness & database identity (:8081/api/health/ready)
#      - Verifies database is connected
#      - Verifies database is NOT 'server_lab'
#   4. Frontend static SPA served by Nginx (:8080/)
#   5. Nginx reverse proxy to API (:8080/api/health)
# ==============================================================================

set -euo pipefail

BACKEND_URL="${GUSBY_BACKEND_URL:-http://127.0.0.1:8081}"
NGINX_URL="${GUSBY_NGINX_URL:-http://127.0.0.1:8080}"
TIMEOUT_SEC=5
MAX_RETRIES=10
RETRY_DELAY=1

echo "Checking deployment health..."

# 1. PM2 Process Status
if command -v pm2 &> /dev/null; then
    if ! pm2 describe gusby-backend 2>/dev/null | grep -q "status.*online"; then
        echo "Error: PM2 process 'gusby-backend' is not online." >&2
        exit 1
    fi
    echo "[OK] PM2: 'gusby-backend' is running"
fi

# 2. Backend Liveness (with retry warmup)
live_ok=false
for _ in $(seq 1 $MAX_RETRIES); do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT_SEC" "$BACKEND_URL/api/health/live" || true)
    if [[ "$code" == "200" ]]; then
        live_ok=true
        break
    fi
    sleep "$RETRY_DELAY"
done

if [[ "$live_ok" != "true" ]]; then
    echo "Error: Backend failed to respond to $BACKEND_URL/api/health/live with HTTP 200." >&2
    exit 1
fi
echo "[OK] Backend: :8081/api/health/live returned HTTP 200"

# 3. Backend Readiness & Database Identity Check
ready_resp=$(curl -s -S --max-time "$TIMEOUT_SEC" "$BACKEND_URL/api/health/ready" || true)
if [[ "$ready_resp" != *"\"database\":\"connected\""* ]] || [[ "$ready_resp" != *"\"status\":\"ready\""* ]]; then
    echo "Error: Backend readiness check failed:" >&2
    echo "$ready_resp" >&2
    exit 1
fi

if [[ "$ready_resp" == *"server_lab"* ]]; then
    echo "CRITICAL ERROR: Backend is connected to 'server_lab'! Refusing verification." >&2
    exit 1
fi

EXPECTED_DB="${GUSBY_EXPECTED_DB:-gusby_db}"
if [[ "$ready_resp" != *"\"database_name\":\"$EXPECTED_DB\""* ]]; then
    echo "CRITICAL ERROR: Connected database does not match expected database '$EXPECTED_DB'!" >&2
    echo "$ready_resp" >&2
    exit 1
fi
echo "[OK] Database: Connected to '$EXPECTED_DB' (server_lab protected)"

# 4. Frontend SPA through Nginx (:8080/)
fe_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT_SEC" "$NGINX_URL/" || true)
if [[ "$fe_code" != "200" ]]; then
    echo "Error: Nginx failed to serve frontend at $NGINX_URL/ (HTTP $fe_code)." >&2
    exit 1
fi
echo "[OK] Frontend: Nginx served static SPA at $NGINX_URL/ with HTTP 200"

# 5. API Proxy through Nginx (:8080/api/health)
proxy_resp=$(curl -s -S --max-time "$TIMEOUT_SEC" "$NGINX_URL/api/health" || true)
if [[ "$proxy_resp" != *"\"service\":\"gusby\""* ]]; then
    echo "Error: Nginx reverse proxy to $NGINX_URL/api/health failed." >&2
    echo "$proxy_resp" >&2
    exit 1
fi
echo "[OK] API Proxy: Nginx forwarded /api/health to Go backend"

echo "=== All deployment verification checks passed ==="
