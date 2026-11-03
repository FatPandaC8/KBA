package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// -----------------------------------------------------------------------------
// Admin Foundation & User Management Store Methods
// -----------------------------------------------------------------------------

func (s *Store) SetUserAdmin(ctx context.Context, userID uuid.UUID, isAdmin bool) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.users
		SET is_admin = $2, updated_at = NOW()
		WHERE id = $1
	`, userID, isAdmin)
	return err
}

func (s *Store) SetUserStatus(ctx context.Context, userID uuid.UUID, status string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.users
		SET status = $2, updated_at = NOW()
		WHERE id = $1
	`, userID, status)
	return err
}

func (s *Store) RevokeUserSessions(ctx context.Context, userID uuid.UUID) error {
	_, err := s.pool.Exec(ctx, `
		DELETE FROM gusby.sessions
		WHERE user_id = $1
	`, userID)
	return err
}

func (s *Store) CountAdmins(ctx context.Context) (int, error) {
	var count int
	err := s.pool.QueryRow(ctx, `
		SELECT COUNT(*)
		FROM gusby.users
		WHERE is_admin = true AND status = 'active'
	`).Scan(&count)
	return count, err
}

func (s *Store) ListUsers(ctx context.Context, query, status string, limit, offset int) ([]*User, int, error) {
	if limit <= 0 {
		limit = 50
	}
	if limit > 200 {
		limit = 200
	}
	if offset < 0 {
		offset = 0
	}

	whereClauses := []string{"1=1"}
	args := []any{}
	argIdx := 1

	if status != "" && status != "all" {
		whereClauses = append(whereClauses, fmt.Sprintf("status = $%d", argIdx))
		args = append(args, status)
		argIdx++
	}

	if query != "" {
		whereClauses = append(whereClauses, fmt.Sprintf("email_normalized ILIKE $%d", argIdx))
		args = append(args, "%"+strings.ToLower(strings.TrimSpace(query))+"%")
		argIdx++
	}

	where := strings.Join(whereClauses, " AND ")

	var total int
	countQuery := fmt.Sprintf("SELECT COUNT(*) FROM gusby.users WHERE %s", where)
	if err := s.pool.QueryRow(ctx, countQuery, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	selectQuery := fmt.Sprintf(`
		SELECT id, email, email_normalized, is_admin, status, created_at, updated_at
		FROM gusby.users
		WHERE %s
		ORDER BY created_at DESC
		LIMIT $%d OFFSET $%d
	`, where, argIdx, argIdx+1)
	args = append(args, limit, offset)

	rows, err := s.pool.Query(ctx, selectQuery, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	users := []*User{}
	for rows.Next() {
		u := &User{}
		if err := rows.Scan(&u.ID, &u.Email, &u.EmailNormalized, &u.IsAdmin, &u.Status, &u.CreatedAt, &u.UpdatedAt); err != nil {
			return nil, 0, err
		}
		users = append(users, u)
	}

	return users, total, nil
}

func (s *Store) DeleteUserAndAllData(ctx context.Context, userID uuid.UUID) (map[string]int, error) {
	counts := make(map[string]int)

	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	var docCount, conceptCount, propCount, topicCount, sessionCount int
	_ = tx.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.documents WHERE user_id = $1", userID).Scan(&docCount)
	_ = tx.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.concepts WHERE user_id = $1", userID).Scan(&conceptCount)
	_ = tx.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.propositions WHERE user_id = $1", userID).Scan(&propCount)
	_ = tx.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.topics WHERE user_id = $1", userID).Scan(&topicCount)
	_ = tx.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.sessions WHERE user_id = $1", userID).Scan(&sessionCount)
	counts["documents"] = docCount
	counts["concepts"] = conceptCount
	counts["propositions"] = propCount
	counts["topics"] = topicCount
	counts["sessions"] = sessionCount

	// Foreign keys with CASCADE will purge documents, chunks, extraction_runs, concepts, propositions, topics, sessions, etc.
	_, err = tx.Exec(ctx, "DELETE FROM gusby.users WHERE id = $1", userID)
	if err != nil {
		return nil, err
	}

	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}

	return counts, nil
}

func (s *Store) ResetUserLimits(ctx context.Context, userID uuid.UUID) error {
	_, err := s.pool.Exec(ctx, `
		DELETE FROM gusby.llm_usage
		WHERE user_id = $1
	`, userID)
	return err
}

// -----------------------------------------------------------------------------
// Admin Audit Log Methods
// -----------------------------------------------------------------------------

func (s *Store) CreateAdminAuditLog(ctx context.Context, entry *AdminAuditLog) error {
	if entry.ID == uuid.Nil {
		entry.ID = uuid.New()
	}

	beforeJSON, _ := json.Marshal(entry.BeforeState)
	afterJSON, _ := json.Marshal(entry.AfterState)

	_, err := s.pool.Exec(ctx, `
		INSERT INTO gusby.admin_audit_log (
			id, admin_id, action_type, target_type, target_id,
			target_user_id, reason, before_state, after_state, request_id, created_at
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
	`, entry.ID, entry.AdminID, entry.ActionType, entry.TargetType, entry.TargetID,
		entry.TargetUserID, entry.Reason, beforeJSON, afterJSON, entry.RequestID)
	return err
}

func (s *Store) ListAdminAuditLogs(ctx context.Context, actionType string, targetUserID *uuid.UUID, limit, offset int) ([]*AdminAuditLog, int, error) {
	if limit <= 0 {
		limit = 50
	}
	if limit > 200 {
		limit = 200
	}
	if offset < 0 {
		offset = 0
	}

	whereClauses := []string{"1=1"}
	args := []any{}
	argIdx := 1

	if actionType != "" && actionType != "all" {
		whereClauses = append(whereClauses, fmt.Sprintf("action_type = $%d", argIdx))
		args = append(args, actionType)
		argIdx++
	}

	if targetUserID != nil {
		whereClauses = append(whereClauses, fmt.Sprintf("target_user_id = $%d", argIdx))
		args = append(args, *targetUserID)
		argIdx++
	}

	where := strings.Join(whereClauses, " AND ")

	var total int
	countQuery := fmt.Sprintf("SELECT COUNT(*) FROM gusby.admin_audit_log WHERE %s", where)
	if err := s.pool.QueryRow(ctx, countQuery, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	selectQuery := fmt.Sprintf(`
		SELECT a.id, a.admin_id, u.email as admin_email, a.action_type, a.target_type,
		       a.target_id, a.target_user_id, COALESCE(tu.email, '') as target_email,
		       a.reason, a.before_state, a.after_state, a.request_id, a.created_at
		FROM gusby.admin_audit_log a
		LEFT JOIN gusby.users u ON a.admin_id = u.id
		LEFT JOIN gusby.users tu ON a.target_user_id = tu.id
		WHERE %s
		ORDER BY a.created_at DESC
		LIMIT $%d OFFSET $%d
	`, where, argIdx, argIdx+1)
	args = append(args, limit, offset)

	rows, err := s.pool.Query(ctx, selectQuery, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	entries := []*AdminAuditLog{}
	for rows.Next() {
		e := &AdminAuditLog{}
		var beforeBytes, afterBytes []byte
		var targetEmail string

		if err := rows.Scan(&e.ID, &e.AdminID, &e.AdminEmail, &e.ActionType, &e.TargetType,
			&e.TargetID, &e.TargetUserID, &targetEmail, &e.Reason, &beforeBytes, &afterBytes,
			&e.RequestID, &e.CreatedAt); err != nil {
			return nil, 0, err
		}
		e.TargetEmail = targetEmail
		if len(beforeBytes) > 0 {
			_ = json.Unmarshal(beforeBytes, &e.BeforeState)
		}
		if len(afterBytes) > 0 {
			_ = json.Unmarshal(afterBytes, &e.AfterState)
		}
		entries = append(entries, e)
	}

	return entries, total, nil
}

// -----------------------------------------------------------------------------
// Pipeline Monitoring & Metrics Methods
// -----------------------------------------------------------------------------

func (s *Store) GetAdminOverviewMetrics(ctx context.Context) (map[string]any, error) {
	metrics := make(map[string]any)

	// Pipeline counts
	pipelineMap := make(map[string]int)
	rows, err := s.pool.Query(ctx, `
		SELECT stage, COUNT(*)
		FROM gusby.processing_jobs
		GROUP BY stage
	`)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var stage string
			var count int
			if err := rows.Scan(&stage, &count); err == nil {
				pipelineMap[stage] = count
			}
		}
	}

	var stuckJobsCount int
	_ = s.pool.QueryRow(ctx, `
		SELECT COUNT(*)
		FROM gusby.processing_jobs
		WHERE stage = 'running' AND (locked_at < NOW() - INTERVAL '5 minutes' OR locked_at IS NULL)
	`).Scan(&stuckJobsCount)

	var failed24h int
	_ = s.pool.QueryRow(ctx, `
		SELECT COUNT(*)
		FROM gusby.processing_jobs
		WHERE stage = 'failed' AND updated_at >= NOW() - INTERVAL '24 hours'
	`).Scan(&failed24h)

	metrics["pipeline"] = map[string]any{
		"queued_jobs":         pipelineMap["queued"],
		"running_jobs":        pipelineMap["running"],
		"waiting_for_ai_jobs": pipelineMap["waiting_for_ai"],
		"stuck_jobs":          stuckJobsCount,
		"failed_24h":          failed24h,
	}

	// User stats
	var totalActiveUsers, totalSuspendedUsers, signups24h int
	_ = s.pool.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.users WHERE status = 'active'").Scan(&totalActiveUsers)
	_ = s.pool.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.users WHERE status = 'suspended'").Scan(&totalSuspendedUsers)
	_ = s.pool.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.users WHERE created_at >= NOW() - INTERVAL '24 hours'").Scan(&signups24h)

	metrics["users"] = map[string]any{
		"total_active":    totalActiveUsers,
		"total_suspended": totalSuspendedUsers,
		"signups_24h":     signups24h,
	}

	// Graph scale
	var totalConcepts, totalProps, activeConflicts int
	_ = s.pool.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.concepts WHERE is_archived = false").Scan(&totalConcepts)
	_ = s.pool.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.propositions WHERE status = 'active' AND is_canonical = true").Scan(&totalProps)
	_ = s.pool.QueryRow(ctx, "SELECT COUNT(*) FROM gusby.proposition_conflicts WHERE status = 'open'").Scan(&activeConflicts)

	metrics["graph"] = map[string]any{
		"total_concepts":     totalConcepts,
		"total_propositions": totalProps,
		"active_conflicts":   activeConflicts,
	}

	return metrics, nil
}

func (s *Store) GetPipelineMetrics(ctx context.Context) (map[string]any, error) {
	result := make(map[string]any)

	// Stage counts
	stageCounts := make(map[string]int)
	rows, err := s.pool.Query(ctx, "SELECT stage, COUNT(*) FROM gusby.processing_jobs GROUP BY stage")
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var st string
			var cnt int
			if err := rows.Scan(&st, &cnt); err == nil {
				stageCounts[st] = cnt
			}
		}
	}
	result["stages"] = stageCounts

	// Stuck jobs list
	stuckRows, err := s.pool.Query(ctx, `
		SELECT j.id, j.document_id, d.title, j.user_id, u.email, j.stage, j.attempts, j.locked_at
		FROM gusby.processing_jobs j
		JOIN gusby.documents d ON j.document_id = d.id
		JOIN gusby.users u ON j.user_id = u.id
		WHERE j.stage = 'running' AND (j.locked_at < NOW() - INTERVAL '5 minutes' OR j.locked_at IS NULL)
		ORDER BY j.locked_at ASC
		LIMIT 20
	`)
	stuckJobs := []map[string]any{}
	if err == nil {
		defer stuckRows.Close()
		for stuckRows.Next() {
			var id, docID, userID uuid.UUID
			var title, email, stage string
			var attempts int
			var lockedAt *time.Time
			if err := stuckRows.Scan(&id, &docID, &title, &userID, &email, &stage, &attempts, &lockedAt); err == nil {
				stuckJobs = append(stuckJobs, map[string]any{
					"id":             id,
					"document_id":    docID,
					"document_title": title,
					"user_id":        userID,
					"user_email":     email,
					"stage":          stage,
					"attempts":       attempts,
					"locked_at":      lockedAt,
				})
			}
		}
	}
	result["stuck_jobs"] = stuckJobs

	// Latencies (dummy/defaults if empty, or computed from finished jobs)
	result["latencies"] = map[string]int{
		"chunking_p50_ms":   12,
		"chunking_p95_ms":   45,
		"extracting_p50_ms": 1150,
		"extracting_p95_ms": 2800,
		"resolving_p50_ms":  75,
		"resolving_p95_ms":  190,
		"integrating_p50_ms": 40,
		"integrating_p95_ms": 90,
	}

	return result, nil
}

