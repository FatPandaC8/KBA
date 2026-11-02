# Gusby: Product Requirements Document (PRD)
**Version:** 1.0-draft  
**Status:** In Review  
**Source of Truth Precedence:** 00_PRODUCT_BRIEF.md > 01_PRD.md > Prompt Defaults

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

### 1.4. Target Users `[Decided]`
- **Researchers & Academics**: Need to map literature, trace claims directly to page citations, and identify contradictions between studies.
- **Intelligence & Market Analysts**: Need to track entity interactions across news articles and whitepapers without risk of hallucinated connections.
- **Knowledge Workers & Domain Specialists**: Need to build personal or project knowledge bases with verifiable provenance.

---

## 2. Product Goals & Success Criteria

### 2.1. Quantitative Success Criteria `[Decided]`
1. **Evidence Validity Rate**: **100%** of propositions in the Canonical Graph must resolve to an exact, verifiable substring in the source text. Invalid evidence drops propositions from canonical integration.
2. **Extraction Precision**: **≥ 90%** precision on the benchmark gold evaluation set.
3. **Graph Interaction Performance**: Constant 60 FPS panning and semantic zooming on Desktop screens up to the enforced Level-of-Detail limit (500 nodes per projection).
4. **Per-User Isolation**: **100%** isolation verified by automated cross-tenant security tests (zero cross-user leakage).
5. **Idempotency**: Re-ingesting an identical document hash produces 0 duplicate nodes, edges, or runs.

### 2.2. Qualitative Success Criteria `[Decided]`
1. **Intellectual, Pure White Aesthetic**: Clean, distraction-free desktop canvas following the earthy-palette design system.
2. **Auditability**: Every merge, conflict, and review action is recorded with timestamp and decider (AI or User).
3. **Graceful Degradation**: Clear, actionable error messages on unsupported files (e.g. scanned PDFs without text layers) or rate-limit events.

---

## 3. Scope & Feature Boundaries

### 3.1. In-Scope Key Features (MVP) `[Decided]`

#### Feature 1: Multi-Source Ingestion
- **Text**: Direct copy-paste into textarea with character count limits.
- **URL**: Web article ingestion with SSRF protection, readability parsing, and metadata extraction.
- **Files**: `.txt`, `.pdf` (digital text layer required), `.docx` up to 10MB per file.
- **Status Lifecycle**: `Uploading` → `Processing` → `Completed` | `Failed`.

#### Feature 2: Multi-Stage Extraction Pipeline
- Document normalization (Unicode NFC) and chunking with preserved character offsets.
- Two-stage LLM extraction via Groq: Concept Extraction followed by Proposition Extraction.
- Deterministic Go-side evidence span locator and character offset validator.

#### Feature 3: Staged Entity Resolution
- Stage 1: Exact and alias match against user's existing concepts.
- Stage 2: Trigram lexical similarity using PostgreSQL `pg_trgm`.
- Stage 3: LLM adjudication strictly for ambiguous candidate pairs.

#### Feature 4: Four-Dimension Confidence Integration
Integration into the Canonical Graph evaluates four independent dimensions:
1. `Extraction Confidence` (LLM-reported confidence in concept identification)
2. `Evidence Validity` (Binary deterministic match of quote in source)
3. `Entity Resolution Confidence` (Confidence in concept canonicalization)
4. `Proposition Confidence` (Confidence in relationship validity)
- **High**: Auto-integrated into Canonical Graph.
- **Medium**: Integration Proposal created, marked with review state `needs_review = true`.
- **Low**: Retained only within the local Document Graph.
- **Invalid Evidence**: Barred from Canonical Graph.

#### Feature 5: Conflict Classification & Preservation
- Automatic detection of proposition candidates sharing identical Subject and Predicate but differing Objects or modalities.
- Classification into: Contextual Difference, Direct Contradiction, or Insufficient Evidence.
- Preservation of both propositions with their supporting evidence. Unresolved contradictions flagged with `conflict` state.

#### Feature 6: Topic Islands & Semantic Zoom
- Automatic topic assignment (many-to-many with concepts, non-hierarchical).
- 4-level semantic zoom in the desktop Knowledge Space:
  - Level 1 (Far): Topic Islands.
  - Level 2 (Closer): Core/Main Concepts per island.
  - Level 3 (Deep): Concepts and Proposition edges.
  - Level 4 (Deepest): Propositions and exact Verbatim Evidence spans.

#### Feature 7: Review as a State
- No standalone "Review Queue" page.
- Pending proposals and conflicts flagged visually directly on nodes/edges and side drawer.
- Quick filter toggle `[Needs Review]` in Knowledge Space.

#### Feature 8: Secure Multi-Tenant Auth
- Email + password registration and login using Argon2id.
- Server-side sessions with hashed tokens stored in Postgres, transmitted in `HttpOnly, Secure, SameSite=Lax` cookies.
- Hard per-user database scoping on every table and query.

---

### 3.2. Explicit Out-of-Scope List `[Decided]`
The following features are strictly **OUT OF SCOPE** for Gusby MVP:
- Mobile applications (iOS, Android) — Gusby is Desktop Web only.
- Audio capture, recording, or Speech-to-Text (STT).
- General AI conversational chatbot or reasoning assistant.
- Notion / Obsidian-style markdown editors or manual wiki note-taking.
- Tasks, reminders, or productivity tooling.
- Multi-user collaboration, workspace sharing, public links, or organization RBAC.
- Dark mode (Gusby is strictly light mode on pure white canvas).
- Nested or hierarchical topics (e.g. subtopics of subtopics).
- Freehand manual graph drawing/editing (nodes and edges reflect evidence only).
- Scanned PDF OCR (PDFs without embedded digital text layers).
- Vector databases, pgvector, or third-party embedding providers.

---

## 4. Risks & Mitigations `[Decided]`

| Risk | Impact | Mitigation Strategy |
|---|---|---|
| **Groq Free-Tier Rate Limits** (RPM/TPM caps) | Pipeline stalls or fails with HTTP 429 | Shared Go rate-limiter, exponential backoff with jitter, small chunk sizes, daily token budget tracking per user. |
| **SSRF via URL Ingestion** | Internal network or cloud metadata exposure | Private/loopback IP validation in Go before and after HTTP redirect resolution; strict HTTP/HTTPS protocol whitelist; timeout & payload size limits. |
| **Prompt Injection in Ingested Content** | Untrusted document instructions hijack extraction schema | Strict prompt boundary delimitation (`<source_document>` XML tags), deterministic JSON schema validation, zero execution of document instructions. |
| **Unicode Offset Mismatch** | Broken UI highlights on Vietnamese text | Canonical UTF-8 byte offsets stored alongside Unicode rune offsets; unified NFC normalization prior to offset indexing. |
| **Silent Knowledge Degradation** | Re-running extraction overwrites user edits or conflicting claims | Non-destructive conflict model; immutable source documents; explicit audit event logging. |

---

## 5. Open Questions & Hypotheses `[Hypothesis]`
- **OQ-PRD-1**: Are conservative confidence thresholds (e.g. High >= 0.85, Med 0.65-0.84) sufficient prior to gold set calibration? *(Status: Adopted as default)*
- **OQ-PRD-2**: Should Account Deletion be implemented in MVP? *(Status: Marked as Needs research; excluded from MVP initial delivery)*
