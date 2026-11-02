package graph

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"

	"gusby/internal/llm"
	"gusby/internal/pipeline"
	"gusby/internal/store"
)

type ConflictClassifierResponse struct {
	Classification           string         `json:"classification"`
	Confidence               float64        `json:"confidence"`
	Explanation              string         `json:"explanation"`
	ReconciliationQualifiers map[string]any `json:"reconciliation_qualifiers"`
}

type IntegrationSummary struct {
	CanonicalPropositions int
	IntegrationProposals  int
	DetectedConflicts     int
	RejectedNoEvidence    int
}

func IntegrateExtractedItems(
	ctx context.Context,
	s *store.Store,
	client llm.LLMClient,
	userID, docID uuid.UUID,
	res *pipeline.ExtractedChunkResult,
) (*IntegrationSummary, error) {
	summary := &IntegrationSummary{}

	// Map raw concept names to resolved Concepts
	conceptMap := make(map[string]*ResolutionResult)
	for _, rawConcept := range res.Concepts {
		resolved, err := ResolveConcept(ctx, s, client, userID, rawConcept.Name, rawConcept.Category, rawConcept.CoreIdea)
		if err != nil {
			return nil, fmt.Errorf("failed to resolve concept %q: %w", rawConcept.Name, err)
		}
		conceptMap[rawConcept.Name] = resolved

		// Link document to concept in Document Graph
		_, _ = s.Pool().Exec(ctx, `
			INSERT INTO gusby.document_concepts (user_id, document_id, concept_id)
			VALUES ($1, $2, $3)
			ON CONFLICT DO NOTHING
		`, userID, docID, resolved.Concept.ID)
	}

	// Process Propositions
	for _, rawProp := range res.Propositions {
		// Rule: Invalid or unsupported evidence is NEVER integrated into canonical graph
		if !rawProp.IsValidEvidence {
			summary.RejectedNoEvidence++
			continue
		}

		subjRes, okSubj := conceptMap[rawProp.SubjectRaw]
		objRes, okObj := conceptMap[rawProp.ObjectRaw]
		if !okSubj || !okObj || subjRes == nil || objRes == nil {
			continue
		}

		subjID := subjRes.Concept.ID
		objID := objRes.Concept.ID
		if subjID == objID {
			// Skip self-referential loops
			continue
		}

		// Calculate 4-dimension confidences
		confExtraction := rawProp.ConfidenceScore
		confEvidence := 1.0 // Verified deterministic verbatim match
		confResolution := (subjRes.Confidence + objRes.Confidence) / 2.0
		confProposition := rawProp.ConfidenceScore

		compositeConfidence := (confExtraction + confEvidence + confResolution + confProposition) / 4.0

		// Check for existing proposition with same Subject and Predicate (Conflict detection)
		existingProps, err := s.FindPropositionBySubjectAndPredicate(ctx, userID, subjID, rawProp.Predicate)
		if err != nil {
			return nil, fmt.Errorf("failed to check existing propositions: %w", err)
		}

		var conflictingProp *store.Proposition
		for _, ep := range existingProps {
			if ep.ObjectConceptID != objID {
				conflictingProp = ep
				break
			}
		}

		hasConflict := false
		if conflictingProp != nil && client != nil {
			// Compare claims and classify conflict
			summary.DetectedConflicts++
			hasConflict = true

			docDate := time.Now().Format("2006-01-02")
			userPrompt := pipeline.BuildConflictUserPrompt(
				subjRes.Concept.Name, rawProp.Predicate,
				conflictingProp.ObjectConceptID.String(), "Existing assertion in canonical graph", docDate,
				objRes.Concept.Name, rawProp.EvidenceQuote, docDate,
			)

			rawConflictJSON, _, _, cErr := client.CompleteJSON(ctx, pipeline.ConflictSystemPrompt, userPrompt, 1024, 0.1)
			conflictType := "contradiction"
			if cErr == nil {
				var cr ConflictClassifierResponse
				if jErr := json.Unmarshal([]byte(rawConflictJSON), &cr); jErr == nil && cr.Classification != "" {
					conflictType = cr.Classification
				}
			}

			// Save proposition first, then record conflict
			newProp := &store.Proposition{
				UserID:                userID,
				SubjectConceptID:      subjID,
				Predicate:             rawProp.Predicate,
				ObjectConceptID:       objID,
				IsCanonical:           true,
				HasConflict:           true,
				ConfidenceExtraction:  confExtraction,
				ConfidenceEvidence:    confEvidence,
				ConfidenceResolution:  confResolution,
				ConfidenceProposition: confProposition,
			}
			newProp, pErr := s.CreateProposition(ctx, newProp)
			if pErr == nil {
				_, _ = s.CreateConflict(ctx, &store.PropositionConflict{
					UserID:                   userID,
					CanonicalPropositionID:   conflictingProp.ID,
					ConflictingPropositionID: newProp.ID,
					ConflictType:             conflictType,
					DetectedBy:               "pipeline",
				})
			}
		}

		// 4-Dimension Confidence Integration Policy
		// High: Auto-integrate (all dimensions >= 0.85)
		if confExtraction >= 0.85 && confResolution >= 0.85 && confProposition >= 0.85 {
			prop := &store.Proposition{
				UserID:                userID,
				SubjectConceptID:      subjID,
				Predicate:             rawProp.Predicate,
				ObjectConceptID:       objID,
				IsCanonical:           true,
				HasConflict:           hasConflict,
				ConfidenceExtraction:  confExtraction,
				ConfidenceEvidence:    confEvidence,
				ConfidenceResolution:  confResolution,
				ConfidenceProposition: confProposition,
			}
			savedProp, err := s.CreateProposition(ctx, prop)
			if err != nil {
				return nil, fmt.Errorf("failed to save canonical proposition: %w", err)
			}

			// Save evidence
			bStart := 0
			bEnd := 0
			cStart := 0
			cEnd := 0
			if rawProp.EvidenceByteStart != nil {
				bStart = *rawProp.EvidenceByteStart
			}
			if rawProp.EvidenceByteEnd != nil {
				bEnd = *rawProp.EvidenceByteEnd
			}
			if rawProp.EvidenceCharStart != nil {
				cStart = *rawProp.EvidenceCharStart
			}
			if rawProp.EvidenceCharEnd != nil {
				cEnd = *rawProp.EvidenceCharEnd
			}

			_, err = s.CreateEvidence(ctx, &store.PropositionEvidence{
				UserID:        userID,
				PropositionID: savedProp.ID,
				DocumentID:    docID,
				ChunkID:       rawProp.ChunkID,
				Quote:         rawProp.EvidenceQuote,
				ByteStart:     bStart,
				ByteEnd:       bEnd,
				CharStart:     cStart,
				CharEnd:       cEnd,
			})
			if err != nil {
				return nil, fmt.Errorf("failed to save proposition evidence: %w", err)
			}
			summary.CanonicalPropositions++

		} else if compositeConfidence >= 0.65 {
			// Medium Confidence: Create Integration Proposal
			proposalPayload := map[string]any{
				"subject_id":     subjID,
				"subject_name":   subjRes.Concept.Name,
				"predicate":      rawProp.Predicate,
				"object_id":      objID,
				"object_name":    objRes.Concept.Name,
				"evidence_quote": rawProp.EvidenceQuote,
				"chunk_id":       rawProp.ChunkID,
			}
			_, _ = s.CreateProposal(ctx, &store.IntegrationProposal{
				UserID:                userID,
				DocumentID:            docID,
				ItemType:              "proposition",
				Payload:               proposalPayload,
				ConfidenceExtraction:  confExtraction,
				ConfidenceEvidence:    confEvidence,
				ConfidenceResolution:  confResolution,
				ConfidenceProposition: confProposition,
			})
			summary.IntegrationProposals++
		}
		// Low Confidence: Retained only within Document Graph (already in extracted_propositions)
	}

	return summary, nil
}
