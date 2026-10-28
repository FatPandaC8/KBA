# M1 Audit — Requirements-to-Implementation Matrix (PRD v2)

**Date:** 2026-10-29
**Branch:** `mvp_v2_prd` (from `mvp_01`), baseline commit `909a584`
**Working tree at audit start:** clean
**PRD source of truth:** `docs/PRD_MVP.md` (PRD v2)

Status legend

| Status | Meaning |
| --- | --- |
| ✅ | Verified working end to end in the current code |
| 🟡 | Exists, but incomplete or broken against the PRD |
| ❌ | Missing |
| ♻️ | Must be replaced; keeping it would preserve a PRD violation |

Evidence labels: `[A]` automated test run in this audit, `[C]` code inspection, `[P]` physical-device run in an earlier session (not re-run in this audit).

---

## 1. Executive summary

The repository is a single-tenant demo, not a multi-user MVP. The largest gaps are structural:

1. **No user identity.** The backend authenticates with two static shared tokens (`ECHO_CLIENT_TOKEN`, `ECHO_ADMIN_TOKEN`). There is no user table, session, email verification, password reset, or Google Sign-In. Every ownership requirement (AUTH, DEL-02, SRCH-04, VR-02, ADM-02) is therefore unmet.
2. **Paid-provider path exists.** STT, embeddings and extraction each call OpenAI first when `OPENAI_API_KEY` is set, with local fallback (`faster-whisper tiny`, `fastembed bge-small`). This violates C1 unless removed.
3. **Transcripts are user-visible.** The Flutter detail screen renders `note.transcript` and the app stores/edits it locally. This violates D5/C3.
4. **The "graph" is a note list with keyword links.** One `knowledge_items` row per capture, `concepts`/`tags` strings, and relationships inferred by keyword overlap. There is no entity model, no duplicate matching, no conflict model, no per-user partition.
5. **The pipeline is synchronous inside the upload request.** There is a `processing_jobs` table but no lease, attempt count, worker cap, or resume logic. No client status endpoint exists.
6. **Ask AI does not exist.** No conversations, retrieval expansion, GraphRAG prompt, citations, or answer persistence.
7. **Admin is a shared-token dashboard.** No email allowlist, no session, no access-reason audit log, no user/quota views.
8. **Tests are green but single-tenant.** 21 server + 31 Flutter tests pass `[A]`, and none exercises users, isolation, QA, or admin authorization.

The prior hardening (upload validation, path confinement, delete/purge, secure token storage, bounded retries, graph bounds, Android config) is real and worth preserving.

---

## 2. Repository and stack inventory

| Area | Current state |
| --- | --- |
| Backend | FastAPI, Python 3.14, SQLite (WAL) |
| Client | Flutter (Android), 3 tabs **Home / Recall / Library** + Settings |
| Admin | Static HTML dashboard at `/admin`, token in `localStorage` |
| STT | local `faster-whisper tiny` (CPU/int8); optional remote OpenAI Whisper |
| Embeddings | local `fastembed BAAI/bge-small-en-v1.5` (384-d); optional remote OpenAI |
| Extraction | optional OpenAI chat completion; otherwise keyword/template fallback |
| Schema | `captures`, `knowledge_items`, `relationships`, `model_eval_records`, `knowledge_embeddings`, `processing_jobs` |
| Migrations | none; `CREATE TABLE IF NOT EXISTS` + ad-hoc `ALTER TABLE` in `init_database()` |
| Dependency manifest | **absent** (no `requirements.txt` / `pyproject.toml`) |
| Audit script | `server/test_server_semantic_consent.py` at repo root, pytest-invisible |

**Verification run in this audit**

| Command | Result |
| --- | --- |
| `python3 -m pytest server/tests -q` | 21 passed |
| `cd mobile && flutter test` | 31 passed |
| `cd mobile && flutter analyze` | No issues found |

Not re-run in this audit: Android build, physical-device flows, live STT/extraction quality.

---

## 3. Requirements matrix

### 3.1 Authentication (AUTH) — all missing

Current identity = one shared client bearer token. No user resource has an owner.

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| AUTH-01 | P0 | ❌ | No sign-up/login, no password storage. Shared token only. |
| AUTH-02 | P0 | ❌ | No Google Sign-In or server-side token validation. |
| AUTH-03 | P0 | ❌ | No email verification, no email sending. |
| AUTH-04 | P0 | ❌ | No password reset or session revocation. |
| AUTH-05 | P0 | ❌ | Sessions do not exist; static tokens never expire and logout is not a server action. |
| AUTH-06 | P0 | ❌ | No rate limiting on any endpoint. |
| AUTH-07 | P0 | ❌ | No account model, so no linking flow. |

