# Project Roadmap

This document provides the feature implementation status, remaining milestones, and explicit scope boundaries for Echo.

*Updated 2026-10-30 to reflect M3 implementation state and voice-first knowledge management direction. See `docs/PRODUCT_DIRECTION.md` for the authoritative product scope.*

---

## 1. Feature Status Matrix (as of M3, 2026-10-30)

| Subsystem / Capability | Status |
| :--- | :--- |
| **Voice recording & upload** | Implemented and verified — press-and-hold; up to 2 minutes; idempotent upload; serialized queue. |
| **STT pipeline** | Implemented and verified — faster-whisper (tiny int8 CPU), ffmpeg decode, English-only enforcement. |
| **Entity & relationship extraction** | Implemented and verified — rule-based (local) and Groq (hosted); schema-constrained output; one repair attempt; idempotent (stable UUIDs). |
| **Entity resolution** | Implemented and verified — similarity ≥ 0.90 auto-links; 0.75–0.90 flagged; tombstones; `user_edited` protection. |
| **Knowledge graph persistence** | Implemented and verified — entities, relationships, confidence, certainty, provenance, contradictions flagged. |
| **Knowledge search (hybrid)** | Implemented and verified — fastembed BAAI/bge-small-en-v1.5 + lexical ranking; 350 ms debounced; per-user scoped. |
| **My Recordings list** | Implemented and verified — date, duration, status, playback, delete, manual retry. |
| **Authentication & multi-user** | Implemented and verified — email/password, Google Sign-In, email verification, password reset, revocable sessions, rate limiting, per-user isolation. |
| **Evaluation opt-in & consent** | Implemented and verified — provider consent screen; evaluation opt-in (default off); withdrawal purges retained audio. |
| **Processing reliability** | Implemented and verified — async job worker; lease-based fault recovery; up to 3 retries; permanent errors fail cleanly. |
| **Capture-first centered FAB navigation** | Implemented (M3) — three-tab layout: Record (centre mic FAB), Graph, Recordings. |
| **Admin transcript inspection & correction** | **Gap — not yet implemented.** Admin pipeline debug view does not yet expose transcript text or allow correction. Transcripts are admin-only; this feature is not a user-facing capability. |
| **Admin dashboard (full)** | **Gap — partially implemented.** AI config and basic monitoring available; pipeline debug and accounts views incomplete. |
| **Evaluation measurement** | **Gap — extraction benchmark only.** WER, entity resolution F1, graph correctness, and provenance coverage not yet measured. |

---

## 2. Remaining Milestones

### M4: Admin Transcript Inspection & Correction

- **What it is:** An internal quality-control and evaluation capability accessible only to admins. End users do not interact with transcripts.
- **Problem:** The admin pipeline debug view does not yet expose transcript text or allow admins to correct ASR errors. Transcript correction is needed to maintain accurate evaluation datasets and to fix incorrect entity extraction caused by STT errors.
- **Scope of work:**
  1. Add transcript view to the admin pipeline debug view for each recording.
  2. Allow admins to edit transcript text inline; persist corrections with `user_edited = 1`.
  3. Corrected transcripts must be used by subsequent extraction re-runs (instead of re-calling the ASR model).
  4. Enforce admin-only authorization on `/api/admin/captures/{id}/transcript` at the backend; return 403 for any non-admin caller.
  5. All admin transcript access must be logged with an audit trail (ADM-02).
- **Not in scope:** Mobile transcript UI, user-facing transcript display, transcript search for end users.

### M5: Admin Dashboard Completion

- **Problem:** The admin dashboard is partially implemented. Pipeline debugging and accounts management views are incomplete.
- **Scope of work:**
  1. Pipeline debug view: audio playback, transcript (admin-only), extraction output, per-stage timing, error details.
  2. Accounts view: search, lock/unlock, track deletion progress.
  3. Knowledge inspection: read-only graph view per user for debugging incorrect entities/relationships.
  4. Verify all admin actions are logged with audit trail (ADM-02).

### M6: Evaluation & Quality Measurement

- **Problem:** No evaluation pipeline exists beyond the extraction benchmark. Release thresholds (PRD §7) cannot be confirmed without measurement.
- **Scope of work:**
  1. Build a gold set for WER measurement on the STT pipeline.
  2. Extend `server/eval.score` to measure entity resolution F1.
  3. Add graph construction correctness measurement (duplicate update rate, provenance coverage).
  4. Record and publish baseline results against PRD §7 thresholds.
  5. Do not claim any threshold is met until actual measurements are recorded.

### M7: Production Deployment

- **Scope of work:**
  1. Privacy policy, Data Safety declaration, account-deletion URL (DEL-04).
  2. Production environment configuration (separate from dev).
  3. Google Play submission (internal track → production).
  4. Verify production deployment end-to-end: recording → STT → extraction → knowledge graph → search.

---

## 3. Explicit Scope Boundaries & Non-Goals

| Feature | Decision | Rationale |
| :--- | :--- | :--- |
| **AI chatbot / conversational assistant** | **Removed from scope** | Echo is a knowledge management system, not an AI assistant. The knowledge layer must be independently useful without LLM reasoning. |
| **LLM question answering (GraphRAG)** | **Removed from scope** | Knowledge retrieval is deterministic search over explicitly stored entities and relationships. No LLM Q&A engine is required or planned for MVP. |
| **Multi-hop AI reasoning** | **Removed from scope** | Graph traversal is a deterministic lookup, not AI inference. |
| **Knowledge inference (new fact generation)** | **Removed from scope** | Echo stores extracted facts. It does not generate new facts from existing ones. |
| **Proactive insights / AI recommendations** | **Removed from scope** | Users explicitly search and browse. No unsolicited AI suggestions. |
| **User-visible transcript access** | **Out of scope** | Transcripts are admin-only internal artifacts. End users interact with recordings and extracted knowledge only. |
| **User transcript editing** | **Out of scope** | Transcript correction is an admin quality-control operation. It is not available to end users. |
| **Transcript full-text search (user-facing)** | **Out of scope** | User search operates over entities and relationships only. |
| **Document / PDF / image ingestion** | **Out of scope** | Voice is the only ingestion channel in the MVP. |
| **External knowledge imports** | **Out of scope** | No web extraction, database imports, or external API knowledge sources. |
| **Offline sync (CRDTs, vector clocks)** | **Out of scope** | Online backend required for processing. Local persistence retains recordings pending upload. |
| **Multi-user collaboration** | **Out of scope** | Single-user personal knowledge management. |
| **Semantic vector database as primary store** | **Out of scope** | SQLite with WAL is sufficient. Embeddings stored as serialized arrays. |
| **Autonomous agents** | **Out of scope** | No autonomous background agents in the MVP. |
