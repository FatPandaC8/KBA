# Gusby Change Requests Log (CHANGE_REQUESTS.md)

This log records formal change requests (CR) initiated after the v1.0 documentation freeze.
Per binding rules:
- Any needed deviation from frozen v1.0 docs requires a Change Request (what, why, which doc sections).
- Only the Orchestrator approves Change Requests.
- Only the Docs Writer edits docs, recording a changelog entry.
- If a change affects product scope, the user must be consulted.

---

| CR ID | Date | Requester | Sections Affected | Summary of Change | Justification | Status |
|---|---|---|---|---|---|---|
| CR-000 | 2026-11-02 | Orchestrator | All | Initial baseline v1.0 docs creation | Project kickoff | Approved (v1.0 Baseline) |
| CR-001 | 2026-11-03 | User / Orchestrator | 01_PRD, 02_TRD, 03_APP_FLOW, 04_DESIGN_SYSTEM, 05_SCHEMA_AND_API, 06_PLAN | Add Single-Owner Admin Dashboard (monitoring, AI health & controls, user/doc management, graph admin, audit log) | Approved scope extension for platform operations & future model swap readiness | Approved (v1.1 Target) |

---

### CR-001: Admin Dashboard & AI Component Health Extension
- **Requester**: User & Orchestrator
- **Date**: 2026-11-03
- **Scope Extension**:
  1. **Single-Owner Role**: `is_admin` boolean on `gusby.users`, server-side `RequireAdmin` middleware returning 404 for non-admins, CLI / env owner bootstrapping.
  2. **Monitoring**: Pipeline health (queue, failures, retries, stuck jobs), user activity feeds, and AI component health & state (rolling window status, latency, error classes, quality signals).
  3. **AI Provider Contract & Controls**: `Describe()`, `Health()`, per-call metadata logging in `gusby.ai_call_log` (zero prompt/text storage), shared AI gate (enabled/paused/circuit_open with half-open recovery), active health probe, eval run recording. Designed for seamless future custom model replacement.
  4. **Management**: User management (suspend, hard delete in single transaction, limit reset), Document management (retry/reprocess, delete with cascading soft retraction of unsupported propositions & orphaned concept flagging), Graph management (concept merge/edit/archive, proposition retract/restore/edit, topic locking, conflict resolution).
  5. **Audit Logging**: Append-only `gusby.admin_audit_log` recording every mutation, content access, and AI control action in the same transaction.
  6. **Design & Trust Rules**: Pure white canvas, light mode, inline SVG charts, zero unverified evidence, strictly scoped per-user repository queries.

