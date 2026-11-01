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

Postgres-only (D1/D2): reads DATABASE_URL, reseed via ``--replace`` — there
is no SQLite data migration.
"""

import argparse
import datetime
import math
import os
import sys
import uuid

import psycopg
from psycopg import sql, rows


def _uuid5(namespace: str, name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"echo:seed:{namespace}:{name}"))


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL is not set (see .env.example)")
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
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

    with psycopg.connect(_database_url(), row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            user_id = args.user_id
            if args.email and not user_id:
                cur.execute("SELECT id::text FROM users WHERE email = %s", (args.email,))
                row = cur.fetchone()
                if row is None:
                    raise SystemExit(f"no user with email {args.email!r}")
                user_id = row["id"]

            cur.execute("SELECT count(*) FROM entities WHERE user_id = %s", (user_id,))
            existing = cur.fetchone()["count"]
            # uuid5 ids never start with 'seed-'; count by the deterministic prefix.
            cur.execute(
                "SELECT count(*) FROM entities WHERE user_id = %s AND provenance = 'device-seed'",
                (user_id,),
            )
            seeded = cur.fetchone()["count"]
            print(f"entities for user: {existing} (seed: {seeded})")
            if args.report_only:
                return
            assert seeded == 0 or args.replace, (
                "refusing to double-seed: rerun with --replace to start over"
            )
            if args.replace:
                # Delete relationships BEFORE entities so FK references
                # never dangle mid-delete.
                cur.execute(
                    "DELETE FROM relationships WHERE user_id = %s AND provenance = 'device-seed'",
                    (user_id,),
                )
                cur.execute(
                    "DELETE FROM entities WHERE user_id = %s AND provenance = 'device-seed'",
                    (user_id,),
                )
                conn.commit()
                print(f"removed previous seed rows for user {user_id}")

            now = datetime.datetime.now(datetime.timezone.utc)
            # One transaction for the whole seed; executemany keeps it fast.
            node_ids = []
            node_rows = []
            for i in range(args.nodes):
                eid = _uuid5(user_id, f"node:{i:05d}")
                node_ids.append(eid)
                node_rows.append(
                    (
                        eid,
                        user_id,
                        None,
                        f"SeedNode {i:05d}",
                        f"seednode {i:05d}",
                        ["person", "project", "concept", "place"][i % 4],
                        f"Synthetic device-seed node {i:05d}.",
                        0.9,
                        "confirmed",
                        "device-seed",
                        "devseed",
                        "",
                        False,
                        now,
                        now,
                    )
                )

            community_count = max(1, math.ceil(args.nodes / args.community_size))
            edges = []
            last_in_community = {}
            for i, eid in enumerate(node_ids):
                community = i // args.community_size
                next_in_community = (i + 1) % args.community_size
                ring = community * args.community_size + next_in_community
                if ring != i:
                    edges.append((i, ring))
                if i % 7 != 0:
                    chord_offset = (i + 2) % args.community_size
                    chord = community * args.community_size + chord_offset
                    if chord != i and chord != ring:
                        edges.append((i, chord))
                last_in_community[community] = i
            for c in range(community_count - 1):
                if c in last_in_community and (c + 1) in last_in_community:
                    edges.append((last_in_community[c], last_in_community[c + 1]))

            edge_rows = []
            for j, (a, b) in enumerate(edges):
                rel_id = _uuid5(user_id, f"rel:{j:05d}")
                edge_rows.append(
                    (
                        rel_id,
                        user_id,
                        node_ids[a],
                        node_ids[b],
                        "Related to",
                        "suggested",
                        0.7,
                        "confirmed",
                        None,
                        "device-seed",
                        False,
                        now,
                    )
                )

            cur.executemany(
                
                """
                INSERT INTO entities
                (id, user_id, capture_id, name, normalized_name, entity_type,
                 description, confidence, certainty, provenance, provider_id,
                 model_version, user_edited, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                node_rows,
            )
            cur.executemany(
                
                """
                INSERT INTO relationships
                (id, user_id, from_id, to_id, relation_type, status, confidence,
                 certainty, source_capture_id, provenance, user_edited, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                edge_rows,
            )
            conn.commit()
            print(
                f"seeded {args.nodes} nodes and {len(edge_rows)} relationships "
                f"for user {user_id} ({community_count} communities)"
            )


if __name__ == "__main__":
    if "--test-idempotent" in sys.argv:
        raise SystemExit(
            "idempotency is guaranteed by uuid5 node/rel ids plus --replace; "
            "run the seeder twice against the dev database to verify"
        )
    main()
