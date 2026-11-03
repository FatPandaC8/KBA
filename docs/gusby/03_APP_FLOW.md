# Gusby: Application Flow & Screen Specification (APP_FLOW.md)
**Version:** 1.1 (Extended via CR-001)  
**Status:** Approved & Binding  
**Source of Truth Precedence:** 00_PRODUCT_BRIEF.md > 03_APP_FLOW.md > DECISIONS.md > Prompt Defaults

---

## 1. Application Routes & Navigation Structure `[Decided]`

```
/ (Root)
 ├── /auth/login         (Sign In screen)
 ├── /auth/signup        (Sign Up screen)
 ├── [Authenticated User Shell]
 │    ├── /              (Knowledge Space - central graph canvas)
 │    ├── /add           (Add Knowledge - ingestion workspace)
 │    ├── /documents     (Documents - repository list & drawer)
 │    └── /settings      (Settings - minimal preferences)
 └── [Authenticated Admin Area - /admin/*] (Visible only to is_admin=true)
      ├── /admin              (Overview - headline stats, quick health, active alerts)
      ├── /admin/pipeline     (Pipeline & Job Queue - queues, stuck jobs, stage latencies, retries)
      ├── /admin/ai           (AI Component - health badge & reason, charts, quality signals, gate controls, probe)
      ├── /admin/users        (User Management - list, search, suspend/unsuspend, delete, reset limits)
      ├── /admin/documents    (Document Management - list, failure drill-down, delete with cascade retraction, reprocess)
      ├── /admin/graph        (Graph Data Admin - user selector, concepts, propositions, topics, conflict resolution)
      └── /admin/audit        (Admin Audit Log - append-only event stream, before/after JSONB inspector)
```

The persistent layout contains a compact icon-only left navigation bar:
- **Logo / Icon**: Gusby circular mark (Home link).
- **Space**: Graph icon (active by default).
- **Add**: Plus icon.
- **Documents**: Folder / Library icon.
- **Admin**: Shield / Gauge icon (**Rendered ONLY if `user.is_admin === true`**).
- **Settings**: Cog icon (bottom pinned).
- **User Avatar / Sign Out**: Quick indicator.

---

## 2. Standard Screen Specifications `[Decided]`

### Screen 1: Auth (Sign In & Sign Up)
- **Routes**: `/auth/login`, `/auth/signup`
- **Visuals**: Centered minimal form on pure white canvas; typography-driven; hairline borders.
- **States**: `Default`, `Submitting`, `Error` (`"Invalid email or password"`).
- **Acceptance Criteria**: Sets `gusby_session` cookie; non-admins never see admin hints; failed login never enumerates email existence.

### Screen 2: Knowledge Space (Central Interactive Canvas)
- **Route**: `/`
- **Visuals**: Fullscreen pure white canvas displaying interactive Topic Islands and Concepts; floating search bar; floating zoom/LOD controls; collapsible right detail drawer.
- **Review State**: Pill toggle `[Needs Review]` highlights pending proposals/conflicts in terracotta badge.

### Screen 3: Add Knowledge (Ingestion Workspace)
- **Route**: `/add`
- **Tabs**: Text, URL, File. Live status polling, duplicate detection.

### Screen 4: Documents (Document Repository)
- **Route**: `/documents`
- **Elements**: Filterable list, status badges, slide-over drawer showing raw text and chunk boundaries.

### Screen 5: Settings
- **Route**: `/settings`
- **Elements**: Account info, password change, token quota indicator.

---

## 3. Admin Area Screen Specifications `[Decided - CR-001]`

### Screen A1: Admin Overview (`/admin`)
- **Visuals**: Clean card-based overview using hairline borders and generous whitespace.
- **Sections**:
  - **Headline Cards**:
    - AI Component Health: Badge (`healthy`, `degraded`, `down`, `paused`), active model name, rolling error rate.
    - Pipeline Throughput: Active jobs, queued jobs, stuck jobs count, 24h failure rate.
    - User Activity: Total active users, new signups (24h/7d), today's total AI tokens consumed.
    - Graph Scale: Total concepts, canonical propositions, active conflicts across all users.
  - **Quick Action Bar**: Run AI Probe, View Stuck Jobs, View Recent Audit Events.
