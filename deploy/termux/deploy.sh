#!/usr/bin/env bash
# ==============================================================================
# Gusby Production Deployment Automation (Android Termux ARM64)
# ==============================================================================
# Complete 14-Step Deployment Lifecycle:
#   1. Check latest eligible successful main-branch CI run
#   2. Identify exact commit SHA
#   3. Verify deployment has not already occurred for this commit
#   4. Retrieve exact source tree
#   5. Validate required dependencies and environment variables
#   6. Build backend and frontend on Android ARM64
#   7. Run pre-deployment checks
#   8. Run database migrations safely (with pre-migration snapshot)
#   9. Activate new release via atomic symlink
#   10. Restart PM2 'gusby-backend' process (never 'pm2 restart all')
#   11. Perform production verification suite (Liveness, Readiness, Nginx, Smoke)
#   12. Mark deployment successful only after verification
#   13. Roll back application activation if verification fails
#   14. Record final deployment result and audit log
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# 0. Global Setup & Mutex Locking
# ------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

DEPLOY_ROOT="${GUSBY_DEPLOY_ROOT:-$ROOT_DIR}"
RELEASES_DIR="$DEPLOY_ROOT/releases"
SHARED_DIR="$DEPLOY_ROOT/shared"
STATE_DIR="$DEPLOY_ROOT/state"
CURRENT_LINK="$DEPLOY_ROOT/current"
PREVIOUS_LINK="$DEPLOY_ROOT/previous"
LOCK_FILE="/tmp/gusby-deploy.lock"

mkdir -p "$RELEASES_DIR" "$SHARED_DIR" "$STATE_DIR" "$SHARED_DIR/logs" "$SHARED_DIR/backups"

# Acquire deployment lock (prevent concurrent executions)
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "Error: Another deployment is already in progress (Locked on $LOCK_FILE)." >&2
    exit 1
fi

# Acquire Android Termux Wake Lock if running inside Termux
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
echo "GUSBY PRODUCTION DEPLOYMENT AGENT"
echo "Host: $(uname -s) $(uname -m) (Termux/ARM64 Native)"
echo "Deploy Root: $DEPLOY_ROOT"
echo "Timestamp:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================================================"

# ------------------------------------------------------------------------------
# Step 1 & 2: Identify Eligible Commit SHA & CI Verification Status
# ------------------------------------------------------------------------------
TARGET_COMMIT=""
FORCE_UNVERIFIED=false

for arg in "$@"; do
    if [[ "$arg" == "--force-unverified" ]]; then
        FORCE_UNVERIFIED=true
    elif [[ -z "$TARGET_COMMIT" ]] && [[ "$arg" != --* ]]; then
        TARGET_COMMIT="$arg"
    fi
done

REPO_NAME="FatPandaC8/KBA"

