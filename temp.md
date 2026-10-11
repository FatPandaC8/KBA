I've read all six documents and probed the environment. Here's what I found before the questions.

Findings & contradictions
Environment facts (my job to find, not yours):

Repo is not yet a git repo; server/, mobile/, database/, README.md exist but are empty. Only docs/ has content.
Toolchain: Python 3.14.8 + pip 26.0.1, git 2.56, Docker 29.8 + Compose 5.6 (postgres:16-alpine already pulled), no psql/flutter/dart locally. Network to pypi.org and huggingface.co is open.
Hardware: 8 CPUs, 7.5 GB RAM, only 873 MB available, 4.6 GB in swap. This is a hard constraint on running transcription + extraction models concurrently.
Contradictions / gaps I resolved or must resolve:

Audio retention is undefined — PRD §12 lists it as open; DATA_MODEL §6 bans audio in PG but says nothing on transient-file cleanup; TEST_PLAN NOTE-012/013 assume a policy exists. Blocker for the voice task.
Auth mechanism is open in all four docs (PRD §12, DATA_MODEL §22, API_SPEC §17, ARCHITECTURE §10). API_SPEC §4.1 even ships a conditional /auth/refresh.
Extraction output schema does not exist anywhere — MVP_PLAN Phase 0 lists "Define the structured extraction output schema" as a deliverable, but no doc contains it. This is the AI boundary you asked me to recommend.
Auto-save threshold undefined — PRD §7.2 says high-confidence explicit facts "may be saved automatically" but no number; TEST_PLAN §10.3 gives quality targets, not a threshold.
Voice upload transport undefined — API_SPEC §7.2 defers it; POST /notes/{id}/transcribe implies audio must be associated transiently with a note, but no upload endpoint exists.
Deletion policy undefined — DATA_MODEL §19 describes per-table behavior but no unified rule for note→evidence→review-items.
Endpoint naming drift: ARCHITECTURE §12 lists /transcriptions, /extractions, /graph as resources; API_SPEC §8 uses /extraction-runs/{id}, /notes/{id}/proposals, /graph/neighborhood. Minor but should be reconciled.
entity_type / value_type are free-text in DATA_MODEL; recommend constrained enums for validation simplicity.
Last-active-admin concurrency mechanism is explicitly called out as open (DATA_MODEL §22 #8) and must be race-safe (TEST_PLAN ADM-005/006 require real parallel transactions).
Now the frontier. These are the decisions whose prerequisites are already settled — I can ask them now without guessing.

F1 - Authentication and session model: The docs leave the mechanism open. Options: (a) username/password + short-lived JWT in an httpOnly cookie, with role/status re-looked-up from the DB on every request (so disabling/revocation is prompt, no refresh token needed)

F2 - Account provisioning: Options: (c) hybrid — public register → user, plus admin POST /admin/users and a one-time setup script for the first admin.

F3 - Audio retention policy: Options: (b) retain 15 days for training purposes 

F4 - Extraction auto-save threshold: Options: (a) auto-save only explicit assertions with confidence ≥ 0.9 and at least one valid evidence span; everything else goes to review; 

F5 - Extraction output schema (the AI boundary you asked for): I need you to confirm the proposal I'm attaching below, since no doc defines it and it determines the KnowledgeExtractor interface and all extraction tests.

Proposed schema returned by the local model (validated by Pydantic before any DB write):

{
  "model": "model-name",
  "prompt_version": "v1",
  "entities": [
    {"mention": "Alice", "canonical_name": "Alice", "entity_type": "person",
     "aliases": [], "confidence": 0.98, "evidence": [{"note_offset": 0, "note_length": 5, "quoted_text": "Alice"}]}
  ],
  "facts": [
    {"subject_mention": "Alice", "predicate": "works_at", "object_mention": "Acme",
     "value_text": null, "value_type": "entity", "assertion_type": "explicit",
     "confidence": 0.97, "evidence": [{"quoted_text": "Alice works at Acme.", "start": 0, "end": 21}]}
  ],
  "relationships": [
    {"source_mention": "Alice", "target_mention": "Acme", "predicate": "works_at",
     "assertion_type": "inferred", "confidence": 0.6, "evidence": [...]}
  ]
}
Rules baked in: offsets are UTF-16 code units matching the client; assertion_type ∈ {explicit, inferred}; confidence ∈ [0,1]; every persisted assertion must carry ≥1 evidence span whose quoted_text is a substring of the source note; unknown fields are dropped; anything failing validation is rejected or queued for review — never persisted.

➡️ Recommended: accept as written, with two knobs: (1) whether relationships is required at all in the MVP (it is, per FR-017/FR-020), and (2) whether the model may emit facts with a literal value_text (yes, per DATA_MODEL §8).

F6 - Entity merge support: Options: (a) MVP supports no explicit merge API — conservative alias matching only, ambiguous matches always become review items

F7 - Deletion / supersession policy: Options: (a) notes are soft-deleted (status=deleted, deleted_at set) — evidence, extraction runs, and review items persist as historical records, but review items derived from a deleted note can no longer be accepted; facts/relationships use superseded_at on correction rather than deletion

F8 - Voice upload transport: Options: (b) a separate POST /audio/uploads returning a short-lived upload_id, then POST /notes/{id}/transcribe {upload_id}.

➡️ Recommended: (b). It decouples the size limit, TTL, and cleanup (TEST_PLAN NOTE-012/013/015) from the note lifecycle, lets the server enforce a 25 MB cap and 10-minute TTL before any transcription cost, and keeps raw audio out of PostgreSQL (DATA_MODEL §6). Transcription deletes the temp file on success or on TTL expiry.

F9 - Last-active-administrator concurrency mechanism: Options: (b) SELECT ... FOR UPDATE on the admin rows inside one transaction, count, reject if ≤1, then update; 

F10 - PostgreSQL row-level security: Options: (a) enable RLS as defense in depth; 

Conventions I'm pinning now (documented defaults, not open votes) — tell me to change any:

Evidence offsets = UTF-16 code units (matches Dart/JS String.substring, the client that will highlight spans).
FTS config = default Postgres config (english) with optional pg_trgm for typo tolerance; Vietnamese diacritics handled by the documented fallback (DATA_MODEL §6).
entity_type and value_type = constrained CHECK enums, not free text.
Facts vs relationships rule: facts = attributes/literal values about one entity; relationships = typed connections between two entities. Never duplicate the same assertion in both.
Literal values stored as text in value_text with value_type (no typed columns) — DATA_MODEL §8 trade-off.
Audit events = retain indefinitely, never deletable via API.
Note immutability = content_version INTEGER + extraction_runs.source_content_version; no full immutable-snapshot table.
Config allowlist = minimal: audio_retention_policy, extraction_auto_save_confidence, max_note_length, max_audio_upload_bytes, graph_max_depth, graph_max_results.
Two quick scoping confirmations before I write the report:

Q-A: Is the mobile client out of scope for the first five tasks (I'm planning tasks 1–5 as backend-only, ending at the text→knowledge milestone)? YES

Q-B: Do you want me to git init the repo and commit the six docs as the starting baseline?
Produce the final implementation-readiness report: contradictions resolved, proposed repository structure, the first five tasks with files/tests/acceptance/dependencies, the security-critical requirements, the deterministic AI test boundary, and the smallest end-to-end milestone.