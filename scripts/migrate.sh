#!/usr/bin/env bash
# ==============================================================================
# Gusby Production Database Migration Tool
# ==============================================================================
# Commands:
#   ./scripts/migrate.sh up        - Safely applies any pending migrations
#   ./scripts/migrate.sh status    - Checks migration status (applied vs pending)
#   ./scripts/migrate.sh validate  - Verifies migration files and database connection
#
# Environment variables:
#   GUSBY_DATABASE_URL or DATABASE_URL (Required)
#   BACKUP_BEFORE_MIGRATE (Default: true)
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
    echo "Error: Neither GUSBY_DATABASE_URL nor DATABASE_URL is set in environment or .env." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# Critical Safety Guard: Never touch 'server_lab' database
# ------------------------------------------------------------------------------
if [[ "$DB_URL" =~ /server_lab([?].*)?$ ]]; then
    echo "========================================================================" >&2
    echo "CRITICAL SAFETY VIOLATION: Target database is 'server_lab'!" >&2
    echo "Gusby migrations are strictly prohibited from touching 'server_lab'." >&2
    echo "Please set GUSBY_DATABASE_URL to a dedicated database (e.g. gusby_db)." >&2
    echo "========================================================================" >&2
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
        echo "Error: 'psql' client utility is not installed or not in PATH." >&2
        echo "On Termux: pkg install postgresql" >&2
        echo "On Ubuntu/Debian: sudo apt-get install postgresql-client" >&2
        exit 1
    fi
fi

MIGRATIONS_DIR="$ROOT_DIR/migrations/gusby"
if [[ ! -d "$MIGRATIONS_DIR" ]]; then
    echo "Error: Migrations directory not found: $MIGRATIONS_DIR" >&2
    exit 1
fi

# Sanitized DB URL for display
SAFE_DB_URL=$(echo "$DB_URL" | sed -E 's/:[^@]+@/:***@/')

# ------------------------------------------------------------------------------
# Helper: Run SQL query
# ------------------------------------------------------------------------------
run_sql() {
    local sql="$1"
    if [[ "$PSQL_CMD" == *"docker exec"* ]]; then
        $PSQL_CMD "$DB_URL" -v ON_ERROR_STOP=1 -t -A -c "$sql"
    else
        $PSQL_CMD "$DB_URL" -v ON_ERROR_STOP=1 -t -A -c "$sql"
    fi
}

run_file() {
    local file="$1"
    if [[ "$PSQL_CMD" == *"docker exec"* ]]; then
        $PSQL_CMD "$DB_URL" -v ON_ERROR_STOP=1 < "$file"
    else
        $PSQL_CMD "$DB_URL" -v ON_ERROR_STOP=1 -f "$file"
    fi
}

# ------------------------------------------------------------------------------
# Ensure schema_migrations table exists
# ------------------------------------------------------------------------------
init_migration_tracker() {
    run_sql "
        CREATE SCHEMA IF NOT EXISTS gusby;
        CREATE TABLE IF NOT EXISTS gusby.schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    " > /dev/null
}

# ------------------------------------------------------------------------------
# Command: status
# ------------------------------------------------------------------------------
cmd_status() {
    echo "========================================================================"
    echo "Gusby Database Migration Status"
    echo "Target: $SAFE_DB_URL"
    echo "========================================================================"
    init_migration_tracker

    printf "%-35s | %-12s | %s\n" "Migration Version" "Status" "Applied At"
    echo "------------------------------------------------------------------------"

    # Get sorted migration files
    for file in $(find "$MIGRATIONS_DIR" -maxdepth 1 -name "*.sql" | sort); do
        filename=$(basename "$file")
        version="${filename%.sql}"

        applied_at=$(run_sql "SELECT applied_at FROM gusby.schema_migrations WHERE version = '$version';" || true)

        if [[ -n "$applied_at" ]]; then
            printf "%-35s | \033[0;32m%-12s\033[0m | %s\n" "$version" "APPLIED" "$applied_at"
        else
            printf "%-35s | \033[0;33m%-12s\033[0m | %s\n" "$version" "PENDING" "-"
        fi
    done
    echo "========================================================================"
}

# ------------------------------------------------------------------------------
# Command: validate
# ------------------------------------------------------------------------------
cmd_validate() {
    echo "[Gusby Migrations] Validating database connection..."
    init_migration_tracker

    # Check pg_trgm extension
    local trgm_installed
    trgm_installed=$(run_sql "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';" || true)
    if [[ "$trgm_installed" == "1" ]]; then
        echo "[Gusby Migrations] Extension 'pg_trgm': INSTALLED (OK)"
    else
        echo "[Gusby Migrations] Extension 'pg_trgm': NOT YET INSTALLED (Will be created during migration)"
    fi

    echo "[Gusby Migrations] Database connection and schema tracker validated successfully."
}

# ------------------------------------------------------------------------------
# Command: up (Apply pending migrations)
# ------------------------------------------------------------------------------
cmd_up() {
    echo "========================================================================"
    echo "Executing Gusby Migrations"
    echo "Target: $SAFE_DB_URL"
    echo "========================================================================"
    init_migration_tracker

    # Find pending migrations
    local pending_migrations=()
    for file in $(find "$MIGRATIONS_DIR" -maxdepth 1 -name "*.sql" | sort); do
        filename=$(basename "$file")
        version="${filename%.sql}"
        applied_at=$(run_sql "SELECT applied_at FROM gusby.schema_migrations WHERE version = '$version';" || true)
        if [[ -z "$applied_at" ]]; then
            pending_migrations+=("$file")
        fi
    done

    if [[ ${#pending_migrations[@]} -eq 0 ]]; then
        echo "[Gusby Migrations] Database is up to date. No pending migrations."
        return 0
    fi

    echo "[Gusby Migrations] Found ${#pending_migrations[@]} pending migration(s)."

    # Optional Pre-migration backup if requested and backup script exists
    if [[ "${BACKUP_BEFORE_MIGRATE:-true}" == "true" ]] && [[ -x "$ROOT_DIR/scripts/backup.sh" ]]; then
        echo "[Gusby Migrations] Creating pre-migration safety backup..."
        "$ROOT_DIR/scripts/backup.sh" pre-migrate || echo "Warning: Backup script finished with non-zero status, proceeding with caution."
    fi

    for file in "${pending_migrations[@]}"; do
        filename=$(basename "$file")
        version="${filename%.sql}"

        echo "[Gusby Migrations] Applying: $filename..."
        
        # Execute migration file
        if run_file "$file" > /dev/null; then
            # Record in tracker
            run_sql "
                INSERT INTO gusby.schema_migrations (version, applied_at)
                VALUES ('$version', now())
                ON CONFLICT (version) DO UPDATE SET applied_at = now();
            " > /dev/null
            echo "[Gusby Migrations] Successfully applied: $filename"
        else
            echo "========================================================================" >&2
            echo "CRITICAL ERROR: Failed to apply migration: $filename" >&2
            echo "Migration aborted. Please review error above and check database state." >&2
            echo "========================================================================" >&2
            exit 1
        fi
    done

    echo "========================================================================"
    echo "[Gusby Migrations] All migrations applied successfully!"
    echo "========================================================================"
}

# ------------------------------------------------------------------------------
# Main Dispatcher
# ------------------------------------------------------------------------------
ACTION="${1:-up}"

case "$ACTION" in
    up)
        cmd_up
        ;;
    status)
        cmd_status
        ;;
    validate)
        cmd_validate
        ;;
    *)
        echo "Usage: $0 {up|status|validate}"
        exit 1
        ;;
esac
