# API_SPEC.md

## 1. Purpose

This document defines the REST API contract for the personal knowledge management application.

The API supports:

- User authentication and account management.
- Text and voice note capture.
- Local AI transcription and structured knowledge extraction.
- Entities, facts, relationships, evidence, and review workflows.
- Search and bounded-depth graph traversal.
- Role-based access control (RBAC) for `user` and `admin`.
- Administrative account management, operational monitoring, and configuration.
- Private data isolation between users.

The API is implemented as part of a modular monolith using FastAPI, PostgreSQL, and Pydantic.

## 2. Core API principles

1. PostgreSQL is the canonical data store.
2. All knowledge content persisted from text or voice capture is text-based. Voice is transcribed before extraction.
3. AI-generated knowledge must be validated before persistence.
4. Every private resource belongs to a specific user.
5. Authorization checks both the caller's role and resource ownership.
6. Administrative privileges do not grant automatic access to private user content.
7. All AI processing must use local services; the application must not send private content to external AI providers.
8. API responses must not expose passwords, authentication secrets, internal stack traces, or model reasoning.
9. Administrative changes to roles, account status, and global configuration must be audited.

## 3. API conventions

### 3.1 Base URL

All application endpoints use:

`/api/v1`

### 3.2 Request and response formats

- Content type: `application/json`
- Field naming: `snake_case`
- IDs: UUID
- Timestamps: ISO 8601 in UTC
- Pagination: `limit` and `cursor` where applicable
- Authentication: bearer-token-compatible interface; the exact session/token mechanism is finalized during implementation.

### 3.3 Common error response

All errors use a consistent structure:

    {
      "error": {
        "code": "RESOURCE_NOT_FOUND",
        "message": "The requested resource was not found",
        "details": {}
      }
    }

Common status codes:

| Status | Meaning |
|---|---|
| `200` | Successful request |
| `201` | Resource created |
| `202` | Processing accepted |
| `204` | Successful operation without a response body |
| `400` | Invalid request |
| `401` | Missing, invalid, or expired authentication |
| `403` | Authenticated caller lacks permission |
| `404` | Resource not found or intentionally concealed due to access policy |
| `409` | State conflict, duplicate operation, or concurrency conflict |
| `422` | Request validation failed |
| `429` | Rate limit exceeded |
| `500` | Unexpected server error |
| `503` | Required local service unavailable |

The API may return `404` rather than `403` for private resources to avoid revealing their existence. This behavior must be consistent across resource endpoints.

## 4. Authentication and account identity

### 4.1 Authentication endpoints

| Method | Endpoint | Purpose | Access |
|---|---|---|---|
| `POST` | `/auth/login` | Authenticate an account | Public |
| `POST` | `/auth/logout` | End the current session | Authenticated |
| `POST` | `/auth/refresh` | Refresh credentials if refresh tokens are implemented | Valid refresh credential |
| `GET` | `/auth/me` | Get the current account and effective role | Authenticated |
| `PATCH` | `/auth/me` | Update permitted self-service profile fields | Authenticated |

`GET /auth/me` response:

    {
      "id": "uuid",
      "username": "alice",
      "role": "user",
      "status": "active",
      "created_at": "2026-10-11T02:00:00Z"
    }

The `role` field is read-only through self-service endpoints. Users cannot promote themselves to `admin`, change their account status, or edit protected authorization fields.

### 4.2 Account status

Supported account statuses:

- `active`: may authenticate and use permitted endpoints.
- `disabled`: cannot establish a new session or continue accessing protected endpoints.

The server must enforce account status on authenticated requests. Disabling an account or revoking its privileges must take effect promptly, rather than relying solely on an unexpired token containing stale role claims.

### 4.3 Initial administrator provisioning

The first administrator must be created through a controlled setup process, such as a one-time setup command or protected installation procedure.

Public registration and ordinary user endpoints must never grant administrator privileges.

Whether ordinary users can register themselves or must be created by an administrator is an implementation decision to finalize before exposing account creation.

## 5. RBAC and authorization model

### 5.1 Roles

Exactly two application roles are supported in the MVP:

- `user`
- `admin`

Custom roles, user groups, and team-level permissions are out of scope.

### 5.2 Permission matrix

| Capability | User | Admin |
|---|---|---|
| Manage own notes and knowledge graph | Yes | Yes |
| Read or modify another user's private graph | No | No, by default |
| View and manage user accounts | No | Yes |
| Assign or revoke administrator roles | No | Yes |
| Disable or reactivate accounts | No | Yes |
| View operational health | Limited public health only | Yes |
| Change permitted global configuration | No | Yes |
| View administrative audit events | No | Yes |
| Change own role | No | No |

