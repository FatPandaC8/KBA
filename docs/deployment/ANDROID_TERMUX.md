# Gusby Deployment Guide: Sony Xperia 1 (Android Termux ARM64)

This guide provides end-to-end instructions for deploying, updating, and operating Gusby on a Sony Xperia 1 (802SO) running Android with Termux, accessed via SSH from a Fedora development workstation.

---

## 1. Environment Architecture

- **Host Hardware**: Sony Xperia 1 (802SO), Qualcomm Snapdragon 855 (8 cores, ARM64), ~5.4 GiB RAM.
- **Operating System**: Android with Termux (Non-root user `u0_a...`).
- **Network Topology**:
  - **Nginx Reverse Proxy**: Port `8080` (public ingress via Cloudflare Tunnel or local LAN).
  - **Go Backend API & Queue Worker**: Port `8081` (binds `127.0.0.1` loopback, managed by PM2 as `gusby-backend`).
  - **PostgreSQL 16-18+**: Port `5432` (binds `127.0.0.1` loopback, managed via `pg_ctl`).
  - **Nuxt 4 Static SPA**: Pre-rendered static files served directly by Nginx (0 MB runtime memory).

---

## 2. Termux Host Provisioning (One-Time Setup)

On the Sony Xperia device, open Termux and run:

```bash
# 1. Update packages
pkg update && pkg upgrade -y

# 2. Install native toolchains
pkg install -y git golang nodejs-lts postgresql nginx openssl-tool curl termux-tools

# 3. Install PM2 process manager
npm install -g pm2

# 4. Acquire Wake Lock and Disable Android Battery Optimization
termux-wake-lock
# In Android Settings -> Apps -> Termux -> Battery -> Set to "Unrestricted"

# 5. Initialize PostgreSQL Cluster (if first time)
if [ ! -d "$PREFIX/var/lib/postgresql" ]; then
    initdb "$PREFIX/var/lib/postgresql"
fi

# 6. Start PostgreSQL via pg_ctl
pg_ctl -D "$PREFIX/var/lib/postgresql" -l "$PREFIX/var/log/postgresql.log" start

# 7. Create Dedicated Gusby Database & Role
# NEVER TOUCH OR MODIFY 'server_lab'
psql -d postgres -c "CREATE USER gusby WITH PASSWORD 'your_secure_password_here';"
psql -d postgres -c "CREATE DATABASE gusby_db OWNER gusby;"
psql -d gusby_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

---

## 3. Remote Access from Fedora Dev Host

On Fedora development workstation:

```bash
# 1. Add SSH config in ~/.ssh/config:
# Host xperia-termux
#     HostName 192.168.1.xxx (or Tailscale IP)
#     Port 8022
#     User u0_a...
#     IdentityFile ~/.ssh/id_ed25519

# 2. Test SSH connection
ssh xperia-termux
```

---

## 4. Production Deployment

To deploy a verified release from the repository:

```bash
# Inside repository on Xperia:
cd ~/KBA

# Execute the 14-step automated deployment agent:
./deploy/termux/deploy.sh
```

The script automatically:
1. Validates dependencies (`go`, `node`, `psql`, `nginx`, `pm2`).
2. Acquires Android Wake Lock to prevent CPU sleep during build.
3. Builds the Go backend binary on ARM64 (`CGO_ENABLED=0 go build ...`).
4. Generates the Nuxt 4 static SPA (`npm run generate`).
5. Dumps a safety backup before applying migrations (`./scripts/backup.sh pre-migrate`).
6. Executes idempotent database migrations (`./scripts/migrate.sh up`).
7. Atomically swaps the release symlink (`current`).
8. Restarts `gusby-backend` in PM2 (`pm2 restart gusby-backend`).
9. Executes multi-tier production verification (`./deploy/termux/verify.sh`).
10. Automatically rolls back to the previous release if verification fails.

---

## 5. Inspecting System Status

```bash
./deploy/termux/status.sh
```

Outputs:
- Active Release ID & Git Commit SHA
- PM2 Process Health
- PostgreSQL Database Connectivity
- Nginx Master Process
- Live API Health (`/api/health/live` and `/api/health/ready`)
- Last 5 deployment audit logs

---

## 6. Process Lifecycle Management

| Service | Start Command | Stop Command | Status Command |
|---|---|---|---|
| **Go Backend** | `pm2 start ecosystem.config.cjs --only gusby-backend` | `pm2 stop gusby-backend` | `pm2 status gusby-backend` |
| **PostgreSQL** | `pg_ctl -D $PREFIX/var/lib/postgresql start` | `pg_ctl -D $PREFIX/var/lib/postgresql stop` | `pg_ctl -D $PREFIX/var/lib/postgresql status` |
| **Nginx** | `nginx` | `nginx -s stop` | `ps aux \| grep nginx` |

> [!WARNING]
> Never use `pm2 restart all`. Only manage explicitly named processes (`pm2 restart gusby-backend`). PostgreSQL and Nginx are managed natively.
