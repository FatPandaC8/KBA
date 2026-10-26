# Architecture Reference

This document describes the technical architecture, data flows, database schemas, API contracts, and component responsibilities for the Echo MVP.

---

## 1. System Components & Responsibilities

```
┌────────────────────────────────────────────────────────┐
│                   Flutter Client (Mobile)              │
│                                                        │
│  [HomeScreen]   [LibraryScreen]  [RecallScreen]  [Detail]│
│        │               │                │           │  │
│        ▼               ▼                ▼           ▼  │
│     ┌──────────────────────────────────────────────┐   │
│     │          NoteProvider (State / SSOT)         │   │
│     └──────────────────────────────────────────────┘   │
│            │                                  │        │
│            ▼                                  ▼        │
│     ┌──────────────┐                 ┌──────────────┐  │
│     │NoteRepository│                 │BackendService│  │
│     │ (Local SQLite)                 │ (HTTP Client)│  │
│     └──────────────┘                 └──────────────┘  │
└───────────────────────────────────────────────┬────────┘
                                                │ REST / Multipart HTTP
                                                ▼
┌────────────────────────────────────────────────────────┐
│                 FastAPI Backend Service                │
│                                                        │
│  [POST /api/captures/upload]   [GET/POST /api/knowledge]│
│  [GET /api/graph]              [PATCH/DELETE /api/rel]  │
│  [POST /api/eval/record]       [GET /api/eval/export]  │
│                                                        │
│     ┌──────────────────────────────────────────────┐   │
│     │          ExtractionPipeline (STT + NLP)      │   │
│     │ (faster-whisper CPU / OpenAI fallback)       │   │
│     └──────────────────────────────────────────────┘   │
│                               │                        │
│                               ▼                        │
│                     ┌──────────────────┐               │
│                     │  SQLite Storage  │               │
│                     │(echo_backend.db) │               │
│                     └──────────────────┘               │
└────────────────────────────────────────────────────────┘
```

### Component Breakdown

1. **`AudioService` (`mobile/lib/services/audio_service.dart`)**:
   - Manages Android microphone permissions via `permission_handler`.
   - Records audio using `record` package with AAC-LC compression at 64 kbps, 44.1 kHz, saved to local `.m4a` files.
   - Provides duration measurement and playback controls via `audioplayers`.

2. **`NoteProvider` (`mobile/lib/state/note_provider.dart`)**:
   - Acts as the Single Source of Truth (SSOT) via `ChangeNotifier`.
   - Coordinates local persistence (`NoteRepository`), backend replication (`BackendService`), and direct client AI fallback (`AIService`).
   - Ensures List and Graph views observe identical data collections.

3. **`NoteRepository` (`mobile/lib/data/repositories/note_repository.dart`)**:
   - Executes CRUD queries against local SQLite database (`echo_notes.db`).
   - Provides keyword substring search (`LIKE '%query%'`) across note fields.

4. **`BackendService` (`mobile/lib/services/backend_service.dart`)**:
   - Handles HTTP communication with the Python FastAPI backend.
   - Manages multipart upload of recordings, knowledge item synchronization, and graph relationship querying.

5. **`FastAPI Backend` (`server/app/main.py`)**:
   - Exposes REST endpoints for audio upload, knowledge item CRUD, graph retrieval, relationship status toggling, and evaluation exports.

6. **`ExtractionPipeline` (`server/app/pipeline.py`)**:
   - Decodes audio formats to 16kHz mono PCM using `ffmpeg`.
   - Transcribes audio via `faster-whisper` (tiny int8 CPU) or OpenAI Whisper.
   - Extracts structured knowledge attributes (title, core idea, details, concepts, tags, open questions).
   - Derives candidate relationships to existing items based on shared concepts, tags, and keywords.

---

## 2. End-to-End Data Flow