if [[ -z "$TARGET_COMMIT" ]]; then
    echo "[Step 1/14] Discovering latest CI-verified commit on main branch..."
    
    # Method A: GitHub CLI
    if command -v gh &> /dev/null && gh auth status &> /dev/null; then
        echo "[Step 1/14] Querying GitHub via gh CLI..."
        LATEST_RUN=$(gh run list --repo "$REPO_NAME" --branch main --workflow "Gusby Production CI" --status success --limit 1 --json headSha -q '.[0].headSha' 2>/dev/null || true)
        if [[ -n "$LATEST_RUN" && "$LATEST_RUN" != "null" ]]; then
            TARGET_COMMIT="$LATEST_RUN"
        fi
    fi

    # Method B: GitHub Public REST API via curl + jq
    if [[ -z "$TARGET_COMMIT" ]] && command -v curl &> /dev/null && command -v jq &> /dev/null; then
        echo "[Step 1/14] Querying GitHub Actions REST API for verified main runs..."
        API_RESP=$(curl -sSf -H "Accept: application/vnd.github.v3+json" --max-time 10 "https://api.github.com/repos/$REPO_NAME/actions/runs?branch=main&status=success&per_page=5" 2>/dev/null || true)
        if [[ -n "$API_RESP" ]]; then
            TARGET_COMMIT=$(echo "$API_RESP" | jq -r '.workflow_runs[] | select(.name == "Gusby Production CI" and .conclusion == "success") | .head_sha' | head -n 1 || true)
            if [[ "$TARGET_COMMIT" == "null" ]]; then
                TARGET_COMMIT=""
            fi
        fi
    fi

    if [[ -z "$TARGET_COMMIT" ]]; then
        if [[ "$FORCE_UNVERIFIED" == "true" ]]; then
            if git rev-parse --is-inside-work-tree &> /dev/null; then
                TARGET_COMMIT=$(git rev-parse HEAD)
                echo "[Step 2/14] WARNING: No verified CI commit found on main. Using local HEAD due to --force-unverified: $TARGET_COMMIT" >&2
            else
                echo "Error: Could not determine target commit SHA and host is not inside a git repository." >&2
                exit 1
            fi
        else
            echo "========================================================================" >&2
            echo "DEPLOYMENT GATING FAILURE: No CI-verified commit found on 'main' branch." >&2
            echo "Gusby deployment gating requires that 'Gusby Production CI' passed on GitHub." >&2
            echo "Check GitHub Actions: https://github.com/$REPO_NAME/actions" >&2
            echo "To override ONLY in an emergency disaster recovery scenario, run:" >&2
            echo "  $0 <commit_sha> --force-unverified" >&2
            echo "========================================================================" >&2
            exit 1
        fi
    else
        echo "[Step 2/14] Selected verified commit from passing CI run: $TARGET_COMMIT"
    fi
else
    echo "[Step 2/14] Target commit explicitly requested: $TARGET_COMMIT"
    
    # Verify the requested commit has passed CI
    if [[ "$FORCE_UNVERIFIED" != "true" ]]; then
        echo "[Step 2/14] Verifying CI status for requested commit $TARGET_COMMIT..."
        CI_CONCLUSION=""
        if command -v curl &> /dev/null && command -v jq &> /dev/null; then
            RUNS_JSON=$(curl -sSf -H "Accept: application/vnd.github.v3+json" --max-time 10 "https://api.github.com/repos/$REPO_NAME/actions/runs?head_sha=$TARGET_COMMIT" 2>/dev/null || true)
            if [[ -n "$RUNS_JSON" ]]; then
                CI_CONCLUSION=$(echo "$RUNS_JSON" | jq -r '.workflow_runs[] | select(.name == "Gusby Production CI") | .conclusion' | head -n 1 || true)
            fi
        fi

        if [[ "$CI_CONCLUSION" != "success" ]]; then
            echo "========================================================================" >&2
            echo "DEPLOYMENT GATING VIOLATION: Commit $TARGET_COMMIT has not passed CI!" >&2
            echo "Observed CI Conclusion: '${CI_CONCLUSION:-not found / pending}'" >&2
            echo "Gating contract strictly prohibits deploying failing, pending, or unverified commits." >&2
            echo "========================================================================" >&2
            exit 1
        fi
        echo "[Step 2/14] CI Verification confirmed: Gusby Production CI passed."
    else
        echo "[Step 2/14] WARNING: Skipping CI verification due to --force-unverified flag." >&2
    fi
fi

SHORT_SHA="${TARGET_COMMIT:0:7}"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%SZ)
RELEASE_ID="release-${SHORT_SHA}-${TIMESTAMP}"
RELEASE_DIR="$RELEASES_DIR/$RELEASE_ID"

