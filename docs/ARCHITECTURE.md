# Architecture Reference

This document describes the technical architecture, data flows, database schemas, API contracts, and component responsibilities for Echo.

*Updated 2026-10-30 to reflect the M3 implementation and voice-first knowledge management direction. See `docs/PRODUCT_DIRECTION.md` for the authoritative product scope.*

---

## 1. System Components & Responsibilities

```
┌────────────────────────────────────────────────────────────────┐
│                    Flutter Client (Android)                    │
│                                                                │
│  [RecordScreen]  [GraphScreen]  [RecordingsScreen]  [Settings] │
│         │              │               │                       │
│         ▼              ▼               ▼                       │
│     ┌───────────────────────────────────────────────────┐      │
│     │            NoteProvider (State / SSOT)            │      │
│     └───────────────────────────────────────────────────┘      │
│            │                                   │               │
│            ▼                                   ▼               │
│     ┌──────────────┐                  ┌──────────────────┐     │
│     │NoteRepository│                  │  BackendService  │     │
│     │(Local SQLite)│                  │  (HTTP Client)   │     │
│     └──────────────┘                  └──────────────────┘     │
└────────────────────────────────────────────────────────────────┘
                                              │ REST / Multipart HTTP
                                              ▼
┌────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend Service                    │
│                                                                │
│  [POST /api/captures/upload]  [GET /api/graph]                 │
│  [GET/PATCH/DELETE /api/entities]                              │
│  [GET/PATCH/DELETE /api/relationships]                         │
│  [GET /api/knowledge/search]  [GET /api/captures/{id}/audio]   │
│                                                                │
│  ┌──────────────────────────────────────────────────────┐      │
│  │                 Processing Pipeline                  │      │
│  │  STT (faster-whisper) → Entity/Relationship          │      │
│  │  Extraction → Entity Resolution → Graph Update       │      │
│  └──────────────────────────────────────────────────────┘      │
│                                 │                              │
│                                 ▼                              │
│                      ┌──────────────────┐                      │
│                      │  SQLite Storage  │                      │
│                      │(echo_backend.db) │                      │
│                      └──────────────────┘                      │
└────────────────────────────────────────────────────────────────┘
```

### Component Breakdown

1. **`AudioService` (`mobile/lib/services/audio_service.dart`)**:
   - Manages Android microphone permissions via `permission_handler`.
   - Records audio using the `record` package with AAC-LC compression at 64 kbps, 44.1 kHz, saved to local `.m4a` files.
   - Provides duration measurement and audio playback controls via `audioplayers`.

2. **`NoteProvider` (`mobile/lib/state/note_provider.dart`)**:
   - Single Source of Truth (SSOT) via `ChangeNotifier`.
   - Coordinates local persistence (`NoteRepository`), backend communication (`BackendService`), and state propagation to all dependent UI widgets.
   - Ensures Graph and Recordings views observe identical data.

3. **`NoteRepository` (`mobile/lib/data/repositories/note_repository.dart`)**:
   - CRUD operations against local SQLite (`echo_notes.db`).
   - Caches processing status and recording metadata for offline display.

4. **`BackendService` (`mobile/lib/services/backend_service.dart`)**:
   - HTTP communication with the FastAPI backend.
   - Manages idempotent multipart audio uploads, knowledge graph polling, and entity/relationship operations.

5. **`FastAPI Backend` (`server/app/main.py`)**:
   - Exposes REST endpoints for audio upload, knowledge graph retrieval, entity/relationship management, search, and evaluation exports.
   - Enforces ownership authorization on every user resource endpoint.

6. **`Processing Pipeline` (`server/app/pipeline.py` and `server/app/application/use_cases/`)**:
   - Decodes audio to 16 kHz mono PCM using `ffmpeg`.
   - Transcribes audio via faster-whisper (local) or Groq (hosted).
   - Extracts entities and relationships from the transcript using the configured LLM provider or the deterministic rule-based extractor.
   - Applies entity resolution: matches extracted entities against existing graph entities using embedding similarity.
   - Updates the knowledge graph incrementally: adds new entities, links resolved entities, flags duplicates, records contradictions, preserves tombstones and `user_edited` records.
   - Generates and stores embeddings for knowledge search.

> [!NOTE]
> Extraction and graph construction are distinct responsibilities. The extraction step produces candidate entities and relationships. The resolution and graph update step applies deterministic application logic — thresholds, tombstone checks, `user_edited` protection — to decide what enters the knowledge graph. This is not AI inference; it is data management.

---

## 2. Voice Capture & Processing Data Flow

> [!IMPORTANT]
> Voice recordings are the only ingestion channel for new knowledge in the MVP. Text note capture is not supported. Entity name/description editing and entity/relationship deletion are knowledge-management operations on extracted data. Transcripts are internal pipeline artifacts — they are not exposed to end users and must not be served through any user-facing endpoint.

