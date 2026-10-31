"""Dump row counts and sample rows from the E2E SQLite database as JSON.

Used by the Playwright persistence spec to assert that HTTP responses are
backed by actual persisted data, not by transient state.

Usage: python3 e2e/db_inspect.py <db_path>
Stdout contains exactly one JSON document. Non-zero exit means inspection
failed; output must never be parsed on failure.
"""

import json
import os
import sqlite3
import sys

if len(sys.argv) != 2:
    print("usage: db_inspect.py <db_path>", file=sys.stderr)
    sys.exit(2)

DB_PATH = sys.argv[1]
if not os.path.exists(DB_PATH):
    print(f"DB not found: {DB_PATH}", file=sys.stderr)
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
try:
    tables = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    counts = {}
    for t in tables:
        if t.startswith("sqlite_"):
            continue
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
        except sqlite3.Error as exc:
            print(f"inspect failed: {exc}", file=sys.stderr)
            sys.exit(1)

    def rows(table, order, limit=300):
        # Newest first (created_at DESC where possible) so the rail of rows
        # from the current E2E run is never truncated to history.
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT {limit}"
            )
        ]
except Exception as exc:  # noqa: BLE001
    print(f"inspect failed: {exc}", file=sys.stderr)
    sys.exit(1)

payload = {
    "tables": tables,
    "counts": counts,
    "knowledge_items": rows("knowledge_items", "created_at"),
    "entities": rows("entities", "created_at"),
    "relationships": rows("relationships", "created_at"),
    "processing_jobs": rows("processing_jobs", "created_at"),
    "captures": rows("captures", "created_at"),
    "relationship_types": rows("relationship_types", "created_at")
    if "relationship_types" in tables
    else [],
    "admin_audit_log": rows("admin_audit_log", "created_at")
    if "admin_audit_log" in tables
    else [],
}
print(json.dumps(payload, default=str))