# ------------------------------------------------------------------------------
# Step 3: Verify Deployment Has Not Already Occurred
# ------------------------------------------------------------------------------
echo "[Step 3/14] Verifying if commit $SHORT_SHA is already the active deployment..."
if [[ -L "$CURRENT_LINK" ]] && [[ -f "$CURRENT_LINK/release-metadata.json" ]]; then
    CURRENT_ACTIVE_SHA=$(grep -o '"commit_sha": "[^"]*' "$CURRENT_LINK/release-metadata.json" | cut -d'"' -f4 || true)
    if [[ "$CURRENT_ACTIVE_SHA" == "$TARGET_COMMIT" ]]; then
        echo "Notice: Commit $TARGET_COMMIT is already active in production at $(readlink -f "$CURRENT_LINK")."
        echo "Exiting deployment (idempotent no-op)."
        exit 0
    fi
fi
echo "[Step 3/14] Proceeding with deployment for new release $RELEASE_ID."

# ------------------------------------------------------------------------------
# Step 4: Retrieve Exact Source Tree
# ------------------------------------------------------------------------------
echo "[Step 4/14] Preparing release directory: $RELEASE_DIR"
mkdir -p "$RELEASE_DIR"

if git rev-parse --is-inside-work-tree &> /dev/null; then
    # Export clean source archive of the exact commit
    git archive "$TARGET_COMMIT" | tar -x -C "$RELEASE_DIR"
else
    echo "Error: Host is not inside a git repository." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# Step 5: Validate Dependencies and Environment Configuration
# ------------------------------------------------------------------------------
echo "[Step 5/14] Validating runtime dependencies and environment..."

# Check required binaries
for cmd in go node npm psql nginx pm2 curl jq tar gzip; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "Error: Required command '$cmd' is not found in PATH." >&2
        exit 1
    fi
done

# Ensure shared .env exists
SHARED_ENV="$SHARED_DIR/.env"
if [[ ! -f "$SHARED_ENV" ]]; then
    if [[ -f "$ROOT_DIR/.env" ]]; then
        echo "[Step 5/14] Initializing shared .env from current working copy..."
        cp "$ROOT_DIR/.env" "$SHARED_ENV"
    else
        echo "Error: Shared environment configuration file missing at $SHARED_ENV" >&2
        exit 1
    fi
fi

# Symlink shared .env into release directory
ln -sf "$SHARED_ENV" "$RELEASE_DIR/.env"

# Validate database URL safety (never server_lab)
set +u
# shellcheck disable=SC1090
source "$SHARED_ENV"
set -u

DB_CHECK_URL="${GUSBY_DATABASE_URL:-${DATABASE_URL:-}}"
if [[ "$DB_CHECK_URL" =~ /server_lab([?].*)?$ ]]; then
    echo "CRITICAL ERROR: GUSBY_DATABASE_URL points to 'server_lab' in $SHARED_ENV! Refusing deployment." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# Step 6: Build Backend and Frontend on Android ARM64
# ------------------------------------------------------------------------------
echo "[Step 6/14] Compiling Go backend binary on ARM64..."
(
    cd "$RELEASE_DIR"
    mkdir -p bin
    CGO_ENABLED=0 go build -ldflags="-s -w -X 'gusby/internal/config.AppVersion=$RELEASE_ID' -X 'gusby/internal/config.GitCommit=$TARGET_COMMIT' -X 'gusby/internal/config.BuildTime=$(date -u +%Y-%m-%dT%H:%M:%SZ)'" -o bin/gusby ./cmd/gusby
    chmod +x bin/gusby
)

echo "[Step 6/14] Building Nuxt 4 static SPA production bundle..."
(
    cd "$RELEASE_DIR/frontend"
    npm ci --prefer-offline --no-audit
    npm run generate
)

# ------------------------------------------------------------------------------
# Step 7: Run Pre-Deployment Verification Checks
# ------------------------------------------------------------------------------
echo "[Step 7/14] Running pre-deployment build integrity checks..."
test -f "$RELEASE_DIR/bin/gusby" || (echo "Missing Go binary!" && exit 1)
test -f "$RELEASE_DIR/frontend/.output/public/index.html" || (echo "Missing frontend index.html!" && exit 1)

