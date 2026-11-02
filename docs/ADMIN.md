# Echo Admin Dashboard

The React + TypeScript dashboard in `admin/` uses the FastAPI admin API and
PostgreSQL-backed read/write ports. It does not connect to the database
directly. Admin authentication uses the server's `ECHO_ADMIN_TOKEN` through the
`X-Admin-Token` header; missing, empty or wrong tokens fail closed.

The current pages are Overview, Users, Captures, Knowledge Graph (read-only)
and Audit Logs. System Operations and Monitoring are explicitly TODO. There
are no job/queue/worker views.

## Manual local setup

From the repository root:

```bash
docker compose up -d postgres
cp .env.example .env                 # edit ECHO_ADMIN_TOKEN before use
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r server/requirements.txt
set -a; source .env; set +a
(cd server && alembic upgrade head)
bash scripts/dev_server.sh           # API at http://127.0.0.1:8000
```

In another terminal, from the repository root:

```bash
cd admin
npm install
npm run dev
```

Open `http://127.0.0.1:5174/` and enter the `ECHO_ADMIN_TOKEN` value configured
in `.env`. Vite proxies `/api` requests to the backend on port 8000. To serve
the React bundle from FastAPI instead:

```bash
cd admin
npm run build
```

Then open `http://127.0.0.1:8000/admin`. The built `admin/dist` assets are
committed because the backend serves that directory.

## Seed development data (optional)

The seed requires explicit opt-in, refuses production, uses only repositories,
and stores its ownership registry in `app_settings`. It creates users,
captures, knowledge items and graph facts; it creates no job fixtures. A
failed sample capture stores `last_error` on the capture row.

The seed command itself does not source `.env`. Either uncomment/configure the
`E2E_*` values in `.env` before sourcing it, or export development-only values
in the current shell. Example:

```bash
export E2E_SEED_ENABLED=true
export E2E_ADMIN_EMAIL=admin@example.test
export E2E_ADMIN_PASSWORD='LocalDevOnly123!'
export E2E_USER_1_EMAIL=user1@example.test
export E2E_USER_1_PASSWORD='LocalDevOnly123!'
export E2E_USER_2_EMAIL=user2@example.test
export E2E_USER_2_PASSWORD='LocalDevOnly123!'
export E2E_USER_3_EMAIL=user3@example.test
export E2E_USER_3_PASSWORD='LocalDevOnly123!'
python -m server.tools.seed_admin seed
```

The seed does not create or change the shared admin token;
`ECHO_ADMIN_TOKEN` remains authoritative.

To remove only data owned by this seed:

```bash
E2E_RESET_CONFIRM=DELETE_ECHO_ADMIN_SEED \
  python -m server.tools.seed_admin reset --confirm-reset
```

## Current admin API shape

- Overview returns flat `users`, `captures`, `entities`, `relationships`
  counts, `capture_statuses`, `ingest_failures` aggregated from
  `captures.last_error`, and recent audit activity.
- Capture lists/details expose capture status/truth, whether a knowledge item
  exists, transcript/knowledge detail for admins, and `last_error`/
  `last_error_at` when present. There are no `stage`, `attempt`, queue or job
  fields.
- PATCH transcript edits the stored knowledge-item transcript.
- POST rerun-extraction calls the Text-KB `KnowledgeIngestorPort`
  synchronously with the stored transcript and existing `capture_id`.
  Successful replays do not create another capture. **Current limitation:**
  `TextKBUseCase.ingest()` returns the existing result as soon as it finds a
  capture that already has a knowledge item. Therefore PATCHing an already-
  ingested transcript and then calling rerun-extraction does not recompute its
  graph. Captures without a knowledge item can be ingested from their stored
  transcript; completed-capture re-extraction needs a separate explicit
  replace/rebuild operation before it can be described as working.
- `/api/admin/jobs` and worker-era retry routes are removed.

## Verify

```bash
# From repository root; Docker Postgres must be available.
python -m pytest server/tests/integration/test_admin_api.py \
  server/tests/integration/test_admin_console.py \
  server/tests/integration/test_admin_dashboard.py -q

cd admin && npm run build
```

To verify auth manually, omit `X-Admin-Token` from a GET (for example
`curl -i http://127.0.0.1:8000/api/admin/overview`): it should return `401`.
For authenticated calls, send `-H "X-Admin-Token: $ECHO_ADMIN_TOKEN"`.
