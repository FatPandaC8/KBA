# Gusby Production Deployment Guide: Sony Xperia 1 (Android Termux ARM64)

This document provides the definitive, production-oriented guide for deploying, operating, and maintaining Gusby on a Sony Xperia 1 (802SO) running Android with Termux, accessed via SSH from a workstation.

---

## 1. System Architecture

- **Host Hardware**: Sony Xperia 1 (802SO), Qualcomm Snapdragon 855 (ARM64), 6 GB RAM.
- **Operating Environment**: Android with Termux (Non-rooted, single user `u0_a...`).
- **Network Topology & Port Allocations**:
  - **Port 8080 (Public/LAN)**: Nginx Reverse Proxy (terminates ingress from Cloudflare Tunnel or local LAN).
  - **Port 8081 (Loopback `127.0.0.1`)**: Go Backend API & Job Queue Worker (managed by PM2 as `gusby-backend`).
  - **Port 5432 (Loopback `127.0.0.1`)**: PostgreSQL database (managed independently via `pg_ctl`).
- **Frontend**: Nuxt 4 Vue SPA compiled with `ssr: false` into static HTML/JS/CSS, served directly by Nginx (0 MB runtime memory in PM2).
- **Backend**: Single statically-linked Go binary compiled for `linux/arm64`.

```mermaid
flowchart TD
    subgraph Ingress ["Public Ingress"]
        Client["Browser Client"]
        Tunnel["Cloudflare Tunnel / LAN"]
    end

    subgraph Host ["Sony Xperia 1 — Android Termux"]
        Nginx["Nginx Reverse Proxy (:8080)"]
        SPA["Static Nuxt 4 SPA Files\n(~/services/gusby/current/frontend/.output/public)"]
        Backend["Go Backend API & Queue Worker (:8081)\n(PM2: gusby-backend)"]
        PG["PostgreSQL (:5432 Loopback)\nDatabase: gusby_db | Schema: gusby"]
        ServerLab["Preserved Database: server_lab\n(Untouched / Isolated)"]
    end

    Client --> Tunnel
    Tunnel --> Nginx
    Nginx -->|/ (Static SPA)| SPA
    Nginx -->|/api/* (Reverse Proxy)| Backend
    Backend -->|pgx pool| PG
```

---

## 2. Directory Structure

To maintain clean separation between source code and persistent runtime data:

```text
~/apps/gusby/                    # Git repository (Source code & deployment scripts)
├── backend/
├── frontend/
├── migrations/gusby/
├── scripts/
│   ├── migrate.sh
│   ├── backup.sh
│   └── restore.sh
├── deploy/
│   ├── termux/
│   │   ├── deploy.sh
│   │   ├── verify.sh
│   │   ├── rollback.sh
│   │   └── status.sh
│   └── nginx/
│       └── gusby-termux.conf
└── ecosystem.config.cjs

~/services/gusby/                # Production runtime directory
├── current -> releases/release-<sha>-<timestamp>   # Active release symlink
├── previous -> releases/release-<sha>-<prev>       # Previous release (for instant rollback)
├── releases/                    # Versioned releases (pruned automatically, keeps last 3)
│   └── release-<sha>-<timestamp>/
│       ├── bin/gusby
│       ├── frontend/.output/public/
│       ├── release-metadata.json
│       └── .env -> ~/services/gusby/shared/.env
├── shared/
│   ├── .env                     # Production environment secrets (chmod 600, outside Git)
│   └── logs/                    # Persistent logs
│       ├── backend-out.log
│       └── backend-err.log
├── state/                       # Deployment audit history
│   ├── active-release.json
│   └── deployment-history.json.log
└── backups/                     # Dedicated database backups (.sql.gz)
```

---

## 3. Critical Architectural Rules & Safety Decisions

1. **Independent Database Lifecycle**:
   PostgreSQL is an independent persistent service. Normal application deployment **never**:
   - Restarts or stops PostgreSQL.
   - Reinitializes PostgreSQL.
   - Creates, drops, or alters databases.
   - Executes database migrations automatically.
   - Modifies schemas or runs backups/restores automatically.
2. **Dedicated Gusby Database**:
   - Gusby runs exclusively against `gusby_db` under role `gusby_user`.
   - The pre-existing `server_lab` database is strictly preserved and never accessed.
   - All migration, backup, and restore scripts verify the connected database using PostgreSQL itself (`SELECT current_database()`) and abort immediately if `server_lab` is detected.
3. **CI-Gated Deployments**:
   - Deployments strictly require a commit that passed the GitHub Actions `Gusby Production CI` workflow.
   - No `--force-unverified` bypass is permitted in the deployment pipeline.

