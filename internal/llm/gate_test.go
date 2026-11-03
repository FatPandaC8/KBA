package llm_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
	"gusby/internal/config"
	"gusby/internal/llm"
	"gusby/internal/store"
)

func getTestStore(t *testing.T) *store.Store {
	t.Helper()
	cfg := config.LoadConfig()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	s, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		t.Skipf("PostgreSQL not accessible (%v), skipping test", err)
	}
	return s
}

func TestAIGate_LifecycleAndBreaker(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	ctx := context.Background()

	mockClient := llm.NewMockClient(`{"pong": true}`)
	gate := llm.NewAIGate(s, mockClient, 3)

	// Ensure clean initial state
	if err := gate.ResetBreaker(ctx, "test_init"); err != nil {
		t.Fatalf("failed to reset breaker: %v", err)
	}

	// 1. Initial State: Allowed
	allowed, reason, err := gate.AllowCall(ctx)
	if err != nil || !allowed {
		t.Fatalf("expected call allowed initially, got allowed=%v, reason=%s, err=%v", allowed, reason, err)
	}

	// 2. Manual Pause & Resume
	if err := gate.Pause(ctx, "Scheduled maintenance window", "admin_tester"); err != nil {
		t.Fatalf("failed to pause gate: %v", err)
	}

	allowed, reason, err = gate.AllowCall(ctx)
	if allowed {
		t.Fatalf("expected call to be blocked when paused, but was allowed")
	}
	if reason != "Scheduled maintenance window" {
		t.Errorf("expected reason 'Scheduled maintenance window', got '%s'", reason)
	}

	if err := gate.Resume(ctx, "admin_tester"); err != nil {
		t.Fatalf("failed to resume gate: %v", err)
	}

	allowed, _, err = gate.AllowCall(ctx)
	if !allowed {
		t.Fatalf("expected call to be allowed after resume")
	}

	// 3. Circuit Breaker: Trip on consecutive failures
	errClass := "rate_limited"
	for i := 1; i <= 3; i++ {
		callLog := &store.AICallLog{
			ID:            uuid.New(),
			Provider:      "groq",
			Model:         "test-model",
			PipelineStage: "chunk_extraction",
			PromptVersion: "v1.0",
			LatencyMs:     150,
			Status:        "error",
			ErrorClass:    errClass,
			CreatedAt:     time.Now(),
		}
		if err := gate.RecordCall(ctx, callLog); err != nil {
			t.Fatalf("failed to record call failure: %v", err)
		}
	}

	// Verify breaker is tripped (circuit_open)
	allowed, reason, err = gate.AllowCall(ctx)
	if allowed {
		t.Fatalf("expected breaker to be open after 3 consecutive failures, but call was allowed")
	}

	state, err := gate.GetState(ctx)
	if err != nil {
		t.Fatalf("failed to get gate state: %v", err)
	}
	if state.State != "circuit_open" {
		t.Errorf("expected state 'circuit_open', got '%s'", state.State)
	}

	// 4. Reset Breaker
	if err := gate.ResetBreaker(ctx, "admin_tester"); err != nil {
		t.Fatalf("failed to reset breaker: %v", err)
	}

	allowed, _, err = gate.AllowCall(ctx)
	if !allowed {
		t.Fatalf("expected call allowed after manual breaker reset")
	}
}

func TestAIGate_ActiveProbe(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	ctx := context.Background()

	// 1. Success Probe
	mockClient := llm.NewMockClient(`{"pong": true}`)
	gate := llm.NewAIGate(s, mockClient, 3)

	probeRes, err := gate.RunProbe(ctx, "e2e_tester")
	if err != nil {
		t.Fatalf("probe error: %v", err)
	}
	if probeRes.Status != "success" || probeRes.HTTPStatus != 200 {
		t.Errorf("expected successful probe, got status=%s, code=%d", probeRes.Status, probeRes.HTTPStatus)
	}

	// 2. Failure Probe
	failingMock := llm.NewMockClient("")
	failingMock.SetFailure(errors.New("simulated network connection timeout"))
	failingGate := llm.NewAIGate(s, failingMock, 3)

	failProbeRes, err := failingGate.RunProbe(ctx, "e2e_tester")
	if err != nil {
		t.Fatalf("probe unexpected execution error: %v", err)
	}
	if failProbeRes.Status != "failed" || failProbeRes.HTTPStatus != 500 {
		t.Errorf("expected failed probe, got status=%s, code=%d", failProbeRes.Status, failProbeRes.HTTPStatus)
	}
}

func TestProvider_DescribeAndHealth(t *testing.T) {
	ctx := context.Background()

	// 1. Mock Client
	mock := llm.NewMockClient("{}")
	desc := mock.Describe()
	if desc.Kind != "mock" || !desc.IsConfigured {
		t.Errorf("unexpected describe output: %+v", desc)
	}

	health, err := mock.Health(ctx)
	if err != nil || health.Status != "healthy" {
		t.Errorf("unexpected health output: %+v, err: %v", health, err)
	}

	// 2. Groq Client Unconfigured
	unconfiguredGroq, _ := llm.NewGroqClient("dummy_key", "model", "http://127.0.0.1:9999", 30, 6000)
	groqDesc := unconfiguredGroq.Describe()
	if groqDesc.Kind != "groq" || groqDesc.Model != "model" {
		t.Errorf("unexpected groq describe output: %+v", groqDesc)
	}
}
