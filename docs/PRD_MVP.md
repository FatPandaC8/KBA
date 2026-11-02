# Echo MVP — PRD (Voice-First Knowledge Management)

*Original product requirements (2026-10-30), with implementation-contract updates noted below as of 2026-11-02. See `docs/PRODUCT_DIRECTION.md` and `docs/architecture/persistence.md` for current architecture.*

> [!NOTE]
> This document has been updated to align with the voice-first personal knowledge management direction. Conversational AI ("Ask AI") is removed from scope. Transcripts are internal processing artifacts accessible to admins only; end users interact with recordings and extracted knowledge (entities and relationships), not raw transcripts.

> **Current pipeline decision (2026-11-02):** the earlier upload/job/worker and retry requirements below are superseded. The app calls `POST /api/stt` then `POST /api/text-kb`; both execute synchronously. The server has no job table, queue, worker, status polling or capture retry/backoff. The client retries explicitly. STT is stateless and persists no audio/transcript; Text-KB accepts a client UUID `capture_id` and commits capture + knowledge + graph in one Postgres UoW. See `CHANGELOG.md` for the complete contract changes. The client keeps audio locally.

## 1. Overview

Echo is an Android-first Flutter app (with a viable path to iOS) that turns a user's spoken recordings into a persistent knowledge graph of entities and relationships. Users explore the graph, search it by entity name, type, and keyword, verify extracted knowledge, correct it when needed, and navigate connections across recordings.

**Navigation: two workspaces — Record and Graph.** Record is the voice-ingestion surface. Search lives inside Graph and operates over entities and relationships; graph state is preserved when switching workspaces.

Echo is a personal knowledge management tool. It is not a conversational AI assistant. The knowledge layer — storage, graph traversal, search, and retrieval — operates independently of any LLM reasoning engine.

## 2. Confirmed decisions

| # | Topic | Decision |
| --- | --- | --- |
| D1 | Reprocessing | There are no persisted stages to resume. Text-KB is atomic and idempotent by `capture_id`; deleted entities stay tombstoned and user edits are protected from overwrite. |
| D2 | Free providers that may train on data | Allowed, but only with clear notice and explicit user consent. |
| D3 | Mic denied / offline | Explain microphone denial and keep the user in control. Offline request failures are visible; locally recorded audio remains available for a manual retry. |
| D4 | Admin authentication | Separate admin access using the existing server admin token mechanism. No extra admin management UI or 2FA in the MVP. |
| D5 | Voice records | Users can play back their own audio. Transcripts are internal processing artifacts; access is restricted to admins. |
| D6 | Recording | Press-and-hold only; release to send. No tap-to-toggle mode. |
| D7 | Auth | Email verification and password reset via a free email-sending service. |
| D8 | Scale | 100–1,000 users, up to 2,000 nodes per user. |
| D9 | Market | Unconstrained. Do only what Google Play requires everywhere. |
| D10 | Benchmarks | Concrete release thresholds (section 7). |
| D11 | Quota | No per-user usage limits. AI failures are reported clearly to users. |
| D12 | Search | Inside the Graph tab. Tapping a result focuses the node/edge on the canvas and opens its detail panel. |
| D13 | Ingestion | Voice recordings are the only source of new knowledge in the MVP. Entity name/description editing and entity/relationship deletion are knowledge management operations, not new ingestion channels. |

## 3. Invariant constraints

- **C1.** No paid APIs and no paid fallback. On quota exhaustion, report the error and allow retry.
- **C2.** Authorization is enforced on the backend. Every user resource gets an ownership check.
- **C3.** Transcripts are admin-only. Transcript text is an internal processing artifact. It must not be served to end users in any API response — not to the recording owner, not to other users, not to unauthenticated callers. Transcript access is restricted to authenticated admin endpoints only.
- **C4.** No AI training pipeline in the MVP (section 10).
- **C5.** Never claim a feature, test, build or deployment succeeded without actual verification.
- **C6.** No default admin account or hardcoded admin token. Secrets stay out of source code and out of the client.

