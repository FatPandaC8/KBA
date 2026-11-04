# Gusby Application Rollback Runbook

This runbook defines the technical procedures and safety boundaries for executing an emergency or automated rollback on the Sony Xperia 1 (Android Termux) host.

---

## 1. Rollback Architecture & Directory Structure

Gusby organizes releases using atomic symlinks in `~/services/gusby`:

```text
~/services/gusby/
├── current -> releases/release-b3c491f-20261104_010000Z   # Active release
├── previous -> releases/release-172fd33-20261103_120000Z  # Verified fallback release
├── releases/                                             # Versioned release directories
│   ├── release-b3c491f-20261104_010000Z/
│   └── release-172fd33-20261103_120000Z/
├── shared/
│   ├── .env                                              # Shared secrets outside Git
│   └── logs/                                             # Stable log directory
└── state/
    ├── active-release.json
    └── deployment-history.json.log
```

---

## 2. Automated vs Manual Rollback

### 2.1 Automated Rollback (During Deployment)
When running [`deploy/termux/deploy.sh`](../../deploy/termux/deploy.sh):
1. Step 10 runs [`deploy/termux/verify.sh`](../../deploy/termux/verify.sh).
2. If any verification probe fails (PM2 process status, liveness HTTP 200, readiness confirming connected to `gusby_db` and not `server_lab`, Nginx static SPA 200, API reverse proxy, or API smoke test), Step 11 triggers [`deploy/termux/rollback.sh`](../../deploy/termux/rollback.sh) automatically.
3. The symlink `current` is atomically reverted to `previous`.
4. PM2 restarts `gusby-backend`.
5. Verification suite re-runs to confirm the restored release is operational.

### 2.2 Manual Rollback (Post-Deployment Incident)
If an unexpected application defect is discovered after a successful deployment:
```bash
# SSH into Xperia Termux host:
ssh xperia-termux

# Execute rollback tool:
cd ~/apps/gusby
./deploy/termux/rollback.sh
```

The script will:
1. Verify the `previous` symlink exists and points to an existing release.
2. Atomically swap `current` to point to `previous`.
3. Restart `gusby-backend` in PM2 (`pm2 restart gusby-backend`).
4. Execute `deploy/termux/verify.sh` to confirm healthy recovery.
5. Record the rollback event in `~/services/gusby/state/deployment-history.json.log`.

---

## 3. Database Safety Rule: Zero Automated Schema Rollbacks

> [!CAUTION]
> **Never perform automated database rollbacks.**  
> Application rollbacks only revert application binaries and static frontend assets. They do not alter, recreate, or drop database tables or columns.

### Rationale:
1. Gusby strictly follows **Expand-and-Contract** schema design: all database migrations add backward-compatible schemas, columns with default values, or nullable fields.
2. The previous release can run safely against the newer database schema.
3. Dropping columns or tables automatically during a rollback destroys user data created while the new release was active.

### Handling Schema Incompatibilities:
If a migration requires corrective action:
1. Do not drop tables or columns blindly.
2. Write an explicit forward migration (e.g. `0003_fix_incompatibility.sql`) and apply it with `./scripts/migrate.sh up`.
3. In a disaster scenario where database data corruption occurred, restore explicitly from a verified backup:
   ```bash
   cd ~/apps/gusby
   ./scripts/restore.sh ~/services/gusby/backups/gusby_pre-migrate_<timestamp>.sql.gz --confirm-target-db=gusby_db
   ```
