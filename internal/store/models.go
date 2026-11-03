package store

import (
	"time"

	"github.com/google/uuid"
)

type User struct {
	ID              uuid.UUID `json:"id"`
	Email           string    `json:"email"`
	EmailNormalized string    `json:"email_normalized"`
	PasswordHash    string    `json:"-"`
	IsAdmin         bool      `json:"is_admin"`
	Status          string    `json:"status"` // active, suspended
	CreatedAt       time.Time `json:"created_at"`
	UpdatedAt       time.Time `json:"updated_at"`
}

type Session struct {
	ID        uuid.UUID `json:"id"`
	UserID    uuid.UUID `json:"user_id"`
	TokenHash string    `json:"-"`
	CreatedAt time.Time `json:"created_at"`
	LastUsedAt time.Time `json:"last_used_at"`
	ExpiresAt time.Time `json:"expires_at"`
}

type Document struct {
	ID           uuid.UUID `json:"id"`
	UserID       uuid.UUID `json:"user_id"`
	Title        string    `json:"title"`
	SourceType   string    `json:"source_type"` // text, url, pdf, docx
	SourceURL    *string   `json:"source_url,omitempty"`
	ContentHash  string    `json:"content_hash"`
	RawContent   []byte    `json:"-"`
	SourceText   string    `json:"source_text"`
	CharCount    int       `json:"char_count"`
	Status       string    `json:"status"` // uploading, processing, completed, failed
	ErrorMessage *string   `json:"error_message,omitempty"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}

type DocumentChunk struct {
	ID         uuid.UUID `json:"id"`
	UserID     uuid.UUID `json:"user_id"`
	DocumentID uuid.UUID `json:"document_id"`
	ChunkIndex int       `json:"chunk_index"`
	ChunkText  string    `json:"chunk_text"`
	ByteStart  int       `json:"byte_start"`
	ByteEnd    int       `json:"byte_end"`
	CharStart  int       `json:"char_start"`
	CharEnd    int       `json:"char_end"`
	CreatedAt  time.Time `json:"created_at"`
}

type ExtractionRun struct {
	ID               uuid.UUID  `json:"id"`
	UserID           uuid.UUID  `json:"user_id"`
	DocumentID       uuid.UUID  `json:"document_id"`
	ModelName        string     `json:"model_name"`
	PromptVersion    string     `json:"prompt_version"`
	Status           string     `json:"status"` // running, completed, failed
	TokensPrompt     int        `json:"tokens_prompt"`
	TokensCompletion int        `json:"tokens_completion"`
	ErrorMessage     *string    `json:"error_message,omitempty"`
	StartedAt        time.Time  `json:"started_at"`
	CompletedAt      *time.Time `json:"completed_at,omitempty"`
}

type ExtractedConcept struct {
	ID              uuid.UUID `json:"id"`
	UserID          uuid.UUID `json:"user_id"`
	ExtractionRunID uuid.UUID `json:"extraction_run_id"`
	ChunkID         uuid.UUID `json:"chunk_id"`
	Name            string    `json:"name"`
	Category        string    `json:"category"`
	CoreIdea        string    `json:"core_idea"`
	ConfidenceScore float64   `json:"confidence_score"`
	CreatedAt       time.Time `json:"created_at"`
}

type ExtractedProposition struct {
	ID                 uuid.UUID `json:"id"`
	UserID             uuid.UUID `json:"user_id"`
	ExtractionRunID    uuid.UUID `json:"extraction_run_id"`
	ChunkID            uuid.UUID `json:"chunk_id"`
	SubjectRaw         string    `json:"subject_raw"`
	Predicate          string    `json:"predicate"`
	ObjectRaw          string    `json:"object_raw"`
	EvidenceQuote      string    `json:"evidence_quote"`
	ConfidenceScore    float64   `json:"confidence_score"`
	IsValidEvidence    bool      `json:"is_valid_evidence"`
	EvidenceByteStart  *int      `json:"evidence_byte_start,omitempty"`
	EvidenceByteEnd    *int      `json:"evidence_byte_end,omitempty"`
	EvidenceCharStart  *int      `json:"evidence_char_start,omitempty"`
	EvidenceCharEnd    *int      `json:"evidence_char_end,omitempty"`
	CreatedAt          time.Time `json:"created_at"`
}

type Concept struct {
	ID             uuid.UUID `json:"id"`
	UserID         uuid.UUID `json:"user_id"`
	Name           string    `json:"name"`
	NameNormalized string    `json:"name_normalized"`
	Description    *string   `json:"description,omitempty"`
	Degree         int       `json:"degree"`
	NeedsReview    bool      `json:"needs_review"`
	IsOrphaned     bool      `json:"is_orphaned"`
	IsArchived     bool      `json:"is_archived"`
	CreatedAt      time.Time `json:"created_at"`
	UpdatedAt      time.Time `json:"updated_at"`
}

type ConceptAlias struct {
	ID              uuid.UUID `json:"id"`
	UserID          uuid.UUID `json:"user_id"`
	ConceptID       uuid.UUID `json:"concept_id"`
	Alias           string    `json:"alias"`
	AliasNormalized string    `json:"alias_normalized"`
	CreatedAt       time.Time `json:"created_at"`
}

type Proposition struct {
	ID                     uuid.UUID      `json:"id"`
	UserID                 uuid.UUID      `json:"user_id"`
	SubjectConceptID       uuid.UUID      `json:"subject_concept_id"`
	Predicate              string         `json:"predicate"`
	ObjectConceptID        uuid.UUID      `json:"object_concept_id"`
	Qualifiers             map[string]any `json:"qualifiers"`
	IsCanonical            bool           `json:"is_canonical"`
	HasConflict            bool           `json:"has_conflict"`
	Status                 string         `json:"status"` // active, retracted
	RetractedAt            *time.Time     `json:"retracted_at,omitempty"`
	RetractedReason        *string        `json:"retracted_reason,omitempty"`
	ConfidenceExtraction   float64        `json:"confidence_extraction"`
	ConfidenceEvidence     float64        `json:"confidence_evidence"`
	ConfidenceResolution   float64        `json:"confidence_resolution"`
	ConfidenceProposition  float64        `json:"confidence_proposition"`
	CreatedAt              time.Time      `json:"created_at"`
	UpdatedAt              time.Time      `json:"updated_at"`
}

type PropositionEvidence struct {
	ID            uuid.UUID `json:"id"`
	UserID        uuid.UUID `json:"user_id"`
	PropositionID uuid.UUID `json:"proposition_id"`
	DocumentID    uuid.UUID `json:"document_id"`
	DocumentTitle string    `json:"document_title,omitempty"`
	ChunkID       uuid.UUID `json:"chunk_id"`
	Quote         string    `json:"quote"`
	ByteStart     int       `json:"byte_start"`
	ByteEnd       int       `json:"byte_end"`
	CharStart     int       `json:"char_start"`
	CharEnd       int       `json:"char_end"`
	CreatedAt     time.Time `json:"created_at"`
}

type Topic struct {
	ID           uuid.UUID `json:"id"`
	UserID       uuid.UUID `json:"user_id"`
	Name         string    `json:"name"`
	Description  *string   `json:"description,omitempty"`
	ColorIndex   int       `json:"color_index"`
	CentroidX    float64   `json:"centroid_x"`
	CentroidY    float64   `json:"centroid_y"`
	IsUserLocked bool      `json:"is_user_locked"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}

