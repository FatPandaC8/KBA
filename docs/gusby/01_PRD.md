# Gusby: Product Requirements Document (PRD)
**Version:** 1.1 (Extended via CR-001)  
**Status:** Approved & Binding  
**Source of Truth Precedence:** 00_PRODUCT_BRIEF.md > 01_PRD.md > DECISIONS.md > Prompt Defaults

---

## 1. Vision & Problem Statement

### 1.1. Product Vision `[Decided]`
**Gusby** is a web-only Text-to-Knowledge-Graph platform that transforms unstructured text, URLs, and document files into structured, connected, and fully trustworthy knowledge graphs.

### 1.2. The Core Problem `[Decided]`
Existing knowledge management and AI synthesis tools suffer from three fatal flaws:
1. **Hallucinated & Unverifiable Links**: Generative AI models invent relationships between entities that the source text never asserted.
2. **Silent Overwriting & False Consensus**: When two sources disagree, systems overwrite or blend contradictory facts without trace.
3. **Graph Bloat**: Systems maximize recall over precision, flooding users with noisy, useless edges.

### 1.3. Core Philosophy: Precision Over Recall `[Decided]`
A small, dense, 100% trustworthy knowledge graph beats a massive graph plagued by hallucinated or misattributed connections. In Gusby:
- **No edge exists without verbatim evidence.** Every proposition links to an exact character span in the source text.
- **Evidence validation is deterministic.** The model cannot declare its own truth; Go-side code mathematically verifies the quote in the source text.
- **Contradictions are preserved, not erased.**
- **Admin actions obey trust rules.** The admin is powerful, but Gusby's trust rules still apply to the admin: no silent overwrite, no silent deletion, no fabricated evidence, all actions audited.

### 1.4. Target Users `[Decided]`
- **Researchers & Academics**: Need to map literature, trace claims directly to page citations, and identify contradictions between studies.
- **Intelligence & Market Analysts**: Need to track entity interactions across news articles and whitepapers without risk of hallucinated connections.
- **Knowledge Workers & Domain Specialists**: Need to build personal or project knowledge bases with verifiable provenance.
- **System Owner / Administrator**: Needs to monitor pipeline & AI health, operate circuit breakers, manage users/documents, and audit knowledge integrity.

---

## 2. Product Goals & Success Criteria

### 2.1. Quantitative Success Criteria `[Decided]`
1. **Evidence Validity Rate**: **100%** of propositions in the Canonical Graph must resolve to an exact, verifiable substring in the source text.
2. **Extraction Precision**: **≥ 90%** precision on the benchmark gold evaluation set.
3. **Graph Interaction Performance**: Constant 60 FPS panning and semantic zooming up to the Level-of-Detail limit (500 nodes per projection).
4. **Per-User Isolation**: **100%** isolation verified by automated cross-tenant security tests.
5. **Idempotency**: Re-ingesting an identical document hash produces 0 duplicate nodes, edges, or runs.
6. **Admin Authorization Boundary**: **100%** server-side enforcement. Non-admins receive HTTP 404 (zero route enumeration).
7. **AI Call Observability**: **100%** of external/internal AI completions recorded with latency, tokens, status, error class, and zero prompt/document text leakage.
8. **Deterministic Admin Evidence Enforcement**: **100%** of manual proposition additions validated by deterministic evidence validator; zero manual proposition without valid document quote.

### 2.2. Qualitative Success Criteria `[Decided]`
1. **Intellectual, Pure White Aesthetic**: Clean, distraction-free desktop canvas following the earthy-palette design system.
2. **Auditability**: Every merge, conflict, review action, and admin mutation/content-access recorded with timestamp and decider.
3. **Future AI Model Readiness**: AI component monitoring and control designed around a generic Provider Contract, enabling future transition from Groq API to a custom paper-trained model with zero UI changes.

---

## 3. Scope & Feature Boundaries

### 3.1. In-Scope Key Features

#### Feature 1: Multi-Source Ingestion `[Decided]`
- Text, URL (SSRF-protected), and files (`.txt`, `.pdf` digital text, `.docx` up to 10MB).
- Status Lifecycle: `Uploading` → `Processing` → `Completed` | `Failed`.

#### Feature 2: Multi-Stage Extraction Pipeline `[Decided]`
- Unicode NFC normalization, chunking with byte and char offsets.
- Two-stage extraction: Concept extraction followed by Proposition extraction.
- Deterministic evidence validator verifying exact quote substring in source text.

#### Feature 3: Staged Entity Resolution `[Decided]`
- Exact & alias match → Trigram lexical similarity (`pg_trgm`) → LLM adjudication for ambiguous candidates.

#### Feature 4: Four-Dimension Confidence Integration `[Decided]`
- Extraction confidence, Evidence validity, Entity resolution confidence, Proposition confidence.

#### Feature 5: Conflict Classification & Preservation `[Decided]`
- Automatic contradiction detection, non-destructive preservation, review flagging.

#### Feature 6: Topic Islands & Semantic Zoom `[Decided]`
- 4-level semantic zoom (Far, Closer, Deep, Deepest) in Knowledge Space.

#### Feature 7: Review as a State `[Decided]`
- In-place review states on nodes and edges; `[Needs Review]` filter toggle.

