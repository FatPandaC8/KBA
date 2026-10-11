# TEST_PLAN.md

## 1. Purpose

This document defines the testing strategy for the personal knowledge management application.

It covers:

- Authentication and account lifecycle.
- Role-based access control (RBAC) for `user` and `admin`.
- Isolation of private knowledge graphs.
- Notes, voice transcription, and local AI extraction.
- Entities, facts, relationships, and evidence.
- Review workflows, search, and graph traversal.
- Administrative audit events and operational endpoints.
- Data integrity, performance, backup, and recovery.

The goal is to verify that the application is functionally correct, protects private information, and behaves predictably when local AI services or infrastructure fail.

## 2. Testing principles

1. **Test observable behavior.** Prefer API and database outcomes over implementation details.
2. **Test authorization and ownership separately.** Having permission to manage accounts does not imply permission to read their private knowledge.
3. **Use isolated test data.** Tests must not depend on real private notes or production accounts.
4. **Test AI output as untrusted input.** Model output must be validated before persistence.
5. **Make tests deterministic where possible.** Use fixed fixtures and mock model responses for most automated tests.
6. **Use real local services for integration tests.** Verify PostgreSQL, transcription, and extraction separately from unit tests.
7. **Test failure paths.** Include timeouts, malformed outputs, concurrent requests, partial failures, and interrupted processing.
8. **Protect sensitive data in tests and logs.** Do not use real passwords, tokens, or private user content.
9. **Keep acceptance criteria measurable.** Do not declare the MVP complete based only on a successful demo.

## 3. Test scope

### In scope

- Authentication, sessions, and account status.
- `user` and `admin` role enforcement.
- Resource ownership and cross-user isolation.
- Administrator account management and audit events.
- Last-active-administrator protection.
- Note CRUD and voice-to-transcript flow.
- Structured extraction and evidence.
- Entity resolution and review.
- Fact and relationship lifecycle.
- Search and bounded graph traversal.
- Data integrity and migrations.
- Local AI service failures and resource limits.
- Backup and restore.
- Performance and privacy.

### Out of scope for the MVP

- Multi-organization tenancy.
- Shared or collaborative graphs.
- Custom roles and configurable permission policies.
- External AI provider integrations.
- Vector database or semantic retrieval quality.
- Large-scale production load testing beyond the target deployment.
- Autonomous execution of model-generated commands.

## 4. Test environments

| Environment | Purpose | Dependencies |
|---|---|---|
| Unit | Business logic and validation | Test runner, mocks |
| API integration | HTTP behavior, authorization, schemas | FastAPI test client, test PostgreSQL |
| Database integration | Constraints, transactions, migrations | Isolated PostgreSQL |
| AI integration | Actual local model behavior | Local transcription/extraction runtimes |
| End-to-end | Complete user workflows | API, PostgreSQL, client or API-driven scenario |
| Performance | Latency and resource usage | Representative local hardware |
| Recovery | Backup and restoration | Isolated recovery environment |

Use a separate test database. Tests must never point at the user's live knowledge database by default.

## 5. Test data and fixtures

Create deterministic fixtures for at least:

- `admin_a`: active administrator.
- `admin_b`: second active administrator.
- `user_a`: active regular user.
- `user_b`: active regular user.
- `disabled_user`: disabled regular user.
- `note_a`, `entity_a`, `fact_a`, `relationship_a`: owned by `user_a`.
- `note_b`, `entity_b`, `fact_b`, `relationship_b`: owned by `user_b`.
- Evidence, extraction runs, and review items belonging to both users.

Include test cases for:

- Empty notes and long notes.
- Vietnamese text, diacritics, punctuation, and mixed-language content.
- Duplicate and near-duplicate entity names.
- Explicit and inferred assertions.
- Missing evidence and invalid evidence offsets.
- Malformed model output.
- Stale extraction results.
- Deleted notes and archived entities.
- Concurrent account-role changes.

Use synthetic content only.

## 6. Authentication and account lifecycle

