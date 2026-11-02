package queue

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/google/uuid"

	"gusby/internal/graph"
	"gusby/internal/llm"
	"gusby/internal/pipeline"
	"gusby/internal/store"
)

type Worker struct {
	id        string
	store     *store.Store
	llmClient llm.LLMClient
	interval  time.Duration
}

func NewWorker(id string, s *store.Store, client llm.LLMClient) *Worker {
	return &Worker{
		id:        id,
		store:     s,
		llmClient: client,
		interval:  1 * time.Second,
	}
}

func (w *Worker) Start(ctx context.Context) {
	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			default:
				processed, err := w.ProcessNext(ctx)
				if err != nil {
					log.Printf("[worker %s] error processing job: %v", w.id, err)
				}
				if !processed {
					time.Sleep(w.interval)
				}
			}
		}
	}()
}

func (w *Worker) ProcessNext(ctx context.Context) (bool, error) {
	job, err := w.store.ClaimNextJob(ctx, w.id)
	if err != nil {
		return false, fmt.Errorf("failed to claim job: %w", err)
	}
	if job == nil {
		return false, nil // No jobs available
	}

	doc, err := w.store.GetDocumentByID(ctx, job.UserID, job.DocumentID)
	if err != nil || doc == nil {
		_ = w.store.FailJob(ctx, job.ID, "document not found")
		return true, fmt.Errorf("document %v not found", job.DocumentID)
	}

	// 1. Stage: Chunking
	_ = w.store.UpdateJobStage(ctx, job.ID, "chunking")
	chunks, err := w.store.GetChunksByDocumentID(ctx, job.UserID, doc.ID)
	if err != nil || len(chunks) == 0 {
		chunks = pipeline.ChunkDocument(job.UserID, doc.ID, doc.SourceText)
		if err := w.store.InsertChunks(ctx, chunks); err != nil {
			msg := err.Error()
			_ = w.store.FailJob(ctx, job.ID, msg)
			_ = w.store.UpdateDocumentStatus(ctx, job.UserID, doc.ID, "failed", &msg)
			return true, err
		}
	}

	// 2. Stage: Extraction
	_ = w.store.UpdateJobStage(ctx, job.ID, "extracting")
	runID, err := pipeline.CreateExtractionRun(ctx, w.store, job.UserID, doc.ID, w.llmClient.ModelName(), pipeline.PromptVersionConcept)
	if err != nil {
		msg := err.Error()
		_ = w.store.FailJob(ctx, job.ID, msg)
		_ = w.store.UpdateDocumentStatus(ctx, job.UserID, doc.ID, "failed", &msg)
		return true, err
	}

	var allExtracted pipeline.ExtractedChunkResult
	var conceptIDs []uuid.UUID

	for _, chunk := range chunks {
		res, err := pipeline.ExtractChunk(ctx, w.llmClient, chunk)
		if err != nil {
			msg := err.Error()
			_ = pipeline.FinishExtractionRun(ctx, w.store, runID, allExtracted.TokensPrompt, allExtracted.TokensComp, err)
			_ = w.store.FailJob(ctx, job.ID, msg)
			_ = w.store.UpdateDocumentStatus(ctx, job.UserID, doc.ID, "failed", &msg)
			return true, err
		}

		allExtracted.Concepts = append(allExtracted.Concepts, res.Concepts...)
		allExtracted.Propositions = append(allExtracted.Propositions, res.Propositions...)
		allExtracted.TokensPrompt += res.TokensPrompt
		allExtracted.TokensComp += res.TokensComp
	}

	// Record token usage
	_ = w.store.RecordTokenUsage(ctx, job.UserID, w.llmClient.ModelName(), allExtracted.TokensPrompt, allExtracted.TokensComp)

	// Persist raw extraction records
	if err := pipeline.PersistExtractedResults(ctx, w.store, runID, &allExtracted); err != nil {
		msg := err.Error()
		_ = w.store.FailJob(ctx, job.ID, msg)
		_ = w.store.UpdateDocumentStatus(ctx, job.UserID, doc.ID, "failed", &msg)
		return true, err
	}
	_ = pipeline.FinishExtractionRun(ctx, w.store, runID, allExtracted.TokensPrompt, allExtracted.TokensComp, nil)

	// 3. Stage: Resolving & Integrating
	_ = w.store.UpdateJobStage(ctx, job.ID, "integrating")
	summary, err := graph.IntegrateExtractedItems(ctx, w.store, w.llmClient, job.UserID, doc.ID, &allExtracted)
	if err != nil {
		msg := err.Error()
		_ = w.store.FailJob(ctx, job.ID, msg)
		_ = w.store.UpdateDocumentStatus(ctx, job.UserID, doc.ID, "failed", &msg)
		return true, err
	}

	// 4. Stage: Topics clustering
	for _, c := range allExtracted.Concepts {
		resolved, err := graph.ResolveConcept(ctx, w.store, nil, job.UserID, c.Name, c.Category, c.CoreIdea)
		if err == nil && resolved != nil {
			conceptIDs = append(conceptIDs, resolved.Concept.ID)
		}
	}
	_ = graph.AutoClusterTopics(ctx, w.store, job.UserID, doc.Title, conceptIDs)

	// 5. Complete Job & Document
	_ = w.store.CompleteJob(ctx, job.ID)
	_ = w.store.UpdateDocumentStatus(ctx, job.UserID, doc.ID, "completed", nil)

	log.Printf("[worker %s] document %s completed: %d canonical props, %d proposals, %d conflicts",
		w.id, doc.ID, summary.CanonicalPropositions, summary.IntegrationProposals, summary.DetectedConflicts)

	return true, nil
}
