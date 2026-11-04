#!/usr/bin/env bash
# ==============================================================================
# Gusby Production Status Inspector (Android Termux ARM64)
# ==============================================================================
# Inspects:
#   - Active Release & Git Commit
#   - PM2 Process Status (gusby-backend)
#   - Database Status (PostgreSQL loopback)
#   - Reverse Proxy Status (Nginx :8080)
#   - Live Health & Readiness Responses
#   - Recent Deployment History
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

DEPLOY_ROOT="${GUSBY_DEPLOY_ROOT:-$ROOT_DIR}"
STATE_DIR="$DEPLOY_ROOT/state"
ACTIVE_FILE="$STATE_DIR/active-release.json"
HISTORY_LOG="$STATE_DIR/deployment-history.json.log"

echo "========================================================================"
echo "GUSBY PRODUCTION SYSTEM STATUS"
echo "Host: $(uname -s) $(uname -m) (Termux/ARM64)"
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================================================"

# 1. Active Release Information
echo "--- [1] ACTIVE RELEASE METADATA ---"
if [[ -f "$ACTIVE_FILE" ]]; then
    cat "$ACTIVE_FILE"
else
    echo "No active release recorded in $ACTIVE_FILE."
    if [[ -L "$DEPLOY_ROOT/current" ]]; then
        echo "Current symlink points to: $(readlink -f "$DEPLOY_ROOT/current")"
    fi
fi
echo ""

# 2. PM2 Process Status
echo "--- [2] PM2 APPLICATION PROCESS MANAGER ---"
if command -v pm2 &> /dev/null; then
    pm2 status gusby-backend || echo "gusby-backend process not registered in PM2."
else
    echo "PM2 is not installed or not in PATH."
fi
echo ""

# 3. PostgreSQL Database Status
echo "--- [3] POSTGRESQL DATABASE STATUS ---"
if command -v pg_isready &> /dev/null; then
    pg_isready -h 127.0.0.1 -p 5432 || true
elif docker ps --format '{{.Names}}' 2>/dev/null | grep -q "kba-postgres"; then
    docker exec kba-postgres pg_isready -U echo -d echo_kb || true
else
    echo "Could not check pg_isready."
fi
echo ""

# 4. Nginx Reverse Proxy Status
echo "--- [4] NGINX REVERSE PROXY STATUS ---"
if command -v nginx &> /dev/null; then
    if ps aux | grep -v grep | grep -q "nginx: master process"; then
        echo "Nginx master process: RUNNING"
    else
        echo "Nginx master process: NOT RUNNING"
    fi
fi
echo ""

# 5. Live Health & Readiness Responses
echo "--- [5] APPLICATION HEALTH & READINESS ENDPOINTS ---"
echo "Liveness  (:8081/api/health/live):"
curl -s -S --max-time 3 http://127.0.0.1:8081/api/health/live || echo "Unreachable"
echo ""
echo "Readiness (:8081/api/health/ready):"
curl -s -S --max-time 3 http://127.0.0.1:8081/api/health/ready || echo "Unreachable"
echo ""
echo ""

# 6. Recent Deployment History
echo "--- [6] RECENT DEPLOYMENT AUDIT LOG ---"
if [[ -f "$HISTORY_LOG" ]]; then
    tail -n 5 "$HISTORY_LOG"
else
    echo "No deployment history log found."
fi
echo "========================================================================"