type TopicMembership struct {
	UserID        uuid.UUID `json:"user_id"`
	TopicID       uuid.UUID `json:"topic_id"`
	ConceptID     uuid.UUID `json:"concept_id"`
	AffinityScore float64   `json:"affinity_score"`
	CreatedAt     time.Time `json:"created_at"`
}

type IntegrationProposal struct {
	ID                     uuid.UUID      `json:"id"`
	UserID                 uuid.UUID      `json:"user_id"`
	DocumentID             uuid.UUID      `json:"document_id"`
	ItemType               string         `json:"item_type"` // concept, proposition, merge
	Payload                map[string]any `json:"payload"`
	ConfidenceExtraction   float64        `json:"confidence_extraction"`
	ConfidenceEvidence     float64        `json:"confidence_evidence"`
	ConfidenceResolution   float64        `json:"confidence_resolution"`
	ConfidenceProposition  float64        `json:"confidence_proposition"`
	Status                 string         `json:"status"` // pending, approved, rejected
	ReviewerType           *string        `json:"reviewer_type,omitempty"`
	ReviewNotes            *string        `json:"review_notes,omitempty"`
	CreatedAt              time.Time      `json:"created_at"`
	ResolvedAt             *time.Time     `json:"resolved_at,omitempty"`
}

type PropositionConflict struct {
	ID                       uuid.UUID  `json:"id"`
	UserID                   uuid.UUID  `json:"user_id"`
	CanonicalPropositionID   uuid.UUID  `json:"canonical_proposition_id"`
	ConflictingPropositionID uuid.UUID  `json:"conflicting_proposition_id"`
	ConflictType             string     `json:"conflict_type"` // contradiction, contextual_difference, insufficient_evidence
	Status                   string     `json:"status"` // open, resolved, acknowledged
	DetectedBy               string     `json:"detected_by"`
	CreatedAt                time.Time  `json:"created_at"`
	ResolvedAt               *time.Time `json:"resolved_at,omitempty"`
}