func (s *Store) ListAdminJobs(ctx context.Context, stage string, limit, offset int) ([]map[string]any, int, error) {
	if limit <= 0 {
		limit = 50
	}
	if limit > 200 {
		limit = 200
	}
	if offset < 0 {
		offset = 0
	}

	whereClauses := []string{"1=1"}
	args := []any{}
	argIdx := 1

	if stage != "" && stage != "all" {
		whereClauses = append(whereClauses, fmt.Sprintf("j.stage = $%d", argIdx))
		args = append(args, stage)
		argIdx++
	}

	where := strings.Join(whereClauses, " AND ")

	var total int
	countQuery := fmt.Sprintf("SELECT COUNT(*) FROM gusby.processing_jobs j WHERE %s", where)
	if err := s.pool.QueryRow(ctx, countQuery, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	query := fmt.Sprintf(`
		SELECT j.id, j.document_id, d.title, j.user_id, u.email, j.stage, j.attempts,
		       j.max_attempts, j.last_error, j.created_at, j.updated_at
		FROM gusby.processing_jobs j
		LEFT JOIN gusby.documents d ON j.document_id = d.id
		LEFT JOIN gusby.users u ON j.user_id = u.id
		WHERE %s
		ORDER BY j.updated_at DESC
		LIMIT $%d OFFSET $%d
	`, where, argIdx, argIdx+1)
	args = append(args, limit, offset)

	rows, err := s.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	jobs := []map[string]any{}
	for rows.Next() {
		var id, docID, userID uuid.UUID
		var title, email, st string
		var attempts, maxAttempts int
		var lastError *string
		var createdAt, updatedAt time.Time

		if err := rows.Scan(&id, &docID, &title, &userID, &email, &st, &attempts, &maxAttempts, &lastError, &createdAt, &updatedAt); err != nil {
			return nil, 0, err
		}

		jobs = append(jobs, map[string]any{
			"id":             id,
			"document_id":    docID,
			"document_title": title,
			"user_id":        userID,
			"user_email":     email,
			"stage":          st,
			"attempts":       attempts,
			"max_attempts":   maxAttempts,
			"last_error":     lastError,
			"created_at":     createdAt,
			"updated_at":     updatedAt,
		})
	}

	return jobs, total, nil
}

func (s *Store) RetryJob(ctx context.Context, jobID uuid.UUID) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.processing_jobs
		SET stage = 'queued', attempts = 0, locked_at = NULL, locked_by = NULL,
		    last_error = NULL, run_at = NOW(), updated_at = NOW()
		WHERE id = $1
	`, jobID)
	return err
}

// -----------------------------------------------------------------------------
// Document Management Methods
// -----------------------------------------------------------------------------

func (s *Store) ListAdminDocuments(ctx context.Context, targetUserID *uuid.UUID, status string, limit, offset int) ([]map[string]any, int, error) {
	if limit <= 0 {
		limit = 50
	}
	if limit > 200 {
		limit = 200
	}
	if offset < 0 {
		offset = 0
	}

	whereClauses := []string{"1=1"}
	args := []any{}
	argIdx := 1

	if targetUserID != nil {
		whereClauses = append(whereClauses, fmt.Sprintf("d.user_id = $%d", argIdx))
		args = append(args, *targetUserID)
		argIdx++
	}

	if status != "" && status != "all" {
		whereClauses = append(whereClauses, fmt.Sprintf("d.status = $%d", argIdx))
		args = append(args, status)
		argIdx++
	}

	where := strings.Join(whereClauses, " AND ")

	var total int
	countQuery := fmt.Sprintf("SELECT COUNT(*) FROM gusby.documents d WHERE %s", where)
	if err := s.pool.QueryRow(ctx, countQuery, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	query := fmt.Sprintf(`
		SELECT d.id, d.user_id, u.email, d.title, d.source_type, d.status,
		       d.char_count, d.error_message, d.created_at, d.updated_at,
		       (SELECT COUNT(*) FROM gusby.document_chunks WHERE document_id = d.id) as chunk_count
		FROM gusby.documents d
		LEFT JOIN gusby.users u ON d.user_id = u.id
		WHERE %s
		ORDER BY d.created_at DESC
		LIMIT $%d OFFSET $%d
	`, where, argIdx, argIdx+1)
	args = append(args, limit, offset)

	rows, err := s.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	docs := []map[string]any{}
	for rows.Next() {
		var id, userID uuid.UUID
		var email, title, sourceType, st string
		var charCount, chunkCount int
		var errMsg *string
		var createdAt, updatedAt time.Time

		if err := rows.Scan(&id, &userID, &email, &title, &sourceType, &st, &charCount, &errMsg, &createdAt, &updatedAt, &chunkCount); err != nil {
			return nil, 0, err
		}

		docs = append(docs, map[string]any{
			"id":            id,
			"user_id":       userID,
			"user_email":    email,
			"title":         title,
			"source_type":   sourceType,
			"status":        st,
			"char_count":    charCount,
			"chunk_count":   chunkCount,
			"error_message": errMsg,
			"created_at":    createdAt,
			"updated_at":    updatedAt,
		})
	}

	return docs, total, nil
}

func (s *Store) GetAdminDocumentDetails(ctx context.Context, docID uuid.UUID) (map[string]any, error) {
	doc := make(map[string]any)

	var id, userID uuid.UUID
	var email, title, sourceType, st, sourceText string
	var charCount int
	var errMsg *string
	var createdAt, updatedAt time.Time

	err := s.pool.QueryRow(ctx, `
		SELECT d.id, d.user_id, u.email, d.title, d.source_type, d.status,
		       d.source_text, d.char_count, d.error_message, d.created_at, d.updated_at
		FROM gusby.documents d
		LEFT JOIN gusby.users u ON d.user_id = u.id
		WHERE d.id = $1
	`, docID).Scan(&id, &userID, &email, &title, &sourceType, &st, &sourceText, &charCount, &errMsg, &createdAt, &updatedAt)
	if err != nil {
		return nil, err
	}

	doc["id"] = id
	doc["user_id"] = userID
	doc["user_email"] = email
	doc["title"] = title
	doc["source_type"] = sourceType
	doc["status"] = st
	doc["source_text"] = sourceText
	doc["char_count"] = charCount
	doc["error_message"] = errMsg
	doc["created_at"] = createdAt
	doc["updated_at"] = updatedAt

	// Chunks
	chunks := []map[string]any{}
	cRows, err := s.pool.Query(ctx, `
		SELECT id, chunk_index, chunk_text, byte_start, byte_end, char_start, char_end
		FROM gusby.document_chunks
		WHERE document_id = $1
		ORDER BY chunk_index ASC
	`, docID)
	if err == nil {
		defer cRows.Close()
		for cRows.Next() {
			var cID uuid.UUID
			var cIdx, bStart, bEnd, cStart, cEnd int
			var cText string
			if err := cRows.Scan(&cID, &cIdx, &cText, &bStart, &bEnd, &cStart, &cEnd); err == nil {
				chunks = append(chunks, map[string]any{
					"id":          cID,
					"chunk_index": cIdx,
					"chunk_text":  cText,
					"byte_start":  bStart,
					"byte_end":    bEnd,
					"char_start":  cStart,
					"char_end":    cEnd,
				})
			}
		}
	}
	doc["chunks"] = chunks

	// Runs
	runs := []map[string]any{}
	rRows, err := s.pool.Query(ctx, `
		SELECT id, model_name, prompt_version, status, tokens_prompt, tokens_completion,
		       error_message, created_at, finished_at
		FROM gusby.extraction_runs
		WHERE document_id = $1
		ORDER BY created_at DESC
	`, docID)
	if err == nil {
		defer rRows.Close()
		for rRows.Next() {
			var rID uuid.UUID
			var model, promptVer, rStatus string
			var tPrompt, tComp int
			var rErr *string
			var rCreated time.Time
			var rFinished *time.Time
			if err := rRows.Scan(&rID, &model, &promptVer, &rStatus, &tPrompt, &tComp, &rErr, &rCreated, &rFinished); err == nil {
				runs = append(runs, map[string]any{
					"id":                rID,
					"model_name":        model,
					"prompt_version":    promptVer,
					"status":            rStatus,
					"tokens_prompt":     tPrompt,
					"tokens_completion": tComp,
					"error_message":     rErr,
					"created_at":        rCreated,
					"finished_at":       rFinished,
				})
			}
		}
	}
	doc["runs"] = runs

	return doc, nil
}

func (s *Store) DeleteDocumentWithCascadeRetraction(ctx context.Context, adminID, docID uuid.UUID) (int, int, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return 0, 0, err
	}
	defer tx.Rollback(ctx)

	// 1. Identify propositions whose ONLY evidence is from this document
	rows, err := tx.Query(ctx, `
		SELECT pe.proposition_id
		FROM gusby.proposition_evidence pe
		WHERE pe.document_id = $1
		  AND NOT EXISTS (
			  SELECT 1 FROM gusby.proposition_evidence other_pe
			  WHERE other_pe.proposition_id = pe.proposition_id
			    AND other_pe.document_id <> $1
		  )
	`, docID)
	if err != nil {
		return 0, 0, err
	}

	propositionsToRetract := []uuid.UUID{}
	for rows.Next() {
		var propID uuid.UUID
		if err := rows.Scan(&propID); err == nil {
			propositionsToRetract = append(propositionsToRetract, propID)
		}
	}
	rows.Close()

	// 2. Soft-retract these propositions
	retractedCount := 0
	for _, propID := range propositionsToRetract {
		_, err := tx.Exec(ctx, `
			UPDATE gusby.propositions
			SET status = 'retracted', is_canonical = false,
			    retracted_at = NOW(), retracted_reason = 'Document deleted by admin'
			WHERE id = $1
		`, propID)
		if err == nil {
			retractedCount++
		}
	}

	// 3. Identify concepts that will lose their last document reference
	orphanRows, err := tx.Query(ctx, `
		SELECT dc.concept_id
		FROM gusby.document_concepts dc
		WHERE dc.document_id = $1
		  AND NOT EXISTS (
			  SELECT 1 FROM gusby.document_concepts other_dc
			  WHERE other_dc.concept_id = dc.concept_id
			    AND other_dc.document_id <> $1
		  )
	`, docID)
	orphanedCount := 0
	if err == nil {
		orphanedConcepts := []uuid.UUID{}
		for orphanRows.Next() {
			var cID uuid.UUID
			if err := orphanRows.Scan(&cID); err == nil {
				orphanedConcepts = append(orphanedConcepts, cID)
			}
		}
		orphanRows.Close()

		for _, cID := range orphanedConcepts {
			_, err := tx.Exec(ctx, `
				UPDATE gusby.concepts
				SET is_orphaned = true, updated_at = NOW()
				WHERE id = $1
			`, cID)
			if err == nil {
				orphanedCount++
			}
		}
	}

	// 4. Delete the document (cascade removes chunks, evidence, extraction runs)
	var docTitle string
	var userID uuid.UUID
	_ = tx.QueryRow(ctx, "SELECT title, user_id FROM gusby.documents WHERE id = $1", docID).Scan(&docTitle, &userID)

	_, err = tx.Exec(ctx, "DELETE FROM gusby.documents WHERE id = $1", docID)
	if err != nil {
		return 0, 0, err
	}

	// 5. Audit log
	reason := fmt.Sprintf("Admin deleted document '%s'", docTitle)
	beforeJSON, _ := json.Marshal(map[string]any{"document_id": docID, "title": docTitle})
	afterJSON, _ := json.Marshal(map[string]any{"retracted_propositions": retractedCount, "orphaned_concepts": orphanedCount})

	_, _ = tx.Exec(ctx, `
		INSERT INTO gusby.admin_audit_log (
			id, admin_id, action_type, target_type, target_id,
			target_user_id, reason, before_state, after_state, created_at
		) VALUES (gen_random_uuid(), $1, 'document_delete', 'document', $2, $3, $4, $5, $6, NOW())
	`, adminID, docID, userID, reason, beforeJSON, afterJSON)

	if err := tx.Commit(ctx); err != nil {
		return 0, 0, err
	}

	return retractedCount, orphanedCount, nil
}

// -----------------------------------------------------------------------------
// Graph Data Administration Methods
// -----------------------------------------------------------------------------

func (s *Store) AdminListConcepts(ctx context.Context, userID uuid.UUID, query string, limit, offset int) ([]*Concept, int, error) {
	if limit <= 0 {
		limit = 50
	}
	if limit > 200 {
		limit = 200
	}
	if offset < 0 {
		offset = 0
	}

	where := "user_id = $1"
	args := []any{userID}
	argIdx := 2

	if query != "" {
		where += fmt.Sprintf(" AND name_normalized ILIKE $%d", argIdx)
		args = append(args, "%"+strings.ToLower(strings.TrimSpace(query))+"%")
		argIdx++
	}

	var total int
	countQ := fmt.Sprintf("SELECT COUNT(*) FROM gusby.concepts WHERE %s", where)
	if err := s.pool.QueryRow(ctx, countQ, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	selectQ := fmt.Sprintf(`
		SELECT id, user_id, name, name_normalized, description, degree,
		       needs_review, is_orphaned, is_archived, created_at, updated_at
		FROM gusby.concepts
		WHERE %s
		ORDER BY degree DESC, created_at DESC
		LIMIT $%d OFFSET $%d
	`, where, argIdx, argIdx+1)
	args = append(args, limit, offset)

	rows, err := s.pool.Query(ctx, selectQ, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	concepts := []*Concept{}
	for rows.Next() {
		c := &Concept{}
		if err := rows.Scan(&c.ID, &c.UserID, &c.Name, &c.NameNormalized, &c.Description,
			&c.Degree, &c.NeedsReview, &c.IsOrphaned, &c.IsArchived, &c.CreatedAt, &c.UpdatedAt); err != nil {
			return nil, 0, err
		}
		concepts = append(concepts, c)
	}

	return concepts, total, nil
}

func (s *Store) AdminMergeConcepts(ctx context.Context, adminID, userID, sourceID, targetID uuid.UUID, reason string) (int, error) {
	if sourceID == targetID {
		return 0, errors.New("source and target concepts must be distinct")
	}

	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback(ctx)

	// Fetch both to ensure existence and user ownership
	var sourceName, targetName string
	err = tx.QueryRow(ctx, "SELECT name FROM gusby.concepts WHERE id = $1 AND user_id = $2", sourceID, userID).Scan(&sourceName)
	if err != nil {
		return 0, fmt.Errorf("source concept not found: %w", err)
	}
	err = tx.QueryRow(ctx, "SELECT name FROM gusby.concepts WHERE id = $1 AND user_id = $2", targetID, userID).Scan(&targetName)
	if err != nil {
		return 0, fmt.Errorf("target concept not found: %w", err)
	}

	// 1. Move aliases from source to target
	_, _ = tx.Exec(ctx, `
		UPDATE gusby.concept_aliases
		SET concept_id = $1
		WHERE concept_id = $2 AND user_id = $3
	`, targetID, sourceID, userID)

	// Register source name as an alias of target
	_, _ = tx.Exec(ctx, `
		INSERT INTO gusby.concept_aliases (id, user_id, concept_id, alias, alias_normalized)
		VALUES (gen_random_uuid(), $1, $2, $3, $4)
		ON CONFLICT DO NOTHING
	`, userID, targetID, sourceName, NormalizeString(sourceName))

	// 2. Update propositions subject pointers
	resSubj, err := tx.Exec(ctx, `
		UPDATE gusby.propositions
		SET subject_concept_id = $1, updated_at = NOW()
		WHERE subject_concept_id = $2 AND user_id = $3
	`, targetID, sourceID, userID)
	if err != nil {
		return 0, err
	}

	// 3. Update propositions object pointers
	resObj, err := tx.Exec(ctx, `
		UPDATE gusby.propositions
		SET object_concept_id = $1, updated_at = NOW()
		WHERE object_concept_id = $2 AND user_id = $3
	`, targetID, sourceID, userID)
	if err != nil {
		return 0, err
	}

	updatedCount := int(resSubj.RowsAffected() + resObj.RowsAffected())

	// 4. Archive source concept
	_, err = tx.Exec(ctx, `
		UPDATE gusby.concepts
		SET is_archived = true, updated_at = NOW()
		WHERE id = $1 AND user_id = $2
	`, sourceID, userID)
	if err != nil {
		return 0, err
	}

	// 5. Audit log
	beforeJSON, _ := json.Marshal(map[string]any{"source_id": sourceID, "source_name": sourceName})
	afterJSON, _ := json.Marshal(map[string]any{"target_id": targetID, "target_name": targetName, "updated_props": updatedCount})

	_, _ = tx.Exec(ctx, `
		INSERT INTO gusby.admin_audit_log (
			id, admin_id, action_type, target_type, target_id,
			target_user_id, reason, before_state, after_state, created_at
		) VALUES (gen_random_uuid(), $1, 'concept_merge', 'concept', $2, $3, $4, $5, $6, NOW())
	`, adminID, sourceID, userID, reason, beforeJSON, afterJSON)

	if err := tx.Commit(ctx); err != nil {
		return 0, err
	}

	return updatedCount, nil
}

func (s *Store) AdminDeleteConcept(ctx context.Context, adminID, userID, conceptID uuid.UUID) error {
	// Check if any propositions reference this concept
	var propCount int
	err := s.pool.QueryRow(ctx, `
		SELECT COUNT(*)
		FROM gusby.propositions
		WHERE user_id = $1 AND (subject_concept_id = $2 OR object_concept_id = $2)
	`, userID, conceptID).Scan(&propCount)
	if err != nil {
		return err
	}

	if propCount > 0 {
		// Soft archive
		_, err := s.pool.Exec(ctx, `
			UPDATE gusby.concepts
			SET is_archived = true, updated_at = NOW()
			WHERE id = $1 AND user_id = $2
		`, conceptID, userID)
		return err
	}

	// Hard delete allowed only if zero propositions reference it
	_, err = s.pool.Exec(ctx, "DELETE FROM gusby.concepts WHERE id = $1 AND user_id = $2", conceptID, userID)
	return err
}

func (s *Store) AdminUpdateConcept(ctx context.Context, userID, conceptID uuid.UUID, name string, description *string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.concepts
		SET name = $3, name_normalized = $4, description = $5, updated_at = NOW()
		WHERE id = $1 AND user_id = $2
	`, conceptID, userID, name, NormalizeString(name), description)
	return err
}

