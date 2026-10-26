# Echo — Personal Knowledge Capture & Recall (MVP)

Echo is an AI-powered, voice-first knowledge capture and recall mobile application for Android. It enables users to record short spoken thoughts ($\le 30$ seconds), transcribes them, extracts structured knowledge (core ideas, concepts, tags, and open research questions), infers relationships with existing thoughts, and maps them onto an interactive Knowledge Graph.

---

## 1. Product Purpose & Capture-First Workflow

Echo is **not** a long-form audio transcription tool, meeting assistant, or generic note-taking application. Its explicit focus is low-friction capture of fleeting, high-value ideas before they are forgotten:

```
[ Short Voice Thought (<=30s) ]
             │
             ▼
   [ Audio Normalization & Local Storage ]
             │
             ▼
   [ Speech-to-Text (faster-whisper) ]
             │
             ▼
   [ Structured Knowledge Extraction (Concepts, Tags, Ideas) ]
             │
             ▼
   [ Semantic Connection Inference (Relationships to Prior Notes) ]
             │
             ▼
   [ Persisted Knowledge Graph & Recall ]
```

### Approved Product Decisions

1. **Short Voice Capture:** Hard cap of 30 seconds for quick, low-friction recording.
2. **Raw Input Preservation:** The original audio file and transcript are preserved verbatim on the local device; AI-extracted structures (title, summary, concepts, open questions) remain editable.
3. **Capture-First Home UI:** Navigation is intended to feature a centered Floating Action Bar (FAB) prioritizing instant voice recording, flanked by secondary tabs.
4. **Mandatory Semantic Recall:** Natural language query matching via dense vector embeddings is a mandatory MVP requirement. Plain keyword matching (`LIKE`) is an interim fallback.
5. **Privacy & Consent-Gated Retention:** Audio retention on the server is gated strictly behind explicit, opt-in evaluation consent.
6. **No Offline Sync:** Offline synchronization is explicitly removed from product scope. The app operates with local SQLite persistence and online backend processing.

---

## 2. Implementation Status & Gap Analysis

Based on repository audit and verification testing:

| Capability | Status | Verified Evidence & Observed Behavior |
| :--- | :--- | :--- |
| **Short Voice Recording ($\le 30\text{s}$)** | **Implemented and verified** | Enforced by timer in `HomeScreen` (`home_screen.dart:48-63`) and `AudioService` (`audio_service.dart:45-53`). Verified with 30s auto-cutoff. |
| **STT Pipeline** | **Implemented but not verified end-to-end** | `server/app/pipeline.py` implements local `faster-whisper` (tiny int8 CPU) via FFmpeg audio decoding (16kHz mono PCM). OpenAI Whisper supported as fallback. Unit tests for server pipeline not present in CI; manual execution verified. |
| **Structured Knowledge Extraction** | **Implemented and verified** | Extracts `title`, `core_idea`, `details`, `concepts`, `tags`, and `open_questions`. Verified on device and in SQLite schemas. |
| **Deterministic Knowledge Graph** | **Implemented and verified** | Zero-overlap bounding box layout algorithm in `graph_layout_engine.dart`. `DeterministicGraphLayout` unit test passes (`flutter test test/graph_layout_test.dart`). |
| **List & Graph View Consistency** | **Implemented and verified** | Shared `NoteProvider` state (`note_provider.dart:249-264`) ensures create, edit, delete, and detail navigation immediately synchronize without app restart. |
| **Embedding-Based Semantic Recall** | **Not implemented (Critical Gap)** | Required by approved product decision. Actual implementation in `NoteRepository.searchNotes()` (`note_repository.dart:61-81`) is pure SQLite substring `LIKE '%query%'`. No vector embeddings, models, or vector stores exist in codebase. |
| **Evaluation Opt-in & Audio Retention** | **Partially implemented (Gap)** | Backend endpoints `/api/eval/record` and `/api/eval/export` require `consent_given=1`. However, the mobile client has **no UI toggle** for evaluation consent, and the server retains all uploads in `server/uploads/` indefinitely regardless of consent. |
| **Capture-First Centered FAB Navigation** | **Not implemented (Target Design)** | Current navigation (`AppShell`, `echo_bottom_nav.dart`) uses a standard 3-tab bottom bar (`Home`, `Recall`, `Library`) with an in-body capture hero card. Centered FAB is documented for subsequent implementation. |
| **Offline Synchronization** | **Removed from scope** | Background retry queues (`retryQueuedNotes()`) were removed. `NoteProvider.syncCaptureToBackend()` raises an immediate exception if backend is unreachable. |

