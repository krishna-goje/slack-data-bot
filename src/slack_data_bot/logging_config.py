"""Structured logging configuration with JSON output and correlation IDs."""

from __future__ import annotations

import json
import logging
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

# Thread-local storage for correlation IDs.
_local = threading.local()


# ---------------------------------------------------------------------------
# Correlation ID helpers
# ---------------------------------------------------------------------------


def get_correlation_id() -> str:
    """Return the current thread's correlation ID, or ``'-'`` if unset."""
    return getattr(_local, "correlation_id", "-")


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID for the current thread."""
    _local.correlation_id = cid


def new_correlation_id() -> str:
    """Generate a new UUID-based correlation ID and set it on the current thread.

    Returns the generated ID so callers can propagate it to child threads.
    """
    cid = uuid.uuid4().hex[:12]
    set_correlation_id(cid)
    return cid


# ---------------------------------------------------------------------------
# Structured JSON formatter
# ---------------------------------------------------------------------------


class StructuredFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Output fields:

    * ``timestamp`` -- ISO-8601 UTC
    * ``level`` -- e.g. ``"INFO"``
    * ``logger`` -- logger name
    * ``message`` -- formatted message
    * ``correlation_id`` -- per-thread correlation ID
    * any extra keys attached to the record
    """

    # Keys that belong to the standard LogRecord and should not be forwarded.
    _BUILTIN_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }

        # Merge extra fields passed via `logger.info("msg", extra={...})`.
        for key, value in record.__dict__.items():
            if key not in self._BUILTIN_ATTRS and key not in payload:
                payload[key] = value

        return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_logging(verbose: bool = False, json_output: bool = True) -> None:
    """Configure the root logger for the application.

    Parameters:
        verbose: When ``True``, set the root level to ``DEBUG`` instead of ``INFO``.
        json_output: When ``True`` (default), use :class:`StructuredFormatter`.
                     Otherwise fall back to a human-readable format.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Remove any pre-existing handlers to avoid duplicate output.
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)

    if json_output:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(_HumanFormatter())

    root.addHandler(handler)


class _HumanFormatter(logging.Formatter):
    """Human-readable formatter that injects the correlation ID.

    Works on Python 3.10+ without relying on ``defaults`` (added in 3.12).
    """

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s [%(levelname)-5s] %(name)s (%(correlation_id)s) %(message)s"
        )

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        if not hasattr(record, "correlation_id"):
            record.correlation_id = get_correlation_id()  # type: ignore[attr-defined]
        return super().format(record)
