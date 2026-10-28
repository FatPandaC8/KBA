# Echo MVP — PRD v2 (English)

*English rewrite of the Vietnamese PRD v2, reflecting all decisions confirmed with the product owner. Items tagged **\[Default\]** are the author’s proposals and have not yet been confirmed.*

## 1. Overview

Echo is an Android-first Flutter app (with a viable path to iOS) that turns a user’s spoken thoughts into a knowledge graph of entities and relationships. Users explore the graph, search it semantically, and ask AI questions that require reasoning across saved knowledge. Echo is a public multi-user product: each user has a private knowledge space, and only the application owner is an administrator.

**Navigation: three tabs — Record, Graph, Ask AI.** Search lives inside the Graph tab.

## 2. Confirmed decisions

| # | Topic | Decision |
| --- | --- | --- |
| D1 | Reprocessing | Only *resume* unfinished stages. Entities the user deleted get a tombstone and are never recreated. Names/descriptions the user edited get a `user_edited` flag and are never overwritten by AI. |
| D2 | Free providers that may train on data | Allowed, but only with clear notice and explicit user consent. |
| D3 | Mic denied / offline | Block the whole app, except logout, account deletion and policy pages. |
| D4 | Admin authentication | Email allowlist in environment variables plus a separate admin login. No 2FA in the MVP. |
| D5 | Voice records | Users can play back their own audio but can **never** see transcripts. |
| D6 | Recording | Press-and-hold only; release to send. No tap-to-toggle mode. |
| D7 | Auth | Email verification and password reset via a free email-sending service. |
| D8 | Scale | 100–1,000 users, up to 2,000 nodes per user. |
| D9 | Market | Unconstrained. Do only what Google Play requires everywhere. |
| D10 | Benchmarks | Concrete release thresholds (section 7). |
| D11 | Quota | No per-user usage limits. AI failures are reported clearly to users. |
| D12 | Search | Inside the Graph tab. Tapping a result focuses the node/edge on the canvas and opens its detail panel. |
| D13 | Ask AI | Separate tab, ChatGPT-style chat. Source chips are display-only and **not tappable**. |

## 3. Invariant constraints

- **C1.** No paid APIs and no paid fallback. On quota exhaustion, report the error and allow retry.
- **C2.** Authorization is enforced on the backend. Every user resource gets an ownership check.
- **C3.** Ordinary users never see transcripts. Ask AI never uses transcripts or audio as a knowledge source.
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
| GATE-04 | P0 | Offline: block the whole app, explain that internet is required, resume automatically when back online. The blocking screen shows the number of recordings waiting to upload. **\[Default\]** | No new records offline; pending recordings upload on reconnect. |

### 4.3 Recording and upload (REC)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| REC-01 | P0 | Press and hold to record; release to upload immediately, with no confirmation screen. | Early release is processed normally. |
| REC-02 | P0 | Show recording state, elapsed and remaining time. Maximum 2 minutes; auto-stop and submit at the limit. | A 120-second recording ends and submits without interaction. |
| REC-03 | P0 | Recordings under 1 second are discarded with a gentle notice. No cancel gesture. **\[Default\]** | An accidental tap creates no record. |
| REC-04 | P0 | No new recording until the previous one has finished uploading (background processing may continue). **\[Default\]** | Two parallel uploads are impossible. |
| REC-05 | P0 | Handle calls, backgrounding, network loss, empty/invalid audio. Never discard audio that has not been safely uploaded. | Simulating each case leaves the audio locally for retry. |
| REC-06 | P0 | Local audio is stored in an app-private directory and deleted only after the backend confirms receipt and storage. **\[Default\]** | Failed upload keeps the file; confirmed upload removes it. |
| REC-07 | P0 | Uploads are idempotent via a client-generated key; retries never create duplicate records. | Sending the same request twice yields one record. |

### 4.4 Processing pipeline (PRC)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| PRC-01 | P0 | Stages: upload, transcribe, extract, save, completed/failed. The UI shows real backend status; no fake percentages. | UI status matches the job table. |
| PRC-02 | P0 | Job state persists in the database (a job table with leases; no message broker). Cap concurrent heavy jobs. | Restarting the backend loses no jobs. |
| PRC-03 | P0 | The backend detects stuck jobs (expired lease) and resumes them. **Reopening the app is not a trigger.** | Two consecutive app opens create no duplicate jobs. |
| PRC-04 | P0 | Every stage is idempotent and reuses valid outputs from completed stages. Never restart a completed record from scratch. | Re-running extraction creates no duplicate entities or relationships. |
| PRC-05 | P0 | Up to 3 automatic retries for recoverable errors; permanent errors are not retried. Distinguish quota exhaustion, network error, provider failure and invalid input. Then report and allow manual retry. | Each error type shows a different message for the correct stage. |
| PRC-06 | P0 | Tombstones for deleted entities; `user_edited` protects edited names/descriptions on reprocessing. | Delete an entity, then resume: it does not return. |
| PRC-07 | P0 | On success, return to Record with a success notification. Do not force a result screen. | — |
| PRC-08 | P0 | English audio only. Unreliable audio yields a clear error and no fabricated knowledge. | Non-English audio creates no entities. |

