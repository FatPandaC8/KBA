package queue_test

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"gusby/internal/config"
	"gusby/internal/llm"
	"gusby/internal/queue"
	"gusby/internal/store"
)

func getTestStore(t *testing.T) *store.Store {
	t.Helper()
	cfg := config.LoadConfig()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	s, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		t.Skipf("PostgreSQL not accessible (%v), skipping queue test", err)
	}
	return s
}

func TestQueueWorker_EndToEnd(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	ctx := context.Background()

	user, err := s.CreateUser(ctx, "worker-"+uuid.NewString()[:8]+"@example.com", "hash-pw-test")
	if err != nil {
		t.Fatalf("failed to create user: %v", err)
	}

	doc := &store.Document{
		UserID:      user.ID,
		Title:       "General Relativity Paper",
		SourceType:  "text",
		ContentHash: "hash-work-" + uuid.NewString(),
		SourceText:  "Albert Einstein published the general relativity theory in 1915. Gravitational lensing confirms the theory.",
		CharCount:   107,
		Status:      "uploading",
	}
	doc, err = s.CreateDocument(ctx, doc)
	if err != nil {
		t.Fatalf("failed to create document: %v", err)
	}

	mockLLM := llm.NewMockClient("")
	mockLLM.SetResponse("Extract key concepts", `{
		"concepts": [
			{"name": "Albert Einstein", "category": "Person", "core_idea": "Theoretical physicist.", "confidence": 0.98},
			{"name": "General Relativity", "category": "Theory", "core_idea": "Theory of gravitation.", "confidence": 0.95}
		]
	}`)
	mockLLM.SetResponse("EXTRACTED CONCEPTS", `{
		"propositions": [
			{
				"subject": "Albert Einstein",
				"predicate": "Published",
				"object": "General Relativity",
				"evidence_quote": "Albert Einstein published the general relativity theory in 1915",
				"confidence": 0.95
			}
		]
	}`)

	// Enqueue job
	job, err := s.EnqueueJob(ctx, user.ID, doc.ID, "queued", 10)
	if err != nil {
		t.Fatalf("failed to enqueue job: %v", err)
	}

	worker := queue.NewWorker("test-worker-1", s, mockLLM)
	processed, err := worker.ProcessNext(ctx)
	if err != nil {
		t.Fatalf("worker failed to process job: %v", err)
	}
	if !processed {
		t.Fatalf("expected worker to process job, got false")
	}

	// Verify document is now completed
	updatedDoc, err := s.GetDocumentByID(ctx, user.ID, doc.ID)
	if err != nil || updatedDoc == nil {
		t.Fatalf("failed to fetch updated doc: %v", err)
	}
	if updatedDoc.Status != "completed" {
		t.Errorf("expected doc status completed, got %s", updatedDoc.Status)
	}

	// Verify canonical proposition was created with verified evidence
	subj, err := s.FindConceptByExactOrAlias(ctx, user.ID, "Albert Einstein")
	if err != nil || subj == nil {
		t.Fatalf("expected concept Albert Einstein, got %v", subj)
	}

	props, err := s.FindPropositionBySubjectAndPredicate(ctx, user.ID, subj.ID, "Published")
	if err != nil || len(props) != 1 {
		t.Fatalf("expected 1 published proposition, got %d (err: %v)", len(props), err)
	}

	evList, err := s.GetEvidenceForProposition(ctx, user.ID, props[0].ID)
	if err != nil || len(evList) != 1 {
		t.Fatalf("expected 1 evidence item, got %d (err: %v)", len(evList), err)
	}
	if evList[0].Quote != "Albert Einstein published the general relativity theory in 1915" {
		t.Errorf("evidence quote mismatch: %q", evList[0].Quote)
	}

	_ = job
}
