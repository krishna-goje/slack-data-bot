"""Tests for the investigation engine: Claude Code CLI, investigator, quality."""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from slack_data_bot.config import EngineConfig, QualityConfig
from slack_data_bot.engine.claude_code import ClaudeCodeEngine, ClaudeCodeError
from slack_data_bot.engine.quality import QualityReviewer
from slack_data_bot.monitor.dedup import SlackMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_config(**overrides) -> EngineConfig:
    defaults = dict(
        backend="claude_code",
        claude_code_path="/usr/local/bin/claude",
        investigation_timeout=60,
        review_timeout=30,
        max_concurrent=2,
    )
    defaults.update(overrides)
    return EngineConfig(**defaults)


def _quality_config(**overrides) -> QualityConfig:
    defaults = dict(
        max_rounds=3,
        min_pass_criteria=5,
        criteria=[
            "data_accuracy", "completeness", "root_cause",
            "time_period", "tone", "actionable", "caveats",
        ],
    )
    defaults.update(overrides)
    return QualityConfig(**defaults)


def _sample_message() -> SlackMessage:
    return SlackMessage(
        ts="1770335814.365139",
        channel_id="C001",
        channel_name="data-questions",
        user_id="U_ALICE",
        user_name="alice",
        text="Why is the dashboard showing wrong numbers?",
        timestamp=datetime(2026, 2, 12, 10, 0, 0, tzinfo=timezone.utc),
        permalink="https://test.slack.com/archives/C001/p1770335814365139",
        priority=50,
    )


# ===================================================================
# ClaudeCodeEngine tests
# ===================================================================


class TestClaudeCodeEngine:
    @patch("subprocess.run")
    def test_claude_code_investigate(self, mock_run):
        """Successful investigation returns parsed stdout."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="The dashboard dropped 10% due to a filter change.\n",
            stderr="",
        )
        engine = ClaudeCodeEngine(_engine_config())
        result = engine.investigate("Why did the dashboard drop?")
        assert "dashboard" in result.lower()
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "--print" in call_args[0][0]
        assert "-p" in call_args[0][0]

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=60))
    def test_claude_code_timeout(self, mock_run):
        engine = ClaudeCodeEngine(_engine_config())
        with pytest.raises(ClaudeCodeError, match="timed out"):
            engine.investigate("Question?")

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_claude_code_not_found(self, mock_run):
        engine = ClaudeCodeEngine(_engine_config())
        with pytest.raises(ClaudeCodeError, match="not found"):
            engine.investigate("Question?")

    @patch("subprocess.run")
    def test_claude_code_error_exit(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Fatal error",
        )
        engine = ClaudeCodeEngine(_engine_config())
        with pytest.raises(ClaudeCodeError, match="exited with code 1"):
            engine.investigate("Question?")

    @patch("subprocess.run")
    def test_claude_code_semaphore(self, mock_run):
        """Semaphore limits concurrent executions to max_concurrent."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="result\n", stderr="",
        )
        config = _engine_config(max_concurrent=1)
        engine = ClaudeCodeEngine(config)

        # The semaphore initial value should match max_concurrent
        assert isinstance(engine._semaphore, threading.Semaphore)

        # After one call, semaphore should be released back
        engine.investigate("Q1?")
        # Acquire and immediately release to prove it's available
        acquired = engine._semaphore.acquire(blocking=False)
        assert acquired is True
        engine._semaphore.release()


# ===================================================================
# InvestigationEngine tests
# ===================================================================


