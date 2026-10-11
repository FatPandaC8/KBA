# DATA_MODEL.md

## 1. Purpose

This document defines the PostgreSQL data model for the personal knowledge management application.

The database stores:

- User accounts, roles, and account status.
- Text notes and voice transcripts.
- Entities, facts, and typed relationships.
- Evidence linking extracted knowledge to source notes.
- AI extraction runs and review items.
- Administrative audit events.

PostgreSQL is the single canonical source of truth. The knowledge graph is represented using relational tables and traversed with bounded-depth SQL queries.

## 2. Design principles

1. PostgreSQL is the canonical data store.
2. Each user's knowledge graph is private and isolated.
3. The application supports two fixed roles: `user` and `admin`.
4. Admin privileges manage accounts and operations; they do not automatically grant access to private knowledge.
5. All persisted note content is text or a transcript.
6. Raw audio is not stored in PostgreSQL.
7. AI-generated knowledge must retain source evidence and distinguish explicit from inferred assertions.
8. Changes must be traceable where history and auditability matter.
9. Schema changes are managed through versioned migrations.
10. Avoid a separate graph database, vector database, or duplicate canonical store in the MVP.

## 3. Entity relationship overview

```text
users
 ├── notes
 │    ├── evidence
 │    │    ├── fact_evidence ── facts
 │    │    └── relationship_evidence ── relationships
 │    ├── extraction_runs
 │    └── review_items
 ├── entities
 │    ├── facts
 │    └── relationships
 └── administrative audit events (as actor or target)

entities ── facts ── entities (optional entity-valued object)
entities ── relationships ── entities
```

All private knowledge records belong to a user. Audit events reference the administrative actor and, where applicable, the affected account.

## 4. Data types and conventions

- Primary keys: `UUID`.
- Timestamps: `TIMESTAMPTZ`, stored and returned in UTC.
- Flexible metadata: `JSONB`, used only where fields are genuinely variable.
- Note content and literal fact values: `TEXT`.
- Confidence: `REAL` constrained to `[0, 1]`.
- Status and role fields: constrained strings or PostgreSQL enums. Use one consistent approach across migrations.
- Foreign keys: explicit referential integrity.
- Deletion: use documented soft-delete or hard-delete policies; do not rely on implicit cascade behavior.

Use `created_at` and `updated_at` where records are mutable. Immutable event records generally need `created_at` only.

## 5. Table: `users`

Stores account identity, authorization role, and account status.

| Column | Type | Constraints / purpose |
|---|---|---|
| `id` | UUID | Primary key |
| `username` | TEXT | Required; unique after documented normalization |
| `password_hash` | TEXT | Required if local password authentication is used |
| `display_name` | TEXT | Optional |
| `role` | TEXT | Required; `user` or `admin`; default `user` |
| `status` | TEXT | Required; `active` or `disabled`; default `active` |
| `created_at` | TIMESTAMPTZ | Required |
| `updated_at` | TIMESTAMPTZ | Required |
| `last_login_at` | TIMESTAMPTZ | Optional |

### Constraints

- `role IN ('user', 'admin')`.
- `status IN ('active', 'disabled')`.
- Username uniqueness must follow one documented case-normalization policy.
- Clients cannot directly update `role` or `status` through ordinary profile endpoints.
- Initial administrator creation must use a controlled provisioning mechanism.
- Password hashes and authentication secrets must never be returned by API queries.

If authentication is delegated to a trusted identity provider later, replace the password-specific fields with a suitable external identity mapping rather than storing unnecessary credentials.

### Role semantics

**`user`**
- Manages their own notes and knowledge graph.
- Cannot manage accounts or change roles.
- Cannot access another user's private records.

**`admin`**
- Has the same private knowledge access as a regular user for their own graph.
- Can manage account metadata, roles, and account status.
- Can inspect permitted operational status and administrative audit events.
- Cannot automatically read another user's notes, entities, facts, relationships, transcripts, or review items.

Role authorization and ownership authorization are separate checks.

## 6. Table: `notes`

Stores user-created text notes and transcripts.

