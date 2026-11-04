# Gusby Incident Response & Operational Runbooks

This document provides standardized, actionable runbooks for diagnosing, mitigating, and recovering from production incidents on the Sony Xperia 1 (Android Termux) host.

---

## 1. Incident Severity Definitions

| Severity | Definition | Target Resolution Time | Example |
|---|---|---|---|
| **SEV-1 (Critical)** | Core application or database completely unavailable. | < 15 minutes | Backend crash loop, database corruption, Android Termux killed. |
| **SEV-2 (Major)** | Major functionality impaired, ingestion blocked, or high error rates. | < 45 minutes | AI circuit breaker tripped, queue backlog stalled, Nginx 502 bad gateway. |
| **SEV-3 (Minor)** | Degraded performance, single component latency, non-blocking bug. | < 4 hours | High 95th percentile latency, single document parse failure. |

---

## 2. Standard Diagnostics & Triage Procedure

When an alert fires or an incident is reported, run the following triage commands:

```bash
# 1. SSH into the Xperia host
ssh termux-xperia

# 2. Check complete system status
cd ~/KBA
./deploy/termux/status.sh

# 3. Inspect application process status and logs
pm2 status gusby-backend
pm2 logs gusby-backend --lines 50

# 4. Check database connectivity
pg_isready -h 127.0.0.1 -p 5432
```

---

## 3. Specific Operational Runbooks

### Runbook 1: Application Crash / Backend Unavailable
**Symptoms**: Alert `GusbyApplicationDown`, HTTP 502 Bad Gateway from Nginx.  
**Action Steps**:
1. Check PM2 status: `pm2 status gusby-backend`.
2. If process status is `errored` or `stopped`:
   - Inspect error log: `tail -n 100 logs/backend-err.log`.
   - Check if database was unreachable during startup: `pg_isready`.
   - Check if configuration validation failed (invalid port or missing secret in `.env`).
3. Restart process: `pm2 restart gusby-backend`.
4. Verify recovery: `curl -s http://127.0.0.1:8081/api/health/live`.

---

### Runbook 2: Frontend Unavailable
**Symptoms**: Browser shows connection refused or Nginx default 404 page.  
**Action Steps**:
1. Check Nginx master process: `ps aux | grep nginx`.
2. If stopped, start Nginx: `nginx`.
3. If running, verify static files exist: `ls -la current/frontend/.output/public/index.html`.
4. Test local response: `curl -I http://127.0.0.1:8080/`.
5. Check Nginx error logs: `tail -n 50 $PREFIX/var/log/nginx/error.log`.

---

### Runbook 3: Database Unavailable
**Symptoms**: Alert `GusbyDatabaseUnreachable`, readiness returns `"database": "unreachable"`.  
**Action Steps**:
1. Check PostgreSQL process: `pg_ctl -D $PREFIX/var/lib/postgresql status`.
2. If PostgreSQL is stopped:
   - Check PostgreSQL log: `tail -n 100 $PREFIX/var/log/postgresql.log`.
   - Start database: `pg_ctl -D $PREFIX/var/lib/postgresql -l $PREFIX/var/log/postgresql.log start`.
3. Verify connection: `psql "$DATABASE_URL" -c "SELECT 1;"`.
4. Re-check readiness: `curl -s http://127.0.0.1:8081/api/health/ready`.

---

### Runbook 4: Database Disk Exhaustion
**Symptoms**: Alert `GusbyDiskSpacePressure`, PostgreSQL fails with "No space left on device".  
**Action Steps**:
1. Check disk utilization: `df -h /data`.
2. Prune old backups (keep latest 3):
   ```bash
   ls -lt ~/backups/gusby/gusby_*.sql.gz | tail -n +4 | awk '{print $9}' | xargs rm -f
   ```
3. Truncate application logs: `pm2 flush`.
4. Clean build artifacts and temporary files:
   ```bash
   cd ~/apps/gusby && rm -rf frontend/.nuxt frontend/.output bin/*.build
   ```
5. Restart backend if needed: `pm2 restart gusby-backend --update-env`.

---

### Runbook 5: Queue Backlog Stalled
**Symptoms**: Alert `GusbyQueueBacklogHigh`, documents stuck in `queued` or `uploading`.  
**Action Steps**:
1. Check AI Circuit Breaker state:
   ```bash
   curl -s http://127.0.0.1:8081/api/health/ready
   ```
2. If `ai_gate` is `circuit_open` or `paused`, see Runbook 6.
3. Inspect stuck jobs in database:
   ```sql
   SELECT id, document_id, stage, attempts, last_error, locked_at, locked_by
   FROM gusby.processing_jobs
   WHERE stage <> 'done' AND stage <> 'failed'
   ORDER BY run_at ASC LIMIT 10;
   ```
