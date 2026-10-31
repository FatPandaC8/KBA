"""Deterministic fake LLM port for automated tests.

All test suites use this client. It never opens a socket and never reads the
real API key. Scripted entries can return valid JSON, malformed JSON, a 429,
a timeout, or any other typed provider error.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from server.app.application.dto import LLMResponse
from server.app.domain.errors import (
    ProviderMalformedResponseError,
    ProviderNetworkError,
    ProviderOutageError,
    ProviderTimeoutError,
    QuotaExhaustedError,
)


@dataclass
class FakeScript:
    """One scripted response.

    Exactly one of ``content``, ``raw_text`` or ``error`` is used. ``raw_text``
    simulates malformed JSON; ``error`` simulates a typed provider failure.
    """

    content: Optional[Dict[str, Any]] = None
    raw_text: Optional[str] = None
    error: Optional[BaseException] = None
    prompt_tokens: int = 120
    completion_tokens: int = 80
    latency_ms: int = 5
    delay_seconds: float = 0.0


class FakeLLMClient:
    provider = "fake"

    def __init__(
        self,
        script: Optional[List[Union[FakeScript, Dict[str, Any], BaseException]]] = None,
        *,
        model: str = "fake-model",
        default_content: Optional[Dict[str, Any]] = None,
    ):
        self.model = model
        self._script: List[FakeScript] = [self._coerce(item) for item in (script or [])]
        self.default_content = default_content
        self.calls: List[Dict[str, Any]] = []
        self.last_usage: Dict[str, Any] = {}

    @staticmethod
    def _coerce(item: Union[FakeScript, Dict[str, Any], BaseException]) -> FakeScript:
        if isinstance(item, FakeScript):
            return item
        if isinstance(item, BaseException):
            return FakeScript(error=item)
        return FakeScript(content=item)

    def push(self, *items: Union[FakeScript, Dict[str, Any], BaseException]) -> None:
        self._script.extend(self._coerce(item) for item in items)

    @property
    def remaining(self) -> int:
        return len(self._script)

    def complete_json(
        self,
        *,
        operation: str,
        system: str,
        user: str,
        schema: Dict[str, Any],
        schema_name: str,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> LLMResponse:
        self.calls.append(
            {
                "operation": operation,
                "system": system,
                "user": user,
                "schema_name": schema_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if self._script:
            script = self._script.pop(0)
        elif self.default_content is not None:
            script = FakeScript(content=self.default_content)
        else:
            raise AssertionError(
                f"FakeLLMClient has no scripted response for operation {operation!r}"
            )

        if script.delay_seconds:
            import time

            time.sleep(script.delay_seconds)
        if script.error is not None:
            raise script.error
        if script.raw_text is not None:
            raise ProviderMalformedResponseError("Provider returned malformed JSON.")
        if script.content is None:
            raise ProviderMalformedResponseError("Provider returned no message content.")

        self.last_usage = {
            "operation": operation,
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": script.prompt_tokens,
            "completion_tokens": script.completion_tokens,
            "total_tokens": script.prompt_tokens + script.completion_tokens,
            "attempts": 1,
            "latency_ms": script.latency_ms,
        }
        return LLMResponse(
            content=dict(script.content),
            raw_text="{}",
            provider=self.provider,
            model=self.model,
            prompt_tokens=script.prompt_tokens,
            completion_tokens=script.completion_tokens,
            total_tokens=script.prompt_tokens + script.completion_tokens,
            attempts=1,
            latency_ms=script.latency_ms,
        )


def quota_after(seconds: int = 30) -> FakeScript:
    return FakeScript(
        error=QuotaExhaustedError(
            "The AI service is busy or the daily quota was reached. Try again later.",
            retry_after=seconds,
        )
    )


def timeout() -> FakeScript:
    return FakeScript(error=ProviderTimeoutError("timed out"))


def outage() -> FakeScript:
    return FakeScript(error=ProviderOutageError("provider outage"))


def network() -> FakeScript:
    return FakeScript(error=ProviderNetworkError("network down"))


def malformed() -> FakeScript:
    return FakeScript(raw_text="{not json")
