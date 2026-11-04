package observability

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

type Metrics struct {
	// HTTP Metrics
	HTTPRequestsTotal   *prometheus.CounterVec
	HTTPRequestDuration *prometheus.HistogramVec
	HTTPErrorsTotal     *prometheus.CounterVec
	HTTPActiveRequests  prometheus.Gauge

	// Database Metrics
	DBPoolConnections *prometheus.GaugeVec
	DBQueryDuration   *prometheus.HistogramVec

	// Queue Worker Metrics
	QueueJobsTotal   *prometheus.CounterVec
	QueueJobDuration *prometheus.HistogramVec
	QueueActiveJobs  prometheus.Gauge

	// AI Provider Metrics
	AIRequestsTotal   *prometheus.CounterVec
	AIRequestDuration *prometheus.HistogramVec
	AITokensTotal     *prometheus.CounterVec

	// System & Process Info
	ProcessStartTime   time.Time
	ProcessUptimeGauge prometheus.Gauge
	BuildInfoGauge     *prometheus.GaugeVec
}

var globalMetrics *Metrics

// InitMetrics initializes and registers all Prometheus metrics in the default registry
func InitMetrics(version, commitSHA, goVersion string) *Metrics {
	if globalMetrics != nil {
		return globalMetrics
	}

	m := &Metrics{
		ProcessStartTime: time.Now(),
		HTTPRequestsTotal: prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Namespace: "gusby",
				Subsystem: "http",
				Name:      "requests_total",
				Help:      "Total number of HTTP requests processed by method, route pattern, and status code.",
			},
			[]string{"method", "route", "status"},
		),
		HTTPRequestDuration: prometheus.NewHistogramVec(
			prometheus.HistogramOpts{
				Namespace: "gusby",
				Subsystem: "http",
				Name:      "request_duration_seconds",
				Help:      "HTTP request latency histogram in seconds.",
				Buckets:   []float64{0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10},
			},
			[]string{"method", "route"},
		),
		HTTPErrorsTotal: prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Namespace: "gusby",
				Subsystem: "http",
				Name:      "errors_total",
				Help:      "Total number of HTTP 4xx and 5xx responses.",
			},
			[]string{"method", "route", "error_code"},
		),
		HTTPActiveRequests: prometheus.NewGauge(
			prometheus.GaugeOpts{
				Namespace: "gusby",
				Subsystem: "http",
				Name:      "active_requests",
				Help:      "Current number of in-flight HTTP requests.",
			},
		),
		DBPoolConnections: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "gusby",
				Subsystem: "db",
				Name:      "pool_connections",
				Help:      "Number of connections in the PostgreSQL connection pool by state.",
			},
			[]string{"state"},
		),
		DBQueryDuration: prometheus.NewHistogramVec(
			prometheus.HistogramOpts{
				Namespace: "gusby",
				Subsystem: "db",
				Name:      "query_duration_seconds",
				Help:      "Database query duration histogram in seconds.",
				Buckets:   []float64{0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2},
			},
			[]string{"operation"},
		),
		QueueJobsTotal: prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Namespace: "gusby",
				Subsystem: "queue",
				Name:      "jobs_total",
				Help:      "Total background jobs handled by final status (completed, failed, retried).",
			},
			[]string{"status"},
		),
		QueueJobDuration: prometheus.NewHistogramVec(
			prometheus.HistogramOpts{
				Namespace: "gusby",
				Subsystem: "queue",
				Name:      "job_duration_seconds",
				Help:      "Background job execution duration in seconds by pipeline stage.",
				Buckets:   []float64{0.1, 0.5, 1, 2, 5, 10, 30, 60, 120},
			},
			[]string{"stage"},
		),
		QueueActiveJobs: prometheus.NewGauge(
			prometheus.GaugeOpts{
				Namespace: "gusby",
				Subsystem: "queue",
				Name:      "active_jobs",
				Help:      "Current number of background jobs being processed concurrently.",
			},
		),
		AIRequestsTotal: prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Namespace: "gusby",
				Subsystem: "ai",
				Name:      "requests_total",
				Help:      "Total external AI provider requests by provider, model, status, and pipeline stage.",
			},
			[]string{"provider", "model", "status", "stage"},
		),
		AIRequestDuration: prometheus.NewHistogramVec(
			prometheus.HistogramOpts{
				Namespace: "gusby",
				Subsystem: "ai",
				Name:      "request_duration_seconds",
				Help:      "External AI provider round-trip latency in seconds.",
				Buckets:   []float64{0.25, 0.5, 1, 2, 3, 5, 8, 12, 20, 30},
			},
			[]string{"provider", "model", "stage"},
		),
		AITokensTotal: prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Namespace: "gusby",
				Subsystem: "ai",
				Name:      "tokens_total",
				Help:      "Total prompt and completion tokens consumed from AI providers.",
			},
			[]string{"type"},
		),
		ProcessUptimeGauge: prometheus.NewGauge(
			prometheus.GaugeOpts{
				Namespace: "gusby",
				Subsystem: "process",
				Name:      "uptime_seconds",
				Help:      "Number of seconds since the Gusby process started.",
			},
		),
		BuildInfoGauge: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "gusby",
				Subsystem: "app",
				Name:      "build_info",
				Help:      "Constant gauge containing version, commit SHA, and Go runtime info as labels.",
			},
			[]string{"version", "commit_sha", "go_version"},
		),
	}

	prometheus.MustRegister(
		m.HTTPRequestsTotal,
		m.HTTPRequestDuration,
		m.HTTPErrorsTotal,
		m.HTTPActiveRequests,
		m.DBPoolConnections,
		m.DBQueryDuration,
		m.QueueJobsTotal,
		m.QueueJobDuration,
		m.QueueActiveJobs,
		m.AIRequestsTotal,
		m.AIRequestDuration,
		m.AITokensTotal,
		m.ProcessUptimeGauge,
		m.BuildInfoGauge,
	)

	m.BuildInfoGauge.WithLabelValues(version, commitSHA, goVersion).Set(1)

	globalMetrics = m
	return m
}