| Column | Type | Constraints / purpose |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required FK to `users.id` |
| `content` | TEXT | Required note text or transcript |
| `capture_type` | TEXT | `text` or `voice` |
| `status` | TEXT | `active` or `deleted` |
| `content_version` | INTEGER | Required; incremented when content changes |
| `created_at` | TIMESTAMPTZ | Required |
| `updated_at` | TIMESTAMPTZ | Required |
| `deleted_at` | TIMESTAMPTZ | Optional |

### Rules

- Voice content is transcribed before it is stored as note content.
- `content` always contains text, never audio bytes.
- Raw audio and temporary audio file paths are not stored in this table.
- `content_version` allows extraction results to be checked against the source version.
- Deleting a note must follow the documented evidence-retention policy.
- Queries must scope notes to the authenticated user's ID.

Indexes:

- `(user_id, created_at DESC)`
- `(user_id, status, updated_at DESC)`
- Full-text search index on `content`, using an appropriate Vietnamese search configuration or a documented fallback.

## 7. Table: `entities`

Stores canonical entities in a user's private graph.

| Column | Type | Constraints / purpose |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required FK to `users.id` |
| `canonical_name` | TEXT | Required |
| `entity_type` | TEXT | Required; e.g. `person`, `organization`, `place`, `concept` |
| `description` | TEXT | Optional |
| `aliases` | JSONB | Default empty array |
| `status` | TEXT | `active` or `archived` |
| `created_at` | TIMESTAMPTZ | Required |
| `updated_at` | TIMESTAMPTZ | Required |

### Rules

- An entity belongs to exactly one user's graph.
- Alias normalization and matching are application responsibilities.
- Automatic entity matching must not merge entities across users.
- Entity merging, if introduced, must preserve fact, relationship, and evidence references.

Indexes:

- `(user_id, entity_type, status)`
- `(user_id, canonical_name)`
- Optional trigram index for fuzzy name matching.

## 8. Table: `facts`

Stores assertions about an entity, including literal-valued facts.

| Column | Type | Constraints / purpose |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required FK to `users.id` |
| `subject_entity_id` | UUID | Required FK to `entities.id` |
| `predicate` | TEXT | Required |
| `object_entity_id` | UUID | Optional FK to `entities.id` |
| `value_text` | TEXT | Optional literal value |
| `value_type` | TEXT | `entity`, `text`, `number`, `boolean`, `date`, or `datetime` |
| `qualifiers` | JSONB | Default empty object |
| `assertion_type` | TEXT | `explicit` or `inferred` |
| `confidence` | REAL | Required; between 0 and 1 |
| `valid_from` | TIMESTAMPTZ | Optional start of real-world validity |
| `valid_to` | TIMESTAMPTZ | Optional end of real-world validity |
| `created_at` | TIMESTAMPTZ | Required |
| `updated_at` | TIMESTAMPTZ | Required |
| `superseded_at` | TIMESTAMPTZ | Optional record-history marker |

### Rules

- The subject entity and any entity-valued object must belong to the same `user_id` as the fact.
- For `value_type = 'entity'`, `object_entity_id` must be non-null and `value_text` must be null.
- For literal value types, `value_text` must be non-null and `object_entity_id` must be null.
- `confidence` must be between 0 and 1.
- `valid_to` must not precede `valid_from` when both are set.
- Inferred facts must not be silently presented as directly stated facts.
- Corrections should preserve relevant history where needed rather than silently erasing prior assertions.

### Value storage trade-off

For the MVP, literal values are stored as text and interpreted using `value_type`. This keeps the schema simple, but typed comparisons and range queries require application-level conversion. If numeric or temporal range queries become important, introduce dedicated typed-value columns or a normalized value representation through a migration.

### Ownership integrity

A plain foreign key to `entities.id` does not by itself prove that an entity belongs to the same user as a fact. Enforce this invariant through composite foreign keys or equivalent database constraints.

Recommended approach:

- Add a unique constraint on `(user_id, id)` in `entities`.
- Reference `(user_id, subject_entity_id)` and `(user_id, object_entity_id)` from `facts`, using the appropriate nullable-object rules.

