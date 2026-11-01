# ADR: PostgreSQL-only persistence and job pipeline re-architecture

Status: Accepted (owner-approved design; corrections applied)
Date: 2026-11-01
Scope: `server/`

## Decision summary

D1. SQLite is removed entirely. PostgreSQL 16 (local Docker) is the only database.
D2. No data migration from SQLite. Local data is recreated by the seed script.
D3. Everything is driven by `DATABASE_URL`/env so a hosted DB later is config-only.
    Session-level server features (advisory locks, LISTEN/NOTIFY, long-lived
    server-side prepared statements) are not used.
D4. Alembic owns the schema. No schema creation at application start. There was
    no prior Alembic config in the repo, so `alembic.ini` + a baseline migration
    are new.
D5. No CI config exists in the repo, so no CI Postgres service is added.
D6. PostgreSQL 16.
D7. Failed jobs: 3 attempts total (2 retries). Backoff: 30 s after attempt 1,
    120 s after attempt 2, then `failed`. ±20% jitter on each delay. Delays,
    jitter and max attempts are Settings values, env-overridable.
D8. The worker runs as a SEPARATE process: `python -m app.worker` and its own
    compose service. The in-process worker thread is removed from the FastAPI
    lifespan. The worker owns its own pool and handles SIGTERM gracefully
    (finish or release the current job's lease). This is a behavior change and
    is recorded in the CHANGELOG.

## Root causes of the original failure chain (investigated 2026-11-01)

All three findings come from source inspection at base commit `a8427ea` plus
incident reports. The incidents were not independently reproduced against the
old runtime; claims marked "structural" are code-level findings.

1. **UNIQUE violation on `entities.user_id` (`_save_extraction`).**
   Structural. The base schema enforces "one self entity per user" only
   through a partial unique index:

   ```sql
   -- SQLite (base, app/infrastructure/database/__init__.py:282)
   CREATE UNIQUE INDEX idx_entities_one_self_per_user
     ON entities(user_id) WHERE is_self = 1;
   -- Postgres (working copy, persistence/postgres.py:363-368), same rule
   ON entities(user_id) WHERE is_self = TRUE;
   ```

   Several code paths can add a self entity: `SqliteUserRepository.save`
   inserts `"Me"` directly (`persistence/__init__.py:205-238`), both
   extractors emit capture-scoped `is_self=True` placeholders via
   `extraction/first_person.py`, and `_save_extraction` substitutes a
   looked-up self entity into the extracted set (`use_cases/jobs.py`) with
   lookup and insert in separate transactions. A race between the lookup and
   the insert — or two flows inserting a self entity close together — hits
   the index, which lives only in the DB and is unknown to the application.
   Fix (R3): `EntityRepo.get_or_create_self(user_id)` performs an atomic
   `INSERT ... ON CONFLICT (user_id) WHERE is_self DO NOTHING` + SELECT in
   one transaction; the partial unique index stays as a safety net; the
   redundant non-unique self index (`postgres.py:708-712`) is dropped.

2. **`_record_failure` missing / transaction left open.** Corrected: at base
   commit `a8427ea`, `ProcessCaptureUseCase._record_failure` exists at
   `server/app/application/use_cases/jobs.py:558` and is called at line 294.
   The real defect is transaction ownership: every repository call commits on
   its own thread-local connection, there is no rollback boundary around a
   failed extraction, and the exception handler calls `_record_failure`
   without first logging the original traceback. A failure while recording
   failure therefore leaves the job/lease state half-written and can mask the
   original error. See the anomaly note below.

3. **`database is locked` in authenticate → session_repo.touch.**
   Structural. `SqliteSessionRepository.touch` executes an `UPDATE` and a
   commit on every authenticated request (`persistence/__init__.py:331-344`),
   even though its WHERE clause throttles actual timestamp changes to once
   per 60 seconds. Write-on-every-read combined with an open write
   transaction during concurrent writes is consistent with SQLite lock
   contention. No incident logs are available to prove which connection held
   the write. Fix (R6): one conditional statement
   (`UPDATE sessions SET last_used_at = now() WHERE token_hash = %s AND
   last_used_at < now() - interval '60 seconds'`) executed only in a short
   transaction; fresh sessions cause no write.

   Related structural finding: SQLite foreign keys were enabled by pragma but
   the `knowledge_embeddings` table declared no foreign key at all
   (`database/__init__.py:186-193`), so embedding rows could reference
   missing items — the observed FK violation surfaces only when the Postgres
   schema enforces it. Under the new design embeddings are written only for
   rows that exist in the same transaction and the FK stays enforced.

### Anomaly: the incident log showing `AttributeError: ... jobs.py:294`

Both persisted points in the working-copy history — base commit `a8427ea`
and the two dangling `WIP on ...` stash snapshots found via `git fsck`
(`ff40b06f`, `5b128124`) — contain `def _record_failure` (at line 558 or
590) while `jobs.py:294` calls it. No committed, stashed, or dangling object
contains a state where the call exists without the method. The running server
that produced the `AttributeError` was therefore executing a working-copy
state that was never snapshotted (autosave checkpoints captured only some
states), or had loaded a stale module copy from an earlier checkpoint.
`a8427ea` is the closest recoverable state and it does not reproduce the
symptom, so the failure-path rewrite in this ADR targets the underlying
defect (transaction ownership, missing original-error logging, unconditional
attempts bookkeeping) rather than the literal missing-method traceback.

## Module map (old → new)

| Old location | New location | Notes |
|---|---|---|
| `app/infrastructure/database/` (DatabaseManager) | deleted | pool + UoW replace it |
| `app/adapters/outbound/persistence/__init__.py` (SQLite repos, 1858 lines) | deleted | |
| `app/adapters/outbound/persistence/factory.py` | deleted | single backend, no branching (R10) |
| `app/adapters/outbound/persistence/postgres.py` (schema + pool) | `persistence/postgres/pool.py`, `uow.py` | schema → Alembic |
| `app/adapters/outbound/persistence/postgres_repos.py` (1999 lines) | `persistence/postgres/{users,sessions,entities,relationships,knowledge,duplicate_candidates,embeddings,captures,eval_records,jobs,relationship_types,tombstones,record_supports,admin}.py` | one module per port (R2) |
| `app/application/ports/__init__.py` (260+ lines, one file) | `ports/uow.py`, `ports/jobs.py` added; keep aggregate port classes exported from the package | R2 |
| `app/application/use_cases/admin_console.py` raw SQL | moved behind read ports in `persistence/postgres/admin.py` | R8 |
| `app/application/use_cases/jobs.py` `_cleanup_orphans` raw SQL + `entity_repo.db.get_connection()` | moved behind ports | R8 |
| SQLite `_layout_graph` (persistence/__init__.py:78) and `domain/graph_layout.py` duplicate | one pure `domain/graph_layout.py`; it no longer imports application DTOs (DTO mapping happens in the application GraphQueryService); SQLite copy deleted with the adapter | R6 |
| `app/main.py` lifespan worker thread + global container import | lifespan creates/closes the API pool only; worker is a separate process | D8 |
| `tools/migrate_self_entities.py` | deleted (SQLite-only tool, superseded by `get_or_create_self`) | |

## Transaction model (R1, R3, R7)

- `UnitOfWork` port: `with uow:` yields repositories bound to ONE connection
  and transaction. Commit on clean exit, rollback on any exception.
  Repositories never commit; application/domain code never sees a connection
  or SQL.
- Repositories obtain the connection from the UoW context (an ambient
  context-set connection). A repository method invoked with no open UoW runs
  its own short transaction so standalone reads keep working; the intended
  pattern is a UoW per use-case operation.
- The pool is created in the FastAPI lifespan (API) and by the worker entry
  point (worker). No global connections, no import-time initialization.
- Settings owns `DATABASE_URL`, pool min/max, connect timeout,
  statement_timeout, idle_in_transaction_session_timeout, and job backoff
  values; all env-overridable with documented defaults (R7).
- `psycopg.errors.*` (constraint violations, serialization failures) are
  caught at the adapter layer and translated to domain errors (R9).

## Self entity and ingest pipeline (R3, R4)

- `get_or_create_self(user_id)` behind `EntityRepositoryPort`: atomic
  upsert + select inside the caller's transaction, with the partial unique
  index retained as a safety net. The self entity is never deleted by dedup
  or orphan pruning.
- Ingest stages, order defined in exactly one place
  (`application/use_cases/ingest.py` `STAGE_ORDER`) and covered by a test:
  1. normalize first-person references
  2. resolve entities (dedup bands, tombstones)
  3. link (relationships, registry normalization)
  4. embeddings for rows that exist in the same transaction
  5. prune orphans (never the self entity; merge-supporting rows kept)
- Stages are plan-then-apply: pure planning functions produce the write plan;
  the whole result is applied inside ONE UoW. FKs stay enforced.

## Job pipeline (R5, D7, D8)

State machine (pure domain module `domain/job_state.py`, unit-tested):

```text
queued --claim--> running
running --complete--> ready (terminal)
running --fail(retryable, attempts left)--> queued (retry_at scheduled)
running --fail(exhausted or non-retryable)--> failed (terminal)
running --reclaim_stale--> queued (attempt incremented)
```

- `JobQueuePort`: `claim()` uses `FOR UPDATE SKIP LOCKED` with a lease +
  heartbeat; `complete()`, `fail(error, attempt, retry_at)`,
  `heartbeat()`, `reclaim_stale()`.
- Reclaiming a stale lease counts as one attempt, so a job that kills its
  worker cannot loop forever: the third loss terminates the job as `failed`.
- Job vocabulary (`queued` / `running` / `ready` / `failed`) is unchanged;
  only a `next_attempt_at` column is added for backoff scheduling.
- JobRunner flow: claim (short tx) → process (NO transaction; LLM/network
  happens here) → persist (one UoW) → complete (tx). On any exception:
  rollback, log the ORIGINAL traceback with job_id/capture_id/attempt, then
  record failure in a NEW transaction. The loop survives any single-job
  failure.
- Worker entry point `python -m app.worker`: own pool, SIGTERM-graceful
  (finish-or-release the current lease), runs as a compose service.

## SQL exceptions to the layering rule (R8)

Concrete SQL (`CREATE TABLE`, raw DDL/test bootstrap) is allowed only in:

- `alembic/` migrations (baseline and future migrations),
- test database setup (`tests/.../postgres_testinfra.py` and compose scripts).

Everything else — including `admin_console.py`, `jobs.py` cleanup paths, and
any future repo — must go through ports implemented in
`app/adapters/outbound/persistence/postgres/`. Enforced by an architecture
test that fails on: `psycopg`(2|3) or adapter imports in domain/application,
`sqlite3` anywhere in `app/`, and SQL-looking statements outside the
allowed DSP locations.

## Types and mapping (R9)

- UUID primary/foreign keys, `TIMESTAMPTZ`, `BOOLEAN`, `JSONB`.
- Case-insensitive matching uses `lower()` expression indexes (chosen over
  `citext` to avoid extension management).
- Domain entities keep ISO-string timestamps and string ids; adapters convert
  datetime/uuid at the row boundary. Domain unchanged ⇒ API unchanged.

## Testing

- All persistence tests run against real PostgreSQL: a template database is
  cloned once per session/xdist worker; tests truncate between cases. No
  SQLite, no mocked database layer in integration tests.
- Per-port contract tests live in `tests/integration/persistence/` and are
  reused for every adapter (today: only the Postgres adapter exists).
- Existing behavior-driven suites (Client Security, Admin Console, Graph M3,
  Pipeline M3, Admin Dashboard, unit) run against Postgres with test strategy
  overrides (fake extraction/embeddings/LLM).
- SQLite-baseline comparison numbers come from the detached worktree at
  `a8427ea`, not the pre-refactor commit `5e869fb`.

## Risks / open items

- Postgres upsert conflict targets must match partial-index semantics;
  regression covered by the same-user capture test.
- `FOR UPDATE SKIP LOCKED` claim with `next_attempt_at` scheduling is new
  behavior on the claim path; covered by concurrency and retry tests.
- Hosted-PostgreSQL move is config-only but untested there (no hosted env).
