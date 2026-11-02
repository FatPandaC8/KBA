package graph

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"gusby/internal/llm"
	"gusby/internal/pipeline"
	"gusby/internal/store"
)

type ResolutionResult struct {
	Concept    *store.Concept
	Confidence float64
	IsNew      bool
	IsMerged   bool
	Proposal   *store.IntegrationProposal
}

type EntityAdjudicationResponse struct {
	IsSameEntity  bool    `json:"is_same_entity"`
	CanonicalName string  `json:"canonical_name"`
	AliasToAdd    string  `json:"alias_to_add"`
	Confidence    float64 `json:"confidence"`
	Reasoning     string  `json:"reasoning"`
}

// ResolveConcept executes staged entity resolution:
// Stage 1: Exact / Alias match
// Stage 2: pg_trgm similarity
// Stage 3: LLM Adjudication for ambiguous cases
func ResolveConcept(
	ctx context.Context,
	s *store.Store,
	client llm.LLMClient,
	userID uuid.UUID,
	rawName, category, coreIdea string,
) (*ResolutionResult, error) {
	name := strings.TrimSpace(rawName)
	if name == "" {
		return nil, fmt.Errorf("concept name cannot be empty")
	}

	// Stage 1: Exact or registered alias match
	existing, err := s.FindConceptByExactOrAlias(ctx, userID, name)
	if err != nil {
		return nil, fmt.Errorf("exact match query failed: %w", err)
	}
	if existing != nil {
		return &ResolutionResult{
			Concept:    existing,
			Confidence: 1.0,
			IsNew:      false,
			IsMerged:   false,
		}, nil
	}

	// Stage 2: pg_trgm similarity lookup
	candidates, similarities, err := s.FindConceptsByTrigram(ctx, userID, name, 0.40, 3)
	if err != nil {
		return nil, fmt.Errorf("trigram search failed: %w", err)
	}

	if len(candidates) > 0 {
		topCandidate := candidates[0]
		topSim := similarities[0]

		// Clear high-confidence match (>= 0.85)
		if topSim >= 0.85 {
			_ = s.AddConceptAlias(ctx, userID, topCandidate.ID, name)
			return &ResolutionResult{
				Concept:    topCandidate,
				Confidence: topSim,
				IsNew:      false,
				IsMerged:   true,
			}, nil
		}

		// Ambiguous match [0.65, 0.88) -> Invoke LLM Adjudication
		if client != nil {
			descA := ""
			if topCandidate.Description != nil {
				descA = *topCandidate.Description
			}
			userPrompt := pipeline.BuildEntityAdjudicationUserPrompt(topCandidate.Name, descA, name, coreIdea)
			rawJSON, _, _, err := client.CompleteJSON(ctx, pipeline.EntityAdjudicationSystemPrompt, userPrompt, 1024, 0.1)
			if err == nil {
				var adj EntityAdjudicationResponse
				if jErr := json.Unmarshal([]byte(rawJSON), &adj); jErr == nil {
					if adj.IsSameEntity && adj.Confidence >= 0.80 {
						_ = s.AddConceptAlias(ctx, userID, topCandidate.ID, name)
						return &ResolutionResult{
							Concept:    topCandidate,
							Confidence: adj.Confidence,
							IsNew:      false,
							IsMerged:   true,
						}, nil
					}
				}
			}
		}
	}

	// Stage 4: Create new Concept
	newConcept, err := s.UpsertConcept(ctx, userID, name, coreIdea)
	if err != nil {
		return nil, fmt.Errorf("failed to create concept: %w", err)
	}

	return &ResolutionResult{
		Concept:    newConcept,
		Confidence: 1.0,
		IsNew:      true,
		IsMerged:   false,
	}, nil
}
