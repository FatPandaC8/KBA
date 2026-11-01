"""Backfill Echo self entities and remove non-self orphan entities.

Run with --dry-run first. --apply is development-only and intentionally
destructive; it is never invoked during application startup.
"""
import argparse
import os
import sqlite3
import uuid


def report(conn):
    users = conn.execute("SELECT id, email FROM users ORDER BY email").fetchall()
    for user_id, email in users:
        orphan_rows = conn.execute(
            """SELECT e.name FROM entities e
               WHERE e.user_id=? AND e.is_self=0
                 AND NOT EXISTS (SELECT 1 FROM relationships r
                   WHERE r.user_id=e.user_id AND (r.from_id=e.id OR r.to_id=e.id))
               ORDER BY e.created_at LIMIT 5""", (user_id,)
        ).fetchall()
        orphan_count = conn.execute(
            """SELECT count(*) FROM entities e
               WHERE e.user_id=? AND e.is_self=0
                 AND NOT EXISTS (SELECT 1 FROM relationships r
                   WHERE r.user_id=e.user_id AND (r.from_id=e.id OR r.to_id=e.id))""", (user_id,)
        ).fetchone()[0]
        zero_capture_count = conn.execute(
            """SELECT count(*) FROM captures c WHERE c.user_id=? AND NOT EXISTS
               (SELECT 1 FROM entities e JOIN relationships r
                ON r.user_id=? AND (r.from_id=e.id OR r.to_id=e.id)
                WHERE e.user_id=? AND e.capture_id=c.id AND e.is_self=0)""",
            (user_id, user_id, user_id),
        ).fetchone()[0]
        candidates = conn.execute(
            """SELECT name FROM entities WHERE user_id=? AND lower(trim(name)) IN
               ('i','me','myself','we','us')
               ORDER BY name""", (user_id,)
        ).fetchall()
        missing = conn.execute(
            "SELECT count(*) FROM entities WHERE user_id=? AND is_self=1", (user_id,)
        ).fetchone()[0] == 0
        print(f"{email}: missing_self={int(missing)} orphans={orphan_count} "
              f"samples={[row[0] for row in orphan_rows]} "
              f"pronoun_candidates={[row[0] for row in candidates]} "
              f"captures_zero_after_orphans={zero_capture_count}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.getenv("ECHO_DB_PATH", "server/echo_backend.db"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.getenv("ECHO_ENV", "development").lower() == "production":
        raise SystemExit("Refusing self-entity migration in production")
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=ON")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(entities)")}
    if "is_self" not in columns:
        conn.execute("ALTER TABLE entities ADD COLUMN is_self INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_one_self_per_user ON entities(user_id) WHERE is_self=1")
    report(conn)
    if not args.apply:
        conn.close()
        return
    conn.execute("BEGIN")
    users = conn.execute("SELECT id, created_at, updated_at FROM users ORDER BY id").fetchall()
    for user_id, created_at, updated_at in users:
        exists = conn.execute("SELECT 1 FROM entities WHERE user_id=? AND is_self=1", (user_id,)).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO entities
                   (id,user_id,capture_id,name,normalized_name,entity_type,description,
                    confidence,certainty,provenance,provider_id,model_version,user_edited,is_self,created_at,updated_at)
                   VALUES (?,?,NULL,'Me','me','self','',1.0,'confirmed','system','','',0,1,?,?)""",
                (str(uuid.uuid4()), user_id, created_at, updated_at),
            )
    conn.execute(
        """DELETE FROM entities WHERE is_self=0 AND NOT EXISTS
           (SELECT 1 FROM relationships r WHERE r.user_id=entities.user_id
            AND (r.from_id=entities.id OR r.to_id=entities.id))"""
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
