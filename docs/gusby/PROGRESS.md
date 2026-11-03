# Gusby Project Progress Tracker

## Phase Overview & Status

| Phase | Description | Status | Checkpoint Date | Notes |
|---|---|---|---|---|
| **Phase 0** | Assessment (read-only) | **COMPLETED** | 2026-11-02 | Repo structure mapped, Postgres 16 running & pg_trgm verified, Groq JSON mode & models tested, branch `feature/knowledge-graph` created safely, .env gitignored. |
| **Phase 1** | Docs and Contracts | **COMPLETED** | 2026-11-02 | Six binding project docs in `docs/gusby/` and machine-readable contracts in `contracts/` produced, checked by Reviewer, and frozen at v1.0. |
| **Phase 2** | Data Foundation | **COMPLETED** | 2026-11-02 | PostgreSQL `gusby` schema, migrations, constraints, domain entities, repository layer verified against real Postgres. |
| **Phase 3** | Auth | **COMPLETED** | 2026-11-02 | Argon2id, HttpOnly session cookies, per-user data isolation, route protection, tenant isolation test passing. |
| **Phase 4** | Ingestion & Extraction | **COMPLETED** | 2026-11-02 | Text/URL/File ingestion (PDF, DOCX, TXT), SSRF protection, Unicode-safe chunking with offsets, deterministic evidence validation. |
| **Phase 5** | Integration, Conflicts, Topics | **COMPLETED** | 2026-11-02 | Staged entity resolution (`pg_trgm` + LLM), 4-dimension confidence policy, conflict classification, review states, topic clustering, SKIP LOCKED queue. |
| **Phase 6** | Graph Query & Frontend | **COMPLETED** | 2026-11-03 | Level-of-detail projections per zoom level, Nuxt 3 + Vue 3 desktop-first app, Knowledge Space (Cytoscape.js), Add Knowledge, Documents, Settings. `npm run build` exits 0. |
| **Phase 7** | Verification & Hardening | **COMPLETED** | 2026-11-03 | Gold evaluation suite (15 benchmark docs, 100% evidence validity rate, 100% prompt injection defense), live end-to-end verification against real Groq API (`openai/gpt-oss-120b`). |

---

## Detailed Checkpoints

### Checkpoint 0: Phase 0 Assessment
- [x] Inspected repo layout: Echo Python backend in `server/`, React admin in `admin/`, Flutter mobile in `mobile/`.
- [x] Verified zero conflict with Echo: Gusby resides in `cmd/gusby`, `internal/`, `frontend/`, `docs/gusby/`, and `contracts/`.
- [x] Confirmed Docker Compose Postgres 16 environment.
- [x] Verified `pg_trgm` extension on PostgreSQL 16.
- [x] Verified Groq API key configuration in `.env` (gitignored).
- [x] Empirically confirmed Groq models (`openai/gpt-oss-120b`, etc.) and JSON mode support.
- [x] Empirically confirmed absence of embeddings endpoint on Groq; confirmed default Postgres `pg_trgm` + aliases + LLM adjudication.
- [x] Created `feature/knowledge-graph` branch without losing untracked files.
- [x] Vault session initialized in `/home/guts/Documents/Antigravity-AI-Vault/AI Brain/Sessions/2026-11-02-gusby-orchestrator-session.md`.

### Checkpoint 1: Phase 1 Docs & Contracts (v1.0 Frozen)
- [x] `docs/gusby/00_PRODUCT_BRIEF.md`: Synthesized Vietnamese Product Brief.
- [x] `docs/gusby/01_PRD.md`: Full product requirements, precision-over-recall philosophy, explicit out-of-scope list.
- [x] `docs/gusby/02_TRD.md`: Technical architecture, Go/Nuxt/Postgres/Groq stack, pipeline stages, security, job queue.
- [x] `docs/gusby/03_APP_FLOW.md`: Every screen, route, transition, review-as-state interaction, verbatim evidence flow.
- [x] `docs/gusby/04_DESIGN_SYSTEM.md`: Pure white canvas, earthy palettes, typography, node/edge styles, semantic zoom.
- [x] `docs/gusby/05_SCHEMA_AND_API.md`: PostgreSQL `gusby` schema, DDL, indexing, all REST endpoints with JSON shapes.
- [x] `docs/gusby/06_IMPLEMENTATION_PLAN.md`: Milestones, module dependencies, task ownership, gold evaluation plan.
- [x] `docs/gusby/DECISIONS.md`, `OPEN_QUESTIONS.md`, `CHANGE_REQUESTS.md`: Architecture logs and freeze baseline.
- [x] `contracts/openapi.yaml`: Full OpenAPI 3.1 specification.
- [x] `contracts/llm/*.json`: Strict JSON schemas for Concept Extraction, Proposition Extraction, Entity Adjudication, and Conflict Classification.
- [x] `contracts/config/config_schema.json`: System configuration schema.
- [x] Reviewer conformance check: Passed with zero contradictions.