**Verdict:** ♻️ replace the authentication layer entirely. Keep only the fail-closed posture (`empty token ⇒ 401`) as a principle.

### 3.2 Consent and gating (GATE)

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| GATE-01 | P0 | 🟡 | A single `evalConsent` switch exists (`/api/eval/consent`, stored as `consent_given` on eval rows). It is not a provider-list consent, has no version/timestamp per user, and does not gate recording. |
| GATE-02 | P0 | ❌ | Decline/withdrawal is not enforced; uploads work with `consent_given=false` (and then silently purge audio). |
| GATE-03 | P0 | 🟡 | Mic permission is requested at record time with an inline error. No app-wide blocking screen; no logout/account-deletion/policy actions. |
| GATE-04 | P0 | ❌ | No connectivity gate, no pending-upload count, no auto-resume screen. |

### 3.3 Recording and upload (REC)

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| REC-01 | P0 | ✅ | Press-and-hold; release submits. Covered by `push_to_talk_test.dart` `[A]` and verified on device earlier `[P]`. |
| REC-02 | P0 | 🟡 | Hard-coded `maxVoiceSeconds = 30` in UI and `max_voice_seconds = 30` on the server. PRD requires 120. |
| REC-03 | P0 | 🟡 | Discard threshold is 800 ms and only when the whole-second timer is still 0 (`home_screen.dart:74,152`); a ~0.9 s clip uploads. |
| REC-04 | P0 | 🟡 (broken) | `createAudioNote` returns immediately after kicking off an async upload, so `_isProcessing` clears and a second recording can start while the first is still uploading. |
| REC-05 | P0 | 🟡 (broken) | Backgrounding/call interrupts call `_cancelRecording()`, which deletes un-uploaded audio. No call-state handling. This contradicts "never discard audio that has not been safely uploaded". |
| REC-06 | P0 | 🟡 | Local audio is app-private, but it is never deleted after a confirmed upload (no `deleteFile` path). |
| REC-07 | P0 | 🟡 | Client key = note UUID and server has `idempotency_key UNIQUE`, but idempotency is keyed on `capture_id` and returns `ready` early; no test proves a duplicate POST yields one record. |

### 3.4 Processing pipeline (PRC)

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| PRC-01 | P0 | 🟡 | Stages are written to `processing_jobs` (`received → transcribing → extracting → indexing → completed/failed`), but there is no client endpoint to read job status; UI shows local states. |
| PRC-02 | P0 | 🟡 | Job rows exist but have no `lease_owner`, `lease_expires_at`, or `attempt`. Processing runs synchronously inside the upload request; a process kill leaves a `processing` row that nothing resumes. No worker cap. |
| PRC-03 | P0 | ❌ | No expired-lease detection or backend self-resume. |
| PRC-04 | P0 | 🟡 | Only whole-capture early return when `status == ready`. No per-stage output reuse; re-running overwrites items and relationships. |
| PRC-05 | P0 | ❌ | No retry count, no error classification (quota/network/provider/invalid), no manual retry contract. |
| PRC-06 | P0 | ❌ | No tombstones, no `user_edited`. Reprocessing can recreate deleted/edited content. |
| PRC-07 | P0 | 🟡 | Upload returns to the Record tab with a snackbar, but the snackbar offers a "View" action to a result screen (minor). No forced result screen. |
| PRC-08 | P0 | 🟡 | `faster-whisper` auto-detects language; no English check, no low-confidence guard, no "no fabricated knowledge" gate. |

### 3.5 Extraction and graph (KG)

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| KG-01 | P0 | 🟡 | One `knowledge_item` per capture (`title`, `core_idea`, `concepts`, `tags`) with a provenance string. No entity records, no confidence, no support/provenance rows. |
| KG-02 | P0 | ❌ | No entity matching, thresholds, or possible-duplicate flag. |
| KG-03 | P0 | 🟡 | Relationships have `suggested/confirmed`; no conflict record, no opposing-claim support. |
| KG-04 | P0 | 🟡 | Custom deterministic component-grid layout on the client. No community detection, no 2,000-node test, no cluster collapsing. |
| KG-05 | P0 | 🟡 | Layout is recomputed on the UI isolate; no level-of-detail; no measured mid-range-device budget. |
| KG-06 | P0 | 🟡 | Edge `status` exists in the model but styling is not proven distinct in grayscale; numeric confidence is absent (good). |
| KG-07 | P0 | 🟡 | Detail screen shows notes with transcript + debug-ish fields; edit name/summary; delete. No entity type/certainty; not an entity detail panel. |
| KG-08 | P0 | 🟡 | Relationship status/label update and delete exist over HTTP; no dedicated relationship detail UI with source/type/target. |