### 4.5 Extraction and graph (KG)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| KG-01 | P0 | Extract entities and relationships from the transcript and save automatically with confidence and provenance (source record). | Every entity/relationship traces back to a record. |
| KG-02 | P0 | Duplicate matching: similarity ≥ 0.90 links automatically; 0.75–0.90 stays separate and is flagged as a possible duplicate (no UI to resolve in the MVP). **\[Default\]** | Thresholds are configurable; no automatic merge in the uncertain band. |
| KG-03 | P0 | Contradictory relationships: keep both, record the conflict and sources, never auto-resolve. | Opposing claims coexist and are flagged. |
| KG-04 | P0 | Single canvas with zoom/pan and clustered layout, using graph community detection (no topic-generation pipeline). **\[Default\]** | 2,000 nodes render smoothly with no data truncation. |
| KG-05 | P0 | Level-of-detail cluster collapsing when zoomed out; layout computed off the UI thread; loading never blocks the UI. | Pan and zoom stay smooth on a mid-range Android device. |
| KG-06 | P0 | Uncertain and conflicting relationships are distinguished by line style, not color alone; no numeric confidence on edges. | Verified in grayscale. |
| KG-07 | P0 | Entity detail: name, description, type, certainty status, related relationships; edit name/description; delete with confirmation. No transcripts or debug data. | Deleting an entity handles related relationships consistently. |
| KG-08 | P0 | Relationship detail: source, type, target, status; delete with confirmation without deleting either entity. | — |

### 4.6 Search inside Graph (SRCH)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| SRCH-01 | P0 | Semantic search bar in the Graph tab over entities and relationships, ranked by relevance. Never returns transcript text. | A synonym query still finds the right result. |
| SRCH-02 | P0 | Results show name, type and context. Tapping focuses the node/edge on the canvas and opens its detail panel. | — |
| SRCH-03 | P0 | Handle empty queries, no results, and retrieval errors. | — |
| SRCH-04 | P0 | Embeddings and indexes are per-user and removed with deleted data. | User A never gets user B’s results; deleted content never returns. |
| SRCH-05 | P0 | Changing the embedding model triggers a full re-index; never mix vectors of different dimensions. **\[Default\]** | — |

### 4.7 Ask AI (QA)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| QA-01 | P0 | Chat UI: conversation list, input at the bottom, reopen and continue conversations, delete a whole conversation. No manual naming. | History is isolated per user. |
| QA-02 | P0 | GraphRAG: retrieve relevant entities/relationships and follow graph connections. Knowledge sources are limited to entities, relationships, descriptions and provenance metadata. | Multi-hop questions are answered correctly. |
| QA-03 | P0 | Separate stored facts from AI inference; state missing evidence; surface contradictions; never fabricate. | Insufficient-evidence test set is refused correctly. |
| QA-04 | P0 | Each answer carries source chips (entity/relationship names). **Chips are display-only, not tappable.** Deleted sources show as “deleted”; the conversation is kept. **\[Default\]** | IDs and name snapshots are stored at answer time. |
| QA-05 | P0 | Handle empty questions, retrieval failure, LLM quota exhaustion, provider outage, network errors and malformed provider responses. | Each failure shows its specific cause. |

### 4.7b My Recordings (VR)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| VR-01 | P0 | A recordings list: date/time, duration, status, audio playback, delete with confirmation. Reached from the Record tab. No transcript. **\[Default location\]** | — |
| VR-02 | P0 | Audio playback endpoint is owner-only; no public URLs. | Anyone else gets 403/404. |
| VR-03 | P0 | Failed recordings are listed with a manual retry button. | — |

### 4.8 Data deletion (DEL)

| ID | Pri | Requirement | AC |
| --- | --- | --- | --- |
| DEL-01 | P0 | Deleting a record deletes its audio and transcript; deletes only entities/relationships with no remaining supporting record; keeps shared knowledge; removes embeddings and index entries; deletes Q&A that depended on the removed knowledge via explicit dependency tracking; keeps unrelated Q&A. | With an entity shared by two records, deleting one record keeps the entity. |
| DEL-02 | P0 | Self-service account deletion takes effect immediately, revokes access, and hard-deletes all data (audio, transcripts, graph, embeddings, jobs, Q&A, sessions) via a reliable workflow. | After deletion every query returns 401 or no data. |
| DEL-03 | P0 | Be accurate about backups and third-party copies; never claim permanent deletion that has not been verified. | Retention is documented. |
| DEL-04 | P0 | Google Play minimum: privacy policy, Data Safety declaration, web URL for account deletion. | — |

### 4.9 Degradation (NET)

- **NET-01 (P0).** When the device is online but a backend or provider component is down: disable only the features that depend on it, name the failing component, preserve existing data and results. Never switch to a paid provider.
- **NET-02 (P0).** In-app notifications only, no push. Processing state and failures are reconstructed from the backend when the app opens.

