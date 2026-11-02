# Echo — voice-first personal knowledge graph

Echo is a Flutter app and FastAPI service that turns a voice recording into a
transcript and then into knowledge-graph data. **The app calls two independent
synchronous APIs:** `POST /api/stt`, then `POST /api/text-kb`. There is no worker,
job queue, capture-status poll, or capture-level retry schedule. The app keeps
the transcript in memory between calls; retrying Text-KB reuses the same
`capture_id`.

Current implementation note: when Groq is selected, its HTTP client still has
bounded provider-transport retries/backoff inside the Text-KB request (plus an
optional schema repair call). This is not a persisted job retry; it is a known
deviation from a literal “no retry/backoff” interpretation and is detailed in
[`docs/AI_PIPELINE.md`](docs/AI_PIPELINE.md).

## Current architecture

```text
Flutter recorder
    │ audio bytes (authenticated)
    ▼
POST /api/stt ── local faster-whisper ──► transcript (response only; not stored)
    │
    │ transcript + client-generated UUID (authenticated + consent)
    ▼
POST /api/text-kb ── extract / resolve / link / deduplicate / embed / prune
    │                     one Postgres unit of work
    ▼
knowledge item + graph changes committed together
```

The database is PostgreSQL 16 only. Alembic owns the schema. The audio remains
on the phone; it is not uploaded or persisted by the server. Transcripts are
stored with the knowledge item and are available only through admin routes.
See [persistence architecture](docs/architecture/persistence.md) and
[AI pipeline](docs/AI_PIPELINE.md).

`server/tools/migrate_self_entities.py` is a retained SQLite-era maintenance
script, not part of this setup. Do not run it against the current Postgres
server; use the repository migration chain and Postgres seed tools instead.

## Run locally (manual)

These commands are for a local development machine. Run them from the repository
root unless a command says otherwise.

### 1. Start PostgreSQL 16 and configure the server

Prerequisites: Docker Compose, Python 3.11+ (3.12 recommended), `ffmpeg`,
Flutter + Android SDK, and Node.js/npm if using the admin dashboard.

```bash
docker compose up -d postgres
cp .env.example .env
```

Edit `.env` before starting the server:

- Keep the local `DATABASE_URL` aligned with `docker-compose.yml` for a local
  database. The example credentials are development-only.
- Set `ECHO_ADMIN_TOKEN` to a private random value. Generate one with
  `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
- For the no-network local extractor, set `ECHO_LLM_PROVIDER=rule_based` and
  `ECHO_KB_EXTRACTOR=local`. For Groq extraction, set `ECHO_LLM_PROVIDER=groq`,
  `ECHO_KB_EXTRACTOR=groq`, and a server-side `GROQ_API_KEY`. Mobile API calls
  cannot select a provider; the admin AI-config API can change the server's
  persisted runtime provider configuration.
- `ECHO_STT_PROVIDER=faster_whisper` is the supported STT provider.

Export the `.env` values for Alembic; Alembic does not source `.env` itself:

```bash
set -a
source .env
set +a
```

Install Python packages and apply migrations once:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r server/requirements.txt
(cd server && alembic upgrade head)
```

Start the API in a second terminal from the repository root:

```bash
source .venv/bin/activate
bash scripts/dev_server.sh
```

The script reads `.env` and serves `127.0.0.1:8000`. It does not run
migrations: `alembic upgrade head` is an explicit setup step. Check it with:

```bash
curl -i http://127.0.0.1:8000/api/health
```

### 2. Run the Android app

For an emulator, use the host address supported by that emulator (commonly
`http://10.0.2.2:8000`). For a USB-connected physical Android device, run:

```bash
adb devices
adb reverse tcp:8000 tcp:8000
cd mobile
flutter pub get
flutter run -d <device-id> --dart-define=BACKEND_URL=http://127.0.0.1:8000
```

`adb reverse` is lost when the device disconnects or the adb server restarts;
run it again in that case. The app URL is a build-time `BACKEND_URL`, not an
editable Settings value. Sign in or create an account in the app. The app
obtains and stores its own session token; do not paste the admin token into the
app.

For a repeatable device setup, `bash scripts/dev_device_up.sh` starts the dev
server if needed and installs the reverse mapping. It requires a working local
`.env` and exactly one authorized Android device.

### 3. Run the admin dashboard

