package store

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Store struct {
	pool *pgxpool.Pool
}

func NewStore(ctx context.Context, databaseURL string) (*Store, error) {
	config, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("failed to parse database url: %w", err)
	}

	config.MaxConns = 10
	config.MinConns = 2
	config.MaxConnIdleTime = 15 * time.Minute

	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		return nil, fmt.Errorf("failed to create connection pool: %w", err)
	}

	if err := pool.Ping(ctx); err != nil {
		return nil, fmt.Errorf("failed to ping postgres: %w", err)
	}

	return &Store{pool: pool}, nil
}

func (s *Store) Close() {
	if s.pool != nil {
		s.pool.Close()
	}
}

func (s *Store) Pool() *pgxpool.Pool {
	return s.pool
}

// Normalize helpers
func NormalizeString(str string) string {
	return strings.ToLower(strings.TrimSpace(str))
}

func HashToken(token string) string {
	h := sha256.Sum256([]byte(token))
	return hex.EncodeToString(h[:])
}

// -----------------------------------------------------------------------------
// Users & Sessions
// -----------------------------------------------------------------------------

func (s *Store) CreateUser(ctx context.Context, email, passwordHash string) (*User, error) {
	norm := NormalizeString(email)
	row := s.pool.QueryRow(ctx, `
		INSERT INTO gusby.users (email, email_normalized, password_hash, is_admin, status)
		VALUES ($1, $2, $3, false, 'active')
		RETURNING id, email, email_normalized, is_admin, status, created_at, updated_at
	`, email, norm, passwordHash)

	u := &User{}
	err := row.Scan(&u.ID, &u.Email, &u.EmailNormalized, &u.IsAdmin, &u.Status, &u.CreatedAt, &u.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return u, nil
}

func (s *Store) GetUserByEmail(ctx context.Context, email string) (*User, error) {
	norm := NormalizeString(email)
	row := s.pool.QueryRow(ctx, `
		SELECT id, email, email_normalized, password_hash, is_admin, status, created_at, updated_at
		FROM gusby.users
		WHERE email_normalized = $1
	`, norm)

	u := &User{}
	err := row.Scan(&u.ID, &u.Email, &u.EmailNormalized, &u.PasswordHash, &u.IsAdmin, &u.Status, &u.CreatedAt, &u.UpdatedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return u, nil
}

func (s *Store) GetUserByID(ctx context.Context, id uuid.UUID) (*User, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT id, email, email_normalized, password_hash, is_admin, status, created_at, updated_at
		FROM gusby.users
		WHERE id = $1
	`, id)

	u := &User{}
	err := row.Scan(&u.ID, &u.Email, &u.EmailNormalized, &u.PasswordHash, &u.IsAdmin, &u.Status, &u.CreatedAt, &u.UpdatedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return u, nil
}

func (s *Store) UpdateUserPassword(ctx context.Context, id uuid.UUID, passwordHash string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.users
		SET password_hash = $2, updated_at = NOW()
		WHERE id = $1
	`, id, passwordHash)
	return err
}

func (s *Store) CreateSession(ctx context.Context, userID uuid.UUID, token string, duration time.Duration) (*Session, error) {
	tokenHash := HashToken(token)
	expiresAt := time.Now().Add(duration)

	row := s.pool.QueryRow(ctx, `
		INSERT INTO gusby.sessions (user_id, token_hash, expires_at)
		VALUES ($1, $2, $3)
		RETURNING id, user_id, created_at, last_used_at, expires_at
	`, userID, tokenHash, expiresAt)

	sess := &Session{TokenHash: tokenHash}
	err := row.Scan(&sess.ID, &sess.UserID, &sess.CreatedAt, &sess.LastUsedAt, &sess.ExpiresAt)
	if err != nil {
		return nil, err
	}
	return sess, nil
}

func (s *Store) GetSessionByToken(ctx context.Context, token string) (*Session, error) {
	tokenHash := HashToken(token)
	row := s.pool.QueryRow(ctx, `
		SELECT id, user_id, token_hash, created_at, last_used_at, expires_at
		FROM gusby.sessions
		WHERE token_hash = $1 AND expires_at > now()
	`, tokenHash)

	sess := &Session{}
	err := row.Scan(&sess.ID, &sess.UserID, &sess.TokenHash, &sess.CreatedAt, &sess.LastUsedAt, &sess.ExpiresAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	// Update last_used_at asynchronously
	go func(id uuid.UUID) {
		ctxTimeout, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_, _ = s.pool.Exec(ctxTimeout, "UPDATE gusby.sessions SET last_used_at = now() WHERE id = $1", id)
	}(sess.ID)

	return sess, nil
}

func (s *Store) DeleteSession(ctx context.Context, token string) error {
	tokenHash := HashToken(token)
	_, err := s.pool.Exec(ctx, "DELETE FROM gusby.sessions WHERE token_hash = $1", tokenHash)
	return err
}

// -----------------------------------------------------------------------------
// Documents & Chunks
// -----------------------------------------------------------------------------

func (s *Store) CreateDocument(ctx context.Context, doc *Document) (*Document, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO gusby.documents (
			user_id, title, source_type, source_url, content_hash, raw_content, source_text, char_count, status
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		RETURNING id, created_at, updated_at
	`, doc.UserID, doc.Title, doc.SourceType, doc.SourceURL, doc.ContentHash, doc.RawContent, doc.SourceText, doc.CharCount, doc.Status)

	err := row.Scan(&doc.ID, &doc.CreatedAt, &doc.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return doc, nil
}

func (s *Store) GetDocumentByHash(ctx context.Context, userID uuid.UUID, contentHash string) (*Document, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT id, user_id, title, source_type, source_url, content_hash, source_text, char_count, status, error_message, created_at, updated_at
		FROM gusby.documents
		WHERE user_id = $1 AND content_hash = $2
	`, userID, contentHash)

	d := &Document{}
	err := row.Scan(&d.ID, &d.UserID, &d.Title, &d.SourceType, &d.SourceURL, &d.ContentHash, &d.SourceText, &d.CharCount, &d.Status, &d.ErrorMessage, &d.CreatedAt, &d.UpdatedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return d, nil
}

func (s *Store) GetDocumentByID(ctx context.Context, userID, docID uuid.UUID) (*Document, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT id, user_id, title, source_type, source_url, content_hash, source_text, char_count, status, error_message, created_at, updated_at
		FROM gusby.documents
		WHERE user_id = $1 AND id = $2
	`, userID, docID)

	d := &Document{}
	err := row.Scan(&d.ID, &d.UserID, &d.Title, &d.SourceType, &d.SourceURL, &d.ContentHash, &d.SourceText, &d.CharCount, &d.Status, &d.ErrorMessage, &d.CreatedAt, &d.UpdatedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return d, nil
}

func (s *Store) ListDocuments(ctx context.Context, userID uuid.UUID, status string, limit, offset int) ([]*Document, int, error) {
	where := "user_id = $1"
	args := []any{userID}
	if status != "" {
		args = append(args, status)
		where += fmt.Sprintf(" AND status = $%d", len(args))
	}

	countQuery := fmt.Sprintf("SELECT COUNT(*) FROM gusby.documents WHERE %s", where)
	var total int
	if err := s.pool.QueryRow(ctx, countQuery, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	args = append(args, limit, offset)
	listQuery := fmt.Sprintf(`
		SELECT id, user_id, title, source_type, source_url, content_hash, source_text, char_count, status, error_message, created_at, updated_at
		FROM gusby.documents
		WHERE %s
		ORDER BY created_at DESC
		LIMIT $%d OFFSET $%d
	`, where, len(args)-1, len(args))

	rows, err := s.pool.Query(ctx, listQuery, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	var docs []*Document
	for rows.Next() {
		d := &Document{}
		if err := rows.Scan(&d.ID, &d.UserID, &d.Title, &d.SourceType, &d.SourceURL, &d.ContentHash, &d.SourceText, &d.CharCount, &d.Status, &d.ErrorMessage, &d.CreatedAt, &d.UpdatedAt); err != nil {
			return nil, 0, err
		}
		docs = append(docs, d)
	}
	return docs, total, nil
}

func (s *Store) UpdateDocumentStatus(ctx context.Context, userID, docID uuid.UUID, status string, errorMsg *string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.documents
		SET status = $3, error_message = $4, updated_at = now()
		WHERE user_id = $1 AND id = $2
	`, userID, docID, status, errorMsg)
	return err
}

func (s *Store) InsertChunks(ctx context.Context, chunks []*DocumentChunk) error {
	if len(chunks) == 0 {
		return nil
	}
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	for _, c := range chunks {
		row := tx.QueryRow(ctx, `
			INSERT INTO gusby.document_chunks (
				user_id, document_id, chunk_index, chunk_text, byte_start, byte_end, char_start, char_end
			) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
			RETURNING id, created_at
		`, c.UserID, c.DocumentID, c.ChunkIndex, c.ChunkText, c.ByteStart, c.ByteEnd, c.CharStart, c.CharEnd)
		if err := row.Scan(&c.ID, &c.CreatedAt); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (s *Store) GetChunksByDocumentID(ctx context.Context, userID, docID uuid.UUID) ([]*DocumentChunk, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, user_id, document_id, chunk_index, chunk_text, byte_start, byte_end, char_start, char_end, created_at
		FROM gusby.document_chunks
		WHERE user_id = $1 AND document_id = $2
		ORDER BY chunk_index ASC
	`, userID, docID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var chunks []*DocumentChunk
	for rows.Next() {
		c := &DocumentChunk{}
		if err := rows.Scan(&c.ID, &c.UserID, &c.DocumentID, &c.ChunkIndex, &c.ChunkText, &c.ByteStart, &c.ByteEnd, &c.CharStart, &c.CharEnd, &c.CreatedAt); err != nil {
			return nil, err
		}
		chunks = append(chunks, c)
	}
	return chunks, nil
}

// -----------------------------------------------------------------------------
// Concepts, Aliases & Graph Nodes
// -----------------------------------------------------------------------------

func (s *Store) UpsertConcept(ctx context.Context, userID uuid.UUID, name, description string) (*Concept, error) {
	norm := NormalizeString(name)
	row := s.pool.QueryRow(ctx, `
		INSERT INTO gusby.concepts (user_id, name, name_normalized, description)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (user_id, name_normalized) DO UPDATE
		SET degree = gusby.concepts.degree + 1, updated_at = now()
		RETURNING id, user_id, name, name_normalized, description, degree, needs_review, created_at, updated_at
	`, userID, strings.TrimSpace(name), norm, description)

	c := &Concept{}
	if err := row.Scan(&c.ID, &c.UserID, &c.Name, &c.NameNormalized, &c.Description, &c.Degree, &c.NeedsReview, &c.CreatedAt, &c.UpdatedAt); err != nil {
		return nil, err
	}
	return c, nil
}

func (s *Store) GetConceptByID(ctx context.Context, userID, conceptID uuid.UUID) (*Concept, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT id, user_id, name, name_normalized, description, degree, needs_review, created_at, updated_at
		FROM gusby.concepts
		WHERE user_id = $1 AND id = $2
	`, userID, conceptID)

	c := &Concept{}
	if err := row.Scan(&c.ID, &c.UserID, &c.Name, &c.NameNormalized, &c.Description, &c.Degree, &c.NeedsReview, &c.CreatedAt, &c.UpdatedAt); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return c, nil
}

func (s *Store) FindConceptByExactOrAlias(ctx context.Context, userID uuid.UUID, name string) (*Concept, error) {
	norm := NormalizeString(name)
	// First check direct name
	row := s.pool.QueryRow(ctx, `
		SELECT id, user_id, name, name_normalized, description, degree, needs_review, created_at, updated_at
		FROM gusby.concepts
		WHERE user_id = $1 AND name_normalized = $2
	`, userID, norm)

	c := &Concept{}
	err := row.Scan(&c.ID, &c.UserID, &c.Name, &c.NameNormalized, &c.Description, &c.Degree, &c.NeedsReview, &c.CreatedAt, &c.UpdatedAt)
	if err == nil {
		return c, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}

	// Check aliases
	row = s.pool.QueryRow(ctx, `
		SELECT c.id, c.user_id, c.name, c.name_normalized, c.description, c.degree, c.needs_review, c.created_at, c.updated_at
		FROM gusby.concept_aliases a
		JOIN gusby.concepts c ON a.concept_id = c.id
		WHERE a.user_id = $1 AND a.alias_normalized = $2
	`, userID, norm)

	err = row.Scan(&c.ID, &c.UserID, &c.Name, &c.NameNormalized, &c.Description, &c.Degree, &c.NeedsReview, &c.CreatedAt, &c.UpdatedAt)
	if err == nil {
		return c, nil
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	return nil, err
}

func (s *Store) FindConceptsByTrigram(ctx context.Context, userID uuid.UUID, name string, minSimilarity float64, limit int) ([]*Concept, []float64, error) {
	norm := NormalizeString(name)
	rows, err := s.pool.Query(ctx, `
		SELECT id, user_id, name, name_normalized, description, degree, needs_review, created_at, updated_at,
		       GREATEST(similarity(name_normalized, $2), word_similarity($2, name_normalized)) as sim
		FROM gusby.concepts
		WHERE user_id = $1 AND GREATEST(similarity(name_normalized, $2), word_similarity($2, name_normalized)) >= $3
		ORDER BY sim DESC
		LIMIT $4
	`, userID, norm, minSimilarity, limit)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()

	var concepts []*Concept
	var sims []float64
	for rows.Next() {
		c := &Concept{}
		var sim float64
		if err := rows.Scan(&c.ID, &c.UserID, &c.Name, &c.NameNormalized, &c.Description, &c.Degree, &c.NeedsReview, &c.CreatedAt, &c.UpdatedAt, &sim); err != nil {
			return nil, nil, err
		}
		concepts = append(concepts, c)
		sims = append(sims, sim)
	}
	return concepts, sims, nil
}

func (s *Store) AddConceptAlias(ctx context.Context, userID, conceptID uuid.UUID, alias string) error {
	norm := NormalizeString(alias)
	_, err := s.pool.Exec(ctx, `
		INSERT INTO gusby.concept_aliases (user_id, concept_id, alias, alias_normalized)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (user_id, alias_normalized) DO NOTHING
	`, userID, conceptID, strings.TrimSpace(alias), norm)
	return err
}

// -----------------------------------------------------------------------------
// Propositions & Evidence
// -----------------------------------------------------------------------------

func (s *Store) CreateProposition(ctx context.Context, p *Proposition) (*Proposition, error) {
	qualBytes, err := json.Marshal(p.Qualifiers)
	if err != nil {
		qualBytes = []byte("{}")
	}

	row := s.pool.QueryRow(ctx, `
		INSERT INTO gusby.propositions (
			user_id, subject_concept_id, predicate, object_concept_id, qualifiers,
			is_canonical, has_conflict, confidence_extraction, confidence_evidence,
			confidence_resolution, confidence_proposition
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
		ON CONFLICT (user_id, subject_concept_id, predicate, object_concept_id) DO UPDATE
		SET updated_at = now()
		RETURNING id, created_at, updated_at
	`, p.UserID, p.SubjectConceptID, p.Predicate, p.ObjectConceptID, qualBytes,
		p.IsCanonical, p.HasConflict, p.ConfidenceExtraction, p.ConfidenceEvidence,
		p.ConfidenceResolution, p.ConfidenceProposition)

	if err := row.Scan(&p.ID, &p.CreatedAt, &p.UpdatedAt); err != nil {
		return nil, err
	}
	return p, nil
}

func (s *Store) CreateEvidence(ctx context.Context, ev *PropositionEvidence) (*PropositionEvidence, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO gusby.proposition_evidence (
			user_id, proposition_id, document_id, chunk_id, quote, byte_start, byte_end, char_start, char_end
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		RETURNING id, created_at
	`, ev.UserID, ev.PropositionID, ev.DocumentID, ev.ChunkID, ev.Quote, ev.ByteStart, ev.ByteEnd, ev.CharStart, ev.CharEnd)

	if err := row.Scan(&ev.ID, &ev.CreatedAt); err != nil {
		return nil, err
	}
	return ev, nil
}

func (s *Store) FindPropositionBySubjectAndPredicate(ctx context.Context, userID, subjectID uuid.UUID, predicate string) ([]*Proposition, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, user_id, subject_concept_id, predicate, object_concept_id, qualifiers,
		       is_canonical, has_conflict, confidence_extraction, confidence_evidence,
		       confidence_resolution, confidence_proposition, created_at, updated_at
		FROM gusby.propositions
		WHERE user_id = $1 AND subject_concept_id = $2 AND predicate = $3
	`, userID, subjectID, predicate)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var props []*Proposition
	for rows.Next() {
		p := &Proposition{}
		var qualBytes []byte
		if err := rows.Scan(
			&p.ID, &p.UserID, &p.SubjectConceptID, &p.Predicate, &p.ObjectConceptID, &qualBytes,
			&p.IsCanonical, &p.HasConflict, &p.ConfidenceExtraction, &p.ConfidenceEvidence,
			&p.ConfidenceResolution, &p.ConfidenceProposition, &p.CreatedAt, &p.UpdatedAt,
		); err != nil {
			return nil, err
		}
		_ = json.Unmarshal(qualBytes, &p.Qualifiers)
		props = append(props, p)
	}
	return props, nil
}

func (s *Store) GetEvidenceForProposition(ctx context.Context, userID, propID uuid.UUID) ([]*PropositionEvidence, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT e.id, e.user_id, e.proposition_id, e.document_id, d.title, e.chunk_id, e.quote, e.byte_start, e.byte_end, e.char_start, e.char_end, e.created_at
		FROM gusby.proposition_evidence e
		JOIN gusby.documents d ON e.document_id = d.id
		WHERE e.user_id = $1 AND e.proposition_id = $2
	`, userID, propID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var list []*PropositionEvidence
	for rows.Next() {
		ev := &PropositionEvidence{}
		if err := rows.Scan(
			&ev.ID, &ev.UserID, &ev.PropositionID, &ev.DocumentID, &ev.DocumentTitle,
			&ev.ChunkID, &ev.Quote, &ev.ByteStart, &ev.ByteEnd, &ev.CharStart, &ev.CharEnd, &ev.CreatedAt,
		); err != nil {
			return nil, err
		}
		list = append(list, ev)
	}
	return list, nil
}

// -----------------------------------------------------------------------------
// Job Queue (SKIP LOCKED)
// -----------------------------------------------------------------------------

func (s *Store) EnqueueJob(ctx context.Context, userID, docID uuid.UUID, stage string, priority int) (*ProcessingJob, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO gusby.processing_jobs (user_id, document_id, stage, priority)
		VALUES ($1, $2, $3, $4)
		RETURNING id, user_id, document_id, stage, priority, attempts, max_attempts, run_at, created_at, updated_at
	`, userID, docID, stage, priority)

	job := &ProcessingJob{}
	if err := row.Scan(&job.ID, &job.UserID, &job.DocumentID, &job.Stage, &job.Priority, &job.Attempts, &job.MaxAttempts, &job.RunAt, &job.CreatedAt, &job.UpdatedAt); err != nil {
		return nil, err
	}
	return job, nil
}

func (s *Store) ClaimNextJob(ctx context.Context, workerID string) (*ProcessingJob, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	row := tx.QueryRow(ctx, `
		SELECT id, user_id, document_id, stage, priority, attempts, max_attempts, run_at, created_at, updated_at
		FROM gusby.processing_jobs
		WHERE stage NOT IN ('done', 'failed') AND run_at <= now()
		  AND (locked_at IS NULL OR locked_at < now() - interval '5 minutes')
		ORDER BY priority DESC, created_at ASC
		LIMIT 1
		FOR UPDATE SKIP LOCKED
	`)

	job := &ProcessingJob{}
	if err := row.Scan(&job.ID, &job.UserID, &job.DocumentID, &job.Stage, &job.Priority, &job.Attempts, &job.MaxAttempts, &job.RunAt, &job.CreatedAt, &job.UpdatedAt); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}

	_, err = tx.Exec(ctx, `
		UPDATE gusby.processing_jobs
		SET locked_at = now(), locked_by = $2, attempts = attempts + 1, updated_at = now()
		WHERE id = $1
	`, job.ID, workerID)
	if err != nil {
		return nil, err
	}

	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}
	return job, nil
}

func (s *Store) UpdateJobStage(ctx context.Context, jobID uuid.UUID, stage string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.processing_jobs
		SET stage = $2, updated_at = now()
		WHERE id = $1
	`, jobID, stage)
	return err
}

func (s *Store) CompleteJob(ctx context.Context, jobID uuid.UUID) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.processing_jobs
		SET stage = 'done', locked_at = NULL, locked_by = NULL, updated_at = now()
		WHERE id = $1
	`, jobID)
	return err
}