---

## 4. First-Time Setup Procedure

### Step 4.1: Install Termux Packages
On the Xperia device inside Termux:
```bash
pkg update && pkg upgrade -y
pkg install -y git golang nodejs-lts postgresql nginx openssl-tool curl jq tar gzip termux-tools
npm install -g pm2
termux-wake-lock
```

*Note: In Android Settings &rarr; Apps &rarr; Termux &rarr; Battery &rarr; Select "Unrestricted".*

### Step 4.2: Start PostgreSQL & Provision Dedicated Database
```bash
# Initialize data cluster if first time
if [ ! -d "$PREFIX/var/lib/postgresql" ]; then
    initdb "$PREFIX/var/lib/postgresql"
fi

# Start PostgreSQL service via pg_ctl
pg_ctl -D "$PREFIX/var/lib/postgresql" -l "$PREFIX/var/log/postgresql.log" start

# Provision dedicated user and database (NEVER touch server_lab)
psql -d postgres -c "CREATE USER gusby_user WITH PASSWORD 'YOUR_STRONG_PASSWORD';"
psql -d postgres -c "CREATE DATABASE gusby_db OWNER gusby_user;"
psql -d gusby_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### Step 4.3: Clone Repository & Create Shared Runtime Directory
```bash
# Clone to ~/apps/gusby
mkdir -p ~/apps
git clone https://github.com/FatPandaC8/KBA.git ~/apps/gusby
cd ~/apps/gusby

# Create production runtime directory structure
mkdir -p ~/services/gusby/shared/logs ~/services/gusby/backups ~/services/gusby/state

# Initialize shared .env
cp .env.example ~/services/gusby/shared/.env
chmod 600 ~/services/gusby/shared/.env
```

Edit `~/services/gusby/shared/.env` with your real production values:
```bash
GUSBY_ENV=production
GUSBY_HOST=127.0.0.1
GUSBY_PORT=8081
GUSBY_DATABASE_URL=postgresql://gusby_user:YOUR_STRONG_PASSWORD@127.0.0.1:5432/gusby_db?sslmode=disable
GUSBY_EXPECTED_DB=gusby_db
GUSBY_SESSION_SECRET=$(openssl rand -base64 32)
GROQ_API_KEY=your_groq_api_key_here
```

### Step 4.4: Run First-Time Database Migrations
Execute the explicit migration tool:
```bash
cd ~/apps/gusby
./scripts/migrate.sh validate
./scripts/migrate.sh up
./scripts/migrate.sh status
```

### Step 4.5: Configure Nginx
```bash
# Copy Termux configuration into conf.d
mkdir -p "$PREFIX/etc/nginx/conf.d"
cp deploy/nginx/gusby-termux.conf "$PREFIX/etc/nginx/conf.d/gusby.conf"

# Verify that $PREFIX/etc/nginx/nginx.conf includes conf.d:
# include /data/data/com.termux/files/usr/etc/nginx/conf.d/*.conf;

# Test and start Nginx
nginx -t
nginx
```

---

## 5. Normal Application Deployment Procedure

Application deployment only builds code, updates static assets, and restarts the backend process:

```bash
cd ~/apps/gusby

# Option A: Deploy the latest CI-verified commit on main
./deploy/termux/deploy.sh

# Option B: Deploy a specific CI-verified commit SHA
./deploy/termux/deploy.sh <commit_sha>
```

### What `deploy.sh` does:
1. Acquires deployment lock (`/tmp/gusby-deploy.lock`) and Termux wake lock.
2. Validates dependencies (`go`, `node`, `npm`, `pm2`, `curl`, `jq`, `tar`, `gzip`, `git`).
3. Queries GitHub Actions API to verify that `Gusby Production CI` completed with status `success` for the target commit.
4. Exports a clean source tree into `~/services/gusby/releases/release-<sha>-<timestamp>`.
5. Compiles the Go backend for ARM64 (`bin/gusby`).
6. Builds the Nuxt 4 static SPA (`npm ci`, `npm run generate`).
7. Atomically updates the `~/services/gusby/current` symlink and preserves `previous`.
8. Restarts `gusby-backend` in PM2 (`pm2 restart gusby-backend`).
9. Executes read-only multi-tier verification (`deploy/termux/verify.sh`).
10. Automatically rolls back to the previous release if verification fails.
11. Prunes older releases, retaining the last 3 releases to conserve disk space.

---

## 6. Manual Database Migration Procedure

Database migrations are **never** run automatically during application deployment. When a new schema migration is introduced:

```bash
cd ~/apps/gusby