---

## 3. High-Level Repository Structure

```
.
├── README.md                          # Repository root entrypoint & audit overview
├── docs/
│   ├── ARCHITECTURE.md                # System components, data flows, schemas, contracts
│   ├── AI_PIPELINE.md                 # Audio constraints, STT, extraction, evaluation logic
│   ├── ROADMAP.md                     # Evidence matrix, gap analysis, and milestones
│   └── PRD_MVP.md                     # Historical product requirements (superseded)
├── mobile/                            # Flutter Android application
│   ├── lib/
│   │   ├── core/theme/                # Colors and typography
│   │   ├── data/                      # SQLite DatabaseHelper, Note model, NoteRepository
│   │   ├── services/                  # AudioService, AIService, BackendService, SettingsService
│   │   ├── state/                     # NoteProvider (SSOT ChangeNotifier)
│   │   └── ui/                        # AppShell, screens (Home, Detail, Library, Recall, Settings)
│   ├── test/                          # Unit & widget tests (widget_test, graph_layout_test)
│   └── pubspec.yaml                   # Flutter dependencies
└── server/                            # Python FastAPI backend & AI pipeline
    ├── app/
    │   ├── main.py                    # REST API endpoints
    │   ├── db.py                      # SQLite helper (captures, items, relationships, eval)
    │   ├── pipeline.py                # faster-whisper STT + extraction + relation inference
    │   └── schemas.py                 # Pydantic schemas
    └── uploads/                       # Server audio storage (unpurged)
```

---

## 4. Prerequisites & Environment Configuration

### Prerequisites
- **Mobile:** Flutter SDK $\ge 3.13.7$, Android SDK (API 29+), connected physical device or emulator.
- **Backend:** Python 3.10+, `ffmpeg` installed and available on system `$PATH`.

### Required Environment Variables & Settings
- `OPENAI_API_KEY` (Optional): If set on host or entered in Settings screen, enables remote OpenAI Whisper STT and GPT-4o-mini knowledge extraction. If unset, system falls back to local `faster-whisper` and local linguistic extraction.
- `ECHO_DB_PATH` (Optional): Backend database path (defaults to `server/echo_backend.db`).

---

## 5. How to Run the Backend and Mobile App

### 1. Run the Backend Server
```bash
# From repository root:
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn faster-whisper numpy pydantic python-multipart
python3 -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

Verify backend health:
```bash
curl -s http://localhost:8000/api/health
# Response: {"status":"ok","service":"Echo Knowledge Backend","pipeline_version":"v1.2-echo-real"}
```

### 2. Forward ADB Port for Android
When running on a physical Android phone over USB:
```bash
adb reverse tcp:8000 tcp:8000
```

### 3. Run the Flutter Mobile App
```bash
cd mobile
flutter pub get
flutter run
```

---

## 6. How to Run Existing Tests

Execute Flutter test suite and static analysis:
```bash
cd mobile
flutter test
# Output:
# 00:00 +2: All tests passed! (widget_test.dart and graph_layout_test.dart)

flutter analyze
# Output:
# No issues found!
```

---

## 7. Documentation Index

- [Architecture Reference](docs/ARCHITECTURE.md): Component diagrams, data contracts, SQLite schemas, and layout mechanics.
- [AI Pipeline & Evaluation](docs/AI_PIPELINE.md): Audio decoding, STT models, extraction prompts, and evaluation dataset specifications.
- [Project Roadmap & Gap Analysis](docs/ROADMAP.md): Evidence matrix, required implementation milestones, and non-goals.
