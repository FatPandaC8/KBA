# MVP_PLAN.md

## 1. Purpose

Define the implementation plan for the first usable version of the personal notes-and-memory application.

The MVP is successful when a small group of users can independently capture information, turn it into structured personal knowledge, review and correct AI suggestions, and retrieve that knowledge later.

The MVP prioritizes **a reliable end-to-end workflow over feature breadth**.

## 2. MVP Objective

Deliver a mobile-first personal knowledge application that allows each user to:

1. Capture information through text or voice.
2. Convert voice into text using local transcription.
3. Extract entities, facts, and relationships using local AI.
4. Review uncertain extraction results.
5. Store and edit knowledge in PostgreSQL.
6. Search notes and entities.
7. Explore direct connections in the knowledge graph.
8. Back up and restore personal data.

All personal data processing must remain within the user's self-hosted environment. Personal data must never be sent to external AI providers.

## 3. Scope

### 3.1 Must Have — P0

| Feature | Requirements | Acceptance condition |
|---|---|---|
| User isolation | Each user has a separate private knowledge graph | One user cannot read or modify another user's data |
| Text capture | Create, view, edit, and delete notes | Note content persists after restart |
| Voice capture | Record voice and submit it to the server | Audio is transcribed before knowledge extraction |
| Local transcription | Run speech recognition on the home server | No external transcription service is called |
| Local knowledge extraction | Extract entities, facts, relationships, and evidence from text | Valid output conforms to the extraction schema |
| Knowledge persistence | Store validated knowledge in PostgreSQL | Knowledge remains available after restart |
| Review workflow | Accept, reject, or dismiss uncertain proposals | Rejected proposals do not become active knowledge |
| Manual knowledge editing | Create, edit, and delete entities, facts, and relationships | Changes persist and maintain referential integrity |
| Provenance | Link extracted facts and relationships to source text | Users can inspect supporting excerpts |
| Keyword search | Search notes and entities | Results are relevant and restricted to the current user |
| Graph exploration | Browse an entity's direct connections | The application shows connected entities and relationship types |
| Temporal history | Preserve superseded facts and relationships | Corrections do not silently destroy previous records |
| Backup and restore | Provide documented backup and recovery steps | A backup can restore usable notes and knowledge |
| Local deployment | Run the application on the home PC | Mobile clients can connect over the home network |

### 3.2 Should Have — P1

- Fuzzy entity-name matching.
- Entity duplicate suggestions.
- Re-run extraction after a note is corrected.
- Clear indicators for explicit versus inferred knowledge.
- Basic filtering by entity type.
- Extraction retry and understandable error messages.
- A simple overview of pending review items.

### 3.3 Out of Scope

Do not implement these as part of the initial MVP:

- AI chat or question answering over the knowledge base.
- Proactive recommendations, reminders, or autonomous actions.
- Semantic/vector search.
- A separate graph database.
- Cloud AI APIs or external AI providers.
- Collaboration and shared graphs.
- Complex note version history.
- Public registration or internet-facing deployment.
- A custom-trained language model.
- Automated scheduling or task management.
- Automatic execution of destructive commands extracted from natural language.

## 4. Product Workflow

### Workflow A: Text Note

1. User enters a note.
2. Server validates the request and saves the original text.
3. Local extraction model produces structured candidate knowledge.
4. Application validates the output and resolves known entities.
5. High-confidence, explicit assertions may be saved automatically according to the configured policy.
6. Ambiguous entities, uncertain facts, and inferred relationships enter the review queue.
7. User inspects, edits, accepts, or rejects proposals.
8. The application persists accepted knowledge and evidence in PostgreSQL.

### Workflow B: Voice Note

1. User records audio in the mobile app.
2. The app submits the audio to the self-hosted server.
3. Server transcribes the audio locally.
4. Server returns the transcript for confirmation or correction when needed.
5. The confirmed transcript is saved as a note with `capture_type = voice`.
6. The text follows the same extraction and review pipeline as a typed note.
7. Temporary audio is discarded after successful transcription unless a specific retry or retention policy requires otherwise.

**Voice and text must converge on the same knowledge-extraction pipeline.** There should not be separate extraction logic for voice notes.

