# Product Requirements Document (PRD)

**Product:** Personal Knowledge Graph & Memory  
**Version:** 1.0 — MVP Draft  
**Status:** Draft for review

## 1. Product Overview

### 1.1 Vision

Build a private personal notes-and-memory application that helps users capture information naturally, organize it into a structured knowledge graph, and preserve connections between things they know.

Users can record voice notes or enter text. The system transcribes voice locally, extracts entities, facts, and relationships using local AI, and organizes the resulting knowledge while preserving links to the original source.

The application should gradually become a reliable external memory that users can build upon over time.

**Core principle: The graph stores what the user knows; AI helps structure that knowledge without taking control away from the user.**

### 1.2 Problem Statement

Traditional note-taking applications primarily store isolated documents. Important information becomes difficult to find, relationships between notes remain implicit, and users must manually organize everything.

Maintaining a knowledge graph manually introduces another problem: users must understand the graph structure and spend time creating entities and relationships.

This product addresses both problems by combining:

- Natural voice and text capture.
- Automatic knowledge extraction.
- Explicit relationships between entities.
- Traceability from structured knowledge to original notes.
- Human review and correction of uncertain AI output.

### 1.3 Product Positioning

This is a **broader personal notes-and-memory application with a knowledge graph as a core capability**, rather than a graph visualization tool alone.

Notes preserve the original information. Entities, facts, and relationships organize that information into reusable knowledge.

The architecture should also support future capabilities such as AI-powered question answering, semantic retrieval, personal insights, recommendations, and knowledge summaries without requiring a complete redesign.

## 2. Target Users

### 2.1 Initial Users

A small group of individual users who want to capture and organize personal knowledge.

Examples include knowledge about:

- Personal interests and hobbies.
- People and relationships.
- Projects and ideas.
- Goals and learning progress.
- Preferences and experiences.
- Important facts that may be useful later.

### 2.2 User Isolation

Each user owns a separate private knowledge space.

Users must not be able to access another user's notes, entities, facts, relationships, source evidence, or AI extraction results.

Shared graphs and collaborative editing are outside the MVP scope.

## 3. Product Goals

The MVP must:

1. Make capturing information fast and convenient.
2. Convert voice recordings into text using local transcription.
3. Extract structured knowledge using local AI.
4. Preserve the original note and the provenance of extracted knowledge.
5. Distinguish explicit information from AI-generated inferences.
6. Allow users to review, correct, and manage extracted knowledge.
7. Support keyword search and graph browsing.
8. Protect personal data from external AI providers.
9. Establish a maintainable foundation for future AI capabilities.
10. Keep the server reusable independently of the mobile application.

## 4. Non-Goals

The following are explicitly excluded from the MVP:

- AI question answering over the knowledge base.
- AI-generated personal recommendations or insights.
- AI-generated summaries based on accumulated knowledge.
- Proactive notifications or autonomous actions.
- Vector embeddings and semantic search.
- External or cloud AI inference.
- Public internet access or remote access outside the home network.
- Offline operation and synchronization.
- Shared knowledge graphs or collaboration.
- Distributed microservices and complex infrastructure.
- Automated backup scheduling.

These capabilities may be considered after the core capture, extraction, review, and retrieval workflow is reliable.

## 5. Core User Journey

### 5.1 Capture and Structure Knowledge

1. The user opens the mobile application.
2. The user records a voice note or enters text.
3. The client submits the content to the home server.
4. The server stores the source note and its metadata.
5. For voice input, the server transcribes the recording locally.
6. Local AI (a decoder model) extracts candidate entities, facts, and relationships.
7. The application validates the extraction and associates each candidate with its supporting source evidence.
8. High-confidence, evidence-supported explicit facts may be saved automatically.
9. Uncertain candidates and inferred relationships are placed in a review queue.
10. The user reviews or corrects proposed knowledge when necessary.
11. The user can search notes, inspect entities, and navigate their relationships.

### 5.2 Manual Knowledge Management

Users can manually create, edit, and delete notes, entities, facts, and relationships.

Manual operations must follow the same validation, ownership, provenance, and temporal-history rules as AI-assisted operations.

## 6. Functional Requirements

Priority definitions:

- **Must:** Required for MVP acceptance.
- **Should:** Valuable but may be deferred if necessary.
- **Could:** Optional enhancement.

### 6.1 Capture and Notes