| ID | Test | Expected result |
|---|---|---|
| AUTH-001 | Login with valid credentials | Authentication succeeds |
| AUTH-002 | Login with incorrect credentials | Rejected without exposing sensitive details |
| AUTH-003 | Request a protected endpoint without credentials | `401` |
| AUTH-004 | Use invalid or expired credentials | `401` |
| AUTH-005 | Access protected endpoints after logout or session revocation | Rejected according to the authentication design |
| AUTH-006 | Disabled user logs in | Rejected |
| AUTH-007 | Disable a user with an active session | Subsequent protected requests are rejected promptly |
| AUTH-008 | Re-enable a disabled user | Access resumes only through the documented authentication flow |
| AUTH-009 | Retrieve `/auth/me` | Returns current account identity, role, and status without secrets |
| AUTH-010 | Submit `role` or `status` through self-service profile update | Protected fields are rejected or ignored; no privilege change occurs |
| AUTH-011 | Register an account, if self-registration is enabled | New account receives only the permitted default role |
| AUTH-012 | Attempt to create the first administrator through a public endpoint | Rejected |

The chosen authentication mechanism must define session expiration, logout, revocation, and role freshness. Tests must verify the actual documented behavior.

## 7. RBAC tests

### 7.1 Role permissions

| ID | Test | Expected result |
|---|---|---|
| RBAC-001 | Regular user accesses their own knowledge endpoints | Allowed |
| RBAC-002 | Regular user accesses `/admin/users` | `403` |
| RBAC-003 | Regular user accesses administrative audit endpoints | `403` |
| RBAC-004 | Regular user accesses detailed administrative system health | `403` |
| RBAC-005 | Regular user changes their own role to `admin` | Rejected; role unchanged |
| RBAC-006 | Regular user changes another user's role | Rejected |
| RBAC-007 | Administrator views permitted account metadata | Allowed |
| RBAC-008 | Administrator assigns a regular user the `admin` role | Allowed and audited |
| RBAC-009 | Administrator revokes an administrator role | Allowed when safeguards pass and action is audited |
| RBAC-010 | Administrator disables or reactivates an account | Allowed and audited |
| RBAC-011 | Non-admin modifies global configuration | Rejected |
| RBAC-012 | Administrator submits an invalid role or status | Validation error; no mutation |
| RBAC-013 | Client submits a forged role claim or `user_id` | Server ignores untrusted claims and uses authenticated identity/current authorization state |
| RBAC-014 | Role change occurs while the target has an active session | New permissions take effect within the documented revocation window |
| RBAC-015 | Administrator attempts an unsupported privileged operation | Rejected |
| RBAC-016 | Administrator updates their own display name | Allowed if the field is permitted; role and status remain protected |

### 7.2 Private-content isolation

These tests are mandatory even when the caller is an administrator.

| ID | Test | Expected result |
|---|---|---|
| ISO-001 | `user_a` reads `note_a` | Allowed |
| ISO-002 | `user_a` reads `note_b` | Denied without leaking private content |
| ISO-003 | `user_a` updates or deletes `note_b` | Denied; `note_b` unchanged |
| ISO-004 | `user_a` reads `entity_b`, `fact_b`, or `relationship_b` | Denied |
| ISO-005 | `user_a` reads evidence or review items belonging to `user_b` | Denied |
| ISO-006 | `user_a` searches for unique text in `user_b`'s notes | No private results returned |
| ISO-007 | `user_a` traverses a graph using `entity_b`'s ID | No foreign graph data returned |
| ISO-008 | Administrator reads another user's note through a normal knowledge endpoint | Denied |
| ISO-009 | Administrator reads another user's graph through search or traversal | Denied |
| ISO-010 | Administrator uses account-management endpoints | Only permitted account metadata is returned |
| ISO-011 | Create a fact referencing an entity owned by another user | Database or service rejects the operation |
| ISO-012 | Create a relationship with endpoints owned by different users | Rejected |
| ISO-013 | Link evidence to a fact or relationship owned by another user | Rejected |
| ISO-014 | Create an extraction run for another user's note | Rejected |
| ISO-015 | Create a review item linking another user's note or extraction run | Rejected |
| ISO-016 | Request a nonexistent private resource | Returns the documented not-found behavior |
| ISO-017 | Use a guessed UUID belonging to another user | No unauthorized data disclosure |
| ISO-018 | Attempt to manipulate pagination or filters to retrieve foreign records | No foreign records returned |

