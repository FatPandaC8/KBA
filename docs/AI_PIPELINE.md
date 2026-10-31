# AI Pipeline Reference

Current pipeline: **local STT → LLM-assisted extraction → entity resolution → knowledge graph persistence → hybrid knowledge search**.

Only text ever reaches a hosted provider. Audio never leaves the server.

---

## 1. End-to-end flow

```
Android recorder (.m4a)
        │  upload (authenticated, consent required)
        ▼
POST /api/captures/upload ──► processing_jobs (SQLite is the queue)
        │
        ▼
1. transcribe   faster-whisper, local, 16 kHz mono via ffmpeg
        │        transcript persisted in the job output
        ▼
2. extract      provider selected explicitly:
        │         - groq       hosted, schema-constrained JSON, text only
        │         - rule_based local deterministic extractor, no network
        │        validated extraction persisted as a stage result
        ▼
3. save         knowledge graph updated: entities + relationships resolved,
        │        deduplicated, and merged (tombstones and user_edited records
        │        are respected; contradictions are flagged, not merged)
        ▼
4. embed        fastembed BAAI/bge-small-en-v1.5, local
        ▼
5. completed    recording becomes READY; knowledge graph and search are available
```

The job row is the contract. Each stage writes its output before advancing, so a restart resumes from the persisted stage instead of re-running completed work (including completed LLM calls).

> [!NOTE]
> **Transcripts are internal pipeline artifacts.** The transcript produced in step 1 is used as input to step 2 (extraction). It is stored in the database for pipeline debugging, extraction evaluation, and admin-initiated transcript correction. Transcripts are never served through any user-facing API endpoint. Transcript access is restricted to admin-authenticated endpoints only. This is enforced at the backend API layer, not by UI omission.
>
> Admins may correct transcript text (e.g. to fix ASR errors that led to incorrect extraction). Corrections are persisted with `user_edited = 1` so that a re-run of the extraction stage uses the corrected transcript rather than re-calling the ASR model. This capability supports ASR evaluation and extraction evaluation dataset preparation — it does not constitute a user-facing feature or a model training pipeline.

### Audio constraints

- Recorder: AAC-LC, 64 kbps, 44.1 kHz, `.m4a`.
- Maximum recording: `ECHO_MAX_VOICE_SECONDS` (default **120 s**); enforced on both the client timer and the upload endpoint.
- Server decodes to mono 16 kHz signed 16-bit PCM with `ffmpeg` before STT.
- STT is **English-only**. A detected non-English language is rejected with a typed input error.

---

## 2. Provider and model selection

Selection is explicit. There is **no silent fallback**: selecting Groq without a server key fails closed and the job records a provider error.

| Variable | Default | Meaning |
|---|---|---|
| `ECHO_LLM_PROVIDER` | `groq` (`rule_based` when `ECHO_ENV=test`) | `groq` or `rule_based` |
| `GROQ_API_KEY` | unset | Server-side only. Never logged, returned, or committed. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Model identifier |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | OpenAI-compatible endpoint |
| `ECHO_LLM_TIMEOUT_SECONDS` | `45` | Per-request timeout |
| `ECHO_LLM_MAX_RETRIES` | `3` | Automatic transport retries (capped at 3) |
| `ECHO_LLM_REPAIR_ATTEMPTS` | `1` | Schema-repair attempts (0 or 1) |
| `ECHO_LLM_MAX_PROMPT_CHARS` | `24000` | Hard prompt bound |
| `ECHO_WHISPER_MODEL` | `tiny` | Local STT model (`tiny`, `base.en`, `small.en`, …) |
| `ECHO_WHISPER_COMPUTE_TYPE` | `int8` | CTranslate2 compute type for local STT |

Provider and model can also be changed at runtime in the admin console (ADM-07). The selection is persisted in `app_settings` and applied without a restart.

### Key handling

- `GROQ_API_KEY` is read from the server environment only.
- `.env` is git-ignored; `.env.example` documents the variables without values.
- `scripts/dev_server.sh` sources `.env` into the server process and refuses to start if `ECHO_LLM_PROVIDER=groq` has no key.
- Automated tests set `ECHO_LLM_PROVIDER=rule_based` and `ECHO_ALLOW_REAL_LLM=0`. `GroqChatClient` additionally refuses real calls when `ECHO_ENV=test` unless `ECHO_ALLOW_REAL_LLM=1` is set explicitly.

---

## 3. Groq free-tier limits and retention

Recorded from public Groq documentation on **2026-10-30**. The account limits page remains authoritative; every value below is configurable because limits change.

| Limit | Value | Variable |
|---|---|---|
| Requests per minute (RPM) | 30 | `ECHO_GROQ_RPM` |
| Requests per day (RPD) | 1,000 | `ECHO_GROQ_RPD` |
| Tokens per minute (TPM) | 8,000 | `ECHO_GROQ_TPM` |
| Tokens per day (TPD) | 200,000 | `ECHO_GROQ_TPD` |

Sources:

- Rate limits: <https://console.groq.com/docs/rate-limits>
- Data handling: <https://console.groq.com/docs/your-data>
- Terms of use: <https://groq.com/terms-of-use>

### Privacy and retention

