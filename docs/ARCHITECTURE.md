# ARCHITECTURE.md

## 1. Purpose

This document defines the software architecture for the personal notes-and-memory application.

The system allows users to capture text or voice notes, extract structured knowledge using local AI, review uncertain results, and retrieve information through search and knowledge-graph traversal.

The architecture prioritizes:

- Local AI processing without external AI providers.
- Reliable knowledge storage and source provenance.
- Role-based access control (RBAC) for users and administrators.
- Strict privacy and isolation between users' knowledge graphs.
- A small, maintainable codebase suitable for a home server.

## 2. Architectural Principles

### 2.1 PostgreSQL is the source of truth

PostgreSQL stores canonical application data, including users, roles, notes, entities, facts, relationships, evidence, extraction runs, and review items.

AI models and search mechanisms are not competing sources of truth.

### 2.2 The knowledge graph is a data model

Represent entities, facts, and relationships using relational tables and foreign keys. Use SQL joins and bounded-depth recursive queries for graph traversal.

Do not introduce a dedicated graph database for the MVP.

### 2.3 AI proposes; application logic validates

The local AI extractor produces structured proposals. The application validates output, checks ownership, resolves entities, applies review rules, and persists accepted knowledge.

The model cannot directly write to PostgreSQL or bypass authorization.

### 2.4 Modular monolith

Use one backend application with explicit internal modules. Avoid microservices, a message broker, Redis, and other infrastructure that is not justified by the MVP.

### 2.5 Role-based access control

The backend authorizes requests using the authenticated user's identity and assigned role.

The MVP has two roles:

- `user`: manages their own notes and knowledge graph.
- `admin`: manages application users, roles, and administrative operations.

**Admin privileges do not automatically grant access to private user content.** Data ownership checks remain mandatory for all roles.

### 2.6 Text is the canonical note content

Voice capture follows this pipeline:

**Audio → local transcription → transcript text → extraction → validation → PostgreSQL**

Raw audio is not stored in PostgreSQL. Temporary audio files must follow a documented retention and cleanup policy.

## 3. System Context

<CodeBlock language="mermaid" editable>
flowchart TD
    U[Regular User]
    AD[Administrator]
    M[Flutter Mobile App]
    API[FastAPI Backend]
    RBAC[Authentication and RBAC]
    APP[Application Use Cases]
    PG[(PostgreSQL)]
    TR[Local Transcription Runtime]
    EX[Local Extraction Runtime]

    U --> M
    AD --> M
    M --> API
    API --> RBAC
    RBAC --> APP
    APP --> PG
    APP --> TR
    APP --> EX
    TR --> APP
    EX --> APP
</CodeBlock>

The mobile application presents features appropriate to the user's role. The backend remains the authority for authorization; hiding a button in the client is not a security control.

## 4. RBAC Model

### 4.1 Roles and permissions

| Capability | User | Admin |
|---|---:|---:|
| Create and manage own notes | Yes | Yes, for own data |
| Capture voice and run extraction | Yes | Yes |
| Review own extraction proposals | Yes | Yes |
| Search and traverse own graph | Yes | Yes |
| Access another user's private graph | No | No, by default |
| List and manage user accounts | No | Yes |
| Disable or reactivate accounts | No | Yes |
| Assign or revoke roles | No | Yes |
| View system health and operational status | No | Yes |
| Manage global application configuration | No | Yes |
| Read private content for administration | No | No, unless a separate audited permission is introduced |

An administrator is still a normal application user and may maintain a private knowledge graph. Administrative privileges are additional permissions, not a replacement for ownership checks.

### 4.2 Role assignment

For the MVP, each account has exactly one role: `user` or `admin`.

Store the role in the user's canonical account record. A separate roles and permissions subsystem is unnecessary until the application needs multiple roles, custom permissions, or role inheritance.

Rules:

- New accounts receive the `user` role by default.
- Only an authorized administrator can change another account's role.
- Users cannot change their own role through ordinary profile endpoints.
- The system must prevent unauthorized privilege escalation.
- The system must not allow the last active administrator to be accidentally removed or demoted without a safe replacement path.
- Role changes take effect on subsequent authorization checks. Long-lived tokens must not preserve revoked privileges indefinitely.

Initial administrator provisioning should use a documented, controlled setup process rather than allowing arbitrary public self-registration as an administrator.

### 4.3 Authorization model

Authorization requires two independent checks:

1. **Role permission:** Is the caller allowed to perform this kind of operation?
2. **Resource ownership:** Is the caller allowed to access this particular resource?

For private knowledge resources, both checks are required. Having the `admin` role does not bypass ownership.

Conceptually:

```python
def authorize_resource_access(
    authenticated_user,
    resource,
    required_permission,
):
    require_permission(
        authenticated_user.role,
        required_permission,
    )
    require_owner(
        authenticated_user.id,
        resource.owner_id,
    )
```

This is illustrative pseudocode. Production authorization must be enforced through centralized backend dependencies and application services, not copied independently into every endpoint.

### 4.4 Administrative permissions

Use a centralized permission registry, even if the initial mapping is simple.

Suggested permissions:

- `users.read`
- `users.update`
- `users.disable`
- `roles.assign`
- `system.health.read`
- `system.config.update`

The `user` role receives permissions for its own knowledge resources. The `admin` role additionally receives the administrative permissions above.

These permissions do not include unrestricted access to other users' notes, transcripts, entities, facts, relationships, or evidence.

## 5. High-Level Architecture

<CodeBlock language="mermaid" editable>
flowchart TB
    subgraph Client["Client Layer"]
        UI[Flutter UI]
        STATE[Client State and API Client]
        UI --> STATE
    end

    subgraph Backend["FastAPI Modular Monolith"]
        API[API Routes]
        AUTH[Authentication]
        RBAC[Role Authorization]
        OWN[Ownership and Resource Policies]
        USE[Application Use Cases]
        DOMAIN[Domain Rules and Validation]
        PORTS[Repository and AI Interfaces]

        API --> AUTH
        AUTH --> RBAC
        RBAC --> OWN
        OWN --> USE
        USE --> DOMAIN
        DOMAIN --> PORTS
    end

    subgraph Infra["Infrastructure Adapters"]
        REPO[PostgreSQL Repositories]
        SEARCH[Search and Graph Queries]
        TRANS[Transcription Adapter]
        EXTRACT[Extraction Adapter]
    end

    DB[(PostgreSQL)]
    STT[Local Transcription Runtime]
    LLM[Local Extraction Runtime]

    STATE --> API
    PORTS --> REPO
    PORTS --> SEARCH
    PORTS --> TRANS
    PORTS --> EXTRACT
    REPO --> DB
    SEARCH --> DB
    TRANS --> STT
    EXTRACT --> LLM
</CodeBlock>

The diagram represents logical boundaries within one backend application. It does not require separate deployable services.

## 6. Recommended Technology Stack

| Layer | Technology |
|---|---|
| Mobile | Flutter and Dart |
| Client state | Riverpod |
| HTTP client | Dio |
| Backend | Python and FastAPI |
| Request and response validation | Pydantic |
| Database access | SQLAlchemy |
| Schema migrations | Alembic |
| Canonical database | PostgreSQL |
| Fuzzy text matching | Optional `pg_trgm` |
| Local transcription | A locally benchmarked runtime such as `faster-whisper` |
| Local extraction | Small quantized instruction model |
| Local model runtime | `llama.cpp` or compatible runtime |
| Testing | `pytest`, HTTPX, Flutter test tooling |

The stack should remain small. Select AI models only after measuring quality, latency, and memory usage on the target server.

## 7. Backend Module Structure

```text
backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── routes/
│   │   │   ├── notes.py
│   │   │   ├── knowledge.py
│   │   │   ├── search.py
│   │   │   ├── review.py
│   │   │   ├── auth.py
│   │   │   └── admin.py
│   │   └── dependencies.py
│   ├── application/
│   │   ├── notes.py
│   │   ├── capture.py
│   │   ├── extraction.py
│   │   ├── review.py
│   │   ├── knowledge.py
│   │   ├── search.py
│   │   ├── users.py
│   │   └── authorization.py
│   ├── domain/
│   │   ├── models.py
│   │   ├── rules.py
│   │   └── errors.py
│   ├── ports/
│   │   ├── repositories.py
│   │   ├── transcription.py
│   │   └── extraction.py
│   ├── infrastructure/
│   │   ├── db/
│   │   ├── search/
│   │   └── ai/
│   └── config.py
├── migrations/
├── tests/
└── pyproject.toml
```

Keep authorization rules centralized. Route modules should declare the required permission and invoke application use cases; they should not each implement their own authorization logic.

## 8. Core Workflows

### 8.1 Text and voice capture

Text and voice use the same knowledge pipeline after text is available.

1. Authenticate the caller.
2. Validate the request and derive the user's identity.
3. Save the note or transcribe audio locally.
4. Run local structured extraction.
5. Validate schema, evidence, ownership, and entity references.
6. Create review items or persist accepted knowledge according to the review policy.
7. Return status and results to the client.

The original note is preserved even if extraction fails. The model cannot bypass authorization or perform privileged operations.