## 9. Table: `relationships`

Stores typed connections between two entities.

| Column | Type | Constraints / purpose |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required FK to `users.id` |
| `source_entity_id` | UUID | Required FK to `entities.id` |
| `target_entity_id` | UUID | Required FK to `entities.id` |
| `predicate` | TEXT | Required |
| `qualifiers` | JSONB | Default empty object |
| `assertion_type` | TEXT | `explicit` or `inferred` |
| `confidence` | REAL | Required; between 0 and 1 |
| `valid_from` | TIMESTAMPTZ | Optional real-world validity start |
| `valid_to` | TIMESTAMPTZ | Optional real-world validity end |
| `created_at` | TIMESTAMPTZ | Required |
| `updated_at` | TIMESTAMPTZ | Required |
| `superseded_at` | TIMESTAMPTZ | Optional record-history marker |

### Rules

- Both endpoint entities must belong to the relationship's `user_id`.
- Confidence and temporal constraints follow the same rules as facts.
- Do not duplicate an identical assertion in both `facts` and `relationships` without a defined semantic reason.
- Use facts for entity attributes and literal-valued assertions; use relationships for meaningful connections between entities. The application must define this convention consistently.

Indexes:

- `(user_id, source_entity_id)`
- `(user_id, target_entity_id)`
- `(user_id, predicate)`

## 10. Table: `evidence`

Stores source spans supporting extracted knowledge.

| Column | Type | Constraints / purpose |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required FK to `users.id` |
| `note_id` | UUID | Required FK to `notes.id` |
| `start_offset` | INTEGER | Required; non-negative |
| `end_offset` | INTEGER | Required; greater than or equal to start offset |
| `quoted_text` | TEXT | Required |
| `created_at` | TIMESTAMPTZ | Required |

### Rules

- The source note must belong to the same user.
- Document whether offsets count Unicode code points, UTF-8 bytes, or another convention; use one convention consistently.
- Evidence must refer to the stored note version used for extraction. If evidence must remain valid after note edits, preserve source versions or store an immutable snapshot/reference to the original content.
- Do not use a model's unsupported explanation as evidence.

Indexes:

- `(user_id, note_id)`
- `(note_id, start_offset)`

## 11. Table: `fact_evidence`

Links facts to their supporting evidence.

| Column | Type | Constraints / purpose |
|---|---|---|
| `fact_id` | UUID | FK to `facts.id` |
| `evidence_id` | UUID | FK to `evidence.id` |
| `created_at` | TIMESTAMPTZ | Required |

Primary key: `(fact_id, evidence_id)`.

The fact and evidence must belong to the same user. Enforce this with composite foreign keys or equivalent database constraints.

## 12. Table: `relationship_evidence`

Links relationships to their supporting evidence.

| Column | Type | Constraints / purpose |
|---|---|---|
| `relationship_id` | UUID | FK to `relationships.id` |
| `evidence_id` | UUID | FK to `evidence.id` |
| `created_at` | TIMESTAMPTZ | Required |

Primary key: `(relationship_id, evidence_id)`.

The relationship and evidence must belong to the same user.

## 13. Table: `extraction_runs`

Tracks local AI processing of a note.

| Column | Type | Constraints / purpose |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required FK to `users.id` |
| `note_id` | UUID | Required FK to `notes.id` |
| `source_content_version` | INTEGER | Required note version processed |
| `model_name` | TEXT | Required |
| `prompt_version` | TEXT | Required |
| `status` | TEXT | `queued`, `running`, `succeeded`, `failed` |
| `output_json` | JSONB | Optional validated or raw structured output, subject to privacy policy |
| `error_code` | TEXT | Optional safe error classification |
| `started_at` | TIMESTAMPTZ | Optional |
| `completed_at` | TIMESTAMPTZ | Optional |
| `created_at` | TIMESTAMPTZ | Required |

### Rules

- The note must belong to the same user.
- Extraction runs must not be accessible across users.
- Do not store hidden model reasoning.
- Avoid storing duplicate note contents in `output_json`.
- Do not expose raw internal exceptions or sensitive runtime details to clients.
- A run based on an outdated source version must not overwrite newer knowledge without revalidation.