For every private resource type, test both read and write operations. Hiding a resource in the UI is not authorization.

## 8. Administrator safeguards and audit

### 8.1 Last active administrator

| ID | Test | Expected result |
|---|---|---|
| ADM-001 | Demote an administrator when another active administrator exists | Allowed and audited |
| ADM-002 | Disable an administrator when another active administrator exists | Allowed and audited |
| ADM-003 | Demote the only active administrator | Rejected; account remains an active administrator |
| ADM-004 | Disable the only active administrator | Rejected; account remains active |
| ADM-005 | Concurrently demote two remaining administrators | At least one active administrator remains |
| ADM-006 | Concurrently disable two remaining administrators | At least one active administrator remains |
| ADM-007 | Attempt to remove the last administrator through different API routes | Safeguard applies consistently |
| ADM-008 | Fail an administrative update during its transaction | No partial role/status change |
| ADM-009 | Provision the initial administrator | Only the controlled provisioning process can do so |

The concurrency tests must use actual parallel requests and PostgreSQL transactions. A unit test that mocks the administrator count is insufficient.

### 8.2 Audit events

| ID | Test | Expected result |
|---|---|---|
| AUD-001 | Assign or revoke a role | Correct actor, target, action, outcome, and timestamp recorded |
| AUD-002 | Disable or reactivate an account | Audit event recorded |
| AUD-003 | Change global configuration | Audit event recorded |
| AUD-004 | Perform an administrative operation that fails validation | No successful-change event is recorded |
| AUD-005 | Cause an authorized operation to fail after authorization | Failure is recorded where required by the audit policy |
| AUD-006 | Read audit events as a regular user | Denied |
| AUD-007 | Read audit events as an administrator | Only permitted audit fields are returned |
| AUD-008 | Inspect audit payloads | No passwords, tokens, transcripts, note content, or private graph payloads |
| AUD-009 | Attempt to update or delete an audit event through normal APIs | Rejected |
| AUD-010 | Roll back a successful-change transaction | The success audit event is not committed independently |
| AUD-011 | Execute concurrent administrative operations | Each committed change has a consistent audit record |

Audit assertions should verify both the event and the actual database state. An audit event alone does not prove that the operation was correctly applied.

## 9. Notes and voice capture

| ID | Test | Expected result |
|---|---|---|
| NOTE-001 | Create a valid text note | Note is saved with the authenticated owner |
| NOTE-002 | Create an empty or invalid note | Validation follows documented rules |
| NOTE-003 | Retrieve, update, and delete an owned note | Correct state transitions |
| NOTE-004 | Submit an arbitrary `user_id` during note creation | Owner remains the authenticated user |
| NOTE-005 | Retry a create request with the same idempotency key | No unintended duplicate note |
| NOTE-006 | Submit Vietnamese text and diacritics | Text persists without corruption |
| NOTE-007 | Submit a large note | Documented size limit is enforced |
| NOTE-008 | Transcribe valid voice input | Transcript is produced by the local service |
| NOTE-009 | Correct a transcript before extraction | Extraction uses the corrected text |
| NOTE-010 | Transcription service unavailable | Clear failure state; no fabricated transcript |
| NOTE-011 | Transcription times out | Request fails safely and can be retried |
| NOTE-012 | Temporary audio cleanup executes | Audio is removed according to retention policy |
| NOTE-013 | Inspect database after voice capture | No raw audio blob or temporary audio path is stored in note content |
| NOTE-014 | Attempt to access another user's voice transcript | Denied |
| NOTE-015 | Submit an oversized or unsupported audio file | Rejected before expensive processing |