func (s *Store) FailJob(ctx context.Context, jobID uuid.UUID, errMsg string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.processing_jobs
		SET stage = 'failed', last_error = $2, locked_at = NULL, locked_by = NULL, updated_at = now()
		WHERE id = $1
	`, jobID, errMsg)
	return err
}

// -----------------------------------------------------------------------------
// Token Usage & Budgeting
// -----------------------------------------------------------------------------

func (s *Store) RecordTokenUsage(ctx context.Context, userID uuid.UUID, model string, promptTokens, completionTokens int) error {
	_, err := s.pool.Exec(ctx, `
		INSERT INTO gusby.llm_usage (user_id, usage_date, model, tokens_prompt, tokens_completion, call_count)
		VALUES ($1, CURRENT_DATE, $2, $3, $4, 1)
		ON CONFLICT (user_id, usage_date, model) DO UPDATE
		SET tokens_prompt = gusby.llm_usage.tokens_prompt + $3,
		    tokens_completion = gusby.llm_usage.tokens_completion + $4,
		    call_count = gusby.llm_usage.call_count + 1
	`, userID, model, promptTokens, completionTokens)
	return err
}

func (s *Store) GetDailyTokensUsed(ctx context.Context, userID uuid.UUID) (int, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT COALESCE(SUM(tokens_prompt + tokens_completion), 0)
		FROM gusby.llm_usage
		WHERE user_id = $1 AND usage_date = CURRENT_DATE
	`, userID)

	var total int
	if err := row.Scan(&total); err != nil {
		return 0, err
	}
	return total, nil
}
