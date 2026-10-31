import importlib.util
import shutil
from typing import List

from server.app.application.dto import ProviderInfoDTO
from server.app.application.ports import ProviderRegistryPort
from server.app.infrastructure.config import (
    GROQ_PRIVACY_URL,
    GROQ_RETENTION_SUMMARY,
    GROQ_TERMS_URL,
    ServerSettings,
)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class LocalProviderRegistry(ProviderRegistryPort):
    """Report exactly which providers are active and what each receives.

    The registry is derived from the selected provider, not from key presence,
    so the consent screen never claims Groq is used when it is not (and never
    hides it when it is).
    """

    def __init__(self, settings: ServerSettings):
        self.settings = settings

    def list_providers(self) -> List[ProviderInfoDTO]:
        stt_ready = _module_available("faster_whisper") and shutil.which("ffmpeg") is not None
        embeddings_ready = _module_available("fastembed")
        providers = [
            ProviderInfoDTO(
                id="stt_local",
                name="faster-whisper (self-hosted)",
                kind="speech_to_text",
                receives=["audio recording"],
                trains_on_data=False,
                available=stt_ready,
                detail="" if stt_ready else "faster-whisper or ffmpeg is not installed",
                retention="Audio and transcript stay on your server.",
            ),
            ProviderInfoDTO(
                id="embeddings_local",
                name="fastembed (self-hosted)",
                kind="embeddings",
                receives=["entity and relationship text"],
                trains_on_data=False,
                available=embeddings_ready,
                detail="" if embeddings_ready else "fastembed is not installed; semantic search falls back to lexical ranking",
                retention="Vectors stay on your server.",
            ),
        ]
        if self.settings.llm_provider == "groq":
            groq_ready = bool(self.settings.groq_api_key)
            detail = "" if groq_ready else "GROQ_API_KEY is not set on the server"
            providers.append(
                ProviderInfoDTO(
                    id="extraction_groq",
                    name=f"Groq hosted model ({self.settings.llm_model})",
                    kind="extraction",
                    receives=["transcript text"],
                    trains_on_data=False,
                    available=groq_ready,
                    detail=detail,
                    model=self.settings.llm_model,
                    retention=GROQ_RETENTION_SUMMARY,
                    privacy_url=GROQ_PRIVACY_URL,
                    terms_url=GROQ_TERMS_URL,
                )
            )
        else:
            providers.append(
                ProviderInfoDTO(
                    id="extraction_local",
                    name="local rule-based extraction (self-hosted)",
                    kind="extraction",
                    receives=["transcript text"],
                    trains_on_data=False,
                    available=True,
                    retention="Text stays on your server.",
                )
            )
        return providers
