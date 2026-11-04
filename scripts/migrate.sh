#!/usr/bin/env bash
# ==============================================================================
# Gusby Production Database Migration Tool
# ==============================================================================
# Commands:
#   ./scripts/migrate.sh up        - Safely applies any pending migrations (DDL/DML)
#   ./scripts/migrate.sh status    - Checks migration status (Read-Only)
#   ./scripts/migrate.sh validate  - Verifies database connection & schema (Read-Only)
#
# Environment variables:
#   GUSBY_DATABASE_URL or DATABASE_URL (Required)
#   GUSBY_EXPECTED_DB                  (Optional validation: e.g. gusby_db)
#   BACKUP_BEFORE_MIGRATE              (Default: true for 'up')
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ------------------------------------------------------------------------------
# Concurrency Protection: Flock file descriptor 201
# ------------------------------------------------------------------------------
LOCK_FILE="/tmp/gusby-migrate.lock"
exec 201>"$LOCK_FILE"
if ! flock -n 201; then
    echo "Error: Another migration process is currently running (Locked on $LOCK_FILE)." >&2
    exit 1
fi

cleanup() {
    flock -u 201 2>/dev/null || true
}
trap cleanup EXIT INT TERM

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

# Locate psql client
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
        echo "On Linux:  sudo apt-get install postgresql-client" >&2
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
# Helpers: Execute SQL queries and files
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
# Critical Safety Verification: Verify Target Database via PostgreSQL itself
# ------------------------------------------------------------------------------
verify_target_db() {
    # 1. URL pattern check
    if [[ "$DB_URL" =~ /server_lab([?].*)?$ ]]; then
        echo "========================================================================" >&2
        echo "CRITICAL SAFETY VIOLATION: Target connection URL specifies 'server_lab'!" >&2
        echo "Gusby migrations are strictly prohibited from touching 'server_lab'." >&2
        echo "========================================================================" >&2
        exit 1
    fi

    # 2. Query PostgreSQL engine directly for current database name
    local actual_db
    actual_db=$(run_sql "SELECT current_database();" 2>/dev/null || true)
    if [[ -z "$actual_db" ]]; then
        echo "Error: Unable to connect to PostgreSQL to determine database identity." >&2
        exit 1
    fi

    if [[ "$actual_db" == "server_lab" ]]; then
        echo "========================================================================" >&2
        echo "CRITICAL SAFETY VIOLATION: Connected to database 'server_lab'!" >&2
        echo "Gusby migrations are strictly prohibited from touching 'server_lab'." >&2
        echo "Please configure GUSBY_DATABASE_URL to point to a dedicated database (e.g. gusby_db)." >&2
        echo "========================================================================" >&2
        exit 1
    fi

    # 3. Optional expected DB validation
    local expected_db="${GUSBY_EXPECTED_DB:-}"
    if [[ -n "$expected_db" && "$actual_db" != "$expected_db" ]]; then
        echo "CRITICAL SAFETY ERROR: Connected database '$actual_db' does not match GUSBY_EXPECTED_DB '$expected_db'." >&2
        exit 1
    fi
}

# Check if migration tracker table exists (Read-Only check)
has_tracker_table() {
    local count
    count=$(run_sql "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'gusby' AND table_name = 'schema_migrations';" 2>/dev/null || echo "0")
    if [[ "$count" == "1" ]]; then
        return 0
    fi
    return 1
}

# Initialize migration tracker table (Mutating: called ONLY by 'up')
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
# Command: status (Read-Only)
# ------------------------------------------------------------------------------
cmd_status() {
    verify_target_db
    local actual_db
    actual_db=$(run_sql "SELECT current_database();")

    echo "========================================================================"
    echo "Gusby Database Migration Status"
    echo "Database: $actual_db"
    echo "Target:   $SAFE_DB_URL"
    echo "========================================================================"

    if ! has_tracker_table; then
        echo "Notice: Migration tracker (gusby.schema_migrations) is not yet initialized."
        echo "All migration files are currently PENDING."
        echo "------------------------------------------------------------------------"
        printf "%-35s | %-12s | %s\n" "Migration Version" "Status" "Applied At"
        echo "------------------------------------------------------------------------"
        for file in $(find "$MIGRATIONS_DIR" -maxdepth 1 -name "*.sql" | sort); do
            filename=$(basename "$file")
            version="${filename%.sql}"
            printf "%-35s | \033[0;33m%-12s\033[0m | %s\n" "$version" "PENDING" "-"
        done
        echo "========================================================================"
        return 0
    fi

    printf "%-35s | %-12s | %s\n" "Migration Version" "Status" "Applied At"
    echo "------------------------------------------------------------------------"

    for file in $(find "$MIGRATIONS_DIR" -maxdepth 1 -name "*.sql" | sort); do
        filename=$(basename "$file")
        version="${filename%.sql}"

        applied_at=$(run_sql "SELECT applied_at FROM gusby.schema_migrations WHERE version = '$version';" 2>/dev/null || true)

        if [[ -n "$applied_at" ]]; then
            printf "%-35s | \033[0;32m%-12s\033[0m | %s\n" "$version" "APPLIED" "$applied_at"
        else
            printf "%-35s | \033[0;33m%-12s\033[0m | %s\n" "$version" "PENDING" "-"
        fi
    done
    echo "========================================================================"
}