# Write release metadata into release directory
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
# Step 8: Run Database Migrations Safely (with Pre-Migration Snapshot)
# ------------------------------------------------------------------------------
echo "[Step 8/14] Executing database migrations safely..."
(
    cd "$RELEASE_DIR"
    chmod +x scripts/migrate.sh scripts/backup.sh
    # Trigger pre-migration backup automatically
    BACKUP_BEFORE_MIGRATE=true ./scripts/migrate.sh up
)

# ------------------------------------------------------------------------------
# Step 9: Atomically Activate New Release Symlink
# ------------------------------------------------------------------------------
echo "[Step 9/14] Activating release $RELEASE_ID..."

# Record current release as previous (for instant rollback)
if [[ -L "$CURRENT_LINK" ]]; then
    OLD_CURRENT=$(readlink -f "$CURRENT_LINK")
    ln -sfn "$OLD_CURRENT" "$PREVIOUS_LINK"
    echo "[Step 9/14] Preserved previous release symlink: $OLD_CURRENT"
fi

# Atomic symlink replacement
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK.tmp"
mv -Tf "$CURRENT_LINK.tmp" "$CURRENT_LINK"
echo "[Step 9/14] 'current' symlink now points to $RELEASE_DIR"

# ------------------------------------------------------------------------------
# Step 10: Restart PM2 Named Process
# ------------------------------------------------------------------------------
echo "[Step 10/14] Restarting 'gusby-backend' in PM2..."
if pm2 describe gusby-backend &> /dev/null; then
    pm2 restart gusby-backend
else
    echo "[Step 10/14] Starting 'gusby-backend' for the first time..."
    pm2 start "$CURRENT_LINK/ecosystem.config.cjs" --only gusby-backend
fi
pm2 save || true

# ------------------------------------------------------------------------------
# Step 11: Perform Production Verification Suite
# ------------------------------------------------------------------------------
echo "[Step 11/14] Performing production verification suite..."
chmod +x "$CURRENT_LINK/deploy/termux/verify.sh"

VERIFY_SUCCESS=false
if "$CURRENT_LINK/deploy/termux/verify.sh"; then
    VERIFY_SUCCESS=true
else
    echo "========================================================================" >&2
    echo "[Step 11/14] PRODUCTION VERIFICATION FAILED!" >&2
    echo "Initiating automatic rollback to preserve system availability..." >&2
    echo "========================================================================" >&2
fi

# ------------------------------------------------------------------------------
# Step 12 & 13: Handle Success vs Rollback
# ------------------------------------------------------------------------------
if [[ "$VERIFY_SUCCESS" != "true" ]]; then
    # Step 13: Rollback
    echo "[Step 13/14] Triggering rollback..."
    if [[ -x "$CURRENT_LINK/deploy/termux/rollback.sh" ]]; then
        "$CURRENT_LINK/deploy/termux/rollback.sh"
    elif [[ -x "$ROOT_DIR/deploy/termux/rollback.sh" ]]; then
        "$ROOT_DIR/deploy/termux/rollback.sh"
    fi

    # Record failure
    echo "{\"timestamp\": \"$TIMESTAMP\", \"release_id\": \"$RELEASE_ID\", \"commit_sha\": \"$TARGET_COMMIT\", \"status\": \"failed_rolled_back\"}" >> "$STATE_DIR/deployment-history.json.log"
    echo "Deployment failed and rolled back. Check logs in $SHARED_DIR/logs." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# Step 14: Record Final Result
# ------------------------------------------------------------------------------
echo "[Step 14/14] Recording successful deployment..."
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
echo "GUSBY DEPLOYMENT COMPLETED AND VERIFIED SUCCESSFULLY"
echo "Active Release: $RELEASE_ID ($SHORT_SHA)"
echo "Path:           $RELEASE_DIR"
echo "========================================================================"
exit 0