The audio transport and retention behavior must be tested against the finalized implementation, not an assumed upload design.

## 10. Structured extraction

### 10.1 Schema and validation

| ID | Test | Expected result |
|---|---|---|
| EXT-001 | Extract a simple person entity | Valid entity proposal |
| EXT-002 | Extract an organization or place | Correct entity type or review proposal |
| EXT-003 | Extract a literal-valued fact | Correct predicate, value, and value type |
| EXT-004 | Extract an entity-to-entity relationship | Correct endpoints and predicate |
| EXT-005 | Process a note containing multiple assertions | Each supported assertion is represented correctly |
| EXT-006 | Process ambiguous text | Uncertain output is flagged or sent for review |
| EXT-007 | Model returns malformed JSON | Output rejected; no invalid knowledge persisted |
| EXT-008 | Model returns unknown fields or invalid types | Schema validation rejects or safely normalizes them |
| EXT-009 | Model returns confidence outside `[0, 1]` | Output rejected or normalized under a documented rule |
| EXT-010 | Model invents evidence not found in the source | Evidence validation fails |
| EXT-011 | Model returns a cross-user entity ID | Ownership validation rejects the proposal |
| EXT-012 | Model proposes a destructive action | No action is executed merely because extraction returned it |
| EXT-013 | Model or local runtime is unavailable | Run fails safely and records a safe error state |
| EXT-014 | Same note is processed twice | No unintended duplicate knowledge |
| EXT-015 | Note changes while extraction is running | Stale output is not silently applied |
| EXT-016 | Model emits explicit and inferred assertions | Assertion types are preserved correctly |

### 10.2 Entity resolution

| ID | Test | Expected result |
|---|---|---|
| ENT-001 | Extract an entity already in the user's graph | Existing entity can be reused |
| ENT-002 | Extract an alias of an existing entity | Candidate match is suggested or safely resolved |
| ENT-003 | Extract an ambiguous name | No unsafe automatic merge |
| ENT-004 | Two different users have identically named entities | No cross-user merge or disclosure |
| ENT-005 | Merge or correct an entity, if supported | References and provenance remain valid |
| ENT-006 | Entity is archived | Search and extraction respect the documented status behavior |

### 10.3 AI quality evaluation

Maintain a versioned, representative evaluation dataset. Evaluate the extractor independently from persistence and UI behavior.

Track:

- Entity precision and recall.
- Predicate and relationship precision.
- Fact value accuracy.
- Entity-resolution accuracy.
- Evidence-span accuracy.
- Explicit/inferred classification accuracy.
- Schema-valid output rate.
- End-to-end extraction latency.
- Memory consumption on target hardware.

Initial release gates:

| Metric | Initial target |
|---|---:|
| Schema-valid output | ≥ 98% |
| Persisted fact precision | ≥ 90% |
| Persisted relationship precision | ≥ 90% |
| Evidence correctness for persisted assertions | 100% |
| Unsupported assertions silently persisted as confirmed | 0 |
| Destructive actions executed from extraction alone | 0 |

These are initial engineering targets, not proof of broad model reliability. The evaluation dataset must include difficult, ambiguous, and negative examples. Report sample size and confidence intervals where appropriate.

## 11. Evidence and provenance

| ID | Test | Expected result |
|---|---|---|
| EVD-001 | Persist an assertion with valid source evidence | Evidence is linked correctly |
| EVD-002 | Evidence span falls outside source text | Rejected |
| EVD-003 | Evidence quote does not match its source span | Rejected or flagged |
| EVD-004 | Source note is edited after extraction | Stale evidence is identifiable |
| EVD-005 | Source note is deleted | Retention policy is applied consistently |
| EVD-006 | A fact has multiple supporting notes | All valid evidence links are retained |
| EVD-007 | A relationship references foreign-user evidence | Rejected |
| EVD-008 | An assertion is marked inferred | Status remains visible to API consumers |
| EVD-009 | API returns an assertion | Source provenance is available where required |

Choose one offset convention and test it with Vietnamese Unicode text, combining marks, punctuation, and emoji.