```
1. User presses-and-holds mic (RecordScreen)
   └── AudioService.startRecording() saves to app-private .m4a

2. User releases mic
   └── NoteProvider.uploadRecording() queues upload
   └── Local record created (status: queued)

3. Upload — POST /api/captures/upload
   └── Idempotency key prevents duplicate records on retry
   └── Backend saves audio; inserts job row (status: upload)

4. Processing pipeline (async job worker)
   ├── transcribe    faster-whisper → transcript + segment timestamps
   ├── extract       LLM (groq) or rule_based → entities + relationships JSON
   │                 Validated against schema; one repair attempt on failure
   ├── resolve       Match extracted entities to existing graph entities
   │                 ≥ 0.90 similarity → auto-link; 0.75–0.90 → flag duplicate
   ├── save          Update knowledge graph (tombstones, user_edited respected)
   └── embed         fastembed BAAI/bge-small-en-v1.5, local

5. Processing complete (status: ready)
   └── Client polls job status and refreshes knowledge graph
```

---

## 3. Database Schemas

The backend uses a single SQLite database with WAL mode. Schema is managed by explicit migration scripts in `server/app/infrastructure/database/`.

Key tables (conceptual summary — authoritative schema is in migration files):

```sql
-- Recordings and their processing state
captures (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  idempotency_key TEXT UNIQUE,
  audio_path TEXT,
  duration_ms INTEGER,
  status TEXT,               -- queued | transcribing | extracting | saving | ready | failed
  failure_reason TEXT,
  failure_class TEXT,
  retry_count INTEGER,
  created_at TEXT
)

-- Async processing jobs with lease-based fault recovery
processing_jobs (
  id TEXT PRIMARY KEY,
  capture_id TEXT,
  status TEXT,
  stage_outputs TEXT,        -- JSON: stores transcript, extraction output per stage
  lease_expires_at TEXT,
  retry_count INTEGER,
  error_class TEXT
)

-- Transcripts (admin-only internal processing artifact; never served to end users)
transcripts (
  id TEXT PRIMARY KEY,
  capture_id TEXT,
  text TEXT,
  segments TEXT,             -- JSON: [{text, start, end}]
  user_edited INTEGER DEFAULT 0,
  created_at TEXT
)

-- Extracted and resolved knowledge graph entities
entities (
  id TEXT PRIMARY KEY,       -- uuid5(user_id, type, normalized_name)
  user_id TEXT,
  name TEXT,
  entity_type TEXT,          -- person | project | organization | place | concept | tool | idea
  description TEXT,
  confidence REAL,
  certainty_status TEXT,     -- certain | uncertain | conflicted | tombstoned
  user_edited INTEGER DEFAULT 0,
  provenance_capture_id TEXT,
  created_at TEXT,
  updated_at TEXT
)

-- Relationships between entities
relationships (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  source_entity_id TEXT,
  target_entity_id TEXT,
  relation_type TEXT,        -- Supports | Example of | Related to | Depends on | Constrained by | Contradicts
  confidence REAL,
  certainty_status TEXT,
  provenance_capture_id TEXT,
  created_at TEXT
)

-- Evidence: links entities/relationships back to transcript segments
entity_mentions (
  id TEXT PRIMARY KEY,
  entity_id TEXT,
  capture_id TEXT,
  transcript_segment TEXT,
  confidence REAL
)

relationship_evidence (
  id TEXT PRIMARY KEY,
  relationship_id TEXT,
  capture_id TEXT,
  transcript_segment TEXT
)

-- Embeddings for knowledge search
entity_embeddings (
  entity_id TEXT PRIMARY KEY,
  embedding BLOB,
  model_id TEXT
)
```

---

## 4. API Contracts & Authorization Boundaries

> [!IMPORTANT]
> **Authorization boundaries are enforced on the backend, not by hiding UI elements.** Three distinct access tiers apply:
> - **Public (unauthenticated):** Nothing. All endpoints require authentication.
> - **User-authenticated:** Recordings metadata, audio playback (own only), extracted entities and relationships (own only), knowledge search.
> - **Admin-authenticated:** All of the above, plus transcripts, pipeline job details, all users' data (with mandatory audit log entry).
>
> Transcripts must never appear in any user-tier API response, whether accidentally included in response bodies, error messages, or debug fields.

