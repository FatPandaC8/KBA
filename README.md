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
| **STT Pipeline** | **Implemented and verified on device** | `server/app/pipeline.py` implements local `faster-whisper` (tiny int8 CPU) via FFmpeg audio decoding (16kHz mono PCM). OpenAI Whisper remains an optional server-side fallback. Verified end-to-end on a physical Android device: recorded audio uploaded with `POST /api/captures/upload` → `200`, transcript and knowledge item created with local provenance. The pipeline still has no automated server test because it requires model weights. |
| **Structured Knowledge Extraction** | **Implemented and verified** | Extracts `title`, `core_idea`, `details`, `concepts`, `tags`, and `open_questions`. Verified on device and in SQLite schemas. |
| **Deterministic Knowledge Graph** | **Implemented and verified** | Zero-overlap bounding box layout algorithm in `graph_layout_engine.dart`. `DeterministicGraphLayout` unit test passes (`flutter test test/graph_layout_test.dart`). |
| **List & Graph View Consistency** | **Implemented and verified** | Shared `NoteProvider` state (`note_provider.dart:249-264`) ensures create, edit, delete, and detail navigation immediately synchronize without app restart. |
| **Embedding-Based Semantic Recall** | **Implemented; keyword fallback when offline** | Server exposes `/api/knowledge/semantic-search` backed by stored embeddings and a backfill use case. `NoteProvider.search()` calls it first and falls back to local SQLite `LIKE` search when the backend is unreachable or returns no semantic hits. Verified on device against a live backend. |
| **Evaluation Opt-in & Audio Retention** | **Implemented and verified** | Settings exposes an opt-in evaluation toggle that defaults to off. Uploads are deleted immediately unless consent is given, and withdrawing consent purges every retained capture audio file plus all evaluation records server-side. Verified on device and covered by server regression tests. |
| **Capture-First Centered FAB Navigation** | **Not implemented (Target Design)** | Current navigation (`AppShell`, `echo_bottom_nav.dart`) uses a standard 3-tab bottom bar (`Home`, `Recall`, `Library`) with an in-body capture hero card. Centered FAB is documented for subsequent implementation. |
| **Retry & Restart Recovery** | **Implemented and verified** | Failed processing is retried automatically a bounded number of times (3 attempts), surfaces an explicit failure reason, and resumes pending work after an app restart. Verified on device, including the capped-attempt behaviour. Client tokens persist across reinstalls. This is bounded retry, not offline sync: the backend must be reachable for processing. |

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
│   ├── test/                          # Unit, widget, migration, and security regression tests
│   └── pubspec.yaml                   # Flutter dependencies
└── server/                            # Python FastAPI backend & AI pipeline
    ├── app/
    │   ├── main.py                    # FastAPI app wiring
    │   ├── api/                       # Routes (client, admin), auth dependencies
    │   ├── application/               # Use cases and ports
    │   ├── adapters/                  # SQLite repositories, HTTP schemas
    │   ├── domain/                    # Entities and domain errors
    │   ├── infrastructure/            # Configuration
    │   ├── pipeline.py                # faster-whisper STT + extraction + relation inference
    │   └── static/                    # Admin dashboard
    └── uploads/                       # Consent-gated audio retention (purged on withdrawal)
