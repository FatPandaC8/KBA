# Echo E2E Suite (Playwright)

API- and browser-level end-to-end tests for the Echo backend. Each run boots one
**real** FastAPI server (uvicorn, SQLite persistence, background job worker,
rule-based extraction, local fastembed embeddings, admin dashboard) and drives
the entire user journeys over real HTTP. No admin frontend exists to skip and
none is built.

## What is real vs scripted (transparency)

| Pipeline port | E2E behavior |
| :--- | :--- |
| HTTP / auth / consent / sessions | real |
| SQLite persistence + migrations | real |
| Background job worker (lease/queue) | real (`ECHO_JOB_POLL_SECONDS=0.2`) |
| Knowledge extraction (rule_based, no Groq) | real code path, deterministic provider |
| Entity resolution + relationship registry (U1) | real |
| Embeddings (fastembed local) | real |
| Speech-to-text | **scripted transcript** (`e2e/server_launcher.py`) |

STT alone is stubbed because real whisper output is not deterministic and would
make entity assertions flaky. The real STT adapter is verified separately by
`python3 e2e/real_stt_check.py` (espeak-ng → wav → faster-whisper). The stub
lives ONLY in `e2e/server_launcher.py` under `ECHO_E2E_MODE=1` and its control
routes are key-guarded; the production app registers none of them.

## Run

```bash
cd e2e
npm install
npx playwright install chromium   # browser for the dashboard spec
npx playwright test               # full suite (~50s)
npx playwright show-report        # artifacts/html-report
```

The launcher cleans `/tmp/opencode/echo-e2e` (DB, uploads, outbox) at server
start, one DB per environment. Tests fail closed on helper-and-secrets
boundaries: no real provider keys are used (`ECHO_LLM_PROVIDER=rule_based`,
`ECHO_ALLOW_REAL_LLM=0`); tokens are per-run test values.

## Scenarios (44 tests)

01 Authentication & account lifecycle — signup/verify/login/me, wrong password,
duplicate signup anti-enumeration, unverified/consent gates, logout revocation,
account deletion, missing/garbage tokens.

02 Capture pipeline — upload → queued → worker STT → extraction → ready,
knowledge item created, public schema exposes no transcript field, idempotent
re-upload, audio retrieval, durable validations (duration 4xx, content-type
415, UUID 400), typed STT failure → client-visible error → retry-to-success,
retry of healthy capture, cross-account ownership 403/404, capture delete
cascades, unknown capture → clean 404.

03 Knowledge graph — relationship normalization ("relies on"→"Depends on",
novel "works at" gets a registry entry), node kinds/degrees, edge evidence,
cross-capture entity resolution to ONE node, entity detail + user PATCH, entity
delete with edge cascade, relationship confirm/reject/delete, graph ownership.

04 Retrieval & mobile sync replica — /api/knowledge stability across re-fetch
(sync idempotency), item detail, semantic search top-rank + shape, providers
privacy contract.

05 Admin API — fails closed without/adminless token, status counts, jobs &
captures incl. admin-only transcript access, user-visible transcript redaction,
knowledge delete + U4 audit rows, config/ai-config (no key material returned),
backfill, admin job retry.

06 Admin dashboard (real browser) — token gate, live metrics, captures table +
Inspect modal with resolved knowledge, knowledge filter, jobs table; browser
console errors fail the test.

07 Persistence integrity (actual SQLite dump via `e2e/db_inspect.py`) — captures,
jobs, knowledge, entities, relationships rows really exist and link up; password
never persisted in the DB file; account deletion clears user's rows.

## Artifacts

`artifacts/html-report` (Playwright HTML report). On failure, screenshots,
videos and traces are kept under `artifacts/test-results/*` — these directories
are git-ignored.

## Notes for CI

- `workers: 1`, serial: one shared server + worker process; tests isolate by
  per-test users.
- Retries on CI only (`retries: process.env.CI ? 1 : 0`).