### Voice ingestion

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/captures/upload` | POST | User | Idempotent multipart audio upload; enqueues processing job |
| `/api/captures/{id}` | GET | User | Recording metadata and processing status (no transcript) |
| `/api/captures/{id}/audio` | GET | User (owner) | Audio playback — owner-only; returns 403 for any other user |
| `/api/captures/{id}` | DELETE | User (owner) | Deletes recording, transcript, and withdraws evidential support |

### Knowledge graph

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/graph` | GET | User | Full entity/relationship graph for the authenticated user |
| `/api/entities/{id}` | GET | User | Entity detail with provenance |
| `/api/entities/{id}` | PATCH | User (owner) | Edit entity name/description (sets `user_edited`) |
| `/api/entities/{id}` | DELETE | User (owner) | Soft-deletes entity (tombstone); removes orphaned relationships |
| `/api/relationships/{id}` | GET | User | Relationship detail |
| `/api/relationships/{id}` | DELETE | User (owner) | Remove a relationship |

### Search

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/knowledge/search` | GET | User | Hybrid entity/relationship search (embedding + lexical) — no transcript content in results |

### Admin (requires admin authentication + mandatory audit log)

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/admin/captures/{id}/transcript` | GET | Admin | Transcript text and segment timestamps for pipeline debugging |
| `/api/admin/captures/{id}/transcript` | PATCH | Admin | Correct transcript text; persisted with `user_edited = 1` |
| `/api/admin/captures/{id}` | GET | Admin | Full pipeline debug view: audio, transcript, extraction output, job stages |
| `/api/admin/ai-config` | GET / PUT | Admin | Read or update STT, extraction, and embedding provider configuration |
| `/api/admin/ai-config/test` | POST | Admin | Verify active configuration with a live test call |
| `/api/admin/users` | GET / PATCH | Admin | User management (lock, unlock, view) |

---

## 5. Knowledge Graph Layout

The mobile graph visualization uses `DeterministicGraphLayout` (`mobile/lib/ui/screens/graph/widgets/graph_layout_engine.dart`):

1. **Partitioning:** Identifies connected components using Breadth-First Search (BFS).
2. **Determinism:** Nodes are sorted by UUID so identical data always produces the same layout.
3. **Collision avoidance:** Singletons and pairs use explicit placement. Components ≥ 3 nodes use circular initialization followed by 40 iterations of force-directed relaxation.
4. **Level of detail:** Clusters collapse when zoomed out. Layout computation runs off the UI thread.
5. **State synchronization:** Both Graph and Recordings views subscribe to `NoteProvider`. Any edit (entity name change, deletion, new recording) immediately propagates without a manual refresh.

---

## 6. Architectural Principles

1. **Knowledge-first, not AI-first.** The product's value comes from capturing, organizing, connecting, and retrieving knowledge. The knowledge layer must be independently useful without an LLM reasoning engine.

2. **Voice as the primary ingestion interface.** All new knowledge originates from voice recordings in the MVP.

3. **Knowledge Layer independence.** Knowledge storage, graph traversal, and search work without a running LLM. Embedding-based search is a retrieval mechanism, not AI reasoning.

4. **Evidence-grounded knowledge.** Every extracted entity and relationship must trace to a source recording and transcript segment. Provenance is not optional.

5. **Separation of extraction and graph construction.** AI models extract candidate entities and relationships from transcripts. Deterministic application logic resolves, deduplicates, and updates the knowledge graph.

6. **Incremental updates.** New recordings extend the knowledge graph — they do not rebuild it from scratch.

7. **Data integrity and user trust.** Silent incorrect merges, duplicate graph updates, and loss of user corrections are defects, not acceptable tradeoffs.

8. **Model independence.** ASR and extraction models must be replaceable by swapping provider configuration without redesigning the Knowledge Layer.

9. **Pragmatic engineering.** SQLite with WAL is the persistence layer. Avoid unnecessary microservices, graph databases, and orchestration platforms unless measurements demonstrate a specific need.

10. **No premature expansion.** Do not introduce semantic reasoning, multi-modal ingestion, or conversational AI without a demonstrated MVP requirement.

---

## 7. Implementation & Gap Status (as of M3, 2026-10-30)

| Area | Implementation Status |
| :--- | :--- |
| Voice recording & upload | Implemented and verified |
| STT (faster-whisper) | Implemented and verified |
| Entity/relationship extraction | Implemented and verified |
| Entity resolution | Implemented and verified |
| Knowledge graph persistence | Implemented and verified |
| Knowledge search (hybrid) | Implemented and verified |
| My Recordings with status | Implemented and verified |
| Authentication & authorization | Implemented and verified |
| Evaluation opt-in & audio retention | Implemented and verified |
| Processing reliability (retry, lease recovery) | Implemented and verified |
| Admin transcript inspection & correction | **Gap — not yet implemented** |
| Admin dashboard (full) | **Gap — partially implemented** |
| Evaluation pipeline (WER, F1 measurement) | **Gap — extraction benchmark only** |