An administrator's ordinary knowledge endpoints operate only on the administrator's own private data, just like a regular user.

### 5.3 Authorization rules

Every protected request must pass the following checks:

1. **Authentication:** identify the caller.
2. **Account status:** reject disabled accounts.
3. **Permission:** verify the caller's current role permits the operation.
4. **Ownership:** for private resources, verify that the resource belongs to the caller.
5. **Validation:** verify request fields and allowed state transitions.
6. **Audit:** record applicable security-sensitive administrative actions.

Role authorization and ownership authorization are independent. Being an administrator does not bypass ownership checks on private knowledge resources.

Ownership must be enforced in the application service and/or database query. The API must not rely on client-supplied `user_id` values as proof of ownership.

### 5.4 Suggested permission mapping

| Permission | Purpose |
|---|---|
| `users.read` | List and view account metadata |
| `users.update` | Update permitted account metadata |
| `users.disable` | Disable or reactivate accounts |
| `roles.assign` | Assign or revoke administrator privileges |
| `system.health.read` | Read operational status |
| `system.config.update` | Change explicitly permitted system configuration |
| `audit.read` | Read administrative audit events |

These permissions are mapped centrally to the two fixed roles. A separate configurable role-permission database is not required for the MVP.

## 6. Common knowledge resource schemas

### 6.1 Note

    {
      "id": "uuid",
      "content": "Alice works at Acme.",
      "capture_type": "text",
      "status": "active",
      "created_at": "2026-10-11T02:00:00Z",
      "updated_at": "2026-10-11T02:00:00Z"
    }

`capture_type` is `text` or `voice`. For voice notes, `content` contains the transcript. Raw audio is not stored in PostgreSQL.

### 6.2 Entity

    {
      "id": "uuid",
      "canonical_name": "Alice",
      "entity_type": "person",
      "description": null,
      "aliases": [],
      "status": "active",
      "created_at": "2026-10-11T02:00:00Z",
      "updated_at": "2026-10-11T02:00:00Z"
    }

### 6.3 Fact

    {
      "id": "uuid",
      "subject_entity_id": "uuid",
      "predicate": "works_at",
      "object_entity_id": "uuid",
      "value_text": null,
      "value_type": "entity",
      "qualifiers": {},
      "assertion_type": "explicit",
      "confidence": 0.98,
      "valid_from": null,
      "valid_to": null,
      "created_at": "2026-10-11T02:00:00Z",
      "updated_at": "2026-10-11T02:00:00Z"
    }

A fact references either an entity-valued object or a literal value, according to `value_type`. It must not contain both.

### 6.4 Relationship

    {
      "id": "uuid",
      "source_entity_id": "uuid",
      "target_entity_id": "uuid",
      "predicate": "works_at",
      "qualifiers": {},
      "assertion_type": "explicit",
      "confidence": 0.98,
      "valid_from": null,
      "valid_to": null,
      "created_at": "2026-10-11T02:00:00Z",
      "updated_at": "2026-10-11T02:00:00Z"
    }

Use facts and relationships according to the canonical data model. Do not persist the same assertion twice merely because it can be represented in both structures.

### 6.5 Evidence

    {
      "id": "uuid",
      "note_id": "uuid",
      "start_offset": 0,
      "end_offset": 21,
      "quoted_text": "Alice works at Acme.",
      "created_at": "2026-10-11T02:00:00Z"
    }

Evidence links extracted knowledge to the source note. Evidence offsets must refer to the stored transcript or text using one documented offset convention.

## 7. Notes and voice capture