func GetMetrics() *Metrics {
	return globalMetrics
}

// HTTPHandler returns the standard Prometheus HTTP handler for scraping /metrics
func HTTPHandler() http.Handler {
	return promhttp.Handler()
}

// responseWriterInterceptor captures HTTP status code
type responseWriterInterceptor struct {
	http.ResponseWriter
	statusCode int
}

func (w *responseWriterInterceptor) WriteHeader(code int) {
	w.statusCode = code
	w.ResponseWriter.WriteHeader(code)
}

// HTTPMiddleware instruments incoming HTTP requests
func HTTPMiddleware(m *Metrics) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if m == nil {
				next.ServeHTTP(w, r)
				return
			}

			// Do not record metrics for the /metrics scraper itself to avoid self-amplification
			if r.URL.Path == "/metrics" {
				next.ServeHTTP(w, r)
				return
			}

			m.HTTPActiveRequests.Inc()
			defer m.HTTPActiveRequests.Dec()

			start := time.Now()
			ww := &responseWriterInterceptor{ResponseWriter: w, statusCode: http.StatusOK}

			next.ServeHTTP(ww, r)

			duration := time.Since(start).Seconds()

			// Extract normalized route pattern to prevent high-cardinality label explosion
			routePattern := r.URL.Path
			rctx := chi.RouteContext(r.Context())
			if rctx != nil && rctx.RoutePattern() != "" {
				routePattern = rctx.RoutePattern()
			} else {
				routePattern = sanitizeRoutePattern(routePattern)
			}

			statusStr := strconv.Itoa(ww.statusCode)
			method := r.Method

			m.HTTPRequestsTotal.WithLabelValues(method, routePattern, statusStr).Inc()
			m.HTTPRequestDuration.WithLabelValues(method, routePattern).Observe(duration)

			if ww.statusCode >= 400 {
				m.HTTPErrorsTotal.WithLabelValues(method, routePattern, statusStr).Inc()
			}
		})
	}
}

// sanitizeRoutePattern collapses dynamic UUIDs or numeric IDs into {id} placeholders
func sanitizeRoutePattern(path string) string {
	parts := strings.Split(path, "/")
	for i, p := range parts {
		if len(p) == 36 && strings.Count(p, "-") == 4 { // UUID
			parts[i] = "{id}"
		} else if _, err := strconv.Atoi(p); err == nil && len(p) > 0 { // Numeric ID
			parts[i] = "{id}"
		}
	}
	return strings.Join(parts, "/")
}

// RecordJobEvent records job status and duration
func (m *Metrics) RecordJobEvent(status, stage string, duration time.Duration) {
	if m == nil {
		return
	}
	m.QueueJobsTotal.WithLabelValues(status).Inc()
	if stage != "" {
		m.QueueJobDuration.WithLabelValues(stage).Observe(duration.Seconds())
	}
}

// RecordAICall records AI provider latency, token usage, and status
func (m *Metrics) RecordAICall(provider, model, stage string, latency time.Duration, promptTokens, completionTokens int, success bool) {
	if m == nil {
		return
	}
	status := "success"
	if !success {
		status = "error"
	}

	m.AIRequestsTotal.WithLabelValues(provider, model, status, stage).Inc()
	m.AIRequestDuration.WithLabelValues(provider, model, stage).Observe(latency.Seconds())
	if promptTokens > 0 {
		m.AITokensTotal.WithLabelValues("prompt").Add(float64(promptTokens))
	}
	if completionTokens > 0 {
		m.AITokensTotal.WithLabelValues("completion").Add(float64(completionTokens))
	}
}

// UpdateDBPool records the current state of the database connection pool
func (m *Metrics) UpdateDBPool(total, idle, acquired, maxConns int32) {
	if m == nil {
		return
	}
	m.DBPoolConnections.WithLabelValues("total").Set(float64(total))
	m.DBPoolConnections.WithLabelValues("idle").Set(float64(idle))
	m.DBPoolConnections.WithLabelValues("acquired").Set(float64(acquired))
	m.DBPoolConnections.WithLabelValues("max").Set(float64(maxConns))
}

// UpdateUptime updates the process uptime gauge
func (m *Metrics) UpdateUptime() {
	if m == nil {
		return
	}
	m.ProcessUptimeGauge.Set(time.Since(m.ProcessStartTime).Seconds())
}

// String returns a summary of the metrics configuration
func (m *Metrics) String() string {
	return fmt.Sprintf("Gusby Prometheus Metrics Registry (started at %s)", m.ProcessStartTime.Format(time.RFC3339))
}