#### Feature 8: Secure Multi-Tenant Auth `[Decided]`
- Argon2id, cryptographic session tokens, HttpOnly cookies, per-user database scoping.

#### Feature 9: Single-Owner Admin Dashboard & Operational Controls `[Decided - CR-001]`
- **Single Owner Access**: `is_admin` flag on user account. CLI / env bootstrap (`GUSBY_OWNER_EMAIL`). Server-side `RequireAdmin` returning 404. Non-admin sidebar hides admin routes.
- **Pipeline & Job Monitoring**: Queue depth (queued, running, waiting for AI, completed, failed), stuck job detection, median/p95 latency per stage, retry operational controls.
- **User Activity Monitoring**: User accounts, status (`active`, `suspended`), document counts, token usage windows, signup trends, activity feed.
- **AI Component Monitoring & Controls**:
  - Provider Contract (`Describe`, `Health` with status `healthy`/`degraded`/`down`/`paused`/`unknown` and generic `details` key-value map).
  - Rolling window error rates, latency (median, p95), error breakdown by class (rate limit, timeout, server error, invalid JSON, schema validation failure, auth error, budget exceeded).
  - Rate-limit and quota indicators (Groq headers when present, per-user budget exhaustion counts).
  - Output quality signals: schema validation failure rate, invalid-JSON retry rate, invalid-evidence rate.
  - Evaluation history display from gold evaluation benchmark runs.
  - Operational Controls: AI Gate (`enabled`, `paused`, `circuit_open`), pause/resume, circuit breaker reset, active harmless probe.
- **User Management**: Suspend/unsuspend (immediate session revocation), hard delete (cascading purge in single transaction with typed confirmation), reset limits.
- **Document Management**: Reprocess failed runs (idempotent, new run created, canonical propositions preserved), delete document (cascades to soft retraction of propositions lacking other valid evidence, flags orphaned concepts).
- **Graph Data Administration**: Table/form tool with explicit user selector. Concept edit/merge/archive, proposition retract/restore/edit, topic locking, conflict resolution.
- **Admin Audit Log**: Append-only `gusby.admin_audit_log` recording every mutation, content access, and AI control action in the same transaction.

---

### 3.2. Explicit Out-of-Scope List `[Decided]`
The following features are strictly **OUT OF SCOPE**:
- Mobile applications (iOS, Android).
- Audio capture, recording, or Speech-to-Text (STT).
- General AI conversational chatbot or reasoning assistant.
- Notion / Obsidian-style markdown editors or manual wiki note-taking.
- Tasks, reminders, or productivity tooling.
- Multi-user collaboration, workspace sharing, public links, or organization RBAC.
- Dark mode.
- Scanned PDF OCR (non-digital PDFs).
- Vector databases, pgvector, or third-party embedding providers.
- **Explicit Admin Out-of-Scope**:
  - Billing, invoicing, or cost dashboards.
  - Graph-quality academic analytics.
  - Multi-admin role hierarchies or permissions matrix.
  - Teams, organizations, or tenant groups.
  - User impersonation ("log in as user").
  - Visual graph canvas editor for admin.
  - Bulk edit or bulk import/export.
  - Email notifications, webhooks, or alerting systems.
  - External monitoring stacks (Prometheus, Grafana, OpenTelemetry collectors).
  - UI for editing API keys.
  - UI for dynamically switching LLM provider or model (stays a configuration change).
  - Building, training, or stubbing custom machine learning models in this phase.

---

## 4. Risks & Mitigations `[Decided]`

| Risk | Impact | Mitigation Strategy |
|---|---|---|
| **Groq Free-Tier Rate Limits** | Pipeline stalls or fails with HTTP 429 | Shared rate-limiter, exponential backoff, circuit breaker, AI gate `waiting_for_ai` state, daily per-user budget tracking. |
| **Admin Privilege Abuse / Accidental Deletion** | Loss of user graph data | Destructive operations require typed confirmation (`DELETE / CONFIRM`), server-side confirmation validation, append-only `admin_audit_log`, non-destructive cascade retraction. |
| **Admin Path Discovery / Enumeration** | Attackers probe administrative endpoints | Server-side middleware returns 404 for non-admins; non-admins never see admin navigation in frontend. |
| **AI Secret Leakage in Admin UI** | Exposure of Groq API key or credentials | Endpoints return only boolean `is_configured`; keys never stored in responses, logs, or fixtures. |
| **Evidence Fabrication by Admin** | Admin manually injects unsubstantiated claims | Manual proposition addition strictly enforces deterministic evidence validation against existing user documents. |
| **Circuit Breaker Thrashed by False Positives** | Unnecessary pipeline pauses | Threshold-based trigger (consecutive failures or sustained error rate over window) with automatic half-open trial before full closure. |

---

## 5. Open Questions & Hypotheses `[Decided / Confirmed]`
- **OQ-PRD-1**: Conservative confidence thresholds? -> Adopted default (High >= 0.85, Med 0.65-0.84).
- **OQ-PRD-2**: Account deletion? -> Confirmed for Admin User Management via single-transaction hard delete.
- **OQ-PRD-3**: Document content access visibility? -> Monitoring screens show metadata only; viewing content or user graph requires explicit action and is logged in `admin_audit_log`.
- **OQ-PRD-4**: Reset limits? -> Clears usage counters, resets budget window, clears rate-limit lockouts.