### 4.10 Admin dashboard (ADM)

| ID | Pri | Requirement |
| --- | --- | --- |
| ADM-01 | P0 | **Authentication:** email in the environment allowlist, separate admin login (isolated from the app), short sessions, rate limiting. No 2FA in the MVP; 2FA is P1 post-MVP. |
| ADM-02 | P0 | **Access audit:** before returning audio, transcripts or detailed knowledge, the admin must enter a reason; the backend logs admin, resource, timestamp and reason *before* returning data. Audio playback is logged too. The privacy policy discloses that admins may listen to audio for debugging. |
| ADM-03 | P0 | **A. Monitoring:** user count and activity, API errors, backend health, job status, failed jobs, **quota-error counts per provider**. |
| ADM-04 | P0 | **B. Pipeline debugging:** original audio, transcript, extracted entities/relationships, outcome, per-stage duration, errors (no secrets). |
| ADM-05 | P0 | **C. Accounts:** search users, view status, lock/unlock, track account-deletion progress (deletion is self-service; no admin approval). |
| ADM-06 | P0 | **D. Knowledge inspection:** view graphs to investigate wrong entities/relationships and inconsistencies; read-only by default. |
| ADM-07 | P0 | **E. AI configuration:** choose provider and model for STT, extraction, retrieval and Q\&A; verify the configuration works. API keys live only in server environment variables, never in the frontend. No paid fallback. |
| ADM-08 | P0 | XSS protection and sanitization of user-generated content; no general bypass of tenant isolation. |

## 5. Non-functional requirements

- **Scale:** 100–1,000 users, up to 2,000 nodes each. Keep SQLite with WAL and limited concurrent write jobs unless measurements show a real need to change.
- **Expected bottleneck:** Whisper on CPU, not the database. Verify actual resources before choosing models; do not assume a GPU.
- **Upload security:** validate file type and size, use safe paths, never trust user filenames, never expose filesystem paths.
- **Performance:** bounded queries, no redundant provider calls, temp-file cleanup. Add caches, queues or microservices only with measured need.
- **Configuration:** separate dev and production. Physical devices use a LAN IP or `adb reverse`, never `localhost`.

## 6. AI providers and privacy

- Separate provider code from business logic with interfaces for STT, entity extraction, relationship extraction, embeddings, retrieval and Q&A. No abstraction without practical benefit.
- Before integrating any provider, check its current privacy policy, retention, training-data usage and free-tier limits, and record the results.
- Send only minimal data; never other users’ data or unnecessary metadata.
- If free APIs are inadequate, evaluate local/self-hosted models per component (quality, latency, CPU/RAM, license).
- **Accepted risk (D11):** one heavy user can exhaust the shared free quota. Mitigation: specific error messages and quota-error counts on the admin dashboard.

## 7. AI evaluation and release thresholds

The evaluation set is synthetic or public, in English, and **never uses real user data**. Record model versions, configuration, latency and resource use, and make results reproducible.

| Component | Metric | Release threshold (initial target) |
| --- | --- | --- |
| STT | WER | ≤ 15% |
| Entities | F1 | ≥ 0.70 |
| Relationships | F1 (correct label and correct source–target pair) | ≥ 0.50 |
| Q&A | Correctness | ≥ 80% |
| Q&A | Unsupported claims | ≤ 10% |
| Q&A | Correct refusal on insufficient evidence | ≥ 80% |

These numbers are not yet calibrated against a real baseline. If a free model misses a threshold, lowering it must be a recorded product decision, never a silent edit. Minimum sample size **\[Default\]**: 50 audio clips, 100 Q&A questions.

## 8. Known limitations and accepted risks

1. **Hold-only recording (D6):** users who cannot hold, or who use TalkBack, will struggle. Deliberate; revisit after the MVP.
2. **No admin 2FA (D4):** admins can hear all users’ audio. Mitigated by short sessions, rate limiting and a mandatory audit log.
3. **Shared quota (D11):** see section 6.
4. **Consent is effectively mandatory (D2):** users who decline cannot use the app.
5. **Source chips are not tappable (D13):** users cannot jump from an answer to its source.
6. **Possible-duplicate flags** have no resolution UI.
7. **Backups and third-party copies** may retain data after deletion; documented.

## 9. Open questions

- What is the app UI language: English only
- Which free email-sending service, and does its quota cover 1,000 users: fake email sending for MVP 
- KG-02 and benchmark thresholds need calibration after the baseline is measured.

## 10. Backlog: Build Echo AI Training Pipeline

**Status:** Backlog, explicitly excluded from the MVP. Scope: dataset collection and governance, labeling and QA, dataset versioning, train/validation/test splits, training or fine-tuning, model evaluation and comparison, model versioning and deployment. **Prerequisites:** a stable MVP, a controlled benchmark, results that expose concrete weaknesses, and defined data-authorization and governance rules. Create this as an issue in the repository’s tracker, or as a documented backlog file if none exists.