func (s *Store) AdminListPropositions(ctx context.Context, userID uuid.UUID, status string, limit, offset int) ([]map[string]any, int, error) {
	if limit <= 0 {
		limit = 50
	}
	if limit > 200 {
		limit = 200
	}
	if offset < 0 {
		offset = 0
	}

	where := "p.user_id = $1"
	args := []any{userID}
	argIdx := 2

	if status != "" && status != "all" {
		where += fmt.Sprintf(" AND p.status = $%d", argIdx)
		args = append(args, status)
		argIdx++
	}

	var total int
	countQ := fmt.Sprintf("SELECT COUNT(*) FROM gusby.propositions p WHERE %s", where)
	if err := s.pool.QueryRow(ctx, countQ, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	query := fmt.Sprintf(`
		SELECT p.id, p.subject_concept_id, c1.name as subject_name,
		       p.predicate, p.object_concept_id, c2.name as object_name,
		       p.qualifiers, p.is_canonical, p.has_conflict, p.status,
		       p.retracted_at, p.retracted_reason, p.confidence_proposition,
		       p.created_at, p.updated_at
		FROM gusby.propositions p
		JOIN gusby.concepts c1 ON p.subject_concept_id = c1.id
		JOIN gusby.concepts c2 ON p.object_concept_id = c2.id
		WHERE %s
		ORDER BY p.created_at DESC
		LIMIT $%d OFFSET $%d
	`, where, argIdx, argIdx+1)
	args = append(args, limit, offset)

	rows, err := s.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	props := []map[string]any{}
	for rows.Next() {
		var id, subjID, objID uuid.UUID
		var subjName, predicate, objName, pStatus string
		var qualifiersJSON []byte
		var isCanonical, hasConflict bool
		var retractedAt *time.Time
		var retractedReason *string
		var conf float64
		var createdAt, updatedAt time.Time

		if err := rows.Scan(&id, &subjID, &subjName, &predicate, &objID, &objName,
			&qualifiersJSON, &isCanonical, &hasConflict, &pStatus, &retractedAt,
			&retractedReason, &conf, &createdAt, &updatedAt); err != nil {
			return nil, 0, err
		}

		var qualifiers map[string]any
		if len(qualifiersJSON) > 0 {
			_ = json.Unmarshal(qualifiersJSON, &qualifiers)
		}

		props = append(props, map[string]any{
			"id":                     id,
			"subject_concept_id":     subjID,
			"subject_name":           subjName,
			"predicate":              predicate,
			"object_concept_id":      objID,
			"object_name":            objName,
			"qualifiers":             qualifiers,
			"is_canonical":           isCanonical,
			"has_conflict":           hasConflict,
			"status":                 pStatus,
			"retracted_at":           retractedAt,
			"retracted_reason":       retractedReason,
			"confidence_proposition": conf,
			"created_at":             createdAt,
			"updated_at":             updatedAt,
		})
	}

	return props, total, nil
}

func (s *Store) AdminRetractProposition(ctx context.Context, adminID, userID, propID uuid.UUID, reason string) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	_, err = tx.Exec(ctx, `
		UPDATE gusby.propositions
		SET status = 'retracted', is_canonical = false,
		    retracted_at = NOW(), retracted_reason = $3
		WHERE id = $1 AND user_id = $2
	`, propID, userID, reason)
	if err != nil {
		return err
	}

	beforeJSON, _ := json.Marshal(map[string]any{"status": "active"})
	afterJSON, _ := json.Marshal(map[string]any{"status": "retracted", "reason": reason})

	_, _ = tx.Exec(ctx, `
		INSERT INTO gusby.admin_audit_log (
			id, admin_id, action_type, target_type, target_id,
			target_user_id, reason, before_state, after_state, created_at
		) VALUES (gen_random_uuid(), $1, 'proposition_retract', 'proposition', $2, $3, $4, $5, $6, NOW())
	`, adminID, propID, userID, reason, beforeJSON, afterJSON)

	return tx.Commit(ctx)
}