## 4. Functional requirements

Priority: **P0** required for release, **P1** should have, **P2** post-MVP. AC = acceptance criterion.

### 4.1 Authentication (AUTH)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| AUTH-01 | P0 | Email/password sign-up and login; passwords hashed with argon2id or bcrypt. | No plaintext passwords; failed login returns a generic error that does not reveal whether the email exists. |
| AUTH-02 | P0 | Google Sign-In with server-side token validation. | Forged or expired tokens are rejected. |
| AUTH-03 | P0 | Email verification before full use. | An unverified account cannot create records. |
| AUTH-04 | P0 | Password reset: single-use, short-lived token; resetting revokes all existing sessions. | A reused token is rejected; old sessions stop working. |
| AUTH-05 | P0 | Expiring, revocable sessions; logout. | After logout or account deletion, old tokens return 401. |
| AUTH-06 | P0 | Abuse rate limits on login, sign-up and email sending (per user and per IP). This is security, not a usage quota. | Exceeding the limit returns 429. |
| AUTH-07 | P0 | Linking a password account and a Google account with the same email happens only after ownership is verified. | An unverified email cannot be used to take over an account. |

### 4.2 Consent and app gating (GATE)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| GATE-01 | P0 | Consent screen listing each AI provider, what data it receives (audio, knowledge text) and that it may use data for training. Store consent version and timestamp. | No consent means no recording. Changing the provider list re-prompts. |
| GATE-02 | P0 | Declining or withdrawing consent means the app cannot be used (STT is mandatory); say so plainly. | Withdrawal returns the user to the blocking screen; existing data is deleted only if the user deletes the account. |
| GATE-03 | P0 | Mic denied or revoked: block the whole app, explain why, link to system settings. | The blocking screen always offers logout, account deletion and policy pages. |
| GATE-04 | P0 | Network requests require connectivity. Recording may be retained locally when a request fails; the user explicitly retries. No background upload queue or automatic resume. | Offline failure is visible; the local audio remains available for manual retry. |

### 4.3 Recording and synchronous processing (REC)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| REC-01 | P0 | Press and hold to record; release starts the synchronous STT → Text-KB request flow without a confirmation screen. | Early release is processed normally. |
| REC-02 | P0 | Show recording state, elapsed and remaining time. Maximum 2 minutes; auto-stop and submit at the limit. | A 120-second recording ends and submits without interaction. |
| REC-03 | P0 | Recordings under 1 second are discarded with a gentle notice. No cancel gesture. **\[Default\]** | An accidental tap creates no record. |
| REC-04 | P0 | A new recording may begin while another capture request is in flight; each capture has its own client UUID. | Each request retains its own capture ID and local audio. |
| REC-05 | P0 | Handle calls, backgrounding, network loss, empty/invalid audio. Keep local audio for a user-triggered retry when STT fails. | Failed STT leaves the audio locally available; no automatic upload retry. |
| REC-06 | P0 | Audio stays in the app-private directory; the server does not persist recording audio. | Playback and STT retry use the local file. |
| REC-07 | P0 | Text-KB is idempotent via the client-generated `capture_id`; retries never create duplicate captures or graph rows. | Repeating Text-KB with the same user and capture ID returns the existing result. |

