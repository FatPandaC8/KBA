# Gusby Open Questions & Hypotheses (OPEN_QUESTIONS.md)

This document tracks all open questions, hypotheses, and items requiring explicit user confirmation.
Following the Autonomy Protocol, any blocking open questions remaining after Phase 1 are batched into a single question set.

---

## 1. Product & Scope Questions

### OQ01: Verbatim Vietnamese Product Brief
- **Type**: Operational / Source-of-Truth
- **Status**: Open (Non-blocking for Phase 1 documentation; synthesized from prompt sections 0-13)
- **Question**: The prompt stated: *"The Product Brief (pasted at the end of this prompt). It is written in Vietnamese. Save it verbatim as `docs/gusby/00_PRODUCT_BRIEF.md`."* However, no Vietnamese text was attached to the end of the initial prompt.
- **Current Action**: We synthesized `00_PRODUCT_BRIEF.md` in detail based on Section 8 ("Product Behavior (from the Brief, summarized)") and all prompt specifications.
- **Recommended Default**: Keep the synthesized brief active for development, and overwrite with verbatim text if the user supplies it later.

### OQ02: Review State Discovery in Knowledge Space
- **Type**: UX / Product Behavior
- **Status**: Hypothesis (Prompt default adopted)
- **Question**: Since review is a state rather than a separate page, how should users discover pending reviews?
- **Prompt Default**: A prominent "Needs review" filter toggle in the Knowledge Space floating controls. When toggled, only nodes and edges with pending proposals, conflicts, or ambiguous merges are highlighted; clicking any flagged element opens its review sidebar.
- **Status**: Decided as default pending user feedback.

### OQ03: Account Deletion and Data Export
- **Type**: Architecture / Scope
- **Status**: Needs research (Prompt default adopted)
- **Question**: Should full account deletion (cascading purge of user's private documents, concepts, propositions, topics) and full JSON/GraphML export be included in MVP?
- **Prompt Default**: Out of MVP scope for initial build; documented in TRD as "Needs research". Implement only upon explicit approval.

---

## 2. Technical & Architectural Questions

### OQ04: Server Ports & Coordination with Echo
- **Type**: Dev Environment
- **Status**: Hypothesis
- **Question**: Echo FastAPI runs on `127.0.0.1:8000` and Echo Admin runs on `127.0.0.1:5174`. What ports should Gusby use?
- **Recommended Default**:
  - Gusby Go API server: `http://127.0.0.1:8080` (configurable via `GUSBY_PORT`)
  - Gusby Nuxt 3 frontend: `http://127.0.0.1:3000` (configurable via `PORT`)
  - PostgreSQL: `127.0.0.1:5432`, database `echo_kb`, dedicated schema `gusby`.

### OQ05: Maximum Document Size and Chunking Parameters
- **Type**: Pipeline / Rate Limits
- **Status**: Hypothesis
- **Question**: What are the upper limits for input documents to protect Groq free-tier tokens?
- **Recommended Default**:
  - Maximum text length: 50,000 characters per document (~10,000 tokens).
  - Maximum file upload size: 10 MB (TXT, PDF, DOCX).
  - Chunk size: 1,500 – 2,500 characters with 200 character overlap, splitting on paragraph/sentence boundaries to ensure context preservation and small prompt payloads.
  - Per-user token budget: 40,000 tokens / day on Groq free tier.

---

## 3. Batch Question Summary (for Phase 1 Exit)
If any of the above defaults require alteration, they can be reviewed in the Phase 1 batched question set. Otherwise, recommended defaults will govern execution.
