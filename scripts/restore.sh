#!/usr/bin/env bash
# ==============================================================================
# Gusby PostgreSQL Database Restore & Verification Tool
# ==============================================================================
# Usage:
#   ./scripts/restore.sh <path_to_backup_file.sql.gz> [--force]
#
# Environment variables:
#   GUSBY_DATABASE_URL or DATABASE_URL (Required)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env if present and DATABASE_URL is not set
if [[ -z "${DATABASE_URL:-}" ]] && [[ -f "$ROOT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.env"
    set +a
fi

DB_URL="${GUSBY_DATABASE_URL:-${DATABASE_URL:-}}"
if [[ -z "$DB_URL" ]]; then
    echo "Error: Neither GUSBY_DATABASE_URL nor DATABASE_URL is set." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# Critical Safety Guard: Never restore into 'server_lab'
# ------------------------------------------------------------------------------
if [[ "$DB_URL" =~ /server_lab([?].*)?$ ]]; then
    echo "========================================================================" >&2
    echo "CRITICAL SAFETY VIOLATION: Target database is 'server_lab'!" >&2
    echo "Restoring into 'server_lab' is strictly forbidden." >&2
    echo "========================================================================" >&2
    exit 1
fi

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <backup_file.sql.gz> [--force]"
    exit 1
fi

BACKUP_FILE="$1"
FORCE_FLAG="${2:-}"

if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Error: Backup file not found: $BACKUP_FILE" >&2
    exit 1
fi

# Verify gzip validity
if ! gzip -t "$BACKUP_FILE" 2>/dev/null; then
    echo "Error: File is not a valid gzip archive: $BACKUP_FILE" >&2
    exit 1
fi

SAFE_DB_URL=$(echo "$DB_URL" | sed -E 's/:[^@]+@/:***@/')

echo "========================================================================"
echo "GUSBY DATABASE RESTORE PROCEDURE"
echo "Backup File: $BACKUP_FILE"
echo "Target DB:   $SAFE_DB_URL"
echo "========================================================================"

if [[ "$FORCE_FLAG" != "--force" ]]; then
    read -r -p "WARNING: This will restore database schema and data into '$SAFE_DB_URL'. Are you sure? [y/N]: " confirm
    if [[ "$confirm" != "y" ]] && [[ "$confirm" != "Y" ]]; then
        echo "Restore cancelled by operator."
        exit 0
    fi
fi

# Check psql availability
PSQL_CMD="${PSQL_CMD:-}"
if [[ -z "$PSQL_CMD" ]]; then
    if command -v psql &> /dev/null; then
        PSQL_CMD="psql"
    elif docker ps --format '{{.Names}}' 2>/dev/null | grep -E -q "kba-postgres|gusby.*pg|postgres"; then
        PG_CONTAINER=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E "kba-postgres|gusby.*pg|postgres" | head -n 1)
        PSQL_CMD="docker exec -i $PG_CONTAINER psql"
    else
        echo "Error: 'psql' utility not found." >&2
        exit 1
    fi
fi

run_sql() {
    local sql="$1"
    if [[ "$PSQL_CMD" == *"docker exec"* ]]; then
        $PSQL_CMD "$DB_URL" -v ON_ERROR_STOP=1 -t -A -c "$sql"
    else
        $PSQL_CMD "$DB_URL" -v ON_ERROR_STOP=1 -t -A -c "$sql"
    fi
}

echo "[Gusby Restore] Ensuring required extensions (pg_trgm) in target database..."
run_sql "CREATE EXTENSION IF NOT EXISTS pg_trgm;" > /dev/null

echo "[Gusby Restore] Restoring schema and data from backup..."

# Restore SQL stream
if [[ "$PSQL_CMD" == *"docker exec"* ]]; then
    gunzip -c "$BACKUP_FILE" | $PSQL_CMD "$DB_URL" -v ON_ERROR_STOP=1 > /dev/null
else
    gunzip -c "$BACKUP_FILE" | psql "$DB_URL" -v ON_ERROR_STOP=1 > /dev/null
fi

echo "[Gusby Restore] Data restored successfully. Performing post-restore verification..."

# ------------------------------------------------------------------------------
# Post-Restore Verification Drill
# ------------------------------------------------------------------------------
run_sql() {
    local sql="$1"
    if [[ "$PSQL_CMD" == *"docker exec"* ]]; then
        $PSQL_CMD "$DB_URL" -v ON_ERROR_STOP=1 -t -A -c "$sql"
    else
        psql "$DB_URL" -v ON_ERROR_STOP=1 -t -A -c "$sql"
    fi
}

# 1. Verify schema existence
SCHEMA_COUNT=$(run_sql "SELECT count(*) FROM information_schema.schemata WHERE schema_name = 'gusby';")
if [[ "$SCHEMA_COUNT" -ne 1 ]]; then
    echo "Verification Failed: 'gusby' schema does not exist!" >&2
    exit 1
fi

# 2. Verify table count
TABLE_COUNT=$(run_sql "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'gusby';")
echo "[Gusby Restore] Verified tables in 'gusby' schema: $TABLE_COUNT"

if [[ "$TABLE_COUNT" -lt 15 ]]; then
    echo "Verification Warning: Table count ($TABLE_COUNT) is lower than expected!" >&2
fi

# 3. Verify applied migrations
echo "[Gusby Restore] Restored schema migrations:"
run_sql "SELECT version, applied_at FROM gusby.schema_migrations ORDER BY applied_at ASC;"

echo "========================================================================"
echo "RESTORE AND VERIFICATION COMPLETED SUCCESSFULLY"
echo "========================================================================"
