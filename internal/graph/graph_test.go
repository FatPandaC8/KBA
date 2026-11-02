package graph_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"gusby/internal/config"
	"gusby/internal/graph"
	"gusby/internal/llm"
	"gusby/internal/pipeline"
	"gusby/internal/store"
)

func getTestStore(t *testing.T) *store.Store {
	t.Helper()
	cfg := config.LoadConfig()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	s, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		t.Skipf("PostgreSQL not accessible (%v), skipping graph integration test", err)
	}
	return s
}

func TestEntityResolution_Staged(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	ctx := context.Background()

	user, err := s.CreateUser(ctx, "res-"+uuid.NewString()[:8]+"@example.com", "hash-pw-test")
	if err != nil {
		t.Fatalf("failed to create user: %v", err)
	}
	userID := user.ID

	// 1. Create canonical concept "Quantum Entanglement"
	c1, err := s.UpsertConcept(ctx, userID, "Quantum Entanglement", "Spooky action at a distance")
	if err != nil {
		t.Fatalf("failed to create concept: %v", err)
	}

	// Case A: Exact match
	resA, err := graph.ResolveConcept(ctx, s, nil, userID, "quantum entanglement", "Physics", "")
	if err != nil {
		t.Fatalf("resolution failed: %v", err)
	}
	if resA.Concept.ID != c1.ID || resA.Confidence != 1.0 || resA.IsNew {
		t.Errorf("expected exact match to c1 with conf=1.0, got id=%v, conf=%f, new=%v", resA.Concept.ID, resA.Confidence, resA.IsNew)
	}

	// Case B: High similarity (>= 0.88)
	// "Quantum Entanglements" (plural)
	resB, err := graph.ResolveConcept(ctx, s, nil, userID, "Quantum Entanglements", "Physics", "")
	if err != nil {
		t.Fatalf("resolution failed: %v", err)
	}
	if resB.Concept.ID != c1.ID || !resB.IsMerged {
		t.Errorf("expected high similarity merge to c1, got id=%v, merged=%v", resB.Concept.ID, resB.IsMerged)
	}

	// Case C: Ambiguous similarity with LLM Adjudication
	mockLLM := llm.NewMockClient(`{
		"is_same_entity": true,
		"canonical_name": "Quantum Entanglement",
		"alias_to_add": "Entangled States",
		"confidence": 0.89,
		"reasoning": "Refers to the same underlying physical phenomenon."
	}`)

	resC, err := graph.ResolveConcept(ctx, s, mockLLM, userID, "Entangled States", "Physics", "State where particles are correlated")
	if err != nil {
		t.Fatalf("resolution failed: %v", err)
	}
	if resC.Concept.ID != c1.ID || !resC.IsMerged {
		t.Errorf("expected LLM adjudicated merge, got id=%v, merged=%v", resC.Concept.ID, resC.IsMerged)
	}

	// Case D: New distinct concept
	resD, err := graph.ResolveConcept(ctx, s, nil, userID, "Photosynthesis", "Biology", "Process used by plants")
	if err != nil {
		t.Fatalf("resolution failed: %v", err)
	}
	if !resD.IsNew || resD.Concept.Name != "Photosynthesis" {
		t.Errorf("expected new concept Photosynthesis, got id=%v, new=%v", resD.Concept.ID, resD.IsNew)
	}
}

