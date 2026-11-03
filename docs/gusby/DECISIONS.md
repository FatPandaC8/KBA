# Gusby Architectural & Design Decisions (DECISIONS.md)

This log records binding architectural decisions made during development. Every decision must adhere to the source-of-truth precedence:
1. Product Brief
2. The Six Project Docs (once approved at v1.0)
3. Prompt defaults
4. Decisions recorded here

---

### D01: Repository Layout & Non-Interference with Echo
- **Status**: Decided
- **Context**: The repository currently contains "Echo", an existing Python FastAPI backend, Flutter app, and React admin dashboard. Gusby is a web-only platform using Go + Nuxt 3.
- **Decision**: Gusby backend resides in `cmd/gusby` and `internal/` (`internal/store`, `internal/auth`, `internal/graph`, `internal/api`, `internal/pipeline`, `internal/llm`, `internal/ingest`, `internal/queue`). Frontend resides in `frontend/` (Nuxt 3). All Gusby docs reside in `docs/gusby/` and contracts in `contracts/`. Unrelated Echo code (`server/`, `mobile/`, `admin/`, `e2e/`, `docs/`) is left untouched.

### D02: PostgreSQL Schema Isolation
- **Status**: Decided
- **Context**: Echo uses `public` schema in the `echo_kb` Postgres database.
- **Decision**: Gusby migrations will manage a dedicated PostgreSQL schema `gusby` (e.g. `gusby.documents`, `gusby.concepts`, `gusby.propositions`, etc.) or dedicated database `gusby_kb`. By default, migrations create and target the `gusby` schema inside the existing Postgres container (`127.0.0.1:5432`), ensuring zero table name collisions with Echo's public tables while reusing Docker Postgres infrastructure.

### D03: Unicode Offset Standard for Evidence Validation
- **Status**: Decided
- **Context**: Evidence validation requires precise character offsets into source text. Go strings are UTF-8 byte sequences, JavaScript uses UTF-16 code units, and source texts may be English or Vietnamese with composite diacritics.
- **Decision**:
  - Canonical internal offset unit: **UTF-8 byte offsets** `(byte_start, byte_end)` for deterministic Go slice indexing `source[byte_start:byte_end]`.
  - Canonical display offset unit: **Unicode codepoints (runes)** `(char_start, char_end)` stored alongside byte offsets to allow language-agnostic frontend text slicing without byte conversion errors in JavaScript.
  - Normalization: NFC (Normalization Form Canonical Composition) applied uniformly upon ingestion before offset calculation.

### D04: Groq Model Selection & Free-Tier Defense
- **Status**: Decided
- **Context**: Groq provides OpenAI-compatible chat completions with strict free-tier RPM/TPM limits.
- **Decision**:
  - Primary LLM: `openai/gpt-oss-120b` (fallback config: `openai/gpt-oss-20b` for low-token tasks if needed).
  - Rate Limiter: In-memory token-bucket rate limiter in Go backend respecting Groq RPM (default 30) and TPM (default 8,000) caps.
  - Retry & Backoff: Exponential backoff with jitter on HTTP 429 and 5xx; parses `Retry-After` header when provided.
  - User-Agent: Explicit header `User-Agent: Gusby/1.0 (+https://github.com/gusby-kg)` to bypass Cloudflare bot filtering.
  - JSON Mode: `response_format: {"type": "json_object"}` with strict Go struct unmarshaling and validation.

### D05: Entity Resolution Without Embeddings
- **Status**: Decided
- **Context**: Groq has no embeddings API, and pgvector is excluded from MVP scope.
- **Decision**: Three-stage entity resolution pipeline:
  1. Exact match against canonical concept names and known aliases (case-insensitive, normalized).
  2. Trigram similarity using PostgreSQL `pg_trgm` (`similarity(name, candidate) >= 0.70`).
  3. LLM adjudication only for ambiguous candidates (similarity between 0.70 and 0.88, or conflicting alias clusters). Clear matches (≥ 0.88) auto-link; unresolved or ambiguous items create an `integration_proposal` with `needs_review = true`.

### D06: Review Is a State, Not a Page
- **Status**: Decided
- **Context**: The product specifies no standalone "Review Queue" page.
- **Decision**: Proposals, merge ambiguities, and conflicts are stored as review states on canonical nodes and edges. The Knowledge Space provides a toggleable filter `[Needs Review]` which dims resolved nodes and highlights unresolved items, opening the adjudication sidebar on click.