### 4.4 Processing pipeline (PRC)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| PRC-01 | P0 | Two calls run in order: stateless `POST /api/stt`, followed by synchronous `POST /api/text-kb`; app shows progress and errors. | UI reflects the in-flight request and final response; no status polling. |
| PRC-02 | P0 | Text-KB writes capture, knowledge item and graph changes in one Postgres UoW; no job table or worker. | Injected mid-ingest failure leaves no partial graph/capture data. |
| PRC-03 | P0 | Failures/slowness return to the client; user taps Retry. There is no server capture retry schedule. | Retry action reuses the same capture ID; after STT success, it reuses the in-memory transcript. |
| PRC-04 | P0 | Text-KB idempotency is keyed by the client UUID `capture_id`; repeated successful requests return the existing result. | Re-running extraction creates no duplicate capture/item/entities/relationships. |
| PRC-05 | P0 | Distinguish quota exhaustion, network error, provider failure and invalid input; return typed errors and allow explicit user retry. | Client error message is actionable; no job retry/backoff state. |
| PRC-06 | P0 | Tombstones for deleted entities; `user_edited` protects edited names/descriptions on reprocessing. | Delete an entity, then resume: it does not return. |
| PRC-07 | P0 | On success, return to Record with a success notification. Do not force a result screen. | — |
| PRC-08 | P0 | English audio only. Unreliable audio yields a clear error and no fabricated knowledge. | Non-English audio creates no entities. |

### 4.5 Extraction and knowledge graph (KG)

> [!NOTE]
> Entity extraction and graph construction are distinct operations. The extraction model identifies candidate entities and relationships from transcripts. Deterministic application logic performs entity resolution, deduplication, conflict detection, and knowledge graph updates. Graph traversal and relationship lookups are retrieval operations, not AI inference.

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| KG-01 | P0 | Extract entities and relationships from the transcript and save automatically with confidence and provenance (source record and transcript segment). | Every entity/relationship traces back to a specific recording. |
| KG-02 | P0 | Entity resolution: similarity ≥ 0.90 links automatically; 0.75–0.90 stays separate and is flagged as a possible duplicate (no UI to resolve in the MVP). **\[Default\]** | Thresholds are configurable; no automatic merge in the uncertain band. |
| KG-03 | P0 | Contradictory relationships: keep both, record the conflict and sources, never auto-resolve. | Opposing claims coexist and are flagged. |
| KG-04 | P0 | Single canvas with zoom/pan and clustered layout, using graph community detection (no topic-generation pipeline). **\[Default\]** | 2,000 nodes render smoothly with no data truncation. |
| KG-05 | P0 | Level-of-detail cluster collapsing when zoomed out; layout computed off the UI thread; loading never blocks the UI. | Pan and zoom stay smooth on a mid-range Android device. |
| KG-06 | P0 | Uncertain and conflicting relationships are distinguished by line style, not color alone; no numeric confidence on edges. | Verified in grayscale. |
| KG-07 | P0 | Entity detail: name, description, type, certainty status, related relationships, provenance (source recording); edit name/description; delete with confirmation. | Deleting an entity handles related relationships consistently. Provenance links to the source recording. |
| KG-08 | P0 | Relationship detail: source entity, type, target entity, certainty status, source recording; delete with confirmation without deleting either entity. | — |

### 4.6 Knowledge search and retrieval (SRCH)

> [!NOTE]
> Knowledge retrieval operates over explicitly stored entities and relationships. Embedding similarity is a retrieval mechanism, not AI reasoning. Transcripts are internal artifacts and are not exposed through user-facing search endpoints.

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| SRCH-01 | P0 | Hybrid search over entities and relationships in the Graph tab, ranked by embedding similarity and lexical score. | A near-synonym query still finds the right entity. |
| SRCH-02 | P0 | Results show name, type and context. Tapping focuses the node/edge on the canvas and opens its detail panel. | — |
| SRCH-03 | P0 | Handle empty queries, no results, and retrieval errors explicitly. | — |
| SRCH-04 | P0 | Embeddings and indexes are per-user and removed when their source data is deleted. | User A never gets user B's results; deleted content never returns. |
| SRCH-05 | P0 | Changing the embedding model triggers a full re-index; never mix vectors of different dimensions. **\[Default\]** | — |

