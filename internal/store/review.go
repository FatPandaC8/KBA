package store

import (
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

func (s *Store) CreateProposal(ctx context.Context, p *IntegrationProposal) (*IntegrationProposal, error) {
	payloadBytes, err := json.Marshal(p.Payload)
	if err != nil {
		payloadBytes = []byte("{}")
	}

	row := s.pool.QueryRow(ctx, `
		INSERT INTO gusby.integration_proposals (
			user_id, document_id, item_type, payload,
			confidence_extraction, confidence_evidence, confidence_resolution, confidence_proposition,
			status
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending')
		RETURNING id, created_at
	`, p.UserID, p.DocumentID, p.ItemType, payloadBytes,
		p.ConfidenceExtraction, p.ConfidenceEvidence, p.ConfidenceResolution, p.ConfidenceProposition)

	if err := row.Scan(&p.ID, &p.CreatedAt); err != nil {
		return nil, err
	}
	p.Status = "pending"
	return p, nil
}

func (s *Store) ListPendingProposals(ctx context.Context, userID uuid.UUID) ([]*IntegrationProposal, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, user_id, document_id, item_type, payload,
		       confidence_extraction, confidence_evidence, confidence_resolution, confidence_proposition,
		       status, reviewer_type, review_notes, created_at, resolved_at
		FROM gusby.integration_proposals
		WHERE user_id = $1 AND status = 'pending'
		ORDER BY created_at DESC
	`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var proposals []*IntegrationProposal
	for rows.Next() {
		p := &IntegrationProposal{}
		var payloadBytes []byte
		if err := rows.Scan(
			&p.ID, &p.UserID, &p.DocumentID, &p.ItemType, &payloadBytes,
			&p.ConfidenceExtraction, &p.ConfidenceEvidence, &p.ConfidenceResolution, &p.ConfidenceProposition,
			&p.Status, &p.ReviewerType, &p.ReviewNotes, &p.CreatedAt, &p.ResolvedAt,
		); err != nil {
			return nil, err
		}
		_ = json.Unmarshal(payloadBytes, &p.Payload)
		proposals = append(proposals, p)
	}
	return proposals, nil
}

func (s *Store) ResolveProposal(ctx context.Context, userID, proposalID uuid.UUID, action, reviewerType, notes string) error {
	now := time.Now()
	_, err := s.pool.Exec(ctx, `
		UPDATE gusby.integration_proposals
		SET status = $3, reviewer_type = $4, review_notes = $5, resolved_at = $6
		WHERE user_id = $1 AND id = $2
	`, userID, proposalID, action, reviewerType, notes, now)
	return err
}

func (s *Store) CreateConflict(ctx context.Context, c *PropositionConflict) (*PropositionConflict, error) {
	row := s.pool.QueryRow(ctx, `
		INSERT INTO gusby.proposition_conflicts (
			user_id, canonical_proposition_id, conflicting_proposition_id, conflict_type, status, detected_by
		) VALUES ($1, $2, $3, $4, 'open', $5)
		RETURNING id, created_at
	`, c.UserID, c.CanonicalPropositionID, c.ConflictingPropositionID, c.ConflictType, c.DetectedBy)

	if err := row.Scan(&c.ID, &c.CreatedAt); err != nil {
		return nil, err
	}
	c.Status = "open"

	// Mark conflicting proposition in propositions table
	_, _ = s.pool.Exec(ctx, `
		UPDATE gusby.propositions SET has_conflict = true WHERE id IN ($1, $2)
	`, c.CanonicalPropositionID, c.ConflictingPropositionID)

	return c, nil
}

func (s *Store) ListOpenConflicts(ctx context.Context, userID uuid.UUID) ([]*PropositionConflict, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, user_id, canonical_proposition_id, conflicting_proposition_id, conflict_type, status, detected_by, created_at, resolved_at
		FROM gusby.proposition_conflicts
		WHERE user_id = $1 AND status = 'open'
		ORDER BY created_at DESC
	`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var conflicts []*PropositionConflict
	for rows.Next() {
		c := &PropositionConflict{}
		if err := rows.Scan(
			&c.ID, &c.UserID, &c.CanonicalPropositionID, &c.ConflictingPropositionID,
			&c.ConflictType, &c.Status, &c.DetectedBy, &c.CreatedAt, &c.ResolvedAt,
		); err != nil {
			return nil, err
		}
		conflicts = append(conflicts, c)
	}
	return conflicts, nil
}

func (s *Store) ResolveConflict(ctx context.Context, userID, conflictID uuid.UUID, decidedBy, choice, reason string) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	_, err = tx.Exec(ctx, `
		INSERT INTO gusby.conflict_resolutions (user_id, conflict_id, decided_by, resolution_choice, reason)
		VALUES ($1, $2, $3, $4, $5)
	`, userID, conflictID, decidedBy, choice, reason)
	if err != nil {
		return err
	}

	_, err = tx.Exec(ctx, `
		UPDATE gusby.proposition_conflicts
		SET status = 'resolved', resolved_at = now()
		WHERE user_id = $1 AND id = $2
	`, userID, conflictID)
	if err != nil {
		return err
	}

	return tx.Commit(ctx)
}