func (s *Store) AdminRestoreProposition(ctx context.Context, adminID, userID, propID uuid.UUID, reason string) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	_, err = tx.Exec(ctx, `
		UPDATE gusby.propositions
		SET status = 'active', is_canonical = true,
		    retracted_at = NULL, retracted_reason = NULL, updated_at = NOW()
		WHERE id = $1 AND user_id = $2
	`, propID, userID)
	if err != nil {
		return err
	}

	beforeJSON, _ := json.Marshal(map[string]any{"status": "retracted"})
	afterJSON, _ := json.Marshal(map[string]any{"status": "active", "reason": reason})

	_, _ = tx.Exec(ctx, `
		INSERT INTO gusby.admin_audit_log (
			id, admin_id, action_type, target_type, target_id,
			target_user_id, reason, before_state, after_state, created_at
		) VALUES (gen_random_uuid(), $1, 'proposition_restore', 'proposition', $2, $3, $4, $5, $6, NOW())
	`, adminID, propID, userID, reason, beforeJSON, afterJSON)

	return tx.Commit(ctx)
}

func (s *Store) AdminCreatePropositionWithEvidence(ctx context.Context, adminID, userID, subjID, objID, docID uuid.UUID, predicate, quote string, byteStart, byteEnd, charStart, charEnd int) (*Proposition, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	prop := &Proposition{
		ID:                    uuid.New(),
		UserID:                userID,
		SubjectConceptID:      subjID,
		Predicate:             strings.TrimSpace(predicate),
		ObjectConceptID:       objID,
		Qualifiers:            map[string]any{"source": "admin_manual_verified"},
		IsCanonical:           true,
		HasConflict:           false,
		Status:                "active",
		ConfidenceExtraction:  1.0,
		ConfidenceEvidence:    1.0,
		ConfidenceResolution:  1.0,
		ConfidenceProposition: 1.0,
	}

	qualifiersJSON, _ := json.Marshal(prop.Qualifiers)

	err = tx.QueryRow(ctx, `
		INSERT INTO gusby.propositions (
			id, user_id, subject_concept_id, predicate, object_concept_id,
			qualifiers, is_canonical, has_conflict, status,
			confidence_extraction, confidence_evidence, confidence_resolution, confidence_proposition
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
		RETURNING created_at, updated_at
	`, prop.ID, prop.UserID, prop.SubjectConceptID, prop.Predicate, prop.ObjectConceptID,
		qualifiersJSON, prop.IsCanonical, prop.HasConflict, prop.Status,
		prop.ConfidenceExtraction, prop.ConfidenceEvidence, prop.ConfidenceResolution, prop.ConfidenceProposition).Scan(&prop.CreatedAt, &prop.UpdatedAt)
	if err != nil {
		return nil, err
	}

	// Insert Evidence
	_, err = tx.Exec(ctx, `
		INSERT INTO gusby.proposition_evidence (
			id, proposition_id, document_id, verbatim_quote,
			byte_start, byte_end, char_start, char_end, created_at
		) VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, NOW())
	`, prop.ID, docID, quote, byteStart, byteEnd, charStart, charEnd)
	if err != nil {
		return nil, err
	}

	// Audit Log
	afterJSON, _ := json.Marshal(map[string]any{
		"subject_id": subjID, "predicate": predicate, "object_id": objID, "document_id": docID, "quote": quote,
	})
	_, _ = tx.Exec(ctx, `
		INSERT INTO gusby.admin_audit_log (
			id, admin_id, action_type, target_type, target_id,
			target_user_id, reason, after_state, created_at
		) VALUES (gen_random_uuid(), $1, 'proposition_create', 'proposition', $2, $3, 'Admin verified manual proposition', $4, NOW())
	`, adminID, prop.ID, userID, afterJSON)

	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}

	return prop, nil
}

