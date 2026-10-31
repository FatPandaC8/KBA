"""Build the configured LLM adapter. No implicit provider fallback."""

from typing import Optional

from server.app.application.ports import LLMChatPort, LLMUsageRepositoryPort
from server.app.domain.errors import ProviderError
from server.app.infrastructure.config import ServerSettings

from .budget import TokenBudget
from .client import GroqChatClient
from .fake import FakeLLMClient


def build_llm_client(
    settings: ServerSettings, usage_repo: LLMUsageRepositoryPort
) -> Optional[LLMChatPort]:
    provider = (settings.llm_provider or "").strip().lower()
    if provider in ("", "rule_based", "local"):
        return None
    if provider == "fake":
        return FakeLLMClient(model=settings.llm_model or "fake-model")
    if provider != "groq":
        raise ProviderError(f"Unknown LLM provider: {settings.llm_provider!r}")
    if not settings.groq_api_key:
        # Fail closed. Selecting Groq without a key must never quietly switch
        # to the deterministic rule-based extractor.
        raise ProviderError(
            "Groq is selected but GROQ_API_KEY is not configured on the server."
        )
    budget = TokenBudget(
        usage_repo,
        provider="groq",
        model=settings.llm_model,
        rpm=settings.groq_rpm,
        rpd=settings.groq_rpd,
        tpm=settings.groq_tpm,
        tpd=settings.groq_tpd,
    )
    return GroqChatClient(
        settings.groq_api_key,
        settings.llm_model,
        base_url=settings.groq_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_retry_wait_seconds=settings.llm_max_retry_wait_seconds,
        budget=budget,
    )
