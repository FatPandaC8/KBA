"""Groq JSON chat client with typed errors, bounded retries and budgeting."""

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from server.app.application.dto import LLMResponse
from server.app.domain.errors import (
    ProviderError,
    ProviderMalformedResponseError,
    ProviderNetworkError,
    ProviderOutageError,
    ProviderSchemaError,
    ProviderTimeoutError,
    QuotaExhaustedError,
)

from .budget import TokenBudget, estimate_tokens

logger = logging.getLogger("echo.llm")

_MAX_ERROR_BODY = 600


def _retry_after(headers: Any, default: int = 5) -> int:
    raw = headers.get("Retry-After") if headers else None
    try:
        return max(0, int(float(raw))) if raw is not None else default
    except (TypeError, ValueError):
        return default


class GroqChatClient:
    provider = "groq"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.groq.com/openai/v1",
        timeout_seconds: int = 45,
        max_retries: int = 3,
        max_retry_wait_seconds: int = 8,
        budget: Optional[TokenBudget] = None,
        fix_temperature: float = 0.1,
    ):
        if not api_key:
            raise ProviderError("Groq is selected but GROQ_API_KEY is not configured.")
        self._api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_retries = max(1, min(3, int(max_retries)))
        self.max_retry_wait_seconds = max(0, int(max_retry_wait_seconds))
        self.budget = budget
        self.fix_temperature = fix_temperature
        self.last_usage: Dict[str, Any] = {}

    def _assert_allowed(self) -> None:
        if os.getenv("ECHO_ENV", "") == "test" and os.getenv("ECHO_ALLOW_REAL_LLM", "0") not in ("1", "true", "True"):
            raise ProviderError(
                "Refusing a real provider call from the test environment; use the fake LLM port."
            )

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Groq sits behind Cloudflare, which rejects the default
                # Python-urllib signature with HTTP 403 (error 1010) even when
                # the key is valid. Send an explicit product identifier.
                "User-Agent": "Echo/1.0 (+https://github.com/echo-notes)",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

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
        self._assert_allowed()
        prompt_chars = len(system or "") + len(user or "")
        prompt_estimate = estimate_tokens(system or "") + estimate_tokens(user or "")
        estimated_total = prompt_estimate + max(16, int(max_tokens))
        if self.budget is not None:
            self.budget.check(estimated_total)
        else:
            raise ProviderError("LLM token budget is not configured.")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            started = time.monotonic()
            try:
                body = self._post(payload)
                latency_ms = int((time.monotonic() - started) * 1000)
                raw_text = ""
                try:
                    raw_text = body["choices"][0]["message"]["content"] or ""
                except (KeyError, IndexError, TypeError):
                    raise ProviderMalformedResponseError(
                        "Provider returned no message content."
                    )
                usage = body.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or prompt_estimate)
                completion_tokens = int(
                    usage.get("completion_tokens") or estimate_tokens(raw_text)
                )
                total_tokens = int(
                    usage.get("total_tokens") or prompt_tokens + completion_tokens
                )
                finish_reason = ""
                try:
                    finish_reason = body["choices"][0].get("finish_reason") or ""
                except (KeyError, IndexError, TypeError):
                    pass
                self.last_usage = {
                    "operation": operation,
                    "provider": self.provider,
                    "model": self.model,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "attempts": attempt,
                    "latency_ms": latency_ms,
                }
                if self.budget is not None:
                    self.budget.record(
                        operation=operation,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    )
                try:
                    content = json.loads(raw_text)
                except (TypeError, ValueError):
                    raise ProviderMalformedResponseError(
                        "Provider returned malformed JSON."
                    )
                if not isinstance(content, dict):
                    raise ProviderMalformedResponseError(
                        "Provider returned JSON that is not an object."
                    )
                logger.info(
                    "llm_call operation=%s provider=%s model=%s attempts=%d "
                    "prompt_tokens=%d completion_tokens=%d total_tokens=%d latency_ms=%d",
                    operation,
                    self.provider,
                    self.model,
                    attempt,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    latency_ms,
                )
                return LLMResponse(
                    content=content,
                    raw_text=raw_text,
                    provider=self.provider,
                    model=self.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    attempts=attempt,
                    latency_ms=latency_ms,
                    finish_reason=finish_reason,
                )
            except urllib.error.HTTPError as exc:
                last_error = exc
                status = int(exc.code or 0)
                retry_after = _retry_after(exc.headers)
                detail = ""
                try:
                    detail = exc.read(_MAX_ERROR_BODY).decode("utf-8", "replace")
                except Exception:
                    detail = ""
                if status == 429:
                    if self.budget is not None:
                        self.budget.record(
                            operation=operation,
                            prompt_tokens=0,
                            completion_tokens=0,
                            total_tokens=0,
                            status="rate_limited",
                        )
                    if attempt < self.max_retries and retry_after <= self.max_retry_wait_seconds:
                        logger.warning(
                            "llm_rate_limited operation=%s attempt=%d retry_after=%d",
                            operation,
                            attempt,
                            retry_after,
                        )
                        time.sleep(max(0, retry_after))
                        continue
                    raise QuotaExhaustedError(
                        "The AI service is busy or the daily quota was reached. Try again later.",
                        retry_after=retry_after,
                    )
                if status in (400, 422):
                    # A schema/enum violation. Do not transport-retry; the
                    # caller gets one bounded repair attempt with feedback.
                    raise ProviderSchemaError(
                        "The provider rejected or could not satisfy the JSON schema."
                    )
                if status in (401, 403):
                    raise ProviderError(
                        "The AI provider rejected its credentials or permissions."
                    )
                if status >= 500:
                    if attempt < self.max_retries:
                        time.sleep(min(2 ** (attempt - 1), self.max_retry_wait_seconds))
                        continue
                    raise ProviderOutageError(
                        "The AI provider is temporarily unavailable. Try again."
                    )
                raise ProviderError(f"The AI provider returned HTTP {status}.")
            except (socket.timeout, TimeoutError):
                last_error = ProviderTimeoutError(
                    "The AI provider timed out. Try again."
                )
                if attempt < self.max_retries:
                    time.sleep(min(2 ** (attempt - 1), self.max_retry_wait_seconds))
                    continue
                raise last_error
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                last_error = ProviderNetworkError(
                    "The AI provider could not be reached. Check the server connection."
                )
                logger.warning(
                    "llm_network_error operation=%s attempt=%d reason=%s",
                    operation,
                    attempt,
                    type(reason).__name__,
                )
                if attempt < self.max_retries:
                    time.sleep(min(2 ** (attempt - 1), self.max_retry_wait_seconds))
                    continue
                raise last_error
            except ProviderError:
                raise
            except Exception:
                logger.exception("llm_unexpected_error operation=%s", operation)
                raise ProviderError("The AI provider call failed unexpectedly.")

        raise ProviderError("The AI provider call failed.") from last_error
