# Echo — Voice-First Personal Knowledge Management System

Echo is a voice-first personal knowledge management system that transforms natural speech into structured, connected, and searchable knowledge. It automatically transcribes recordings, extracts entities and relationships, resolves references across recordings, and maintains a persistent knowledge graph with traceable evidence. Users can explore, search, verify, and manage their knowledge without relying on an AI reasoning or conversational assistant.

---

## 1. Product Purpose & Voice-First Workflow

Echo is **not** a long-form audio transcription tool, meeting assistant, generic note-taking application, or AI conversational assistant. Its core value is transforming unstructured voice recordings into structured, connected, and retrievable personal knowledge:

```
[ Voice Recording ]
             │
             ▼
   [ Audio Storage & Lifecycle Management ]
             │
             ▼
   [ Speech-to-Text (faster-whisper) ]
             │
             ▼
   [ Knowledge Extraction (Entities & Relationships) ]
             │
             ▼
   [ Entity Resolution & Knowledge Graph Update ]
             │
             ▼
   [ Knowledge Retrieval (Search, Browse, Explore) ]
```

### Approved Product Decisions

1. **Voice Capture:** Voice recordings are the primary and only ingestion channel for new knowledge in the MVP. Up to 2 minutes per recording (configurable via `ECHO_MAX_VOICE_SECONDS`).
2. **Raw Input Preservation:** The original audio file and transcript are preserved verbatim as internal artifacts; extracted entities, relationships, and user corrections to knowledge are editable but protected from AI overwrite.
3. **Capture-First Home UI:** Navigation features a centered Floating Action Bar (FAB) prioritizing instant voice recording, with secondary tabs for Graph and My Recordings.
4. **Knowledge Retrieval:** Entity and relationship search uses hybrid embedding similarity and lexical ranking. Knowledge retrieval does not require an LLM reasoning engine.
5. **Privacy & Consent-Gated Retention:** Audio retention on the server is gated strictly behind explicit, opt-in evaluation consent.
6. **No Offline Sync:** Offline synchronization is explicitly removed from product scope. The app operates with local persistence and online backend processing.
7. **Transcript Access:** Transcripts are internal processing artifacts. Access is restricted to admin-only endpoints (with mandatory audit logging). Transcript text is never served through any user-facing API response. Users interact with recordings (audio playback) and extracted knowledge (entities, relationships), not raw transcripts.

---

## 2. Implementation Status & Gap Analysis

Based on M3 implementation (2026-10-29, branch `mvp_v2_prd`). See `docs/M3_REPORT.md` for detailed evidence.

| Capability | Status | Notes |
| :--- | :--- | :--- |
| **Voice Recording & Upload** | **Implemented and verified** | Press-and-hold; up to 2 minutes; idempotent upload; serialized queue; local audio preserved until server confirms durable storage. |
| **STT Pipeline** | **Implemented and verified** | `faster-whisper` (tiny int8 CPU) via FFmpeg (16 kHz mono PCM). English-only; non-English fails with a typed error. |
| **Entity & Relationship Extraction** | **Implemented and verified** | Deterministic local rule-based extractor with Groq-hosted LLM option. Schema-constrained output, validation, one repair attempt. Idempotent (stable UUIDs). |
| **Entity Resolution** | **Implemented and verified** | Similarity ≥ 0.90 auto-links; 0.75–0.90 flagged as candidate duplicate; tombstones for deleted entities; `user_edited` protects corrections. |
| **Knowledge Graph** | **Implemented and verified** | Persistent entities and relationships with confidence, certainty, provenance. Contradictions kept and flagged. Server-side community detection layout. |
| **Knowledge Search** | **Implemented and verified** | Hybrid fastembed + lexical ranking over entities and relationships. 350 ms debounced; scoped to authenticated owner. |
| **My Recordings** | **Implemented and verified** | Date, duration, status, playback, delete, manual retry. Processing status polled from real backend job state. |
| **Authentication & Multi-user** | **Implemented and verified** | Email/password, Google Sign-In, email verification, password reset, revocable sessions, rate limiting, per-user data isolation. |
| **Consent & Privacy** | **Implemented and verified** | Provider consent screen; evaluation opt-in (default off); withdrawal purges retained audio. |
| **Processing Reliability** | **Implemented and verified** | Async job worker; lease-based fault recovery; up to 3 retries for recoverable errors; permanent errors fail cleanly with typed error class. |
| **Capture-First Centered FAB Navigation** | **Implemented (M3)** | Three-tab layout: Record (centre mic FAB), Graph, Recordings. Note: the M3 implementation included an "Ask AI" tab which is no longer part of the product scope; see `docs/M3_REPORT.md` for historical details. |

