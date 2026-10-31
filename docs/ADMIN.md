# Echo Admin Dashboard

The Admin Dashboard is a React + TypeScript app in `admin/`. It uses the
existing FastAPI admin API; it does not create a second database or bypass the
server authorization boundary.

## Run locally

From the repository root, configure `.env` from `.env.example`, including a
non-empty `ECHO_ADMIN_TOKEN`. Start the backend first:

```bash
bash scripts/dev_server.sh
```

In another terminal:

```bash
cd admin
npm install
npm run dev
```

Open `http://127.0.0.1:5174/`. Vite proxies `/api` to the backend on port
8000. For the backend-served dashboard, run `npm run build` in `admin/` and
open `http://127.0.0.1:8000/admin`.

The dashboard covers Overview, Users, Captures, Knowledge Graph, and Audit
Logs. System Operations and Monitoring are intentionally marked TODO. Entities
and Relationships are read-only; graph changes come from the capture pipeline.

## Seed and reset development data

The seed is opt-in, idempotent, and tracks only records it owns. It refuses to
run in production. Credentials come from the environment; do not hardcode or
print them.

```bash
E2E_SEED_ENABLED=true python -m server.tools.seed_admin seed
E2E_RESET_CONFIRM=DELETE_ECHO_ADMIN_SEED \
  python -m server.tools.seed_admin reset --confirm-reset
```

Set `E2E_ADMIN_EMAIL/PASSWORD` and `E2E_USER_{1,2,3}_EMAIL/PASSWORD` before
seeding. `ECHO_DB_PATH` selects the existing SQLite database.

## Verification

```bash
python -m pytest server/tests -q
cd admin && npm run build
cd ../e2e && npm install && npm test
```

The Playwright configuration builds the admin app before starting its isolated
backend, so browser coverage exercises the current React dashboard.
