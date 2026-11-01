"""Base schema for the PostgreSQL persistence layer.

Kept as plain SQL strings so the ADR's R8 exception for migrations is explicit
and the schema is reviewable in one place. The server never creates schema at
startup; every environment applies these files with ``alembic upgrade head``.
"""

# Table creation. Order matters: users first, then their dependents.
INITIAL_TABLES_SQL = """
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    email_normalized TEXT NOT NULL,
    password_hash TEXT,
    google_sub TEXT,
    email_verified_at TIMESTAMPTZ,
    is_locked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_email_normalized UNIQUE (email_normalized),
    CONSTRAINT uq_users_google_sub UNIQUE (google_sub)
);

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE email_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE consents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    providers_hash TEXT NOT NULL,
    providers_json TEXT NOT NULL,
    granted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE captures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    audio_path TEXT,
    duration_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'received',
    stage TEXT NOT NULL DEFAULT 'uploaded',
    error_class TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    user_edited_title BOOLEAN NOT NULL DEFAULT FALSE,
    user_edited_summary BOOLEAN NOT NULL DEFAULT FALSE,
    knowledge_item_id UUID,
    has_audio BOOLEAN NOT NULL DEFAULT FALSE,
    audio_on_server BOOLEAN NOT NULL DEFAULT FALSE,
    idempotency_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_captures_user_idempotency UNIQUE (user_id, idempotency_key)
);

CREATE TABLE knowledge_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    capture_id UUID REFERENCES captures(id) ON DELETE CASCADE,    title TEXT NOT NULL,
    core_idea TEXT,
    details TEXT NOT NULL DEFAULT '',
    transcript TEXT,
    concepts TEXT[] NOT NULL DEFAULT '{}',
    tags TEXT[] NOT NULL DEFAULT '{}',
    open_questions TEXT[] NOT NULL DEFAULT '{}',
    candidate_relations TEXT[] NOT NULL DEFAULT '{}',
    provenance TEXT NOT NULL DEFAULT 'voice-capture',
    provider_id TEXT NOT NULL DEFAULT '',
    model_version TEXT NOT NULL DEFAULT '',
    user_edited BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One self row per user is enforced by the partial unique index; the UL
-- composite keys make relationship endpoints owner-checked by FK.
CREATE TABLE entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    capture_id UUID REFERENCES captures(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'concept',
    description TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    certainty TEXT NOT NULL DEFAULT 'confirmed',
    provenance TEXT NOT NULL DEFAULT 'voice-capture',
    provider_id TEXT NOT NULL DEFAULT '',
    model_version TEXT NOT NULL DEFAULT '',
    user_edited BOOLEAN NOT NULL DEFAULT FALSE,
    is_self BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_entities_user_id UNIQUE (user_id, id)
);

CREATE TABLE relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    from_id UUID NOT NULL,
    to_id UUID NOT NULL,
    relation_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'suggested',
    confidence REAL NOT NULL DEFAULT 0.6,
    certainty TEXT NOT NULL DEFAULT 'confirmed',
    source_capture_id UUID REFERENCES captures(id) ON DELETE SET NULL,
    provenance TEXT NOT NULL DEFAULT 'voice-capture',
    user_edited BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_utterance TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_relationships_edge UNIQUE (user_id, from_id, to_id, relation_type),
    CONSTRAINT fk_relationships_from FOREIGN KEY (user_id, from_id)
        REFERENCES entities (user_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_relationships_to FOREIGN KEY (user_id, to_id)
        REFERENCES entities (user_id, id) ON DELETE CASCADE
);

CREATE TABLE relationship_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    canonical_name TEXT NOT NULL,
    normalized_key TEXT NOT NULL,
    semantic_description TEXT NOT NULL DEFAULT '',
    aliases TEXT[] NOT NULL DEFAULT '{}',
    provenance TEXT NOT NULL DEFAULT 'registry-seed',
    user_edited BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_relationship_types_key UNIQUE (user_id, normalized_key)
);

CREATE TABLE duplicate_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    decision TEXT NOT NULL DEFAULT 'pending',
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_duplicate_candidates UNIQUE (user_id, source_entity_id, target_entity_id)
);

CREATE TABLE tombstones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL,
    target_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_tombstones UNIQUE (user_id, target_kind, target_name)
);

CREATE TABLE record_supports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record_id UUID NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL,
    target_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_record_supports UNIQUE (record_id, target_kind, target_id)
);

CREATE TABLE model_eval_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    capture_id UUID REFERENCES captures(id) ON DELETE SET NULL,
    transcript TEXT,
    structured_json JSONB,
    user_corrected BOOLEAN NOT NULL DEFAULT FALSE,
    consent_given BOOLEAN NOT NULL DEFAULT FALSE,
    pipeline_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Embeddings only ever target knowledge items; the FK is the pipeline rule
-- "embed only rows that exist in this transaction" hardened at DB level.
CREATE TABLE knowledge_embeddings (
    item_id UUID PRIMARY KEY REFERENCES knowledge_items(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    embedding BYTEA,
    model_name TEXT NOT NULL DEFAULT '',
    dimension INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    capture_id UUID REFERENCES captures(id) ON DELETE SET NULL,
    stage TEXT NOT NULL DEFAULT 'queued',
    status TEXT NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    error_class TEXT NOT NULL DEFAULT '',
    error_message TEXT,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expires_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    stage_outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE llm_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL,
    model TEXT NOT NULL,
    operation TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd NUMERIC(10, 6),
    status TEXT NOT NULL DEFAULT 'success',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE admin_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor TEXT NOT NULL DEFAULT 'admin',
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL DEFAULT '',
    resource_id TEXT NOT NULL DEFAULT '',
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    ip_address TEXT NOT NULL DEFAULT 'unknown',
    outcome TEXT NOT NULL DEFAULT 'success',
    detail TEXT NOT NULL DEFAULT '',
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE admin_seed_registry (
    seed_name TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (seed_name, record_type, record_id)
);
"""