```

---

## 4. Prerequisites & Environment Configuration

### Prerequisites
- **Mobile:** Flutter SDK $\ge 3.13.7$, Android SDK (API 29+), connected physical device or emulator.
- **Backend:** Python 3.10+, `ffmpeg` installed and available on system `$PATH`.

### Required Environment Variables & Settings
- `ECHO_CLIENT_TOKEN` (**Required**): Shared token used by the Android client. If it is empty, protected client endpoints fail closed with HTTP 503.
- `ECHO_ADMIN_TOKEN` (**Required for the admin dashboard**): Admin token. There is no default. If it is empty, admin endpoints fail closed with HTTP 503.
- `ECHO_CORS_ORIGINS` (Optional): Comma-separated browser origins. CORS is disabled unless this is set; the Android client does not need CORS.
- `ECHO_DB_PATH` (Optional): Backend database path (defaults to `server/echo_backend.db`).
- `ECHO_UPLOAD_DIR` (Optional): Audio upload directory (defaults to `server/uploads`).
- `ECHO_MAX_UPLOAD_BYTES` (Optional): Upload size limit (defaults to 25 MiB).
- `OPENAI_API_KEY` (Optional): If set on the backend host, enables remote OpenAI Whisper STT and GPT-4o-mini knowledge extraction. If unset, the backend falls back to local `faster-whisper` and local linguistic extraction.

### Platform Scope

Android is the only actively supported build and verification target in this phase. The `ios/` Flutter scaffold is intentionally preserved for future work but is not built, tested, or released here. Debug Android builds allow cleartext HTTP for local development; release builds keep Android's secure default and require HTTPS.

### Android signing

Debug builds are signed with the Flutter debug key and are **not** production artifacts. Release builds use a release keystore only when `mobile/android/key.properties` and the referenced keystore exist. If they are absent, release builds fall back to the debug key and must not be published. The application ID `dev.echo.notes.dev` is provisional until the owner provides a permanent publishing identity.

---

## 5. How to Run the Backend and Mobile App

### 1. Run the Backend Server
```bash
# From repository root:
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn faster-whisper numpy pydantic python-multipart
export ECHO_CLIENT_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export ECHO_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

Store the generated client token for entry in the app's Settings screen. Do not commit tokens or paste them into logs.

Verify backend health:
```bash
curl -s http://localhost:8000/api/health
# Response: {"status":"ok","service":"Echo Knowledge Backend","pipeline_version":"v1.2-echo-real"}
```

Protected endpoints require `Authorization: Bearer <ECHO_CLIENT_TOKEN>` (or `X-Client-Token`).

### 2. Forward ADB Port for Android
When running on a physical Android phone over USB:
```bash
adb reverse tcp:8000 tcp:8000
```
The app's default server URL is `http://127.0.0.1:8000`, which only works while `adb reverse` is active. This is a development-only workaround, not a production networking solution. For a LAN server, enter a reachable `http://<host>:<port>` URL in Settings; use HTTPS for release builds. `adb reverse` is cleared when the device reconnects, so re-run it as needed.

### 3. Run the Flutter Mobile App
```bash
cd mobile
flutter pub get
flutter run -d <android-device-id>
```
After launch, open Settings, enter the backend URL and the client token, then use **Test connection**.

---

## 6. How to Run Existing Tests

Execute Flutter test suite and static analysis:
```bash
cd mobile
flutter test
flutter analyze
```

Run backend tests against a temporary database and upload directory (never the production database). The root `conftest.py` forces isolated test paths and non-production tokens, so a plain invocation is safe:
```bash
python -m pytest server/tests -q
```
The explicit environment variables below still work if you prefer to choose the temporary location:
```bash
ECHO_DB_PATH=/tmp/echo-test/echo.db \
ECHO_UPLOAD_DIR=/tmp/echo-test/uploads \
ECHO_ADMIN_TOKEN=test-admin-token \
ECHO_CLIENT_TOKEN=test-client-token \
python -m pytest server/tests -q
```

Build the debug APK for Android:
```bash
cd mobile
flutter build apk --debug
```

---

## 7. Documentation Index 

- [Architecture Reference](docs/ARCHITECTURE.md): Component diagrams, data contracts, SQLite schemas, and layout mechanics.
- [AI Pipeline & Evaluation](docs/AI_PIPELINE.md): Audio decoding, STT models, extraction prompts, and evaluation dataset specifications.
- [Project Roadmap & Gap Analysis](docs/ROADMAP.md): Evidence matrix, required implementation milestones, and non-goals.