All note endpoints require authentication and operate only on the caller's notes.

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/notes` | Create a text note |
| `GET` | `/notes` | List the caller's notes |
| `GET` | `/notes/{note_id}` | Retrieve a note |
| `PATCH` | `/notes/{note_id}` | Update note content or permitted metadata |
| `DELETE` | `/notes/{note_id}` | Delete or soft-delete a note |
| `POST` | `/notes/{note_id}/transcribe` | Transcribe an eligible voice capture if audio is available temporarily |
| `POST` | `/notes/{note_id}/extract` | Start or request knowledge extraction |
| `GET` | `/notes/{note_id}/evidence` | List evidence associated with the note |

### 7.1 Create a text note

`POST /notes`

Request:

    {
      "content": "Alice works at Acme.",
      "idempotency_key": "client-generated-key"
    }

Response: `201 Created`

The server derives the owner from the authenticated identity. The request must not accept an arbitrary owner ID.

### 7.2 Voice capture

Voice capture follows this sequence:

1. The client records audio.
2. The audio is sent to the local transcription service through an upload mechanism defined during implementation.
3. The server transcribes the audio.
4. The client may correct the transcript before extraction.
5. The transcript is saved as note content.
6. The same extraction pipeline used for text notes processes the transcript.

If temporary audio upload is implemented, it must be size-limited, authenticated, and deleted according to the documented retention policy. Raw audio must not be persisted in PostgreSQL.

The exact upload transport and temporary-audio retention policy remain implementation decisions.

## 8. Knowledge extraction and review

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/notes/{note_id}/extract` | Request extraction |
| `GET` | `/extraction-runs/{run_id}` | Retrieve extraction status |
| `GET` | `/notes/{note_id}/proposals` | List pending proposals for a note |
| `GET` | `/review-items` | List the caller's pending review items |
| `GET` | `/review-items/{review_id}` | Retrieve a review item |
| `POST` | `/review-items/{review_id}/accept` | Accept a proposal |
| `POST` | `/review-items/{review_id}/reject` | Reject a proposal |
| `PATCH` | `/review-items/{review_id}` | Edit a proposal before acceptance |

### 8.1 Extraction request

`POST /notes/{note_id}/extract`

Request:

    {
      "force": false
    }

Response: `202 Accepted`

    {
      "run_id": "uuid",
      "status": "queued"
    }

The run status may be `queued`, `running`, `succeeded`, or `failed`.

Repeated requests must not create duplicate knowledge unintentionally. The service should use idempotency and source-version checks to avoid applying stale extraction results after a note changes.

### 8.2 Extraction output

The extraction service may propose:

- Entity mentions and candidate entities.
- Facts and typed relationships.
- Evidence spans from the source text.
- Explicit versus inferred assertions.
- Confidence values and validation issues.

The API must validate model output against a schema. Invalid or uncertain proposals must be rejected or routed for review rather than silently persisted as confirmed knowledge.

An extracted action-like phrase must not automatically trigger a destructive or external action. The MVP does not provide an autonomous command-execution API.

### 8.3 Review operations

Acceptance must revalidate the proposal, verify ownership, and apply the change transactionally.

A review item may transition from `pending` to `accepted` or `rejected`. Repeated acceptance must not create duplicate facts, relationships, or entities.

Editing a proposal must not rewrite the original source note or erase its provenance.

## 9. Entities, facts, relationships, and graph access

All endpoints in this section require authentication and enforce ownership.

### 9.1 Entities

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/entities` | Create an entity |
| `GET` | `/entities` | List or search the caller's entities |
| `GET` | `/entities/{entity_id}` | Retrieve an entity |
| `PATCH` | `/entities/{entity_id}` | Update an entity |
| `DELETE` | `/entities/{entity_id}` | Delete or archive an entity |

### 9.2 Facts

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/facts` | Create a fact |
| `GET` | `/facts` | List facts with supported filters |
| `GET` | `/facts/{fact_id}` | Retrieve a fact |
| `PATCH` | `/facts/{fact_id}` | Update a fact |
| `DELETE` | `/facts/{fact_id}` | Delete or supersede a fact |

### 9.3 Relationships

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/relationships` | Create a relationship |
| `GET` | `/relationships` | List relationships |
| `GET` | `/relationships/{relationship_id}` | Retrieve a relationship |
| `PATCH` | `/relationships/{relationship_id}` | Update a relationship |
| `DELETE` | `/relationships/{relationship_id}` | Delete or supersede a relationship |

### 9.4 Graph traversal

`GET /graph/neighborhood`

Query parameters:

- `entity_id` — required starting entity.
- `depth` — bounded traversal depth.
- `relationship_types` — optional predicate filter.
- `limit` — maximum results.

Example:

`GET /graph/neighborhood?entity_id={uuid}&depth=2&limit=50`

The server must enforce a maximum depth and result limit. Every returned node and edge must belong to the caller's private graph.

Graph traversal must not reveal entities or relationships owned by other users, even when IDs are guessed or supplied directly.

## 10. Search

`GET /search`

Supported parameters:

- `q` — required query text.
- `types` — optional entity, fact, relationship, or note filters.
- `limit` — maximum number of results.
- `cursor` — optional pagination cursor.

Example:

`GET /search?q=Alice&types=entity,fact&limit=20`

Search uses PostgreSQL full-text search and, where appropriate, trigram matching. Results are scoped to the authenticated user's private data.

The MVP does not require a vector database or external semantic search provider.

## 11. Administrative API

Every endpoint in this section requires an authenticated, active administrator with the corresponding permission. Admin routes manage application operations, not other users' private knowledge content.

### 11.1 Account management

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/admin/users` | List account metadata |
| `POST` | `/admin/users` | Create a regular user account, if admin-managed provisioning is enabled |
| `GET` | `/admin/users/{user_id}` | Retrieve account metadata |
| `PATCH` | `/admin/users/{user_id}` | Update permitted account metadata |
| `PUT` | `/admin/users/{user_id}/role` | Assign or change a role |
| `PUT` | `/admin/users/{user_id}/status` | Disable or reactivate an account |

