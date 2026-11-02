# Echo — Product Direction

*This document is the authoritative definition of Echo's product scope, MVP boundaries, and architectural principles. It supersedes any conflicting statements in earlier documents. When documents conflict, this file takes precedence.*

---

## 1. Canonical Product Definition

**Echo is a voice-first personal knowledge management system that transforms natural speech into structured, connected, and searchable knowledge. It automatically transcribes recordings, extracts entities and relationships, resolves references across recordings, and maintains a persistent knowledge graph with traceable evidence. Users can explore, search, verify, and manage their knowledge without relying on an AI reasoning or conversational assistant.**

---

## 2. Core Workflow

```
Voice Capture
      │
      ▼
Speech Processing (ASR / Transcription)
      │
      ▼
Knowledge Extraction (Entity & Relationship Extraction)
      │
      ▼
Entity Resolution (Deduplication, Merging, Conflict Handling)
      │
      ▼
Knowledge Graph Construction (Incremental Graph Update)
      │
      ▼
Knowledge Retrieval (Search, Browse, Explore, Correct)
```

Each stage is a distinct responsibility. Extraction produces candidate entities and relationships. Resolution and graph construction are deterministic application logic — they are not AI inference. Retrieval operates over explicitly extracted and stored knowledge — it does not require an LLM.

---

## 3. MVP Functional Scope

### A. Voice Capture and Management

- Audio recording (press-and-hold).
- Recording lifecycle management (queued, transcribing, extracting, ready, failed).
- Audio storage and authenticated playback.
- Recording metadata (duration, timestamp, status, failure reason).
- Recording history with manual retry.
- Processing status tracking.

### B. Speech Processing

- Automatic speech recognition (ASR) using local faster-whisper.
- Transcript generation with sentence segmentation.
- Timestamp alignment.
- Transcript stored as an internal pipeline artifact, accessible to admins only for debugging and evaluation.
- Audio/transcript traceability (transcript is anchored to its source recording).
- English-only; non-English input fails with a clear error and no fabricated knowledge.

### C. Knowledge Extraction

- Entity extraction from transcript text.
- Entity classification (person, organization, place, project, concept, tool, idea).
- Entity mention detection with confidence scores.
- Relationship extraction with relation type classification.
- Evidence extraction (which transcript segment supports each entity or relationship).
- Structured output validation (schema-constrained, no schema repair loops).
- Extraction is idempotent: re-running extraction for the same recording produces the same result.

### D. Knowledge Resolution and Organization

- Entity resolution: matching newly extracted entities to existing graph entities.
- Duplicate detection with configurable similarity thresholds.
  - Similarity ≥ 0.90: automatic linking.
  - Similarity 0.75–0.90: flagged as a candidate duplicate, no automatic merge.
- Entity merging is explicit and user-confirmed; silent merges are not permitted.
- Relationship deduplication.
- Incremental knowledge graph updates: new recordings extend the graph, they do not rebuild it.
- Conflict handling: contradictory relationships are both preserved and flagged, never auto-resolved.
- Knowledge consistency: tombstones for deleted entities; `user_edited` flag protects user corrections from being overwritten by reprocessing.

### E. Knowledge Graph

- Persistent entity storage with stable, deterministic IDs.
- Relationship management (add, confirm, delete, flag conflicts).
- Entity-centric knowledge organization.
- Cross-recording connections: the same entity mentioned in multiple recordings is unified.
- Graph traversal for browsing related entities and relationships.
- Knowledge history: provenance is preserved; every entity and relationship traces back to its source recording and transcript segment.
- Evidence tracking: deletion of a recording correctly withdraws its evidential support.

### F. Knowledge Retrieval and Exploration

- Recording search (by date, status, content).
- Entity search (by name, type, keyword; hybrid embedding + lexical ranking).
- Relationship browsing (entity detail shows all relationships).
- Related recording discovery (which recordings mention a given entity).
- Entity detail pages with name, type, description, certainty status, provenance, and related recordings.
- Graph exploration with zoom, pan, and cluster collapsing.
- Manual correction and verification: users can edit entity names/descriptions and delete incorrect entities/relationships. These corrections are protected from reprocessing by the `user_edited` flag.

---

## 4. Voice-Only Ingestion Policy

Voice recordings are the only independent source of new knowledge in the MVP.

**Excluded ingestion channels:**
- Document ingestion (PDF, DOCX, etc.)
- Image ingestion
- External knowledge imports
- Web browsing or web extraction
- Arbitrary text-based knowledge creation

**Not excluded — these are knowledge management, not ingestion:**
- Entity name and description editing.
- Manual entity and relationship deletion.

---

## 5. Explicitly Excluded Features

