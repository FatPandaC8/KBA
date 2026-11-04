#!/usr/bin/env bash
# ==============================================================================
# Gusby Database Backup Tool
# ==============================================================================
# Usage:
#   ./scripts/backup.sh [manual|scheduled]
#
# Environment variables:
#   GUSBY_DATABASE_URL or DATABASE_URL (Required)
#   GUSBY_BACKUP_DIR                   (Default: ~/backups/gusby)
#   GUSBY_EXPECTED_DB                  (Default: gusby_db)
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

for cmd in psql pg_dump gzip; do
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

BACKUP_TYPE="${1:-manual}"
BACKUP_DIR="${GUSBY_BACKUP_DIR:-$HOME/backups/gusby}"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date -u +%Y%m%d_%H%M%SZ)
FINAL_FILE="$BACKUP_DIR/gusby_${BACKUP_TYPE}_${TIMESTAMP}.sql.gz"
TMP_FILE="${FINAL_FILE}.tmp.$$"

trap 'rm -f "$TMP_FILE" 2>/dev/null || true' EXIT INT TERM

echo "Dumping schema 'gusby' from database '$ACTUAL_DB'..."
pg_dump "$DB_URL" --schema=gusby --clean --if-exists --no-owner --no-acl | gzip -9 > "$TMP_FILE"

# Validate compressed archive integrity before moving to final name
if ! gzip -t "$TMP_FILE"; then
    echo "Error: Backup file failed gzip integrity check!" >&2
    rm -f "$TMP_FILE"
    exit 1
fi

mv "$TMP_FILE" "$FINAL_FILE"
echo "Backup created successfully: $FINAL_FILE ($(du -h "$FINAL_FILE" | cut -f1))"
