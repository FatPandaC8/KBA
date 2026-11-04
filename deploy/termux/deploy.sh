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

# 1. Verify required tools
for cmd in go node npm pm2 curl jq git; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "Error: Required command '$cmd' is not found in PATH." >&2
        exit 1
    fi
done

# 2. Verify the production .env exists and has safe permissions
if [[ ! -f "$SERVICE_DIR/.env" ]]; then
    echo "Error: Production configuration missing at $SERVICE_DIR/.env." >&2
    echo "Deployment requires an existing production environment file ($SERVICE_DIR/.env)." >&2
    exit 1
fi

# Ensure safe permissions (deny group/world access)
ENV_PERMS=$(stat -c "%a" "$SERVICE_DIR/.env" 2>/dev/null || stat -f "%Lp" "$SERVICE_DIR/.env" 2>/dev/null || echo "")
if [[ -n "$ENV_PERMS" ]]; then
    # In octal notation, safe permissions for secrets have 0 for group and other (e.g. 600, 400)
    if [[ "$ENV_PERMS" =~ [1-7][0-7]$|[0-7][1-7]$ ]]; then
        echo "Notice: Restricting permissions on $SERVICE_DIR/.env to 600 (was $ENV_PERMS)..."
        chmod 600 "$SERVICE_DIR/.env" || {
            echo "Error: Insecure permissions ($ENV_PERMS) on $SERVICE_DIR/.env and failed to restrict to 600." >&2
            exit 1
        }
    fi
fi

# Ensure database safety in .env: Gusby must never point to 'server_lab'
if grep -E "^(GUSBY_DATABASE_URL|DATABASE_URL)=.*server_lab" "$SERVICE_DIR/.env" &> /dev/null; then
    echo "CRITICAL SAFETY ERROR: $SERVICE_DIR/.env points to 'server_lab'! Refusing deployment." >&2
    exit 1
fi

# Validate configured database name if explicitly set
CONFIGURED_EXPECTED_DB=$(grep -E "^GUSBY_EXPECTED_DB=" "$SERVICE_DIR/.env" | cut -d'=' -f2- | tr -d ' "' || true)
if [[ -n "$CONFIGURED_EXPECTED_DB" && "$CONFIGURED_EXPECTED_DB" != "gusby_db" ]]; then
    echo "CRITICAL SAFETY ERROR: GUSBY_EXPECTED_DB in $SERVICE_DIR/.env is '$CONFIGURED_EXPECTED_DB' (must be 'gusby_db')." >&2
    exit 1
fi

# 3. Verify the target commit passed the required GitHub Actions CI workflow
TARGET_COMMIT="${1:-}"
REPO_NAME="FatPandaC8/KBA"
WORKFLOW_NAME="Gusby Production CI"

AUTH_HEADER=()
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    AUTH_HEADER=(-H "Authorization: Bearer $GITHUB_TOKEN")
fi

if [[ -z "$TARGET_COMMIT" ]]; then
    echo "[CI Gating] Finding latest CI-verified commit on main branch..."
    RUNS_JSON=$(curl -sSf "${AUTH_HEADER[@]}" -H "Accept: application/vnd.github.v3+json" --max-time 15 \
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
    RUNS_JSON=$(curl -sSf "${AUTH_HEADER[@]}" -H "Accept: application/vnd.github.v3+json" --max-time 15 \
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

# 4. Build the Go backend for the Termux ARM64 host
echo "[Build] Compiling Go backend binary for ARM64..."
TMP_BIN="$ROOT_DIR/bin/gusby.build"
mkdir -p "$ROOT_DIR/bin"
(
    cd "$ROOT_DIR"
    CGO_ENABLED=0 go build \
        -ldflags="-s -w -X 'gusby/internal/config.GitCommit=$TARGET_COMMIT' -X 'gusby/internal/config.BuildTime=$(date -u +%Y-%m-%dT%H:%M:%SZ)'" \
        -o "$TMP_BIN" ./cmd/gusby
    chmod +x "$TMP_BIN"
)

# 5. Generate the Nuxt static frontend
echo "[Build] Generating Nuxt static SPA..."
(
    cd "$ROOT_DIR/frontend"
    npm ci --prefer-offline --no-audit
    npm run generate
)

# 6. Copy the generated frontend files into ~/services/gusby/frontend/
echo "[Deploy] Copying frontend static assets to $SERVICE_DIR/frontend..."
rm -rf "${SERVICE_DIR:?}/frontend"/*
cp -R "$ROOT_DIR/frontend/.output/public"/* "$SERVICE_DIR/frontend/"

# 7. Replace the backend binary in ~/services/gusby/bin/
echo "[Deploy] Replacing backend binary in $SERVICE_DIR/bin/gusby..."
mv -f "$TMP_BIN" "$SERVICE_DIR/bin/gusby"

# 8. Restart the existing PM2 backend process, or start it if it does not exist
echo "[Process] Updating PM2 process 'gusby-backend'..."
if pm2 describe gusby-backend &> /dev/null; then
    pm2 restart gusby-backend --update-env
else
    pm2 start "$ROOT_DIR/ecosystem.config.cjs" --only gusby-backend
fi
pm2 save || true

# 9. Run mandatory deployment verification
echo "[Verification] Running mandatory read-only deployment verification..."
VERIFY_SCRIPT="$SCRIPT_DIR/verify.sh"
if [[ ! -f "$VERIFY_SCRIPT" ]]; then
    echo "Error: Mandatory verification script missing at $VERIFY_SCRIPT." >&2
    exit 1
fi
if [[ ! -x "$VERIFY_SCRIPT" ]]; then
    echo "Error: Verification script at $VERIFY_SCRIPT is not executable." >&2
    exit 1
fi
"$VERIFY_SCRIPT"

# 10. Report the deployed commit
echo "========================================================================"
echo "Gusby Deployment Completed Successfully"
echo "Commit:  ${TARGET_COMMIT:0:7} ($TARGET_COMMIT)"
echo "Backend: $SERVICE_DIR/bin/gusby"
echo "Static:  $SERVICE_DIR/frontend"
echo "========================================================================"
