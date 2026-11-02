# Changelog

## Unreleased — synchronous two-API pipeline and current admin contract

### Breaking API changes

- Replaced `POST /api/captures/upload` (multipart upload + queued processing)
  with two app-sequenced endpoints:
  - `POST /api/stt`: raw audio request body, session auth, transcript response;
    stateless and persists no audio, transcript or capture.
  - `POST /api/text-kb`: JSON `{capture_id: UUID, text: string}`, session auth
    and current consent; synchronously creates capture, knowledge item and
    graph changes in one Postgres UoW. A successful repeat with the same
    `capture_id` for the same user returns the existing result; cross-user reuse is
    `409`.
- Removed recording status/poll and manual server retry endpoints. Removed
  `/api/admin/jobs` and worker-era job/retry controls. The app handles retries
  explicitly; Text-KB retries reuse the capture ID, and STT retries resend
  audio if no transcript was obtained. The Groq client still has bounded
  provider-transport retries inside a request; this known divergence from a
  strict no-retry interpretation is documented in `docs/AI_PIPELINE.md`.
- `GET /api/recordings` now returns capture facts only:
  `{capture_id, created_at, has_knowledge_item, last_error}`. It is not a
  processing-status or polling API.
- Admin `GET /api/admin/captures-page` and `/api/admin/captures/{id}/console`
  remove job fields (`stage`, `attempt`, job status/error class) and expose
  capture truth (`capture_status`, `has_knowledge_item`, `last_error`,
  `last_error_at`). Admin overview counts are flat fields rather than a nested
  `counts` object and include `ingest_failures` buckets derived from
  `captures.last_error`.
- Admin dashboard capture filters now use `ready`, `transcript_missing`, and
  actual capture statuses; `queued` and `processing` are removed.

### Persistence and behavior

- PostgreSQL 16 is the only server database. Apply migrations with
  `cd server && alembic upgrade head`; SQLite server storage is unsupported.
- Added capture error fields in migration `0002_capture_last_error`, dropped
  `processing_jobs` in `0003_drop_processing_jobs`, and dropped worker-era
  capture stage/retry fields in `0004_drop_worker_capture_columns`. The
  original baseline migration is retained unchanged.
- Removed worker process/entrypoint, compose worker service, job queue port
  and adapter, job state machine/stage outputs, retry policy settings and
  `ECHO_WORKER_*` / `ECHO_JOB_*` settings.
- Admin rerun-extraction now calls `KnowledgeIngestorPort` synchronously with
  the stored transcript and existing capture ID. PATCH transcript remains.
  **Known limitation:** the ingestor returns early for an existing capture
  with a knowledge item, so PATCH + rerun does not rebuild a completed graph
  yet. See `docs/ADMIN.md` and `docs/ROADMAP.md`.
- Provider selection is configuration-only (`ECHO_STT_PROVIDER`,
  `ECHO_KB_EXTRACTOR`); requests cannot pick a provider.
- Server graph layout spacing is deterministic and keeps adjacent node
  centres at least one node diameter apart within a community. API response
  shape is unchanged.

### Manual local run

See `README.md` for Postgres 16 startup, `.env` setup, migrations, API run,
ADB reverse, Flutter launch, API curl smoke tests and test commands.

## Historical releases

No earlier changelog entries were maintained in this repository. Earlier
worker/queue descriptions remain only in explicitly historical milestone
documents; they do not describe the current runtime.