### 8.2 Search and graph traversal

1. Authenticate the caller.
2. Check the required permission.
3. scope database queries to the authenticated user's graph.
4. Run PostgreSQL full-text search or bounded graph traversal.
5. Return results and relevant provenance.

An administrator using normal search receives results from their own graph, not all users' graphs.

### 8.3 Administrative user management

1. Authenticate the caller.
2. Verify the required administrative permission.
3. Validate the target account and requested operation.
4. Apply the change through the user-management application service.
5. Record an audit event for role changes, account disabling, and other security-sensitive operations.
6. Invalidate or refresh affected authentication state where necessary.

Administrative endpoints must never infer permission from a client-supplied role field.

## 9. Data Model Changes for RBAC

The detailed schema belongs in `DATA_MODEL.md`. At minimum, the `users` table needs a role field.

Example:

```text
users
-----
id
email_or_username
password_hash_or_auth_identity
role                 -- user | admin
status               -- active | disabled
created_at
updated_at
```

The exact authentication fields depend on the chosen authentication design.

### Data ownership

Every user-owned resource must have a reliable ownership path:

- Notes belong to a user.
- Entities belong to a user.
- Facts and relationships reference entities belonging to the same user.
- Evidence references notes belonging to the same user.
- Extraction runs and review items are scoped to their source note and owner.

Enforce ownership in repository queries and application services. Use database constraints where practical to prevent cross-user references.

Do not rely on the role field to establish resource ownership.

## 10. Authentication and Authorization

### 10.1 Authentication

Protected endpoints require a verified authenticated identity. A bearer-token-compatible interface is suitable, with the final mechanism documented separately.

The authentication layer resolves the current account and its current status and role.

### 10.2 Authorization dependencies

Use reusable backend dependencies or equivalent application policies for:

- `require_authenticated_user`
- `require_permission`
- `require_resource_owner`

The names are illustrative. The goal is a single, testable implementation of permission checks.

### 10.3 Disabled accounts

Disabled accounts must not access protected application resources. Administrative actions affecting account status must be checked against the current account state.

### 10.4 Role freshness

Do not trust a role claim in a long-lived token indefinitely. Use a server-side role lookup or a token/session revocation strategy that ensures role changes and account disabling take effect promptly.

## 11. Search and Graph Traversal

Use PostgreSQL full-text search and optional `pg_trgm`. Use relational joins and bounded recursive SQL for graph exploration.

Requirements:

- Every query is scoped to the authenticated user's data.
- Graph traversal has a maximum depth and result limit.
- Cycles cannot cause unbounded traversal.
- Deleted or inactive records are excluded according to lifecycle rules.
- Administrative status does not widen search scope.

A cross-user administrative analytics feature is not required for the MVP. If added later, it should expose aggregate operational metrics rather than private note content by default.

## 12. API Design Boundaries

The API is versioned under `/api/v1`.

User-facing resources include:

- `/notes`
- `/transcriptions`
- `/extractions`
- `/review-items`
- `/entities`
- `/facts`
- `/relationships`
- `/search`
- `/graph`

Administrative resources include:

- `/admin/users`
- `/admin/users/{user_id}`
- `/admin/users/{user_id}/role`
- `/admin/users/{user_id}/status`
- `/admin/audit-events`
- `/admin/system`

Administrative routes must require the appropriate permission. A route being under `/admin` is not itself an authorization mechanism.

The exact HTTP methods, request schemas, responses, and status codes belong in `API_SPEC.md`.

## 13. Mobile Client Architecture

Organize the Flutter application by feature:

```text
mobile/
├── lib/
│   ├── app/
│   ├── core/
│   │   ├── api/
│   │   ├── auth/
│   │   └── errors/
│   └── features/
│       ├── notes/
│       ├── voice_capture/
│       ├── review/
│       ├── search/
│       ├── knowledge_graph/
│       └── admin/
└── test/
```

The client may hide administrative screens from regular users based on the authenticated account's permissions. However, every administrative operation must still be authorized by the backend.

The backend remains authoritative for identity, roles, ownership, validation, and persistence.

## 14. Security and Privacy

Minimum requirements:

- Authentication is required for private resources.
- Role checks are enforced server-side.
- Ownership checks apply to all user-owned data, including for administrators.
- Users cannot assign themselves roles or change their account status through ordinary endpoints.
- Role changes and account disabling generate audit events.
- Passwords, tokens, note contents, transcripts, and secrets are not unnecessarily logged.
- AI-generated output cannot bypass authorization.
- Raw audio is not stored in PostgreSQL.
- Local AI processing does not transmit personal content to external providers.
- The server remains restricted to the intended home-network environment.