The following are **out of scope for the MVP**. Do not design for them, do not introduce them as hidden architectural dependencies, and do not frame existing capabilities as steps toward them.

| Feature | Status |
|---|---|
| AI chatbot or conversational assistant | Excluded |
| Question answering over the knowledge graph using an LLM | Post-MVP |
| Multi-hop AI reasoning | Excluded |
| Knowledge inference (generating new facts from existing ones) | Excluded |
| Proactive insights | Excluded |
| Pattern discovery powered by AI | Excluded |
| AI recommendations | Excluded |
| Autonomous agents | Excluded |
| AI-generated summaries as a core product requirement | Excluded |
| Knowledge graph designed to support an AI reasoning engine | Excluded |
| Document ingestion | Excluded |
| Image ingestion | Excluded |
| External knowledge imports | Excluded |
| Semantic vector database (as a primary store) | Excluded |
| Multi-modal ingestion | Excluded |
| Offline sync with CRDTs or vector clocks | Excluded |
| Multi-user collaboration | Excluded |

---

## 6. Architectural Principles

1. **Knowledge-first, not AI-first.** The product's value comes from capturing, organizing, connecting, and retrieving knowledge. The knowledge layer must be independently useful without an LLM reasoning engine.

2. **Voice as the primary ingestion interface.** All new knowledge originates from voice recordings in the MVP.

3. **Knowledge Layer independence.** Knowledge storage, management, search, and graph traversal must work without a running LLM. Embedding-based entity search is retrieval, not reasoning.

4. **Evidence-grounded knowledge.** Every extracted entity and relationship must be traceable to its source recording and transcript segment. Provenance is not optional.

5. **Separation of extraction and graph construction.** AI models extract candidate entities and relationships from transcripts. Deterministic application logic validates, resolves, deduplicates, and updates the knowledge graph.

6. **Incremental updates.** New recordings update existing knowledge rather than rebuilding the entire graph from scratch.

7. **Data integrity and user trust.** Silent incorrect merges, duplicate graph updates, and loss of user corrections are defects, not acceptable tradeoffs.

8. **Model independence.** ASR and extraction models must be replaceable (by swapping provider configuration) without redesigning the Knowledge Layer.

9. **Pragmatic engineering.** Avoid unnecessary infrastructure, microservices, graph databases, and AI orchestration platforms. The server uses PostgreSQL 16 with ports and a unit-of-work boundary; the Flutter client keeps its own on-device SQLite store. There is no server-side worker or job queue.

10. **No premature expansion.** Do not introduce semantic reasoning, multi-modal ingestion, or autonomous agents without a demonstrated MVP requirement.

---

## 7. Terminology Clarifications

These distinctions must be maintained consistently throughout all documentation:

| Concept A | Is NOT the same as | Concept B |
|---|---|---|
| Entity extraction | | Entity resolution |
| Relationship extraction | | Graph construction |
| Graph traversal | | AI reasoning |
| Full-text search | | Semantic reasoning |
| Knowledge retrieval | | LLM-powered Q&A |
| Storing relationships | | Inferring new relationships |
| Embedding similarity search | | AI inference |
| Transcript (internal artifact, admin-only) | | Extracted knowledge (entities, relationships — user-facing) |

Embedding-based similarity is a retrieval mechanism, not an inference engine. Describing graph traversal or relationship lookups as "AI" is inaccurate and must be avoided.

---

## 8. Evaluation Strategy

Retain and refine evaluation requirements for the actual pipeline:

| Component | Metrics |
|---|---|
| ASR (STT) | WER ≤ 15%, CER |
| Entity extraction | Precision, Recall, F1 ≥ 0.70 |
| Relationship extraction | Precision, Recall, F1 ≥ 0.50 (correct label and correct source–target pair) |
| Entity resolution | Pairwise Precision, Recall, F1 |
| Graph construction | Node and edge correctness, consistency, no duplicate updates |
| Provenance | Evidence coverage and correctness |
| Processing | Latency, failure rate, retry rate |
| Reliability | Duplicate update rate, data loss rate, correction preservation rate |

**Excluded evaluation targets:**
- LLM question answering correctness
- Multi-hop reasoning quality
- Recommendation quality
- AI inference accuracy
- AI-generated insight quality

Evaluation results must use an actual gold set and actual measurements. Do not invent benchmark results or claim performance targets have been achieved without verified measurements.

---

## 9. Document History

| Date | Change |
|---|---|
| 2026-10-30 | Initial creation. Establishes voice-first KMS direction; removes conversational AI from MVP scope. Transcripts are admin-only internal processing artifacts; end users interact with recordings and extracted knowledge only. |
| 2026-10-30 | Correction: removed incorrectly introduced user-facing transcript access (viewing, correction, full-text search). Transcripts remain admin-only. |
