"""Password hashing, opaque session tokens and lightweight rate limiting."""

import hashlib
import re
import secrets
import threading
import time
from typing import Dict, Optional, Tuple

import bcrypt

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_BCRYPT_ROUNDS = 12


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalize_email(email)))


def validate_password(password: str, min_length: int = 10) -> Optional[str]:
    """Return an error message, or None when the password is acceptable."""
    if not isinstance(password, str) or len(password) < min_length:
        return f"Password must be at least {min_length} characters."
    if password.lower() == password or password.upper() == password:
        return "Password must mix upper and lower case characters."
    if not any(ch.isdigit() for ch in password):
        return "Password must include at least one digit."
    return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RateLimiter:
    """In-process sliding-window limiter.

    The MVP runs a single backend process. A multi-process deployment must
    move this to shared storage; that is recorded as a production note rather
    than silently claimed to be distributed.
    """

    def __init__(self) -> None:
        self._events: Dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int = 60) -> Tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = [e for e in self._events.get(key, []) if e > cutoff]
            if len(events) >= limit:
                retry_after = max(1, int(window_seconds - (now - events[0])) + 1)
                self._events[key] = events
                return False, retry_after
            events.append(now)
            self._events[key] = events
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


rate_limiter = RateLimiter()
