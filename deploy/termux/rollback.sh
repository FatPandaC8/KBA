#!/usr/bin/env bash
# ==============================================================================
# Gusby Application Rollback Tool (Android Termux ARM64)
# ==============================================================================
# Performs safe, atomic application rollback to the previous release.
#
# Rules:
# - Reverts application symlink atomically.
# - Explicitly restarts 'gusby-backend' in PM2 (never 'pm2 restart all').
# - Runs production verification suite.
# - DOES NOT perform unsafe automated database rollback.
# - Updates deployment history and active release metadata.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

DEPLOY_ROOT="${GUSBY_DEPLOY_ROOT:-$ROOT_DIR}"
CURRENT_LINK="$DEPLOY_ROOT/current"
PREVIOUS_LINK="$DEPLOY_ROOT/previous"
STATE_DIR="$DEPLOY_ROOT/state"
HISTORY_FILE="$STATE_DIR/deployment-history.json"
ACTIVE_FILE="$STATE_DIR/active-release.json"

echo "========================================================================"
echo "GUSBY APPLICATION ROLLBACK INITIATED"
echo "Deploy Root: $DEPLOY_ROOT"
echo "========================================================================"

# 1. Verify previous release exists
if [[ ! -L "$PREVIOUS_LINK" ]] && [[ ! -d "$PREVIOUS_LINK" ]]; then
    echo "Error: No previous release symlink found at $PREVIOUS_LINK." >&2
    echo "Cannot perform rollback: No previous release registered." >&2
    exit 1
fi

PREVIOUS_TARGET=$(readlink -f "$PREVIOUS_LINK")
CURRENT_TARGET=$(readlink -f "$CURRENT_LINK" || echo "none")

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
else
    echo "Notice: PM2 not in PATH; skipping process manager signal."
fi

# 4. Run verification suite
echo "[Rollback] Running production verification suite on restored release..."
if [[ -x "$SCRIPT_DIR/verify.sh" ]]; then
    if ! "$SCRIPT_DIR/verify.sh"; then
        echo "========================================================================" >&2
        echo "CRITICAL: Verification failed after rollback!" >&2
        echo "Manual operator intervention required immediately." >&2
        echo "========================================================================" >&2
        exit 1
    fi
else
    echo "Notice: Verification script not found at $SCRIPT_DIR/verify.sh."
fi

# 5. Record rollback in state history
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p "$STATE_DIR"

if [[ -f "$HISTORY_FILE" ]]; then
    TMP_HIST=$(mktemp)
    # Append rollback record
    cat <<EOF >> "$HISTORY_FILE.log"
{"timestamp": "$TIMESTAMP", "action": "rollback", "restored_release": "$PREVIOUS_TARGET", "previous_failed": "$CURRENT_TARGET", "status": "success"}
EOF
fi

cat <<EOF > "$ACTIVE_FILE"
{
  "active_release": "$PREVIOUS_TARGET",
  "active_since": "$TIMESTAMP",
  "rollback_event": true
}
EOF

echo "========================================================================"
echo "GUSBY ROLLBACK COMPLETED SUCCESSFULLY"
echo "Active Release: $PREVIOUS_TARGET"
echo "Database Status: Unmodified (Preserving data integrity)"
echo "========================================================================"
exit 0