Indexes:

- `(user_id, note_id, created_at DESC)`
- `(status, created_at)`

## 14. Table: `review_items`

Stores proposals requiring user review.

| Column | Type | Constraints / purpose |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | Required FK to `users.id` |
| `note_id` | UUID | Required FK to `notes.id` |
| `extraction_run_id` | UUID | Required FK to `extraction_runs.id` |
| `item_type` | TEXT | `entity`, `fact`, or `relationship` |
| `proposed_json` | JSONB | Required structured proposal |
| `status` | TEXT | `pending`, `accepted`, `rejected` |
| `reviewed_at` | TIMESTAMPTZ | Optional |
| `created_at` | TIMESTAMPTZ | Required |
| `updated_at` | TIMESTAMPTZ | Required |

### Rules

- The note and extraction run must belong to the same user.
- Acceptance must validate the proposal again and apply the change transactionally.
- Repeated acceptance must not create duplicate knowledge.
- The review item must retain provenance to its source note and extraction run.
- A review item must not be accepted if its source is deleted or invalid under the retention policy.

Indexes:

- `(user_id, status, created_at DESC)`
- `(note_id, extraction_run_id)`

## 15. Table: `admin_audit_events`

Stores security-sensitive administrative actions.

| Column | Type | Constraints / purpose |
|---|---|---|
| `id` | UUID | Primary key |
| `actor_user_id` | UUID | Required FK to `users.id` |
| `action` | TEXT | Required action identifier |
| `target_user_id` | UUID | Optional FK to `users.id` |
| `outcome` | TEXT | `success` or `failure` |
| `reason` | TEXT | Optional administrative reason |
| `metadata` | JSONB | Default empty object; restricted non-sensitive metadata |
| `created_at` | TIMESTAMPTZ | Required |

### Events to audit

- Account creation through administrative provisioning.
- Role assignment, promotion, demotion, and revocation.
- Account disabling and reactivation.
- Security-sensitive account metadata changes.
- Global configuration changes.
- Failed privileged operations where useful for security monitoring.

### Rules

- Audit events are append-only through normal application operations.
- Ordinary users cannot read audit events.
- Administrators can read permitted audit records.
- Audit records must not include passwords, tokens, transcripts, note contents, private graph payloads, or hidden model reasoning.
- `actor_user_id` identifies the administrator performing the action.
- `target_user_id` identifies the affected account, when applicable.
- Retention and deletion must follow a documented policy.
- A failed action must not be represented as a successful change.

Indexes:

- `(created_at DESC)`
- `(actor_user_id, created_at DESC)`
- `(target_user_id, created_at DESC)`
- `(action, created_at DESC)`

For reliable auditing, write the audit event in the same database transaction as the successful administrative change. For failures that must be recorded, write a separate failure event after the failed transaction has rolled back.

## 16. Last-active-administrator protection

The system must prevent accidental removal of the last active administrator.

This rule applies when an operation would:

- Demote an active administrator to `user`.
- Disable an active administrator.
- Otherwise remove that account's ability to administer the system.

The safeguard must be concurrency-safe. A simple count followed by an update is insufficient because concurrent requests could both observe multiple administrators and then remove them all.

The application must serialize these operations using an appropriate transaction and locking strategy, or another database-enforced mechanism.

The database should enforce valid role and status values. The application service must enforce the broader last-active-administrator invariant within a concurrency-safe transaction.

Initial administrator provisioning must be separate from public account registration.

## 17. Ownership and isolation constraints

### 17.1 Required invariants

- Every private knowledge record has one owner.
- All referenced private resources belong to the same owner unless an explicit cross-owner relationship is introduced in a future design.
- Users can access only their own private records.
- Administrators cannot bypass ownership restrictions for private knowledge.
- Admin account management exposes account metadata only, not private graph content.
- Audit access is governed separately from private knowledge access.

### 17.2 Database enforcement

Application authorization checks are mandatory, but database constraints should prevent invalid references wherever practical.

