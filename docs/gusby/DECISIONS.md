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
