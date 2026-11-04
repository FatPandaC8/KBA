package queue

import (
	"context"
	"errors"
	"fmt"
	"log"
	"sync"
	"time"

	"github.com/google/uuid"

	"gusby/internal/graph"
	"gusby/internal/llm"
	"gusby/internal/observability"
	"gusby/internal/pipeline"
	"gusby/internal/store"
)

type Worker struct {
	id        string
	store     *store.Store
	llmClient llm.LLMClient
	gate      *llm.AIGate
	interval  time.Duration
	stopCh    chan struct{}
	doneCh    chan struct{}
	stopOnce  sync.Once
}

func NewWorker(id string, s *store.Store, client llm.LLMClient, gate ...*llm.AIGate) *Worker {
	var g *llm.AIGate
	if len(gate) > 0 && gate[0] != nil {
		g = gate[0]
	} else {
		g = llm.NewAIGate(s, client, 3)
	}
	return &Worker{
		id:        id,
		store:     s,
		llmClient: client,
		gate:      g,
		interval:  1 * time.Second,
		stopCh:    make(chan struct{}),
		doneCh:    make(chan struct{}),
	}
}

func (w *Worker) Start(ctx context.Context) {
	go func() {
		defer close(w.doneCh)
		for {
			select {
			case <-ctx.Done():
				return
			case <-w.stopCh:
				return
			default:
				processed, err := w.ProcessNext(ctx)
				if err != nil {
					log.Printf("[worker %s] error processing job: %v", w.id, err)
				}
				if !processed {
					select {
					case <-ctx.Done():
						return
					case <-w.stopCh:
						return
					case <-time.After(w.interval):
					}
				}
			}
		}
	}()
}

// Stop initiates graceful worker shutdown and waits for any in-flight job processing to complete
func (w *Worker) Stop(ctx context.Context) error {
	w.stopOnce.Do(func() {
		close(w.stopCh)
	})

	select {
	case <-w.doneCh:
		log.Printf("[worker %s] stopped gracefully", w.id)
		return nil
	case <-ctx.Done():
		log.Printf("[worker %s] shutdown context timed out before worker finished", w.id)
		return ctx.Err()
	}
}

func (w *Worker) ProcessNext(ctx context.Context) (bool, error) {
	job, err := w.store.ClaimNextJob(ctx, w.id)
	if err != nil {
		return false, fmt.Errorf("failed to claim job: %w", err)
	}
	if job == nil {
		return false, nil // No jobs available
	}

	jobStartTime := time.Now()
	metrics := observability.GetMetrics()
	if metrics != nil {
		metrics.QueueActiveJobs.Inc()
		defer metrics.QueueActiveJobs.Dec()
	}

	doc, err := w.store.GetDocumentByID(ctx, job.UserID, job.DocumentID)
	if err != nil || doc == nil {
		_ = w.store.FailJob(ctx, job.ID, "document not found")
		if metrics != nil {
			metrics.RecordJobEvent("failed", "init", time.Since(jobStartTime))
		}
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

	// 2. Stage: Extraction - Check Gate First
	allowed, reason, err := w.gate.AllowCall(ctx)
	if !allowed {
		log.Printf("[worker %s] AI Gate active (%s). Pausing job %s into waiting_for_ai", w.id, reason, job.ID)
		_ = w.store.PauseJobForAI(ctx, job.ID, 5)
		return false, nil
	}

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
		startChunk := time.Now()
		res, err := pipeline.ExtractChunk(ctx, w.llmClient, chunk)
		duration := int(time.Since(startChunk).Milliseconds())

		callLog := &store.AICallLog{
			UserID:        &job.UserID,
			RunID:         &runID,
			Provider:      w.llmClient.Describe().Kind,
			Model:         w.llmClient.ModelName(),
			PipelineStage: "chunk_extraction",
			PromptVersion: pipeline.PromptVersionConcept,
			LatencyMs:     duration,
			CreatedAt:     time.Now(),
		}

		if err != nil {
			errClass := "extraction_failure"
			if errors.Is(err, llm.ErrQuotaExceeded) {
				errClass = "rate_limited"
			}
			callLog.Status = "error"
			callLog.ErrorClass = errClass
			_ = w.gate.RecordCall(ctx, callLog)

			// If circuit breaker tripped or gate blocked
			allowedNow, _, _ := w.gate.AllowCall(ctx)
			if !allowedNow {
				log.Printf("[worker %s] Gate tripped during extraction. Moving job %s to waiting_for_ai", w.id, job.ID)
				_ = w.store.PauseJobForAI(ctx, job.ID, 10)
				return false, nil
			}

			msg := err.Error()
			_ = pipeline.FinishExtractionRun(ctx, w.store, runID, allExtracted.TokensPrompt, allExtracted.TokensComp, err)
			_ = w.store.FailJob(ctx, job.ID, msg)
			_ = w.store.UpdateDocumentStatus(ctx, job.UserID, doc.ID, "failed", &msg)
			return true, err
		}

		callLog.Status = "success"
		callLog.ErrorClass = "none"
		callLog.TokensPrompt = res.TokensPrompt
		callLog.TokensCompletion = res.TokensComp
		_ = w.gate.RecordCall(ctx, callLog)

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

	// 3. Stage: Resolving & Integrating - Check Gate
	allowedInt, reasonInt, _ := w.gate.AllowCall(ctx)
	if !allowedInt {
		log.Printf("[worker %s] AI Gate active (%s) before integration. Pausing job %s into waiting_for_ai", w.id, reasonInt, job.ID)
		_ = w.store.PauseJobForAI(ctx, job.ID, 5)
		return false, nil
	}

	_ = w.store.UpdateJobStage(ctx, job.ID, "integrating")
	startInt := time.Now()
	summary, err := graph.IntegrateExtractedItems(ctx, w.store, w.llmClient, job.UserID, doc.ID, &allExtracted)
	intDuration := int(time.Since(startInt).Milliseconds())

	intCallLog := &store.AICallLog{
		UserID:        &job.UserID,
		RunID:         &runID,
		Provider:      w.llmClient.Describe().Kind,
		Model:         w.llmClient.ModelName(),
		PipelineStage: "graph_integration",
		PromptVersion: "v1.0",
		LatencyMs:     intDuration,
		CreatedAt:     time.Now(),
	}

	if err != nil {
		intCallLog.Status = "error"
		intCallLog.ErrorClass = "integration_failure"
		_ = w.gate.RecordCall(ctx, intCallLog)

		allowedNow, _, _ := w.gate.AllowCall(ctx)
		if !allowedNow {
			log.Printf("[worker %s] Gate tripped during integration. Moving job %s to waiting_for_ai", w.id, job.ID)
			_ = w.store.PauseJobForAI(ctx, job.ID, 10)
			return false, nil
		}

		msg := err.Error()
		_ = w.store.FailJob(ctx, job.ID, msg)
		_ = w.store.UpdateDocumentStatus(ctx, job.UserID, doc.ID, "failed", &msg)
		return true, err
	}

	intCallLog.Status = "success"
	intCallLog.ErrorClass = "none"
	_ = w.gate.RecordCall(ctx, intCallLog)

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

	if metrics != nil {
		metrics.RecordJobEvent("completed", "pipeline", time.Since(jobStartTime))
	}

	log.Printf("[worker %s] document %s completed: %d canonical props, %d proposals, %d conflicts",
		w.id, doc.ID, summary.CanonicalPropositions, summary.IntegrationProposals, summary.DetectedConflicts)

	return true, nil
}
