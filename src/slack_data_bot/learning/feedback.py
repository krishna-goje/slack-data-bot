"""Feedback collection - captures human corrections to improve future responses."""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone

from slack_data_bot.config import LearningConfig
from slack_data_bot.monitor.dedup import SlackMessage

logger = logging.getLogger(__name__)


class FeedbackCollector:
    """Captures and analyzes human feedback on bot-generated drafts."""

    def __init__(self, config: LearningConfig) -> None:
        self.config = config
        self._feedback_file = config.storage_path / "feedback.jsonl"
        config.storage_path.mkdir(parents=True, exist_ok=True)

    def record_feedback(
        self,
        message: SlackMessage,
        original_draft: str,
        action: str,
        edited_text: str | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        """Store a feedback entry capturing the human decision on a draft."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message_ts": message.ts,
            "channel_id": message.channel_id,
            "channel_name": message.channel_name,
            "user_id": message.user_id,
            "original_draft": original_draft,
            "action": action,
            "edited_text": edited_text,
            "rejection_reason": rejection_reason,
        }
        self._save_feedback(entry)

    def get_common_corrections(self, limit: int = 10) -> list[dict]:
        """Analyze feedback to find common rejection/edit patterns."""
        entries = self._load_feedback()

        # Count rejection reasons
        reason_counter: Counter[str] = Counter()
        for entry in entries:
            if entry.get("action") == "rejected" and entry.get("rejection_reason"):
                reason_counter[entry["rejection_reason"]] += 1

        # Count edit frequency by channel
        edit_channels: Counter[str] = Counter()
        for entry in entries:
            if entry.get("action") == "edited":
                channel = entry.get("channel_name", "unknown")
                edit_channels[channel] += 1

        corrections: list[dict] = []

        for reason, count in reason_counter.most_common(limit):
            corrections.append({
                "type": "rejection_reason",
                "value": reason,
                "count": count,
            })

        for channel, count in edit_channels.most_common(limit):
            corrections.append({
                "type": "frequently_edited_channel",
                "value": channel,
                "count": count,
            })

        return corrections[:limit]

    def get_feedback_for_channel(self, channel_id: str) -> list[dict]:
        """Get all feedback entries for a specific channel."""
        entries = self._load_feedback()
        return [e for e in entries if e.get("channel_id") == channel_id]

    def _save_feedback(self, entry: dict) -> None:
        """Append a feedback entry to the JSONL file."""
        try:
            with self._feedback_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            logger.exception("Failed to write feedback to %s", self._feedback_file)

    def _load_feedback(self) -> list[dict]:
        """Load all feedback entries from the JSONL file."""
        if not self._feedback_file.exists():
            return []

        entries: list[dict] = []
        try:
            with self._feedback_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning("Corrupt feedback line, skipping")
        except OSError:
            logger.exception("Failed to read feedback from %s", self._feedback_file)

        return entries
