"""Tests for the delivery subsystem: notifier and approval flow."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from slack_data_bot.delivery.approval import ApprovalAction, ApprovalFlow
from slack_data_bot.delivery.notifier import Notifier
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
# Notifier
# ===================================================================


class TestNotifier:
    def test_notifier_sends_dm(self, sample_config, mock_slack_client):
        notifier = Notifier(sample_config, slack_client=mock_slack_client)
        msg = _msg()
        result = notifier.notify_human(msg, "Draft answer.", quality_score=5, quality_total=7)
        assert result is not None
        mock_slack_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_slack_client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == sample_config.slack.owner_user_id
        assert "blocks" in call_kwargs

    def test_notifier_error_notification(self, sample_config, mock_slack_client):
        notifier = Notifier(sample_config, slack_client=mock_slack_client)
        msg = _msg()
        result = notifier.notify_error(msg, "Timeout during investigation")
        assert result is not None
        mock_slack_client.chat_postMessage.assert_called_once()

    def test_notifier_no_client_returns_none(self, sample_config):
        notifier = Notifier(sample_config, slack_client=None)
        result = notifier.notify_human(_msg(), "Draft.", 3, 7)
        assert result is None


# ===================================================================
# ApprovalFlow
# ===================================================================


class TestApprovalFlow:
    def test_approval_submit(self, sample_config):
        flow = ApprovalFlow(sample_config, slack_client=None)
        msg = _msg()
        approval_id = flow.submit_for_approval(msg, "Draft answer.")
        assert isinstance(approval_id, str)
        assert len(approval_id) > 0

        # Should be retrievable by approval_id
        pending = flow.get_pending(approval_id)
        assert pending is not None
        assert pending.draft == "Draft answer."
        assert pending.message is msg

        # Should also be retrievable by message_id
        pending2 = flow.get_pending(msg.message_id)
        assert pending2 is pending

    def test_approval_handle_approve(self, sample_config):
        flow = ApprovalFlow(sample_config, slack_client=None)
        action = flow.handle_action("approve", "some_id", "U_REVIEWER")
        assert action == ApprovalAction.APPROVE

    def test_approval_handle_reject(self, sample_config):
        flow = ApprovalFlow(sample_config, slack_client=None)
        action = flow.handle_action("reject", "some_id", "U_REVIEWER")
        assert action == ApprovalAction.REJECT

    def test_approval_handle_unknown_action(self, sample_config):
        flow = ApprovalFlow(sample_config, slack_client=None)
        with pytest.raises(ValueError, match="Unknown action_id"):
            flow.handle_action("unknown", "id", "U1")

    def test_approval_post_response(self, sample_config, mock_slack_client):
        flow = ApprovalFlow(sample_config, slack_client=mock_slack_client)
        msg = _msg(thread_ts="1770335814.365139")
        result = flow.post_approved_response(msg, "Approved answer.")
        assert result is not None
        call_kwargs = mock_slack_client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == msg.channel_id
        assert call_kwargs["thread_ts"] == "1770335814.365139"
        assert call_kwargs["text"] == "Approved answer."

    def test_approval_pending_eviction(self, sample_config):
        """When pending count exceeds MAX_PENDING, oldest entries are evicted."""
        flow = ApprovalFlow(sample_config, slack_client=None)
        # Lower limit for testing
        flow.MAX_PENDING = 10

        msgs = []
        for i in range(20):
            m = _msg(ts=f"1770335{i:03d}.000001", channel_id=f"C{i:03d}")
            flow.submit_for_approval(m, f"Draft {i}")
            msgs.append(m)

        # After 20 submissions, some should have been evicted
        # The dict has both approval_id and message_id entries, so it's larger
        # than the raw count of PendingApproval objects. Eviction removes oldest quarter.
        assert len(flow._pending) < 40  # 20 submissions x 2 keys without eviction

    def test_approval_remove_pending(self, sample_config):
        flow = ApprovalFlow(sample_config, slack_client=None)
        msg = _msg()
        aid = flow.submit_for_approval(msg, "Draft.")
        removed = flow.remove_pending(aid)
        assert removed is not None
        assert flow.get_pending(aid) is None
        assert flow.get_pending(msg.message_id) is None