4. If a job is locked by a dead worker:
   ```sql
   UPDATE gusby.processing_jobs
   SET locked_at = NULL, locked_by = NULL, stage = 'queued'
   WHERE locked_at < now() - INTERVAL '15 minutes';
   ```

---

### Runbook 6: External AI Provider Outage (Groq API Down)
**Symptoms**: AI requests failing, Circuit Breaker trips to `circuit_open`.  
**Action Steps**:
1. Check Groq status at [status.groq.com](https://status.groq.com).
2. Check recent AI call logs:
   ```sql
   SELECT created_at, model, status, error_class, latency_ms
   FROM gusby.ai_call_log
   ORDER BY created_at DESC LIMIT 10;
   ```
3. Once Groq service is restored, reset the circuit breaker via Admin API:
   ```bash
   curl -X POST -b "gusby_session=YOUR_ADMIN_SESSION" http://127.0.0.1:8080/api/admin/ai/gate/reset-breaker
   ```
4. Active queue workers will immediately resume processing pending documents.

---

### Runbook 7: Failed Deployment
**Symptoms**: Deployment script exits with non-zero code or verification fails.  
**Action Steps**:
1. Inspect deployment terminal output or backend error logs:
   ```bash
   tail -n 100 ~/services/gusby/logs/backend-err.log
   ```
2. Verify current service status:
   ```bash
   ~/apps/gusby/deploy/termux/status.sh
   ```
3. If necessary, execute manual rollback by redeploying the previous CI-verified commit:
   ```bash
   cd ~/apps/gusby
   ./deploy/termux/deploy.sh <previous_ci_verified_commit_sha>
   ```
4. Verify system health with `deploy/termux/verify.sh`.

---

### Runbook 8: Failed Database Migration
**Symptoms**: Manual `./scripts/migrate.sh up` execution failed with an error.  
**Action Steps**:
1. Note the failing migration file name and error message from `migrate.sh` output.
2. Inspect `gusby.schema_migrations`:
   ```bash
   ./scripts/migrate.sh status
   ```
   The failing version was not marked as applied.
3. If partial DDL executed and corrupts the schema, restore from the automated pre-migration snapshot:
   ```bash
   LATEST_PRE_MIGRATE=$(ls -t backups/gusby_pre-migrate_*.sql.gz | head -n 1)
   ./scripts/restore.sh "$LATEST_PRE_MIGRATE" --force
   ```
4. Correct the migration SQL in a new commit.

---

### Runbook 9: Android Reboot / Power Loss
**Symptoms**: Xperia phone restarted due to battery depletion or OS update.  
**Action Steps**:
1. Ensure USB power is reconnected.
2. Open Termux (or start via Termux:Boot).
3. Acquire wake lock: `termux-wake-lock`.
4. Start PostgreSQL:
   ```bash
   pg_ctl -D $PREFIX/var/lib/postgresql start
   ```
5. Resurrect PM2 processes:
   ```bash
   pm2 resurrect || pm2 start ~/KBA/current/ecosystem.config.cjs --only gusby-backend
   ```
6. Start Nginx: `nginx`.
7. Run verification: `~/KBA/deploy/termux/verify.sh`.

---

### Runbook 10: Termux Process Termination (Android Low Memory Killer)
**Symptoms**: PM2 daemon and backend disappear without error logs.  
**Action Steps**:
1. Re-open Termux.
2. Confirm battery optimization exemption:
   - Android Settings → Apps → Termux → Battery → Set to **Unrestricted**.
3. Acquire wake lock: `termux-wake-lock`.
4. Restore PM2 processes: `pm2 resurrect`.
5. Check memory consumption: `pm2 monit`.

---

### Runbook 11: Network Interruption / Cloudflare Tunnel Disconnect
**Symptoms**: Local curl on phone works (`127.0.0.1:8080`), but external domain is unreachable.  
**Action Steps**:
1. Verify device WiFi / cellular connection: `ping -c 3 1.1.1.1`.
2. Check `cloudflared` tunnel process:
   ```bash
   ps aux | grep cloudflared
   ```
3. Restart tunnel:
   ```bash
   cloudflared tunnel run gusby-lab &
   ```

---

### Runbook 12: Disaster Recovery & Full Backup Restoration Drill
**Procedure**:
1. Identify the most recent healthy backup in `backups/`:
   ```bash
   ls -lht backups/gusby_*.sql.gz
   ```
2. Execute restore tool:
   ```bash
   ./scripts/restore.sh backups/gusby_manual_<timestamp>.sql.gz --force
   ```
3. Verify restored tables and migrations:
   ```bash
   ./scripts/migrate.sh status
   ./deploy/termux/verify.sh
   ```
