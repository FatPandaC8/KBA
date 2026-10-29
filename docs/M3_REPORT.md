# Echo MVP — M3 report (capture → pipeline → graph → Ask AI)

*Status: implemented and verified locally, awaiting owner approval. Date: 2026-10-29. Branch: `mvp_v2_prd`.*

This report covers milestone M3 of `docs/PRD_MVP.md` (v2): the recording/upload
pipeline, processing jobs, knowledge graph, graph search, Ask AI, My Recordings,
and the deletion behaviour those features require. M2 already delivered AUTH and
GATE; M4 will cover administration and the production deployment surface.

## 1. What was built

### Backend

- **Asynchronous pipeline (REC-01…REC-07, PRC-01…PRC-08).** `POST
  /api/captures/upload` now accepts audio and returns `202` with a job in
  `queued`. A single background `JobWorker` (started/stopped in the app
  lifespan) claims jobs atomically, advances
  `upload → transcribe → extract → save → completed`, and marks `failed` as a
  terminal state. Jobs are persisted in `processing_jobs` with a lease, attempt
  counter and per-stage outputs. Expired leases are claimable, so a restarted
  backend resumes work without the client triggering anything. Completed stages
  are reused on resume; re-uploading the same idempotency key returns the same
  job instead of creating a second one.
- **Retries and error classes (PRC-05).** Up to three automatic retries for
  recoverable errors only (`network_error`, `provider_failure`,
  `quota_exhausted`). `invalid_input` fails permanently. Every failure is
  reported with the stage and class, and manual retry is available through
  `POST /api/recordings/{id}/retry`.
- **Extraction and graph (KG-01…KG-08).** A deterministic, local rule-based
  extractor produces entities and relationships with confidence, certainty and
  provenance; ids are stable per user/capture. Duplicate matching uses a
  documented similarity: ≥ 0.90 auto-links, 0.75–0.90 is stored as a flagged
  candidate per entity pair. Contradicting relationships are both kept and
  marked `conflicting`. Deleted entities get tombstones and user-edited names /
  descriptions are protected (`user_edited`).
- **Graph layout (KG-04, KG-05).** The server performs deterministic label
  propagation (community detection) and assigns node coordinates and cluster
  metadata, so the client only renders. No topic-generation pipeline is used.
- **Graph search (SRCH-01…SRCH-04).** Hybrid semantic (fastembed) + lexical
  scoring over entities and relationships, scoped to the owner. Responses never
  include transcripts or raw audio.
- **Ask AI (QA-01…QA-05).** Conversations and messages persist per user.
  `POST /api/ask` answers from a graph-grounded, deterministic local answerer
  behind `AnswerProviderPort`: facts, inferences and contradictions are returned
  separately, and insufficient evidence produces a refusal instead of an answer.
  Citations store the target id **and** a name snapshot, so deleted sources keep
  their name and show as `deleted`.
- **Deletion (DEL-01, DEL-02).** Deleting a record removes its audio and
  transcript, removes embeddings and support links, deletes entities and
  relationships with no remaining supporting record, keeps shared knowledge, and
  deletes only Q&A messages that directly cited knowledge removed by that record.
  Account deletion revokes sessions and hard-deletes the user's data.
- **Providers (GATE-01, D2).** `GET /api/providers` lists only the free local
  components actually in use; no paid provider is configured or reachable.

### Mobile

- **Three tabs** — Record (centre FAB), Graph, Ask AI — with search inside the
  Graph tab (`app_shell.dart`, `echo_bottom_nav.dart`).
- **Serialized upload queue (REC-04).** Captures are inserted locally and
  uploads are sent one at a time (M3 behaviour). Revised by owner decision
  2026-10-29: the mic is no longer gated by an in-flight upload or by
  server-side processing — a new recording can start immediately; uploads
  still serialize in the queue.
- **Status polling (PRC-01, PRC-03).** The client polls
  `/api/recordings/{id}/status` and maps real backend stages to the visible
  state; no fake percentages. Polling stops on `ready`/`failed`.
- **Audio retention (REC-05, REC-06; revised 2026-10-29).** The local file was
  deleted only after a terminal `ready` in M3. Per the owner decision, the
  local copy is now deleted as soon as the server answers 202 — the backend
  only returns 202 after the file write and the capture/job DB commit, so the
  server copy is durable and retries use server-side audio. An upload that
  never reaches 202 (network down, server rejected) keeps the local file.
  Server-only audio is streamed through the authenticated bytes endpoint,
  never a public URL.
