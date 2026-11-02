# Server persistence and synchronous ingest architecture

Status: Accepted implementation (supersedes the worker/job-queue portions of
the 2026-11-01 persistence ADR)
Scope: `server/`

## Current decisions

1. **PostgreSQL 16 only** for server persistence. There is no server SQLite
   adapter or fallback. The Flutter app separately uses its local SQLite store
   for device notes.
2. `DATABASE_URL` selects the server database. Alembic owns schema changes;
   application startup does not create or migrate the schema.
3. The server exposes two independent synchronous ingestion APIs. The mobile
   app invokes them in order; there is no umbrella endpoint.
4. There is no worker process, processing-job table, queue, status poll,
   capture-level retry/backoff, lease or `SKIP LOCKED` claim path. A
   slow/failing request ends; the user explicitly retries in the app.
5. Providers are selected at server startup from environment/configuration.
   Requests cannot select providers.
6. `POST /api/stt` is stateless: it accepts raw audio bytes and returns a
   transcript. It creates no capture and persists neither audio nor transcript.
7. `POST /api/text-kb` receives a client-generated UUID `capture_id` and text.
   For the same user, repeating a completed capture ID returns its existing
   result. A capture ID owned by another user is a conflict (`409`).
8. Text-KB writes capture + knowledge item + graph data in one unit of work
   (UoW). On failure that UoW rolls back. The optional admin failure record
    (`captures.last_error`, `last_error_at`) is written separately after
    rollback, so it cannot leave partial graph data.

**Implementation note:** the Groq HTTP client currently has bounded provider
transport retries (`ECHO_LLM_MAX_RETRIES`, default 3) and one optional schema
repair call. These execute inside the Text-KB request; they are not job
retries or persisted retry/backoff. This is a remaining deviation from the
owner's strict “no retry/backoff” decision and should be resolved explicitly.

## Request flows and contracts

```text
Flutter recorder
    │ raw audio (up to configured byte/duration limits)
    ▼
POST /api/stt  [session auth]
    │ {transcript, language, provider, elapsed_ms}
    │ nothing persisted
    ▼
Flutter holds transcript in memory
    │ {capture_id: UUID, text: transcript}
    ▼
POST /api/text-kb  [session auth + current consent]
    │ validate → extract → normalize first person → resolve → link →
    │ deduplicate → write embeddings → prune orphans → commit one UoW
    ▼
{capture_id, knowledge_item_id, entities_added,
 relationships_added, provider, elapsed_ms}
```

`POST /api/stt` uses the raw request body, not multipart. It requires a session
but not Text-KB consent; the route does no writes. Limits default to 25 MiB
(`ECHO_MAX_UPLOAD_BYTES`) and 120 decoded seconds
(`ECHO_MAX_VOICE_SECONDS`). Invalid audio/language is a typed client error;
over-limit audio is `413`.

`POST /api/text-kb` requires a canonical UUID and non-empty text; text length
defaults to 20,000 characters (`ECHO_MAX_TEXT_KB_CHARS`). It requires a session
and current consent. Empty/malformed input is `400`, too-long text is `422`,
cross-user capture-ID reuse is `409`, and only actual provider/server faults
are `5xx`. Error responses use `detail: {class, message}`.

Capture journal reads (`GET /api/recordings`) expose only `capture_id`,
`created_at`, `has_knowledge_item`, and `last_error`. They do not represent
in-progress work and are not for polling. Ordinary client APIs never return
transcripts; admin capture routes can read/correct the stored transcript.

## Ports and composition root

The application ports contain no HTTP or SQL types:

- `AudioTranscriptionPort.transcribe(audio, content_type, language_hint?)`
  returns `TranscriptDTO(text, language, confidence, provider)`. The current
  adapter is `FasterWhisperSpeechAdapter` (`ECHO_STT_PROVIDER=faster_whisper`).
- `KnowledgeIngestorPort.ingest(user_id, capture_id, text)` returns
  `IngestResultDTO`. It has no audio/STT dependency. The current adapters are
  local rule-based extraction (`ECHO_KB_EXTRACTOR=local`) and Groq
  (`ECHO_KB_EXTRACTOR=groq`, with `ECHO_LLM_PROVIDER=groq` and server-side
  `GROQ_API_KEY`). Missing/unknown providers fail closed.

`server/app/api/dependencies.py` is the composition root. It selects adapters
from `ServerSettings`; never from request parameters. `server/app/application/
use_cases/text_kb.py` implements the synchronous Text-KB use case. Its
architecture test forbids importing the speech/STT package; the inverse
boundary is also tested.

## Unit-of-work and ordering guarantees

`UnitOfWork` binds Postgres repositories to one connection/transaction. A
clean exit commits; an exception rolls back. The Text-KB write set includes
the capture, knowledge item, resolved entities, relationships, support rows,
duplicate candidates and embeddings. Extraction/provider work happens before
the write UoW; persistence and graph changes are atomic.

The graph application flow preserves these invariants:

1. First-person placeholders normalize to the single canonical self entity
   before relationship endpoints are resolved (Bug #2 regression coverage).
2. Resolution/tombstone handling precedes link planning; registry meanings
   are normalized before relationship persistence.
3. Knowledge item row exists before its embedding FK is written.
4. Deduplication/support records are written before the final orphan prune;
   entities still supported by a capture are not removed.
5. Any persistence error rolls back the whole ingest. A retry using the same
   capture ID succeeds after the failure is corrected; no half-ingest is
   mistaken for a completed idempotent replay.

Embedding-provider failure is deliberately degraded (lexical retrieval can
continue); relational/FK failures are not swallowed.

## Admin data boundary

Admin reads/aggregates are implemented by Postgres read ports in
`adapters/outbound/persistence/postgres/admin_reads.py`. The
`AdminConsoleUseCase` sees ports only: it imports neither psycopg nor SQL.
Admin rerun-extraction calls the same `KnowledgeIngestorPort` synchronously
with the stored transcript and existing capture ID. PATCH transcript updates
the stored knowledge item text. Admin authorization behavior is unchanged.

Worker-era admin fields (stage, attempts, queue depth, job rows, processing
status) are removed. Admin capture responses expose created time, transcript
and knowledge-item presence, and the last ingest error/time where available.

## Migrations and local database

The migration chain is append-only:

| Revision | Purpose |
|---|---|
| `0001_baseline_schema` | Postgres schema baseline (historical baseline includes the old job table) |
| `0002_capture_last_error` | Store last ingest error/time on captures for admin |
| `0003_drop_processing_jobs` | Drop the worker-era processing-job table |
| `0004_drop_worker_capture_columns` | Drop capture stage/error-class/error-message/retry columns |

The baseline is not edited to erase history. New databases run the full chain;
existing databases upgrade with `alembic upgrade head`. Local Postgres runs as
the only service in `docker-compose.yml` (`postgres:16-alpine`, loopback port
5432). The exact working manual setup is in the root README.

## Verification

From the repository root, with the Postgres service available:

```bash
python -m pytest server/tests -q
```

The suite includes real-Postgres UoW rollback/idempotency/API tests and
architecture tests for persistence and module boundaries. The Flutter client
suite is run separately with `cd mobile && flutter test`.
