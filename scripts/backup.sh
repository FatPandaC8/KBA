#!/usr/bin/env bash
# ==============================================================================
# Gusby PostgreSQL Backup Tool & Automated Retention Policy
# ==============================================================================
# Usage:
#   ./scripts/backup.sh [manual|pre-migrate|scheduled]
#
# Environment variables:
#   GUSBY_DATABASE_URL or DATABASE_URL (Required)
#   GUSBY_BACKUP_DIR                   (Default: $HOME/services/gusby/backups or ./backups)
#   GUSBY_BACKUP_RETENTION_COUNT       (Default: 10)
#   GUSBY_BACKUP_RETENTION_DAYS        (Default: 7)
#   GUSBY_EXPECTED_DB                  (Optional validation: e.g. gusby_db)
#
# Scope & Limitations:
#   - Dumps the application schema 'gusby' from the connected dedicated database.
#   - Does NOT back up other databases (e.g. server_lab is strictly excluded).
#   - Does NOT dump global cluster roles or tablespaces.
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

# Locate psql & pg_dump
PSQL_CMD="${PSQL_CMD:-}"
PG_DUMP_CMD="${PG_DUMP_CMD:-}"

if [[ -z "$PSQL_CMD" ]]; then
    if command -v psql &> /dev/null; then
        PSQL_CMD="psql"
    elif docker ps --format '{{.Names}}' 2>/dev/null | grep -E -q "kba-postgres|gusby.*pg|postgres"; then
        PG_CONTAINER=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E "kba-postgres|gusby.*pg|postgres" | head -n 1)
        PSQL_CMD="docker exec -i $PG_CONTAINER psql"
    else
        echo "Error: 'psql' client utility is not installed or not in PATH." >&2
        exit 1
    fi
fi

if [[ -z "$PG_DUMP_CMD" ]]; then
    if command -v pg_dump &> /dev/null; then
        PG_DUMP_CMD="pg_dump"
    elif docker ps --format '{{.Names}}' 2>/dev/null | grep -E -q "kba-postgres|gusby.*pg|postgres"; then
        PG_CONTAINER=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E "kba-postgres|gusby.*pg|postgres" | head -n 1)
        PG_DUMP_CMD="docker exec -i $PG_CONTAINER pg_dump"
    else
        echo "Error: 'pg_dump' utility not found." >&2
        echo "On Termux: pkg install postgresql" >&2
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
    echo "CRITICAL SAFETY VIOLATION: Database URL points to 'server_lab'. Refusing operation." >&2
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
    echo "Gusby backup tool is strictly prohibited from touching 'server_lab'." >&2
    echo "========================================================================" >&2
    exit 1
fi

EXPECTED_DB="${GUSBY_EXPECTED_DB:-}"
if [[ -n "$EXPECTED_DB" && "$ACTUAL_DB" != "$EXPECTED_DB" ]]; then
    echo "CRITICAL SAFETY ERROR: Connected database '$ACTUAL_DB' does not match GUSBY_EXPECTED_DB '$EXPECTED_DB'." >&2
    exit 1
fi

BACKUP_TYPE="${1:-manual}"

# Default backup dir preference: services/gusby/backups if exists, else ./backups
DEFAULT_BACKUP_DIR="$ROOT_DIR/backups"
if [[ -d "$HOME/services/gusby/backups" ]]; then
    DEFAULT_BACKUP_DIR="$HOME/services/gusby/backups"
fi
BACKUP_DIR="${GUSBY_BACKUP_DIR:-$DEFAULT_BACKUP_DIR}"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date -u +%Y%m%d_%H%M%SZ)
BACKUP_FILENAME="gusby_${BACKUP_TYPE}_${TIMESTAMP}.sql.gz"
BACKUP_FILEPATH="$BACKUP_DIR/$BACKUP_FILENAME"
TMP_FILEPATH="${BACKUP_FILEPATH}.tmp.$$"

echo "========================================================================"
echo "GUSBY POSTGRESQL BACKUP"
echo "Database:  $ACTUAL_DB"
echo "Type:      $BACKUP_TYPE"
echo "Target:    $BACKUP_FILEPATH"
echo "========================================================================"

# Cleanup temporary file on exit
trap 'rm -f "$TMP_FILEPATH" 2>/dev/null || true' EXIT INT TERM

# Dump schema 'gusby' to temporary file with compression
echo "[Gusby Backup] Dumping schema 'gusby' to temporary staging file..."
if [[ "$PG_DUMP_CMD" == *"docker exec"* ]]; then
    $PG_DUMP_CMD "$DB_URL" --schema=gusby --clean --if-exists --no-owner --no-acl | gzip -9 > "$TMP_FILEPATH"
else
    $PG_DUMP_CMD "$DB_URL" --schema=gusby --clean --if-exists --no-owner --no-acl | gzip -9 > "$TMP_FILEPATH"
fi

# Validate compressed archive integrity before moving to final destination
echo "[Gusby Backup] Verifying archive integrity..."
if ! gzip -t "$TMP_FILEPATH"; then
    echo "Error: Generated backup file failed gzip integrity check!" >&2
    rm -f "$TMP_FILEPATH"
    exit 1
fi

# Atomic move from temporary file to final valid-looking filename
mv -f "$TMP_FILEPATH" "$BACKUP_FILEPATH"
BACKUP_SIZE=$(du -h "$BACKUP_FILEPATH" | cut -f1)
echo "[Gusby Backup] Backup created and verified successfully: $BACKUP_FILENAME ($BACKUP_SIZE)"

# ------------------------------------------------------------------------------
# Retention Policy: Prune backups older than RETENTION_DAYS, keeping at least RETENTION_COUNT
# ------------------------------------------------------------------------------
RETENTION_COUNT="${GUSBY_BACKUP_RETENTION_COUNT:-10}"
RETENTION_DAYS="${GUSBY_BACKUP_RETENTION_DAYS:-7}"

echo "[Gusby Backup] Applying retention policy (Keep last $RETENTION_COUNT backups or newer than $RETENTION_DAYS days)..."
TOTAL_BACKUPS=$(find "$BACKUP_DIR" -maxdepth 1 -name "gusby_*.sql.gz" | wc -l)

if [[ $TOTAL_BACKUPS -gt $RETENTION_COUNT ]]; then
    find "$BACKUP_DIR" -maxdepth 1 -name "gusby_*.sql.gz" -mtime +"$RETENTION_DAYS" | sort | head -n -"$RETENTION_COUNT" | while read -r old_backup; do
        if [[ -f "$old_backup" ]]; then
            echo "[Gusby Backup] Pruning expired backup: $(basename "$old_backup")"
            rm -f "$old_backup"
        fi
    done
fi

echo "[Gusby Backup] Current backups in $BACKUP_DIR:"
ls -lh "$BACKUP_DIR"/gusby_*.sql.gz 2>/dev/null || echo "No backups found."