- **My Recordings (VR-01…VR-03).** Date, duration, status, playback, delete with
  confirmation and manual retry. No transcript is shown.
- **Reconciliation (NET-02).** On app open the client reads
  `/api/recordings` and rebuilds local state; it never creates jobs.
- **Graph canvas (KG-04…KG-08).** Server coordinates are authoritative, with
  zoom/pan, fit-to-view, level-of-detail cluster collapsing below 0.55 scale,
  and a deterministic local fallback only when every server coordinate is
  identical. Certainty is encoded by line style (solid/dashed/dotted) and
  `?`/`!` label prefixes, never colour alone. Entity and relationship panels
  support edit/delete with confirmation.
- **Search (SRCH-01…SRCH-03).** 350 ms debounced search; results show name, type
  and context; tapping focuses the node/edge on the canvas and opens the detail
  panel. Empty, no-result and error states are distinct and retryable.
- **Ask AI (QA-01…QA-05).** Conversation history, new conversation, delete,
  chat input, distinct failure labels (`quota_exhausted`, `network_error`,
  `provider_failure`) and **display-only** citation chips including
  `name (deleted)`.

## 2. Requirement coverage

| Requirement | State | Primary evidence |
| --- | --- | --- |
| REC-01, REC-02 | Already implemented (M2), unchanged | `home_screen.dart`, `push_to_talk_test.dart` |
| REC-03 | Implemented | sub-second discard; `push_to_talk_test.dart` |
| REC-04 | Implemented, revised 2026-10-29 | serialized upload queue; mic no longer gated by in-flight work; `m3_pipeline_test.dart` "uploads are serialized" |
| REC-05 | Implemented | upload failures (no server confirmation) keep the local file; `m3_pipeline_test.dart` |
| REC-06 | Implemented, revised 2026-10-29 | local audio deleted on server receipt+storage confirmation (202), not on `ready`; server copy keeps captures retryable; `m3_pipeline_test.dart` + reconciliation test |
| REC-07 | Implemented | idempotency key; `test_pipeline_m3.py::test_writing_to_a_ready_job_is_idempotent_and_not_duplicated` |
| PRC-01, PRC-02 | Implemented | job table + worker; `test_pipeline_m3.py` stage tracking |
| PRC-03 | Implemented | lease expiry; `test_resume_reuses_completed_stage_outputs_without_reprocessing` |
| PRC-04 | Implemented | per-stage outputs reused; same test |
| PRC-05 | Implemented | retries/error classes; three pipeline tests + client mapping tests |
| PRC-06 | Implemented | tombstones + `user_edited`; `test_deleted_entity_is_not_recreated_by_later_captures` |
| PRC-07 | Implemented | success returns to Record; no result screen |
| PRC-08 | Implemented | invalid/non-English audio fails without knowledge; `test_invalid_audio_fails_permanently_and_never_loops` |
| KG-01 | Implemented | extraction with provenance; `test_extraction_is_deterministic_with_stable_ids_and_provenance` |
| KG-02 | Implemented | thresholds; `test_duplicate_entities_auto_link_above_090_and_flag_between_075_and_090` |
| KG-03 | Implemented | `test_contradicting_edges_are_both_kept_and_marked` |
| KG-04, KG-05 | Implemented | server clustering + coordinates; `test_graph_layout_is_clustered_and_deterministic`, `test_graph_handles_two_thousand_nodes_within_budget` |
| KG-06 | Implemented | line styles + text markers; `m3_ask_search_test.dart`, `knowledge_graph_failure_test.dart` |
| KG-07, KG-08 | Implemented | `test_entity_detail_update_and_delete`; `graph_detail_sheets.dart` |
| SRCH-01, SRCH-02 | Implemented | `test_graph_search_finds_entities_by_name_and_prefix`; `m3_ask_search_test.dart` (debounce + focus) |
| SRCH-03 | Implemented | empty/no-result/error states; `m3_ask_search_test.dart` |
| SRCH-04 | Implemented | owner scoping; `test_graph_is_scoped_to_the_owner`, `test_conversations_and_ask_are_owner_scoped` |
| SRCH-05 | **Partial** | `model_name`/`dimension` stored and mismatched vectors score 0 (never mixed); automatic full re-index job is not built (see §5) |
| QA-01, QA-03 | Implemented | `test_grounded_answer_carries_display_only_citations`, `test_conversation_continues_with_the_same_thread` |
| QA-02 | Implemented | refusal on an empty graph **and** on a non-empty graph for an unrelated question: `test_ask_refuses_instead_of_inventing_when_graph_is_empty`, `test_ask_refuses_an_unrelated_question_when_notes_exist`; search relevance floor: `test_graph_search_does_not_match_everything_for_an_unrelated_query` |
| QA-04 | Implemented | citation ids + name snapshots; `test_deleted_entity_citation_is_marked_but_keeps_its_name`; chips non-tappable in `m3_ask_search_test.dart` |
| QA-05 | Implemented | distinct failures; `test_quota_network_and_provider_failures_are_distinct_and_retryable` |
| VR-01…VR-03 | Implemented | `/api/recordings*` owner-only routes; `recordings_screen.dart` |
| DEL-01 | Implemented | shared entity kept; `test_deleting_one_record_keeps_entities_still_supported_by_another`; `test_deleting_a_record_removes_only_answers_that_cited_it` |
| DEL-02 | Implemented (M2, retained) | account deletion revokes sessions and removes data |
| DEL-03, DEL-04 | Documentation (M4/M5) | production prep still to be written |
| NET-01 | Implemented | failing component named, data preserved, no paid fallback |
| NET-02 | Implemented | reconciliation test; resume creates no jobs |
| ADM-* | Out of scope for M3 | M4 |

