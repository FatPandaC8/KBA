package observability_test

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"gusby/internal/observability"
)

func TestStructuredLogger_Redaction(t *testing.T) {
	var buf bytes.Buffer
	logger := observability.InitLogger("production", "test-service", &buf)

	ctx := context.WithValue(context.Background(), observability.RequestIDKey, "req-12345")
	ctx = context.WithValue(ctx, observability.UserIDKey, "user-abcdef")

	enriched := observability.FromContext(ctx)
	enriched.Info("User attempted login",
		"email", "user@example.com",
		"password", "SuperSecret123!",
		"api_key", "gsk_1234567890",
		"authorization", "Bearer eyJhbGciOi...",
		"database_url", "postgresql://user:pass@127.0.0.1:5432/gusby",
	)

	logged := buf.String()
	if strings.Contains(logged, "SuperSecret123!") {
		t.Errorf("Password was not redacted from log output: %s", logged)
	}
	if strings.Contains(logged, "gsk_1234567890") {
		t.Errorf("API key was not redacted from log output: %s", logged)
	}
	if strings.Contains(logged, "Bearer eyJhbGciOi...") {
		t.Errorf("Authorization token was not redacted from log output: %s", logged)
	}
	if !strings.Contains(logged, "REDACTED") {
		t.Errorf("Expected [REDACTED] in log output: %s", logged)
	}
	if !strings.Contains(logged, "req-12345") {
		t.Errorf("Expected request_id to be preserved in log: %s", logged)
	}

	_ = logger
}

func TestPrometheusMetrics_RegistrationAndHTTPMiddleware(t *testing.T) {
	metrics := observability.InitMetrics("v1.0.0-test", "commit123", "go1.27")
	if metrics == nil {
		t.Fatal("expected non-nil metrics registry")
	}

	handler := observability.HTTPMiddleware(metrics)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("OK"))
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/test", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", rec.Code)
	}

	// Verify /metrics endpoint output
	metricsReq := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	metricsRec := httptest.NewRecorder()
	observability.HTTPHandler().ServeHTTP(metricsRec, metricsReq)

	metricsBody := metricsRec.Body.String()
	if !strings.Contains(metricsBody, "gusby_http_requests_total") {
		t.Errorf("expected gusby_http_requests_total in /metrics output")
	}
	if !strings.Contains(metricsBody, "gusby_app_build_info") {
		t.Errorf("expected gusby_app_build_info in /metrics output")
	}
}

func TestMetrics_EventRecording(t *testing.T) {
	metrics := observability.GetMetrics()
	if metrics == nil {
		t.Fatal("expected non-nil metrics")
	}

	// Record job metrics
	metrics.RecordJobEvent("completed", "chunking", 250*time.Millisecond)
	metrics.RecordJobEvent("failed", "extracting", 500*time.Millisecond)

	// Record AI call metrics
	metrics.RecordAICall("groq", "gpt-oss-120b", "extraction", 1200*time.Millisecond, 150, 45, true)

	// Update DB pool metrics
	metrics.UpdateDBPool(10, 8, 2, 20)
	metrics.UpdateUptime()

	// Verify output in metrics scrape
	metricsReq := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	metricsRec := httptest.NewRecorder()
	observability.HTTPHandler().ServeHTTP(metricsRec, metricsReq)

	output := metricsRec.Body.String()
	if !strings.Contains(output, "gusby_queue_jobs_total") {
		t.Errorf("expected gusby_queue_jobs_total in scrape")
	}
	if !strings.Contains(output, "gusby_ai_requests_total") {
		t.Errorf("expected gusby_ai_requests_total in scrape")
	}
	if !strings.Contains(output, "gusby_db_pool_connections") {
		t.Errorf("expected gusby_db_pool_connections in scrape")
	}
}

func TestOpenTelemetryTracer_NoopFallback(t *testing.T) {
	tracer, cleanup, err := observability.InitTracer("gusby-test", "test")
	if err != nil {
		t.Fatalf("unexpected error initializing tracer: %v", err)
	}
	defer func() {
		_ = cleanup(context.Background())
	}()

	ctx, span := observability.StartSpan(context.Background(), "test-operation")
	defer span.End()

	if ctx == nil {
		t.Fatal("expected non-nil context from span")
	}
	_ = tracer
}