### 3.6 Search inside Graph (SRCH)

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| SRCH-01 | P0 | 🟡 | Cosine search over **knowledge-item** embeddings, not entities/relationships; global (no user scope). Never returns transcripts (good). |
| SRCH-02 | P0 | 🟡 | Results list opens the note detail; no focus-on-canvas / edge highlight / detail panel. |
| SRCH-03 | P0 | 🟡 | Empty, loading, no-result and error states exist in Recall/Library screens; not validated for the Graph-tab search UX. |
| SRCH-04 | P0 | ❌ | Embeddings are global; no per-user partition; no user deletion cascade. |
| SRCH-05 | P0 | ❌ | No embedding model/dimension record; no re-index trigger. |

### 3.7 Ask AI (QA) — entirely missing

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| QA-01 | P0 | ❌ | No conversation model, list, continuation, or delete. |
| QA-02 | P0 | ❌ | No GraphRAG retrieval, no bounded graph expansion, no subgraph prompt. |
| QA-03 | P0 | ❌ | No stored-fact/inference separation, no refusal or contradiction handling. |
| QA-04 | P0 | ❌ | No answers, no citation IDs/name snapshots, no "deleted" rendering. |
| QA-05 | P0 | ❌ | No Q&A error taxonomy. |

### 3.8 My Recordings (VR)

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| VR-01 | P0 | 🟡 | Notes list shows date/status/duration, retry and delete, but shows transcript and plays only a local file; not reachable as a Record-tab recordings list. |
| VR-02 | P0 | ❌ | No client audio endpoint. Only `/api/admin/captures/{id}/audio` exists, behind the admin token. |
| VR-03 | P0 | 🟡 | Retry exists on the detail screen; failed items are not surfaced as a recordings list with retry. |

### 3.9 Data deletion (DEL)

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| DEL-01 | P0 | 🟡 | Delete removes capture, item, relationships, embeddings, job, audio. No support/provenance rows, so "keep shared knowledge" cannot be expressed; no Q&A dependency cleanup. |
| DEL-02 | P0 | ❌ | No accounts, no self-service deletion, no session revocation. |
| DEL-03 | P0 | ❌ | No retention/backup documentation or deletion verification. |
| DEL-04 | P0 | ❌ | No privacy policy, Data Safety text, or public account-deletion URL. |

### 3.10 Degradation (NET)

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| NET-01 | P0 | 🟡 | Screens show generic errors and retries; no component-level disable/naming, no explicit "never switch to paid" guard. |
| NET-02 | P0 | 🟡 | Local note status is persisted, but there is no client job-status endpoint to reconstruct processing state on app open. |

### 3.11 Admin (ADM)

| ID | Pri | Status | Finding |
| --- | --- | --- | --- |
| ADM-01 | P0 | 🟡 | Single static `ECHO_ADMIN_TOKEN`; no email allowlist, no separate login, no session expiry, no rate limit. Token persisted in `localStorage`. |
| ADM-02 | P0 | ❌ | No reason prompt, no audit table, no pre-return logging; audio playback not logged. |
| ADM-03 | P0 | 🟡 | Overview/jobs/logs exist; no user counts, API-error rates, or per-provider quota-error counts. |
| ADM-04 | P0 | 🟡 | Capture inspection shows audio/transcript/knowledge/outcome; no per-stage durations or classified errors. |
| ADM-05 | P0 | ❌ | No account search/status/lock/deletion-progress. |
| ADM-06 | P0 | 🟡 | Knowledge list + delete exists; no graph inspection view; delete contradicts "read-only by default". |
| ADM-07 | P0 | 🟡 | Config shows environment/model/base URL/has-key and lets the model be changed at runtime; no provider/model selection per component, no verification step, no paid-fallback guard. |
| ADM-08 | P0 | 🟡 | `escapeHtml` is used and user content is escaped; but there is no tenant isolation to bypass (single tenant), and the token-in-localStorage pattern is weak. |

### Status counts