Use composite foreign keys such as `(user_id, entity_id)` to ensure that related entities, facts, relationships, evidence, extraction runs, and review items cannot accidentally cross user boundaries.

Row-level security (RLS) may be considered as additional defense in depth. It is not a substitute for correct application authorization, and it must be designed carefully for connection pooling and the administrative audit workflow.

## 18. Indexing strategy

Create indexes only for expected query patterns.

| Table | Index purpose |
|---|---|
| `users` | Unique normalized username; role/status administration |
| `notes` | User-scoped chronological listing, status, full-text search |
| `entities` | User-scoped lookup by name and type |
| `facts` | Subject, predicate, and user-scoped retrieval |
| `relationships` | Source and target traversal |
| `evidence` | Source note and text-span lookup |
| `fact_evidence` | Fact-to-evidence joins |
| `relationship_evidence` | Relationship-to-evidence joins |
| `extraction_runs` | Note history and pending processing |
| `review_items` | User-scoped pending review |
| `admin_audit_events` | Actor, target, action, and time-based queries |

Indexes must support ownership-scoped access patterns, not merely unscoped searches.

## 19. Deletion and history policy

Deletion behavior must be explicit for each table.

- Notes may use soft deletion to preserve history and provenance.
- Entities must not be deleted in a way that leaves dangling facts or relationships.
- Facts and relationships may be superseded when a user corrects a previous assertion.
- Evidence should retain its relationship to the source content version where history is required.
- Review items derived from deleted notes must become invalid or be removed according to the documented policy.
- Extraction-run records should retain enough metadata to explain processing outcomes without unnecessarily duplicating private content.
- Administrative audit events must follow a dedicated retention policy and must not be silently removed through ordinary account deletion.

Account deletion, if introduced, requires a defined policy for private data, backups, and audit references. It must not accidentally remove the only record of a security-sensitive administrative action.

## 20. Data that is deliberately not stored

The MVP does not require:

- Raw audio blobs in PostgreSQL.
- Audio file paths in note records.
- External AI provider request logs.
- Hidden model reasoning.
- A separate graph database.
- A separate vector database.
- Shared graph ownership.
- A general-purpose role-permission management system.
- An unrestricted admin-access flag for private user content.

Temporary audio may exist outside PostgreSQL during transcription, subject to access controls and the documented retention policy.

## 21. Migration and implementation rules

1. Use Alembic for schema migrations.
2. Keep migrations versioned, reviewable, and reversible where practical.
3. Add ownership constraints before relying on cross-table relationships.
4. Add role and status constraints before exposing admin endpoints.
5. Provision the initial administrator through a controlled process.
6. Test migration behavior with existing data and duplicate or invalid values.
7. Test concurrent role changes and last-active-administrator protection.
8. Test cross-user references and authorization failures.
9. Avoid schema changes that duplicate canonical knowledge across multiple stores.
10. Update `API_SPEC.md`, `ARCHITECTURE.md`, and `TEST_PLAN.md` when the canonical model changes.

## 22. Open decisions

Resolve these before implementing the corresponding features:

1. Authentication mechanism and exact identity fields.
2. Self-registration versus administrator-managed account creation.
3. Note and evidence retention after deletion.
4. Whether immutable note versions are required for permanent evidence validity.
5. Whether numeric and temporal facts need native typed-value columns.
6. Audit-event retention and backup policy.
7. Whether PostgreSQL row-level security will be used as defense in depth.
8. Exact concurrency-safe implementation for last-active-administrator protection.

These decisions must not weaken user data isolation or allow administrators to access private knowledge by default.

## 23. Definition of done

The data model is ready when:

- Every private knowledge record is scoped to one user.
- The two fixed roles and two account statuses are enforced.
- Cross-user references are prevented by appropriate constraints.
- Administrative actions are auditable without recording private content.
- Last-active-administrator protection is implemented transactionally.
- Voice notes store transcripts, not raw audio.
- Knowledge assertions retain provenance and explicit/inferred status.
- Schema migrations and integrity tests pass.
- The API and test plan match the implemented schema.
