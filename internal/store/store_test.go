package store_test

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"

	"gusby/internal/config"
	"gusby/internal/store"
)

func getTestStore(t *testing.T) *store.Store {
	t.Helper()
	cfg := config.LoadConfig()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	s, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		t.Skipf("PostgreSQL not accessible (%v), skipping database integration test", err)
	}
	return s
}

func TestStore_DataFoundation_Integration(t *testing.T) {
	if os.Getenv("CI") == "" && testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	s := getTestStore(t)
	defer s.Close()
	ctx := context.Background()

	// 1. User & Session
	userEmail := "test-" + uuid.NewString()[:8] + "@example.com"
	user, err := s.CreateUser(ctx, userEmail, "hashed-argon2id-pw")
	if err != nil {
		t.Fatalf("failed to create user: %v", err)
	}
	if user.Email != userEmail {
		t.Errorf("expected email %s, got %s", userEmail, user.Email)
	}

	fetchedUser, err := s.GetUserByEmail(ctx, userEmail)
	if err != nil || fetchedUser == nil {
		t.Fatalf("failed to fetch user by email: %v", err)
	}

	sessionToken := uuid.NewString()
	sess, err := s.CreateSession(ctx, user.ID, sessionToken, 24*time.Hour)
	if err != nil || sess == nil {
		t.Fatalf("failed to create session: %v", err)
	}

	fetchedSess, err := s.GetSessionByToken(ctx, sessionToken)
	if err != nil || fetchedSess == nil {
		t.Fatalf("failed to fetch session by token: %v", err)
	}
	if fetchedSess.UserID != user.ID {
		t.Errorf("session user mismatch: expected %v, got %v", user.ID, fetchedSess.UserID)
	}

	// 2. Document & Hash Uniqueness
	docHash := "sha256-" + uuid.NewString()
	doc := &store.Document{
		UserID:      user.ID,
		Title:       "Test Ingestion Article",
		SourceType:  "text",
		ContentHash: docHash,
		SourceText:  "Knowledge graphs connect concepts with verified evidence.",
		CharCount:   58,
		Status:      "completed",
	}
	doc, err = s.CreateDocument(ctx, doc)
	if err != nil {
		t.Fatalf("failed to create document: %v", err)
	}

	// Duplicate document hash for same user should fail unique constraint
	dupDoc := &store.Document{
		UserID:      user.ID,
		Title:       "Duplicate Article",
		SourceType:  "text",
		ContentHash: docHash,
		SourceText:  "Different text, same hash.",
		CharCount:   26,
		Status:      "uploading",
	}
	_, err = s.CreateDocument(ctx, dupDoc)
	if err == nil {
		t.Errorf("expected duplicate content hash to fail unique constraint, but got nil")
	}

	// 3. Chunks with Offsets
	chunks := []*store.DocumentChunk{
		{
			UserID:     user.ID,
			DocumentID: doc.ID,
			ChunkIndex: 0,
			ChunkText:  "Knowledge graphs connect concepts with verified evidence.",
			ByteStart:  0,
			ByteEnd:    58,
			CharStart:  0,
			CharEnd:    58,
		},
	}
	if err := s.InsertChunks(ctx, chunks); err != nil {
		t.Fatalf("failed to insert chunks: %v", err)
	}

	fetchedChunks, err := s.GetChunksByDocumentID(ctx, user.ID, doc.ID)
	if err != nil || len(fetchedChunks) != 1 {
		t.Fatalf("expected 1 chunk, got %d (err: %v)", len(fetchedChunks), err)
	}

	// 4. Concept Upsert & Trigram Similarity
	c1, err := s.UpsertConcept(ctx, user.ID, "Knowledge Graph", "Structured knowledge network")
	if err != nil {
		t.Fatalf("failed to upsert concept: %v", err)
	}

	c2, err := s.UpsertConcept(ctx, user.ID, "Verified Evidence", "Verbatim proof from text")
	if err != nil {
		t.Fatalf("failed to upsert concept: %v", err)
	}

	// Trigram search: "knowledg graf" should match "Knowledge Graph"
	trigramMatches, sims, err := s.FindConceptsByTrigram(ctx, user.ID, "knowledg graf", 0.40, 5)
	if err != nil {
		t.Fatalf("trigram search failed: %v", err)
	}
	if len(trigramMatches) == 0 {
		t.Errorf("expected trigram match for 'knowledg graf', got 0 matches")
	} else if trigramMatches[0].ID != c1.ID {
		t.Errorf("expected top match to be %s, got %s (sim: %f)", c1.Name, trigramMatches[0].Name, sims[0])
	}

	// 5. Proposition & Verbatim Evidence
	prop := &store.Proposition{
		UserID:                user.ID,
		SubjectConceptID:      c1.ID,
		Predicate:             "Connects with",
		ObjectConceptID:       c2.ID,
		Qualifiers:            map[string]any{"modality": "definitional"},
		IsCanonical:           true,
		ConfidenceExtraction:  0.95,
		ConfidenceEvidence:    1.0,
		ConfidenceResolution:  0.92,
		ConfidenceProposition: 0.94,
	}
	prop, err = s.CreateProposition(ctx, prop)
	if err != nil {
		t.Fatalf("failed to create proposition: %v", err)
	}

	ev := &store.PropositionEvidence{
		UserID:        user.ID,
		PropositionID: prop.ID,
		DocumentID:    doc.ID,
		ChunkID:       fetchedChunks[0].ID,
		Quote:         "connect concepts with verified evidence",
		ByteStart:     17,
		ByteEnd:       57,
		CharStart:     17,
		CharEnd:       57,
	}
	ev, err = s.CreateEvidence(ctx, ev)
	if err != nil {
		t.Fatalf("failed to create evidence: %v", err)
	}

	evList, err := s.GetEvidenceForProposition(ctx, user.ID, prop.ID)
	if err != nil || len(evList) != 1 {
		t.Fatalf("expected 1 evidence item, got %d (err: %v)", len(evList), err)
	}
	if evList[0].Quote != ev.Quote {
		t.Errorf("evidence quote mismatch: expected %q, got %q", ev.Quote, evList[0].Quote)
	}

	// 6. Job Queue SKIP LOCKED Claim
	job, err := s.EnqueueJob(ctx, user.ID, doc.ID, "queued", 10)
	if err != nil {
		t.Fatalf("failed to enqueue job: %v", err)
	}

	claimedJob, err := s.ClaimNextJob(ctx, "worker-1")
	if err != nil || claimedJob == nil {
		t.Fatalf("failed to claim job: %v", err)
	}
	if claimedJob.ID != job.ID {
		t.Errorf("claimed job ID mismatch: expected %v, got %v", job.ID, claimedJob.ID)
	}

	if err := s.CompleteJob(ctx, claimedJob.ID); err != nil {
		t.Fatalf("failed to complete job: %v", err)
	}

	// 7. Token Usage & Budgeting
	if err := s.RecordTokenUsage(ctx, user.ID, "openai/gpt-oss-120b", 500, 150); err != nil {
		t.Fatalf("failed to record token usage: %v", err)
	}
	used, err := s.GetDailyTokensUsed(ctx, user.ID)
	if err != nil {
		t.Fatalf("failed to get daily tokens: %v", err)
	}
	if used < 650 {
		t.Errorf("expected daily tokens >= 650, got %d", used)
	}
}