| Status | Count |
| --- | --- |
| ✅ verified working | 1 (REC-01) |
| 🟡 exists but incomplete/broken | 34 |
| ❌ missing | 26 |
| ♻️ replace | Auth layer + extraction/graph model (cross-cutting) |

---

## 4. Security and data-integrity risks

Ordered by severity.

1. **No tenant isolation (critical).** Any holder of the shared client token reads, edits, deletes, searches and (after VR-02) plays every user's data. This is the single largest release blocker.
2. **Shared static tokens (high).** No expiry, no revocation, no per-device binding. Admin and client tokens are printed in config/settings and the admin token is stored in `localStorage`.
3. **Paid-provider calls (high, policy).** `OPENAI_API_KEY` silently routes STT, embeddings and extraction to a paid API. It also sends user audio/text to a third party without a provider-specific consent.
4. **Transcript exposure (high, privacy).** Transcripts are shipped to and displayed by the client (`note_detail_screen.dart:385-475`, `note.dart`, `database_helper.dart`). D5 forbids this.
5. **Un-uploaded audio is deleted on backgrounding/calls (high, data integrity).** `didChangeAppLifecycleState → _cancelRecording()` deletes the in-progress file.
6. **No idempotency/lease safety in processing (high).** A crash mid-request leaves a `processing` job forever; a client retry can re-run extraction and create duplicates.
7. **No deletion dependency model (high).** Deleting a capture cannot preserve shared entities or clean dependent answers, so DEL-01 is unachievable without provenance/support tables.
8. **Admin access to user audio has no audit trail (high, privacy).** Deleting `/api/admin/knowledge/{id}` is unrestricted and unlogged.
9. **Runtime config mutation (medium).** `POST /api/admin/config` mutates the live model/base URL; combined with a shared token this is a remote prompt/data-routing change.
10. **Dev dependency on `localhost` (medium).** The settings screen defaults to a host URL; physical devices need LAN IP or `adb reverse`, and the debug cleartext exception must not leak into release.
11. **No dependency manifest (medium).** Versions are implicit; builds are not reproducible and CVE scanning is impossible.
12. **Legacy duplicate schema modules (low).** `server/app/db.py`, `pipeline.py`, `schemas.py` and the root test import a second, divergent schema. Risk of fixing the wrong layer.

---

## 5. Test inventory and gaps

**Existing (passing)**

- Server unit: domain invariants, use-case behavior.
- Server integration: admin API, admin dashboard, client security (401/413/path/traversal).
- Server architecture: import-boundary test.
- Flutter: push-to-talk, recording navigation guard, graph layout/bounds/failure, DB migration, note edit race, provider regression, semantic consent, Android config, back navigation.

**Missing (must be added from M2)**

- Auth: sign-up/login/reset/verification, generic errors, session expiry/revocation, Google token rejection.
- Isolation: user A vs user B for read/edit/delete/search/audio/ask.
- Upload: duplicate idempotency key, size/type rejection, concurrent uploads.
- Pipeline: stage idempotency, lease expiry/resume, retry caps, error classification, duplicate-open safety.
- KG: entity matching bands, conflict retention, tombstone/user_edited protection, 2,000-node performance.
- Search: per-user partition, deletion removal, model-change re-index.
- QA: grounding/citations, refusal on missing evidence, contradiction surfacing, malformed output, quota error.
- Deletion: shared-entity retention, Q&A dependency cleanup, account deletion revocation.
- Admin: allowlist login, session expiry, rate limit, reason-required audit ordering, XSS.
- Evaluation harness: WER, entity F1, relationship F1, QA correctness/refusal/unsupported claims.

---

## 6. Dead, duplicate and misplaced code

| Path | Issue | Proposed action |
| --- | --- | --- |
| `server/app/db.py` | Second schema/connection implementation, unreferenced by app code | Remove after confirming no imports in M2 |
| `server/app/pipeline.py` | Legacy pipeline, superseded by `application/use_cases` | Remove in M2 |
| `server/app/schemas.py` | Legacy Pydantic models, superseded by `adapters/inbound/http/schemas.py` | Remove in M2 |
| `server/test_server_semantic_consent.py` | Root-level pytest file importing legacy modules, not collected | Delete or rewrite against current stack |
| `main.py` backward-compat alias (`pipeline = container.extractor`, injected `embed_knowledge_item`) | Keeps a legacy shape only for the root test | Remove with the legacy test |
| `mobile/lib/ui/screens/recall/recall_screen.dart` | Duplicate search UX, not in the PRD's three tabs | Fold into Graph tab |
| `mobile/lib/ui/screens/home/widgets/text_capture_dialog.dart` | Text capture is not in PRD (voice-first) | Remove or move to backlog; owner decision |
| `mobile/lib/services/ai_service.dart` | Direct client→OpenAI transcription path (paid, leaks key) | Remove (security + C1) |