class TestInvestigationPipeline:
    def test_investigation_pipeline(self, sample_config):
        """Full pipeline: investigate -> quality review -> result."""
        from slack_data_bot.engine.investigator import InvestigationEngine, InvestigationResult

        engine = InvestigationEngine(sample_config)

        # Mock the internal claude engine
        engine.claude = MagicMock()
        engine.claude.investigate.return_value = "The metric dropped due to a filter bug."
        engine.claude.review_draft.return_value = (
            "data_accuracy: PASS\n"
            "completeness: PASS\n"
            "root_cause: PASS\n"
            "time_period: PASS\n"
            "tone: PASS\n"
            "actionable: PASS\n"
            "caveats: PASS\n"
            "## Feedback\nNo changes needed."
        )

        msg = _sample_message()
        result = engine.investigate(msg)

        assert isinstance(result, InvestigationResult)
        assert result.question == msg.text
        assert "filter bug" in result.draft
        assert result.approved is True
        assert result.rounds >= 1


# ===================================================================
# QualityReviewer tests
# ===================================================================


class TestQualityReviewer:
    def test_quality_review_pass_first_round(self):
        """Draft passes all criteria on the first review round."""
        config = _quality_config()
        reviewer = QualityReviewer(config)
        mock_engine = MagicMock()
        mock_engine.review_draft.return_value = (
            "data_accuracy: PASS\n"
            "completeness: PASS\n"
            "root_cause: PASS\n"
            "time_period: PASS\n"
            "tone: PASS\n"
            "actionable: PASS\n"
            "caveats: PASS\n"
            "## Feedback\nNo changes needed."
        )

        draft, result = reviewer.review_and_improve("Q?", "Good answer.", mock_engine)
        assert result.passed is True
        assert result.score >= 5
        assert result.rounds == 1
        assert draft == "Good answer."

    def test_quality_review_needs_revision(self):
        """Draft fails first review, passes after revision."""
        config = _quality_config(max_rounds=3, min_pass_criteria=5)
        reviewer = QualityReviewer(config)
        mock_engine = MagicMock()

        # First review: only 3 pass
        # Second review (of revised draft): all pass
        mock_engine.review_draft.side_effect = [
            (
                "data_accuracy: PASS\n"
                "completeness: FAIL\n"
                "root_cause: PASS\n"
                "time_period: FAIL\n"
                "tone: PASS\n"
                "actionable: FAIL\n"
                "caveats: FAIL\n"
                "## Feedback\nAdd time context and fix gaps."
            ),
            (
                "data_accuracy: PASS\n"
                "completeness: PASS\n"
                "root_cause: PASS\n"
                "time_period: PASS\n"
                "tone: PASS\n"
                "actionable: PASS\n"
                "caveats: PASS\n"
                "## Feedback\nNo changes needed."
            ),
        ]
        mock_engine.investigate.return_value = "Improved answer with dates and root cause."

        draft, result = reviewer.review_and_improve("Q?", "Weak answer.", mock_engine)
        assert result.passed is True
        assert result.rounds == 2

    def test_quality_review_max_rounds(self):
        """Draft never passes; returns best version after max_rounds."""
        config = _quality_config(max_rounds=2, min_pass_criteria=5)
        reviewer = QualityReviewer(config)
        mock_engine = MagicMock()

        mock_engine.review_draft.side_effect = [
            "data_accuracy: PASS\ncompleteness: FAIL\n## Feedback\nNeeds work.",
            "data_accuracy: PASS\ncompleteness: PASS\nroot_cause: FAIL\n## Feedback\nStill bad.",
        ]
        mock_engine.investigate.return_value = "Revised but still incomplete."

        draft, result = reviewer.review_and_improve("Q?", "Bad answer.", mock_engine)
        assert result.passed is False
        assert result.rounds <= 2

    def test_quality_parse_review(self):
        """_parse_review correctly parses PASS/FAIL lines and feedback."""
        config = _quality_config()
        reviewer = QualityReviewer(config)
        review_text = (
            "data_accuracy: PASS\n"
            "completeness: FAIL\n"
            "root_cause: PASS\n"
            "## Feedback\n"
            "Add more detail about the root cause."
        )
        result = reviewer._parse_review(review_text)
        assert result.criteria_results.get("data_accuracy") is True
        assert result.criteria_results.get("completeness") is False
        assert result.criteria_results.get("root_cause") is True
        assert result.score == 2
        assert "root cause" in result.feedback