**Administrative access to private content is denied by default.** If a future support feature requires content access, introduce a separate narrowly scoped permission, an explicit reason, and an audit trail rather than silently granting all administrators access.

## 15. Error Handling and Observability

Use structured logs with request and operation identifiers.

Log operational metadata such as request ID, operation type, duration, status, and error category. Do not log sensitive note content or credentials by default.

Authorization failures should return safe, consistent errors. Avoid revealing whether another user's private resource exists.

Audit events should capture at least:

- Actor account ID.
- Action.
- Target account or resource ID, where applicable.
- Timestamp.
- Outcome.
- Reason for security-sensitive changes, where required.

Audit events must not contain private note text. Regular users must not be able to modify or delete administrative audit records through the public API.

## 16. Deployment Architecture

Deploy the MVP on one home server:

```text
Home Server
├── FastAPI backend
├── PostgreSQL
├── Local transcription runtime
├── Local extraction runtime
├── Local model files
└── Controlled temporary storage

Mobile Device
└── Flutter client
```

Docker Compose is optional. A single-host deployment is sufficient.

Deployment documentation must cover initial administrator provisioning, authentication configuration, migrations, network restrictions, backup and restore, model installation, and temporary-audio cleanup.

Do not expose the server to the public internet for the MVP.

## 17. Testing Strategy

Testing must cover both role permissions and data ownership.

### Role authorization tests

- A regular user cannot access administrative endpoints.
- An administrator can manage user accounts and roles.
- A regular user cannot change their own role.
- An administrator cannot grant administrative privileges through an unauthorized route.
- Disabling an account prevents subsequent protected access.
- Role revocation takes effect according to the documented token/session policy.
- The last active administrator cannot be accidentally removed without a safe replacement path.

### Ownership tests

- A user cannot read, modify, or delete another user's notes.
- A user cannot link another user's entity to a fact or relationship.
- An administrator cannot read another user's private graph through ordinary endpoints.
- Search and graph traversal never return another user's data.
- Extraction and review endpoints enforce the ownership of the source note.
- Forged user IDs and model-generated references cannot bypass ownership checks.

### Other test categories

- Unit tests for domain rules and permission mapping.
- Integration tests for repositories and database constraints.
- AI evaluation tests for extraction quality and evidence grounding.
- End-to-end tests for text, voice, review, and retrieval workflows.
- Operational tests for local-only processing, backup, restore, and resource limits.

See `TEST_PLAN.md` for the detailed test cases and release gates.

## 18. Explicitly Deferred

The MVP does not include:

- Custom roles or a user-configurable permission editor.
- Organization or team-based tenancy.
- Shared knowledge graphs.
- Administrative access to private content by default.
- Complex approval workflows for role changes.
- Distributed services or Kubernetes.
- A separate graph database, search engine, or vector database.
- External AI providers.
- Public-internet deployment.

These features should be introduced only when justified by actual requirements.

## 19. Architecture Decision Summary

| Decision | MVP choice | Reason |
|---|---|---|
| Canonical storage | PostgreSQL | Reliable persistence and relational integrity |
| Backend architecture | Modular monolith | Simple deployment and maintenance |
| Graph representation | Relational tables | Sufficient for bounded personal knowledge graphs |
| Access control | RBAC with `user` and `admin` | Clear separation of ordinary and administrative capabilities |
| Resource privacy | Ownership checks for all roles | Prevents administrator privileges from automatically exposing private content |
| Role storage | Role field on `users` | Smallest maintainable model for two fixed roles |
| Authorization enforcement | Central backend policies | Consistent and testable access decisions |
| Administrative auditing | Audit sensitive account and role changes | Traceability for privileged actions |
| AI processing | Local transcription and extraction | Privacy and no external AI-provider costs |
| Search | PostgreSQL full-text search | Avoids unnecessary infrastructure |
| Deployment | Single home server | Low operational cost |

## 20. Definition of Done

The architecture is implemented when:

1. Text and voice capture share a text-based knowledge pipeline.
2. AI generates validated proposals without direct database writes.
3. PostgreSQL remains the single source of truth.
4. Accepted knowledge retains verifiable source evidence.
5. The application supports `user` and `admin` roles.
6. Administrative permissions are enforced centrally by the backend.
7. Resource ownership is enforced independently of role.
8. Administrators cannot access private user content by default.
9. Role assignment, account disabling, and other privileged changes are auditable.
10. Role changes and disabled-account status are enforced promptly.
11. Search and graph traversal remain user-scoped.
12. Local AI processing works without external AI-provider calls.
13. Backup, restore, and recovery procedures are documented and tested.