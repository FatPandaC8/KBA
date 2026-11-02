# Project status and roadmap

Updated 2026-11-02 to match the checked-in Postgres + two-API implementation.
For exact setup, see `README.md`; historical milestone reports retain their
original state and are not the current runbook.

## Current implementation status

| Capability | Current state |
|---|---|
| Android voice capture | Implemented; records locally, maximum duration configurable (default 120 s). |
| STT | `POST /api/stt`, raw audio body, synchronous, local faster-whisper; persists nothing. |
| Text-to-knowledge | `POST /api/text-kb`, synchronous; same-user `capture_id` replay is idempotent; capture/item/graph commit in one Postgres UoW. |
| Error handling | Typed request errors; retries are explicit user actions. Capture failure details may be stored as `last_error` for admin. |
| Knowledge extraction | Startup-selected local rule-based provider or Groq; no per-request provider selection and no silent fallback. |
| Graph persistence/search | PostgreSQL 16; entity resolution, relationship registry, tombstones, embeddings and lexical fallback. |
| Graph layout | Deterministic server layout; community spacing tested; client paints graph edges and nodes. |
| Authentication/consent | Email/password, verification, revocable sessions, per-user isolation, versioned provider consent. |
| Mobile graph | Record and Graph tabs; graph refresh is a client read, not job polling. |
| Admin | React dashboard: Overview, Users, Captures, Knowledge Graph (read-only), Audit Logs. Capture status/error from capture truth; transcript correction and synchronous Text-KB call. **Gap:** completed captures return the existing idempotent result, so a transcript edit does not currently rebuild that capture's graph. |
| Server persistence | PostgreSQL 16 only, Alembic migrations, ports/UoW. Flutter's on-device note store remains SQLite. |
| Legacy Playwright suite | Not migrated: it still targets the removed SQLite/worker/upload/status contracts. See `e2e/README.md`. |

## Next work

1. **Finish documentation/runbook validation** — keep README, env example,
   persistence architecture, admin guide and changelog aligned with current
   routes and setup commands.
2. **Migrate Playwright E2E suite** — replace SQLite/job fixtures and upload /
   status polling with Postgres fixtures and the `/api/stt` → `/api/text-kb`
   flow. Until then, use `python -m pytest server/tests -q` and the manual
   device steps in the root README.
3. **Resolve bounded Groq transport retry behavior** — `GroqChatClient`
    currently retries provider transport errors inside a request. Decide and
    implement alignment with the owner-approved no-retry/backoff requirement.
4. **Make admin re-extraction replace completed output** — add an explicit
   rebuild/update contract that can reprocess a corrected transcript without
   violating normal Text-KB idempotency or creating duplicate graph data.
5. **Provider/quality evaluation** — measure STT quality, extraction precision
    and graph correctness before making quality claims.
6. **Production readiness** — production secrets, HTTPS, backups, privacy/data
   retention policy, account deletion verification and deployment automation.

## Explicit exclusions

- No worker process, durable job queue, poll/status API or automatic capture
  retry schedule.
- No request-level provider selector or silent local fallback from a selected
  hosted provider.
- No user-visible transcript API, chatbot/GraphRAG, multi-hop inference, or
  document ingestion in the current MVP.
- No migration of old SQLite **server** data. Server persistence is Postgres;
  the mobile app's private on-device SQLite store is separate.
- No production deployment claim until the production readiness work above is
  completed and verified.
