"""Bot state management - persists answered questions, queue, and configuration state."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone

from slack_data_bot.config import CacheConfig
from slack_data_bot.monitor.dedup import SlackMessage

logger = logging.getLogger(__name__)

DEFAULT_STATE: dict = {
    "answered": {},
    "in_progress": {},
    "queue": [],
    "last_poll": None,
    "stats": {"total_questions": 0, "total_answered": 0},
}


class BotState:
    """Persists bot state including answered questions, queue, and stats."""

    def __init__(self, config: CacheConfig) -> None:
        self.config = config
        self._state_file = config.cache_path / "state.json"
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        """Create cache directory if it doesn't exist."""
        self.config.cache_path.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        """Load state from disk. Returns default state if missing or corrupt."""
        if not self._state_file.exists():
            return _deep_copy_default()

        try:
            with self._state_file.open("r", encoding="utf-8") as f:
                state = json.load(f)
            # Ensure all expected keys are present
            for key, default_value in DEFAULT_STATE.items():
                if isinstance(default_value, (dict, list)):
                    state.setdefault(key, type(default_value)())
                else:
                    state.setdefault(key, default_value)
            return state
        except (json.JSONDecodeError, OSError):
            logger.exception("Corrupt state file at %s, returning defaults", self._state_file)
            return _deep_copy_default()

    def save(self, state: dict) -> None:
        """Atomically save state to disk (write tmp then rename)."""
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=self.config.cache_path,
                prefix=".state_",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2, default=str)
                os.replace(tmp_path, self._state_file)
            except BaseException:
                # Clean up temp file on any failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError:
            logger.exception("Failed to save state to %s", self._state_file)

    def mark_answered(self, message_ts: str, channel_id: str, summary: str) -> None:
        """Add a message to the answered cache."""
        state = self.load()
        key = f"{channel_id}:{message_ts}"
        state["answered"][key] = {
            "message_ts": message_ts,
            "channel_id": channel_id,
            "summary": summary,
            "answered_at": datetime.now(timezone.utc).isoformat(),
        }
        state["stats"]["total_answered"] = state["stats"].get("total_answered", 0) + 1
        # Remove from in_progress if present
        state["in_progress"].pop(key, None)
        self.save(state)

    def is_answered(self, message_ts: str, channel_id: str) -> bool:
        """Check whether a message has already been answered."""
        state = self.load()
        key = f"{channel_id}:{message_ts}"
        return key in state.get("answered", {})

    def get_answered_cache(self) -> dict:
        """Return all answered entries."""
        state = self.load()
        return state.get("answered", {})

    def prune_old_entries(self) -> None:
        """Remove answered entries older than the configured TTL."""
        state = self.load()
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.answer_ttl_days)
        cutoff_iso = cutoff.isoformat()

        answered = state.get("answered", {})
        pruned = {
            key: entry
            for key, entry in answered.items()
            if entry.get("answered_at", "") >= cutoff_iso
        }

        removed = len(answered) - len(pruned)
        if removed > 0:
            state["answered"] = pruned
            self.save(state)
            logger.info("Pruned %d expired entries from answered cache", removed)

    def get_queue(self) -> list[dict]:
        """Return the pending investigation queue."""
        state = self.load()
        return state.get("queue", [])

    def add_to_queue(self, message: SlackMessage) -> None:
        """Add a message to the investigation queue."""
        state = self.load()
        entry = {
            "message_ts": message.ts,
            "channel_id": message.channel_id,
            "channel_name": message.channel_name,
            "user_id": message.user_id,
            "user_name": message.user_name,
            "text": message.text,
            "priority": message.priority,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        state["queue"].append(entry)
        state["stats"]["total_questions"] = state["stats"].get("total_questions", 0) + 1
        self.save(state)

    def remove_from_queue(self, message_id: str) -> None:
        """Remove a message from the queue by its timestamp ID."""
        state = self.load()
        state["queue"] = [
            item for item in state.get("queue", [])
            if item.get("message_ts") != message_id
        ]
        self.save(state)


def _deep_copy_default() -> dict:
    """Return a fresh copy of the default state structure."""
    return {
        "answered": {},
        "in_progress": {},
        "queue": [],
        "last_poll": None,
        "stats": {"total_questions": 0, "total_answered": 0},
    }
