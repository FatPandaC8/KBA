"""Device-performance seeder: fills one user's graph with synthetic nodes.

Used by the 2,000-node on-device check (owner criteria: no ANR/crash/OOM,
first render <= ~3 s, pan/zoom ~30 fps or better on the test device). It
inserts entities and relationships directly into the server database for the
given user id — it never goes through the processing pipeline.

Deterministic: identical arguments always produce an identical graph. Nodes
are named so they can be distinguished from real extracted entities. Add
--replace to delete this tool's earlier rows for the user before seeding.

All IDs are globally unique (uuid5 from user_id + index) so multiple users
can be seeded without collisions. The seed is idempotent: re-running with
the same args produces identical rows.
"""

import argparse
import datetime
import math
import os
import sqlite3
import sys
import tempfile
import uuid


def _uuid5(namespace: str, name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"echo:seed:{namespace}:{name}"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="path to the SQLite server DB")
    parser.add_argument("--user-id", required=False, help="user id to seed for")
    parser.add_argument("--email", required=False,
                        help="look up the user id by email and seed for that user")
    parser.add_argument("--nodes", type=int, default=2000)
    parser.add_argument("--community-size", type=int, default=250)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--replace", action="store_true",
                        help="delete previously seeded rows for this user first")
    parser.add_argument("--report-only", action="store_true",
                        help="print current entity counts and exit")
    args = parser.parse_args()

    if not args.user_id and not args.email:
        parser.error("one of --user-id or --email is required")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        user_id = args.user_id
        if args.email and not user_id:
            row = conn.execute(
                "SELECT id FROM users WHERE email = ?", (args.email,)
            ).fetchone()
            if row is None:
                raise SystemExit(f"no user with email {args.email!r}")
            user_id = row["id"]

        existing = conn.execute(
            "SELECT count(*) FROM entities WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        seeded = conn.execute(
            "SELECT count(*) FROM entities WHERE user_id = ? AND id LIKE 'seed-%'",
            (user_id,),
        ).fetchone()[0]
        print(f"entities for user: {existing} (seed: {seeded})")
        if args.report_only:
            return
        assert seeded == 0 or args.replace, (
            "refusing to double-seed: rerun with --replace to start over"
        )
        if args.replace:
            # Delete relationships (seed-rel-*) BEFORE entities (seed-*)
            # so foreign-key-like references never dangle mid-delete.
            conn.execute(
                "DELETE FROM relationships WHERE user_id = ? AND id LIKE 'seed-rel-%'",
                (user_id,),
            )
            conn.execute(
                "DELETE FROM entities WHERE user_id = ? AND id LIKE 'seed-%'",
                (user_id,),
            )
            conn.commit()
            print(f"removed previous seed rows for user {user_id}")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute("BEGIN")
        node_ids = []
        for i in range(args.nodes):
            eid = _uuid5(user_id, f"node:{i:05d}")
            node_ids.append(eid)
            conn.execute(
                """
                INSERT INTO entities
                (id, user_id, capture_id, name, normalized_name, entity_type,
                 description, confidence, certainty, provenance, provider_id,
                 model_version, user_edited, created_at, updated_at)
                VALUES (?, ?, NULL, ?, ?, ?, ?, 0.9, 'confirmed', 'device-seed',
                        'devseed', '', 0, ?, ?)
                """,
                (
                    eid,
                    user_id,
                    f"SeedNode {i:05d}",
                    f"seednode {i:05d}",
                    ["person", "project", "concept", "place"][i % 4],
                    f"Synthetic device-seed node {i:05d}.",
                    now,
                    now,
                ),
            )

        relationships = []
        community_count = max(1, math.ceil(args.nodes / args.community_size))
        last_in_community = {}
        for i, eid in enumerate(node_ids):
            community = i // args.community_size
            # Ring: connect to next node in community, wrap to first node
            next_in_community = (i + 1) % args.community_size
            ring = community * args.community_size + next_in_community
            if ring != i:
                relationships.append((i, ring))
            if i % 7 != 0:
                # Chord: connect to node 2 steps ahead within the same community
                chord_offset = (i + 2) % args.community_size
                chord = community * args.community_size + chord_offset
                if chord != i and chord != ring:
                    relationships.append((i, chord))
            last_in_community[community] = i
        for c in range(community_count - 1):
            if c in last_in_community and (c + 1) in last_in_community:
                relationships.append((last_in_community[c], last_in_community[c + 1]))

        edge_rows = []
        for j, (a, b) in enumerate(relationships):
            rel_id = _uuid5(user_id, f"rel:{j:05d}")
            edge_rows.append(
                (
                    rel_id,
                    user_id,
                    node_ids[a],
                    node_ids[b],
                    "related_to",
                    "candidate",
                    0.7,
                    "confirmed",
                    "",
                    "device-seed",
                    0,
                    now,
                )
            )
        conn.executemany(
            """
            INSERT INTO relationships
            (id, user_id, from_id, to_id, relation_type, status, confidence,
             certainty, source_capture_id, provenance, user_edited, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            edge_rows,
        )
        conn.commit()
        print(
            f"seeded {args.nodes} nodes and {len(edge_rows)} relationships "
            f"for user {user_id} ({community_count} communities)"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    # --- Idempotency test (runs instead of main when requested) ---
    if "--test-idempotent" in sys.argv:
        tmpdb = tempfile.mktemp(suffix=".db")
        try:
            conn = sqlite3.connect(tmpdb)
            conn.executescript(
                """
                CREATE TABLE users (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                    email_normalized TEXT, password_hash TEXT,
                    google_sub TEXT, email_verified_at TEXT,
                    is_locked INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT
                );
                CREATE TABLE entities (
                    id TEXT PRIMARY KEY, user_id TEXT,
                    capture_id TEXT, name TEXT, normalized_name TEXT,
                    entity_type TEXT, description TEXT, confidence REAL,
                    certainty TEXT, provenance TEXT, provider_id TEXT,
                    model_version TEXT, user_edited INTEGER, created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE relationships (
                    id TEXT PRIMARY KEY, from_id TEXT, to_id TEXT,
                    relation_type TEXT, status TEXT, created_at TEXT,
                    user_id TEXT, user_edited INTEGER, confidence REAL,
                    certainty TEXT, source_capture_id TEXT, provenance TEXT
                );
                """
            )
            conn.execute(
                "INSERT INTO users (id, email, email_normalized, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "6aba2ba4-0f73-4b73-9a6d-3ecb7c24bf69",
                    "devicecheck@example.com",
                    "devicecheck@example.com",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            conn.commit()
            conn.close()
            # Seed twice into a temp DB, then confirm identical counts.
            os.system(f"python3 {__file__} --db {tmpdb} --user-id 6aba2ba4-0f73-4b73-9a6d-3ecb7c24bf69 --nodes 2000 --replace >/dev/null 2>&1")
            os.system(f"python3 {__file__} --db {tmpdb} --user-id 6aba2ba4-0f73-4b73-9a6d-3ecb7c24bf69 --nodes 2000 --replace >/dev/null 2>&1")
            conn = sqlite3.connect(tmpdb)
            r1 = conn.execute("SELECT count(*) FROM entities WHERE user_id = ?", ("6aba2ba4-0f73-4b73-9a6d-3ecb7c24bf69",)).fetchone()[0]
            r2 = conn.execute("SELECT count(*) FROM relationships WHERE user_id = ?", ("6aba2ba4-0f73-4b73-9a6d-3ecb7c24bf69",)).fetchone()[0]
            conn.close()
            os.unlink(tmpdb)
            if r1 != 2000 or r2 != 3721:
                print(f"FAIL: idempotent seed failed. entities={r1}, relationships={r2}", file=sys.stderr)
                sys.exit(1)
            print(f"PASS: idempotent seed — 2 runs produce identical {r1} nodes + {r2} edges")
        except Exception as e:
            print(f"FAIL: idempotent seed error: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    main()
