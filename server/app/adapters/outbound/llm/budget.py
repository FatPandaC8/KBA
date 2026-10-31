"""Token/request budgeting against Groq's free TPM/TPD/RPM/RPD limits.

Limits are account-scoped, so this guard is intentionally conservative: it
uses the provider's reported usage and refuses a call before sending it when
the request could cross a limit. A refusal is explicit, never a fallback.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from server.app.application.ports import LLMUsageRepositoryPort
from server.app.domain.errors import QuotaExhaustedError


def estimate_tokens(text: str) -> int:
    """Cheap, deliberately pessimistic estimate (~4 chars/token)."""
    return max(1, (len(text or "") + 3) // 4)


class TokenBudget:
    def __init__(
        self,
        usage_repo: LLMUsageRepositoryPort,
        *,
        provider: str,
        model: str,
        rpm: int,
        rpd: int,
        tpm: int,
        tpd: int,
        user_id: str = "",
    ):
        self.usage_repo = usage_repo
        self.provider = provider
        self.model = model
        self.rpm = max(1, rpm)
        self.rpd = max(1, rpd)
        self.tpm = max(1, tpm)
        self.tpd = max(1, tpd)
        self.user_id = user_id

    def _minute_usage(self, user_id: Optional[str] = None) -> Dict[str, int]:
        since = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        return self.usage_repo.usage_since(since, user_id=user_id)

    def _day_usage(self, user_id: Optional[str] = None) -> Dict[str, int]:
        now = datetime.now(timezone.utc)
        since = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        return self.usage_repo.usage_since(since, user_id=user_id)

    def check(self, estimated_tokens: int, user_id: Optional[str] = None) -> None:
        estimated = max(1, int(estimated_tokens))
        minute = self._minute_usage(user_id)
        day = self._day_usage(user_id)

        if minute["calls"] + 1 > self.rpm:
            raise QuotaExhaustedError(
                "The AI service is busy (requests-per-minute limit). Try again in a minute.",
                retry_after=60,
            )
        if day["calls"] + 1 > self.rpd:
            raise QuotaExhaustedError(
                "The AI provider's daily request quota has been reached. Try again tomorrow.",
                retry_after=3600,
            )
        if minute["total_tokens"] + estimated > self.tpm:
            raise QuotaExhaustedError(
                "The AI service is busy (tokens-per-minute limit). Try again in under a minute.",
                retry_after=60,
            )
        if day["total_tokens"] + estimated > self.tpd:
            raise QuotaExhaustedError(
                "The AI provider's daily token quota has been reached. Try again tomorrow.",
                retry_after=3600,
            )

    def record(
        self,
        *,
        operation: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        status: str = "success",
        user_id: Optional[str] = None,
    ) -> None:
        self.usage_repo.record(
            user_id=user_id if user_id is not None else self.user_id,
            provider=self.provider,
            model=self.model,
            operation=operation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            status=status,
        )

    def snapshot(self, user_id: Optional[str] = None) -> Dict[str, object]:
        minute = self._minute_usage(user_id)
        day = self._day_usage(user_id)
        return {
            "minute_calls": minute["calls"],
            "minute_tokens": minute["total_tokens"],
            "day_calls": day["calls"],
            "day_tokens": day["total_tokens"],
            "limits": {"rpm": self.rpm, "rpd": self.rpd, "tpm": self.tpm, "tpd": self.tpd},
        }
