#!/usr/bin/env bash
# ==============================================================================
# Gusby PostgreSQL Database Restore & Verification Tool
# ==============================================================================
# Usage:
#   ./scripts/restore.sh <path_to_backup_file.sql.gz> [--confirm-target-db=<dbname>]
#
# Environment variables:
#   GUSBY_DATABASE_URL or DATABASE_URL (Required)
#   GUSBY_EXPECTED_DB                  (Optional validation: e.g. gusby_db)
#
# Scope & Safety:
#   - Restores schema 'gusby' from the compressed backup archive.
#   - Strictly forbids restoring into 'server_lab'.
#   - Requires explicit interactive confirmation or --confirm-target-db flag.
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

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <backup_file.sql.gz> [--confirm-target-db=<dbname>]" >&2
    exit 1
fi

BACKUP_FILE="$1"
CONFIRM_FLAG="${2:-}"

if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Error: Backup file not found: $BACKUP_FILE" >&2
    exit 1
fi

# Locate psql
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

# ------------------------------------------------------------------------------
# Critical Safety Verification: Verify Target Database via PostgreSQL itself
# ------------------------------------------------------------------------------
if [[ "$DB_URL" =~ /server_lab([?].*)?$ ]]; then
    echo "========================================================================" >&2
    echo "CRITICAL SAFETY VIOLATION: Database URL points to 'server_lab'!" >&2
    echo "Restoring into 'server_lab' is strictly forbidden." >&2
    echo "========================================================================" >&2
    exit 1
fi

ACTUAL_DB=$(run_sql "SELECT current_database();" 2>/dev/null || true)
if [[ -z "$ACTUAL_DB" ]]; then
    echo "Error: Unable to connect to PostgreSQL to verify database identity." >&2
    exit 1
fi

if [[ "$ACTUAL_DB" == "server_lab" ]]; then
    echo "========================================================================" >&2
    echo "CRITICAL SAFETY VIOLATION: Connected to database 'server_lab'!" >&2
    echo "Restoring into 'server_lab' is strictly forbidden." >&2
    echo "========================================================================" >&2
    exit 1
fi

EXPECTED_DB="${GUSBY_EXPECTED_DB:-}"
if [[ -n "$EXPECTED_DB" && "$ACTUAL_DB" != "$EXPECTED_DB" ]]; then
    echo "CRITICAL SAFETY ERROR: Connected database '$ACTUAL_DB' does not match GUSBY_EXPECTED_DB '$EXPECTED_DB'." >&2
    exit 1
fi

# Verify gzip archive integrity before proceeding
echo "[Gusby Restore] Testing archive integrity..."
if ! gzip -t "$BACKUP_FILE" 2>/dev/null; then
    echo "Error: File is not a valid gzip archive: $BACKUP_FILE" >&2
    exit 1
fi

SAFE_DB_URL=$(echo "$DB_URL" | sed -E 's/:[^@]+@/:***@/')

echo "========================================================================"
echo "GUSBY DATABASE RESTORE PROCEDURE"
echo "Backup File: $BACKUP_FILE"
echo "Target DB:   $ACTUAL_DB"
echo "Endpoint:    $SAFE_DB_URL"
echo "========================================================================"

# Confirmation safeguard: prevent accidental data overwrites
if [[ "$CONFIRM_FLAG" == "--confirm-target-db=$ACTUAL_DB" || "$CONFIRM_FLAG" == "--force" ]]; then
    echo "[Gusby Restore] Automatic target confirmation matched: '$ACTUAL_DB'"
else
    echo "WARNING: This operation will OVERWRITE existing data in schema 'gusby' inside database '$ACTUAL_DB'."
    read -r -p "To proceed, type the target database name exactly ('$ACTUAL_DB'): " typed_name
    if [[ "$typed_name" != "$ACTUAL_DB" ]]; then
        echo "Restore aborted: typed name '$typed_name' does not match target database '$ACTUAL_DB'."
        exit 1
    fi
fi

echo "[Gusby Restore] Ensuring required extensions (pg_trgm) in target database..."
run_sql "CREATE EXTENSION IF NOT EXISTS pg_trgm;" > /dev/null

echo "[Gusby Restore] Streaming SQL archive into target database..."
if [[ "$PSQL_CMD" == *"docker exec"* ]]; then
    gunzip -c "$BACKUP_FILE" | $PSQL_CMD "$DB_URL" -v ON_ERROR_STOP=1 > /dev/null
else
    gunzip -c "$BACKUP_FILE" | psql "$DB_URL" -v ON_ERROR_STOP=1 > /dev/null
fi

echo "[Gusby Restore] Database restore stream completed successfully."
echo "[Gusby Restore] Running post-restore read-only verification drill..."

# ------------------------------------------------------------------------------
# Post-Restore Read-Only Verification Drill
# ------------------------------------------------------------------------------
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
    echo "Verification Warning: Table count ($TABLE_COUNT) is lower than baseline expectations." >&2
fi

# 3. Verify applied migrations
echo "[Gusby Restore] Restored schema migrations recorded:"
run_sql "SELECT version, applied_at FROM gusby.schema_migrations ORDER BY applied_at ASC;" || echo "Notice: schema_migrations empty or missing."

echo "========================================================================"
echo "RESTORE AND VERIFICATION COMPLETED SUCCESSFULLY"
echo "Target Database: $ACTUAL_DB (Schema 'gusby' restored)"
echo "========================================================================"
exit 0
