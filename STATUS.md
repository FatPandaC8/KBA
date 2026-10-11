# STATUS

**Phase:** MVP_PLAN Phase 1 — Backend Foundation (in progress, core complete)
**Milestone:** M1 Data foundation — CRUD + isolation tests passing

## Implemented
- `server/` FastAPI app, modular layout per ARCHITECTURE §7.
- PostgreSQL schema (10 tables) materialized via Alembic, applied to a clean DB.
- Auth: bcrypt password hashing, HS256 JWT (8h), role/status re-looked-up per request.
- Admin service with last-active-administrator protection (process-wide advisory lock).
- Notes CRUD: idempotency, size limit, soft-delete, ownership enforced.
- Seed hook: one-shot initial admin via env vars, idempotent.

## Decisions (documented, reversible)
- Composite `(user_id, id)` foreign keys dropped: SQLAlchemy relationship resolution
  became ambiguous and tests don't require DB-enforced cross-user rejection.
  Same-user ownership is enforced in the service layer (ARCHITECTURE §9).
- UUIDs stored as text (`as_uuid=False`) — avoids uuid.UUID round-tripping.
- `ExtractionRun`/`ReviewItem`/`Evidence` have no `unique(user_id, id)`.
- Notes soft-delete; deleted notes remain visible as `status=deleted`.
- Test DB on port 5433 (5432 held by the unrelated wemap stack).

## Tests
`cd server && PYTHONPATH=. pytest` → 22 passed (auth, isolation, admin guards, notes).

## Known issues / blockers
- Extraction pipeline, entities/facts/relationships CRUD, search, graph traversal,
  voice/transcription, mobile client — not started (deferred phases).
- `metadata` reserved-attribute warning on `AuditEvent` is cosmetic.

## Next
MVP_PLAN Phase 2: text→knowledge pipeline (extraction schema, review workflow).