## 12. Review workflow

| ID | Test | Expected result |
|---|---|---|
| REV-001 | List pending review items | Only the caller's items are returned |
| REV-002 | Accept a valid proposal | Knowledge is persisted transactionally |
| REV-003 | Reject a proposal | Proposal is marked rejected |
| REV-004 | Edit a proposal before acceptance | Validated changes are applied |
| REV-005 | Accept the same proposal twice | No duplicate assertion is created |
| REV-006 | Accept an invalid proposal | No invalid knowledge is persisted |
| REV-007 | Accept a proposal after its source becomes invalid | Operation is rejected or requires reprocessing |
| REV-008 | Two requests accept the same proposal concurrently | At most one effective acceptance |
| REV-009 | User attempts to accept another user's proposal | Denied |
| REV-010 | Administrator attempts to accept another user's proposal | Denied by ownership rules |

## 13. Facts, relationships, and temporal integrity

| ID | Test | Expected result |
|---|---|---|
| DATA-001 | Create a fact with an entity-valued object | Valid entity reference |
| DATA-002 | Create a fact with a literal value | Correct value and `value_type` |
| DATA-003 | Provide both entity object and literal value | Rejected |
| DATA-004 | Omit both entity object and literal value | Rejected |
| DATA-005 | Create a relationship between owned entities | Allowed |
| DATA-006 | Create a relationship with a foreign endpoint | Rejected |
| DATA-007 | Provide confidence below 0 or above 1 | Rejected |
| DATA-008 | Provide invalid temporal ordering | Rejected |
| DATA-009 | Supersede a fact | History and retrieval remain consistent |
| DATA-010 | Delete or archive an entity with references | Referential integrity preserved |
| DATA-011 | Attempt to create duplicate knowledge through retries | No unintended duplicates |
| DATA-012 | Run migrations against an existing database | Schema and data remain valid |
| DATA-013 | Query an entity's neighborhood | Correct bounded graph results |
| DATA-014 | Create evidence links across owners | Rejected by service or database constraints |

Where practical, use composite foreign keys to enforce same-owner references at the database level.

## 14. Search and graph traversal

| ID | Test | Expected result |
|---|---|---|
| SRCH-001 | Search for an existing note phrase | Relevant owned results returned |
| SRCH-002 | Search using Vietnamese text and diacritics | Behavior matches the documented search configuration |
| SRCH-003 | Search for an absent term | Empty result set |
| SRCH-004 | Filter by supported result types | Only requested types returned |
| SRCH-005 | Search across notes and graph records | All results are ownership-scoped |
| SRCH-006 | Request an unsupported graph depth | Validation error |
| SRCH-007 | Request an excessive result limit | Limit enforced |
| SRCH-008 | Traverse a valid graph neighborhood | Correct nodes and edges returned |
| SRCH-009 | Attempt cross-user traversal | No foreign records exposed |
| SRCH-010 | Paginate a large result set | Stable pagination without unintended duplication or leakage |

## 15. Database integrity and migrations

Test the schema directly, not only through HTTP endpoints.

- Required fields reject null values.
- Role and status constraints reject invalid values.
- User identity uniqueness is enforced.
- Facts and relationships cannot reference entities belonging to another user.
- Evidence and review records cannot cross user boundaries.
- Foreign keys behave according to the documented deletion policy.
- Audit records cannot be modified through ordinary application operations.
- Transaction rollback leaves no partial data.
- Concurrent operations preserve invariants.
- Migrations succeed from a clean database and the previous supported schema version.
- Migration failures do not leave the database in an undocumented state.

If PostgreSQL row-level security is used, test policies using the same roles and connection-pooling behavior used in the deployed application.

## 16. API contract and error handling

- Validate request and response schemas.
- Verify documented status codes.
- Verify consistent error formats.
- Verify pagination and filtering limits.
- Verify unknown fields are handled according to the schema policy.
- Verify invalid UUIDs and enum values are rejected.
- Verify protected fields cannot be changed through mass assignment.
- Verify error responses do not reveal stack traces, SQL, credentials, filesystem paths, or private content.
- Verify a missing dependency produces a controlled error rather than corrupting state.

