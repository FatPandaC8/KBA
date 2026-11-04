#!/usr/bin/env bash
# ==============================================================================
# Gusby Application Production Deployment Automation (Android Termux ARM64)
# ==============================================================================
# Application Deployment Lifecycle:
#   1. Acquire deployment mutex lock & Termux wake lock.
#   2. Validate deployment environment and required toolchains.
#   3. Discover or validate target Git commit SHA against GitHub Actions CI.
#      Strict gating: ONLY commits with 'completed' & 'success' runs of
#      'Gusby Production CI' are eligible for deployment. No bypass flag.
#   4. Check idempotency: exit cleanly if commit is already active.
#   5. Extract exact commit source tree into release directory.
#   6. Build Go backend binary for ARM64 with metadata flags.
#   7. Build Nuxt 4 static SPA production bundle (npm ci + npm run generate).
#   8. Validate pre-deployment build integrity.
#   9. Activate new release atomically via 'current' symlink (preserving 'previous').
#   10. Restart PM2 'gusby-backend' process (never 'pm2 restart all').
#   11. Execute read-only multi-tier production verification suite.
#   12. Trigger automated application rollback if verification fails.
#   13. Prune old releases (retaining last 3 releases to protect device storage).
#   14. Record deployment metadata and audit log.
#
# CRITICAL ARCHITECTURAL DECISIONS:
#   - Database lifecycle is independent: NEVER runs migrations or touches PostgreSQL.
#   - Database 'server_lab' is strictly protected.
#   - Production runtime lives at ~/services/gusby, separate from ~/apps/gusby repo.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

DEPLOY_ROOT="${GUSBY_DEPLOY_ROOT:-$HOME/services/gusby}"
RELEASES_DIR="$DEPLOY_ROOT/releases"
SHARED_DIR="$DEPLOY_ROOT/shared"
STATE_DIR="$DEPLOY_ROOT/state"
CURRENT_LINK="$DEPLOY_ROOT/current"
PREVIOUS_LINK="$DEPLOY_ROOT/previous"
LOCK_FILE="/tmp/gusby-deploy.lock"

mkdir -p "$RELEASES_DIR" "$SHARED_DIR" "$STATE_DIR" "$SHARED_DIR/logs"

# ------------------------------------------------------------------------------
# 1. Mutex Locking & Android Wake Lock
# ------------------------------------------------------------------------------
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "Error: Another deployment is already in progress (Locked on $LOCK_FILE)." >&2
    exit 1
fi

if command -v termux-wake-lock &> /dev/null; then
    echo "[Deployment] Acquiring Termux Wake Lock..."
    termux-wake-lock || true
fi

