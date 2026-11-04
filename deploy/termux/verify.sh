#!/usr/bin/env bash
# ==============================================================================
# Gusby Read-Only Multi-Tier Production Verification Suite
# ==============================================================================
# Checks:
#   Tier 0: PM2 Process Status (gusby-backend is running)
#   Tier 1: Backend Liveness (:8081/api/health/live)
#   Tier 2: Backend Readiness & PostgreSQL Identity (:8081/api/health/ready)
#           - Verifies database is 'connected'
#           - Verifies database_name is NOT 'server_lab'
#   Tier 3: Frontend Static SPA via Nginx (:8080/)
#   Tier 4: Reverse Proxy Routing (:8080/api/health)
#   Tier 5: API Error Contract Smoke Test (:8081/api/auth/login returns 401)
#   Tier 6: Telemetry Endpoint (:8081/metrics)
#
# GUARANTEES:
#   - Strictly READ-ONLY: Never modifies DB, never runs DDL, never restarts services.
# ==============================================================================

set -euo pipefail

BACKEND_URL="${GUSBY_BACKEND_URL:-http://127.0.0.1:8081}"
NGINX_URL="${GUSBY_NGINX_URL:-http://127.0.0.1:8080}"
EXPECTED_DB="${GUSBY_EXPECTED_DB:-}"
TIMEOUT_SEC=5
MAX_RETRIES=15
RETRY_DELAY=2

echo "========================================================================"
echo "GUSBY READ-ONLY PRODUCTION VERIFICATION"
echo "Backend URL: $BACKEND_URL"
echo "Nginx URL:   $NGINX_URL"
echo "Timestamp:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================================================"

http_get() {
    local url="$1"
    curl -s -S --max-time "$TIMEOUT_SEC" "$url"
}

http_status() {
    local url="$1"
    curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT_SEC" "$url"
}

# ------------------------------------------------------------------------------
# Tier 0: PM2 Process Status
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 0: Checking PM2 'gusby-backend' process status... "
if command -v pm2 &> /dev/null; then
    PM2_DESC=$(pm2 describe gusby-backend 2>/dev/null || true)
    if [[ -z "$PM2_DESC" ]]; then
        echo "FAILED!"
        echo "Error: 'gusby-backend' process is not registered in PM2." >&2
        exit 1
    fi
    if echo "$PM2_DESC" | grep -q "status.*online"; then
        echo "PASSED (Process status: online)"
    else
        echo "WARNING: PM2 process registered but not in 'online' state. Continuing HTTP probes..."
    fi
else
    echo "SKIPPED (PM2 not in PATH)"
fi

# ------------------------------------------------------------------------------
# Tier 1: Backend Liveness Check (with warmup retry loop)
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 1: Testing Backend Liveness (:8081/api/health/live)... "
live_ok=false
for i in $(seq 1 $MAX_RETRIES); do
    code=$(http_status "$BACKEND_URL/api/health/live" || true)
    if [[ "$code" == "200" ]]; then
        live_ok=true
        break
    fi
    sleep "$RETRY_DELAY"
done

if [[ "$live_ok" != "true" ]]; then
    echo "FAILED!"
    echo "Error: Backend failed to respond with HTTP 200 to $BACKEND_URL/api/health/live after $MAX_RETRIES attempts." >&2
    exit 1
fi
echo "PASSED (HTTP 200)"

# ------------------------------------------------------------------------------
# Tier 2: Database Connectivity & Dedicated Identity Verification
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 2: Testing Database Connectivity & Database Identity... "
ready_resp=$(http_get "$BACKEND_URL/api/health/ready" || true)

if [[ "$ready_resp" != *"\"database\":\"connected\""* ]] || [[ "$ready_resp" != *"\"status\":\"ready\""* ]]; then
    echo "FAILED!"
    echo "Error: Readiness check returned unexpected response:" >&2
    echo "$ready_resp" >&2
    exit 1
fi

# Verify connected database is NOT server_lab
if [[ "$ready_resp" == *"server_lab"* ]]; then
    echo "CRITICAL FAILURE!"
    echo "CRITICAL ERROR: Backend readiness reports connected to 'server_lab'!" >&2
    echo "Gusby backend must never connect to server_lab." >&2
    exit 1
fi

# If EXPECTED_DB is set, ensure it matches
if [[ -n "$EXPECTED_DB" ]]; then
    if [[ "$ready_resp" != *"\"database_name\":\"$EXPECTED_DB\""* ]]; then
        echo "FAILED!"
        echo "Error: Backend connected to unexpected database (expected: $EXPECTED_DB)." >&2
        echo "$ready_resp" >&2
        exit 1
    fi
fi
echo "PASSED (PostgreSQL connected to dedicated database, server_lab protected)"

# ------------------------------------------------------------------------------
# Tier 3: Frontend Static SPA via Nginx (:8080)
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 3: Testing Frontend Static SPA via Nginx (:8080)... "
fe_status=$(http_status "$NGINX_URL/" || true)
if [[ "$fe_status" != "200" ]]; then
    echo "FAILED! (HTTP $fe_status)"
    echo "Error: Nginx failed to serve frontend index at $NGINX_URL/" >&2
    exit 1
fi

fe_body=$(http_get "$NGINX_URL/" || true)
if [[ "$fe_body" != *"<!DOCTYPE html>"* ]] && [[ "$fe_body" != *"__nuxt"* ]]; then
    echo "FAILED! (Payload does not resemble Nuxt static SPA)" >&2
    exit 1
fi
echo "PASSED (HTTP 200, Nuxt Static SPA Shell Verified)"

# ------------------------------------------------------------------------------
# Tier 4: Nginx Reverse Proxy Routing to Backend (/api/)
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 4: Testing Nginx API Reverse Proxy Routing... "
proxy_resp=$(http_get "$NGINX_URL/api/health" || true)
if [[ "$proxy_resp" != *"\"service\":\"gusby\""* ]]; then
    echo "FAILED!"
    echo "Error: Nginx did not route /api/health correctly to Go backend." >&2
    echo "$proxy_resp" >&2
    exit 1
fi
echo "PASSED (Reverse Proxy routing functional)"

# ------------------------------------------------------------------------------
# Tier 5: API Error Contract Smoke Test (Read-Only)
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 5: Testing API Error Contract Smoke Test... "
smoke_status=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    -d '{"email":"invalid_probe@test.local","password":"wrong_password"}' \
    --max-time "$TIMEOUT_SEC" "$BACKEND_URL/api/auth/login" || true)

if [[ "$smoke_status" != "401" ]]; then
    echo "FAILED! (Expected HTTP 401, got $smoke_status)"
    exit 1
fi
echo "PASSED (HTTP 401 Auth Contract Verified, No DB Mutation)"

# ------------------------------------------------------------------------------
# Tier 6: Prometheus Telemetry Endpoint
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 6: Testing Prometheus /metrics Endpoint... "
metrics_resp=$(http_get "$BACKEND_URL/metrics" || true)
if [[ "$metrics_resp" != *"gusby_http_requests_total"* ]]; then
    echo "FAILED!"
    echo "Error: /metrics endpoint did not contain expected Gusby telemetry." >&2
    exit 1
fi
echo "PASSED (Metrics Registry Verified)"

echo "========================================================================"
echo "ALL READ-ONLY PRODUCTION VERIFICATION CHECKS PASSED SUCCESSFULLY"
echo "========================================================================"
exit 0
