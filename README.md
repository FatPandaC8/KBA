# KBA — personal knowledge graph (MVP)

Self-hosted FastAPI backend on PostgreSQL. Mobile client (Flutter) is Phase 4.

## Run locally

```bash
# 1. PostgreSQL (port 5433 here because 5432 is busy; change as you like)
docker run -d --name kba-pg -e POSTGRES_USER=kba -e POSTGRES_PASSWORD=kba \
  -e POSTGRES_DB=kba -p 5433:5432 postgres:16-alpine

# 2. App
cd server
cp .env.example .env            # edit DATABASE_URL / JWT_SECRET / seed creds
pip install -e ".[test]"
alembic upgrade head            # apply migrations
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

First request seeds the initial admin from `.env` (`ADMIN_SEED_USERNAME` /
`ADMIN_SEED_PASSWORD`).

## API docs

FastAPI serves the OpenAPI spec at runtime — no separate tooling needed:

- `http://127.0.0.1:8000/docs` — Swagger UI (interactive)
- `http://127.0.0.1:8000/redoc` — ReDoc
- `http://127.0.0.1:8000/openapi.json` — raw spec

The `description=` arg on each `APIRouter` and route summary shows up in the UI;
add a docstring to a handler and it becomes its description automatically.

## Quick start once running

```bash
# login as the seeded admin
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"change-me"}' | jq -r .access_token)

curl -X POST http://127.0.0.1:8000/notes \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":"Alice works at Acme."}'
curl http://127.0.0.1:8000/notes -H "Authorization: Bearer $TOKEN"
```

## Tests

```bash
cd server
export $(grep -v '^#' .env | xargs)   # or set DATABASE_URL → .../kba_test
PYTHONPATH=. pytest                   # uses a test database on 5433
```

## Health

- `/health/live`, `/health/ready` — unauthenticated
- Last-active-admin deletion is blocked; `pg_advisory_xact_lock(1)` serializes admin mutations.

## Architecture

`MVP_PLAN.md` / `ARCHITECTURE.md` / `DATA_MODEL.md` / `API_SPEC.md` / `TEST_PLAN.md` in `docs/`.
