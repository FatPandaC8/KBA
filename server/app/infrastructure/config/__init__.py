import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DEFAULT_AI_PROVIDERS: List[Dict[str, object]] = [
    {
        "id": "stt_local",
        "name": "faster-whisper (self-hosted)",
        "receives": ["audio recording"],
        "trains_on_data": False,
    },
    {
        "id": "embeddings_local",
        "name": "fastembed (self-hosted)",
        "receives": ["entity and relationship text"],
        "trains_on_data": False,
    },
    {
        "id": "extraction_local",
        "name": "local rule-based extraction (self-hosted)",
        "receives": ["transcript text"],
        "trains_on_data": False,
    },
]


@dataclass
class ServerSettings:
    app_env: str = os.getenv("ECHO_ENV", "production")
    db_path: str = os.getenv("ECHO_DB_PATH", "server/echo_backend.db")
    upload_dir: str = os.getenv("ECHO_UPLOAD_DIR", "server/uploads")
    pipeline_version: str = "v2.0-echo-mvp"
    max_voice_seconds: int = int(os.getenv("ECHO_MAX_VOICE_SECONDS", "120"))
    max_upload_bytes: int = int(os.getenv("ECHO_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
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

    # Consent. Bump the version when the provider list or data use changes.
    consent_version: str = os.getenv("ECHO_CONSENT_VERSION", "2026-10-29-v1")
    ai_providers_json: str = os.getenv("ECHO_AI_PROVIDERS", "")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def ai_providers(self) -> List[Dict[str, object]]:
        raw = self.ai_providers_json.strip()
        if not raw:
            return list(DEFAULT_AI_PROVIDERS)
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


_SETTINGS_INSTANCE: Optional[ServerSettings] = None


def get_settings() -> ServerSettings:
    global _SETTINGS_INSTANCE
    if _SETTINGS_INSTANCE is None:
        _SETTINGS_INSTANCE = ServerSettings()
    return _SETTINGS_INSTANCE
