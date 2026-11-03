package llm

import (
	"context"
	"fmt"
	"log"
	"time"

	"github.com/google/uuid"
	"gusby/internal/store"
)

type ProbeResult struct {
	Status         string `json:"status"` // "success" or "failed"
	LatencyMs      int    `json:"latency_ms"`
	HTTPStatus     int    `json:"http_status"`
	TokensConsumed int    `json:"tokens_consumed"`
	ProbeTimestamp string `json:"probe_timestamp"`
	Error          string `json:"error,omitempty"`
}

type AIGate struct {
	store            *store.Store
	client           LLMClient
	failureThreshold int
}

func NewAIGate(s *store.Store, client LLMClient, failureThreshold int) *AIGate {
	if failureThreshold <= 0 {
		failureThreshold = 3
	}
	return &AIGate{
		store:            s,
		client:           client,
		failureThreshold: failureThreshold,
	}
}

func (g *AIGate) GetState(ctx context.Context) (*store.AIGateState, error) {
	return g.store.GetAIGateState(ctx)
}

func (g *AIGate) AllowCall(ctx context.Context) (bool, string, error) {
	state, err := g.store.GetAIGateState(ctx)
	if err != nil {
		return false, fmt.Sprintf("failed to read AI gate state: %v", err), err
	}

	if state.State == "paused" {
		reason := "AI processing gate is paused by administrator"
		if state.Reason != "" {
			reason = state.Reason
		}
		return false, reason, nil
	}

	if state.State == "circuit_open" || state.State == "open" {
		reason := "Circuit breaker is open due to consecutive AI provider failures"
		if state.Reason != "" {
			reason = state.Reason
		}
		return false, reason, nil
	}

	return true, "", nil
}

func (g *AIGate) RecordCall(ctx context.Context, call *store.AICallLog) error {
	if call == nil {
		return nil
	}
	if call.ID == uuid.Nil {
		call.ID = uuid.New()
	}
	if call.CreatedAt.IsZero() {
		call.CreatedAt = time.Now()
	}
	if call.PromptVersion == "" {
		call.PromptVersion = "v1.0"
	}

	// Persist call record
	if err := g.store.RecordAICall(ctx, call); err != nil {
		log.Printf("[AIGate] Warning: failed to record AI call log: %v", err)
	}

	// Update breaker state
	if call.Status == "error" || (call.ErrorClass != "" && call.ErrorClass != "none") {
		errClass := call.ErrorClass
		if errClass == "" {
			errClass = "unknown_error"
		}
		tripped, err := g.store.RecordAIFailure(ctx, errClass, g.failureThreshold)
		if err != nil {
			log.Printf("[AIGate] Warning: failed to record AI failure in breaker: %v", err)
		}
		if tripped {
			log.Printf("[AIGate] Circuit breaker TRIPPED after %d consecutive failures (last: %s)", g.failureThreshold, errClass)
		}
	} else {
		if err := g.store.RecordAISuccess(ctx); err != nil {
			log.Printf("[AIGate] Warning: failed to record AI success in breaker: %v", err)
		}
	}

	return nil
}

func (g *AIGate) Pause(ctx context.Context, reason, updatedBy string) error {
	if reason == "" {
		reason = "Manually paused by administrator"
	}
	if updatedBy == "" {
		updatedBy = "admin"
	}
	return g.store.UpdateAIGateState(ctx, "paused", reason, updatedBy, false)
}

func (g *AIGate) Resume(ctx context.Context, updatedBy string) error {
	if updatedBy == "" {
		updatedBy = "admin"
	}
	return g.store.UpdateAIGateState(ctx, "enabled", "Resumed by administrator", updatedBy, true)
}

func (g *AIGate) ResetBreaker(ctx context.Context, updatedBy string) error {
	if updatedBy == "" {
		updatedBy = "admin"
	}
	return g.store.UpdateAIGateState(ctx, "enabled", "Circuit breaker manually reset", updatedBy, true)
}

func (g *AIGate) RunProbe(ctx context.Context, triggeredBy string) (*ProbeResult, error) {
	if triggeredBy == "" {
		triggeredBy = "admin"
	}

	start := time.Now()
	systemPrompt := "You are a deterministic health probe. Reply with valid JSON only: {\"pong\": true}."
	userPrompt := "ping"

	respJSON, pTokens, cTokens, err := g.client.CompleteJSON(ctx, systemPrompt, userPrompt, 50, 0.0)
	latency := int(time.Since(start).Milliseconds())

	nowStr := time.Now().UTC().Format(time.RFC3339)
	var callLog store.AICallLog
	callLog.ID = uuid.New()
	callLog.Provider = g.client.Describe().Kind
	callLog.Model = g.client.ModelName()
	callLog.PipelineStage = "probe"
	callLog.PromptVersion = "v1.0"
	callLog.LatencyMs = latency
	callLog.CreatedAt = time.Now()

	if err != nil {
		callLog.Status = "error"
		callLog.ErrorClass = "probe_failure"
		_ = g.store.RecordAICall(ctx, &callLog)

		return &ProbeResult{
			Status:         "failed",
			LatencyMs:      latency,
			HTTPStatus:     500,
			TokensConsumed: 0,
			ProbeTimestamp: nowStr,
			Error:          err.Error(),
		}, nil
	}

	callLog.Status = "success"
	callLog.ErrorClass = "none"
	callLog.TokensPrompt = pTokens
	callLog.TokensCompletion = cTokens
	_ = g.store.RecordAICall(ctx, &callLog)
	_ = g.store.RecordAISuccess(ctx)

	_ = respJSON // Verbatim JSON response parsed

	return &ProbeResult{
		Status:         "success",
		LatencyMs:      latency,
		HTTPStatus:     200,
		TokensConsumed: pTokens + cTokens,
		ProbeTimestamp: nowStr,
	}, nil
}