# 1. Inspect migration status (Read-only)
./scripts/migrate.sh status

# 2. Validate database connectivity & extension readiness (Read-only)
./scripts/migrate.sh validate

# 3. Apply pending migrations (creates safety backup first, updates schema_migrations)
./scripts/migrate.sh up

# 4. Confirm all migrations are marked APPLIED
./scripts/migrate.sh status
```

Safety features:
- Uses `flock` and PostgreSQL advisory lock (ID `847291`) to prevent concurrent runs.
- Verifies that `current_database()` is `gusby_db` and strictly refuses `server_lab`.
- Creates a safety pre-migration snapshot before applying DDL.

---

## 7. Read-Only Production Verification Procedure

To inspect application health without modifying database state or restarting services:

```bash
cd ~/apps/gusby
./deploy/termux/verify.sh
```

Probes tested:
- **Tier 0**: PM2 process status (`gusby-backend`).
- **Tier 1**: Backend liveness (`:8081/api/health/live`).
- **Tier 2**: Backend readiness & database identity (`:8081/api/health/ready` confirms database is connected to `gusby_db` and not `server_lab`).
- **Tier 3**: Static SPA availability through Nginx (`:8080/`).
- **Tier 4**: Nginx API reverse proxy (`:8080/api/health`).
- **Tier 5**: Read-only auth error contract (`POST :8081/api/auth/login` returns 401).
- **Tier 6**: Prometheus telemetry endpoint (`:8081/metrics`).

---

## 8. Process Management & Log Inspection

```bash
# Check PM2 process table
pm2 status

# Tail Go backend logs
tail -f ~/services/gusby/shared/logs/backend-out.log
tail -f ~/services/gusby/shared/logs/backend-err.log

# View PM2 real-time logs
pm2 logs gusby-backend

# Restart only backend (zero downtime for static frontend)
pm2 restart gusby-backend

# Inspect overall system status
~/apps/gusby/deploy/termux/status.sh
```

---

## 9. Nginx Configuration & Reload

To apply changes to Nginx routing:
```bash
# Always test syntax first
nginx -t

# Reload configuration without dropping connections
nginx -s reload
```

---

## 10. Database Backup and Restore Procedures

### Database Backup
```bash
cd ~/apps/gusby

# Manual backup:
./scripts/backup.sh manual

# Scheduled backup (e.g. from cron):
./scripts/backup.sh scheduled
```
Backups are created in `~/services/gusby/backups/gusby_<type>_<timestamp>.sql.gz`.  
The script dumps only schema `gusby`, verifies compressed archive integrity (`gzip -t`), and prunes backups older than 7 days while keeping at least 10 copies.

### Database Restore
```bash
cd ~/apps/gusby

# Interactive restore (prompts to type the exact database name):
./scripts/restore.sh ~/services/gusby/backups/gusby_manual_20261104_120000Z.sql.gz

# Automated / Non-interactive restore:
./scripts/restore.sh ~/services/gusby/backups/gusby_manual_20261104_120000Z.sql.gz --confirm-target-db=gusby_db
```

---

## 11. Known Android / Termux Constraints

- **No systemd**: Services must be launched via `pg_ctl` and `pm2`.
- **Non-root environment**: All services run under the Termux user. Privileged ports (<1024) cannot be used directly; Nginx listens on port `8080`.
- **Android Battery Optimization**: If Termux is put to sleep by Android Doze, background connections stall. Always keep `termux-wake-lock` active and set battery optimization to "Unrestricted".
- **Memory Boundaries**: Compiled Go backend is capped at `256M` in PM2 (`max_memory_restart: '256M'`).
- **Storage Conservation**: Nuxt static generation avoids running Node.js in production. Releases are capped at 3 version directories to avoid filling device flash memory.

---

## 12. Recovery Procedure if Deployment Fails

### 12.1 Automatic Rollback
If `deploy/termux/verify.sh` fails during deployment, `deploy.sh` automatically invokes `deploy/termux/rollback.sh`, restores the `previous` symlink, restarts PM2, and re-verifies.

### 12.2 Manual Rollback
To immediately revert an active release after a post-deployment incident:
```bash
cd ~/apps/gusby
./deploy/termux/rollback.sh
```
This:
1. Atomically updates `current` to point to `previous`.
2. Restarts `gusby-backend` in PM2.
3. Runs `verify.sh` to confirm system availability.
4. Does **not** touch or revert PostgreSQL schemas, ensuring no data loss.