### 4.7 My Recordings (VR)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| VR-01 | P0 | A recordings list: date/time, duration, status, audio playback, delete with confirmation. Reached from the Record tab. **\[Default location\]** | — |
| VR-02 | P0 | Recording detail: list of entities and relationships extracted from this recording with provenance; audio playback; processing status and error detail. Users can edit entity names/descriptions and delete entities/relationships from this view. | Extracted knowledge is navigable from the recording that produced it. |
| VR-03 | P0 | Audio playback endpoint is owner-only; no public URLs. The transcript endpoint is admin-only and must never appear in client API calls. | A user calling the transcript endpoint gets 403. Anyone else calling the audio endpoint gets 403/404. |
| VR-04 | P0 | Failed recordings are listed with a manual retry button. | — |

### 4.8 Data deletion (DEL)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| DEL-01 | P0 | Deleting a recording deletes its audio and transcript; deletes only entities/relationships with no remaining supporting recording; keeps shared knowledge; removes embeddings and index entries. | With an entity shared by two recordings, deleting one recording keeps the entity. |
| DEL-02 | P0 | Self-service account deletion takes effect immediately, revokes access, and hard-deletes all user data (local audio is removed by the app; server transcripts/graph/embeddings/sessions by the API). | After deletion every query returns 401 or no data. |
| DEL-03 | P0 | Be accurate about backups and third-party copies; never claim permanent deletion that has not been verified. | Retention is documented. |
| DEL-04 | P0 | Google Play minimum: privacy policy, Data Safety declaration, web URL for account deletion. | — |

### 4.9 Degradation (NET)

- **NET-01 (P0).** When the device is online but a backend or provider component is down: disable only the features that depend on it, name the failing component, preserve existing data and results. Never switch to a paid provider.
- **NET-02 (P0).** In-app notifications only, no push. Processing state and failures are reconstructed from the backend when the app opens.

### 4.10 Admin dashboard (ADM)

| ID | Pri | Requirement |
| --- | --- | --- |
| ADM-01 | P0 | **Authentication:** existing admin authentication is a server-configured `ECHO_ADMIN_TOKEN`, sent as `X-Admin-Token`; it fails closed if missing or wrong. This implementation contract is unchanged by the pipeline split. |
| ADM-02 | P0 | **Access audit:** admin mutations are audited with actor, resource, timestamp and outcome. **Current gap:** transcript/detail reads do not ask for a reason or create a read-access audit entry; the current app flow does not persist server audio for new captures. |
| ADM-03 | P0 | **A. Monitoring:** user/capture/entity/relationship counts, capture status counts, recent admin activity, and failure counts from capture `last_error`. There are no jobs or queue-depth metrics. |
| ADM-04 | P0 | **B. Pipeline debugging:** capture creation time, stored transcript and knowledge item, extracted entities/relationships, and `last_error`/`last_error_at`. Transcripts are accessible only through admin-authenticated routes. Admins may PATCH transcript text and invoke the Text-KB port with the existing capture ID. **Implementation gap:** completed captures currently return the idempotent existing result, so PATCH + rerun does not rebuild completed graph output. |
| ADM-05 | P0 | **C. Accounts:** search, view, create, update and delete users. **Current gap:** admin lock/unlock controls and account-deletion progress UI are not implemented. |
| ADM-06 | P0 | **D. Knowledge inspection:** view graphs to investigate wrong entities/relationships and inconsistencies; read-only by default. |
| ADM-07 | P0 | **E. AI configuration:** provider selection is server configuration only (`ECHO_STT_PROVIDER`, `ECHO_KB_EXTRACTOR`); requests cannot select providers. API keys live only in server environment variables, never in the frontend. No silent fallback. |
| ADM-08 | P0 | XSS protection and sanitization of user-generated content; no general bypass of tenant isolation. |

## 5. Non-functional requirements

- **Scale:** 100–1,000 users, up to 2,000 nodes each. The server uses PostgreSQL 16; the mobile app's local store uses SQLite. Do not introduce a queue or worker absent a measured requirement and owner decision.
- **Expected bottleneck:** Whisper on CPU, not the database. Verify actual resources before choosing models; do not assume a GPU.
- **Upload security:** validate file type and size, use safe paths, never trust user filenames, never expose filesystem paths.
- **Performance:** bounded queries, synchronous request timeouts, and no redundant provider calls. Add caching or services only with measured need; processing remains in the request and retry is user-triggered.
- **Configuration:** separate dev and production. Physical devices use a LAN IP or `adb reverse`, never `localhost`.