## 17. Performance and resource usage

Initial targets for the target home-server hardware:

| Operation | Initial target |
|---|---|
| Note CRUD API, excluding inference | p95 ≤ 500 ms |
| PostgreSQL text search on the initial dataset | p95 ≤ 500 ms |
| Bounded graph traversal on the initial dataset | p95 ≤ 500 ms |
| Authorization checks | No material overhead beyond the documented API latency budget |
| Role/status revocation | Enforced within the chosen documented revocation window |

These targets are provisional and must be measured on the actual deployment environment.

For local AI, benchmark separately:

- Transcription latency and real-time factor.
- Extraction latency per note.
- Peak resident memory.
- CPU utilization.
- Behavior under concurrent requests.
- Recovery after timeout or out-of-memory termination.

The system must enforce limits on note length, audio size, extraction concurrency, graph depth, and result count. It must not become unresponsive because several inference requests run simultaneously.

## 18. Privacy and security testing

- Private note content never appears in application logs by default.
- Passwords, tokens, and authentication secrets are never logged.
- Administrative audit events contain no private knowledge payloads.
- No private content is sent to external AI services.
- Temporary audio follows the retention policy.
- API responses expose only fields permitted for the endpoint.
- Cross-user access is tested using valid IDs, guessed IDs, filters, pagination, and graph traversal.
- Disabled accounts are rejected by every protected endpoint.
- Administrative endpoints validate both role and account status.
- The server does not trust client-provided owner IDs or role claims.
- Backup files and database credentials are protected.
- Rate limits are applied to authentication and sensitive operations.
- Dependency and configuration checks are run before deployment.

The cross-user isolation suite must include administrator callers, not just regular users.

## 19. Backup and recovery

| ID | Test | Expected result |
|---|---|---|
| REC-001 | Create a backup using the documented procedure | Backup completes and is stored securely |
| REC-002 | Restore into an isolated PostgreSQL instance | Database restores successfully |
| REC-003 | Verify notes, entities, facts, and relationships after restore | Data and references remain consistent |
| REC-004 | Verify roles and account statuses after restore | Authorization state is preserved |
| REC-005 | Verify administrative audit events after restore | Audit history is preserved according to policy |
| REC-006 | Restore a corrupted or incomplete backup | Failure is detected and reported |
| REC-007 | Verify model files and configuration recovery requirements | Documented dependencies can be restored |
| REC-008 | Verify restored database access controls | Private data remains protected |

A backup is not considered verified until a restore test has passed.

## 20. End-to-end acceptance scenarios

### E2E-001: Text capture and knowledge extraction

1. Authenticate as `user_a`.
2. Create a text note.
3. Request local extraction.
4. Retrieve the extraction run.
5. Review uncertain proposals.
6. Accept a valid proposal.
7. Retrieve the resulting entity, fact, or relationship.
8. Verify its evidence references the original note.
9. Search for the resulting knowledge.
10. Verify the database contains no unintended duplicates.

**Pass:** the note, extracted knowledge, evidence, and search results are correct and belong to `user_a`.

### E2E-002: Voice capture

1. Authenticate as `user_a`.
2. Submit voice input using the implemented upload mechanism.
3. Transcribe locally.
4. Correct the transcript if necessary.
5. Save the transcript as a voice-originated note.
6. Run extraction.
7. Review and save valid knowledge.
8. Inspect persisted data and temporary files.

**Pass:** the transcript is the canonical note content, extraction uses the correct transcript version, and audio retention follows policy.

### E2E-003: User isolation

1. Create distinct notes and graph records for `user_a` and `user_b`.
2. Search and traverse each graph independently.
3. Attempt direct access to the other user's IDs.
4. Attempt writes referencing the other user's entities.
5. Repeat the private-resource tests as an administrator.

**Pass:** neither regular users nor administrators can access another user's private knowledge through ordinary knowledge endpoints.

