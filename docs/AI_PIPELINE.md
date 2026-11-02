# AI and knowledge-ingest pipeline

## Current flow (synchronous, two APIs)

The mobile app owns the order and invokes two independent API requests:

```text
Record on device
   └─ POST /api/stt (raw audio bytes; session auth)
        └─ local faster-whisper → transcript response only; no server write
             └─ app keeps transcript in memory
                  └─ POST /api/text-kb {capture_id: UUID, text}
                       (session auth + consent)
                       └─ extract → normalize first person → resolve → link
                            → deduplicate → embedding → prune → commit one UoW
```

There is no worker process, job/queue table, status endpoint, polling,
stage-output cache, or persisted/capture-level retry schedule. The app shows
progress while a request is in flight and presents a Retry action after an
error. If STT succeeded, a Text-KB retry uses the in-memory transcript and the
same `capture_id`; if STT failed, the app resends the local audio to `/api/stt`.

**Known configuration/code mismatch:** `GroqChatClient` still has bounded
provider transport retries/backoff inside one Text-KB request
(`ECHO_LLM_MAX_RETRIES`, default 3; bounded wait settings), and a schema
repair attempt may make another provider call. These are not worker/job
retries, but they conflict with a literal reading of the owner's “no
retry/backoff” decision. This is documented rather than hidden; align the
implementation/config with that decision before treating the no-retry promise
as complete.

`POST /api/stt` accepts the raw request body (not multipart), requires user
session authentication, and persists nothing. `POST /api/text-kb` accepts
JSON `{ "capture_id": "<UUID>", "text": "..." }`, requires a valid session
and current consent, and is idempotent for the same user's completed capture
ID. Other-user ID reuse returns `409`.

## Input limits and typed errors

Defaults (all server-side configuration):

| Setting | Default | Enforcement |
|---|---:|---|
| `ECHO_MAX_UPLOAD_BYTES` | 25 MiB | `POST /api/stt`; over-limit → `413` |
| `ECHO_MAX_VOICE_SECONDS` | 120 seconds | decoded audio duration; over-limit → `413` |
| `ECHO_MAX_TEXT_KB_CHARS` | 20,000 characters | `POST /api/text-kb`; too long → `422` |

Bad audio/empty transcript/unsupported language are typed client errors.
Text-KB rejects invalid UUID/empty input as `400`; another user's capture ID
is `409`. Provider failures and unexpected server faults return `5xx`; the
response carries `detail: {class, message}` for the two ingest APIs. No server
retry policy hides the failure from the user.

## Providers

Client ingestion requests have no provider field. The provider is part of
server configuration, not an STT/Text-KB request parameter. In addition to
environment settings read at startup, the authenticated admin AI-config API
can update the effective extractor configuration at runtime and persists it
in `app_settings`.

| Setting | Choices/default | Behavior |
|---|---|---|
| `ECHO_STT_PROVIDER` | `faster_whisper` | Current local STT provider; English-only by default |
| `ECHO_KB_EXTRACTOR` | `local` or `groq` | Local deterministic rules or hosted Groq text extraction |
| `ECHO_LLM_PROVIDER` | `groq` in a normal dev launch; `rule_based` in tests/local config | LLM client configuration; `groq` requires `GROQ_API_KEY` |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Model name when Groq extraction is selected |
| `ECHO_LLM_TIMEOUT_SECONDS` | 45 | Per-provider-call timeout |
| `ECHO_LLM_MAX_RETRIES` | 3 | Current bounded provider transport retry count (implementation deviation noted above) |
| `ECHO_LLM_MAX_RETRY_WAIT_SECONDS` | 8 | Maximum wait for current transport retries |
| `ECHO_LLM_REPAIR_ATTEMPTS` | 1 | Bounded schema-repair call for malformed extraction output |
| `ECHO_LLM_MAX_PROMPT_CHARS` | 24,000 | Prompt input cap |

`ECHO_KB_EXTRACTOR=groq` requires a configured LLM client and fails closed if
one is missing. It does not silently fall back to the local extractor. Only
transcript text is sent to a hosted extractor; audio remains on the device and
is sent only to the configured local STT server.