### Workflow C: Retrieve Knowledge

1. User searches for a note or entity.
2. The server executes a user-scoped database query.
3. The user opens a result.
4. The application displays associated facts, relationships, and evidence.
5. The user can navigate to directly connected entities.

## 5. Implementation Phases

Phases should be completed in dependency order. Do not build every screen or AI feature before validating the underlying data flow.

### Phase 0 — Freeze MVP Contracts

**Goal:** Resolve the decisions that affect interfaces and database design.

Tasks:

- Finalize `PRD.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `API_SPEC.md`, and `TEST_PLAN.md`.
- Define the structured extraction output schema.
- Define the distinction between explicit facts and inferred knowledge.
- Define extraction acceptance and review rules.
- Choose initial transcription and extraction models based on local hardware tests.
- Decide how users are provisioned and authenticated.
- Define audio cleanup behavior.
- Define how note edits invalidate prior extraction results.

Deliverables:

- Approved core documents.
- Initial API and extraction schemas.
- A small, versioned set of extraction examples.

**Exit criteria:** The mobile client, API, database, and AI adapter can be implemented without guessing their core contracts.

### Phase 1 — Backend Foundation

**Goal:** Establish a reliable application server and canonical database.

Tasks:

- Initialize the Python project and FastAPI application.
- Configure PostgreSQL and SQLAlchemy.
- Set up Alembic migrations.
- Implement user-scoped repository operations.
- Implement note CRUD.
- Implement entity, fact, and relationship CRUD.
- Enforce ownership and referential integrity.
- Implement health checks and structured logging.
- Add automated tests for persistence and isolation.

Deliverables:

- Running API.
- Migrated PostgreSQL schema.
- Working CRUD operations.
- Database integration tests.

**Exit criteria:** Notes and knowledge records can be created, retrieved, edited, and deleted without corrupting relationships or crossing user boundaries.

### Phase 2 — Text-to-Knowledge Pipeline

**Goal:** Turn a typed note into validated, traceable knowledge.

Tasks:

- Define a strict structured extraction schema.
- Implement the `KnowledgeExtractor` interface.
- Connect a local model that can produce schema-conforming output.
- Validate model output using Pydantic.
- Implement entity resolution and duplicate detection.
- Implement evidence linking.
- Implement confidence and review rules.
- Make extraction idempotent where possible.
- Record extraction runs and failures.
- Add test fixtures covering ordinary notes, ambiguity, corrections, and unsupported inferences.

Deliverables:

- Working text extraction pipeline.
- Canonical entity, fact, and relationship persistence.
- Evidence and review records.
- Extraction tests.

**Exit criteria:** A note can produce valid structured knowledge without losing its original text, and repeated extraction does not blindly duplicate the graph.

### Phase 3 — Local AI Runtime

**Goal:** Run extraction and transcription without external AI services.

Tasks:

- Integrate the chosen local speech-to-text runtime.
- Integrate the chosen local extraction model.
- Configure model paths and runtime settings.
- Add timeout, cancellation, and failure handling.
- Keep AI inference behind replaceable interfaces.
- Ensure inference requests do not call external providers.
- Benchmark memory usage, latency, and extraction quality on the target PC.
- Verify that transcription and extraction can operate within available RAM.

Deliverables:

- Local transcription adapter.
- Local extraction adapter.
- Benchmark results and documented model configuration.

**Exit criteria:** Representative text and voice inputs can be processed entirely locally with acceptable quality and without exhausting system memory.

### Phase 4 — Mobile Client and Review Workflow

**Goal:** Make the core workflow usable from a phone.

Tasks:

- Initialize the Flutter application.
- Implement API client and error handling.
- Implement note list and note editor.
- Implement text capture.
- Implement voice recording and upload.
- Show the transcript and allow correction.
- Implement extraction status and review queue.
- Implement proposal detail, accept, reject, and dismiss actions.
- Implement entity, fact, and relationship detail views.
- Display source evidence and explicit/inferred labels.

Deliverables:

- Functional mobile client.
- End-to-end text and voice capture.
- Review and correction interface.

**Exit criteria:** A user can capture a note, inspect extracted knowledge, correct it, and confirm the final state from a mobile device.

### Phase 5 — Search and Graph Exploration

**Goal:** Make saved knowledge useful after capture.

Tasks:

- Implement PostgreSQL full-text search for notes.
- Implement entity search by canonical name and aliases.
- Add `pg_trgm` fuzzy matching if tests demonstrate value.
- Implement bounded direct-neighbor queries.
- Display relationships and connected entities.
- Add basic filtering and pagination.
- Verify user isolation for all search and traversal paths.

Deliverables:

- Search interface.
- Entity detail and connection views.
- Query and integration tests.

**Exit criteria:** Users can retrieve notes and navigate the graph without exposing another user's information or triggering unbounded traversal.

### Phase 6 — Backup, Security, and Reliability

**Goal:** Make the application safe enough for actual personal use.

Tasks:

- Document deployment on the home PC.
- Configure secrets and database credentials.
- Implement the chosen authentication and user-provisioning model.
- Restrict server access to the intended home-network environment.
- Document and test backup and restore.
- Define deletion and audio-cleanup behavior.
- Test database migrations from a clean installation.
- Test recovery from failed transcription and extraction.
- Verify that personal data is not sent to external AI providers.
- Check logs for accidental exposure of note contents, transcripts, credentials, or sensitive model input.

Deliverables:

- Deployment instructions.
- Backup and restore instructions.
- Security checklist.
- Recovery and migration tests.

**Exit criteria:** A fresh installation can be deployed, backed up, restored, and used without relying on external AI services.

### Phase 7 — MVP Acceptance

**Goal:** Validate the complete product against real usage scenarios.

Tasks:

- Run the complete automated test suite.
- Execute the end-to-end acceptance scenarios.
- Test with a small set of realistic personal notes.
- Review extraction errors and user correction effort.
- Measure transcription and extraction latency on target hardware.
- Fix P0 defects.
- Document known limitations.

Deliverable:

- MVP release candidate and acceptance report.

**Exit criteria:** Every P0 acceptance condition is met, and unresolved issues are documented rather than hidden.

## 6. Recommended Technical Stack

| Layer | Choice | Reason |
|---|---|---|
| Mobile | Flutter and Dart | One mobile codebase |
| State management | Riverpod | Explicit application state |
| HTTP client | Dio | API communication and upload support |
| API | Python and FastAPI | Small, typed API surface and strong local AI ecosystem |
| Validation | Pydantic | Request and extraction-output validation |
| Persistence | SQLAlchemy | Relational persistence |
| Migrations | Alembic | Versioned schema changes |
| Database | PostgreSQL | Canonical notes and knowledge store |
| Search | PostgreSQL full-text search; optional `pg_trgm` | Avoid separate search infrastructure |
| Transcription | `faster-whisper` or another locally benchmarked runtime | Local speech recognition |
| Extraction | Small quantized local instruction model | Structured knowledge extraction |
| Model runtime | `llama.cpp` or compatible local runtime | CPU-friendly inference options |
| Deployment | Simple local service configuration | Low operational overhead |

Model choices are provisional until benchmarked on the target hardware. Keep model-specific code behind application interfaces.

## 7. Architecture Boundaries

Use a modular monolith, not microservices.

Recommended dependency direction:

```text
Flutter client
      │
      ▼
