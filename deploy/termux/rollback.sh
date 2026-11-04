#!/usr/bin/env bash
# ==============================================================================
# Gusby Application Rollback Tool (Android Termux ARM64)
# ==============================================================================
# Performs safe, atomic application rollback to the previous release.
#
# Rules:
# - Reverts application symlink atomically to 'previous'.
# - Explicitly restarts 'gusby-backend' in PM2 (never 'pm2 restart all').
# - Runs read-only production verification suite.
# - DOES NOT touch PostgreSQL or perform database rollbacks.
# - Updates deployment history and active release metadata.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

DEPLOY_ROOT="${GUSBY_DEPLOY_ROOT:-$HOME/services/gusby}"
CURRENT_LINK="$DEPLOY_ROOT/current"
PREVIOUS_LINK="$DEPLOY_ROOT/previous"
STATE_DIR="$DEPLOY_ROOT/state"
HISTORY_LOG="$STATE_DIR/deployment-history.json.log"
ACTIVE_FILE="$STATE_DIR/active-release.json"

echo "========================================================================"
echo "GUSBY APPLICATION ROLLBACK INITIATED"
echo "Deploy Root: $DEPLOY_ROOT"
echo "Timestamp:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================================================"

# 1. Verify previous release exists
if [[ ! -L "$PREVIOUS_LINK" ]] && [[ ! -d "$PREVIOUS_LINK" ]]; then
    echo "Error: No previous release symlink found at $PREVIOUS_LINK." >&2
    echo "Cannot perform rollback: No previous release registered." >&2
    exit 1
fi

PREVIOUS_TARGET=$(readlink -f "$PREVIOUS_LINK")
CURRENT_TARGET=$(readlink -f "$CURRENT_LINK" 2>/dev/null || echo "none")

if [[ "$PREVIOUS_TARGET" == "$CURRENT_TARGET" ]]; then
    echo "Warning: 'previous' release is identical to 'current' release ($PREVIOUS_TARGET)." >&2
    exit 1
fi

echo "[Rollback] Current Release:  $CURRENT_TARGET"
echo "[Rollback] Target (Previous): $PREVIOUS_TARGET"

# 2. Atomically swap symlink
echo "[Rollback] Switching 'current' symlink to $PREVIOUS_TARGET..."
ln -sfn "$PREVIOUS_TARGET" "$CURRENT_LINK.tmp"
mv -Tf "$CURRENT_LINK.tmp" "$CURRENT_LINK"

# 3. Explicitly restart PM2 process
echo "[Rollback] Restarting 'gusby-backend' process in PM2..."
if command -v pm2 &> /dev/null; then
    pm2 restart gusby-backend || pm2 start "$CURRENT_LINK/ecosystem.config.cjs" --only gusby-backend
    pm2 save || true
else
    echo "Notice: PM2 not in PATH; skipping process manager signal."
fi

# 4. Run read-only verification suite
echo "[Rollback] Running read-only verification suite on restored release..."
VERIFY_SCRIPT="$CURRENT_LINK/deploy/termux/verify.sh"
if [[ ! -x "$VERIFY_SCRIPT" ]]; then
    VERIFY_SCRIPT="$SCRIPT_DIR/verify.sh"
fi

if [[ -x "$VERIFY_SCRIPT" ]]; then
    if ! "$VERIFY_SCRIPT"; then
        echo "========================================================================" >&2
        echo "CRITICAL: Verification failed after rollback!" >&2
        echo "Manual operator intervention required immediately." >&2
        echo "========================================================================" >&2
        exit 1
    fi
else
    echo "Notice: Verification script not found at $VERIFY_SCRIPT."
fi

# 5. Record rollback in state history
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p "$STATE_DIR"

cat <<EOF >> "$HISTORY_LOG"
{"timestamp": "$TIMESTAMP", "action": "rollback", "restored_release": "$PREVIOUS_TARGET", "previous_failed": "$CURRENT_TARGET", "status": "success"}
EOF

cat <<EOF > "$ACTIVE_FILE"
{
  "active_release": "$PREVIOUS_TARGET",
  "active_since": "$TIMESTAMP",
  "rollback_event": true,
  "status": "rolled_back"
}
EOF

echo "========================================================================"
echo "GUSBY ROLLBACK COMPLETED SUCCESSFULLY"
echo "Active Release:  $PREVIOUS_TARGET"
echo "Database Status: Unmodified (Preserving data integrity)"
echo "========================================================================"
exit 0
