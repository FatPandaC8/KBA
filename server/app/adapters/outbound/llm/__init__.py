"""Provider-agnostic LLM plumbing.

The rest of the application only sees the ``LLMChatPort`` interface. Groq is
one implementation; ``FakeLLMClient`` is the deterministic test double. There
is deliberately no adapter that silently falls back to another provider.
"""

from .client import GroqChatClient
from .fake import FakeLLMClient, FakeScript
from .validation import (
    EXTRACTION_SCHEMA,
    EXTRACTION_SCHEMA_NAME,
    validate_extraction,
)

__all__ = [
    "GroqChatClient",
    "FakeLLMClient",
    "FakeScript",
    "EXTRACTION_SCHEMA",
    "EXTRACTION_SCHEMA_NAME",
    "validate_extraction",
]