- **States**: `Loading` (skeleton cards), `Error` (inline retry banner).

---

### Screen A2: Pipeline & Job Monitoring (`/admin/pipeline`)
- **Visuals**: Two-column layout: Queue Health Metrics on top; Job Table below.
- **Elements**:
  - **Queue Breakdown**: Counts by stage (`queued`, `running`, `waiting_for_ai`, `done`, `failed`).
  - **Stuck Jobs Section**: Highlights jobs running $> 5$ minutes or with expired heartbeats, with `"Force Release / Re-queue"` action.
  - **Stage Latency & Failure Rate**: Median and p95 latency for `chunking`, `extracting`, `resolving`, `integrating`.
  - **Job Table**: Filterable by stage, search by Document ID or User ID. Columns: Job ID, Document Title, User Email, Stage, Attempts, Last Error, Created, Updated.
  - **Operational Control**: `"Retry Job"` button on failed jobs. Opens confirmation: verifies idempotent re-execution from last valid stage.

---

### Screen A3: AI Component Monitoring & Control (`/admin/ai`)
- **Visuals**: Multi-section operational dashboard for monitoring and controlling the current Groq API provider (and future custom model).
- **Sections**:
  1. **Provider Identity & Config Card**:
     - Kind (`groq`), Model (`openai/gpt-oss-120b`), Version, Capabilities (`json_mode`, etc.).
     - API Key Status: Boolean `"Configured"` badge (Never displays or leaks raw key).
  2. **Health Badge & Reason**:
     - Large visual badge (`healthy` green, `degraded` amber, `down` red, `paused` slate).
     - Explicit textual derivation reason (e.g. `"Healthy: 0% error rate over last 50 calls; last probe succeeded in 320ms"`).
  3. **Performance Metrics (Selectable Window: 1h, 24h, 7d)**:
     - Total Calls, Token Volume (Input / Output).
     - Latency: Median and p95 (inline SVG sparkline).
     - Error Breakdown: Rate limited (429), Timeout, Server Error (5xx), Invalid JSON, Schema Validation Failure, Budget Exceeded.
     - Last Success Time & Last Failure Time with error reason.
  4. **Rate Limit & Budget State**:
     - Remaining requests/tokens (if reported by provider headers), recent 429 count, users exhausting budget.
  5. **Output Quality Signals**:
     - Schema Validation Failure Rate (target $< 5\%$).
     - Invalid JSON Retry Rate (target $< 2\%$).
     - **Invalid Evidence Rate** (quotes not found in source text, target $< 1\%$).
  6. **Evaluation History Card**:
     - Latest gold evaluation suite benchmark metrics (Evidence Validity Rate 100%, Injection Defense 100%, Conflict Accuracy).
     - Trend comparison table against previous runs.
  7. **Generic Provider Details Panel**:
     - Key-value inspector rendering `ProviderHealth.Details` as-is (enabling future custom model GPU metrics, queue depth, or checkpoint tags).
  8. **Operational Controls (AI Gate)**:
     - Current Gate Status (`enabled`, `paused`, `circuit_open`).
     - Action Buttons:
       - **Run Active Probe**: Executes harmless prompt test call. Shows modal with latency, HTTP status, and response summary.
       - **Pause AI**: Pauses all incoming LLM stages. Queued jobs enter `waiting_for_ai`.
       - **Resume AI**: Resumes processing; waiting jobs resume automatically.
       - **Reset Circuit Breaker**: Resets error counters and closes circuit to `enabled`.
     - Confirmation Modal: Each control requires a click confirmation and provides an immediate success/error toast.

---

### Screen A4: User Management (`/admin/users`)
- **Visuals**: Searchable, paginated user table with side-drawer user profile.
- **Elements**:
  - Filter by status (`all`, `active`, `suspended`).
  - Search by email.
  - Columns: Email, Status, Signup Date, Last Active, Documents Count, 24h Tokens Consumed, Actions.
