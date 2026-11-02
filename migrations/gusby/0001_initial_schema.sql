-- Gusby Initial Schema Migration: 0001_initial_schema.sql
-- Dedicated schema: gusby

CREATE SCHEMA IF NOT EXISTS gusby;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Migration tracker
CREATE TABLE IF NOT EXISTS gusby.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Users & Auth
CREATE TABLE IF NOT EXISTS gusby.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    email_normalized TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gusby_users_email_normalized UNIQUE (email_normalized)
);

CREATE TABLE IF NOT EXISTS gusby.sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gusby_sessions_token_hash ON gusby.sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_gusby_sessions_user_id ON gusby.sessions(user_id);

-- Documents & Source Ingestion
CREATE TABLE IF NOT EXISTS gusby.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('text', 'url', 'pdf', 'docx')),
    source_url TEXT,
    content_hash TEXT NOT NULL,
    raw_content BYTEA,
    source_text TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('uploading', 'processing', 'completed', 'failed')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gusby_documents_user_hash UNIQUE (user_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_gusby_documents_user_status ON gusby.documents(user_id, status);

CREATE TABLE IF NOT EXISTS gusby.document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES gusby.documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    byte_start INTEGER NOT NULL,
    byte_end INTEGER NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gusby_chunks_doc_index UNIQUE (document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_gusby_chunks_doc ON gusby.document_chunks(document_id);

-- Extraction Runs & Staged Extractions
CREATE TABLE IF NOT EXISTS gusby.extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES gusby.documents(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    tokens_prompt INTEGER NOT NULL DEFAULT 0,
    tokens_completion INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS gusby.extracted_concepts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    extraction_run_id UUID NOT NULL REFERENCES gusby.extraction_runs(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES gusby.document_chunks(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT,
    core_idea TEXT,
    confidence_score DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gusby.extracted_propositions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    extraction_run_id UUID NOT NULL REFERENCES gusby.extraction_runs(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES gusby.document_chunks(id) ON DELETE CASCADE,
    subject_raw TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_raw TEXT NOT NULL,
    evidence_quote TEXT NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL,
    is_valid_evidence BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_byte_start INTEGER,
    evidence_byte_end INTEGER,
    evidence_char_start INTEGER,
    evidence_char_end INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Canonical Knowledge Graph
CREATE TABLE IF NOT EXISTS gusby.concepts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    description TEXT,
    degree INTEGER NOT NULL DEFAULT 0,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gusby_concepts_user_name UNIQUE (user_id, name_normalized)
);
CREATE INDEX IF NOT EXISTS idx_gusby_concepts_user_norm ON gusby.concepts(user_id, name_normalized);
CREATE INDEX IF NOT EXISTS idx_gusby_concepts_trgm ON gusby.concepts USING gin (name_normalized gin_trgm_ops);

CREATE TABLE IF NOT EXISTS gusby.concept_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    concept_id UUID NOT NULL REFERENCES gusby.concepts(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gusby_aliases_user_alias UNIQUE (user_id, alias_normalized)
);

CREATE TABLE IF NOT EXISTS gusby.propositions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    subject_concept_id UUID NOT NULL REFERENCES gusby.concepts(id) ON DELETE CASCADE,
    predicate TEXT NOT NULL,
    object_concept_id UUID NOT NULL REFERENCES gusby.concepts(id) ON DELETE CASCADE,
    qualifiers JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_canonical BOOLEAN NOT NULL DEFAULT TRUE,
    has_conflict BOOLEAN NOT NULL DEFAULT FALSE,
    confidence_extraction DOUBLE PRECISION NOT NULL,
    confidence_evidence DOUBLE PRECISION NOT NULL,
    confidence_resolution DOUBLE PRECISION NOT NULL,
    confidence_proposition DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gusby_propositions_triplet UNIQUE (user_id, subject_concept_id, predicate, object_concept_id)
);
CREATE INDEX IF NOT EXISTS idx_gusby_prop_user_subj ON gusby.propositions(user_id, subject_concept_id);
CREATE INDEX IF NOT EXISTS idx_gusby_prop_user_obj ON gusby.propositions(user_id, object_concept_id);

CREATE TABLE IF NOT EXISTS gusby.proposition_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    proposition_id UUID NOT NULL REFERENCES gusby.propositions(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES gusby.documents(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES gusby.document_chunks(id) ON DELETE CASCADE,
    quote TEXT NOT NULL,
    byte_start INTEGER NOT NULL,
    byte_end INTEGER NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gusby_evidence_prop ON gusby.proposition_evidence(proposition_id);

CREATE TABLE IF NOT EXISTS gusby.document_concepts (
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES gusby.documents(id) ON DELETE CASCADE,
    concept_id UUID NOT NULL REFERENCES gusby.concepts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, concept_id)
);

-- Topics
CREATE TABLE IF NOT EXISTS gusby.topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    color_index INTEGER NOT NULL DEFAULT 0,
    centroid_x DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    centroid_y DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gusby_topics_user_name UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS gusby.topic_memberships (
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES gusby.topics(id) ON DELETE CASCADE,
    concept_id UUID NOT NULL REFERENCES gusby.concepts(id) ON DELETE CASCADE,
    affinity_score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (topic_id, concept_id)
);
CREATE INDEX IF NOT EXISTS idx_gusby_topic_concept ON gusby.topic_memberships(concept_id);

-- Audit, Conflict & Proposals
CREATE TABLE IF NOT EXISTS gusby.integration_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES gusby.documents(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL CHECK (item_type IN ('concept', 'proposition', 'merge')),
    payload JSONB NOT NULL,
    confidence_extraction DOUBLE PRECISION NOT NULL,
    confidence_evidence DOUBLE PRECISION NOT NULL,
    confidence_resolution DOUBLE PRECISION NOT NULL,
    confidence_proposition DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewer_type TEXT CHECK (reviewer_type IN ('user', 'ai')),
    review_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_gusby_proposals_user_status ON gusby.integration_proposals(user_id, status);

CREATE TABLE IF NOT EXISTS gusby.proposition_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    canonical_proposition_id UUID NOT NULL REFERENCES gusby.propositions(id) ON DELETE CASCADE,
    conflicting_proposition_id UUID NOT NULL REFERENCES gusby.propositions(id) ON DELETE CASCADE,
    conflict_type TEXT NOT NULL CHECK (conflict_type IN ('contradiction', 'contextual_difference', 'insufficient_evidence')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'acknowledged')),
    detected_by TEXT NOT NULL DEFAULT 'pipeline',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS gusby.conflict_resolutions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    conflict_id UUID NOT NULL REFERENCES gusby.proposition_conflicts(id) ON DELETE CASCADE,
    decided_by TEXT NOT NULL CHECK (decided_by IN ('user', 'ai')),
    resolution_choice TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gusby.integration_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (actor IN ('user', 'ai')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Job Queue
CREATE TABLE IF NOT EXISTS gusby.processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES gusby.documents(id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('queued', 'chunking', 'extracting', 'resolving', 'integrating', 'done', 'failed')),
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ,
    locked_by TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gusby_jobs_poll ON gusby.processing_jobs(run_at, priority DESC) WHERE stage NOT IN ('done', 'failed');

-- Token Usage Accounting
CREATE TABLE IF NOT EXISTS gusby.llm_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES gusby.users(id) ON DELETE CASCADE,
    usage_date DATE NOT NULL DEFAULT CURRENT_DATE,
    model TEXT NOT NULL,
    tokens_prompt INTEGER NOT NULL DEFAULT 0,
    tokens_completion INTEGER NOT NULL DEFAULT 0,
    call_count INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_gusby_usage_user_date_model UNIQUE (user_id, usage_date, model)
);
