"""Shared data types and deduplication logic.

SlackMessage is the core data type used across all modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class SlackMessage:
    """Represents a Slack message that may need a response."""
    ts: str
    channel_id: str
    channel_name: str
    user_id: str
    user_name: str
    text: str
    timestamp: datetime
    permalink: str
    thread_ts: Optional[str] = None
    is_direct_mention: bool = False
    is_domain_question: bool = False
    is_dm: bool = False
    reply_count: int = 0
    priority: int = 0
    metadata: dict = field(default_factory=dict)

    @property
    def message_id(self) -> str:
        """Unique identifier for deduplication (thread-level)."""
        thread_key = self.thread_ts or self.ts
        return f"{self.channel_id}:{thread_key}"

    @property
    def relative_time(self) -> str:
        """Human-readable relative time (e.g., '2h ago')."""
        now = datetime.now(timezone.utc)
        ts = self.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        diff = now - ts
        if diff < timedelta(seconds=0):
            return "just now"
        if diff.days > 0:
            return f"{diff.days}d ago"
        if diff.seconds >= 3600:
            return f"{diff.seconds // 3600}h ago"
        if diff.seconds >= 60:
            return f"{diff.seconds // 60}m ago"
        return "just now"

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "ts": self.ts,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "text": self.text[:200] + "..." if len(self.text) > 200 else self.text,
            "timestamp": self.timestamp.isoformat(),
            "relative_time": self.relative_time,
            "permalink": self.permalink,
            "thread_ts": self.thread_ts,
            "is_direct_mention": self.is_direct_mention,
            "is_domain_question": self.is_domain_question,
            "is_dm": self.is_dm,
            "reply_count": self.reply_count,
            "priority": self.priority,
        }


def deduplicate_messages(messages: list[SlackMessage]) -> list[SlackMessage]:
    """Deduplicate messages by thread/message ID, keeping highest priority."""
    valid = [m for m in messages if m is not None]
    seen: dict[str, SlackMessage] = {}
    for msg in valid:
        msg_id = msg.message_id
        if msg_id not in seen or msg.priority > seen[msg_id].priority:
            seen[msg_id] = msg
    return list(seen.values())
