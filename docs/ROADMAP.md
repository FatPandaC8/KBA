# Project Roadmap & Gap Analysis

This document provides an evidence-based audit of Echo's MVP, evaluates gaps against approved product decisions, and establishes prioritized milestones.

---

## 1. Feature Status Matrix

| Subsystem / Capability | Classification | Evidence & Source Files |
| :--- | :--- | :--- |
| **Short Voice Capture ($\le 30\text{s}$)** | **Implemented and verified** | Enforced by timer in `HomeScreen` (`home_screen.dart:48-63`) and `AudioService` (`audio_service.dart:45-53`). Verified live on Android with 30s auto-cutoff. |
| **Backend Audio Decoding & STT** | **Implemented but not verified end-to-end** | FFmpeg decoding and `faster-whisper` (tiny int8 CPU) in `server/app/pipeline.py`. Backend `/api/health` returns version `v1.2-echo-real`. Verified via local test audio and curl; no automated CI end-to-end integration test. |
| **Structured Knowledge Extraction** | **Implemented and verified** | In `server/app/pipeline.py`. Correctly extracts title, core idea, details, concepts, tags, and open questions into SQLite `knowledge_items`. |
| **Knowledge Graph Deterministic Layout** | **Implemented and verified** | In `graph_layout_engine.dart`. `test/graph_layout_test.dart` passes with zero node bounding-box collisions. Pan, zoom, Bézier curves, and neighbor focus verified on device. |
| **List & Graph View Consistency** | **Implemented and verified** | `NoteProvider` is the Single Source of Truth (`note_provider.dart:249-264`). Changes (create, edit, delete) immediately synchronize across List and Graph views without restart. |
| **Embedding-Based Semantic Recall** | **Not implemented (Critical Gap)** | Required by approved product decision. Actual search in `NoteRepository.searchNotes()` (`note_repository.dart:61-81`) is pure SQLite substring `LIKE '%query%'`. No vector embeddings, models, or vector stores exist in codebase. |
| **Evaluation Opt-In & Retention Policy** | **Partially implemented (Gap)** | Backend endpoints `/api/eval/record` and `/api/eval/export` enforce `consent_given=1`. However, `SettingsScreen` lacks an evaluation opt-in toggle, and `server/uploads/` permanently stores uploaded audio without consent-gated purging. |
| **Capture-First Centered FAB Navigation** | **Not implemented (Target Design)** | Approved product decision requires a centered Floating Action Bar with capture in the center and secondary tabs on either side. Current UI uses standard 3-tab bottom bar (`echo_bottom_nav.dart`). |
| **Offline Synchronization** | **Removed from scope** | Background retry queue (`retryQueuedNotes()`) was removed. Local SQLite persistence remains intact; online processing fails fast with clean user notification if unreachable. |

---

## 2. Prioritized Implementation Milestones

### Milestone 1: Embedding-Based Semantic Recall (Highest Priority)
- **Problem:** Currently, natural language search in the Recall screen falls back to substring `LIKE` matching, failing on semantic paraphrases, conceptual synonyms, and exploratory queries.
- **Scope of Work:**
  1. Add an embedding generation step (either local lightweight ONNX/TFLite model or remote OpenAI `text-embedding-3-small`).
  2. Add vector storage (e.g. SQLite vector extension, sqlite-vec, or serialized float array with in-memory cosine similarity ranking).
  3. Update `NoteRepository.searchNotes()` to rank results by vector similarity distance.
  4. Display match confidence/similarity scores in `RecallScreen`.

### Milestone 2: Evaluation Opt-in & Server Audio Purging
- **Problem:** User evaluation consent cannot currently be toggled from the mobile app, and the server retains all raw audio files indefinitely in `server/uploads/`.
- **Scope of Work:**
  1. Add `Evaluation & Model Quality` switch in `SettingsScreen` (defaulting to **OFF**).
  2. Persist consent in `SettingsService` via `SharedPreferences`.
  3. Send `consent_given` flag in multipart upload payload to `POST /api/captures/upload`.
  4. Implement an automatic deletion hook in `server/app/main.py` that purges `server/uploads/{capture_id}.m4a` immediately after transcription if `consent_given` is false.

### Milestone 3: Capture-First Centered Floating Action Bar
- **Problem:** The current bottom navigation is a standard 3-tab row (`Home`, `Recall`, `Library`) where voice capture is confined to an in-body card on the Home screen.
- **Scope of Work:**
  1. Re-architect `AppShell` and `EchoBottomNav` to feature a centered, elevated microphone FAB.
  2. Position `Recall` and `Library` tabs on either side of the center action.
  3. Ensure tapping the center action initiates short voice capture from any tab in the application.

---

## 3. Explicit Scope Boundaries & Non-Goals

| Feature | Scope Decision | Rationale |
| :--- | :--- | :--- |
| **Offline Sync Queues & Auto-Retries** | **Explicitly Out of Scope (Removed)** | Avoids complex distributed reconciliation logic (CRDTs, vector clocks) in an MVP. Mobile app ensures local persistence, while AI processing requires online server connection. |
| **Long-Form Transcription** | **Explicitly Out of Scope** | Echo is strictly designed for quick, transient thought capture ($\le 30\text{s}$). Meetings and lecture transcription are intentionally unsupported. |
| **Multi-User Collaboration & Sync** | **Out of Scope** | Single-user personal knowledge capture and recall. |