## 3. Deliberate behaviour to confirm

These decisions were agreed during M3 and are visible in the product:

1. **Record deletion vs. direct entity deletion (DEL-01 / QA-04).** Deleting a
   *record* also deletes Q&A messages that cited knowledge removed by that
   record, because their evidence no longer exists. Deleting an *entity or
   relationship directly* keeps conversations and shows `deleted` citation
   chips. This is the reconciliation of the two requirements and is deliberate.
2. **"Confirmed receipt" for local audio** means the server reached terminal
   `completed` and the client received the knowledge snapshot — not merely HTTP
   202. A failed job always keeps local audio.
3. **Duplicate matching only compares entities from other captures**, so a
   single recording cannot flag itself.
4. **Server coordinates are authoritative**; the client's deterministic layout
   engine is only a fallback for degenerate (all-identical) coordinates.
5. **Extraction is deterministic and rule-based.** No generative model is used
   for extraction or answers in the MVP; this is what makes the free/local
   constraint and the refusal behaviour auditable.
6. **Search and Ask require relevance.** A shared word with an entity, or a
   clearly close embedding, is required before an entity counts as evidence.
   Similarity alone is not evidence: with `bge-small`, an unrelated question
   still scores 0.42–0.52 against every name, so without this floor the
   assistant answered any question whenever the graph was non-empty. The
   threshold is 0.62 (calibrated; genuine matches score ≥ 0.74).

## 4. `[Default]` items implemented — please confirm

These are the author's proposals from the PRD, implemented as written:

| ID | Implemented behaviour |
| --- | --- |
| REC-03 | Recordings shorter than 1 s are discarded with a gentle notice; no cancel gesture. |
| REC-04 | Uploads serialize in the queue; the mic is never gated by in-flight work (revised 2026-10-29, supersedes the M3 original). |
| REC-06 | Local audio is deleted on server receipt + durable-storage confirmation (202 after file+DB commit), not on terminal `ready` (revised 2026-10-29, supersedes the M3 original); server-side failure paths keep the server copy and still allow manual retry. |
| KG-02 | 0.90 auto-link / 0.75–0.90 flagged candidate, per entity pair; no manual resolve UI. |
| KG-04 | Server-side community detection with a single clustered canvas. |
| SRCH-05 | Vectors are tagged with model and dimension and never mixed; **full re-index on model change is not automated** (see §5). |
| QA-04 | Source chips are display-only; deleted sources show `name (deleted)` and the conversation is kept. |
| VR-01 | My Recordings is reached from the Record tab; no transcript. |
| GATE-04 | Offline blocking screen includes the pending-upload count (M2). |

## 5. Limitations (not claimed as done)

- **Quality thresholds are not measured yet.** WER ≤ 15 %, entity F1 ≥ 0.70,
  relationship F1 ≥ 0.50, QA correctness ≥ 80 %, unsupported claims ≤ 10 % and
  correct refusal ≥ 80 % are M5 work against a labelled gold set. M3 verifies
  behaviour, not accuracy.