### Checkpoint 2: Phase 2 Data Foundation
- [x] Applied `migrations/gusby/0001_initial_schema.sql` (21 tables in `gusby` schema).
- [x] Domain types and PostgreSQL repository implementation in `internal/store/`.
- [x] Trigram GIN indexes on `name_normalized` using `pg_trgm`.
- [x] Integration tests in `internal/store/store_test.go` passing against real Docker PostgreSQL 16.

### Checkpoint 3: Phase 3 Authentication & Isolation
- [x] Argon2id password hashing and constant-time verification in `internal/auth/password.go`.
- [x] Cryptographic 32-byte session tokens in `internal/auth/session.go` with `gusby_session` cookie.
- [x] In-memory sliding-window auth rate limiter in `internal/auth/service.go`.
- [x] Generic error messages preventing user enumeration.
- [x] Automated tenant isolation test in `internal/auth/auth_test.go` proving User B cannot query or traverse User A's data.

### Checkpoint 4: Phase 4 Ingestion & Extraction
- [x] SSRF-protected HTTP fetching with RFC1918/loopback/cloud metadata blocking in `internal/ingest/ssrf.go`.
- [x] Text, URL, PDF, and DOCX extractors in `internal/ingest/extractor.go`.
- [x] Unicode NFC boundary-aware chunker tracking byte and rune offsets in `internal/pipeline/chunker.go`.
- [x] Deterministic verbatim evidence validation in `internal/pipeline/evidence.go`.
- [x] Two-stage extraction engine with JSON mode, bounded retry, and injection-protected prompts.

### Checkpoint 5: Phase 5 Integration, Conflicts, Queue
- [x] Staged entity resolution: exact match -> trigram (`GREATEST(similarity, word_similarity) >= 0.85`) -> LLM adjudication (`[0.40, 0.85)`).
- [x] 4-dimension confidence scoring (extraction, evidence, resolution, proposition).
- [x] Non-destructive conflict detection: preserves both contradictory claims with audit trails.
- [x] Automatic spatial topic clustering into island centroids.
- [x] PostgreSQL `FOR UPDATE SKIP LOCKED` background worker in `internal/queue/worker.go`.

### Checkpoint 6: Phase 6 Graph Query & Frontend
- [x] Level-of-detail projections (Far: Topics <= 50, Medium: Core Concepts <= 150, Deep: Full Network <= 500) in `internal/graph/projection.go`.
- [x] REST API handlers and Chi router in `internal/api/`.
- [x] Nuxt 3 (Vue 3 + TypeScript) desktop-first application in `frontend/`:
  - Knowledge Space (`/`): Cytoscape.js canvas, semantic zoom, search, review filter, right detail drawer, verbatim evidence reader.
  - Ingestion Workspace (`/add`): Text, URL, Drag-and-drop file upload with progress polling.
  - Documents (`/documents`): Source repository table, reader drawer with chunks.
  - Settings (`/settings`): Earthy preset palettes (Slate, Terracotta, Moss, Ochre), password change, security.
- [x] Nuxt production build: `npm run build` exits 0 cleanly.

### Checkpoint 7: Phase 7 Verification, Hardening & Definition of Done
- [x] Gold Evaluation Set: `eval/gusby/gold_set.json` with 15 curated benchmark documents (English technical, Vietnamese diacritics, contradictory pairs, adversarial prompt injections).
- [x] Evaluation Benchmark Runner: `eval/gusby/eval_test.go`:
  - Total Documents Evaluated: 15 / 15 (100%)
  - Evidence Validity Rate: 100.00% (target 100%)
  - Prompt Injection Defense Rate: 100.00% (target 100%)
  - Conflict Classification Accuracy: 100.00% (target >= 85%)
- [x] Live End-to-End Verification against real Groq API (`tests/gusby/live_e2e_test.go`):
  - Ingested two documents with contradictory assertions.
  - Real Groq LLM (`openai/gpt-oss-120b`) extracted concepts and propositions.
  - Verified 100% verbatim evidence quotes with exact document UUIDs, byte spans, and char spans.
  - Automatic topic island creation verified.
  - Test passed cleanly in 12.59s.

---

## Admin Dashboard Extension (CR-001)

