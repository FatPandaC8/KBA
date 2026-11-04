# Gusby Environment Configuration Reference

This document provides a comprehensive reference of all environment variables recognized by the Gusby Go backend API, background queue worker, Nuxt 4 frontend, and deployment automation scripts.

---

## 1. Backend Environment Variables (Go API & Queue Worker)

| Variable | Required (Prod) | Default Value | Description & Precedence |
|---|---|---|---|
| `GUSBY_ENV` | Optional | `development` | Runtime environment (`development`, `production`, `test`). In `production`, strict validation enforces non-default secrets and dedicated database URLs. |
| `GUSBY_ENV_FILE` | Optional | `<empty>` | Explicit filesystem path to `.env` file (e.g. `~/services/gusby/.env`). When set, loads environment variables directly from this file. |
| `GUSBY_HOST` | Optional | `127.0.0.1` | Loopback bind IP for HTTP server. Keep at `127.0.0.1` so backend is never directly exposed to internet. |
| `HOST` | Optional | `127.0.0.1` | Fallback for `GUSBY_HOST`. |
| `GUSBY_PORT` | Optional | `8081` | Network port for Go backend HTTP API. Port 8080 is reserved for Nginx. |
| `PORT` | Optional | `8081` | Fallback for `GUSBY_PORT`. |
| `GUSBY_DATABASE_URL` | **Yes** (Prod) | Fallback dev | **Primary** PostgreSQL connection string. Must target dedicated database (e.g. `gusby_db`) and role (`gusby_user`). **Connection to `server_lab` is strictly prohibited and rejected.** |
| `DATABASE_URL` | Optional | `<empty>` | Fallback database connection string if `GUSBY_DATABASE_URL` is omitted. |
| `GUSBY_EXPECTED_DB` | Optional | `<empty>` | Expected database name (e.g. `gusby_db`). When set, scripts and backend health checks verify that `SELECT current_database()` matches this string. |
| `GUSBY_SESSION_SECRET` | **Yes** (Prod) | Insecure dev key | Cryptographic secret for signing session cookies and validating CSRF tokens. Minimum 32 characters in production. Generate via `openssl rand -base64 32`. |
| `GUSBY_CORS_ALLOWED_ORIGINS` | Optional | Loopback ports | Comma-separated list of allowed CORS/CSRF origins (e.g. `http://127.0.0.1:8080,https://gusby.example.com`). |
| `GUSBY_OWNER_EMAIL` | Optional | `<empty>` | Email address of the system owner, automatically granted `is_admin = true` on initial startup. |
| `GROQ_API_KEY` | **Yes** (Prod) | `<empty>` | Groq Cloud API key for entity extraction, resolution, and conflict classification. |
| `GROQ_MODEL` | Optional | `openai/gpt-oss-120b` | Target LLM model identifier on Groq or OpenAI-compatible inference server. |
| `GROQ_BASE_URL` | Optional | `https://api.groq.com/openai/v1` | Base URL for LLM API endpoint. |
| `GROQ_RPM` | Optional | `30` | Request rate limit per minute. |
| `GROQ_TPM` | Optional | `8000` | Token rate limit per minute. |
| `GUSBY_DAILY_USER_TOKEN_BUDGET` | Optional | `40000` | Daily token budget per user to protect from quota exhaustion. |
| `E2E_SEED_ENABLED` | Optional | `false` | Development seed accounts flag. **Must be false in production.** |
| `E2E_ADMIN_EMAIL` | Optional | `<empty>` | Email for development/testing admin account (seeded when `E2E_SEED_ENABLED=true`). |
| `E2E_ADMIN_PASSWORD` | Optional | `<empty>` | Password for development/testing admin account. |
| `E2E_USER_1_EMAIL` .. `3` | Optional | `<empty>` | Emails for development/testing non-admin accounts. |
| `E2E_USER_1_PASSWORD` .. `3` | Optional | `<empty>` | Passwords for development/testing non-admin accounts. |

---

## 2. Frontend Client Variables (Nuxt 4 SPA)

| Variable | Required (Prod) | Default Value | Description |
|---|---|---|---|
| `GUSBY_API_BASE` | Optional | `""` (Empty string) | API prefix for browser HTTP client. Behind Nginx reverse proxy, leave empty so requests use relative path `/api/...` on the same origin. |
| `GUSBY_BACKEND_URL` | Optional | `http://127.0.0.1:8081` | Backend proxy target when running Nuxt dev server (`npm run dev`). |

---

## 3. Deployment & Operational Variables

| Variable | Required | Default Value | Description |
|---|---|---|---|
| `GUSBY_DEPLOY_ROOT` | Optional | `$HOME/services/gusby` | Production runtime directory root containing `bin/`, `frontend/`, `logs/`, and `.env`. |
| `GUSBY_BACKEND_URL` | Optional | `http://127.0.0.1:8081` | Backend health check URL used by `deploy/termux/verify.sh`. |
| `GUSBY_NGINX_URL` | Optional | `http://127.0.0.1:8080` | Nginx endpoint used by `deploy/termux/verify.sh`. |
| `GUSBY_BACKUP_DIR` | Optional | `$HOME/backups/gusby` | Destination directory for `.sql.gz` database backup archives. |
| `GUSBY_BACKUP_RETENTION_COUNT` | Optional | `10` | Minimum number of backup archives to keep. |
| `GUSBY_BACKUP_RETENTION_DAYS` | Optional | `7` | Days after which older backups exceeding the retention count are pruned. |

---

## 4. Generating Production Secrets

On your target host (Sony Xperia Termux), generate a cryptographically secure session secret:

```bash
openssl rand -base64 32
```

Add the resulting 32+ character string into `~/services/gusby/.env`. Never commit this file or print its contents into logs.
