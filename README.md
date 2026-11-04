# Gusby — Text-to-Knowledge-Graph Platform

Gusby turns unstructured text, URLs, and documents into connected, structured, trustworthy knowledge.

**Core Principle: Precision over recall.** A small, trustworthy graph beats a large one with erroneous edges. Every relationship is grounded in exact, deterministic verbatim evidence from the original source text with byte and character offsets.

---

## Architecture Overview

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'background': 'transparent', 'clusterBkg': 'none' }}}%%
flowchart TD
    subgraph ClientLayer ["Client & Edge"]
        User["Browser Client"]
        Nginx["Nginx Reverse Proxy (:8080)"]
    end

    subgraph ServiceLayer ["Application Services (PM2 Managed)"]
        SPA["Nuxt Static SPA (/frontend/.output/public)"]
        Backend["Go API & Queue Worker (127.0.0.1:8081)"]
    end

    subgraph StorageLayer ["Data Persistence & Inference"]
        Postgres["PostgreSQL 16 - 18+ (127.0.0.1:5432)\nSchema: gusby | Extension: pg_trgm"]
        Groq["Groq Cloud LLM (openai/gpt-oss-120b)"]
    end

    User -->|HTTP / HTTPS| Nginx
    Nginx -->|/* (Static Assets)| SPA
    Nginx -->|/api/*| Backend
    Backend -->|pgx pool| Postgres
    Backend -->|Inference| Groq
```

---

## Technology Stack

- **Backend**: Go 1.27 (`chi/v5` router, `pgx/v5` connection pool, Argon2id auth, `ledongthuc/pdf`, XML DOCX extractor).
- **Frontend**: Nuxt 4 (Vue 3, TypeScript, Tailwind CSS, Cytoscape.js for interactive canvas).
- **Database**: PostgreSQL 16 - 18+ (Tested on PostgreSQL 18.6; dedicated `gusby` schema, `pg_trgm` extension for trigram similarity).
- **Process Manager**: PM2 (Production process monitoring, automatic restarts, memory limits).
- **Web Server / Reverse Proxy**: Nginx (Listening on port `8080`, serving frontend static files, proxying `/api/` to `127.0.0.1:8081`).
- **LLM Engine**: Groq API (`openai/gpt-oss-120b`) with JSON mode, bounded repair retries, rate limiting, and token budgeting.

---

## Network Ports & Topology

| Service | Bind Address | Port | Access Scope |
|---|---|---|---|
| **Nginx Reverse Proxy** | `0.0.0.0` | `8080` | Public / Cloudflare Tunnel entrypoint |
| **Go Backend HTTP API** | `127.0.0.1` | `8081` | Private (Loopback only) |
| **Nuxt Dev Server** | `0.0.0.0` | `3000` | Development only |
| **PostgreSQL Database** | `127.0.0.1` | `5432` | Private (Loopback only) |

---

## Quickstart Guide (Local Development)

### 1. Prerequisites
- **Docker Compose** or local PostgreSQL (16 - 18+) with `pg_trgm`
- **Go 1.23+** (Go 1.27 recommended)
- **Node.js 18+** & **npm**
- **Groq API Key** (from [console.groq.com](https://console.groq.com))

### 2. Environment Setup
```bash
# 1. Start local PostgreSQL
docker compose up -d postgres

# 2. Configure environment
cp .env.example .env
# Edit .env and supply your GROQ_API_KEY
```

### 3. Apply Database Migrations
```bash
chmod +x ./scripts/migrate.sh
./scripts/migrate.sh
```

### 4. Run Backend Server & Worker
```bash
# Starts API server and queue worker on http://127.0.0.1:8081
go run ./cmd/gusby
```

### 5. Run Nuxt 4 Frontend
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000 in your browser
```

---

## Production Build & VPS Deployment

Gusby is engineered for standalone VPS deployment (Linux VPS or Android Termux ARM64) with zero Docker runtime dependency:

```bash
# 1. Build Go binary
CGO_ENABLED=0 go build -ldflags="-s -w" -o ./bin/gusby ./cmd/gusby

# 2. Build Nuxt Static SPA
cd frontend
npm ci
npm run generate
cd ..

# 3. Start Backend via PM2
pm2 start ecosystem.config.cjs
pm2 save

# 4. Configure Nginx
# Copy deploy/nginx/gusby-linux.conf (or gusby-termux.conf) to your Nginx configuration
sudo nginx -t && sudo systemctl reload nginx
```

---

---

## Production Engineering Lifecycle

Gusby features a complete, battle-tested engineering lifecycle:
**Development → Code Review → CI → Build → Release → CD → Deployment → Verification → Observability → Incident Response → Recovery.**

### Engineering Documentation Index
- **[Software Development Life Cycle (SDLC)](file:///home/guts/P2/KBA/docs/engineering/SDLC.md)**: Branch strategies, PR requirements, code review, and Expand-and-Contract database migrations.
- **[Continuous Integration & Delivery (CI/CD)](file:///home/guts/P2/KBA/docs/engineering/CI_CD.md)**: 4-tier automated GitHub Actions pipeline, status checks, and merge gates.
- **[Release & Artifact Management](file:///home/guts/P2/KBA/docs/engineering/RELEASE_MANAGEMENT.md)**: Commit SHA anchoring, build info injection, artifact checksums, and release manifests.
- **[Android Termux Deployment Guide](docs/deployment/ANDROID_TERMUX.md)**: Simple, direct single-host deployment on Sony Xperia 1 (ARM64), wake locks, PM2, and static Nginx SPA.
- **[Linux VPS Deployment Guide](docs/deployment/VPS_DEPLOYMENT.md)**: Standard Linux server configuration, security hardening, and Nginx reverse proxy.
- **[Application Rollback & Safety Guide](docs/deployment/ROLLBACK.md)**: Manual CI-verified commit redeployment procedure and database safety rules.
- **[Observability Architecture](docs/operations/OBSERVABILITY.md)**: Prometheus metrics (`/metrics`), structured `log/slog` JSON logging, and OpenTelemetry tracing.
- **[Incident Response Runbooks](docs/operations/INCIDENT_RESPONSE.md)**: Step-by-step runbooks for application, database, and hardware outages.
- **[Backup & Restore Guide](docs/operations/BACKUP_AND_RESTORE.md)**: Dedicated database backups, retention policies, and manual restore drills.
- **[Disaster Recovery Plan](docs/operations/RECOVERY.md)**: Complete host replacement procedures and RPO/RTO recovery targets.

---

## Android Termux Production Deployment

On the Sony Xperia 1 host (`~/apps/gusby`):
```bash
# Deploys latest CI-verified commit on main branch directly to ~/services/gusby:
./deploy/termux/deploy.sh

# Deploy a specific CI-verified commit SHA (also used for rollback):
./deploy/termux/deploy.sh <commit_sha>

# Inspect live production health and service status:
./deploy/termux/status.sh

# Run read-only verification suite:
./deploy/termux/verify.sh
```

---

## Running Test & Benchmark Suites

### 1. Run Unit & Integration Tests
```bash
go test -count=1 -p 1 ./internal/...
```

### 2. Run the 15-Document Gold Evaluation Benchmark
Audits extraction precision, 100% evidence validity rate, prompt injection defense, and contradiction classification accuracy:
```bash
go test -count=1 -v ./eval/gusby/...
```

### 3. Run Admin Authorization Matrix Audit
```bash
go test -count=1 -v ./tests/admin/...
```

### 4. Run Live End-to-End Real-Groq Audit
Performs a live roundtrip against Groq LLM ingesting contradictory assertions, verifying exact byte/char offsets:
```bash
go test -count=1 -v -timeout 120s ./tests/gusby/...
```

---

## Project Specifications & Documentation

Architecture specifications reside in `docs/gusby/`:
- `00_PRODUCT_BRIEF.md`: Canonical Product Brief (Vietnamese).
- `01_PRD.md`: Vision, scope boundaries, and explicit out-of-scope list.
- `02_TRD.md`: Stack justification, system architecture, security, and job queue.
- `03_APP_FLOW.md`: Screen routes, review-as-state interaction, and evidence viewing workflow.
- `04_DESIGN_SYSTEM.md`: Pure white canvas, earthy preset palettes, and semantic zoom.
- `05_SCHEMA_AND_API.md`: PostgreSQL schema DDL and REST API specifications.
- `06_IMPLEMENTATION_PLAN.md`: Milestones, dependencies, and evaluation framework.
- `DECISIONS.md`: Strategic architecture decisions log.