### D07: Web Framework & Graph Visualization Library
- **Status**: Decided
- **Context**: Web-only Nuxt 3 (Vue 3 + TypeScript). Desktop-first, requiring semantic zoom and Topic Islands.
- **Decision**:
  - Nuxt 3 with Tailwind CSS (configured for minimal, intellectual design system).
  - Graph rendering: Canvas/WebGL-accelerated library (e.g. Cytoscape.js with fcose/cola layout or D3 Force on 2D Canvas) capable of fluid 60fps rendering up to the enforced node cap (500 nodes per projection).

### D08: Single-Owner Admin Role & Security Model
- **Status**: Decided
- **Context**: Operational monitoring and data administration are needed without the complexity of multi-admin RBAC or separate admin login portals.
- **Decision**:
  - `is_admin` boolean added to `gusby.users`. No public or user API can set or alter this flag.
  - Bootstrapping: CLI command `gusby admin grant --email <email>` and env variable fallback `GUSBY_OWNER_EMAIL`.
  - Server-side authorization middleware `RequireAdmin` returns HTTP 404 (or generic 403) to prevent endpoint enumeration by unauthorized users.
  - Safeguards: Admin cannot suspend or delete self; the last remaining admin account cannot be removed or demoted. Destructive operations require explicit typed confirmation (`DELETE / CONFIRM`) both on client and server.
  - Strict tenant scoping: Admin operations taking `user_id` strictly route through scoped repository queries (`WHERE user_id = $1`). Admin does not bypass multi-tenant isolation.

### D09: AI Provider Contract, Observability & Circuit Breaker
- **Status**: Decided
- **Context**: Today the AI component uses Groq API; in the future a custom model built from research papers will be swapped in. The architecture must enable this swap cleanly with zero UI changes and strict observability.
- **Decision**:
  - Extend Go `LLMClient` with `Describe() ProviderDescription` and `Health(ctx) (ProviderHealth, error)`. `Health()` provides normalized status (`healthy`, `degraded`, `down`, `paused`, `unknown`) and a generic `details map[string]any` rendered as-is by the admin UI.
  - Append-only `gusby.ai_call_log` records per-call metadata (latency, status, error class, token counts, retry count, run ID, user ID). Zero prompt, response, or document text is ever stored in this table. Retention default: 30 days.
  - AI Gate & Circuit Breaker: Shared gate across all pipeline LLM calls with persistent state in `gusby.ai_gate_state` (`enabled`, `paused`, `circuit_open` with half-open recovery). Jobs wait (`waiting_for_ai`) rather than burn retries when paused or open.
  - Active probe: Admin-initiated test call using a fixed harmless prompt, tiny token budget, logged and audited.

### D10: Destructive Operation Semantics, Cascade Retraction & Auditability
- **Status**: Decided
- **Context**: The admin is powerful, but Gusby's core principle "precision over recall and 100% evidence validity" must never be violated by admin actions.
- **Decision**:
  - Document Deletion: In one transaction, delete document and raw evidence. Any canonical proposition left with zero valid evidence is soft-retracted (`status = 'retracted'`, hidden from normal views, preserved for audit). Concepts left with no document references are flagged `orphaned = true` for review.
  - User Deletion: Hard delete of all user data in a single cascading transaction after typed confirmation. A minimal audit record is preserved in `admin_audit_log`.
  - Manual Graph Edits: Any manually created proposition MUST cite a verbatim span from an existing document, validated by the deterministic evidence validator.
  - Admin Audit Log: Append-only table `gusby.admin_audit_log` records every mutation, content access, and AI control action in the same transaction.

### D11: Metrics Computation via PostgreSQL SQL Queries
- **Status**: Decided
- **Context**: Monitoring pipeline and user health without adding external infrastructure (no Prometheus, Grafana, or dedicated metric agents).
- **Decision**:
  - Pipeline health (queue depth, failure rates, stage latencies, stuck jobs) and user metrics are computed using optimized SQL queries with indexes over `gusby.processing_jobs`, `gusby.documents`, `gusby.users`, and `gusby.ai_call_log`.
  - Paginated, filterable, with manual refresh and optional lightweight client polling.

