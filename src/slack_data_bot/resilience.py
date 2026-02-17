"""Resilience utilities: retry, rate limiting, and input sanitization."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Sequence, Type

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def _log_retry(retry_state: RetryCallState) -> None:
    """Log each retry attempt with useful context."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "Retry attempt %d/%s for %s: %s",
        retry_state.attempt_number,
        retry_state.retry_object.stop.max_attempt_number  # type: ignore[union-attr]
        if hasattr(retry_state.retry_object.stop, "max_attempt_number")
        else "?",
        getattr(retry_state.fn, "__qualname__", "unknown"),
        exc,
    )


def with_retry(
    max_attempts: int = 3,
    min_wait: int = 1,
    max_wait: int = 30,
    retryable_exceptions: tuple[Type[BaseException], ...] = (Exception,),
) -> Any:
    """Decorator factory for retrying functions with exponential backoff + jitter.

    Usage::

        @with_retry(max_attempts=5, retryable_exceptions=(ConnectionError, TimeoutError))
        def call_external_service():
            ...
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(retryable_exceptions),
        before_sleep=_log_retry,
    )


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class RateLimiter:
    """Token-bucket rate limiter.

    Limits calls to *max_calls* within a sliding window of *period_seconds*.
    Thread-safe.  Can be used as a context manager::

        limiter = RateLimiter(max_calls=10, period_seconds=60)
        with limiter:
            do_something()
    """

    def __init__(self, max_calls: int, period_seconds: float) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be positive")
        self._max = max_calls
        self._period = period_seconds
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                # Prune calls outside the sliding window.
                cutoff = now - self._period
                self._calls = [t for t in self._calls if t > cutoff]

                if len(self._calls) < self._max:
                    self._calls.append(now)
                    return

                # Calculate how long to wait for the oldest call to expire.
                sleep_for = self._calls[0] - cutoff

            # Sleep outside the lock so other threads can proceed.
            time.sleep(max(sleep_for, 0.01))

    def __enter__(self) -> RateLimiter:
        self.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Input sanitization
# ---------------------------------------------------------------------------

# Control characters except newline (\n) and tab (\t).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# ANSI escape sequences (e.g. colour codes).
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def sanitize_user_input(text: str, max_length: int = 10_000) -> str:
    """Sanitize user input to prevent prompt injection and control-char abuse.

    1. Truncate to *max_length* characters.
    2. Strip ANSI escape sequences (must happen before control-char removal
       so that the full ``ESC[...m`` sequence is matched, not just the ESC byte).
    3. Strip remaining control characters (except newline / tab).
    """
    text = text[:max_length]
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = _CONTROL_CHARS_RE.sub("", text)
    return text


def wrap_user_input(text: str) -> str:
    """Wrap user input in delimiters to prevent prompt injection.

    Returns the sanitized text enclosed in ``<user_input>`` tags so that
    downstream LLM prompts treat it as untrusted content.
    """
    sanitized = sanitize_user_input(text)
    return f"<user_input>\n{sanitized}\n</user_input>"


# Patterns that look like secrets/tokens.
_SECRET_PATTERNS: Sequence[tuple[str, str]] = (
    (r"xox[bpa]-[A-Za-z0-9\-]+", "xox*-[REDACTED]"),
    (r"xapp-[A-Za-z0-9\-]+", "xapp-[REDACTED]"),
    (r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer [REDACTED]"),
    (r"sk-[A-Za-z0-9]{20,}", "sk-[REDACTED]"),
    (r"ghp_[A-Za-z0-9]{36,}", "ghp_[REDACTED]"),
)


def redact_secrets(text: str) -> str:
    """Redact token-like strings from *text* for safe logging.

    Recognised patterns include Slack tokens (``xoxb-``, ``xapp-``),
    Bearer tokens, OpenAI keys (``sk-``), and GitHub PATs (``ghp_``).
    """
    for pattern, replacement in _SECRET_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text