The local STT adapter decodes audio to mono 16 kHz PCM with `ffmpeg` and uses
`faster-whisper` (default model `tiny`, compute type `int8`; configurable via
`ECHO_WHISPER_MODEL` and `ECHO_WHISPER_COMPUTE_TYPE`).

## Text-KB transaction and graph invariants

Text-KB is implemented by the `KnowledgeIngestorPort`. It does not know about
audio or STT. It extracts the knowledge item and graph proposals, then persists
all relational graph changes within one UoW. The order preserves:

1. First-person references normalize to one canonical `Me` node before any
   relationship endpoint is resolved.
2. Tombstoned entities stay deleted; duplicate names resolve/flag according to
   configured similarity thresholds; relationship types pass through the
   user's canonical registry.
3. The knowledge item exists before its embedding is written (foreign-key
   correctness).
4. Capture support is recorded before orphan pruning, so a captured entity is
   not removed just because its typed relationship was suppressed.
5. Any UoW failure rolls back capture, knowledge item, entity, relationship,
   support, duplicate-candidate and embedding writes together.

`capture_id` makes a successful retry safe. A retry after a rolled-back
failure can complete using the same UUID; a repeat after success returns the
existing result and creates no new capture or graph objects.

### Admin re-extraction

Admin `POST /api/admin/captures/{capture_id}/rerun-extraction` reads the stored
transcript and calls the same `KnowledgeIngestorPort` synchronously with the
existing capture ID. It creates no new capture. **Current limitation:** the
ingestor treats any capture that already has a knowledge item as a successful
idempotent replay and returns the existing result without invoking extraction.
Consequently, PATCH transcript followed by rerun-extraction does not rebuild a
completed capture's graph yet. Captures without a knowledge item can be
ingested from their stored transcript. Do not rely on the current admin rerun
button to replace existing graph output.

## Search and embeddings

The graph and knowledge APIs remain usable with the local extractor; no LLM
reasoning service is required for graph reads. Local FastEmbed vectors assist
semantic retrieval; lexical retrieval remains available if embeddings cannot
be produced. The graph layout is deterministic and server-generated. The
Flutter client renders node and edge data; current layout spacing is tested
to keep node centres at least one node diameter apart within a community.

## Consent and transcript access

The client-facing `/api/graph`, knowledge and recordings responses do not
return transcripts. Admin-authenticated capture detail exposes stored
transcript text for correction and synchronous rerun. `POST /api/text-kb`
requires current consent because it invokes extraction and persists knowledge;
the STT endpoint is stateless and requires authentication but not extraction
consent.

## Manual smoke tests

After starting the server, obtaining a user session token and granting consent,
run from the repo root:

```bash
# STT is raw audio, not multipart; response includes transcript + language.
curl -i -X POST http://127.0.0.1:8000/api/stt \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: audio/wav' \
  --data-binary @/path/to/short-recording.wav

# Text-KB works without an audio upload or STT call.
CAPTURE_ID="$(python -c 'import uuid; print(uuid.uuid4())')"
curl -i -X POST http://127.0.0.1:8000/api/text-kb \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"capture_id\":\"$CAPTURE_ID\",\"text\":\"I met Anna at the cafe yesterday.\"}"

# Safe retry: same UUID and same text.
curl -i -X POST http://127.0.0.1:8000/api/text-kb \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"capture_id\":\"$CAPTURE_ID\",\"text\":\"I met Anna at the cafe yesterday.\"}"
```

## Tests

```bash
python -m pytest server/tests/unit/test_split_ports.py \
  server/tests/unit/test_graph_layout_spacing.py -q
python -m pytest server/tests/integration/test_pipeline_split_api.py \
  server/tests/integration/test_text_kb_rollback.py \
  server/tests/integration/test_pipeline_m3.py -q
```

All persistence integration tests use real PostgreSQL via the repo-root pytest
fixtures; no SQLite server database or worker fixture is used.
