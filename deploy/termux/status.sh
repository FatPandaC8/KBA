#!/usr/bin/env bash
# ==============================================================================
# Gusby Service Status Inspector (Android Termux)
# ==============================================================================
# Checks:
#   1. PM2 process status (gusby-backend)
#   2. PostgreSQL database status (127.0.0.1:5432)
#   3. Nginx reverse proxy status (:8080)
#   4. Backend live endpoints (:8081/api/health/live, :8081/api/health/ready)
# ==============================================================================

set -euo pipefail

echo "=== Gusby System Status: $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# 1. PM2 Process Status
echo "--- [1] PM2 Process Manager ---"
if command -v pm2 &> /dev/null; then
    pm2 status gusby-backend || echo "gusby-backend not registered in PM2."
else
    echo "pm2 command not found in PATH."
fi
echo ""

# 2. PostgreSQL Status
echo "--- [2] PostgreSQL Service ---"
if command -v pg_isready &> /dev/null; then
    pg_isready -h 127.0.0.1 -p 5432 || true
else
    echo "pg_isready command not found in PATH."
fi
echo ""

# 3. Nginx Reverse Proxy
echo "--- [3] Nginx Process ---"
if ps aux | grep -v grep | grep -q "nginx: master process"; then
    echo "Nginx: RUNNING"
else
    echo "Nginx: NOT RUNNING"
fi
echo ""

# 4. Backend Health & Readiness Probes
echo "--- [4] HTTP Endpoints ---"
echo -n "Liveness  (:8081/api/health/live): "
curl -s -S --max-time 3 http://127.0.0.1:8081/api/health/live || echo "Unreachable"
echo ""
echo -n "Readiness (:8081/api/health/ready): "
curl -s -S --max-time 3 http://127.0.0.1:8081/api/health/ready || echo "Unreachable"
echo ""
echo "=========================================================="