The account list and account detail responses must not include private notes, graph data, passwords, password hashes, authentication tokens, or model outputs.

Example role request:

`PUT /admin/users/{user_id}/role`

    {
      "role": "admin",
      "reason": "Authorized administrator assignment"
    }

Allowed roles: `user`, `admin`.

Example status request:

`PUT /admin/users/{user_id}/status`

    {
      "status": "disabled",
      "reason": "Account access revoked"
    }

Allowed statuses: `active`, `disabled`.

A role or status update must be authorized, validated, committed transactionally, and audited.

### 11.2 Account-management safeguards

The implementation must enforce the following rules:

- Users cannot change their own role through self-service APIs.
- Only administrators can assign or revoke administrator privileges.
- A disabled account cannot continue using protected endpoints.
- The last active administrator cannot be demoted or disabled unless another active administrator is established within the same safe administrative workflow.
- Concurrent role or status changes must not bypass these safeguards.
- A failed administrative operation must not be recorded as a successful change.
- Account provisioning must never permit self-assigned administrator privileges.

For the last-active-administrator check, the implementation must prevent race conditions, not just perform an unprotected count followed by an update.

### 11.3 Administrative audit events

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/admin/audit-events` | Search and paginate administrative audit events |
| `GET` | `/admin/audit-events/{event_id}` | Retrieve one audit event |

Audit records should contain:

    {
      "id": "uuid",
      "actor_user_id": "uuid",
      "action": "user.role_changed",
      "target_user_id": "uuid",
      "outcome": "success",
      "reason": "Authorized administrator assignment",
      "created_at": "2026-10-11T02:00:00Z"
    }

Audit events must be append-only through the normal application API. They must not contain passwords, tokens, note contents, transcripts, or private graph payloads.

Audit at least:

- Role assignments and revocations.
- Account disable and reactivation operations.
- Account creation and security-sensitive account changes.
- Global configuration changes.
- Failed privileged operations where recording them is operationally useful.

Access to audit events requires the `audit.read` permission.

### 11.4 Operational health

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health/live` | Check whether the API process is alive |
| `GET` | `/health/ready` | Check whether required dependencies are ready |
| `GET` | `/admin/system/health` | View detailed operational status |

Liveness and readiness endpoints must reveal only the minimum information necessary and must not expose secrets, internal paths, connection strings, or private user content.

Detailed operational status requires administrator access.