| Phase | Description | Status | Checkpoint Date | Notes |
|---|---|---|---|---|
| **Admin Phase 0** | Assessment (read-only) | **COMPLETED** | 2026-11-03 | Verified existing auth, job queue, LLM interface, full Go build & tests passing, Nuxt build passing, branch `feature/admin-dashboard` created. |
| **Admin Phase 1** | Docs & Contracts (v1.1) | **COMPLETED** | 2026-11-03 | CR-001 logged; six project docs updated to v1.1; D08-D11 logged; OpenAPI & AI health schema updated and validated. |
| **Admin Phase 2** | Admin Foundation | **COMPLETED** | 2026-11-03 | Database migrations (`is_admin`, `status`, `admin_audit_log`), store methods, bootstrap CLI, `RequireAdmin` middleware returning 404. |
| **Admin Phase 3** | AI Instrumentation | **COMPLETED** | 2026-11-03 | AI Provider Contract, `ai_call_log`, AI gate & circuit breaker, active probe, eval run recording. |
| **Admin Phase 4** | Monitoring UI & Backend | **COMPLETED** | 2026-11-03 | Overview, pipeline health, AI health dashboard with SVG sparklines & gate controls. |
| **Admin Phase 5** | User & Doc Management | **COMPLETED** | 2026-11-03 | Suspend/purge, cascade retraction on doc delete, reprocess runs. |
| **Admin Phase 6** | Graph Data Administration | **COMPLETED** | 2026-11-03 | Form/table graph manager with user context, concept merge, proposition retract, topic locking, audit logs viewer. |
| **Admin Phase 7** | Verification & Hardening | **COMPLETED** | 2026-11-03 | Authorization matrix (100% pass across 34 endpoints & 4 actor types), destructive semantics test, future model checklist. |

### Checkpoint 8: Admin Phase 0 & Phase 1 Complete
- [x] Preconditions verified: `go test -v ./...` passes 100%, `npm run build` exits 0.
- [x] Working branch created: `feature/admin-dashboard`.
- [x] Formal Change Request `CR-001` recorded in `docs/gusby/CHANGE_REQUESTS.md`.
- [x] Architecture decisions `D08` - `D11` logged in `docs/gusby/DECISIONS.md`.
- [x] Six project docs updated to v1.1: `01_PRD.md`, `02_TRD.md`, `03_APP_FLOW.md`, `04_DESIGN_SYSTEM.md`, `05_SCHEMA_AND_API.md`, `06_IMPLEMENTATION_PLAN.md`.
- [x] `contracts/openapi.yaml` updated with all 28 `/api/admin/*` endpoints and components.
- [x] `contracts/llm/ai_health_schema.json` created and validated.
- [x] Reviewer conformance check: zero contradictions across Brief, docs, and contracts. v1.1 frozen.

### Checkpoint 9: Admin Phases 2-6 Complete (Core Foundation, AI Instrumentation, Monitoring, Management)
- [x] Applied migration `0002_admin_and_ai_observability.sql`: added `is_admin`, `status` to users, `admin_audit_log`, `ai_call_log`, `ai_gate_state`, `eval_run`.
- [x] Implemented repository methods in `internal/store/admin.go` (36 methods).
- [x] Implemented `RequireAdmin` middleware with stealth HTTP 404 enforcement, demotion prevention, self-action safeguards.
- [x] Implemented Admin CLI subcommands (`gusby admin grant|revoke|list`) in `cmd/gusby/main.go`.
- [x] Implemented AI Provider Contract (`Describe()`, `Health()`) across `GroqClient` and `MockClient`.
- [x] Centralized `AIGate` with automatic circuit breaker (5 consecutive failures -> `circuit_open`), pause/resume, active `RunProbe()`.
- [x] Integrated `AIGate` into queue worker with job state `waiting_for_ai` and exponential backoff; sanitized call logging to `gusby.ai_call_log`.
- [x] Implemented 28 `/api/admin/*` REST endpoints in `internal/api/admin_handlers.go`.
- [x] Implemented desktop-first Nuxt 3 admin interface (`frontend/pages/admin/`): Overview, Pipeline, AI Observability, Users, Documents, Graph, Audit.
- [x] Verified Nuxt build: `npm run build` exits 0 cleanly.

### Checkpoint 10: Admin Phase 7 Complete (Verification & Hardening)
- [x] Implemented comprehensive authorization matrix test in `tests/admin/auth_matrix_test.go`:
  - 34 admin endpoints tested against 4 actor types: Anonymous, Regular User, Suspended Admin, Active Admin.
  - 100% PASS: All non-admin/suspended actors receive strict HTTP 404 (stealth); active admin permitted.
- [x] Destructive operation safeguards verified:
  - Document deletion triggers cascade proposition retraction without deleting source evidence.
  - Concept merge preserves target canonical concept with source name recorded as alias.
  - User purge logs tombstone in `admin_audit_log` with `ON DELETE SET NULL`.
- [x] Authored `docs/gusby/FUTURE_MODEL_SWAP_CHECKLIST.md` establishing zero-schema, zero-UI model swap steps.


