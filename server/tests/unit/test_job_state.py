"""Unit tests for the pure job state machine (ADR R5/D7)."""

import random
from datetime import timedelta

from server.app.domain.job_state import (
    FAILED,
    QUEUED,
    READY,
    RUNNING,
    InvalidTransition,
    RetryPolicy,
    decides_terminal,
    is_recoverable,
    next_state_after_failure,
    next_state_after_reclaim,
    retry_delay,
    validate_transition,
)


def test_transitions_allow_only_the_documented_paths():
    for from_state, to_state in [(QUEUED, RUNNING), (RUNNING, READY), (RUNNING, QUEUED), (RUNNING, FAILED)]:
        assert validate_transition(from_state, to_state) == to_state
    for bad in [(READY, QUEUED), (FAILED, RUNNING), (QUEUED, FAILED)]:
        try:
            validate_transition(*bad)
        except InvalidTransition:
            continue
        raise AssertionError(f"transition {bad} must be invalid")


def test_recoverable_errors_retry_until_the_budget_is_spent():
    assert is_recoverable("network_error") and is_recoverable("provider_failure")
    assert not is_recoverable("quota_exhausted")
    assert not is_recoverable("invalid_input")
    policy = RetryPolicy()
    assert decides_terminal("network_error", 1, policy) is False
    assert decides_terminal("network_error", 2, policy) is False
    assert decides_terminal("network_error", 3, policy) is True
    # Non-recoverable classes are terminal on the first failure.
    assert decides_terminal("quota_exhausted", 1, policy) is True
    assert decides_terminal("invalid_input", 1, policy) is True


def test_classification_table_single_home():
    """Item 2 (4a/4b): ONE table in job_state defines retryable vs terminal.
    timeout is retryable; unsupported_language and quota_exhausted terminal."""
    from server.app.domain.job_state import (
        TERMINAL_CLASSES,
        RETRYABLE_CLASSES,
    )

    assert RETRYABLE_CLASSES == {"network_error", "provider_failure", "timeout"}
    assert {"invalid_input", "unsupported_language", "quota_exhausted"} <= TERMINAL_CLASSES
    assert is_recoverable("timeout")
    assert not is_recoverable("unsupported_language")
    assert is_recoverable("network_error") and is_recoverable("provider_failure")



def test_backoff_schedule_and_jitter_bounds():
    policy = RetryPolicy(max_attempts=3,
                         base_backoff_seconds=(30.0, 120.0), jitter_fraction=0.2)
    rng = random.Random(7)
    d1 = retry_delay(1, policy, rng)
    d2 = retry_delay(2, policy, rng)
    assert 24 <= d1.total_seconds() <= 36
    assert 96 <= d2.total_seconds() <= 144
    # A consumed attempt beyond the budget has no next attempt.
    assert retry_delay(3, policy, rng) is None


def test_failure_transitions_follow_the_state_machine():
    state, delay = next_state_after_failure(
        RUNNING, "network_error", 1, RetryPolicy(max_attempts=3)
    )
    assert state == QUEUED and delay is not None
    state, delay = next_state_after_failure(
        RUNNING, "quota_exhausted", 1, RetryPolicy(max_attempts=3)
    )
    assert state == FAILED and delay is None
    state, _ = next_state_after_failure(
        RUNNING, "network_error", 3, RetryPolicy(max_attempts=3)
    )
    assert state == FAILED


def test_reclaim_stale_costs_attempts_and_cannot_loop_forever():
    policy = RetryPolicy(max_attempts=3)
    # Attempts 0 and 1: room left after incrementing.
    assert next_state_after_reclaim(0, policy)[0] == QUEUED
    assert next_state_after_reclaim(1, policy)[0] == QUEUED
    assert next_state_after_reclaim(2, policy)[0] == FAILED
    assert next_state_after_reclaim(5, policy)[0] == FAILED