> [!NOTE]
> The Ask AI tab was implemented in M3 and is present in the codebase. It is **excluded from the current product scope**. See `docs/PRODUCT_DIRECTION.md` §5 and `docs/M3_REPORT.md` for details.


---

## 3. High-Level Repository Structure

```
.
├── README.md                          # Repository root entrypoint & status overview
├── docs/
│   ├── PRODUCT_DIRECTION.md           # Authoritative product scope & architectural principles
│   ├── ARCHITECTURE.md                # System components, data flows, schemas, contracts
│   ├── AI_PIPELINE.md                 # Audio constraints, STT, extraction, entity resolution
│   ├── ROADMAP.md                     # Feature status matrix and implementation milestones
│   ├── PRD_MVP.md                     # Product requirements (updated for current direction)
│   ├── M3_REPORT.md                   # M3 milestone report (historical; includes Ask AI implementation)
│   └── M1_AUDIT.md                    # M1 pre-auth audit report (historical)
├── mobile/                            # Flutter Android application
│   ├── lib/
│   │   ├── core/theme/                # Colors and typography
│   │   ├── data/                      # SQLite DatabaseHelper, Note model, NoteRepository
│   │   ├── services/                  # AudioService, BackendService, SettingsService
│   │   ├── state/                     # NoteProvider (SSOT ChangeNotifier)
│   │   └── ui/                        # AppShell, screens (Record, Graph, Recordings, Settings)
│   ├── test/                          # Unit, widget, migration, and security regression tests
│   └── pubspec.yaml                   # Flutter dependencies
└── server/                            # Python FastAPI backend & processing pipeline
    ├── app/
    │   ├── main.py                    # FastAPI app wiring
    │   ├── api/                       # Routes (client, admin), auth dependencies
    │   ├── application/               # Use cases and ports
    │   ├── adapters/                  # SQLite repositories, HTTP schemas
    │   ├── domain/                    # Entities and domain errors
    │   ├── infrastructure/            # Configuration
    │   ├── pipeline.py                # faster-whisper STT + entity/relationship extraction
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

- [Product Direction](docs/PRODUCT_DIRECTION.md): Canonical product definition, MVP scope, excluded features, architectural principles, and evaluation strategy. **Start here.**
- [Architecture Reference](docs/ARCHITECTURE.md): Component diagrams, data flows, knowledge pipeline stages, SQLite schemas, and API contracts.
- [AI Pipeline Reference](docs/AI_PIPELINE.md): Audio decoding, STT models, entity/relationship extraction, entity resolution, knowledge search, and extraction benchmark.
- [Product Requirements (PRD)](docs/PRD_MVP.md): Functional requirements, acceptance criteria, and confirmed product decisions.
- [Project Roadmap](docs/ROADMAP.md): Feature status matrix, remaining milestones, and explicit scope boundaries.
- [M3 Milestone Report](docs/M3_REPORT.md): Historical report of the M3 implementation (recording pipeline, knowledge graph, search, Ask AI). Preserved as a record; Ask AI section reflects implementation state, not current MVP scope.
- [M1 Audit Report](docs/M1_AUDIT.md): Historical audit of the pre-M2 codebase. Preserved for reference.