### E2E-004: Administrator lifecycle

1. Authenticate as `admin_a`.
2. List permitted account metadata.
3. Promote `user_b` to administrator.
4. Verify the role-change audit event.
5. Verify `user_b` receives administrator privileges according to the documented session policy.
6. Disable `user_b`.
7. Verify access is revoked promptly.
8. Reactivate `user_b` and verify the documented reauthentication behavior.

**Pass:** account changes are authorized, audited, and enforced without exposing private knowledge.

### E2E-005: Last active administrator

1. Ensure exactly one active administrator remains.
2. Attempt to demote that administrator.
3. Attempt to disable that administrator.
4. Repeat through every supported administrative route.
5. Submit concurrent administrative requests designed to remove the final administrators.

**Pass:** at least one active administrator remains, and failed operations do not create false success audit events.

### E2E-006: Failure recovery

1. Start an extraction.
2. Make the local AI runtime unavailable or force a timeout.
3. Verify the run reaches a safe failure state.
4. Restore the runtime.
5. Retry the operation.
6. Verify no duplicate or partial knowledge was persisted.

**Pass:** the system recovers cleanly and remains consistent.

### E2E-007: Backup and restore

1. Create accounts, notes, graph records, evidence, and audit events.
2. Produce a backup.
3. Restore it to an isolated environment.
4. Verify record counts, relationships, ownership, roles, and status.
5. Run authorization and isolation tests against the restored instance.

**Pass:** the restored system preserves data integrity and access-control behavior.

## 21. CI and release gates

Every change must pass the relevant automated checks:

1. Formatting, linting, and static checks.
2. Unit tests.
3. API integration tests.
4. Database integrity and migration tests.
5. RBAC and cross-user isolation tests.
6. Administrative safeguard and audit tests.
7. Extraction validation tests.
8. End-to-end acceptance tests for affected workflows.

Before an MVP release, all of the following are mandatory:

- No known cross-user data leak.
- No user self-promotion to administrator.
- No successful administrative mutation without its required audit event.
- Last-active-administrator protection passes concurrency tests.
- Disabled-account access revocation works as documented.
- AI output is validated before persistence.
- Persisted assertions have valid provenance according to the chosen evidence policy.
- Backup restoration succeeds.
- No unresolved critical or high-severity security defect.

A failed security test blocks release even if ordinary functional tests pass.

## 22. Defect severity

| Severity | Examples | Release policy |
|---|---|---|
| Critical | Cross-user private-data exposure, privilege escalation, credentials exposed | Block release immediately |
| High | Last administrator can be removed, disabled users retain access, audit bypass | Block release |
| Medium | Incorrect extraction, broken review flow, search inconsistency | Fix or explicitly defer with documented impact |
| Low | Minor usability issue, non-critical display inconsistency | May defer |

## 23. Execution order

1. Database migrations and constraints.
2. Authentication and account lifecycle.
3. RBAC and ownership isolation.
4. Administrative safeguards and audit logging.
5. Note CRUD.
6. Extraction validation and evidence.
7. Review workflow.
8. Entity, fact, and relationship lifecycle.
9. Search and graph traversal.
10. Voice transcription integration.
11. Performance and resource limits.
12. Backup and restore.
13. Full end-to-end acceptance.

Run the RBAC and ownership suite early and on every change that affects authentication, account services, resource repositories, or administrative endpoints.

## 24. Definition of done

The MVP is ready when:

- All P0 functional tests pass.
- The two-role RBAC model is enforced server-side.
- Private graph isolation is verified for both roles.
- Administrative account changes are validated and audited.
- The last-active-administrator invariant holds under concurrent requests.
- Disabled accounts and revoked privileges are enforced promptly.
- Text and voice capture work end to end.
- AI output is validated and source evidence is retained.
- Invalid or uncertain proposals follow the review policy.
- Database migrations and integrity constraints pass.
- Performance is measured on the target hardware.
- Backup restoration is verified.
- No critical or high-severity security defects remain.
- The test results and any accepted limitations are documented.
