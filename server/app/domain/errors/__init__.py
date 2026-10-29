class DomainError(Exception):
    """Base exception for all domain errors."""
    pass


class EntityNotFoundError(DomainError):
    """Raised when a domain entity is not found."""

    def __init__(self, entity_name: str, entity_id: str):
        super().__init__(f"{entity_name} with id '{entity_id}' not found.")
        self.entity_name = entity_name
        self.entity_id = entity_id


class ValidationError(DomainError):
    """Raised when domain constraints or invariants are violated."""
    pass


class AudioProcessingError(DomainError):
    """Raised when audio capture, decoding, or transcription fails."""
    pass


class AuthError(DomainError):
    """Raised when authentication or authorization fails.

    Messages are deliberately generic so callers cannot enumerate accounts.
    """


class ProviderNotConfiguredError(DomainError):
    """Raised when an optional external provider has no server-side config."""


class RateLimitedError(DomainError):
    """Raised when an abuse rate limit is exceeded."""

    def __init__(self, retry_after: int):
        super().__init__("Too many requests. Try again later.")
        self.retry_after = retry_after


class ConsentRequiredError(DomainError):
    """Raised when an action requires current AI-provider consent."""


# --------------------------------------------------------------- processing
class ProviderError(DomainError):
    """A provider failed while doing work (PRC-05: provider_failure)."""

    error_class = "provider_failure"


class QuotaExhaustedError(ProviderError):
    """A free-tier/quota limit was hit. Never retried automatically."""

    error_class = "quota_exhausted"


class ProviderNetworkError(ProviderError):
    """A transient network failure. Retried automatically."""

    error_class = "network_error"


class InvalidInputAudioError(DomainError):
    """The input itself is unusable (silent/corrupt/non-English)."""

    error_class = "invalid_input"


class InsufficientEvidenceError(DomainError):
    """The graph has too little evidence to answer without fabrication."""

    def __init__(self, message: str = "There is not enough evidence in your graph to answer that."):
        super().__init__(message)