| ID | Requirement | Priority |
|---|---|---|
| FR-001 | Users can create text notes. | Must |
| FR-002 | Users can record and upload voice notes through the mobile client. | Must |
| FR-003 | The server stores the source note and relevant metadata. | Must |
| FR-004 | Users can list, view, edit, and delete their notes. | Must |
| FR-005 | The system exposes processing status for transcription and extraction. | Must |
| FR-006 | Failed processing can be retried without creating duplicate knowledge. | Must |
| FR-007 | Audio retention follows an explicit, documented policy. | Must |

### 6.2 Local AI Processing

| ID | Requirement | Priority |
|---|---|---|
| FR-008 | Voice transcription runs on the user's home server. | Must |
| FR-009 | Entity, fact, and relationship extraction runs using a locally hosted model. | Must |
| FR-010 | AI output follows a defined structured schema. | Must |
| FR-011 | The system validates AI output before persistence. | Must |
| FR-012 | Extraction runs record model and prompt/schema versions. | Must |
| FR-013 | The system distinguishes explicit statements from inferred knowledge. | Must |
| FR-014 | Uncertain or ambiguous extraction results are available for review. | Must |

### 6.3 Knowledge Graph

| ID | Requirement | Priority |
|---|---|---|
| FR-015 | Users can create, edit, and delete entities. | Must |
| FR-016 | Users can create, edit, and delete facts. | Must |
| FR-017 | Users can create, edit, and delete typed relationships. | Must |
| FR-018 | Knowledge records can link to supporting source notes and evidence. | Must |
| FR-019 | Users can inspect an entity's direct relationships. | Must |
| FR-020 | The system preserves historical assertions when time-sensitive facts change. | Must |
| FR-021 | Ambiguous entity matches are flagged instead of being merged automatically. | Must |

### 6.4 Review and Correction

| ID | Requirement | Priority |
|---|---|---|
| FR-022 | Users can inspect pending extraction proposals. | Must |
| FR-023 | Users can accept or reject a proposal. | Must |
| FR-024 | Users can edit a proposal before accepting it. | Must |
| FR-025 | Review decisions are persisted and resolved items do not remain pending. | Must |
| FR-026 | Users can trace proposed and accepted knowledge to its source. | Must |

### 6.5 Search and Retrieval

| ID | Requirement | Priority |
|---|---|---|
| FR-027 | Users can search notes by keyword. | Must |
| FR-028 | Users can search entities by name. | Must |
| FR-029 | The system supports practical typo-tolerant search where feasible. | Should |
| FR-030 | Users can browse a bounded neighborhood of graph relationships. | Must |
| FR-031 | Search results expose relevant source-note references. | Must |

### 6.6 Privacy and Operations

| ID | Requirement | Priority |
|---|---|---|
| FR-032 | Each user has an isolated private knowledge graph. | Must |
| FR-033 | Every API operation enforces authorization and ownership. | Must |
| FR-034 | Personal content is never sent to external AI providers. | Must |
| FR-035 | The service provides health checks and useful processing errors. | Should |
| FR-036 | Manual backup and restoration procedures are documented and tested. | Must |

## 7. Knowledge and Trust Rules

### 7.1 Provenance

Every AI-created fact or relationship must link to its originating note and extraction run. When practical, it must also retain a supporting text span.

The system must not present AI-generated knowledge as an independently verified fact.

### 7.2 Explicit and Inferred Knowledge

- **Explicit:** Directly stated or clearly supported by the user's source material.
- **Inferred:** A conclusion proposed by the model that is not directly stated.
- **User-entered:** Knowledge explicitly created or corrected by the user.

Inferred relationships require review in the MVP. High-confidence explicit facts may be automatically saved only when they pass validation and evidence requirements.

Model confidence scores are heuristics, not guaranteed probabilities.

### 7.3 Temporal Information

The system distinguishes:

- When information was recorded.
- When the information was valid in the real world, if known.
- Whether a newer assertion supersedes an older one.

Changing a fact must not silently erase its previous history.

### 7.4 Entity Resolution

When an extraction mentions an entity that may already exist, the system should match it to an existing entity only when the match is sufficiently reliable.

Ambiguous matches must be sent for review. Incorrect entity merging can contaminate many connected records, so conservative behavior is preferred.

### 7.5 Deletion

Users must be able to delete their own data.

The implementation must define how deleting a note affects extracted knowledge and its evidence. Permanent deletion must also account for retained audio files. The behavior must be clear to users and must not leave misleading provenance references.

