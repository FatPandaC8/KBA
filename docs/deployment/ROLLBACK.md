# Gusby Rollback Procedure

In this simplified single-host setup, releases are not managed through versioned directories or automated symlink swaps.

---

## 1. How Rollback Works

If a deployment fails, `deploy.sh` stops immediately and reports the error.

To roll back to a previous known-good version:

1. Identify the previous CI-verified commit SHA from GitHub Actions or git history:
   ```bash
   git log --oneline -n 5
   ```
2. Redeploy that commit:
   ```bash
   cd ~/apps/gusby
   ./deploy/termux/deploy.sh <previous_commit_sha>
   ```

`deploy.sh` will:
- Verify that the previous commit passed GitHub Actions CI.
- Recompile the backend and copy it to `~/services/gusby/bin/gusby`.
- Regenerate the frontend and sync it to `~/services/gusby/frontend/`.
- Restart `gusby-backend` in PM2.
- Verify that the service is running and healthy.

---

## 2. Database Safety

Application rollbacks **never** drop or modify database columns automatically.

Gusby follows backward-compatible schema principles. If a migration needs to be corrected, apply a corrective migration forward using `./scripts/migrate.sh up`.
