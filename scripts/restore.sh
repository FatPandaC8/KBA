#!/usr/bin/env bash
# ==============================================================================
# Gusby Database Restore Tool
# ==============================================================================
# Usage:
#   ./scripts/restore.sh <backup_file.sql.gz> [--confirm-target-db=<dbname>]
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
elif [[ -z "${DATABASE_URL:-}" ]] && [[ -f "$HOME/services/gusby/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$HOME/services/gusby/.env"
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

for cmd in psql gunzip gzip; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "Error: Required command '$cmd' is not installed or not in PATH." >&2
        exit 1
    fi
done

# Verify database is not server_lab
if [[ "$DB_URL" =~ /server_lab([?].*)?$ ]]; then
    echo "CRITICAL SAFETY VIOLATION: Database URL specifies 'server_lab'!" >&2
    exit 1
fi

ACTUAL_DB=$(psql "$DB_URL" -v ON_ERROR_STOP=1 -t -A -c "SELECT current_database();" 2>/dev/null || true)
if [[ "$ACTUAL_DB" == "server_lab" || -z "$ACTUAL_DB" ]]; then
    echo "CRITICAL SAFETY VIOLATION: Connected to 'server_lab' or unreachable database." >&2
    exit 1
fi

EXPECTED_DB="${GUSBY_EXPECTED_DB:-gusby_db}"
if [[ "$ACTUAL_DB" != "$EXPECTED_DB" ]]; then
    echo "CRITICAL SAFETY ERROR: Connected DB '$ACTUAL_DB' does not match expected database '$EXPECTED_DB'." >&2
    exit 1
fi

# Verify archive integrity
if ! gzip -t "$BACKUP_FILE" 2>/dev/null; then
    echo "Error: File is not a valid gzip archive: $BACKUP_FILE" >&2
    exit 1
fi

# Confirmation guard
if [[ "$CONFIRM_FLAG" == "--confirm-target-db=$ACTUAL_DB" || "$CONFIRM_FLAG" == "--force" ]]; then
    echo "Target database confirmed: '$ACTUAL_DB'"
else
    echo "WARNING: This will restore data into database '$ACTUAL_DB' (schema 'gusby')."
    read -r -p "Type target database name ('$ACTUAL_DB') to confirm: " typed
    if [[ "$typed" != "$ACTUAL_DB" ]]; then
        echo "Restore cancelled."
        exit 1
    fi
fi

echo "Restoring into database '$ACTUAL_DB'..."
psql "$DB_URL" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" > /dev/null
gunzip -c "$BACKUP_FILE" | psql "$DB_URL" -v ON_ERROR_STOP=1 > /dev/null

echo "Restore completed successfully."
psql "$DB_URL" -v ON_ERROR_STOP=1 -c "SELECT count(*) AS gusby_tables FROM information_schema.tables WHERE table_schema = 'gusby';"