FastAPI routes
      │
      ▼
Application services
      │
      ├── Note service
      ├── Knowledge service
      ├── Extraction service
      ├── Review service
      └── Search service
              │
              ▼
      Repository interfaces
              │
              ▼
         PostgreSQL

Extraction service ──► Local model adapter
Voice workflow ──────► Local transcription adapter
```

Rules:

- API routes handle HTTP concerns, not business logic.
- Application services enforce workflows and ownership rules.
- Repositories handle persistence.
- Local AI adapters handle inference and output generation.
- Domain logic must not depend directly on FastAPI or a specific model runtime.
- Introduce abstractions where they isolate real change or simplify testing, not for every class.

## 8. Milestones and Dependencies

| Milestone | Depends on | Completion signal |
|---|---|---|
| M0: Contracts frozen | Product decisions | Core schemas and interfaces agreed |
| M1: Data foundation | M0 | CRUD and isolation tests pass |
| M2: Text extraction | M1 | Text produces validated knowledge |
| M3: Local AI | M2 | Extraction and transcription run locally |
| M4: Mobile capture | M1, M3 | Phone can capture and review notes |
| M5: Retrieval | M1 | Search and graph exploration work |
| M6: Reliability | M1–M5 | Backup, restore, and security checks pass |
| M7: Acceptance | M0–M6 | P0 acceptance criteria pass |

Some work can be parallelized after the relevant contracts are stable. Avoid implementing the client against an unsettled API schema.

## 9. MVP Acceptance Scenarios

The MVP must pass these scenarios:

1. **Text capture:** Create a note and retrieve the same content after a server restart.
2. **Voice capture:** Submit voice, obtain a transcript locally, correct it, and save it as a note.
3. **Extraction:** Extract supported entities, facts, and relationships from a known test note.
4. **Evidence:** Open an extracted fact and inspect its source excerpt.
5. **Review:** Reject an uncertain proposal and verify that it does not become active knowledge.
6. **Correction:** Correct a fact and verify that the old value remains available as superseded history.
7. **Idempotency:** Re-run extraction on the same unchanged note and verify that duplicate active knowledge is not blindly created.
8. **Search:** Find a note by a distinctive phrase and an entity by its name.
9. **Graph traversal:** Open an entity and inspect its direct relationships.
10. **Isolation:** Verify that one user cannot access another user's notes, entities, evidence, or review items.
11. **Local-only processing:** Disable internet access and verify that transcription and extraction still work after models are installed.
12. **Recovery:** Restore a backup and verify that notes, knowledge, and evidence remain consistent.
13. **Failure handling:** Simulate failed transcription or extraction and verify that the application reports the failure without inventing knowledge.
14. **Privacy:** Inspect outbound requests and logs to verify that personal note content is not sent to external AI services or unnecessarily exposed in logs.

## 10. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Local models are too slow or memory-intensive | Benchmark early; select smaller quantized models; avoid concurrent model loads |
| Extraction produces incorrect facts | Require evidence, validate schemas, apply confidence rules, and provide review |
| Entity duplication fragments the graph | Normalize names, resolve against existing entities, and offer merge suggestions |
| Repeated extraction creates duplicate records | Track source versions and implement idempotent persistence |
| Transcript errors corrupt knowledge | Allow transcript correction and make extraction depend on the confirmed text |
| Cross-user data leakage | Scope repository operations and test database ownership constraints |
| Scope grows beyond a manageable MVP | Defer chat, vector search, automation, collaboration, and custom model training |
| Data loss during development or deployment | Test backup restoration, not merely backup creation |

## 11. MVP Success Metrics

The MVP is successful when:

- All P0 functional requirements pass.
- Every voice-derived note enters extraction as text.
- No raw audio is persisted in PostgreSQL.
- No personal data is sent to external AI providers.
- All user-isolation tests pass.
- Every accepted AI-extracted fact or relationship has appropriate provenance where the source supports it.
- Repeated extraction does not blindly duplicate active knowledge.
- A backup can be restored into a working installation.
- Representative voice and text inputs complete the workflow within an acceptable latency budget established through target-hardware benchmarks.
- A small group of users can complete the primary workflow without developer intervention.

Do not define an arbitrary extraction-accuracy target before creating a representative evaluation set. Establish a baseline first, then set a measurable quality target.

## 12. Implementation Rules

- Build one complete vertical slice at a time.
- Start with text capture and persistence before adding voice.
- Validate local model feasibility early rather than postponing it until mobile integration.
- Keep the canonical database independent of model output formats.
- Treat AI output as untrusted input.
- Never execute commands or destructive actions merely because a model extracted them from a note.
- Avoid adding services or infrastructure without a demonstrated requirement.
- Keep the six core documents synchronized when an API, schema, or product decision changes.

The first end-to-end milestone should be: **create a text note → extract structured knowledge locally → review uncertain results → save to PostgreSQL → search and retrieve the knowledge.** Voice capture can then reuse the same pipeline after transcription.