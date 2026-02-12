"""Usage tracking - records bot activity for analysis and improvement."""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from slack_data_bot.config import LearningConfig
from slack_data_bot.monitor.dedup import SlackMessage

logger = logging.getLogger(__name__)


class UsageTracker:
    """Tracks bot usage patterns for analysis and self-improvement."""

    def __init__(self, config: LearningConfig) -> None:
        self.config = config
        self._events_dir = config.storage_path / "events"
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Create storage directories if they don't exist."""
        self._events_dir.mkdir(parents=True, exist_ok=True)

    def record_question(self, message: SlackMessage, classification: str) -> None:
        """Log a detected question with its classification type."""
        self._log_event("question", {
            "message_ts": message.ts,
            "channel_id": message.channel_id,
            "channel_name": message.channel_name,
            "user_id": message.user_id,
            "user_name": message.user_name,
            "classification": classification,
            "text_length": len(message.text),
            "has_thread": message.thread_ts is not None,
            "priority": message.priority,
        })

    def record_investigation(
        self,
        message: SlackMessage,
        duration_seconds: float,
        success: bool,
    ) -> None:
        """Log an investigation attempt with timing and outcome."""
        self._log_event("investigation", {
            "message_ts": message.ts,
            "channel_id": message.channel_id,
            "channel_name": message.channel_name,
            "duration_seconds": round(duration_seconds, 2),
            "success": success,
        })

    def record_approval(
        self,
        message: SlackMessage,
        action: str,
        response_time_seconds: float,
    ) -> None:
        """Log a human approval/rejection decision."""
        self._log_event("approval", {
            "message_ts": message.ts,
            "channel_id": message.channel_id,
            "channel_name": message.channel_name,
            "action": action,
            "response_time_seconds": round(response_time_seconds, 2),
        })

    def get_stats(self, days: int = 30) -> dict:
        """Return aggregate statistics over the last N days."""
        events = self._read_events(days)

        questions = [e for e in events if e.get("type") == "question"]
        investigations = [e for e in events if e.get("type") == "investigation"]
        approvals = [e for e in events if e.get("type") == "approval"]

        approved = [a for a in approvals if a.get("data", {}).get("action") == "approved"]
        rejected = [a for a in approvals if a.get("data", {}).get("action") == "rejected"]

        inv_times = [
            e["data"]["duration_seconds"]
            for e in investigations
            if "duration_seconds" in e.get("data", {})
        ]
        resp_times = [
            e["data"]["response_time_seconds"]
            for e in approvals
            if "response_time_seconds" in e.get("data", {})
        ]

        channel_counter = Counter(
            e.get("data", {}).get("channel_name", "unknown") for e in questions
        )
        type_counter = Counter(
            e.get("data", {}).get("classification", "unknown") for e in questions
        )

        return {
            "period_days": days,
            "total_questions": len(questions),
            "total_investigations": len(investigations),
            "total_approved": len(approved),
            "total_rejected": len(rejected),
            "avg_investigation_time": (
                round(sum(inv_times) / len(inv_times), 2) if inv_times else 0.0
            ),
            "avg_response_time": (
                round(sum(resp_times) / len(resp_times), 2) if resp_times else 0.0
            ),
            "top_channels": channel_counter.most_common(10),
            "top_question_types": type_counter.most_common(10),
        }

    def _log_event(self, event_type: str, data: dict) -> None:
        """Append an event to today's JSONL file."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        filepath = self._events_dir / f"{date_str}.jsonl"

        entry = {
            "type": event_type,
            "timestamp": now.isoformat(),
            "data": data,
        }

        try:
            with filepath.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            logger.exception("Failed to write event to %s", filepath)

    def _read_events(self, days: int) -> list[dict]:
        """Read events from the last N days of JSONL files."""
        events: list[dict] = []
        today = datetime.now(timezone.utc).date()

        for day_offset in range(days):
            date = today - timedelta(days=day_offset)
            filepath = self._events_dir / f"{date.isoformat()}.jsonl"

            if not filepath.exists():
                continue

            try:
                with filepath.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                events.append(json.loads(line))
                            except json.JSONDecodeError:
                                logger.warning("Corrupt line in %s, skipping", filepath)
            except OSError:
                logger.exception("Failed to read events from %s", filepath)

        return events