type ProcessingJob struct {
	ID          uuid.UUID  `json:"id"`
	UserID      uuid.UUID  `json:"user_id"`
	DocumentID  uuid.UUID  `json:"document_id"`
	Stage       string     `json:"stage"` // queued, chunking, extracting, resolving, integrating, waiting_for_ai, done, failed
	Priority    int        `json:"priority"`
	Attempts    int        `json:"attempts"`
	MaxAttempts int        `json:"max_attempts"`
	RunAt       time.Time  `json:"run_at"`
	LockedAt    *time.Time `json:"locked_at,omitempty"`
	LockedBy    *string    `json:"locked_by,omitempty"`
	LastError   *string    `json:"last_error,omitempty"`
	FailedStage *string    `json:"failed_stage,omitempty"`
	StartedAt   *time.Time `json:"started_at,omitempty"`
	FinishedAt  *time.Time `json:"finished_at,omitempty"`
	CreatedAt   time.Time  `json:"created_at"`
	UpdatedAt   time.Time  `json:"updated_at"`
}

type LLMUsage struct {
	ID               uuid.UUID `json:"id"`
	UserID           uuid.UUID `json:"user_id"`
	UsageDate        time.Time `json:"usage_date"`
	Model            string    `json:"model"`
	TokensPrompt     int       `json:"tokens_prompt"`
	TokensCompletion int       `json:"tokens_completion"`
	CallCount        int       `json:"call_count"`
}

// -----------------------------------------------------------------------------
// Admin & AI Observability Models (CR-001)
// -----------------------------------------------------------------------------

type AdminAuditLog struct {
	ID           uuid.UUID      `json:"id"`
	AdminID      uuid.UUID      `json:"admin_id"`
	AdminEmail   string         `json:"admin_email,omitempty"`
	ActionType   string         `json:"action_type"`
	TargetType   string         `json:"target_type"`
	TargetID     *uuid.UUID     `json:"target_id,omitempty"`
	TargetUserID *uuid.UUID     `json:"target_user_id,omitempty"`
	TargetEmail  string         `json:"target_email,omitempty"`
	Reason       *string        `json:"reason,omitempty"`
	BeforeState  map[string]any `json:"before_state,omitempty"`
	AfterState   map[string]any `json:"after_state,omitempty"`
	RequestID    *string        `json:"request_id,omitempty"`
	CreatedAt    time.Time      `json:"created_at"`
}

type AICallLog struct {
	ID               uuid.UUID  `json:"id"`
	CreatedAt        time.Time  `json:"created_at"`
	Provider         string     `json:"provider"`
	Model            string     `json:"model"`
	PipelineStage    string     `json:"pipeline_stage"`
	PromptVersion    string     `json:"prompt_version"`
	LatencyMs        int        `json:"latency_ms"`
	Status           string     `json:"status"` // success, error
	ErrorClass       string     `json:"error_class"` // none, rate_limited, timeout, server_error, invalid_json, schema_validation_failed, auth_error, budget_exceeded
	TokensPrompt     int        `json:"tokens_prompt"`
	TokensCompletion int        `json:"tokens_completion"`
	RetryCount       int        `json:"retry_count"`
	RunID            *uuid.UUID `json:"run_id,omitempty"`
	UserID           *uuid.UUID `json:"user_id,omitempty"`
}

type AIGateState struct {
	ID                  string    `json:"id"`
	State               string    `json:"state"` // enabled, paused, circuit_open, half_open
	Reason              string    `json:"reason"`
	ConsecutiveFailures int       `json:"consecutive_failures"`
	UpdatedBy           string    `json:"updated_by"`
	UpdatedAt           time.Time `json:"updated_at"`
}

type EvalRun struct {
	ID                   uuid.UUID `json:"id"`
	DatasetVersion       string    `json:"dataset_version"`
	Model                string    `json:"model"`
	PromptVersion        string    `json:"prompt_version"`
	TotalDocuments       int       `json:"total_documents"`
	PropositionsAudited  int       `json:"propositions_audited"`
	EvidenceValidityRate float64   `json:"evidence_validity_rate"`
	InjectionDefenseRate float64   `json:"injection_defense_rate"`
	ConflictAccuracy     float64   `json:"conflict_accuracy"`
	PrecisionScore       float64   `json:"precision_score"`
	RecallScore          float64   `json:"recall_score"`
	CreatedAt            time.Time `json:"created_at"`
}
