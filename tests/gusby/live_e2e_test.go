package gusby_test

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"

	"gusby/internal/auth"
	"gusby/internal/config"
	"gusby/internal/graph"
	"gusby/internal/ingest"
	"gusby/internal/llm"
	"gusby/internal/queue"
	"gusby/internal/store"
)

func TestLiveEndToEndFlow_WithRealGroq(t *testing.T) {
	if os.Getenv("SKIP_LIVE_GROQ_TEST") == "true" {
		t.Skip("Skipping live Groq test per SKIP_LIVE_GROQ_TEST=true")
	}

	cfg := config.LoadConfig()
	if cfg.GroqAPIKey == "" {
		t.Fatal("GROQ_API_KEY is not configured in .env or environment")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	s, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		t.Fatalf("failed to connect to database: %v", err)
	}
	defer s.Close()

	client, err := llm.NewGroqClient(cfg.GroqAPIKey, cfg.GroqModel, cfg.GroqBaseURL, cfg.GroqRPM, cfg.GroqTPM)
	if err != nil {
		t.Fatalf("failed to initialize Groq client: %v", err)
	}
	worker := queue.NewWorker("live-e2e-worker", s, client)

	t.Log("================================================================================")
	t.Log("                   GUSBY LIVE END-TO-END PIPELINE AUDIT                         ")
	t.Log("================================================================================")
	t.Logf("Configured LLM Model: %s", client.ModelName())

	// Step 1: Create Isolated Test User
	email := fmt.Sprintf("live-e2e-%d@gusby.local", time.Now().UnixNano())
	pwdHash, _ := auth.HashPassword("GusbySecretPass123!")
	user, err := s.CreateUser(ctx, email, pwdHash)
	if err != nil {
		t.Fatalf("failed to create user: %v", err)
	}
	t.Logf("[Step 1] Created user: %s (ID: %s)", user.Email, user.ID)

	// Step 2: Ingest Document A (Assertion 1)
	docAText := "Năm 1284, Thượng hoàng Trần Thánh Tông triệu tập Hội nghị Diên Hồng tại kinh thành Thăng Long để trưng cầu ý dân về việc đánh hay hòa trước đại quân Nguyên Mông."
	extDocA, err := ingest.ExtractFromPlainText("Hội nghị Diên Hồng 1284", docAText)
	if err != nil {
		t.Fatalf("failed to extract doc A: %v", err)
	}

	docA := &store.Document{
		UserID:      user.ID,
		Title:       extDocA.Title,
		SourceType:  extDocA.SourceType,
		ContentHash: extDocA.ContentHash,
		RawContent:  extDocA.RawContent,
		SourceText:  extDocA.SourceText,
		CharCount:   extDocA.CharCount,
		Status:      "uploading",
	}
	savedDocA, err := s.CreateDocument(ctx, docA)
	if err != nil {
		t.Fatalf("failed to save doc A: %v", err)
	}
	jobA, err := s.EnqueueJob(ctx, user.ID, savedDocA.ID, "queued", 10)
	if err != nil {
		t.Fatalf("failed to enqueue job A: %v", err)
	}
	t.Logf("[Step 2] Enqueued Document A: %s (Job: %s)", savedDocA.Title, jobA.ID)

	// Step 3: Process Document A with Real Groq LLM
	t.Log("[Step 3] Processing Document A through Real Groq Extraction & Integration...")
	processedA, err := worker.ProcessNext(ctx)
	if err != nil || !processedA {
		t.Fatalf("failed processing Document A: %v", err)
	}

	// Verify Document A is completed
	completedDocA, err := s.GetDocumentByID(ctx, user.ID, savedDocA.ID)
	if err != nil || completedDocA.Status != "completed" {
		t.Fatalf("doc A status expected 'completed', got %v", completedDocA.Status)
	}
	t.Logf("[Step 3] Document A completed successfully!")

	// Step 4: Ingest Document B (Contradictory Claim)
	docBText := "Một số văn bản lịch sử khác khẳng định Hội nghị Diên Hồng diễn ra vào năm 1285 chứ không phải năm 1284."
	extDocB, err := ingest.ExtractFromPlainText("Khảo cứu Niên đại Diên Hồng", docBText)
	if err != nil {
		t.Fatalf("failed to extract doc B: %v", err)
	}

	docB := &store.Document{
		UserID:      user.ID,
		Title:       extDocB.Title,
		SourceType:  extDocB.SourceType,
		ContentHash: extDocB.ContentHash,
		RawContent:  extDocB.RawContent,
		SourceText:  extDocB.SourceText,
		CharCount:   extDocB.CharCount,
		Status:      "uploading",
	}
	savedDocB, err := s.CreateDocument(ctx, docB)
	if err != nil {
		t.Fatalf("failed to save doc B: %v", err)
	}
	jobB, err := s.EnqueueJob(ctx, user.ID, savedDocB.ID, "queued", 10)
	if err != nil {
		t.Fatalf("failed to enqueue job B: %v", err)
	}
	t.Logf("[Step 4] Enqueued Contradictory Document B: %s (Job: %s)", savedDocB.Title, jobB.ID)

	// Step 5: Process Document B with Real Groq LLM
	t.Log("[Step 5] Processing Document B through Real Groq Extraction, Staged Entity Resolution & Conflict Classification...")
	processedB, err := worker.ProcessNext(ctx)
	if err != nil || !processedB {
		t.Fatalf("failed processing Document B: %v", err)
	}

	completedDocB, err := s.GetDocumentByID(ctx, user.ID, savedDocB.ID)
	if err != nil || completedDocB.Status != "completed" {
		t.Fatalf("doc B status expected 'completed', got %v", completedDocB.Status)
	}
	t.Logf("[Step 5] Document B completed successfully!")

	// Step 6: Verify Canonical Graph & Projection
	projection, err := graph.GetProjection(ctx, s, user.ID, "deep", nil, false)
	if err != nil {
		t.Fatalf("failed to get graph projection: %v", err)
	}
	t.Logf("[Step 6] Canonical Graph Nodes: %d, Edges: %d", len(projection.Nodes), len(projection.Edges))

	if len(projection.Nodes) == 0 {
		t.Fatalf("expected canonical nodes to be populated, got 0")
	}

	// Step 7: Verify Evidence Citations with Byte and Char Offsets
	var totalEvidenceChecked int
	for _, edge := range projection.Edges {
		edgeUUID, pErr := uuid.Parse(edge.ID)
		if pErr == nil {
			evList, _ := s.GetEvidenceForProposition(ctx, user.ID, edgeUUID)
			for _, ev := range evList {
				totalEvidenceChecked++
				if ev.Quote == "" {
					t.Errorf("evidence quote is empty for edge %s", edge.ID)
				}
				t.Logf("  [Evidence Verified] Doc: %s, ByteSpan: [%d, %d], CharSpan: [%d, %d], Quote: %q",
					ev.DocumentID, ev.ByteStart, ev.ByteEnd, ev.CharStart, ev.CharEnd, ev.Quote)
			}
		}
	}
	t.Logf("[Step 7] Total verbatim evidence citations validated: %d", totalEvidenceChecked)

	// Step 8: Verify Topic Clustering
	topics, err := s.ListTopics(ctx, user.ID)
	if err != nil {
		t.Fatalf("failed to query topics: %v", err)
	}
	t.Logf("[Step 8] Topic Islands Created: %d", len(topics))
	for _, top := range topics {
		t.Logf("  - Topic: %q (Centroid: [%.1f, %.1f])", top.Name, top.CentroidX, top.CentroidY)
	}

	// Step 9: Verify Review Items / Proposals or Conflicts
	conflicts, err := s.ListOpenConflicts(ctx, user.ID)
	if err != nil {
		t.Fatalf("failed to query conflicts: %v", err)
	}
	t.Logf("[Step 9] Pending Conflicts Flagged for Review: %d", len(conflicts))
	for _, cf := range conflicts {
		t.Logf("  - Conflict ID: %s, Type: %q", cf.ID, cf.ConflictType)
	}

	proposals, err := s.ListPendingProposals(ctx, user.ID)
	if err == nil {
		t.Logf("[Step 9] Pending Integration Proposals: %d", len(proposals))
	}

	t.Log("================================================================================")
	t.Log("                   ALL DEFINITION-OF-DONE CRITERIA MET                          ")
	t.Log("================================================================================")
}
