# Gusby Production Deployment Guide: Sony Xperia 1 (Android Termux)

A minimal, understandable production deployment setup for Gusby on a Sony Xperia 1 running Android Termux.

---

## 1. Target Architecture

```text
Internet / LAN
       |
       v
 Nginx :8080
       |
       +---- / ----------> Static Nuxt frontend (~/services/gusby/frontend)
       |
       +---- /api/ ------> Go backend :8081 (~/services/gusby/bin/gusby)
                                |
                                v
                           PostgreSQL :5432 (database: gusby_db)
```

Only 4 core services run:
- **Nginx**: Listens on port `8080`, serves static SPA files, proxies `/api/` to `127.0.0.1:8081`.
- **Go Backend**: Runs on `127.0.0.1:8081`, managed by PM2 as `gusby-backend`.
- **PostgreSQL**: Runs on `127.0.0.1:5432`, managed independently via `pg_ctl`.
- **Static Frontend**: Pre-rendered static Nuxt 4 SPA (0 MB PM2 memory).

---

## 2. Directory Structure

```text
~/apps/gusby/                    # Git repository (source & scripts)
├── cmd/gusby/
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
│   │   └── status.sh
│   └── nginx/
│       └── gusby-termux.conf
└── ecosystem.config.cjs

~/services/gusby/                # Production runtime directory
├── bin/gusby                    # Compiled Go backend binary
├── frontend/                    # Generated static Nuxt SPA assets
├── logs/                        # Backend logs (backend-out.log, backend-err.log)
├── backups/                     # Database backups
└── .env                         # Production environment secrets (chmod 600)
```

---

## 3. Initial Setup (Once Only)

### Step 3.1: Install Termux Packages
```bash
pkg update && pkg upgrade -y
pkg install -y git golang nodejs-lts postgresql nginx openssl-tool curl jq termux-tools
npm install -g pm2
termux-wake-lock
```

*Note: In Android Settings &rarr; Apps &rarr; Termux &rarr; Battery &rarr; Select "Unrestricted".*

### Step 3.2: Initialize PostgreSQL & Create Dedicated Database
```bash
# Initialize data cluster if first time
if [ ! -d "$PREFIX/var/lib/postgresql" ]; then
    initdb "$PREFIX/var/lib/postgresql"
fi

# Start PostgreSQL service via pg_ctl
pg_ctl -D "$PREFIX/var/lib/postgresql" -l "$PREFIX/var/log/postgresql.log" start

# Provision dedicated user and database (server_lab remains untouched)
psql -d postgres -c "CREATE USER gusby_user WITH PASSWORD 'YOUR_STRONG_PASSWORD';"
psql -d postgres -c "CREATE DATABASE gusby_db OWNER gusby_user;"
psql -d gusby_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### Step 3.3: Clone Repository & Create Production Directory
```bash
mkdir -p ~/apps ~/services/gusby/bin ~/services/gusby/frontend ~/services/gusby/logs ~/services/gusby/backups
git clone https://github.com/FatPandaC8/KBA.git ~/apps/gusby
cd ~/apps/gusby

# Initialize production .env
cp .env.example ~/services/gusby/.env
chmod 600 ~/services/gusby/.env
```

Edit `~/services/gusby/.env`:
```ini
GUSBY_ENV=production
GUSBY_HOST=127.0.0.1
GUSBY_PORT=8081
GUSBY_DATABASE_URL=postgresql://gusby_user:YOUR_STRONG_PASSWORD@127.0.0.1:5432/gusby_db?sslmode=disable
GUSBY_SESSION_SECRET=GENERATE_WITH_OPENSSL_RAND_BASE64_32
GROQ_API_KEY=your_groq_api_key
```

### Step 3.4: Run First-Time Database Migrations
```bash
cd ~/apps/gusby
./scripts/migrate.sh status
./scripts/migrate.sh up
```

### Step 3.5: Configure Nginx
```bash
mkdir -p "$PREFIX/etc/nginx/conf.d"
cp deploy/nginx/gusby-termux.conf "$PREFIX/etc/nginx/conf.d/gusby.conf"
nginx -t
nginx
```

---

## 4. Normal Application Deployment

To deploy the latest CI-verified commit on `main`:

```bash
cd ~/apps/gusby
./deploy/termux/deploy.sh
```

Or deploy a specific CI-verified commit SHA:

```bash
./deploy/termux/deploy.sh <commit_sha>
```

What `deploy.sh` does:
1. Checks that required commands exist (`go`, `node`, `npm`, `pm2`, `curl`, `jq`, `git`).
2. Verifies via GitHub Actions API that `Gusby Production CI` completed with `success` for the commit.
3. Compiles the Go backend to `~/services/gusby/bin/gusby`.
4. Generates the static Nuxt frontend (`npm ci` and `npm run generate`).
5. Copies static frontend assets to `~/services/gusby/frontend/`.
6. Restarts `gusby-backend` in PM2.
7. Runs `deploy/termux/verify.sh` to confirm health.

Normal deployment **never** touches or restarts PostgreSQL, and never runs migrations.

---

## 5. Manual Database Migrations

When a code update includes a new database migration:

```bash
cd ~/apps/gusby

# Check pending migrations (Read-Only):
./scripts/migrate.sh status

# Apply pending migrations:
./scripts/migrate.sh up
```

Safety rules:
- Verifies connected database via `SELECT current_database()` (strictly refuses `server_lab`).
- Never run automatically by the deployment script.

---

## 6. Verification

To verify that the deployment is working correctly:

```bash
cd ~/apps/gusby
./deploy/termux/verify.sh
```

Checks:
- PM2 process `gusby-backend` is online.
- Backend liveness probe (`:8081/api/health/live`) returns HTTP 200.
- Backend readiness probe (`:8081/api/health/ready`) confirms database is connected and not `server_lab`.
- Nginx serves frontend at `http://127.0.0.1:8080/`.
- Nginx proxies `/api/health` to Go backend.

---

## 7. Logs and Process Management

```bash
# Check PM2 process status
pm2 status

# View live backend logs
pm2 logs gusby-backend

# Tail persistent logs
tail -f ~/services/gusby/logs/backend-out.log
tail -f ~/services/gusby/logs/backend-err.log

# Restart backend process
pm2 restart gusby-backend

# Reload Nginx configuration
nginx -t && nginx -s reload
```