- Groq does **not** retain inference inputs/outputs by default.
- It may retain data for up to **30 days** only to troubleshoot platform reliability or investigate abuse.
- **Zero Data Retention** can be enabled in Groq Data Controls.
- Groq states API data is **not used to train models**.
- Data is processed in the **United States (GCP)**.

The consent screen shows these facts, names Groq, and links the privacy and terms URLs.

### Budgeting

Every hosted call is checked against RPM/RPD/TPM/TPD *before* it is sent, using the provider's reported usage from `llm_usage`. A call that could cross a limit is refused with a typed quota error instead of being sent. Usage is reported in the admin console (last 24 hours: calls and tokens).

### Retry behavior

- Transport retries: up to 3, with exponential backoff.
- `429`: `Retry-After` is honoured. A long wait is surfaced to the user instead of being slept through; a short wait is retried within the cap.
- Schema-invalid or malformed JSON: exactly **one** repair attempt with the validation error appended. A second failure fails the stage — it never degrades to rule-based output.
- Timeout, outage, and network failures are typed and retryable.
- After the automatic retry cap is exhausted, the recording is marked failed with a manual retry action.

---

## 4. Extraction contract

The hosted extractor returns strict JSON (`response_format` = `json_schema`, `strict: true`, low temperature) with:

```json
{
  "title": "short noun phrase",
  "core_idea": "one sentence",
  "entities": [{"name": "Echo", "type": "project", "confidence": 0.95}],
  "relationships": [
    {"source": "Echo", "target": "FastAPI",
     "relation_type": "depends_on", "confidence": 0.9}
  ]
}
```

Local validation enforces:

- entity types in `person | project | organization | place | concept | tool | idea`
- relationship types in `Supports | Example of | Related to | Depends on | Constrained by | Contradicts`
- `source`/`target` must exactly match an extracted entity name
- no self-loops, no duplicate edges, confidence in `[0, 1]`
- bounded counts and prompt size

Entity and relationship IDs are deterministic (`uuid5` over user, capture, type, and normalized name), so re-running extraction for one capture is idempotent.

### Persistence and resume

- Validated output is stored in `processing_jobs.stage_outputs["extraction"]` together with provider/model/token metadata.
- Resuming a job reads that stored result. It never re-calls the provider.
- Tombstoned entities are not recreated.
- `user_edited = 1` knowledge items are never overwritten by a later save.
- A background lease heartbeat renews the job lease during slow provider calls; provider latency cannot make a healthy job look abandoned.

---

## 5. Knowledge search

> [!NOTE]
> Embedding-based search is a retrieval mechanism, not AI reasoning. The knowledge graph is independently useful and searchable without any LLM. Graph traversal and relationship lookups are deterministic operations over stored data.

`GET /api/graph` and the knowledge search endpoint operate per authenticated user. Search ranks entities and relationships by:

1. Local embedding similarity (fastembed), when an index is available.
2. Lexical overlap, with question words and stopwords removed.
3. A relevance floor (`ECHO_GRAPHRAG_RELEVANCE_FLOOR`, default `0.12`).

Text-only fallback never crosses users. Transcript full-text search is a separate endpoint and also scoped to the authenticated owner.

---

## 6. Admin configuration (ADM-07)

| Endpoint | Purpose |
|---|---|
| `GET /api/admin/ai-config` | Active provider/model, availability, limits, consent version, 24 h usage, recent calls |
| `PUT /api/admin/ai-config` | Switch provider/model for STT, extraction, or embeddings; persisted and applied without restart |
| `POST /api/admin/ai-config/test` | Minimal live call; reports success/failure, token count, latency, and typed error without exposing the key |

Changing the extraction provider or model changes the effective consent version (`<base>:<provider>:<model>`), so every user is re-prompted before their next recording.

---

## 7. Repeatable benchmark

The benchmark runs the exact extraction adapter the pipeline uses against a fixed gold set and prints precision/recall/F1 for entities and relationships. The rule-based extractor is the pinned baseline.

```bash
# Deterministic, offline, no socket.
python -m server.eval.score --provider rule_based

# Hosted comparison. Requires an explicit opt-in and a server-side key.
python -m server.eval.score --provider groq \
    --model openai/gpt-oss-120b --allow-real-calls \
    --json-out /tmp/opencode/groq-benchmark.json
```

Gold set: `server/eval_data/gold/gold_v1.json` (8 transcripts). The command prints the gold file SHA-256 so a report can be tied to an exact dataset.

Rule-based baseline measured on 2026-10-30:

```
Entities : P=0.571 R=0.667 F1=0.615 (tp=16 fp=12 fn=8)
Relations: P=0.231 R=0.750 F1=0.353 (tp=9 fp=30 fn=3)
```

The baseline is noisy by design: it favours recall and over-extracts. Use the same gold set and the printed delta to evaluate a hosted model. No quality claim is made for Groq until that run is executed and recorded.

---

## 8. Test strategy

- All automated tests use `FakeLLMClient` (scripted valid JSON, malformed JSON, 429, timeout, outage). No test opens a network socket or reads the real key.
- The HTTP client tests monkeypatch transport and verify retry caps, Retry-After handling, typed errors, and the test-environment refusal.
- Pipeline tests verify persistence, one-repair semantics, no re-call on resume, tombstones, and `user_edited` protection.

```bash
python -m pytest -q          # from the repository root
cd mobile && flutter analyze
```
