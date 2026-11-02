import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

GROQ_PRIVACY_URL = "https://console.groq.com/docs/your-data"
GROQ_TERMS_URL = "https://groq.com/terms-of-use"
GROQ_RETENTION_SUMMARY = (
    "Groq does not retain inference inputs/outputs by default. It may retain "
    "them for up to 30 days only to troubleshoot platform reliability or "
    "investigate abuse; Zero Data Retention can be enabled in Groq Data "
    "Controls. Groq states API data is not used to train models. Data is "
    "processed in the United States (GCP)."
)

# Free-plan limits published by Groq on 2026-10-30 for the default model.
# The account limits page remains authoritative; these are configurable.
GROQ_FREE_LIMITS = {
    "openai/gpt-oss-120b": {
        "rpm": 30,
        "rpd": 1000,
        "tpm": 8000,
        "tpd": 200000,
    }
}


def _provider_entry(
    provider: str, model: str, available: bool
) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = [
        {
            "id": "stt_local",
            "name": "faster-whisper (self-hosted)",
            "kind": "speech_to_text",
            "receives": ["audio recording"],
            "trains_on_data": False,
            "retention": "Audio and transcript stay on your server.",
        },
        {
            "id": "embeddings_local",
            "name": "fastembed (self-hosted)",
            "kind": "embeddings",
            "receives": ["entity and relationship text"],
            "trains_on_data": False,
            "retention": "Vectors stay on your server.",
        },
    ]
    if provider == "groq":
        entries.append(
            {
                "id": "extraction_groq",
                "name": f"Groq hosted model ({model})",
                "kind": "extraction",
                "receives": ["transcript text"],
                "trains_on_data": False,
                "model": model,
                "retention": GROQ_RETENTION_SUMMARY,
                "privacy_url": GROQ_PRIVACY_URL,
                "terms_url": GROQ_TERMS_URL,
                "available": available,
            }
        )
    else:
        entries.append(
            {
                "id": "extraction_local",
                "name": "local rule-based extraction (self-hosted)",
                "kind": "extraction",
                "receives": ["transcript text"],
                "trains_on_data": False,
                "retention": "Text stays on your server.",
            }
        )
    return entries