func TestConflictClassification_Preservation(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	ctx := context.Background()

	user, err := s.CreateUser(ctx, "conflict-"+uuid.NewString()[:8]+"@example.com", "hash-pw-test")
	if err != nil {
		t.Fatalf("failed to create user: %v", err)
	}
	userID := user.ID

	docA := &store.Document{
		UserID:      userID,
		Title:       "Study 2020",
		SourceType:  "text",
		ContentHash: "hash-conf-a-" + uuid.NewString(),
		SourceText:  "Light behaves strictly as a continuous wave in this classical experiment.",
		CharCount:   72,
		Status:      "completed",
	}
	docA, _ = s.CreateDocument(ctx, docA)

	docB := &store.Document{
		UserID:      userID,
		Title:       "Study 2024",
		SourceType:  "text",
		ContentHash: "hash-conf-b-" + uuid.NewString(),
		SourceText:  "Light behaves strictly as discrete particles called photons in photoelectric tests.",
		CharCount:   83,
		Status:      "completed",
	}
	docB, _ = s.CreateDocument(ctx, docB)

	chunkA := &store.DocumentChunk{
		ID:         uuid.New(),
		UserID:     userID,
		DocumentID: docA.ID,
		ChunkIndex: 0,
		ChunkText:  docA.SourceText,
		ByteStart:  0,
		ByteEnd:    len(docA.SourceText),
		CharStart:  0,
		CharEnd:    len([]rune(docA.SourceText)),
	}
	_ = s.InsertChunks(ctx, []*store.DocumentChunk{chunkA})

	chunkB := &store.DocumentChunk{
		ID:         uuid.New(),
		UserID:     userID,
		DocumentID: docB.ID,
		ChunkIndex: 0,
		ChunkText:  docB.SourceText,
		ByteStart:  0,
		ByteEnd:    len(docB.SourceText),
		CharStart:  0,
		CharEnd:    len([]rune(docB.SourceText)),
	}
	_ = s.InsertChunks(ctx, []*store.DocumentChunk{chunkB})

	// Ingest first claim: Light (Subject) -> Behaves as (Predicate) -> Continuous Wave (Object)
	res1 := &pipeline.ExtractedChunkResult{
		Concepts: []*store.ExtractedConcept{
			{Name: "Light", Category: "Physics", ConfidenceScore: 0.95},
			{Name: "Continuous Wave", Category: "Model", ConfidenceScore: 0.90},
		},
		Propositions: []*store.ExtractedProposition{
			{
				ChunkID:         chunkA.ID,
				SubjectRaw:      "Light",
				Predicate:       "Behaves as",
				ObjectRaw:       "Continuous Wave",
				EvidenceQuote:   "Light behaves strictly as a continuous wave",
				ConfidenceScore: 0.95,
				IsValidEvidence: true,
			},
		},
	}

	summary1, err := graph.IntegrateExtractedItems(ctx, s, nil, userID, docA.ID, res1)
	if err != nil {
		t.Fatalf("integration 1 failed: %v", err)
	}
	if summary1.CanonicalPropositions != 1 {
		t.Errorf("expected 1 canonical prop, got %d", summary1.CanonicalPropositions)
	}

	// Ingest conflicting claim: Light (Subject) -> Behaves as (Predicate) -> Discrete Photons (Object)
	mockLLM := llm.NewMockClient(`{
		"classification": "contextual_difference",
		"confidence": 0.92,
		"explanation": "Wave-particle duality: classical experiment observes waves while photoelectric test observes photons.",
		"reconciliation_qualifiers": {"experimental_domain": "photoelectric effect"}
	}`)

	res2 := &pipeline.ExtractedChunkResult{
		Concepts: []*store.ExtractedConcept{
			{Name: "Light", Category: "Physics", ConfidenceScore: 0.95},
			{Name: "Discrete Photons", Category: "Model", ConfidenceScore: 0.92},
		},
		Propositions: []*store.ExtractedProposition{
			{
				ChunkID:         chunkB.ID,
				SubjectRaw:      "Light",
				Predicate:       "Behaves as",
				ObjectRaw:       "Discrete Photons",
				EvidenceQuote:   "Light behaves strictly as discrete particles called photons",
				ConfidenceScore: 0.94,
				IsValidEvidence: true,
			},
		},
	}

	summary2, err := graph.IntegrateExtractedItems(ctx, s, mockLLM, userID, docB.ID, res2)
	if err != nil {
		t.Fatalf("integration 2 failed: %v", err)
	}

	if summary2.DetectedConflicts != 1 {
		t.Errorf("expected 1 conflict detected, got %d", summary2.DetectedConflicts)
	}

	// Verify both propositions are preserved (zero overwrites)
	conflicts, err := s.ListOpenConflicts(ctx, userID)
	if err != nil {
		t.Fatalf("list conflicts failed: %v", err)
	}
	if len(conflicts) != 1 {
		t.Fatalf("expected 1 open conflict, got %d", len(conflicts))
	}
	if conflicts[0].ConflictType != "contextual_difference" {
		t.Errorf("expected conflict_type contextual_difference, got %s", conflicts[0].ConflictType)
	}
}