---

## 7. Proposed implementation order

The PRD milestone order is sound. Within M2–M3 I propose this sequence so each step is testable:

**M2 — Foundation and security**
1. Schema v1 migration runner + `users`, `sessions`, `consent_versions`, `admin_sessions`, `admin_audit_log`, `records`, `entities`, `entity_supports`, `relationship_supports`, `tombstones`, `user_edits`, `conversations`, `messages`, `answer_citations`, `jobs` (lease/attempt columns).
2. Auth: email/password (argon2id), sessions, verification/reset (fake email adapter in dev), rate limiting, Google token verification interface (disabled without credentials).
3. Ownership middleware/repository scoping helper; fail-closed by default.
4. Upload hardening carried over + `user_id` + idempotency key scoped per user.
5. Isolation test suite (read/edit/delete/search/audio).

**M3 — Core**
6. Provider interfaces and the free-only registry; delete OpenAI remote paths; record provider metadata.
7. Job worker with lease, stage outputs, retry caps and error taxonomy; client job-status endpoint.
8. Recording UX: 120 s, press-and-hold, serialized uploads, retain-on-background, delete-on-confirmed-receipt.
9. Extraction: entities + relationships + confidence + support/provenance; matching bands; conflicts; tombstones/user_edited.
10. Graph: server-side community detection, client LOD, node focus from search, 2,000-node fixture.
11. Ask AI: conversations, bounded graph retrieval, structured answer with citations, refusal rules.
12. Recordings list + owner audio endpoint; deletion cascade with support counts and citation cleanup.

**M4 — Admin:** allowlist login, sessions, rate limits, audit-before-return, users/quota views, graph inspection, provider config validation.

**M5 — Reliability/eval:** retry/idempotency tests, degradation matrix, WER/entity/relationship/QA benchmark harness, thresholds.

**M6 — UI/UX:** design system, three tabs, states, graph usability, accessibility (TalkBack limits documented).

**M7 — Verification/release:** full suites, local E2E, device run, release build, docs, production prep, final report.

**Risk notes**

- Local `faster-whisper tiny` may miss WER ≤ 15%. M5 will measure; if it misses, I will report and ask, not lower the threshold.
- SQLite write concurrency is acceptable for the stated scale only if heavy jobs are capped; M3 will enforce a small worker limit.
- Google Sign-In requires a real OAuth client ID; without it AUTH-02 stays behind a disabled adapter and is reported as unverified.

---

## 8. Owner decisions needed at M1

None block M2. Flagged for later confirmation:

1. **Provider set.** Proposal: local `faster-whisper` (STT) + local `fastembed` (embeddings) + a free LLM tier for extraction/Q&A. All paid OpenAI paths removed. Consent screen must name whichever free LLM is used.
2. **Email service.** PRD section 9 says "fake email sending for MVP". Proposal: dev adapter writes verification/reset links to logs and a local inbox file; production adapter left pluggable.
3. **Text capture.** Not in PRD. Proposal: remove from the UI, keep in backlog.
4. **`[Default]` items** will be implemented as written and listed for confirmation: GATE-04, REC-03, REC-04, REC-06, KG-02, KG-04, SRCH-05, QA-04, VR-01 location, eval minimum sample size.

---

## 9. Evidence from this audit

```
$ python3 -m pytest server/tests -q
21 passed in 3.22s

$ cd mobile && flutter test
All tests passed!  (31)

$ cd mobile && flutter analyze
No issues found!
```

Code anchors for the main findings: `server/app/infrastructure/config/__init__.py` (tokens, 30 s, OpenAI key), `server/app/api/dependencies.py` (shared-token auth), `server/app/api/routes/client.py:56-166` (synchronous upload), `server/app/application/use_cases/__init__.py:62` (pipeline), `server/app/adapters/outbound/{speech,embeddings,extraction}/__init__.py` (remote-first providers), `mobile/lib/ui/app_shell.dart` (tabs), `mobile/lib/ui/screens/home/home_screen.dart:69,73` (background cancel, 30 s), `mobile/lib/ui/screens/detail/note_detail_screen.dart:385` (transcript), `server/app/static/index.html:625` (localStorage token).
