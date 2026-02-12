"""Tests for the main bot orchestrator."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from slack_data_bot.monitor.dedup import SlackMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(**overrides) -> SlackMessage:
    defaults = dict(
        ts="1770335814.365139",
        channel_id="C001",
        channel_name="data-questions",
        user_id="U_ALICE",
        user_name="alice",
        text="Why is the dashboard wrong?",
        timestamp=datetime(2026, 2, 12, 10, 0, 0, tzinfo=timezone.utc),
        permalink="https://test.slack.com/archives/C001/p1770335814365139",
        priority=50,
    )
    defaults.update(overrides)
    return SlackMessage(**defaults)


# ===================================================================
# Bot init and lifecycle
# ===================================================================


class TestSlackDataBot:
    @patch("slack_data_bot.bot.SlackDataBot._create_slack_client", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_monitor", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_state", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_tracker", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._setup_bolt_app")
    def test_bot_init(
        self, mock_bolt, mock_tracker, mock_state, mock_monitor, mock_client, sample_config
    ):
        """Bot initialises all subsystems without error."""
        from slack_data_bot.bot import SlackDataBot

        bot = SlackDataBot(sample_config)
        assert bot.config is sample_config
        assert bot.engine is not None
        assert bot.notifier is not None
        assert bot.approval is not None

    @patch("slack_data_bot.bot.SlackDataBot._create_slack_client", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_monitor", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_state", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_tracker", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._setup_bolt_app")
    def test_bot_dry_run(
        self, mock_bolt, mock_tracker, mock_state, mock_monitor, mock_client, sample_config
    ):
        """Dry run should complete without starting any loops."""
        from slack_data_bot.bot import SlackDataBot

        bot = SlackDataBot(sample_config)
        # run_once delegates to poll_cycle; with no monitor it returns 0
        count = bot.run_once()
        assert count == 0

    @patch("slack_data_bot.bot.SlackDataBot._create_slack_client", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_state", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_tracker", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._setup_bolt_app")
    def test_bot_poll_cycle(self, mock_bolt, mock_tracker, mock_state, mock_client, sample_config):
        """Poll cycle finds questions, investigates, and notifies."""
        from slack_data_bot.bot import SlackDataBot

        # Create bot with mocked monitor
        mock_monitor = MagicMock()
        mock_monitor.find_unanswered.return_value = [_msg()]

        with patch("slack_data_bot.bot.SlackDataBot._create_monitor", return_value=mock_monitor):
            bot = SlackDataBot(sample_config)
            bot._running = True

        # Mock the investigation engine
        mock_result = MagicMock()
        mock_result.draft = "The dashboard dropped because of a filter bug."
        mock_result.quality_score = 6
        mock_result.quality_total = 7
        bot.engine = MagicMock()
        bot.engine.investigate.return_value = mock_result

        # Mock notifier and approval
        bot.notifier = MagicMock()
        bot.approval = MagicMock()

        count = bot.poll_cycle()
        assert count == 1
        bot.engine.investigate.assert_called_once()
        bot.notifier.notify_human.assert_called_once()

    @patch("slack_data_bot.bot.SlackDataBot._create_slack_client", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_monitor", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_state", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_tracker", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._setup_bolt_app")
    def test_bot_on_approval(
        self, mock_bolt, mock_tracker, mock_state, mock_monitor, mock_client, sample_config
    ):
        """Approval posts the draft and records the answer."""
        from slack_data_bot.bot import SlackDataBot

        bot = SlackDataBot(sample_config)
        bot.approval = MagicMock()
        bot.state = None
        bot.tracker = None

        msg = _msg()
        bot._on_approval(msg, "Approved draft.")
        bot.approval.post_approved_response.assert_called_once_with(msg, "Approved draft.")

    @patch("slack_data_bot.bot.SlackDataBot._create_slack_client", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_monitor", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_state", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._create_tracker", return_value=None)
    @patch("slack_data_bot.bot.SlackDataBot._setup_bolt_app")
    def test_bot_on_rejection(
        self, mock_bolt, mock_tracker, mock_state, mock_monitor, mock_client, sample_config
    ):
        """Rejection records feedback for learning."""
        from slack_data_bot.bot import SlackDataBot

        bot = SlackDataBot(sample_config)
        bot.tracker = MagicMock()
        msg = _msg()
        bot._on_rejection(msg, "Bad draft.", "Inaccurate")
        bot.tracker.record_rejection.assert_called_once()


# ===================================================================
# CLI main()
# ===================================================================


class TestMainCli:
    def test_main_cli_args(self, tmp_config_file):
        """--dry-run exits with code 0 after validating config."""
        from slack_data_bot.bot import main

        with patch.object(sys, "argv", ["bot", "--config", str(tmp_config_file), "--dry-run"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
