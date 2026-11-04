#!/usr/bin/env bash
# ==============================================================================
# Gusby Production Deployment Script (Android Termux ARM64)
# ==============================================================================
# Simple, reliable, single-host deployment:
#   1. Acquire deployment lock & Android wake lock.
#   2. Validate required toolchains (go, node, npm, pm2, curl, jq).
#   3. Verify target commit passed GitHub Actions CI ('Gusby Production CI').
#   4. Compile Go backend binary to ~/services/gusby/bin/gusby.
#   5. Generate Nuxt 4 static frontend (npm ci + npm run generate).
#   6. Copy static frontend files to ~/services/gusby/frontend/.
#   7. Restart or start the 'gusby-backend' PM2 process.
#   8. Run read-only verification suite.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

SERVICE_DIR="${GUSBY_SERVICE_DIR:-$HOME/services/gusby}"
mkdir -p "$SERVICE_DIR/bin" "$SERVICE_DIR/frontend" "$SERVICE_DIR/logs"

# 1. Deployment lock (prevent concurrent executions)
LOCK_FILE="/tmp/gusby-deploy.lock"
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "Error: Another deployment is already in progress (locked on $LOCK_FILE)." >&2
    exit 1
fi

if command -v termux-wake-lock &> /dev/null; then
    termux-wake-lock || true
fi

cleanup() {
    local exit_code=$?
    if command -v termux-wake-unlock &> /dev/null; then
        termux-wake-unlock || true
    fi
    flock -u 200 2>/dev/null || true
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

echo "========================================================================"
echo "Gusby Production Deployment"
echo "Host:        $(uname -s) $(uname -m)"
echo "Service Dir: $SERVICE_DIR"
echo "Timestamp:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================================================"

# 2. Check required commands
for cmd in go node npm pm2 curl jq git; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "Error: Required command '$cmd' is not found in PATH." >&2
        exit 1
    fi
done

# Ensure production configuration exists
if [[ ! -f "$SERVICE_DIR/.env" ]]; then
    if [[ -f "$ROOT_DIR/.env" ]]; then
        echo "Notice: Initializing $SERVICE_DIR/.env from repository .env..."
        cp "$ROOT_DIR/.env" "$SERVICE_DIR/.env"
        chmod 600 "$SERVICE_DIR/.env"
    else
        echo "Error: Production configuration missing at $SERVICE_DIR/.env." >&2
        echo "Please create $SERVICE_DIR/.env with required production variables." >&2
        exit 1
    fi
fi

# Ensure database safety in .env
if grep -E "^(GUSBY_DATABASE_URL|DATABASE_URL)=.*server_lab" "$SERVICE_DIR/.env" &> /dev/null; then
    echo "CRITICAL SAFETY ERROR: $SERVICE_DIR/.env points to 'server_lab'! Refusing deployment." >&2
    exit 1
fi

# 3. Commit identification & GitHub Actions CI verification
TARGET_COMMIT="${1:-}"
REPO_NAME="FatPandaC8/KBA"
WORKFLOW_NAME="Gusby Production CI"

if [[ -z "$TARGET_COMMIT" ]]; then
    echo "[CI Gating] Finding latest CI-verified commit on main branch..."
    RUNS_JSON=$(curl -sSf -H "Accept: application/vnd.github.v3+json" --max-time 15 \
        "https://api.github.com/repos/$REPO_NAME/actions/runs?branch=main&status=completed&per_page=15" 2>/dev/null || true)

    TARGET_COMMIT=$(echo "$RUNS_JSON" | jq -r \
        '[.workflow_runs[] | select(.name == "'"$WORKFLOW_NAME"'" and .status == "completed" and .conclusion == "success")] | .[0].head_sha // empty' 2>/dev/null || true)

    if [[ -z "$TARGET_COMMIT" ]]; then
        echo "Error: No completed successful CI run found on 'main' for workflow '$WORKFLOW_NAME'." >&2
        exit 1
    fi
    echo "[CI Gating] Verified commit from main: $TARGET_COMMIT"
else
    echo "[CI Gating] Verifying requested commit $TARGET_COMMIT..."
    RUNS_JSON=$(curl -sSf -H "Accept: application/vnd.github.v3+json" --max-time 15 \
        "https://api.github.com/repos/$REPO_NAME/actions/runs?head_sha=$TARGET_COMMIT" 2>/dev/null || true)

    MATCH_COUNT=$(echo "$RUNS_JSON" | jq -r \
        '[.workflow_runs[] | select(.name == "'"$WORKFLOW_NAME"'" and .head_sha == "'"$TARGET_COMMIT"'" and .status == "completed" and .conclusion == "success")] | length' 2>/dev/null || echo "0")

    if [[ "$MATCH_COUNT" -eq 0 ]]; then
        echo "Error: Commit $TARGET_COMMIT has not passed required CI workflow '$WORKFLOW_NAME'." >&2
        exit 1
    fi
    echo "[CI Gating] Verified: '$WORKFLOW_NAME' passed for commit $TARGET_COMMIT."
fi

# Checkout the verified commit in git working tree if in git repo
if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree &> /dev/null; then
    CURRENT_HEAD=$(git -C "$ROOT_DIR" rev-parse HEAD)
    if [[ "$CURRENT_HEAD" != "$TARGET_COMMIT" ]]; then
        echo "[Git] Checking out verified commit $TARGET_COMMIT..."
        git -C "$ROOT_DIR" checkout -q "$TARGET_COMMIT"
    fi
fi

# 4. Compile Go backend binary
echo "[Build] Compiling Go backend binary for ARM64..."
(
    cd "$ROOT_DIR"
    CGO_ENABLED=0 go build \
        -ldflags="-s -w -X 'gusby/internal/config.GitCommit=$TARGET_COMMIT' -X 'gusby/internal/config.BuildTime=$(date -u +%Y-%m-%dT%H:%M:%SZ)'" \
        -o "$SERVICE_DIR/bin/gusby" ./cmd/gusby
    chmod +x "$SERVICE_DIR/bin/gusby"
)

# 5. Build static Nuxt frontend SPA
echo "[Build] Generating Nuxt static SPA..."
(
    cd "$ROOT_DIR/frontend"
    npm ci --prefer-offline --no-audit
    npm run generate
)

# 6. Copy frontend assets to production service directory
echo "[Deploy] Copying frontend static assets to $SERVICE_DIR/frontend..."
rm -rf "${SERVICE_DIR:?}/frontend"/*
cp -R "$ROOT_DIR/frontend/.output/public"/* "$SERVICE_DIR/frontend/"

# 7. Restart or start PM2 process
echo "[Process] Updating PM2 process 'gusby-backend'..."
if pm2 describe gusby-backend &> /dev/null; then
    pm2 restart gusby-backend
else
    pm2 start "$ROOT_DIR/ecosystem.config.cjs" --only gusby-backend
fi
pm2 save || true

# 8. Run deployment verification
echo "[Verification] Running read-only deployment verification..."
if [[ -x "$SCRIPT_DIR/verify.sh" ]]; then
    "$SCRIPT_DIR/verify.sh"
fi

echo "========================================================================"
echo "Gusby Deployment Completed Successfully"
echo "Commit:  ${TARGET_COMMIT:0:7} ($TARGET_COMMIT)"
echo "Backend: $SERVICE_DIR/bin/gusby"
echo "Static:  $SERVICE_DIR/frontend"
echo "========================================================================"