## 8. Non-Functional Requirements

### 8.1 Privacy and Security

- Local inference for transcription and extraction.
- No external AI APIs or hosted inference endpoints.
- Authentication and authorization on every private resource.
- No cross-user access through search, nested references, or graph traversal.
- No note bodies, transcripts, audio, or sensitive model outputs in routine logs.
- The service is not publicly exposed by default.

### 8.2 Performance

The system should remain usable on the intended home-server hardware.

Initial performance targets will be set after measuring transcription and extraction latency, memory consumption, and quality using representative data.

The application should avoid loading multiple large models concurrently when doing so would exceed available memory.

### 8.3 Maintainability

- Use a modular monolith rather than microservices.
- Keep domain logic independent of FastAPI, PostgreSQL, and AI runtimes.
- Use interfaces at meaningful boundaries, including persistence, transcription, and extraction.
- Keep business rules in application/domain services rather than HTTP handlers.
- Avoid unnecessary abstractions and premature infrastructure.
- Expose reusable server capabilities through a documented API.

### 8.4 Reliability

- Use database transactions for related knowledge changes.
- Make retries safe and prevent duplicate extraction results.
- Track processing status and failures.
- Use database migrations.
- Verify backup restoration into a clean environment.

### 8.5 Usability

- Clearly distinguish completed processing, pending review, and failed processing.
- Show source evidence for proposed knowledge.
- Make correction and rejection straightforward.
- Provide understandable errors and retry options.

## 9. Technical Direction

The following is the initial recommended direction, subject to implementation validation.

| Layer | Proposed technology |
|---|---|
| Mobile client | Flutter and Dart |
| API | Python and FastAPI |
| API validation | Pydantic |
| Canonical database | PostgreSQL |
| Database access | SQLAlchemy, where useful |
| Migrations | Alembic |
| Local transcription | Evaluate faster-whisper |
| Local extraction | Evaluate a small quantized instruct model through llama.cpp or a compatible local runtime |
| Search | PostgreSQL full-text search and optional `pg_trgm` |
| Deployment | Docker Compose |
| Testing | pytest, API/integration tests, and Flutter tests |

The database stores notes and structured knowledge in one canonical system. A separate graph database, search cluster, vector database, Redis instance, or message broker is not required for the MVP.

The exact model versions must be chosen through testing on the target hardware, not assumed in advance.

## 10. MVP Success Criteria

The MVP is considered complete when all the following are demonstrated:

1. A user can capture a note through text and voice.
2. Voice transcription and extraction run locally without sending personal content to external AI services.
3. The system creates structured knowledge from a note.
4. Every accepted AI-created fact or relationship has traceable provenance.
5. Uncertain or inferred knowledge is reviewable.
6. Users can correct and delete notes and knowledge.
7. Users can search notes and entities and browse direct graph relationships.
8. Cross-user isolation tests pass with zero unauthorized reads or mutations.
9. Retried processing does not create duplicate knowledge.
10. Backup restoration recovers notes, knowledge, review state, and provenance.

The first evaluation should measure extraction quality, auto-save precision, review frequency, processing latency, and memory use. Quality thresholds should be set after establishing a labeled baseline.

## 11. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Local models are too slow or memory-intensive | Benchmark small quantized models and run inference sequentially. |
| AI invents relationships | Require validation and provenance; review inferred relationships. |
| Existing entities are incorrectly merged | Use conservative matching and a review workflow. |
| Changing facts destroys history | Preserve validity and supersession history. |
| Notes or evidence leak across users | Enforce ownership throughout the application and test every access path. |
| Scope expands before the core works | Defer Q&A, insights, semantic search, remote access, and distributed infrastructure. |
| Home-server failure causes data loss | Document and test manual backup and restoration. |

## 12. Decisions Still Open

The following details should be resolved during implementation rather than guessed:

1. **Model selection:** Exact transcription and extraction models after target-hardware benchmarking.
2. **Confidence policy:** Thresholds calibrated against a small manually labeled dataset.
3. **Audio retention:** Whether audio is deleted after transcription by default or retained according to a user-configurable policy.
4. **Authentication:** Final session/token approach appropriate for a home-network deployment.
5. **Entity merging:** Whether the MVP supports explicit entity merge or only conservative matching and review.
6. **Performance targets:** Numerical latency and memory targets after baseline measurements.

These open decisions do not prevent implementation of the core architecture and data model.
