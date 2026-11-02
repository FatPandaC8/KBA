package pipeline

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"

	"gusby/internal/llm"
	"gusby/internal/store"
)

type ConceptExtractionOutput struct {
	Concepts []struct {
		Name       string  `json:"name"`
		Category   string  `json:"category"`
		CoreIdea   string  `json:"core_idea"`
		Confidence float64 `json:"confidence"`
	} `json:"concepts"`
}

type PropositionExtractionOutput struct {
	Propositions []struct {
		Subject       string         `json:"subject"`
		Predicate     string         `json:"predicate"`
		Object        string         `json:"object"`
		EvidenceQuote string         `json:"evidence_quote"`
		Confidence    float64        `json:"confidence"`
		Qualifiers    map[string]any `json:"qualifiers"`
	} `json:"propositions"`
}

type ExtractedChunkResult struct {
	Concepts     []*store.ExtractedConcept
	Propositions []*store.ExtractedProposition
	TokensPrompt int
	TokensComp   int
}

// ExtractChunk processes a single DocumentChunk through the two-stage LLM pipeline and deterministic evidence validation
func ExtractChunk(ctx context.Context, client llm.LLMClient, chunk *store.DocumentChunk) (*ExtractedChunkResult, error) {
	result := &ExtractedChunkResult{}

	// 1. Stage 1: Extract Concepts
	conceptPrompt := BuildConceptUserPrompt(chunk.ChunkText)
	rawConceptJSON, pTokens1, cTokens1, err := client.CompleteJSON(ctx, ConceptSystemPrompt, conceptPrompt, 2048, 0.1)
	if err != nil {
		return nil, fmt.Errorf("concept extraction failed: %w", err)
	}
	result.TokensPrompt += pTokens1
	result.TokensComp += cTokens1

	var conceptData ConceptExtractionOutput
	if err := json.Unmarshal([]byte(rawConceptJSON), &conceptData); err != nil {
		// Single bounded repair attempt
		repairPrompt := fmt.Sprintf("%s\n\nYour previous output was invalid JSON: %v. Return ONLY a valid JSON object matching the schema.", conceptPrompt, err)
		repairedJSON, pRepair, cRepair, rErr := client.CompleteJSON(ctx, ConceptSystemPrompt, repairPrompt, 2048, 0.1)
		if rErr != nil {
			return nil, fmt.Errorf("concept repair failed: %w", rErr)
		}
		result.TokensPrompt += pRepair
		result.TokensComp += cRepair
		if err := json.Unmarshal([]byte(repairedJSON), &conceptData); err != nil {
			return nil, fmt.Errorf("failed to parse concept JSON after repair: %w", err)
		}
	}

	var conceptNames []string
	for _, c := range conceptData.Concepts {
		if c.Name == "" {
			continue
		}
		ec := &store.ExtractedConcept{
			ID:              uuid.New(),
			UserID:          chunk.UserID,
			ChunkID:         chunk.ID,
			Name:            c.Name,
			Category:        c.Category,
			CoreIdea:        c.CoreIdea,
			ConfidenceScore: c.Confidence,
		}
		result.Concepts = append(result.Concepts, ec)
		conceptNames = append(conceptNames, c.Name)
	}

	if len(conceptNames) < 2 {
		// Need at least 2 concepts to form relationships
		return result, nil
	}

	// 2. Stage 2: Extract Propositions
	propPrompt := BuildPropositionUserPrompt(chunk.ChunkText, conceptNames)
	rawPropJSON, pTokens2, cTokens2, err := client.CompleteJSON(ctx, PropositionSystemPrompt, propPrompt, 2048, 0.1)
	if err != nil {
		return nil, fmt.Errorf("proposition extraction failed: %w", err)
	}
	result.TokensPrompt += pTokens2
	result.TokensComp += cTokens2

	var propData PropositionExtractionOutput
	if err := json.Unmarshal([]byte(rawPropJSON), &propData); err != nil {
		repairPrompt := fmt.Sprintf("%s\n\nYour previous output was invalid JSON: %v. Return ONLY a valid JSON object matching the schema.", propPrompt, err)
		repairedJSON, pRepair, cRepair, rErr := client.CompleteJSON(ctx, PropositionSystemPrompt, repairPrompt, 2048, 0.1)
		if rErr != nil {
			return nil, fmt.Errorf("proposition repair failed: %w", rErr)
		}
		result.TokensPrompt += pRepair
		result.TokensComp += cRepair
		if err := json.Unmarshal([]byte(repairedJSON), &propData); err != nil {
			return nil, fmt.Errorf("failed to parse proposition JSON after repair: %w", err)
		}
	}

	// 3. Stage 3: Deterministic Evidence Validation
	for _, p := range propData.Propositions {
		if p.Subject == "" || p.Predicate == "" || p.Object == "" {
			continue
		}

		span := ValidateEvidence(chunk.ChunkText, p.EvidenceQuote, chunk.ByteStart, chunk.CharStart)

		ep := &store.ExtractedProposition{
			ID:              uuid.New(),
			UserID:          chunk.UserID,
			ChunkID:         chunk.ID,
			SubjectRaw:      p.Subject,
			Predicate:       p.Predicate,
			ObjectRaw:       p.Object,
			EvidenceQuote:   p.EvidenceQuote,
			ConfidenceScore: p.Confidence,
			IsValidEvidence: span.IsValid,
		}

		if span.IsValid {
			ep.EvidenceByteStart = &span.DocumentByteStart
			ep.EvidenceByteEnd = &span.DocumentByteEnd
			ep.EvidenceCharStart = &span.DocumentCharStart
			ep.EvidenceCharEnd = &span.DocumentCharEnd
		}

		result.Propositions = append(result.Propositions, ep)
	}

	return result, nil
}

