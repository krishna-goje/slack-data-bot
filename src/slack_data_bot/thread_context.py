"""In-memory thread context tracking for the Slack agent.

Tracks which channel/conversation each user was viewing when they
opened the DataKrait assistant panel, so the bot can tailor responses
(e.g. "in #ask-data-team, contracts dropped" vs generic).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ChannelContext:
    """Context about the channel a user was viewing when they messaged DataKrait."""

    channel_id: str
    channel_name: str = ""
    title: str = ""


class ThreadContextStore:
    """Simple in-memory store mapping user_id → their last-known channel context.

    Thread-safe for asyncio (single-threaded event loop).
    Not persisted across restarts — context is ephemeral.
    """

    def __init__(self) -> None:
        self._contexts: dict[str, ChannelContext] = {}

    def set(self, user_id: str, context: ChannelContext) -> None:
        """Store or update the channel context for a user."""
        self._contexts[user_id] = context

    def get(self, user_id: str) -> ChannelContext | None:
        """Get the stored channel context for a user, or None."""
        return self._contexts.get(user_id)

    def remove(self, user_id: str) -> None:
        """Remove stored context for a user."""
        self._contexts.pop(user_id, None)

    def to_dict(self, user_id: str) -> dict[str, Any]:
        """Return context as a plain dict for passing to investigation functions."""
        ctx = self.get(user_id)
        if ctx is None:
            return {}
        return {
            "channel_id": ctx.channel_id,
            "channel_name": ctx.channel_name,
            "title": ctx.title,
        }