The API serves the committed `admin/dist` bundle at `/admin`. To develop the
React UI with hot reload:

```bash
cd admin
npm install
npm run dev
```

Open `http://127.0.0.1:5174/`; Vite proxies `/api` to port 8000. Sign in using
the `ECHO_ADMIN_TOKEN` configured on the server. To rebuild the API-served UI:

```bash
npm run build
```

See [Admin Dashboard](docs/ADMIN.md) for the feature list, API, seed/reset and
verification commands.

## API workflow and manual smoke test

`POST /api/stt` accepts a **raw audio request body** (not multipart), requires a
user session, and persists nothing. The server enforces a 25 MiB audio-byte cap
and a 120-second decoded-duration cap by default. `POST /api/text-kb` accepts
JSON `{ "capture_id": "<UUID>", "text": "..." }`, requires a session and
current consent, and is capped at 20,000 characters by default. Repeating the
same request with the same `capture_id` for the same user returns the existing
result; reusing another user's ID returns `409`.

For a local manual API test, create and verify a development user, log in, and
grant consent. The development server exposes a verification token in the
signup response:

```bash
EMAIL="you@example.test"
read -r -s -p 'Password: ' PASSWORD; echo
SIGNUP="$(curl -fsS http://127.0.0.1:8000/api/auth/signup \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")"
VERIFY_TOKEN="$(python -c 'import json,sys; print(json.load(sys.stdin)["dev_verification_token"])' <<< "$SIGNUP")"
curl -fsS http://127.0.0.1:8000/api/auth/verify-email \
  -H 'Content-Type: application/json' -d "{\"token\":\"$VERIFY_TOKEN\"}"
LOGIN="$(curl -fsS http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")"
TOKEN="$(python -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<< "$LOGIN")"
curl -fsS http://127.0.0.1:8000/api/consent \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"granted":true}'
```

Then run these calls with that user session token:

```bash
curl -i -X POST http://127.0.0.1:8000/api/stt \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: audio/wav' \
  --data-binary @/path/to/short-recording.wav

curl -i -X POST http://127.0.0.1:8000/api/text-kb \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"capture_id":"00000000-0000-4000-8000-000000000001","text":"I met Anna at the cafe yesterday."}'

curl -i http://127.0.0.1:8000/api/graph \
  -H "Authorization: Bearer $TOKEN"
```

The sample UUID is illustrative; generate a new UUID for a new capture. A
validation or size error returns a typed `detail` body. Network/provider
failures are returned in the request; the user retries in the app.

## Tests and builds

The repository-root pytest configuration provisions an isolated PostgreSQL
test database. Docker Compose's `postgres` service must be available:

```bash
python -m pytest server/tests -q
cd mobile && flutter analyze lib test && flutter test
cd ../admin && npm run build
```

`e2e/README.md` documents the current status of the checked-in Playwright
suite: its tests still target the removed worker/SQLite API and must be
migrated before they are a valid current-pipeline test gate. Do not point any
test command at production data.

## Provider and environment settings

See `.env.example` for the runnable local configuration. Important settings:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | required | PostgreSQL 16 connection URL |
| `ECHO_ADMIN_TOKEN` | empty (fails closed) | Admin API authentication |
| `ECHO_STT_PROVIDER` | `faster_whisper` | STT adapter selected at startup |
| `ECHO_KB_EXTRACTOR` | follows `ECHO_LLM_PROVIDER` | `local` or `groq`; server config, also editable by the admin AI-config endpoint |
| `ECHO_LLM_PROVIDER` | `groq` outside tests | LLM provider configuration; no silent fallback |
| `GROQ_API_KEY` | unset | Server-only credential when Groq is enabled |
| `ECHO_MAX_VOICE_SECONDS` | `120` | Decoded audio duration limit |
| `ECHO_MAX_UPLOAD_BYTES` | `26214400` | Raw STT request-body limit |
| `ECHO_MAX_TEXT_KB_CHARS` | `20000` | Text-KB transcript length limit |
| `ECHO_UPLOAD_DIR` | `server/uploads` | Legacy/admin audio storage path; new client captures do not upload audio |

## Historical docs

`docs/M3_REPORT.md` and `docs/M1_AUDIT.md` describe earlier milestones. They
are historical and may refer to the former asynchronous pipeline; use the
current architecture and API docs for behavior now.