func PersistExtractedResults(ctx context.Context, s *store.Store, runID uuid.UUID, res *ExtractedChunkResult) error {
	tx, err := s.Pool().Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	for _, c := range res.Concepts {
		c.ExtractionRunID = runID
		_, err := tx.Exec(ctx, `
			INSERT INTO gusby.extracted_concepts (
				id, user_id, extraction_run_id, chunk_id, name, category, core_idea, confidence_score
			) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		`, c.ID, c.UserID, c.ExtractionRunID, c.ChunkID, c.Name, c.Category, c.CoreIdea, c.ConfidenceScore)
		if err != nil {
			return err
		}
	}

	for _, p := range res.Propositions {
		p.ExtractionRunID = runID
		_, err := tx.Exec(ctx, `
			INSERT INTO gusby.extracted_propositions (
				id, user_id, extraction_run_id, chunk_id, subject_raw, predicate, object_raw,
				evidence_quote, confidence_score, is_valid_evidence,
				evidence_byte_start, evidence_byte_end, evidence_char_start, evidence_char_end
			) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
		`, p.ID, p.UserID, p.ExtractionRunID, p.ChunkID, p.SubjectRaw, p.Predicate, p.ObjectRaw,
			p.EvidenceQuote, p.ConfidenceScore, p.IsValidEvidence,
			p.EvidenceByteStart, p.EvidenceByteEnd, p.EvidenceCharStart, p.EvidenceCharEnd)
		if err != nil {
			return err
		}
	}

	return tx.Commit(ctx)
}

func CreateExtractionRun(ctx context.Context, s *store.Store, userID, docID uuid.UUID, modelName, promptVer string) (uuid.UUID, error) {
	row := s.Pool().QueryRow(ctx, `
		INSERT INTO gusby.extraction_runs (user_id, document_id, model_name, prompt_version, status)
		VALUES ($1, $2, $3, $4, 'running')
		RETURNING id
	`, userID, docID, modelName, promptVer)

	var id uuid.UUID
	if err := row.Scan(&id); err != nil {
		return uuid.Nil, err
	}
	return id, nil
}

func FinishExtractionRun(ctx context.Context, s *store.Store, runID uuid.UUID, pTokens, cTokens int, err error) error {
	status := "completed"
	var errMsg *string
	if err != nil {
		status = "failed"
		msg := err.Error()
		errMsg = &msg
	}

	_, qErr := s.Pool().Exec(ctx, `
		UPDATE gusby.extraction_runs
		SET status = $2, tokens_prompt = $3, tokens_completion = $4, error_message = $5, completed_at = now()
		WHERE id = $1
	`, runID, status, pTokens, cTokens, errMsg)
	return qErr
}