### A. Spoken Idea Capture & Ingestion
```
1. User taps mic (HomeScreen)
   └── AudioService.startRecording() -> saves to mobile/recordings/capture_<timestamp>.m4a
   └── Countdown timer enforces <=30s duration cap

2. Recording finishes (HomeScreen)
   └── NoteProvider.createAudioNote() writes Note (status: queued) to local SQLite
   └── NoteProvider.syncCaptureToBackend() initiates async upload

3. Upload Request (POST /api/captures/upload)
   └── Backend saves audio file to server/uploads/{capture_id}.m4a
   └── Backend inserts capture record (status: received) into captures table

4. Server Processing (ExtractionPipeline)
   └── decode_audio_ffmpeg() converts M4A into normalized 16kHz float32 array
   └── transcribe() runs faster-whisper (tiny int8 CPU) with VAD filter
   └── extract_knowledge() generates title, core idea, details, concepts, tags, questions
   └── connect_knowledge() matches against existing knowledge items in echo_backend.db

5. Storage & Client Sync
   └── Backend writes KnowledgeItem and Relationships to echo_backend.db
   └── Response returns CaptureUploadResponse
   └── NoteProvider updates local Note with transcript, summary, concepts (status: ready)
   └── KnowledgeGraphWidget updates reactively via ListenableBuilder
```

### B. Direct Text Note Capture
```
1. User types in TextCaptureDialog
2. NoteProvider.createTextNote() persists Note locally (status: ready or pending)
3. NoteProvider invokes _syncNoteToBackend() to replicate knowledge record
4. Backend executes connect_knowledge() and stores derived graph edges
```

---

## 3. Database Schemas

### Mobile Client: `echo_notes.db` (SQLite v2)

Defined in [`mobile/lib/data/datasources/database_helper.dart`](../mobile/lib/data/datasources/database_helper.dart):

```sql
CREATE TABLE notes (
  id TEXT PRIMARY KEY,
  audioPath TEXT,
  audioDurationMs INTEGER,
  originalContent TEXT NOT NULL,
  transcript TEXT,
  title TEXT NOT NULL,
  summary TEXT,
  keyFacts TEXT,          -- JSON encoded List<String>
  openQuestions TEXT,     -- JSON encoded List<String>
  tags TEXT,              -- JSON encoded List<String>
  status TEXT NOT NULL,   -- 'rawOnly', 'queued', 'uploading', 'ready', 'failed'
  failureReason TEXT,
  createdAt TEXT NOT NULL,
  updatedAt TEXT NOT NULL
);

CREATE INDEX idx_notes_title ON notes(title);
CREATE INDEX idx_notes_created ON notes(createdAt);
```

### Backend Service: `echo_backend.db` (SQLite)

Defined in [`server/app/db.py`](../server/app/db.py):

```sql
CREATE TABLE captures (
  id TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE,
  audio_path TEXT,
  duration_ms INTEGER,
  status TEXT,
  created_at TEXT
);

CREATE TABLE knowledge_items (
  id TEXT PRIMARY KEY,
  capture_id TEXT UNIQUE,
  title TEXT,
  core_idea TEXT,
  details TEXT DEFAULT '',
  transcript TEXT,
  concepts TEXT,             -- JSON List<str>
  tags TEXT,                 -- JSON List<str>
  open_questions TEXT,       -- JSON List<str>
  candidate_relations TEXT,  -- JSON List<str>
  provenance TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE relationships (
  id TEXT PRIMARY KEY,
  from_id TEXT,
  to_id TEXT,
  relation_type TEXT,        -- 'Supports', 'Related to'
  status TEXT,               -- 'suggested', 'confirmed'
  created_at TEXT,
  UNIQUE(from_id, to_id, relation_type)
);

CREATE TABLE model_eval_records (
  id TEXT PRIMARY KEY,
  capture_id TEXT,
  transcript TEXT,
  structured_json TEXT,
  user_corrected INTEGER DEFAULT 0,
  consent_given INTEGER DEFAULT 0,
  pipeline_version TEXT,
  created_at TEXT
);
```

---

## 4. API Contracts

### `POST /api/captures/upload`
- **Request:** `multipart/form-data`
  - `file`: Audio binary (`.m4a`)
  - `capture_id`: UUID
  - `idempotency_key`: UUID
  - `duration_ms`: Integer