cleanup() {
    local exit_code=$?
    if command -v termux-wake-unlock &> /dev/null; then
        echo "[Deployment] Releasing Termux Wake Lock..."
        termux-wake-unlock || true
    fi
    flock -u 200 2>/dev/null || true
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

echo "========================================================================"
echo "GUSBY PRODUCTION APPLICATION DEPLOYMENT"
echo "Host:        $(uname -s) $(uname -m) (Android Termux ARM64)"
echo "Source Repo: $ROOT_DIR"
echo "Deploy Root: $DEPLOY_ROOT"
echo "Timestamp:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================================================"

# ------------------------------------------------------------------------------
# 2. Validate Required Runtime Dependencies
# ------------------------------------------------------------------------------
echo "[Deployment] Validating required toolchains and utilities..."
for cmd in go node npm pm2 curl jq tar gzip git; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "Error: Required command '$cmd' is not found in PATH." >&2
        exit 1
    fi
done

# Ensure shared .env exists outside release directories
SHARED_ENV="$SHARED_DIR/.env"
if [[ ! -f "$SHARED_ENV" ]]; then
    if [[ -f "$ROOT_DIR/.env" ]]; then
        echo "[Deployment] Initializing shared .env from repository working copy..."
        cp "$ROOT_DIR/.env" "$SHARED_ENV"
        chmod 600 "$SHARED_ENV"
    else
        echo "Error: Production environment configuration missing at $SHARED_ENV" >&2
        echo "Please create $SHARED_ENV before deploying." >&2
        exit 1
    fi
fi

# Ensure database safety in shared .env
if grep -E "^(GUSBY_DATABASE_URL|DATABASE_URL)=.*server_lab" "$SHARED_ENV" &> /dev/null; then
    echo "CRITICAL SAFETY ERROR: $SHARED_ENV specifies 'server_lab'! Refusing deployment." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# 3. Identify Commit SHA & Enforce CI Gating
# ------------------------------------------------------------------------------
TARGET_COMMIT=""
for arg in "$@"; do
    if [[ "$arg" != --* ]] && [[ -z "$TARGET_COMMIT" ]]; then
        TARGET_COMMIT="$arg"
    fi
done

# Determine GitHub repository for CI API check
REPO_NAME="${GUSBY_GITHUB_REPO:-}"
if [[ -z "$REPO_NAME" ]]; then
    if git -C "$ROOT_DIR" remote get-url origin &> /dev/null; then
        ORIGIN_URL=$(git -C "$ROOT_DIR" remote get-url origin)
        REPO_NAME=$(echo "$ORIGIN_URL" | sed -E 's/.*github\.com[:\/]([^\/]+\/[^\/\.]+)(\.git)?/\1/')
    fi
fi
REPO_NAME="${REPO_NAME:-FatPandaC8/KBA}"
CI_WORKFLOW_NAME="Gusby Production CI"

if [[ -z "$TARGET_COMMIT" ]]; then
    echo "[Deployment] Querying GitHub Actions for latest verified commit on main branch..."
    API_RESP=$(curl -sSf -H "Accept: application/vnd.github.v3+json" --max-time 15 \
        "https://api.github.com/repos/$REPO_NAME/actions/runs?branch=main&status=completed&per_page=20" 2>/dev/null || true)

    if [[ -n "$API_RESP" ]]; then
        TARGET_COMMIT=$(echo "$API_RESP" | jq -r \
            '[.workflow_runs[] | select(.name == "'"$CI_WORKFLOW_NAME"'" and .status == "completed" and .conclusion == "success")] | .[0].head_sha // empty' 2>/dev/null || true)
    fi

    if [[ -z "$TARGET_COMMIT" || "$TARGET_COMMIT" == "null" ]]; then
        echo "========================================================================" >&2
        echo "DEPLOYMENT GATING ERROR: No CI-verified commit found on 'main' branch." >&2
        echo "A commit must have a completed, successful '$CI_WORKFLOW_NAME' run." >&2
        echo "Check GitHub Actions: https://github.com/$REPO_NAME/actions" >&2
        echo "========================================================================" >&2
        exit 1
    fi
    echo "[Deployment] Discovered latest passing CI commit: $TARGET_COMMIT"
else
    echo "[Deployment] Target commit explicitly requested: $TARGET_COMMIT"
    echo "[Deployment] Verifying CI workflow completion for commit $TARGET_COMMIT..."

    RUNS_JSON=$(curl -sSf -H "Accept: application/vnd.github.v3+json" --max-time 15 \
        "https://api.github.com/repos/$REPO_NAME/actions/runs?head_sha=$TARGET_COMMIT" 2>/dev/null || true)

    CI_VERIFIED="false"
    if [[ -n "$RUNS_JSON" ]]; then
        MATCHING_RUNS=$(echo "$RUNS_JSON" | jq -r \
            '[.workflow_runs[] | select(.name == "'"$CI_WORKFLOW_NAME"'" and .head_sha == "'"$TARGET_COMMIT"'" and .status == "completed" and .conclusion == "success")] | length' 2>/dev/null || echo "0")
        if [[ "$MATCHING_RUNS" -gt 0 ]]; then
            CI_VERIFIED="true"
        fi
    fi

    if [[ "$CI_VERIFIED" != "true" ]]; then
        echo "========================================================================" >&2
        echo "DEPLOYMENT GATING VIOLATION: Commit $TARGET_COMMIT has not passed CI!" >&2
        echo "Gusby requires workflow '$CI_WORKFLOW_NAME' with status 'completed' and conclusion 'success'." >&2
        echo "Refusing to deploy unverified, pending, or failing commit." >&2
        echo "========================================================================" >&2
        exit 1
    fi
    echo "[Deployment] CI verification confirmed: '$CI_WORKFLOW_NAME' passed."
fi

SHORT_SHA="${TARGET_COMMIT:0:7}"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%SZ)
RELEASE_ID="release-${SHORT_SHA}-${TIMESTAMP}"
RELEASE_DIR="$RELEASES_DIR/$RELEASE_ID"