@dataclass
class ServerSettings:
    app_env: str = os.getenv("ECHO_ENV", "production")
    # Database configuration: either SQLite path (ECHO_DB_PATH) or PostgreSQL URL (DATABASE_URL)
    # If DATABASE_URL is set, PostgreSQL is used; otherwise SQLite with db_path.
    db_path: str = os.getenv("ECHO_DB_PATH", "server/echo_backend.db")
    database_url: str = os.getenv("DATABASE_URL", "")
    upload_dir: str = os.getenv("ECHO_UPLOAD_DIR", "server/uploads")
    pipeline_version: str = "v2.0-echo-mvp"
    max_voice_seconds: int = int(os.getenv("ECHO_MAX_VOICE_SECONDS", "120"))
    max_upload_bytes: int = int(os.getenv("ECHO_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
    # Text-KB limit (pipeline split): a single ingest call's transcript cap.
    max_text_kb_chars: int = int(os.getenv("ECHO_MAX_TEXT_KB_CHARS", "20000"))
    # Admin authentication. Empty value fails closed; replaced by an email
    # allowlist in M4. No default credential is ever baked into the source.
    admin_token: str = os.getenv("ECHO_ADMIN_TOKEN", "")
    # Comma-separated browser origins. Native Android clients do not need CORS.
    cors_origins: str = os.getenv("ECHO_CORS_ORIGINS", "")

    # User authentication
    session_ttl_hours: int = int(os.getenv("ECHO_SESSION_TTL_HOURS", "720"))
    verify_token_ttl_minutes: int = int(os.getenv("ECHO_VERIFY_TOKEN_TTL_MINUTES", "1440"))
    reset_token_ttl_minutes: int = int(os.getenv("ECHO_RESET_TOKEN_TTL_MINUTES", "30"))
    password_min_length: int = int(os.getenv("ECHO_PASSWORD_MIN_LENGTH", "10"))
    auth_rate_limit_per_minute: int = int(os.getenv("ECHO_AUTH_RATE_LIMIT_PER_MINUTE", "20"))
    google_client_id: str = os.getenv("ECHO_GOOGLE_CLIENT_ID", "")
    email_outbox_path: str = os.getenv("ECHO_EMAIL_OUTBOX", "server/outbox")
    # True only for local development. The API never returns raw tokens when
    # this is false, so a production deployment cannot leak verification links.
    expose_dev_tokens: bool = os.getenv("ECHO_ENV", "production") in ("test", "development")

    # Consent. The effective version is derived from the base version plus the
    # active provider/model, so switching either re-prompts every user.
    consent_version: str = os.getenv("ECHO_CONSENT_VERSION", "2026-10-30-v4")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    # Explicit provider selection. "groq" never silently degrades to the
    # rule-based extractor: a missing key fails closed.
    llm_provider: str = os.getenv(
        "ECHO_LLM_PROVIDER",
        "rule_based" if os.getenv("ECHO_ENV", "production") == "test" else "groq",
    )
    llm_timeout_seconds: int = int(os.getenv("ECHO_LLM_TIMEOUT_SECONDS", "45"))
    llm_max_retries: int = int(os.getenv("ECHO_LLM_MAX_RETRIES", "3"))
    llm_repair_attempts: int = int(os.getenv("ECHO_LLM_REPAIR_ATTEMPTS", "1"))
    llm_max_retry_wait_seconds: int = int(os.getenv("ECHO_LLM_MAX_RETRY_WAIT_SECONDS", "8"))
    llm_max_prompt_chars: int = int(os.getenv("ECHO_LLM_MAX_PROMPT_CHARS", "24000"))
    groq_rpm: int = int(os.getenv("ECHO_GROQ_RPM", "30"))
    groq_rpd: int = int(os.getenv("ECHO_GROQ_RPD", "1000"))
    groq_tpm: int = int(os.getenv("ECHO_GROQ_TPM", "8000"))
    groq_tpd: int = int(os.getenv("ECHO_GROQ_TPD", "200000"))
    # A deliberate opt-in for real calls in test-like environments. Automated
    # tests leave this unset and use the deterministic fake port.
    allow_real_llm: bool = os.getenv("ECHO_ALLOW_REAL_LLM", "0") in ("1", "true", "True")
    ai_providers_json: str = os.getenv("ECHO_AI_PROVIDERS", "")

    # Processing jobs (PRC-02 … PRC-05). The background loop itself is the
    # separate worker process (D8): `python -m app.worker`.
    job_retry_limit: int = int(os.getenv("ECHO_JOB_RETRY_LIMIT", "3"))
    job_lease_seconds: int = int(os.getenv("ECHO_JOB_LEASE_SECONDS", "300"))
    job_poll_seconds: float = float(os.getenv("ECHO_JOB_POLL_SECONDS", "1.0"))
    worker_enabled: bool = os.getenv("ECHO_WORKER_ENABLED", "1") not in ("0", "false", "False")

    # D7: 3 attempts total, 30s backoff after attempt 1 and 120s after
    # attempt 2, +/-20% jitter. All env-overridable.
    job_max_attempts: int = int(os.getenv("ECHO_JOB_MAX_ATTEMPTS", "3"))
    job_backoff_a1_seconds: float = float(os.getenv("ECHO_JOB_BACKOFF_A1_SECONDS", "30"))
    job_backoff_a2_seconds: float = float(os.getenv("ECHO_JOB_BACKOFF_A2_SECONDS", "120"))
    job_backoff_jitter: float = float(os.getenv("ECHO_JOB_BACKOFF_JITTER", "0.2"))

    # PostgreSQL connection pool (ADR R7). The API opens its pool in the
    # FastAPI lifespan; the worker process owns its own pool. No schema is
    # created at startup: ``alembic upgrade head`` owns the schema.
    database_pool_min: int = int(os.getenv("ECHO_DB_POOL_MIN", "1"))
    database_pool_max: int = int(os.getenv("ECHO_DB_POOL_MAX", "4"))
    database_connect_timeout: float = float(os.getenv("ECHO_DB_CONNECT_TIMEOUT", "30"))
    database_statement_timeout_ms: int = int(
        os.getenv("ECHO_DB_STATEMENT_TIMEOUT_MS", "30000")
    )
    database_idle_in_tx_timeout_ms: int = int(
        os.getenv("ECHO_DB_IDLE_IN_TX_TIMEOUT_MS", "30000")
    )
    # Local-dev knob: "off" trades crash-window durability for commit latency
    # when the Docker volume's WAL sync stalls (see ADR D3 note). Default on.
    database_synchronous_commit: str = os.getenv(
        "ECHO_DB_SYNCHRONOUS_COMMIT", "on"
    ).strip() or "on"

    # Duplicate matching bands (KG-02)
    duplicate_auto_link_threshold: float = float(os.getenv("ECHO_DUPLICATE_AUTO_LINK", "0.90"))
    duplicate_flag_threshold: float = float(os.getenv("ECHO_DUPLICATE_FLAG", "0.75"))

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def ai_providers(self) -> List[Dict[str, object]]:
        raw = self.ai_providers_json.strip()
        if not raw:
            return _provider_entry(
                self.llm_provider, self.llm_model, self.llm_provider_available
            )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("ECHO_AI_PROVIDERS must be valid JSON") from exc
        if not isinstance(parsed, list) or not parsed:
            raise ValueError("ECHO_AI_PROVIDERS must be a non-empty JSON array")
        for entry in parsed:
            if not isinstance(entry, dict) or "id" not in entry or "name" not in entry:
                raise ValueError("Each AI provider needs an id and a name")
        return parsed

    @property
    def llm_model(self) -> str:
        return self.groq_model

    @llm_model.setter
    def llm_model(self, value: str) -> None:
        if value and value.strip():
            self.groq_model = value.strip()

    @property
    def llm_provider_available(self) -> bool:
        if self.llm_provider == "groq":
            return bool(self.groq_api_key)
        return self.llm_provider in ("rule_based", "fake")

    @property
    def effective_consent_version(self) -> str:
        """Consent version changes whenever provider or model changes."""
        return f"{self.consent_version}:{self.llm_provider}:{self.llm_model}"

    def llm_limits(self) -> Dict[str, int]:
        return {
            "rpm": self.groq_rpm,
            "rpd": self.groq_rpd,
            "tpm": self.groq_tpm,
            "tpd": self.groq_tpd,
        }


_SETTINGS_INSTANCE: Optional[ServerSettings] = None


def get_settings() -> ServerSettings:
    global _SETTINGS_INSTANCE
    if _SETTINGS_INSTANCE is None:
        _SETTINGS_INSTANCE = ServerSettings()
    return _SETTINGS_INSTANCE
