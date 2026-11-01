"""Job state machine (pure domain, ADR R5/D7).

Vocabulary is fixed by the public API contract:
``queued`` / ``running`` / ``ready`` / ``failed``. This module owns the
decisions; the adapter only stores what it is told.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import random

QUEUED = "queued"
RUNNING = "running"
READY = "ready"  # terminal
FAILED = "failed"  # terminal

TERMINAL_STATES = frozenset({READY, FAILED})
ALL_STATES = frozenset({QUEUED, RUNNING, READY, FAILED})

# Recoverable error classes retry automatically; everything else is terminal
# as soon as it fails once (e.g. quota, invalid input).
RECOVERABLE_CLASSES = frozenset({"network_error", "provider_failure"})

# Worker-loss classification for reclaimed stale leases.
WORKER_LOST = "worker_lost"


class InvalidTransition(ValueError):
    """Raised when a transition is not allowed by the state machine."""


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATES


def validate_transition(current: str, target: str) -> str:
    if current not in ALL_STATES or target not in ALL_STATES:
        raise InvalidTransition(f"unknown state: {current} -> {target}")
    allowed = {
        (QUEUED, RUNNING),
        (RUNNING, READY),
        (RUNNING, QUEUED),  # retryable failure or stale reclaim
        (RUNNING, FAILED),
    }
    if (current, target) not in allowed:
        raise InvalidTransition(f"transition not allowed: {current} -> {target}")
    return target


@dataclass(frozen=True)
class RetryPolicy:
    """D7: max attempts (3 = 2 retries), delays per failed attempt, jitter.

    ``base_backoff_seconds`` maps attempt number -> delay:
    attempt 1 -> delays[0], attempt 2 -> delays[1], ... then terminal.
    All values are Settings-driven env overrides.
    """

    max_attempts: int = 3
    base_backoff_seconds: tuple = (30.0, 120.0)
    jitter_fraction: float = 0.2  # +/-20%

    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if not 0.0 <= self.jitter_fraction < 1.0:
            raise ValueError("jitter_fraction must be within [0, 1)")


def is_recoverable(error_class: str) -> bool:
    return error_class in RECOVERABLE_CLASSES


def decides_terminal(
    error_class: str,
    attempt: int,
    policy: Optional[RetryPolicy] = None,
) -> bool:
    """Attempts spent + error class -> terminal?

    ``attempt`` is the number of attempts CONSUMED (the one that failed).
    """
    policy = policy or RetryPolicy()
    if not is_recoverable(error_class):
        return True
    return attempt >= policy.max_attempts


def retry_delay(
    failed_attempt: int,
    policy: Optional[RetryPolicy] = None,
    rng: Optional[random.Random] = None,
) -> Optional[timedelta]:
    """Backoff with +/- jitter for the NEXT attempt; None when terminal."""
    policy = policy or RetryPolicy()
    rng = rng or random.Random()
    if decides_terminal("network_error", failed_attempt, policy):
        return None
    index = min(max(failed_attempt, 1), len(policy.base_backoff_seconds)) - 1
    base = float(policy.base_backoff_seconds[index])
    spread = base * policy.jitter_fraction
    seconds = base + rng.uniform(-spread, spread)
    return timedelta(seconds=max(1.0, seconds))


def next_state_after_failure(
    status_after_claim: str,
    error_class: str,
    attempt: int,
    policy: Optional[RetryPolicy] = None,
) -> tuple:
    """(target_state, retry_delay) after one failed attempt from `running`."""
    validate_transition(status_after_claim or RUNNING, FAILED)  # sanity only
    if decides_terminal(error_class, attempt, policy):
        return FAILED, None
    return QUEUED, retry_delay(attempt, policy)


def next_state_after_reclaim(attempt: int, policy: Optional[RetryPolicy] = None) -> tuple:
    """Stale-lease reclaim costs one attempt (owner-confirmed).

    ``attempt`` is the attempts consumed so far; a job that loses its worker
    repeatedly reaches max_attempts and terminates as ``failed`` instead of
    looping forever.
    """
    policy = policy or RetryPolicy()
    new_attempt = attempt + 1
    if new_attempt >= policy.max_attempts:
        return FAILED, None
    return QUEUED, None
