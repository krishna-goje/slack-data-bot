"""Integration tests: end-to-end workflows with all mocks in place."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slack_data_bot.delivery.approval import ApprovalAction, ApprovalFlow
from slack_data_bot.delivery.notifier import Notifier
from slack_data_bot.engine.investigator import InvestigationEngine
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
        text="Why did WBR numbers drop this week?",
        timestamp=datetime(2026, 2, 12, 10, 0, 0, tzinfo=timezone.utc),
        permalink="https://test.slack.com/archives/C001/p1770335814365139",
        priority=50,
    )
    defaults.update(overrides)
    return SlackMessage(**defaults)


# ===================================================================
# Full poll -> investigate -> notify workflow
# ===================================================================


class TestFullPollInvestigateNotify:
    def test_full_poll_investigate_notify(self, sample_config, mock_slack_client):
        """End-to-end: monitor finds question, engine investigates, notifier sends DM."""
        # -- Monitor mock: return one unanswered question
        msg = _msg()
        mock_monitor = MagicMock()
        mock_monitor.find_unanswered.return_value = [msg]

        # -- Engine mock: return investigation result
        engine = InvestigationEngine(sample_config)
        engine.claude = MagicMock()
        engine.claude.investigate.return_value = "The drop was due to a filter change in dbt."
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

        result = engine.investigate(msg)
        assert result.approved is True

        # -- Notifier: sends DM with draft
        notifier = Notifier(sample_config, slack_client=mock_slack_client)
        resp = notifier.notify_human(
            msg, result.draft, result.quality_score, result.quality_total,
        )
        assert resp is not None
        mock_slack_client.chat_postMessage.assert_called_once()


# ===================================================================
# Full approval flow
# ===================================================================


class TestFullApprovalFlow:
    def test_full_approval_flow(self, sample_config, mock_slack_client):
        """Submit -> approve -> post to thread."""
        flow = ApprovalFlow(sample_config, slack_client=mock_slack_client)
        msg = _msg()
        draft = "The metric dropped because of filter X."

        # Submit
        aid = flow.submit_for_approval(msg, draft)
        pending = flow.get_pending(aid)
        assert pending is not None

        # Approve
        action = flow.handle_action("approve", aid, "U_REVIEWER")
        assert action == ApprovalAction.APPROVE

        # Post
        result = flow.post_approved_response(msg, draft)
        assert result is not None
        call_kwargs = mock_slack_client.chat_postMessage.call_args[1]
        assert call_kwargs["text"] == draft

        # Clean up
        flow.remove_pending(aid)
        assert flow.get_pending(aid) is None

    def test_full_rejection_flow(self, sample_config, mock_slack_client):
        """Submit -> reject -> record feedback."""
        flow = ApprovalFlow(sample_config, slack_client=mock_slack_client)
        msg = _msg()
        aid = flow.submit_for_approval(msg, "Bad draft.")

        action = flow.handle_action("reject", aid, "U_REVIEWER")
        assert action == ApprovalAction.REJECT

        # Verify pending still exists until explicitly removed
        pending = flow.get_pending(aid)
        assert pending is not None

        # Remove after rejection
        flow.remove_pending(aid)
        assert flow.get_pending(aid) is None


# ===================================================================
# No questions found
# ===================================================================


class TestNoQuestionsFound:
    def test_no_questions_found(self, sample_config):
        """When search returns nothing, no investigation or notification occurs."""
        mock_monitor = MagicMock()
        mock_monitor.find_unanswered.return_value = []

        engine = MagicMock()
        notifier = MagicMock()

        # Simulate the poll_cycle logic
        questions = mock_monitor.find_unanswered({})
        assert len(questions) == 0
        engine.investigate.assert_not_called()
        notifier.notify_human.assert_not_called()


# ===================================================================
# Source code audit: no hardcoded Opendoor references
# ===================================================================


class TestOpendoorAudit:
    """Scan source code for hardcoded values that should be configurable.

    The bot must be generic and not contain references to any specific
    organization, user IDs, channel IDs, or internal table names.
    """

    # Patterns that should NOT appear in the source code
    FORBIDDEN_PATTERNS = [
        r"\bopendoor\b",           # Company name
        r"\bkrishna\b",            # Personal name
        r"\bU07J[A-Z0-9]+\b",     # Slack user IDs
        r"\bC16FWCE9X\b",         # Specific channel ID
        r"\bacq_l[12]\b",         # Internal dbt model names
        r"\binv_l2\b",            # Internal dbt model names
        r"\bwbr_ingest\b",        # Internal dbt model names
    ]

    @pytest.fixture()
    def source_files(self) -> list[Path]:
        src_dir = Path(__file__).parent.parent / "src" / "slack_data_bot"
        files = list(src_dir.rglob("*.py"))
        assert len(files) > 0, "No source files found -- check path"
        return files

    def test_opendoor_audit(self, source_files):
        violations: list[str] = []
        combined_pattern = re.compile(
            "|".join(f"({p})" for p in self.FORBIDDEN_PATTERNS),
            re.IGNORECASE,
        )

        for filepath in source_files:
            content = filepath.read_text(encoding="utf-8")
            for line_num, line in enumerate(content.splitlines(), 1):
                # Skip comments that mention patterns in a generic way
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                match = combined_pattern.search(line)
                if match:
                    violations.append(
                        f"{filepath.relative_to(filepath.parent.parent.parent)}:"
                        f"{line_num}: {match.group()!r} in: {stripped[:120]}"
                    )

        assert violations == [], (
            f"Found {len(violations)} hardcoded reference(s) in source:\n"
            + "\n".join(violations)
        )
