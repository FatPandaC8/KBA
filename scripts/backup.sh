#!/usr/bin/env bash
# ==============================================================================
# Gusby PostgreSQL Backup Tool & Automated Retention Policy
# ==============================================================================
# Usage:
#   ./scripts/backup.sh [manual|pre-migrate|scheduled]
#
# Environment variables:
#   GUSBY_DATABASE_URL or DATABASE_URL (Required)
#   GUSBY_BACKUP_DIR (Default: ./backups)
#   GUSBY_BACKUP_RETENTION_COUNT (Default: 10)
#   GUSBY_BACKUP_RETENTION_DAYS (Default: 7)
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

# Critical safety guard: Never dump or touch 'server_lab'
if [[ "$DB_URL" =~ /server_lab([?].*)?$ ]]; then
    echo "CRITICAL SAFETY VIOLATION: Database URL points to 'server_lab'. Refusing operation." >&2
    exit 1
fi

BACKUP_TYPE="${1:-manual}"
BACKUP_DIR="${GUSBY_BACKUP_DIR:-$ROOT_DIR/backups}"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date -u +%Y%m%d_%H%M%SZ)
BACKUP_FILENAME="gusby_${BACKUP_TYPE}_${TIMESTAMP}.sql.gz"
BACKUP_FILEPATH="$BACKUP_DIR/$BACKUP_FILENAME"

echo "[Gusby Backup] Starting $BACKUP_TYPE backup..."
echo "[Gusby Backup] Target directory: $BACKUP_DIR"

# Check pg_dump availability
PG_DUMP_CMD=""
if command -v pg_dump &> /dev/null; then
    PG_DUMP_CMD="pg_dump"
elif docker ps --format '{{.Names}}' 2>/dev/null | grep -q "kba-postgres"; then
    PG_DUMP_CMD="docker exec -i kba-postgres pg_dump"
else
    echo "Error: 'pg_dump' utility is not found." >&2
    echo "On Termux: pkg install postgresql" >&2
    exit 1
fi

# Execute dump of the 'gusby' schema with compression
if [[ "$PG_DUMP_CMD" == *"docker exec"* ]]; then
    $PG_DUMP_CMD "$DB_URL" --schema=gusby --clean --if-exists --no-owner --no-acl | gzip -9 > "$BACKUP_FILEPATH"
else
    pg_dump "$DB_URL" --schema=gusby --clean --if-exists --no-owner --no-acl | gzip -9 > "$BACKUP_FILEPATH"
fi

BACKUP_SIZE=$(du -h "$BACKUP_FILEPATH" | cut -f1)
echo "[Gusby Backup] Backup created successfully: $BACKUP_FILENAME ($BACKUP_SIZE)"

# ------------------------------------------------------------------------------
# Retention Policy: Prune backups older than RETENTION_DAYS, keeping at least RETENTION_COUNT
# ------------------------------------------------------------------------------
RETENTION_COUNT="${GUSBY_BACKUP_RETENTION_COUNT:-10}"
RETENTION_DAYS="${GUSBY_BACKUP_RETENTION_DAYS:-7}"

echo "[Gusby Backup] Applying retention policy (Keep last $RETENTION_COUNT backups or newer than $RETENTION_DAYS days)..."

# Count current backups
TOTAL_BACKUPS=$(find "$BACKUP_DIR" -maxdepth 1 -name "gusby_*.sql.gz" | wc -l)

if [[ $TOTAL_BACKUPS -gt $RETENTION_COUNT ]]; then
    # Find files older than retention days and delete only if total exceeds retention count
    find "$BACKUP_DIR" -maxdepth 1 -name "gusby_*.sql.gz" -mtime +"$RETENTION_DAYS" | sort | head -n -"$RETENTION_COUNT" | while read -r old_backup; do
        if [[ -f "$old_backup" ]]; then
            echo "[Gusby Backup] Pruning expired backup: $(basename "$old_backup")"
            rm -f "$old_backup"
        fi
    done
fi

echo "[Gusby Backup] Current backups in repository:"
ls -lh "$BACKUP_DIR"/gusby_*.sql.gz 2>/dev/null || echo "No backups found."