- **Response:** `200 OK`
  ```json
  {
    "capture_id": "string",
    "status": "ready",
    "knowledge_item": {
      "id": "string",
      "capture_id": "string",
      "title": "string",
      "core_idea": "string",
      "details": "string",
      "transcript": "string",
      "concepts": ["string"],
      "tags": ["string"],
      "open_questions": ["string"],
      "candidate_relations": ["string"],
      "provenance": "string"
    },
    "relationships": [
      {
        "id": "string",
        "from_id": "string",
        "to_id": "string",
        "relation_type": "string",
        "status": "suggested"
      }
    ]
  }
  ```

### `GET /api/knowledge` & `POST /api/knowledge`
- `GET /api/knowledge?q={query}`: Substring search across `title`, `core_idea`, `transcript`, `concepts`, and `tags`.
- `POST /api/knowledge`: Ingests or updates a `KnowledgeItem` JSON payload, connects to existing items, and stores candidate relationships.

### `DELETE /api/knowledge/{item_id}`
- Deletes knowledge item and cascades deletion to associated edges in `relationships`.

### `GET /api/graph`
- Returns nodes and edges.
- *Known API Limitation:* In `db.py:221-230`, backend returns modulo coordinates from a static 8-point preset array (`coord_presets`). The mobile client ignores these coordinates and computes layout deterministically on-device via `DeterministicGraphLayout`.

### `PATCH /api/relationships/{rel_id}` & `DELETE /api/relationships/{rel_id}`
- Updates relationship status (`suggested` -> `confirmed`) or deletes the edge.

### `POST /api/eval/record` & `GET /api/eval/export`
- `/api/eval/record`: Inserts evaluation log only if form parameter `consent_given=True`.
- `/api/eval/export`: Returns JSON array of evaluation records filtered by `consent_given = 1`.

---

## 5. Knowledge Graph Layout & Synchronization

The mobile visualization employs [`DeterministicGraphLayout`](../mobile/lib/ui/screens/library/widgets/graph_layout_engine.dart):

1. **Partitioning:** Identifies connected components using Breadth-First Search (BFS).
2. **Determinism:** Nodes are sorted by UUID to ensure identical spatial configurations across re-renders.
3. **Collision Avoidance:**
   - Singletons and node pairs use explicit coordinate placements.
   - Components $\ge 3$ nodes use circular initialization followed by 40 iterations of force-directed relaxation (Hooke's spring attraction and inverse square repulsion).
   - Zero node bounding-box overlaps verified by `test/graph_layout_test.dart`.
4. **Synchronization with List View:**
   - Both views subscribe directly to `NoteProvider.notes`.
   - Editing or deleting a note in the List view instantly recalculates graph nodes and visible edges without manual refresh or app restart.

---

## 6. Current Implementation vs. Approved Decisions

| Area | Current Architecture | Approved Product Decision | Gap Status |
| :--- | :--- | :--- | :--- |
| **Recall / Search** | SQLite `LIKE '%query%'` substring matching in `NoteRepository.dart:73-79` | Dense vector embedding similarity retrieval across captures | **Critical Gap (Unimplemented)** |
| **Evaluation Opt-in** | Backend accepts `consent_given` flag; mobile client has no toggle in `SettingsScreen` | Separate explicit opt-in toggle, default OFF | **Gap (Partially Implemented)** |
| **Server Audio Retention** | Audio written to `server/uploads/` is retained indefinitely | Retain audio on server only when evaluation consent is granted; purge otherwise | **Gap (Partially Implemented)** |
| **Home Navigation** | Standard 3-tab bottom bar (`Home`, `Recall`, `Library`) in `echo_bottom_nav.dart` | Centered Floating Action Bar for capture, flanked by secondary tabs | **Target Design (Unimplemented)** |
| **Offline Sync** | Background retry queues removed; fails fast on network disconnect | Offline sync removed from scope | **Aligned** |