# ------------------------------------------------------------------------------
# 4. Check Idempotency
# ------------------------------------------------------------------------------
echo "[Deployment] Checking active deployment status..."
if [[ -L "$CURRENT_LINK" ]] && [[ -f "$CURRENT_LINK/release-metadata.json" ]]; then
    CURRENT_ACTIVE_SHA=$(jq -r '.commit_sha // empty' "$CURRENT_LINK/release-metadata.json" 2>/dev/null || true)
    if [[ "$CURRENT_ACTIVE_SHA" == "$TARGET_COMMIT" ]]; then
        echo "Notice: Commit $TARGET_COMMIT ($SHORT_SHA) is already actively deployed at $(readlink -f "$CURRENT_LINK")."
        echo "Exiting deployment (idempotent no-op)."
        exit 0
    fi
fi

# ------------------------------------------------------------------------------
# 5. Extract Exact Commit Source Tree
# ------------------------------------------------------------------------------
echo "[Deployment] Extracting source archive for commit $SHORT_SHA into $RELEASE_DIR..."
mkdir -p "$RELEASE_DIR"

if ! git -C "$ROOT_DIR" archive "$TARGET_COMMIT" | tar -x -C "$RELEASE_DIR"; then
    echo "Error: Failed to extract git archive for commit $TARGET_COMMIT from $ROOT_DIR." >&2
    echo "Make sure the commit is fetched in local git repository: git fetch origin main" >&2
    rm -rf "$RELEASE_DIR"
    exit 1
fi

# Link shared environment file into release
ln -sf "$SHARED_ENV" "$RELEASE_DIR/.env"

# ------------------------------------------------------------------------------
# 6. Build Backend and Frontend for Android ARM64
# ------------------------------------------------------------------------------
echo "[Deployment] Compiling Go backend binary for ARM64..."
(
    cd "$RELEASE_DIR"
    mkdir -p bin
    CGO_ENABLED=0 go build \
        -ldflags="-s -w -X 'gusby/internal/config.AppVersion=$RELEASE_ID' -X 'gusby/internal/config.GitCommit=$TARGET_COMMIT' -X 'gusby/internal/config.BuildTime=$(date -u +%Y-%m-%dT%H:%M:%SZ)'" \
        -o bin/gusby ./cmd/gusby
    chmod +x bin/gusby
)

echo "[Deployment] Generating Nuxt 4 static SPA production bundle..."
(
    cd "$RELEASE_DIR/frontend"
    npm ci --prefer-offline --no-audit
    npm run generate
)

# ------------------------------------------------------------------------------
# 7. Validate Pre-Deployment Build Artifacts
# ------------------------------------------------------------------------------
echo "[Deployment] Validating build artifacts..."
if [[ ! -x "$RELEASE_DIR/bin/gusby" ]]; then
    echo "Error: Missing Go backend executable at $RELEASE_DIR/bin/gusby" >&2
    rm -rf "$RELEASE_DIR"
    exit 1
fi

if [[ ! -f "$RELEASE_DIR/frontend/.output/public/index.html" ]]; then
    echo "Error: Missing frontend static SPA at $RELEASE_DIR/frontend/.output/public/index.html" >&2
    rm -rf "$RELEASE_DIR"
    exit 1
fi

# Write release metadata
cat <<EOF > "$RELEASE_DIR/release-metadata.json"
{
  "release_id": "$RELEASE_ID",
  "commit_sha": "$TARGET_COMMIT",
  "short_sha": "$SHORT_SHA",
  "deployed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "host": "$(uname -n)",
  "arch": "$(uname -m)"
}
EOF

# ------------------------------------------------------------------------------
# 8. Atomically Activate New Release
# ------------------------------------------------------------------------------
echo "[Deployment] Activating release $RELEASE_ID..."
if [[ -L "$CURRENT_LINK" ]]; then
    OLD_CURRENT=$(readlink -f "$CURRENT_LINK" || true)
    if [[ -n "$OLD_CURRENT" && -d "$OLD_CURRENT" ]]; then
        ln -sfn "$OLD_CURRENT" "$PREVIOUS_LINK"
        echo "[Deployment] Preserved previous release link: $OLD_CURRENT"
    fi