- **Local `faster-whisper tiny`** may miss the WER target; if it does, M5 will
  report it and ask, not lower the threshold.
- **SRCH-05 re-index** is a documented gap: model/dimension are persisted and
  mismatches are never mixed, but switching the embedding model requires a
  manual re-index today.
- **2,000-node test is a server-side budget test**, not an on-device frame-rate
  measurement; smooth pan/zoom was observed on the test device with a small
  graph only, so a large-graph frame-rate check is still outstanding.
- **No generative extraction/answering provider**, so "AI" here is
  graph-grounded deterministic logic. This satisfies the no-paid-API constraint
  and is reported as such; it is not an LLM quality comparison. The rule-based
  extractor is coarse: a real recording about a report and two people produced
  three entities and generic "Related to" edges (see §7).
- **Real speech was verified with a synthesised WAV, not a human recording**
  (§7). This exercises the real local STT and pipeline; it is not the M5 WER
  measurement.

## 6. Automated evidence

```
$ python3 -m pytest server/tests -q
72 passed in 33.49s

$ cd mobile && flutter test
All tests passed!  (49 tests)

$ cd mobile && flutter analyze
No issues found!

$ cd mobile && flutter build apk --debug
✓ Built build/app/outputs/flutter-apk/app-debug.apk
```

New M3 test files: `server/tests/unit/test_extraction_m3.py`,
`server/tests/integration/test_pipeline_m3.py`, `test_graph_m3.py`,
`test_ask_m3.py`, `test_providers_m3.py`, `mobile/test/m3_pipeline_test.dart`,
`mobile/test/m3_ask_search_test.dart`, `mobile/test/auth_gate_test.dart`,
`mobile/test/record_outcome_snackbar_test.dart`.

## 7. Android build and physical-device pass

Device: Sony `802SO` (Xperia), Android 10, id `BH9704EQGU`, 1096×2560 at 420 dpi.
Build: `flutter build apk --debug`; package `dev.echo.notes.dev`; backend on the
host reached with `adb reverse tcp:8000 tcp:8000`.

| Check | Result |
| --- | --- |
| Install and cold start | Launches to the auth gate; no crash. |
| Sign in | Real account created, verified, consented through the API; UI sign-in against the local backend succeeded. |
| Session persistence | After `force-stop` and relaunch the app opened directly to the tabs, no re-login. |
| Tabs | Record (centre mic), Graph, Ask AI all present; Record is the landing tab. |
| Graph tab | Loads `/api/graph`, shows the empty state ("No knowledge yet") with search available. |
| Ask AI (empty graph) | Reaches `/api/ask`, shows the refusal "There is not enough evidence in your graph to answer that." and no citation chips. |
| Press-and-hold recording | 4.5 s hold recorded and uploaded (`202`, then status polling). |
| Failure surface | The captured silence failed with `invalid_input`; My Recordings showed "Failed · invalid input", the honest explanation, playback of the retained audio, Retry and Delete. |
| Terminal feedback | The "Organizing…" banner was replaced by "This recording could not be processed. Open My recordings to retry." and expired after 6 s; the stale banner no longer sticks. |
| Real speech path (host, same build) | A synthesised WAV ("Remind me to send the quarterly report to Alice on Friday…") was uploaded through the API: `ready` in <2 s, knowledge item created, graph with 3 nodes / 2 edges, grounded answer with citations for "Who is Alice?", refusal for "What is my blood type?". |

### Defects found by the device pass and fixed

1. **Auth gate never reopened the app after sign-in.** `SettingsService` did not
   notify listeners, so a successful login left the user on the gate until the
   next launch. Fixed by making it a `ChangeNotifier` and resetting the shell on
   session change; regression test `auth_gate_test.dart`.
2. **A SnackBar with an action never expired.** Current Flutter defaults
   `persist` to `action != null`, so "Organizing…" stayed on screen forever and
   still claimed work was running after a failure. Fixed with an explicit
   terminal message plus `persist: false`; regression test
   `record_outcome_snackbar_test.dart`. Also fixed "1 captures".
3. **Any question was answered once the graph was non-empty.** Semantic
   similarity alone marked every entity as evidence. Fixed with the relevance
   floor described in §3.6; regression tests in `test_ask_m3.py` and
   `test_graph_m3.py`. Verified against the real embedding model.