# ------------------------------------------------------------------------------
# Command: validate (Read-Only)
# ------------------------------------------------------------------------------
cmd_validate() {
    verify_target_db
    local actual_db
    actual_db=$(run_sql "SELECT current_database();")

    echo "[Gusby Migrations] Validating database connection..."
    echo "[Gusby Migrations] Verified connected database: $actual_db (Not server_lab)"

    # Check pg_trgm extension
    local trgm_installed
    trgm_installed=$(run_sql "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';" 2>/dev/null || true)
    if [[ "$trgm_installed" == "1" ]]; then
        echo "[Gusby Migrations] Extension 'pg_trgm': INSTALLED (OK)"
    else
        echo "[Gusby Migrations] Extension 'pg_trgm': NOT YET INSTALLED (Will be installed on 'up')"
    fi

    # Read-only check on tracker
    if has_tracker_table; then
        local count
        count=$(run_sql "SELECT count(*) FROM gusby.schema_migrations;" 2>/dev/null || echo "0")
        echo "[Gusby Migrations] Tracker table 'gusby.schema_migrations': READY ($count applied)"
    else
        echo "[Gusby Migrations] Tracker table 'gusby.schema_migrations': NOT INITIALIZED (Read-only validation passed)"
    fi

    # Validate migration SQL files exist and are readable
    local file_count
    file_count=$(find "$MIGRATIONS_DIR" -maxdepth 1 -name "*.sql" | wc -l)
    if [[ "$file_count" -eq 0 ]]; then
        echo "Error: No migration SQL files found in $MIGRATIONS_DIR." >&2
        exit 1
    fi
    echo "[Gusby Migrations] Discovered $file_count migration files in $MIGRATIONS_DIR."
    echo "[Gusby Migrations] Database connection and migration files validated successfully."
}

# ------------------------------------------------------------------------------
# Command: up (Explicit Mutation: Apply pending migrations)
# ------------------------------------------------------------------------------
cmd_up() {
    verify_target_db
    local actual_db
    actual_db=$(run_sql "SELECT current_database();")

    echo "========================================================================"
    echo "Executing Gusby Database Migrations"
    echo "Database: $actual_db"
    echo "Target:   $SAFE_DB_URL"
    echo "========================================================================"

    # Acquire PostgreSQL Advisory Lock (ID 847291) to prevent concurrent migrations across multiple sessions
    local lock_acquired
    lock_acquired=$(run_sql "SELECT pg_try_advisory_lock(847291);" 2>/dev/null || echo "false")
    if [[ "$lock_acquired" != "t" && "$lock_acquired" != "true" ]]; then
        echo "Error: Could not acquire PostgreSQL advisory lock (another migration is running in DB)." >&2
        exit 1
    fi

    # Release advisory lock on exit
    trap 'run_sql "SELECT pg_advisory_unlock(847291);" >/dev/null 2>&1 || true; cleanup' EXIT INT TERM

    init_migration_tracker

    # Find pending migrations
    local pending_migrations=()
    for file in $(find "$MIGRATIONS_DIR" -maxdepth 1 -name "*.sql" | sort); do
        filename=$(basename "$file")
        version="${filename%.sql}"
        applied_at=$(run_sql "SELECT applied_at FROM gusby.schema_migrations WHERE version = '$version';" 2>/dev/null || true)
        if [[ -z "$applied_at" ]]; then
            pending_migrations+=("$file")
        fi
    done

    if [[ ${#pending_migrations[@]} -eq 0 ]]; then
        echo "[Gusby Migrations] Database is up to date. No pending migrations."
        return 0
    fi

    echo "[Gusby Migrations] Found ${#pending_migrations[@]} pending migration(s)."

    # Pre-migration backup if requested and backup script exists
    if [[ "${BACKUP_BEFORE_MIGRATE:-true}" == "true" ]] && [[ -x "$ROOT_DIR/scripts/backup.sh" ]]; then
        echo "[Gusby Migrations] Creating pre-migration safety backup..."
        "$ROOT_DIR/scripts/backup.sh" pre-migrate || echo "Warning: Backup script finished with non-zero status; proceeding with caution."
    fi

    for file in "${pending_migrations[@]}"; do
        filename=$(basename "$file")
        version="${filename%.sql}"

        echo "[Gusby Migrations] Applying: $filename..."
        
        # Execute migration file
        if run_file "$file" > /dev/null; then
            # Record in tracker as single source of truth
            run_sql "
                INSERT INTO gusby.schema_migrations (version, applied_at)
                VALUES ('$version', now())
                ON CONFLICT (version) DO UPDATE SET applied_at = now();
            " > /dev/null
            echo "[Gusby Migrations] Successfully applied and recorded: $filename"
        else
            echo "========================================================================" >&2
            echo "CRITICAL ERROR: Failed to apply migration: $filename" >&2
            echo "Migration aborted. Database state preserved up to last successful migration." >&2
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
ACTION="${1:-status}"

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
        echo "Usage: $0 {status|validate|up}"
        echo "  status   - View applied and pending migrations (Read-Only)"
        echo "  validate - Test database connectivity and extension readiness (Read-Only)"
        echo "  up       - Apply pending migrations (Explicit mutation)"
        exit 1
        ;;
esac