fi

# Atomic symlink swap
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK.tmp"
mv -Tf "$CURRENT_LINK.tmp" "$CURRENT_LINK"
echo "[Deployment] 'current' symlink now points to $RELEASE_DIR"

# ------------------------------------------------------------------------------
# 9. Restart Backend via PM2
# ------------------------------------------------------------------------------
echo "[Deployment] Restarting 'gusby-backend' in PM2..."
if pm2 describe gusby-backend &> /dev/null; then
    pm2 restart gusby-backend
else
    echo "[Deployment] Registering 'gusby-backend' with PM2..."
    pm2 start "$CURRENT_LINK/ecosystem.config.cjs" --only gusby-backend
fi
pm2 save || true

# ------------------------------------------------------------------------------
# 10. Run Read-Only Production Verification Suite
# ------------------------------------------------------------------------------
echo "[Deployment] Executing production verification suite..."
chmod +x "$CURRENT_LINK/deploy/termux/verify.sh"

VERIFY_SUCCESS=false
if "$CURRENT_LINK/deploy/termux/verify.sh"; then
    VERIFY_SUCCESS=true
else
    echo "========================================================================" >&2
    echo "PRODUCTION VERIFICATION FAILED!" >&2
    echo "Initiating automatic rollback to previous release..." >&2
    echo "========================================================================" >&2
fi

# ------------------------------------------------------------------------------
# 11. Handle Rollback vs Success
# ------------------------------------------------------------------------------
if [[ "$VERIFY_SUCCESS" != "true" ]]; then
    if [[ -x "$CURRENT_LINK/deploy/termux/rollback.sh" ]]; then
        "$CURRENT_LINK/deploy/termux/rollback.sh"
    elif [[ -x "$SCRIPT_DIR/rollback.sh" ]]; then
        "$SCRIPT_DIR/rollback.sh"
    fi

    echo "{\"timestamp\": \"$TIMESTAMP\", \"release_id\": \"$RELEASE_ID\", \"commit_sha\": \"$TARGET_COMMIT\", \"status\": \"failed_rolled_back\"}" >> "$STATE_DIR/deployment-history.json.log"
    echo "Deployment failed and application was safely rolled back." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# 12. Prune Old Releases (Keep Last 3 Releases)
# ------------------------------------------------------------------------------
echo "[Deployment] Pruning old releases (retaining last 3 releases)..."
TOTAL_RELEASES=$(find "$RELEASES_DIR" -maxdepth 1 -mindepth 1 -type d -name "release-*" | wc -l)
if [[ "$TOTAL_RELEASES" -gt 3 ]]; then
    find "$RELEASES_DIR" -maxdepth 1 -mindepth 1 -type d -name "release-*" | sort | head -n -3 | while read -r old_rel; do
        if [[ "$old_rel" != "$(readlink -f "$CURRENT_LINK")" && "$old_rel" != "$(readlink -f "$PREVIOUS_LINK" 2>/dev/null || true)" ]]; then
            echo "[Deployment] Removing old release: $(basename "$old_rel")"
            rm -rf "$old_rel"
        fi
    done
fi

# ------------------------------------------------------------------------------
# 13. Record Deployment Success
# ------------------------------------------------------------------------------
cat <<EOF > "$STATE_DIR/active-release.json"
{
  "active_release_id": "$RELEASE_ID",
  "commit_sha": "$TARGET_COMMIT",
  "short_sha": "$SHORT_SHA",
  "deployed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "status": "success"
}
EOF

echo "{\"timestamp\": \"$TIMESTAMP\", \"release_id\": \"$RELEASE_ID\", \"commit_sha\": \"$TARGET_COMMIT\", \"status\": \"success\"}" >> "$STATE_DIR/deployment-history.json.log"

echo "========================================================================"
echo "GUSBY APPLICATION DEPLOYMENT COMPLETED SUCCESSFULLY"
echo "Active Release: $RELEASE_ID ($SHORT_SHA)"
echo "Path:           $RELEASE_DIR"
echo "========================================================================"
exit 0
