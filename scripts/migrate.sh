#!/usr/bin/env bash
# ==============================================================================
# Gusby Database Migration Tool
# ==============================================================================
# Usage:
#   ./scripts/migrate.sh status    - View migration status (Read-Only)
#   ./scripts/migrate.sh up        - Apply pending migrations (Manual mutation)
#
# Environment variables:
#   GUSBY_DATABASE_URL or DATABASE_URL (Required)
#   GUSBY_EXPECTED_DB                  (Optional verification: e.g. gusby_db)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Mutex locking against concurrent migration runs
LOCK_FILE="/tmp/gusby-migrate.lock"
exec 201>"$LOCK_FILE"
if ! flock -n 201; then
    echo "Error: Another migration process is running (locked on $LOCK_FILE)." >&2
    exit 1
fi
trap 'flock -u 201 2>/dev/null || true' EXIT INT TERM

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

if ! command -v psql &> /dev/null; then
    echo "Error: 'psql' client utility is not installed or not in PATH." >&2
    exit 1
fi

MIGRATIONS_DIR="$ROOT_DIR/migrations/gusby"
if [[ ! -d "$MIGRATIONS_DIR" ]]; then
    echo "Error: Migrations directory not found: $MIGRATIONS_DIR" >&2
    exit 1
fi

run_sql() {
    local sql="$1"
    psql "$DB_URL" -v ON_ERROR_STOP=1 -t -A -c "$sql"
}

run_file() {
    local file="$1"
    psql "$DB_URL" -v ON_ERROR_STOP=1 -f "$file"
}

# ------------------------------------------------------------------------------
# Verify Target Database Identity
# ------------------------------------------------------------------------------
verify_target_db() {
    if [[ "$DB_URL" =~ /server_lab([?].*)?$ ]]; then
        echo "CRITICAL SAFETY VIOLATION: Database URL points to 'server_lab'!" >&2
        exit 1
    fi

    local actual_db
    actual_db=$(run_sql "SELECT current_database();" 2>/dev/null || true)
    if [[ -z "$actual_db" ]]; then
        echo "Error: Failed to connect to PostgreSQL to verify database identity." >&2
        exit 1
    fi

    if [[ "$actual_db" == "server_lab" ]]; then
        echo "CRITICAL SAFETY VIOLATION: Connected to database 'server_lab'!" >&2
        echo "Gusby is strictly forbidden from modifying 'server_lab'." >&2
        exit 1
    fi

    local expected_db="${GUSBY_EXPECTED_DB:-gusby_db}"
    if [[ "$actual_db" != "$expected_db" ]]; then
        echo "CRITICAL SAFETY ERROR: Connected DB '$actual_db' does not match expected database '$expected_db'." >&2
        exit 1
    fi
}

has_tracker_table() {
    local count
    count=$(run_sql "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'gusby' AND table_name = 'schema_migrations';" 2>/dev/null || echo "0")
    [[ "$count" == "1" ]]
}

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
    echo "========================================================================"

    if ! has_tracker_table; then
        echo "Tracker table (gusby.schema_migrations) not initialized yet."
        echo "All migration files are PENDING."
        echo "------------------------------------------------------------------------"
        for file in $(find "$MIGRATIONS_DIR" -maxdepth 1 -name "*.sql" | sort); do
            version="$(basename "$file" .sql)"
            printf "%-35s | PENDING\n" "$version"
        done
        echo "========================================================================"
        return 0
    fi

    printf "%-35s | %-10s | %s\n" "Migration" "Status" "Applied At"
    echo "------------------------------------------------------------------------"
    for file in $(find "$MIGRATIONS_DIR" -maxdepth 1 -name "*.sql" | sort); do
        version="$(basename "$file" .sql)"
        applied_at=$(run_sql "SELECT applied_at FROM gusby.schema_migrations WHERE version = '$version';" 2>/dev/null || true)
        if [[ -n "$applied_at" ]]; then
            printf "%-35s | APPLIED    | %s\n" "$version" "$applied_at"
        else
            printf "%-35s | PENDING    | -\n" "$version"
        fi
    done
    echo "========================================================================"
}

# ------------------------------------------------------------------------------
# Command: up (Manual Mutation)
# ------------------------------------------------------------------------------
cmd_up() {
    verify_target_db
    local actual_db
    actual_db=$(run_sql "SELECT current_database();")

    echo "Applying migrations to database '$actual_db'..."

    # PG Advisory Lock (847291)
    local lock_acquired
    lock_acquired=$(run_sql "SELECT pg_try_advisory_lock(847291);" 2>/dev/null || echo "false")
    if [[ "$lock_acquired" != "t" && "$lock_acquired" != "true" ]]; then
        echo "Error: Could not acquire PostgreSQL advisory lock." >&2
        exit 1
    fi
    trap 'run_sql "SELECT pg_advisory_unlock(847291);" >/dev/null 2>&1 || true; flock -u 201 2>/dev/null || true' EXIT INT TERM

    init_migration_tracker

    local pending=()
    for file in $(find "$MIGRATIONS_DIR" -maxdepth 1 -name "*.sql" | sort); do
        version="$(basename "$file" .sql)"
        applied_at=$(run_sql "SELECT applied_at FROM gusby.schema_migrations WHERE version = '$version';" 2>/dev/null || true)
        if [[ -z "$applied_at" ]]; then
            pending+=("$file")
        fi
    done

    if [[ ${#pending[@]} -eq 0 ]]; then
        echo "Database is up to date. No pending migrations."
        return 0
    fi

    echo "Found ${#pending[@]} pending migration(s):"
    for file in "${pending[@]}"; do
        version="$(basename "$file" .sql)"
        echo "Applying $version..."
        if run_file "$file" > /dev/null; then
            run_sql "INSERT INTO gusby.schema_migrations (version, applied_at) VALUES ('$version', now()) ON CONFLICT (version) DO UPDATE SET applied_at = now();" > /dev/null
            echo "[OK] Applied: $version"
        else
            echo "Error: Failed to apply $version. Aborting." >&2
            exit 1
        fi
    done

    echo "All migrations applied successfully."
}

ACTION="${1:-status}"
case "$ACTION" in
    status)
        cmd_status
        ;;
    up)
        cmd_up
        ;;
    *)
        echo "Usage: $0 {status|up}"
        exit 1
        ;;
esac