func TestFourDimensionConfidencePolicy(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	ctx := context.Background()

	user, err := s.CreateUser(ctx, "conf4d-"+uuid.NewString()[:8]+"@example.com", "hash-pw-test")
	if err != nil {
		t.Fatalf("failed to create user: %v", err)
	}
	userID := user.ID
	doc := &store.Document{
		UserID:      userID,
		Title:       "Test Doc",
		SourceType:  "text",
		ContentHash: "hash-4d-" + uuid.NewString(),
		SourceText:  "Sample text for confidence policy validation.",
		CharCount:   45,
		Status:      "completed",
	}
	doc, _ = s.CreateDocument(ctx, doc)

	chunk := &store.DocumentChunk{
		ID:         uuid.New(),
		UserID:     userID,
		DocumentID: doc.ID,
		ChunkIndex: 0,
		ChunkText:  doc.SourceText,
		ByteStart:  0,
		ByteEnd:    len(doc.SourceText),
		CharStart:  0,
		CharEnd:    len([]rune(doc.SourceText)),
	}
	_ = s.InsertChunks(ctx, []*store.DocumentChunk{chunk})

	// 1. High confidence (all >= 0.85, valid evidence) -> Canonical Proposition
	resHigh := &pipeline.ExtractedChunkResult{
		Concepts: []*store.ExtractedConcept{
			{Name: "High Alpha", Category: "Concept", ConfidenceScore: 0.95},
			{Name: "High Beta", Category: "Concept", ConfidenceScore: 0.95},
		},
		Propositions: []*store.ExtractedProposition{
			{
				ChunkID:         chunk.ID,
				SubjectRaw:      "High Alpha",
				Predicate:       "Interacts with",
				ObjectRaw:       "High Beta",
				EvidenceQuote:   "Sample text for confidence",
				ConfidenceScore: 0.95,
				IsValidEvidence: true,
			},
		},
	}
	sumHigh, err := graph.IntegrateExtractedItems(ctx, s, nil, userID, doc.ID, resHigh)
	if err != nil {
		t.Fatalf("high confidence failed: %v", err)
	}
	if sumHigh.CanonicalPropositions != 1 {
		t.Errorf("expected 1 canonical prop, got %d", sumHigh.CanonicalPropositions)
	}

	// 2. Medium confidence (composite >= 0.65, extraction = 0.70) -> Integration Proposal
	resMed := &pipeline.ExtractedChunkResult{
		Concepts: []*store.ExtractedConcept{
			{Name: "Med Alpha", Category: "Concept", ConfidenceScore: 0.70},
			{Name: "Med Beta", Category: "Concept", ConfidenceScore: 0.70},
		},
		Propositions: []*store.ExtractedProposition{
			{
				ChunkID:         chunk.ID,
				SubjectRaw:      "Med Alpha",
				Predicate:       "May relate to",
				ObjectRaw:       "Med Beta",
				EvidenceQuote:   "policy validation",
				ConfidenceScore: 0.70,
				IsValidEvidence: true,
			},
		},
	}
	sumMed, err := graph.IntegrateExtractedItems(ctx, s, nil, userID, doc.ID, resMed)
	if err != nil {
		t.Fatalf("med confidence failed: %v", err)
	}
	if sumMed.IntegrationProposals != 1 {
		t.Errorf("expected 1 integration proposal, got %d", sumMed.IntegrationProposals)
	}

	// 3. Invalid evidence (IsValidEvidence = false) -> Barred from canonical graph
	resInvalid := &pipeline.ExtractedChunkResult{
		Concepts: []*store.ExtractedConcept{
			{Name: "Inv Alpha", Category: "Concept", ConfidenceScore: 0.99},
			{Name: "Inv Beta", Category: "Concept", ConfidenceScore: 0.99},
		},
		Propositions: []*store.ExtractedProposition{
			{
				ChunkID:         chunk.ID,
				SubjectRaw:      "Inv Alpha",
				Predicate:       "Relates to",
				ObjectRaw:       "Inv Beta",
				EvidenceQuote:   "Hallucinated non-existent quote",
				ConfidenceScore: 0.99,
				IsValidEvidence: false, // Invalid
			},
		},
	}
	sumInv, err := graph.IntegrateExtractedItems(ctx, s, nil, userID, doc.ID, resInvalid)
	if err != nil {
		t.Fatalf("invalid evidence test failed: %v", err)
	}
	if sumInv.CanonicalPropositions != 0 || sumInv.IntegrationProposals != 0 {
		t.Errorf("invalid evidence must NEVER be integrated into canonical graph or proposals: got %d canonical, %d proposals",
			sumInv.CanonicalPropositions, sumInv.IntegrationProposals)
	}
	if sumInv.RejectedNoEvidence != 1 {
		t.Errorf("expected 1 rejected proposition, got %d", sumInv.RejectedNoEvidence)
	}
}
