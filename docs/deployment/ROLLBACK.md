# Gusby Application Rollback Guide

This runbook defines the technical procedures and decision tree for executing an emergency or automated rollback on the Sony Xperia 1 (Android Termux) host.

---

## 1. Rollback Architecture & Directory Symlinks

Gusby organizes releases using atomic symlinks:

```
$HOME/gusby/
├── releases/
│   ├── release-b3c491f-20261104_010000Z/   # Current active release
│   └── release-172fd33-20261103_120000Z/   # Previous verified release
├── current -> releases/release-b3c491f-20261104_010000Z
├── previous -> releases/release-172fd33-20261103_120000Z
├── shared/
│   ├── .env                                # Shared environment secrets
│   └── backups/                            # Database snapshots
└── state/
    ├── active-release.json
    └── deployment-history.json.log
```

---

## 2. Automated vs Manual Rollback

### 2.1 Automated Rollback (During Deployment)
When running [`deploy/termux/deploy.sh`](file:///home/guts/P2/KBA/deploy/termux/deploy.sh):
1. Step 11 runs [`deploy/termux/verify.sh`](file:///home/guts/P2/KBA/deploy/termux/verify.sh).
2. If any check fails (liveness, database ping, Nginx static SPA 200, API smoke test), Step 13 triggers [`deploy/termux/rollback.sh`](file:///home/guts/P2/KBA/deploy/termux/rollback.sh) automatically.
3. The symlink is swapped back to `previous`, PM2 reloads `gusby-backend`, and verification re-executes.

### 2.2 Manual Rollback (Post-Deployment Incident)
If an issue is discovered after deployment has completed:
```bash
# SSH into Xperia Termux host
ssh termux-xperia

# Execute rollback tool
cd ~/KBA
./deploy/termux/rollback.sh
```

The script will:
1. Verify `previous` symlink exists and points to a valid release.
2. Atomically switch `current` to point to `previous`.
3. Restart `gusby-backend` in PM2 (`pm2 restart gusby-backend`).
4. Execute `deploy/termux/verify.sh` to confirm healthy recovery.
5. Record the rollback event in `state/deployment-history.json.log`.

---

## 3. Database Safety Rule: No Automatic Schema Rollback

> [!CAUTION]
> **Never perform automated database rollbacks.**  
> Application rollbacks only revert application code and static assets. They do not alter the database.

### Why?
1. Gusby strictly follows **Expand-and-Contract** schema design: new database columns and tables are nullable or possess defaults, making them fully backward-compatible with older application versions.
2. Dropping or altering columns automatically during a rollback can destroy user data created while the new release was active.

### Handling Schema Incompatibilities
If a migration was not backward-compatible:
1. Do not drop tables or columns blindly.
2. Write a corrective forward migration (e.g., `0003_fix_incompatibility.sql`) that restores compatibility.
3. If data was corrupted, restore from the pre-migration snapshot taken automatically by `backup.sh`:
   ```bash
   ./scripts/restore.sh backups/gusby_pre-migrate_<timestamp>.sql.gz --force
   ```
