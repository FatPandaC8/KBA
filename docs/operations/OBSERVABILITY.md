# Gusby Production Observability Architecture

This document describes the telemetry architecture, Prometheus metrics, structured logging, OpenTelemetry tracing, and Grafana dashboard integration for Gusby.

---

## 1. Observability Architecture Overview

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'background': 'transparent' }}}%%
flowchart TD
    subgraph Host ["Sony Xperia 1 (Android Termux ARM64)"]
        subgraph AppProcess ["Gusby Process (:8081)"]
            Router["Chi Router + HTTP Middleware"]
            Worker["Queue Worker (SKIP LOCKED)"]
            LLMClient["Groq LLM Client"]
            DBPool["pgxpool (PostgreSQL 16)"]

            Logger["Structured JSON Logger\n(log/slog + Redaction)"]
            PromRegistry["Prometheus Metrics Registry\n(/metrics)"]
            OTelTracer["OpenTelemetry Tracer\n(Noop / OTLP)"]
        end

        Router --> PromRegistry
        Worker --> PromRegistry
        LLMClient --> PromRegistry
        DBPool --> PromRegistry
    end

    subgraph MonitoringHost ["Fedora Dev Workstation / Remote VPS"]
        PromServer["Prometheus Server\n(deploy/monitoring/prometheus.yml)"]
        Grafana["Grafana Dashboards\n(deploy/monitoring/grafana-dashboard.json)"]
        Alerts["Alertmanager\n(deploy/monitoring/alerts.yml)"]
    end

    PromServer -->|Scrape :8081/metrics via SSH tunnel| PromRegistry
    PromServer --> Alerts
    Grafana -->|Query TSDB| PromServer
```

---

## 2. Prometheus Metrics Catalog

All metrics are exposed at `http://127.0.0.1:8081/metrics`:

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `gusby_http_requests_total` | Counter | `method`, `route`, `status` | Total HTTP requests by normalized route pattern and status. |
| `gusby_http_request_duration_seconds` | Histogram | `method`, `route` | HTTP request latency histogram. |
| `gusby_http_errors_total` | Counter | `method`, `route`, `error_code` | HTTP 4xx and 5xx error responses. |
| `gusby_http_active_requests` | Gauge | none | Current number of in-flight HTTP requests. |
| `gusby_db_pool_connections` | Gauge | `state` (`total`, `idle`, `acquired`, `max`) | PostgreSQL connection pool status. |
| `gusby_db_query_duration_seconds` | Histogram | `operation` | Database query duration in seconds. |
| `gusby_queue_jobs_total` | Counter | `status` (`completed`, `failed`, `retried`) | Total background jobs processed by status. |
| `gusby_queue_job_duration_seconds` | Histogram | `stage` (`chunking`, `extracting`, `integrating`) | Job duration by stage. |
| `gusby_queue_active_jobs` | Gauge | none | Number of jobs currently being processed. |
| `gusby_ai_requests_total` | Counter | `provider`, `model`, `status`, `stage` | External AI provider requests. |
| `gusby_ai_request_duration_seconds` | Histogram | `provider`, `model`, `stage` | External AI provider latency. |
| `gusby_ai_tokens_total` | Counter | `type` (`prompt`, `completion`) | Total prompt and completion tokens used. |
| `gusby_process_uptime_seconds` | Gauge | none | Seconds since process startup. |
| `gusby_app_build_info` | Gauge | `version`, `commit_sha`, `go_version` | Constant build metadata. |

### Label Cardinality Protection
To prevent high-cardinality time-series explosion:
- URL parameters and IDs are collapsed to `{id}` (e.g., `/api/documents/{id}`).
- User IDs, request IDs, document IDs, and query strings are never added as Prometheus labels.

---

## 3. Structured Logging & Secret Redaction

Logging uses Go standard `log/slog` outputting structured JSON in production:

```json
{
  "time": "2026-11-04T00:30:00Z",
  "level": "INFO",
  "service": "gusby",
  "env": "production",
  "request_id": "c1f7b889-1100-4b2e-a5e2-632b84db5390",
  "user_id": "8f3b2049-9cf7-4f62-b919-4cb5038c352f",
  "msg": "Document ingestion job completed",
  "document_id": "e8fb4643-d819-47ac-b6f7-8df8e80a59af",
  "canonical_props": 3,
  "conflicts": 0
}
```

### Sensitive Data Masking Policy
The logger replacer ([`internal/observability/logger.go`](file:///home/guts/P2/KBA/internal/observability/logger.go)) automatically redacts:
- Passwords and password hashes.
- Bearer tokens, session cookies, and API keys (`gsk_...`, `ECHO_ADMIN_TOKEN`).
- PostgreSQL URLs containing credentials (`postgresql://user:pass@...` becomes `[REDACTED_DB_URL]`).
- Raw user text or document body content.

---

## 4. OpenTelemetry Tracing

Implemented via [`internal/observability/tracer.go`](file:///home/guts/P2/KBA/internal/observability/tracer.go):
- Default (Termux): No-op tracer provider active (`OTEL_ENABLED=false`). Zero CPU and 0 MB RAM overhead.
- When `OTEL_ENABLED=true`: Exports trace spans to standard OTLP HTTP collector for request flows, database queries, and AI extractions.
- Context propagation passes across asynchronous queue jobs.

---

## 5. Grafana Dashboard Integration

1. On Fedora or monitoring server, install Prometheus and Grafana.
2. Configure Prometheus using [`deploy/monitoring/prometheus.yml`](file:///home/guts/P2/KBA/deploy/monitoring/prometheus.yml).
3. Import [`deploy/monitoring/grafana-dashboard.json`](file:///home/guts/P2/KBA/deploy/monitoring/grafana-dashboard.json) in Grafana.
4. Alerts are evaluated against rules in [`deploy/monitoring/alerts.yml`](file:///home/guts/P2/KBA/deploy/monitoring/alerts.yml).
