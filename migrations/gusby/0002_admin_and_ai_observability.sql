-- Gusby Schema Migration: 0002_admin_and_ai_observability.sql
-- Dedicated schema: gusby

-- 1. Users: is_admin, status
ALTER TABLE gusby.users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE gusby.users ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_gusby_users_status'
    ) THEN
        ALTER TABLE gusby.users ADD CONSTRAINT chk_gusby_users_status CHECK (status IN ('active', 'suspended'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_gusby_users_status ON gusby.users (status);
CREATE INDEX IF NOT EXISTS idx_gusby_users_is_admin ON gusby.users (is_admin);

-- 2. Processing Jobs: waiting_for_ai, started_at, finished_at, failed_stage
ALTER TABLE gusby.processing_jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE gusby.processing_jobs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;
ALTER TABLE gusby.processing_jobs ADD COLUMN IF NOT EXISTS failed_stage TEXT;

-- Update processing_jobs stage check constraint to include 'waiting_for_ai'
ALTER TABLE gusby.processing_jobs DROP CONSTRAINT IF EXISTS processing_jobs_stage_check;
ALTER TABLE gusby.processing_jobs ADD CONSTRAINT processing_jobs_stage_check 
CHECK (stage IN ('queued', 'chunking', 'extracting', 'resolving', 'integrating', 'waiting_for_ai', 'done', 'failed'));

-- 3. Concepts: is_orphaned, is_archived
ALTER TABLE gusby.concepts ADD COLUMN IF NOT EXISTS is_orphaned BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE gusby.concepts ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false;

-- 4. Propositions: status, retracted_at, retracted_reason
ALTER TABLE gusby.propositions ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE gusby.propositions ADD COLUMN IF NOT EXISTS retracted_at TIMESTAMPTZ;
ALTER TABLE gusby.propositions ADD COLUMN IF NOT EXISTS retracted_reason TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_gusby_propositions_status'
    ) THEN
        ALTER TABLE gusby.propositions ADD CONSTRAINT chk_gusby_propositions_status CHECK (status IN ('active', 'retracted'));
    END IF;
END $$;

-- 5. Topics: is_user_locked
ALTER TABLE gusby.topics ADD COLUMN IF NOT EXISTS is_user_locked BOOLEAN NOT NULL DEFAULT false;

-- 6. Admin Audit Log (Append-only)
CREATE TABLE IF NOT EXISTS gusby.admin_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID NOT NULL REFERENCES gusby.users(id),
    action_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID,
    target_user_id UUID REFERENCES gusby.users(id) ON DELETE SET NULL,
    reason TEXT,
    before_state JSONB,
    after_state JSONB,
    request_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON gusby.admin_audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_action ON gusby.admin_audit_log (action_type);
CREATE INDEX IF NOT EXISTS idx_admin_audit_target_user ON gusby.admin_audit_log (target_user_id);

-- 7. AI Call Log (Append-only, no prompts/text)
CREATE TABLE IF NOT EXISTS gusby.ai_call_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    pipeline_stage TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    status TEXT NOT NULL, -- 'success', 'error'
    error_class TEXT NOT NULL, -- 'none', 'rate_limited', 'timeout', 'server_error', 'invalid_json', 'schema_validation_failed', 'auth_error', 'budget_exceeded'
    tokens_prompt INTEGER NOT NULL DEFAULT 0,
    tokens_completion INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    run_id UUID REFERENCES gusby.extraction_runs(id) ON DELETE SET NULL,
    user_id UUID REFERENCES gusby.users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ai_call_log_created ON gusby.ai_call_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_call_log_provider_model ON gusby.ai_call_log (provider, model);
CREATE INDEX IF NOT EXISTS idx_ai_call_log_error_class ON gusby.ai_call_log (error_class) WHERE error_class <> 'none';

-- 8. AI Gate State (Persistent single-row or primary gate)
CREATE TABLE IF NOT EXISTS gusby.ai_gate_state (
    id TEXT PRIMARY KEY DEFAULT 'primary_gate',
    state TEXT NOT NULL CHECK (state IN ('enabled', 'paused', 'circuit_open', 'half_open')),
    reason TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Initialize primary gate if not exists
INSERT INTO gusby.ai_gate_state (id, state, reason, consecutive_failures, updated_by, updated_at)
VALUES ('primary_gate', 'enabled', 'Initialized default state', 0, 'system', now())
ON CONFLICT (id) DO NOTHING;

-- 9. Evaluation Benchmark Runs
CREATE TABLE IF NOT EXISTS gusby.eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_version TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    total_documents INTEGER NOT NULL,
    propositions_audited INTEGER NOT NULL,
    evidence_validity_rate DOUBLE PRECISION NOT NULL,
    injection_defense_rate DOUBLE PRECISION NOT NULL,
    conflict_accuracy DOUBLE PRECISION NOT NULL,
    precision_score DOUBLE PRECISION NOT NULL,
    recall_score DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_created ON gusby.eval_runs (created_at DESC);
