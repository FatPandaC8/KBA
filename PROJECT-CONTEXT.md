# PROJECT-CONTEXT

Purpose: shared, declarative baseline for any agent or contributor working on Echo. Keep factual, short, secret-free. Update when phase or constraints change.

## Project

Echo — a personal voice-capture knowledge MVP. The user records voice notes on Android; the backend transcribes, extracts structured knowledge, builds a personal knowledge graph, and answers questions grounded only in stored graph data with visible refusal when evidence is insufficient.

## Stack

- Mobile: Flutter/Dart (`mobile/`), package `dev.echo.notes.dev`
- Backend: Python FastAPI + SQLite (`server/`), pip-installable deps
- AI (current, all local/free): faster-whisper STT, fastembed bge-small embeddings, deterministic rule-based extraction/Q&A
- Planned AI: Groq (free plan) as the only hosted LLM for extraction + answer synthesis, behind existing provider ports

## Current phase

Branch `mvp_v2_prd`. M1–M3 committed (latest `77cfa26`: recording pipeline, knowledge graph, search, Ask AI, deletion). In progress after owner decisions, in order:

1. REC-04/REC-06 rework: delete local audio once the server confirms receipt + durable storage (202 after file+DB commit), not on terminal `ready`; allow a new recording while the previous one is still processing (uploads stay serialized; mic is not gated by in-flight processing)
2. 2,000-node on-device check on the test device. Pass criteria: no ANR/crash/OOM, first render ≤ ~3 s, pan/zoom ~30 fps or better
3. Pinned rule-based baseline for M5: gold-set scorer harness in `server/eval/`, baseline pinned exactly to `mvp_v2_prd@77cfa26`
4. Groq integration (blocked until owner creates billing-disabled account and sets the key in a server env var; record real console Limits numbers before wiring)

## Constraints (hard, owner-set)

- No paid APIs or paid fallback, ever. No silent fallback to rule-based either.
- Groq is the only LLM provider (extraction + Q&A). STT stays local faster-whisper unless M5 shows WER > 15%. OpenRouter and Gemini are out; Cloudflare may be revisited later as an explicitly selected second provider.
- Groq receives transcript/subgraph text only — never audio, never other users' data.
- Transcripts/raw audio are never exposed as a knowledge source.
- Consent (GATE-01) names every provider + data received, re-prompts on any named-provider or model change (versioned).
- LLM output: schema-validate, persist validated output as the stage result, never re-call the provider on retry/resume. Deterministic fake LLM port (scripted 429/malformed JSON/timeout) ships with the real adapter. Honor Retry-After, max 3 automatic retries then manual. Specific "daily quota reached" message. Classify 429/quota vs outage vs network vs malformed vs invalid input.
- Keys live only in a server environment variable.
- Tests with every change; never claim unverified success. `[Default]` items allowed but must be listed in reports for owner confirmation.
- M5 release thresholds: WER ≤ 15%, entity F1 ≥ 0.70, relationship F1 ≥ 0.50, QA correctness ≥ 80%, correct refusal ≥ 80%. Never lowered silently.

## Definition of done (per work item)

- Implemented per PRD requirement IDs (`docs/PRD_MVP.md`: AUTH, GATE, REC, PRC, KG, SRCH, QA, VR, DEL, NET, ADM)
- Server tests green: `python3 -m pytest server/tests -q`; mobile tests green: `/home/guts/flutter/bin/flutter test`; `flutter analyze` clean
- Committed to `mvp_v2_prd` with conventional message referencing the requirement IDs
- Owner-facing report/summary with any `[Default]` choices listed; no unverified claims
