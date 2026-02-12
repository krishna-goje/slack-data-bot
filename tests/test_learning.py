"""Tests for the learning subsystem: tracker, feedback, optimizer."""

from __future__ import annotations

from datetime import datetime, timezone

from slack_data_bot.config import LearningConfig
from slack_data_bot.learning.feedback import FeedbackCollector
from slack_data_bot.learning.optimizer import Optimizer
from slack_data_bot.learning.tracker import UsageTracker
from slack_data_bot.monitor.dedup import SlackMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _learning_config(tmp_path) -> LearningConfig:
    return LearningConfig(
        enabled=True,
        storage_dir=str(tmp_path / "learning"),
        feedback_tracking=True,
    )


def _msg(**overrides) -> SlackMessage:
    defaults = dict(
        ts="1770335814.365139",
        channel_id="C001",
        channel_name="data-questions",
        user_id="U_ALICE",
        user_name="alice",
        text="Why did the metric drop?",
        timestamp=datetime(2026, 2, 12, 10, 0, 0, tzinfo=timezone.utc),
        permalink="",
        priority=50,
    )
    defaults.update(overrides)
    return SlackMessage(**defaults)


# ===================================================================
# UsageTracker
# ===================================================================


class TestUsageTracker:
    def test_tracker_record_question(self, tmp_path):
        config = _learning_config(tmp_path)
        tracker = UsageTracker(config)
        msg = _msg()
        tracker.record_question(msg, "domain_keyword")
        # Verify event was written by checking stats
        stats = tracker.get_stats(days=1)
        assert stats["total_questions"] == 1

    def test_tracker_record_investigation(self, tmp_path):
        config = _learning_config(tmp_path)
        tracker = UsageTracker(config)
        msg = _msg()
        tracker.record_investigation(msg, duration_seconds=45.5, success=True)
        stats = tracker.get_stats(days=1)
        assert stats["total_investigations"] == 1
        assert stats["avg_investigation_time"] == 45.5

    def test_tracker_get_stats(self, tmp_path):
        config = _learning_config(tmp_path)
        tracker = UsageTracker(config)

        # Record a mix of events
        msg = _msg()
        tracker.record_question(msg, "direct_mention")
        tracker.record_investigation(msg, duration_seconds=30.0, success=True)
        tracker.record_approval(msg, action="approved", response_time_seconds=120.0)

        stats = tracker.get_stats(days=1)
        assert stats["total_questions"] == 1
        assert stats["total_investigations"] == 1
        assert stats["total_approved"] == 1
        assert stats["total_rejected"] == 0
        assert stats["avg_investigation_time"] == 30.0
        assert stats["avg_response_time"] == 120.0
        assert stats["period_days"] == 1


# ===================================================================
# FeedbackCollector
# ===================================================================


class TestFeedbackCollector:
    def test_feedback_record(self, tmp_path):
        config = _learning_config(tmp_path)
        collector = FeedbackCollector(config)
        msg = _msg()
        collector.record_feedback(
            msg,
            original_draft="Bad draft.",
            action="rejected",
            rejection_reason="Inaccurate numbers",
        )
        entries = collector._load_feedback()
        assert len(entries) == 1
        assert entries[0]["action"] == "rejected"
        assert entries[0]["rejection_reason"] == "Inaccurate numbers"

    def test_feedback_common_corrections(self, tmp_path):
        config = _learning_config(tmp_path)
        collector = FeedbackCollector(config)
        msg = _msg()

        # Record multiple rejections with same reason
        for _ in range(3):
            collector.record_feedback(
                msg,
                original_draft="Bad draft.",
                action="rejected",
                rejection_reason="Wrong time period",
            )
        collector.record_feedback(
            msg,
            original_draft="Another draft.",
            action="edited",
        )

        corrections = collector.get_common_corrections(limit=10)
        assert len(corrections) >= 1
        rejection_corrections = [c for c in corrections if c["type"] == "rejection_reason"]
        assert rejection_corrections[0]["value"] == "Wrong time period"
        assert rejection_corrections[0]["count"] == 3


# ===================================================================
# Optimizer
# ===================================================================


class TestOptimizer:
    def test_optimizer_high_rejection_rate(self, tmp_path):
        config = _learning_config(tmp_path)
        tracker = UsageTracker(config)
        feedback = FeedbackCollector(config)
        msg = _msg()

        # Create stats with high rejection rate: 8 rejected, 2 approved
        for _ in range(2):
            tracker.record_approval(msg, action="approved", response_time_seconds=60.0)
        for _ in range(8):
            tracker.record_approval(msg, action="rejected", response_time_seconds=30.0)

        optimizer = Optimizer(config, tracker=tracker, feedback=feedback)
        recs = optimizer.analyze()

        high_rej = [r for r in recs if r.category == "high_rejection_rate"]
        assert len(high_rej) == 1
        assert high_rej[0].priority == "high"

    def test_optimizer_slow_investigations(self, tmp_path):
        config = _learning_config(tmp_path)
        tracker = UsageTracker(config)
        feedback = FeedbackCollector(config)
        msg = _msg()

        # Create slow investigation events
        for _ in range(6):
            tracker.record_investigation(msg, duration_seconds=200.0, success=True)

        optimizer = Optimizer(config, tracker=tracker, feedback=feedback)
        recs = optimizer.analyze()

        slow = [r for r in recs if r.category == "slow_investigations"]
        assert len(slow) == 1
        assert slow[0].priority == "medium"

    def test_optimizer_generate_report(self, tmp_path):
        config = _learning_config(tmp_path)
        tracker = UsageTracker(config)
        feedback = FeedbackCollector(config)
        msg = _msg()

        tracker.record_question(msg, "domain_keyword")
        tracker.record_investigation(msg, duration_seconds=50.0, success=True)

        optimizer = Optimizer(config, tracker=tracker, feedback=feedback)
        report = optimizer.generate_report()
        assert "Bot Performance Report" in report
        assert "Questions detected:" in report
        assert "1" in report  # at least 1 question