- **Drawer / Actions**:
  - **Suspend / Unsuspend**: Requires optional reason. Suspending immediately revokes all active sessions in `gusby.sessions` and blocks login.
  - **Reset Limits**: Clears token usage counters and resets rate-limit lockout window for this user.
  - **Delete User**: **Destructive Action**. Opens confirmation modal requiring typed input: `"DELETE <email>"`. Explains consequences: all documents, chunks, extraction records, concepts, propositions, topics, and sessions belonging to this user will be permanently purged in a single transaction.

---

### Screen A5: Document Management (`/admin/documents`)
- **Visuals**: Document table with multi-filter (User, Status) and run inspector drawer.
- **Elements**:
  - Columns: Title, Source Type, User Email, Status, Chunks, Concepts Extracted, Created At, Actions.
  - Drawer: Shows raw document source text, chunk spans, extraction runs history, and failure reasons.
- **Actions**:
  - **Reprocess Document**: Idempotent re-run trigger. Creates a new extraction run, preserving history. Applies bounded retries and token budgeting.
  - **Delete Document**: **Destructive Action**. Opens confirmation modal requiring typed input: `"DELETE <title>"`. Displays calculated consequences:
    - Lists number of propositions that will be soft-retracted (propositions with zero remaining valid evidence).
    - Lists number of concepts that will be flagged as orphaned.
    - Requires typed confirmation. Executes in a single database transaction.

---

### Screen A6: Graph Data Administration (`/admin/graph`)
- **Visuals**: Table and form management interface (Form/Table based utility, NOT a visual graph canvas).
- **Tenant Context**: **Mandatory User Selector Dropdown** at the top. The admin explicitly selects a target user before any graph data is loaded.
- **Tabs**:
  1. **Concepts**:
     - Search & List concepts for selected user.
     - Actions: Edit name/description/type; manage aliases.
     - **Merge Concepts**: Select Source Concept and Target Concept. Validates merge, updates proposition pointers, preserves extraction provenance, logs in `integration_events` and `admin_audit_log`.
     - Archive Concept: Soft-archive concept if it has propositions; delete only if zero references exist.
  2. **Propositions**:
     - List propositions with Subject, Predicate, Object, Modality, Polarity, Evidence Quote.
     - **Retract / Restore**: Soft-retracts proposition (`is_canonical = false`, `status = 'retracted'`).
     - **Edit Qualifiers / Modality**: Requires typed reason; preserves prior state in history.
     - **Manual Proposition Addition**: Form with Subject, Predicate, Object, Document ID, and Verbatim Evidence Quote.
       - **Strict Invariant**: Enforces Go deterministic evidence validation. If quote is not found at verbatim offset in the selected document, the addition is **hard rejected**.
  3. **Topics**:
     - Create, rename, edit description, manage concept memberships.
     - Mark manual edits as **User-Locked** so incremental auto-clustering does not overwrite them.
  4. **Conflicts & Reviews**:
     - List items needing review (conflicts, integration proposals).
     - Actions: Resolve with recorded decision (`contextual_difference`, `contradiction`, `dismissed`, `insufficient_evidence`). Preserves both propositions and evidence.

---

### Screen A7: Admin Audit Log (`/admin/audit`)
- **Visuals**: Chronological append-only event stream table.
- **Filters**: Date range, Action Type (`user_suspend`, `user_delete`, `document_delete`, `concept_merge`, `proposition_retract`, `ai_gate_pause`, `ai_gate_resume`, `ai_probe`), Target Type.
- **Columns**: Timestamp, Admin Email, Action, Target Type & ID, Affected User, Reason, Details.
- **Detail Modal**: Side-by-side JSONB comparison of `before_state` and `after_state`.

---

## 4. Authorization & Error Flow Matrix `[Decided - CR-001]`

| User Type | Route Requested | Server Response | Client Behavior |
|---|---|---|---|
| **Anonymous (No Cookie)** | `/admin/*` | HTTP 404 (or 401) | Redirect immediately to `/auth/login` |
| **Regular User (`is_admin=false`)** | `/admin/*` | **HTTP 404 Not Found** | Renders 404 Page (Zero leak that admin route exists) |
| **Suspended User** | `/admin/*` or `/api/*` | **HTTP 401 Unauthorized** | Revoked session; redirected to `/auth/login` |
| **Admin (`is_admin=true`)** | `/admin/*` | **HTTP 200 OK** | Renders requested Admin screen with live data |
