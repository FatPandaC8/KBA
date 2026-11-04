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
- Verify that the previous commit passed GitHub Actions CI (`Gusby Production CI`).
- Recompile the Go backend for ARM64 and replace `~/services/gusby/bin/gusby`.
- Regenerate the static Nuxt frontend and copy to `~/services/gusby/frontend/`.
- Restart `gusby-backend` in PM2 with `--update-env`.
- Run mandatory verification (`deploy/termux/verify.sh`).

---

## 2. Database Safety

Application rollbacks **never** drop or modify database columns automatically.

Gusby follows backward-compatible schema principles. If a migration needs to be corrected, apply a corrective migration forward using `./scripts/migrate.sh up`.