### 11.5 Global configuration

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/admin/system/config` | Read permitted application configuration |
| `PATCH` | `/admin/system/config` | Update explicitly allowlisted settings |

Only documented, safe configuration fields may be changed through the API. Secrets, arbitrary file paths, executable commands, database credentials, and unrestricted model-runtime parameters must not be exposed through generic configuration updates.

Configuration changes must be validated, audited, and applied according to their documented restart or reload requirements.

## 12. Ownership and data isolation

Every private data table and corresponding application service must preserve user ownership.

The server must derive the current user from the authenticated identity, not from request-body ownership fields.

For every private resource request, tests must cover:

- The resource belongs to the caller.
- The resource belongs to another regular user.
- The resource belongs to an administrator.
- The caller is an administrator attempting to access another user's private resource.
- The caller's account has been disabled.
- The referenced resource does not exist.

Administrative account management is the explicit exception to ordinary ownership checks for account metadata only. It does not grant permission to read private knowledge resources.

## 13. Concurrency, idempotency, and state changes

- Create operations should support an idempotency key where retries could create duplicates.
- Updates should support optimistic concurrency control where stale edits could overwrite newer data.
- Review acceptance must be transactional.
- Extraction results must be associated with the source note version they processed.
- Role changes and account status changes must be transactional and promptly enforced.
- Last-active-administrator protection must remain correct under concurrent requests.
- Delete behavior must follow the canonical data model's soft-delete, history, and evidence-retention rules.

## 14. Security requirements

1. Require authentication for all private and administrative endpoints.
2. Centralize authorization logic rather than implementing inconsistent route-specific checks.
3. Validate all inputs and enforce request-size limits.
4. Rate-limit authentication and sensitive administrative operations.
5. Store passwords using an established password-hashing algorithm if password authentication is selected.
6. Protect tokens and sessions against unauthorized reuse.
7. Never trust a client-provided role or owner ID.
8. Avoid leaking resource existence through cross-user access attempts.
9. Audit role and account-status changes.
10. Keep private content out of application logs and administrative audit payloads.
11. Ensure database migrations and backup files are protected.
12. Keep AI inference local and prevent private content from being sent to external providers.
13. Validate model-generated output before writing to the database.
14. Do not expose arbitrary system commands or unrestricted configuration through administrative endpoints.

## 15. API testing requirements

The automated test suite must include:

### Authentication
- Missing, invalid, and expired credentials are rejected.
- Disabled accounts cannot access protected endpoints.
- Role changes are enforced promptly.
- Logout and token/session revocation behave according to the chosen authentication mechanism.

### User authorization
- A user can manage their own knowledge resources.
- A user cannot access another user's notes, entities, facts, relationships, evidence, or review items.
- A user cannot access administrative endpoints.
- A user cannot assign themselves the administrator role.

### Administrator authorization
- An administrator can manage account metadata, roles, and account status.
- An administrator cannot read another user's private graph through normal knowledge endpoints.
- Only administrators can access detailed operational health, configuration, and audit events.
- Invalid role and status values are rejected.
- The last active administrator cannot be accidentally demoted or disabled.
- Concurrent administrative requests cannot bypass that safeguard.
- Successful role, status, and configuration changes generate appropriate audit records.

### Data integrity
- Evidence references valid source text.
- Extraction output is validated before persistence.
- Repeated requests do not create unintended duplicates.
- Review operations are transactional.
- Search and graph traversal remain scoped to the caller's data.

## 16. Implementation priorities

### P0 — Required for the MVP

- Authentication and current-account endpoint.
- Two fixed roles: `user` and `admin`.
- Centralized role authorization and ownership enforcement.
- User-scoped notes, knowledge, search, and graph APIs.
- Account role and status fields.
- Controlled initial administrator provisioning.
- Administrator account-management endpoints.
- Last-active-administrator safeguards.
- Administrative audit events.
- Local transcription and structured extraction workflows.
- Input validation, error handling, and isolation tests.

### P1 — Implement where needed

- Self-service account registration.
- Refresh-token support, if required by the chosen session design.
- Advanced audit filtering and retention.
- Additional operational configuration controls.
- More sophisticated optimistic concurrency and idempotency support.

### Out of scope

- Custom roles and a configurable permission-management interface.
- Shared graphs or collaborative workspaces.
- Administrator browsing of private user content by default.
- Autonomous execution of model-generated commands.
- External AI providers.
- Vector database integration.

## 17. Open decisions

Resolve these before implementation reaches the relevant feature:

1. **Authentication:** username/password, session cookies, or bearer tokens; select the mechanism based on the mobile-first client and home-network deployment.
2. **Account provisioning:** public self-registration, administrator-created accounts, or a combination.
3. **Role freshness:** server-side role lookup, session invalidation, or another mechanism that ensures prompt revocation.
4. **Voice upload:** exact transport and temporary audio retention policy.
5. **Deletion:** retention and cascading behavior for notes, evidence, facts, relationships, and audit records.
6. **Audit retention:** duration and backup requirements.
7. **Configuration scope:** which safe operational settings administrators may change through the API.

These decisions must be documented before their implementation. They must not weaken the ownership or administrator-isolation requirements defined above.

## 18. Definition of done

The API specification is considered implemented when:

- All documented P0 endpoints and schemas are implemented.
- The two-role authorization model is enforced server-side.
- Private resources are isolated by ownership for both roles.
- Administrative account operations are protected and audited.
- Last-active-administrator safeguards are concurrency-safe.
- Disabled accounts and revoked privileges are enforced promptly.
- Voice input is transcribed before knowledge extraction and persistence.
- AI output is validated and linked to source evidence.
- Automated tests cover successful, invalid, unauthorized, and cross-user requests.
- API documentation matches actual request and response schemas.
- No private knowledge content is exposed through administrative account or audit endpoints.