# Query-time indexes, including the graph-query indexes used by
# /api/graph/graph and admin listing pages.
INDEX_SQL = """
CREATE UNIQUE INDEX idx_entities_one_self_per_user
    ON entities (user_id) WHERE is_self;

CREATE INDEX idx_entities_user_name ON entities (user_id, normalized_name);
CREATE INDEX idx_entities_capture ON entities (capture_id);
CREATE INDEX idx_entities_user_type ON entities (user_id, entity_type);
CREATE INDEX idx_entities_user_created ON entities (user_id, created_at DESC);
CREATE INDEX idx_entities_lower_name ON entities (lower(name));
CREATE INDEX idx_entities_lower_description ON entities (lower(description));

CREATE INDEX idx_relationships_user_from_to ON relationships (user_id, from_id, to_id);
CREATE INDEX idx_relationships_user_to ON relationships (user_id, to_id);
CREATE INDEX idx_relationships_capture ON relationships (source_capture_id);
CREATE INDEX idx_relationships_type ON relationships (relation_type);
CREATE INDEX idx_relationships_status ON relationships (status);

CREATE INDEX idx_knowledge_user_created ON knowledge_items (user_id, created_at DESC);
CREATE INDEX idx_knowledge_capture ON knowledge_items (capture_id);
CREATE INDEX idx_knowledge_created ON knowledge_items (created_at DESC);

CREATE INDEX idx_captures_user_created ON captures (user_id, created_at DESC);
CREATE INDEX idx_captures_created ON captures (created_at DESC);

CREATE INDEX idx_sessions_user ON sessions (user_id);
CREATE UNIQUE INDEX idx_sessions_token_hash_lower ON sessions (lower(token_hash));
CREATE INDEX idx_sessions_active ON sessions (token_hash, revoked_at)
    WHERE revoked_at IS NULL;

CREATE INDEX idx_email_tokens_user ON email_tokens (user_id);
CREATE UNIQUE INDEX idx_email_tokens_token_hash_lower ON email_tokens (lower(token_hash));

CREATE INDEX idx_consents_user_created ON consents (user_id, created_at DESC);

CREATE INDEX idx_record_supports_record ON record_supports (record_id);
CREATE INDEX idx_record_supports_target ON record_supports (user_id, target_kind, target_id);

CREATE INDEX idx_duplicate_candidates_user_decision
    ON duplicate_candidates (user_id, decision);
CREATE INDEX idx_duplicate_candidates_source ON duplicate_candidates (source_entity_id);
CREATE INDEX idx_duplicate_candidates_target ON duplicate_candidates (target_entity_id);

CREATE INDEX idx_tombstones_user ON tombstones (user_id, target_kind, target_name);

CREATE INDEX idx_eval_consent ON model_eval_records (consent_given);
CREATE INDEX idx_eval_capture ON model_eval_records (capture_id);

CREATE INDEX idx_processing_jobs_status_claim ON processing_jobs (status, next_attempt_at);
CREATE INDEX idx_processing_jobs_capture ON processing_jobs (capture_id);
CREATE INDEX idx_processing_jobs_user_created ON processing_jobs (user_id, created_at DESC);
CREATE INDEX idx_processing_jobs_lease ON processing_jobs (lease_expires_at)
    WHERE lease_owner <> '';

CREATE UNIQUE INDEX idx_llm_usage_pk ON llm_usage (id);
CREATE INDEX idx_llm_usage_created ON llm_usage (created_at);
CREATE INDEX idx_llm_usage_user_created ON llm_usage (user_id, created_at);

CREATE INDEX idx_admin_audit_created ON admin_audit_log (created_at DESC);
CREATE INDEX idx_admin_audit_user ON admin_audit_log (user_id, created_at DESC);

CREATE INDEX idx_relationship_types_user_key
    ON relationship_types (user_id, normalized_key);
"""

DROP_SQL = """
DROP TABLE IF EXISTS admin_seed_registry, admin_audit_log, app_settings,
    llm_usage, processing_jobs, knowledge_embeddings, model_eval_records,
    record_supports, tombstones, duplicate_candidates, relationship_types,
    relationships, entities, knowledge_items, captures, consents, email_tokens,
    sessions, users CASCADE;
"""

BASE_SCHEMA_SQL = INITIAL_TABLES_SQL + INDEX_SQL
