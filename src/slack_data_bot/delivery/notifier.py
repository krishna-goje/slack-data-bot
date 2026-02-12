"""Notification delivery - sends draft responses to human for review.

Sends DM notifications to the bot owner with investigation results,
quality scores, and interactive approval buttons via Slack Block Kit.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from slack_sdk import WebClient

    from slack_data_bot.config import BotConfig
    from slack_data_bot.monitor.dedup import SlackMessage

logger = logging.getLogger(__name__)


class Notifier:
    """Sends DM notifications to the bot owner with investigation results.

    Each notification includes the original question summary, a link to the
    Slack message, the drafted response, a quality score, and interactive
    approve/edit/reject buttons.
    """

    def __init__(self, config: BotConfig, slack_client: WebClient | None = None) -> None:
        self.owner_user_id: str = config.slack.owner_user_id
        self._client = slack_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def notify_human(
        self,
        message: SlackMessage,
        draft: str,
        quality_score: int,
        quality_total: int,
    ) -> dict[str, Any] | None:
        """Send a DM to the owner with the draft response for review.

        Returns the Slack API response dict on success, or ``None``
        if no client is configured.
        """
        if not self._client:
            logger.warning("No Slack client configured; skipping notification")
            return None

        blocks: list[dict] = []
        blocks.extend(self._format_question_block(message))
        blocks.extend(self._format_draft_block(draft, quality_score, quality_total))
        blocks.extend(self._format_action_block(message.message_id))

        fallback_text = (
            f"New question from {message.user_name} in #{message.channel_name}: "
            f"{message.text[:120]}"
        )

        try:
            response = self._client.chat_postMessage(
                channel=self.owner_user_id,
                text=fallback_text,
                blocks=blocks,
            )
            logger.info("Sent review notification for message %s", message.message_id)
            return response
        except Exception:
            logger.exception("Failed to send review notification for %s", message.message_id)
            return None

    def notify_error(self, message: SlackMessage, error: str) -> dict[str, Any] | None:
        """Send an error notification DM to the owner."""
        if not self._client:
            logger.warning("No Slack client configured; skipping error notification")
            return None

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Investigation Error", "emoji": True},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Channel:* <#{message.channel_id}|{message.channel_name}>\n"
                        f"*From:* {message.user_name}\n"
                        f"*Question:* {message.text[:200]}\n\n"
                        f"*Error:*\n```{error[:500]}```"
                    ),
                },
            },
        ]

        try:
            return self._client.chat_postMessage(
                channel=self.owner_user_id,
                text=f"Investigation error: {error[:100]}",
                blocks=blocks,
            )
        except Exception:
            logger.exception("Failed to send error notification for %s", message.message_id)
            return None

    # ------------------------------------------------------------------
    # Block Kit builders
    # ------------------------------------------------------------------

    def _format_question_block(self, message: SlackMessage) -> list[dict]:
        """Build Slack Block Kit blocks for the original question."""
        link_text = f"<{message.permalink}|View in Slack>" if message.permalink else ""
        return [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "New Question for Review", "emoji": True},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Channel:* <#{message.channel_id}|{message.channel_name}> "
                        f"({message.relative_time})\n"
                        f"*From:* {message.user_name}\n"
                        f"{link_text}"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"> {message.text[:500]}",
                },
            },
        ]

    def _format_draft_block(
        self, draft: str, quality_score: int, quality_total: int,
    ) -> list[dict]:
        """Build Slack Block Kit blocks for the draft response and quality score."""
        score_bar = self._score_indicator(quality_score, quality_total)
        # Truncate draft for the notification; full text stored in PendingApproval
        display_draft = draft if len(draft) <= 2900 else draft[:2900] + "\n...(truncated)"
        return [
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Quality:* {score_bar}  ({quality_score}/{quality_total})",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Draft Response:*\n{display_draft}",
                },
            },
        ]

    def _format_action_block(self, message_id: str) -> list[dict]:
        """Build Slack Block Kit blocks for approve/edit/reject buttons."""
        return [
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "approve",
                        "value": message_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit"},
                        "action_id": "edit",
                        "value": message_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "action_id": "reject",
                        "value": message_id,
                    },
                ],
            },
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _score_indicator(score: int, total: int) -> str:
        """Return a visual quality score bar (e.g., ``[####--] 4/6``)."""
        if total <= 0:
            return "[------] ?/?"
        filled = min(score, total)
        bar = "#" * filled + "-" * (total - filled)
        return f"[{bar}]"
