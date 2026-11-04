# Gusby Disaster Recovery (DR) Plan & Procedures

This document provides end-to-end disaster recovery instructions in the event of catastrophic failure, complete device destruction, or host replacement.

---

## 1. Disaster Recovery Scenarios & Objectives

| Metric | Target |
|---|---|
| **Recovery Point Objective (RPO)** | Maximum 24 hours of data loss (daily scheduled backups) or immediately prior to any migration. |
| **Recovery Time Objective (RTO)** | < 30 minutes to restore service on a replacement Android phone or Linux VPS. |

---

## 2. Complete Host Replacement Scenario (New Device Provisioning)

If the primary Sony Xperia 1 device suffers permanent hardware failure:

### Step 1: Provision Replacement Device
1. Install Termux and Termux:API from F-Droid.
2. Open Termux and install dependencies:
   ```bash
   pkg update && pkg upgrade -y
   pkg install -y git golang nodejs-lts postgresql nginx openssl-tool curl
   npm install -g pm2
   termux-wake-lock
   ```

### Step 2: Initialize Database Cluster & Gusby Database
```bash
initdb "$PREFIX/var/lib/postgresql"
pg_ctl -D "$PREFIX/var/lib/postgresql" -l "$PREFIX/var/log/postgresql.log" start

psql -d postgres -c "CREATE USER gusby WITH PASSWORD 'your_secure_password';"
psql -d postgres -c "CREATE DATABASE gusby_db OWNER gusby;"
psql -d gusby_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### Step 3: Clone Repository & Configure Environment
```bash
git clone https://github.com/FatPandaC8/KBA.git ~/KBA
cd ~/KBA

# Create shared production environment
mkdir -p shared
cat <<EOF > shared/.env
GUSBY_ENV=production
GUSBY_HOST=127.0.0.1
GUSBY_PORT=8081
GUSBY_DATABASE_URL=postgresql://gusby:your_secure_password@127.0.0.1:5432/gusby_db
GUSBY_SESSION_SECRET=$(openssl rand -base64 32)
GROQ_API_KEY=your_groq_api_key_here
EOF
```

### Step 4: Restore Latest Database Backup
Transfer the latest backup file from off-site storage or dev machine:
```bash
scp user@fedora:~/backups/gusby_latest.sql.gz ~/KBA/backups/
./scripts/restore.sh ~/KBA/backups/gusby_latest.sql.gz --force
```

### Step 5: Execute Initial Deployment
```bash
./deploy/termux/deploy.sh
```

### Step 6: Configure & Start Nginx
```bash
cp deploy/nginx/gusby-termux.conf $PREFIX/etc/nginx/conf.d/gusby.conf
nginx
```

### Step 7: Verify Service Restoration
```bash
./deploy/termux/verify.sh
```

---

## 3. Disaster Recovery Drill Checklist

Maintainers should practice this drill quarterly:
- [ ] Confirm latest backup exists in `backups/` and is valid (`gzip -t`).
- [ ] Spin up a temporary PostgreSQL instance on dev workstation.
- [ ] Execute `./scripts/restore.sh <backup_file> --force` on test database.
- [ ] Verify all tables and concept counts match expectations.
- [ ] Record test results and sign off on disaster recovery readiness.
