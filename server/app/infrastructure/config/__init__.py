import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class ServerSettings:
    app_env: str = os.getenv("ECHO_ENV", "production")
    db_path: str = os.getenv("ECHO_DB_PATH", "server/echo_backend.db")
    upload_dir: str = os.getenv("ECHO_UPLOAD_DIR", "server/uploads")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    pipeline_version: str = "v1.2-echo-real"
    max_voice_seconds: int = 30
    admin_token: str = os.getenv("ECHO_ADMIN_TOKEN", "echo-admin-secure-key-2026")

_SETTINGS_INSTANCE: Optional[ServerSettings] = None

def get_settings() -> ServerSettings:
    global _SETTINGS_INSTANCE
    if _SETTINGS_INSTANCE is None:
        _SETTINGS_INSTANCE = ServerSettings()
    return _SETTINGS_INSTANCE
