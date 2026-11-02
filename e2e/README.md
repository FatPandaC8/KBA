# E2E status and manual checks

## Current API manual checks

The current end-to-end path is documented with copy/paste commands in the root
[`README.md`](../README.md): start Postgres 16, apply Alembic migrations, start
the API, create/login a user, grant consent, call `/api/stt` with raw audio,
call `/api/text-kb` with a UUID and text, then read `/api/graph`.

For a physical Android device, run `adb reverse tcp:8000 tcp:8000`, build/run
the Flutter app with `BACKEND_URL=http://127.0.0.1:8000`, and execute the app
flow. `scripts/dev_device_up.sh` automates the health check and port reverse.

## Playwright suite status

**The checked-in Playwright suite is a legacy worker/SQLite harness and is not
compatible with the current server pipeline.** Its current configuration and
specs still expect SQLite persistence, `POST /api/captures/upload`, recording
status polling, `/api/admin/jobs`, and a worker fixture. The current server
requires `DATABASE_URL` (PostgreSQL 16) and exposes `/api/stt` plus
`/api/text-kb` instead. Do not treat the legacy Playwright run as evidence that
the current API works; migrate its harness and specs before using it as a gate.

Relevant legacy files to migrate:

- `playwright.config.ts` — starts a SQLite/worker launcher.
- `server_launcher.py` — patches the old path-based transcriber and job use
  case.
- `helpers/harness.ts` and `tests/02-capture.spec.ts` — upload/poll/retry.
- `tests/05-admin.spec.ts` — admin job list/retry.
- `tests/07-persistence.spec.ts` — asserts `processing_jobs` and SQLite dump.

The current supported automated server tests are run from the repository root
against isolated PostgreSQL test databases:

```bash
python -m pytest server/tests -q
```

The current Flutter widget/unit suite is:

```bash
cd mobile
flutter analyze lib test
flutter test
```

For the current physical-device graph performance harness, see
`mobile/integration_test/perf_test.dart` and its `PERF_SESSION_TOKEN`/
`BACKEND_URL` command comment.