## 6. AI providers and privacy

- Separate provider code from business logic with interfaces for STT, entity extraction, relationship extraction, and embeddings. No abstraction without practical benefit.
- Before integrating any provider, check its current privacy policy, retention, training-data usage and free-tier limits, and record the results.
- Send only minimal data; never other users' data or unnecessary metadata.
- If free APIs are inadequate, evaluate local/self-hosted models per component (quality, latency, CPU/RAM, license).
- **Accepted risk (D11):** one heavy user can exhaust the shared free quota. Mitigation: specific error messages and quota-error counts on the admin dashboard.

## 7. AI evaluation and release thresholds

The evaluation set is synthetic or public, in English, and **never uses real user data**. Record model versions, configuration, latency and resource use, and make results reproducible.

| Component | Metric | Release threshold (initial target) |
| --- | --- | --- |
| STT | WER | ≤ 15% |
| Entity extraction | Precision, Recall, F1 | F1 ≥ 0.70 |
| Relationship extraction | F1 (correct label and correct source–target pair) | F1 ≥ 0.50 |
| Entity resolution | Pairwise Precision, Recall, F1 | To be calibrated after baseline |
| Graph construction | Node/edge correctness, no duplicate updates | To be calibrated after baseline |
| Provenance | Evidence coverage and correctness | To be calibrated after baseline |
| Processing | Latency, failure rate, retry rate | To be calibrated after baseline |

These numbers are not yet calibrated against a real baseline. If a free model misses a threshold, lowering it must be a recorded product decision, never a silent edit. Minimum sample size **\[Default\]**: 50 audio clips.

## 8. Known limitations and accepted risks

1. **Hold-only recording (D6):** users who cannot hold, or who use TalkBack, will struggle. Deliberate; revisit after the MVP.
2. **No admin 2FA (D4):** admins can hear all users' audio. Mitigated by short sessions, rate limiting and a mandatory audit log.
3. **Shared quota (D11):** see section 6.
4. **Consent is effectively mandatory (D2):** users who decline cannot use the app.
5. **Possible-duplicate flags** have no resolution UI in the MVP.
6. **Backups and third-party copies** may retain data after deletion; documented.

## 9. Open questions

- Which free email-sending service, and does its quota cover 1,000 users: fake email sending for MVP.
- KG-02 duplicate-matching thresholds and evaluation benchmarks need calibration after the baseline is measured.
- SRCH-05 full re-index on embedding model change is not yet automated.

## 10. Backlog: Build Echo AI Training Pipeline

**Status:** Backlog, explicitly excluded from the MVP. Scope: dataset collection and governance, labeling and QA, dataset versioning, train/validation/test splits, training or fine-tuning, model evaluation and comparison, model versioning and deployment. **Prerequisites:** a stable MVP, a controlled benchmark, results that expose concrete weaknesses, and defined data-authorization and governance rules.

## 11. Explicitly Excluded Features

The following are out of scope for the MVP. See `docs/PRODUCT_DIRECTION.md` §5 for the full list with rationale.

| Feature | Status |
| --- | --- |
| AI chatbot / conversational assistant | Excluded |
| LLM question answering over the knowledge graph | Excluded |
| Multi-hop AI reasoning | Excluded |
| Knowledge inference (generating new facts) | Excluded |
| Proactive AI insights or recommendations | Excluded |
| Document / image / PDF ingestion | Excluded |
| External knowledge imports | Excluded |
| Offline sync (CRDTs, vector clocks) | Excluded |
| Multi-user collaboration | Excluded |
| Semantic vector database as primary store | Excluded |
| User-visible transcript access (viewing, searching, or editing raw transcripts) | Excluded — admin-only |