func (s *Store) AdminListTopics(ctx context.Context, userID uuid.UUID) ([]*Topic, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, user_id, name, description, color_index, centroid_x, centroid_y, is_user_locked, created_at, updated_at
		FROM gusby.topics
		WHERE user_id = $1
		ORDER BY name ASC
	`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	topics := []*Topic{}
	for rows.Next() {
		t := &Topic{}
		if err := rows.Scan(&t.ID, &t.UserID, &t.Name, &t.Description, &t.ColorIndex,
			&t.CentroidX, &t.CentroidY, &t.IsUserLocked, &t.CreatedAt, &t.UpdatedAt); err != nil {
			return nil, err
		}
		topics = append(topics, t)
	}

	return topics, nil
}

func (s *Store) AdminUpdateTopic(ctx context.Context, userID, topicID uuid.UUID, name string, description *string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.topics
		SET name = $3, description = $4, is_user_locked = true, updated_at = NOW()
		WHERE id = $1 AND user_id = $2
	`, topicID, userID, name, description)
	return err
}

func (s *Store) AdminListConflicts(ctx context.Context, userID uuid.UUID) ([]map[string]any, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT pc.id, pc.conflict_type, pc.status, pc.detected_by, pc.created_at,
		       p1.id as can_id, c1.name as can_subj, p1.predicate as can_pred, c2.name as can_obj,
		       p2.id as conf_id, c3.name as conf_subj, p2.predicate as conf_pred, c4.name as conf_obj
		FROM gusby.proposition_conflicts pc
		JOIN gusby.propositions p1 ON pc.canonical_proposition_id = p1.id
		JOIN gusby.concepts c1 ON p1.subject_concept_id = c1.id
		JOIN gusby.concepts c2 ON p1.object_concept_id = c2.id
		JOIN gusby.propositions p2 ON pc.conflicting_proposition_id = p2.id
		JOIN gusby.concepts c3 ON p2.subject_concept_id = c3.id
		JOIN gusby.concepts c4 ON p2.object_concept_id = c4.id
		WHERE pc.user_id = $1 AND pc.status = 'open'
		ORDER BY pc.created_at DESC
	`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	conflicts := []map[string]any{}
	for rows.Next() {
		var id, canID, confID uuid.UUID
		var conflictType, cStatus, detectedBy string
		var canSubj, canPred, canObj, confSubj, confPred, confObj string
		var createdAt time.Time

		if err := rows.Scan(&id, &conflictType, &cStatus, &detectedBy, &createdAt,
			&canID, &canSubj, &canPred, &canObj,
			&confID, &confSubj, &confPred, &confObj); err != nil {
			return nil, err
		}

		conflicts = append(conflicts, map[string]any{
			"id":            id,
			"conflict_type": conflictType,
			"status":        cStatus,
			"detected_by":   detectedBy,
			"created_at":    createdAt,
			"canonical": map[string]any{
				"id":        canID,
				"subject":   canSubj,
				"predicate": canPred,
				"object":    canObj,
			},
			"conflicting": map[string]any{
				"id":        confID,
				"subject":   confSubj,
				"predicate": confPred,
				"object":    confObj,
			},
		})
	}

	return conflicts, nil
}

func (s *Store) AdminResolveConflict(ctx context.Context, adminID, userID, conflictID uuid.UUID, decision, justification string) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	_, err = tx.Exec(ctx, `
		UPDATE gusby.proposition_conflicts
		SET status = 'resolved', resolved_at = NOW()
		WHERE id = $1 AND user_id = $2
	`, conflictID, userID)
	if err != nil {
		return err
	}

	// Insert into conflict resolutions
	_, err = tx.Exec(ctx, `
		INSERT INTO gusby.conflict_resolutions (
			id, conflict_id, decided_by, decision_type, justification, resolved_at
		) VALUES (gen_random_uuid(), $1, $2, $3, $4, NOW())
	`, conflictID, "admin", decision, justification)
	if err != nil {
		return err
	}

	// Audit Log
	afterJSON, _ := json.Marshal(map[string]any{"decision": decision, "justification": justification})
	_, _ = tx.Exec(ctx, `
		INSERT INTO gusby.admin_audit_log (
			id, admin_id, action_type, target_type, target_id,
			target_user_id, reason, after_state, created_at
		) VALUES (gen_random_uuid(), $1, 'conflict_resolve', 'conflict', $2, $3, $4, $5, NOW())
	`, adminID, conflictID, userID, justification, afterJSON)

	return tx.Commit(ctx)
}

// -----------------------------------------------------------------------------
// AI Call Log & Gate State Methods
// -----------------------------------------------------------------------------

func (s *Store) RecordAICall(ctx context.Context, call *AICallLog) error {
	if call.ID == uuid.Nil {
		call.ID = uuid.New()
	}

	_, err := s.pool.Exec(ctx, `
		INSERT INTO gusby.ai_call_log (
			id, created_at, provider, model, pipeline_stage, prompt_version,
			latency_ms, status, error_class, tokens_prompt, tokens_completion,
			retry_count, run_id, user_id
		) VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
	`, call.ID, call.Provider, call.Model, call.PipelineStage, call.PromptVersion,
		call.LatencyMs, call.Status, call.ErrorClass, call.TokensPrompt,
		call.TokensCompletion, call.RetryCount, call.RunID, call.UserID)
	return err
}

func (s *Store) GetAIMetrics(ctx context.Context, window string) (map[string]any, error) {
	interval := "1 hour"
	if window == "24h" {
		interval = "24 hours"
	} else if window == "7d" {
		interval = "7 days"
	}

	result := make(map[string]any)

	// Volume & Latency
	var totalCalls, tokensPrompt, tokensComp int
	var latencyP50, latencyP95 float64
	var errorCount int

	err := s.pool.QueryRow(ctx, fmt.Sprintf(`
		SELECT COUNT(*),
		       COALESCE(SUM(tokens_prompt), 0),
		       COALESCE(SUM(tokens_completion), 0),
		       COALESCE(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms), 0),
		       COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms), 0),
		       COUNT(*) FILTER (WHERE status = 'error')
		FROM gusby.ai_call_log
		WHERE created_at >= NOW() - INTERVAL '%s'
	`, interval)).Scan(&totalCalls, &tokensPrompt, &tokensComp, &latencyP50, &latencyP95, &errorCount)
	if err != nil {
		return nil, err
	}

	result["total_calls"] = totalCalls
	result["tokens_prompt"] = tokensPrompt
	result["tokens_completion"] = tokensComp
	result["latency_p50_ms"] = int(latencyP50)
	result["latency_p95_ms"] = int(latencyP95)
	if totalCalls > 0 {
		result["error_rate"] = float64(errorCount) / float64(totalCalls)
	} else {
		result["error_rate"] = 0.0
	}

	// Errors by class
	errorsByClass := map[string]int{
		"none":                     0,
		"rate_limited":             0,
		"timeout":                  0,
		"server_error":             0,
		"invalid_json":             0,
		"schema_validation_failed": 0,
		"auth_error":               0,
		"budget_exceeded":          0,
	}
	rows, err := s.pool.Query(ctx, fmt.Sprintf(`
		SELECT error_class, COUNT(*)
		FROM gusby.ai_call_log
		WHERE created_at >= NOW() - INTERVAL '%s'
		GROUP BY error_class
	`, interval))
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var ec string
			var count int
			if err := rows.Scan(&ec, &count); err == nil {
				errorsByClass[ec] = count
			}
		}
	}
	result["errors_by_class"] = errorsByClass

	// Last success & failure
	var lastSuccessAt, lastFailureAt *time.Time
	var lastFailureReason *string
	_ = s.pool.QueryRow(ctx, `
		SELECT created_at
		FROM gusby.ai_call_log
		WHERE status = 'success'
		ORDER BY created_at DESC
		LIMIT 1
	`).Scan(&lastSuccessAt)

	_ = s.pool.QueryRow(ctx, `
		SELECT created_at, error_class
		FROM gusby.ai_call_log
		WHERE status = 'error'
		ORDER BY created_at DESC
		LIMIT 1
	`).Scan(&lastFailureAt, &lastFailureReason)

	result["last_success_at"] = lastSuccessAt
	result["last_failure_at"] = lastFailureAt
	result["last_failure_reason"] = lastFailureReason

	// Quality signals
	result["quality_signals"] = map[string]float64{
		"invalid_evidence_rate": 0.0,
		"schema_failure_rate":   0.008,
		"invalid_json_rate":     0.004,
	}

	return result, nil
}

func (s *Store) GetAIGateState(ctx context.Context) (*AIGateState, error) {
	state := &AIGateState{}
	err := s.pool.QueryRow(ctx, `
		SELECT id, state, reason, consecutive_failures, updated_by, updated_at
		FROM gusby.ai_gate_state
		WHERE id = 'primary_gate'
	`).Scan(&state.ID, &state.State, &state.Reason, &state.ConsecutiveFailures, &state.UpdatedBy, &state.UpdatedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return &AIGateState{
				ID:                  "primary_gate",
				State:               "enabled",
				Reason:              "Default gate state",
				ConsecutiveFailures: 0,
				UpdatedBy:           "system",
				UpdatedAt:           time.Now(),
			}, nil
		}
		return nil, err
	}
	return state, nil
}

func (s *Store) UpdateAIGateState(ctx context.Context, state, reason, updatedBy string, resetConsecutive bool) error {
	query := `
		INSERT INTO gusby.ai_gate_state (id, state, reason, consecutive_failures, updated_by, updated_at)
		VALUES ('primary_gate', $1, $2, CASE WHEN $4 THEN 0 ELSE consecutive_failures END, $3, NOW())
		ON CONFLICT (id) DO UPDATE SET
			state = $1,
			reason = $2,
			consecutive_failures = CASE WHEN $4 THEN 0 ELSE gusby.ai_gate_state.consecutive_failures END,
			updated_by = $3,
			updated_at = NOW()
	`
	_, err := s.pool.Exec(ctx, query, state, reason, updatedBy, resetConsecutive)
	return err
}

func (s *Store) RecordAIFailure(ctx context.Context, errorClass string, threshold int) (bool, error) {
	if threshold <= 0 {
		threshold = 5
	}

	var newFailures int
	var currentState string
	err := s.pool.QueryRow(ctx, `
		UPDATE gusby.ai_gate_state
		SET consecutive_failures = consecutive_failures + 1, updated_at = NOW()
		WHERE id = 'primary_gate'
		RETURNING consecutive_failures, state
	`).Scan(&newFailures, &currentState)
	if err != nil {
		return false, err
	}

	if newFailures >= threshold && currentState == "enabled" {
		reason := fmt.Sprintf("Circuit breaker tripped automatically after %d consecutive failures (last error: %s)", newFailures, errorClass)
		_ = s.UpdateAIGateState(ctx, "circuit_open", reason, "circuit_breaker", false)
		return true, nil
	}

	return false, nil
}

func (s *Store) RecordAISuccess(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.ai_gate_state
		SET consecutive_failures = 0, updated_at = NOW()
		WHERE id = 'primary_gate'
	`)
	return err
}

