"""E2E harness server for Playwright runs.

Serves the REAL Echo backend (FastAPI app, SQLite persistence, job worker,
rule-based extraction, local embeddings) on a loopback port. Only one port is
replaced deterministically: speech-to-text. STT is stubbed so the transcript
that enters the extraction pipeline is controlled by the test suite without
making other pipeline stages fakes (WHY: real whisper output is not
deterministic and would make entity assertions flaky; everything downstream
of the transcript is still a real code path).

The harness control routes exist ONLY when this launcher runs
(ECHO_E2E_MODE=1); the production app has no knowledge of them. All routes
are loopback-only and guarded with a per-run key. No real API keys are ever
needed: the extraction provider is rule_based and ECHO_ALLOW_REAL_LLM=0.

IMPORTANT: the workspace is cleaned BEFORE the app module is imported, so the
container always creates a fresh schema (importing-and-then-deleting the DB
file would leave the runtime with a schema-less database).
"""

import json
import os
import shutil
import sys
import threading

from fastapi import HTTPException, Request

E2E_KEY = os.getenv("ECHO_E2E_KEY", "")
E2E_MODE = os.getenv("ECHO_E2E_MODE", "") == "1"


def _clean_workspace(db_path: str, upload_dir: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = db_path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    shutil.rmtree(upload_dir, ignore_errors=True)
    os.makedirs(upload_dir, exist_ok=True)
    # Email outbox lives next to the DB file (registry: ECHO_EMAIL_OUTBOX may
    # also be set explicitly; both locations are cleaned for determinism).
    shutil.rmtree(os.path.join(os.path.dirname(db_path), "outbox"), ignore_errors=True)


_scripts: dict[str, dict] = {}
_lock = threading.Lock()


def main() -> None:
    if not E2E_MODE:
        print("E2E harness refuses to start: ECHO_E2E_MODE != 1", file=sys.stderr)
        sys.exit(2)
    if not E2E_KEY:
        print("E2E harness refuses to start: ECHO_E2E_KEY missing", file=sys.stderr)
        sys.exit(2)

    db_path = os.getenv("ECHO_DB_PATH", "")
    upload_dir = os.getenv("ECHO_UPLOAD_DIR", "")
    if not db_path or not upload_dir:
        print("E2E harness requires ECHO_DB_PATH and ECHO_UPLOAD_DIR", file=sys.stderr)
        sys.exit(2)

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    _clean_workspace(db_path, upload_dir)

    # Import AFTER cleanup: container init builds the schema on a fresh file.
    from uvicorn import run as _uvicorn_run  # noqa: E402
    from server.app.api.dependencies import get_container  # noqa: E402
    from server.app.domain.errors import ProviderNetworkError  # noqa: E402
    from server.app.main import app  # noqa: E402

    # Deterministic default so an unscripted capture fails loudly instead of
    # silently producing nonsense knowledge.
    no_script_msg = "E2E harness: no transcript script registered for capture"

    class ScriptedTranscriber:
        def transcribe(self, audio_file_path: str) -> str:
            capture_id = os.path.splitext(os.path.basename(audio_file_path))[0]
            with _lock:
                script = _scripts.get(capture_id)
            if script is None:
                raise ProviderNetworkError(f"{no_script_msg} {capture_id}")
            if script.get("fail") or script.get("error"):
                raise ProviderNetworkError(script.get("error") or "E2E scripted STT failure")
            return script["text"]

    container = get_container()
    container.process_capture_uc.transcriber = ScriptedTranscriber()

    def _guard(request: Request) -> None:
        if request.headers.get("x-e2e-key") != E2E_KEY:
            raise HTTPException(status_code=403, detail="forbidden")

    @app.post("/__e2e__/script", tags=["e2e"], include_in_schema=False)
    async def _script_stt(request: Request):
        _guard(request)
        body = await request.json()
        capture_id = body.get("captureId")
        if not capture_id:
            raise HTTPException(status_code=400, detail="captureId required")
        with _lock:
            _scripts[capture_id] = {
                "text": body.get("text", ""),
                "fail": bool(body.get("fail", False)),
                "error": body.get("error", ""),
            }
        return {"ok": True, "capture_id": capture_id}

    @app.delete("/__e2e__/script", tags=["e2e"], include_in_schema=False)
    async def _clear_scripts(request: Request):
        _guard(request)
        capture_id = None
        raw = await request.body()
        if raw:
            try:
                capture_id = json.loads(raw).get("captureId")
            except (ValueError, TypeError):
                pass
        with _lock:
            if capture_id:
                _scripts.pop(capture_id, None)
            else:
                _scripts.clear()
        return {"ok": True}

    print("E2E harness server starting", flush=True)
    _uvicorn_run(app, host="127.0.0.1", port=int(os.getenv("ECHO_E2E_PORT", "8123")), log_level="warning")


if __name__ == "__main__":
    main()
