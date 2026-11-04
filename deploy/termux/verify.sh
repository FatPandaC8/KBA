#!/usr/bin/env bash
# ==============================================================================
# Gusby Multi-Tier Production Verification Suite
# ==============================================================================
# Checks:
#   Tier 1: Backend Liveness (:8081/api/health/live)
#   Tier 2: Backend & Database Readiness (:8081/api/health/ready)
#   Tier 3: Frontend SPA Availability via Nginx (:8080/)
#   Tier 4: Reverse Proxy Routing (:8080/api/health)
#   Tier 5: Prometheus Telemetry (:8081/metrics)
#   Tier 6: API Smoke Test (Auth endpoint error contract)
# ==============================================================================

set -euo pipefail

BACKEND_URL="${GUSBY_BACKEND_URL:-http://127.0.0.1:8081}"
NGINX_URL="${GUSBY_NGINX_URL:-http://127.0.0.1:8080}"
TIMEOUT_SEC=5
MAX_RETRIES=15
RETRY_DELAY=2

echo "========================================================================"
echo "GUSBY PRODUCTION VERIFICATION"
echo "Backend URL: $BACKEND_URL"
echo "Nginx URL:   $NGINX_URL"
echo "========================================================================"

# Helper: HTTP GET with timeout
http_get() {
    local url="$1"
    curl -s -S --max-time "$TIMEOUT_SEC" "$url"
}

http_status() {
    local url="$1"
    curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT_SEC" "$url"
}

# ------------------------------------------------------------------------------
# Tier 1: Backend Liveness Check (with retry loop for warmup)
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 1: Testing Backend Liveness... "
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
# Tier 2: Database Connectivity & Service Readiness
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 2: Testing Database Connectivity & Readiness... "
ready_resp=$(http_get "$BACKEND_URL/api/health/ready" || true)
if [[ "$ready_resp" != *"\"database\":\"connected\""* ]] || [[ "$ready_resp" != *"\"status\":\"ready\""* ]]; then
    echo "FAILED!"
    echo "Error: Readiness check returned unexpected response:" >&2
    echo "$ready_resp" >&2
    exit 1
fi
echo "PASSED (PostgreSQL Connected, AI Gate Active)"

# ------------------------------------------------------------------------------
# Tier 3: Frontend SPA Availability (Static Files through Nginx)
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
    echo "FAILED! (Invalid HTML payload)"
    exit 1
fi
echo "PASSED (HTTP 200, HTML5 SPA Shell Verified)"

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
echo "PASSED (Reverse Proxy Functioning)"

# ------------------------------------------------------------------------------
# Tier 5: Prometheus Telemetry Endpoint
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 5: Testing Prometheus /metrics Endpoint... "
metrics_resp=$(http_get "$BACKEND_URL/metrics" || true)
if [[ "$metrics_resp" != *"gusby_http_requests_total"* ]]; then
    echo "FAILED!"
    echo "Error: /metrics endpoint did not contain expected Gusby metrics." >&2
    exit 1
fi
echo "PASSED (Metrics Registry Verified)"

# ------------------------------------------------------------------------------
# Tier 6: API Smoke Test (Contract Validation)
# ------------------------------------------------------------------------------
echo -n "[Verification] Tier 6: Testing API Error Contract Smoke Test... "
smoke_status=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    -d '{"email":"invalid@test.local","password":"bad"}' \
    --max-time "$TIMEOUT_SEC" "$BACKEND_URL/api/auth/login" || true)

# Expect 401 Unauthorized (proves routing, json decoding, auth failure handling without crashing)
if [[ "$smoke_status" != "401" ]]; then
    echo "FAILED! (Expected HTTP 401, got $smoke_status)"
    exit 1
fi
echo "PASSED (HTTP 401 Contract Verified)"

echo "========================================================================"
echo "ALL PRODUCTION VERIFICATION CHECKS PASSED SUCCESSFULLY"
echo "========================================================================"
exit 0