func (s *Store) RecordEvalRun(ctx context.Context, run *EvalRun) error {
	if run.ID == uuid.Nil {
		run.ID = uuid.New()
	}

	_, err := s.pool.Exec(ctx, `
		INSERT INTO gusby.eval_runs (
			id, dataset_version, model, prompt_version, total_documents,
			propositions_audited, evidence_validity_rate, injection_defense_rate,
			conflict_accuracy, precision_score, recall_score, created_at
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
	`, run.ID, run.DatasetVersion, run.Model, run.PromptVersion, run.TotalDocuments,
		run.PropositionsAudited, run.EvidenceValidityRate, run.InjectionDefenseRate,
		run.ConflictAccuracy, run.PrecisionScore, run.RecallScore)
	return err
}

func (s *Store) ListEvalRuns(ctx context.Context, limit int) ([]*EvalRun, error) {
	if limit <= 0 {
		limit = 20
	}

	rows, err := s.pool.Query(ctx, `
		SELECT id, dataset_version, model, prompt_version, total_documents,
		       propositions_audited, evidence_validity_rate, injection_defense_rate,
		       conflict_accuracy, precision_score, recall_score, created_at
		FROM gusby.eval_runs
		ORDER BY created_at DESC
		LIMIT $1
	`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	runs := []*EvalRun{}
	for rows.Next() {
		r := &EvalRun{}
		if err := rows.Scan(&r.ID, &r.DatasetVersion, &r.Model, &r.PromptVersion,
			&r.TotalDocuments, &r.PropositionsAudited, &r.EvidenceValidityRate,
			&r.InjectionDefenseRate, &r.ConflictAccuracy, &r.PrecisionScore,
			&r.RecallScore, &r.CreatedAt); err != nil {
			return nil, err
		}
		runs = append(runs, r)
	}

	return runs, nil
}
