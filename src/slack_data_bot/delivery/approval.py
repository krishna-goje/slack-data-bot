"""Approval flow - handles human review decisions via Slack interactive messages.

Manages the lifecycle of pending approvals: submission, button-click handling,
and final posting of approved responses to the original thread.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from slack_sdk import WebClient

    from slack_data_bot.config import BotConfig
    from slack_data_bot.monitor.dedup import SlackMessage

logger = logging.getLogger(__name__)


class ApprovalAction(Enum):
    """Possible human review decisions."""

    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


@dataclass
class PendingApproval:
    """A draft response waiting for human review."""

    message: SlackMessage
    draft: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approval_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class ApprovalFlow:
    """Manages the approval lifecycle for drafted responses.

    Flow:
      1. ``submit_for_approval`` stores the draft and returns an ``approval_id``.
      2. When the human clicks a button, ``handle_action`` resolves the decision.
      3. On approval, ``post_approved_response`` delivers the draft to the
         original Slack thread.
    """

    # Maximum number of pending approvals before oldest are evicted.
    MAX_PENDING = 200

    def __init__(self, config: BotConfig, slack_client: WebClient | None = None) -> None:
        self.config = config
        self._client = slack_client
        self._pending: dict[str, PendingApproval] = {}

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def submit_for_approval(self, message: SlackMessage, draft: str) -> str:
        """Store a draft response and return a unique approval ID.

        Parameters
        ----------
        message:
            The original Slack message the draft responds to.
        draft:
            The drafted response text.

        Returns
        -------
        str
            A unique ``approval_id`` that maps to this pending approval.
        """
        pending = PendingApproval(message=message, draft=draft)
        self._pending[pending.approval_id] = pending

        # Also index by message_id so button value lookups work.
        self._pending[message.message_id] = pending

        # Evict oldest entries if we exceed the limit.
        self._evict_if_needed()

        logger.info(
            "Submitted for approval: id=%s message=%s",
            pending.approval_id,
            message.message_id,
        )
        return pending.approval_id

    # ------------------------------------------------------------------
    # Action handling
    # ------------------------------------------------------------------

    def handle_action(
        self,
        action_id: str,
        approval_id: str,
        user_id: str,
    ) -> ApprovalAction:
        """Process a button click from the interactive notification.

        Parameters
        ----------
        action_id:
            The ``action_id`` from the Slack interaction payload
            (``"approve"``, ``"edit"``, or ``"reject"``).
        approval_id:
            The ``value`` field from the button, which is either the
            ``approval_id`` or the ``message_id`` used as a lookup key.
        user_id:
            The Slack user ID of the person who clicked the button.

        Returns
        -------
        ApprovalAction
            The resolved action enum value.

        Raises
        ------
        ValueError
            If ``action_id`` does not map to a known action.
        """
        action_map = {
            "approve": ApprovalAction.APPROVE,
            "edit": ApprovalAction.EDIT,
            "reject": ApprovalAction.REJECT,
        }

        action = action_map.get(action_id)
        if action is None:
            raise ValueError(f"Unknown action_id: {action_id!r}")

        logger.info(
            "Approval action: %s by user %s for approval %s",
            action.value,
            user_id,
            approval_id,
        )
        return action

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    def post_approved_response(
        self,
        message: SlackMessage,
        draft: str,
    ) -> dict[str, Any] | None:
        """Post the approved draft as a reply in the original Slack thread.

        Parameters
        ----------
        message:
            The original Slack message to reply to.
        draft:
            The approved response text.

        Returns
        -------
        dict or None
            The Slack API response, or ``None`` if no client is configured.
        """
        if not self._client:
            logger.warning("No Slack client configured; cannot post response")
            return None

        # Reply in thread; use thread_ts if the original was in a thread,
        # otherwise start a new thread from the message ts.
        thread_ts = message.thread_ts or message.ts

        try:
            response = self._client.chat_postMessage(
                channel=message.channel_id,
                text=draft,
                thread_ts=thread_ts,
            )
            logger.info(
                "Posted approved response in #%s thread %s",
                message.channel_name,
                thread_ts,
            )
            return response
        except Exception:
            logger.exception(
                "Failed to post approved response in #%s thread %s",
                message.channel_name,
                thread_ts,
            )
            return None

    # ------------------------------------------------------------------
    # Pending lookup
    # ------------------------------------------------------------------

    def get_pending(self, approval_id: str) -> PendingApproval | None:
        """Retrieve a pending approval by its ID or message ID.

        Returns ``None`` if the approval has expired or was never submitted.
        """
        return self._pending.get(approval_id)

    def remove_pending(self, approval_id: str) -> PendingApproval | None:
        """Remove and return a pending approval after it has been acted on."""
        pending = self._pending.pop(approval_id, None)
        if pending is not None:
            # Also remove the message_id alias if present.
            self._pending.pop(pending.message.message_id, None)
        return pending

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evict_if_needed(self) -> None:
        """Remove oldest pending approvals when the cache exceeds MAX_PENDING."""
        if len(self._pending) <= self.MAX_PENDING:
            return

        # Sort by creation time, evict the oldest quarter.
        by_age = sorted(
            (
                (k, v)
                for k, v in self._pending.items()
                if isinstance(v, PendingApproval)
            ),
            key=lambda item: item[1].created_at,
        )
        evict_count = len(by_age) // 4
        for key, _ in by_age[:evict_count]:
            self._pending.pop(key, None)

        logger.info("Evicted %d stale pending approvals", evict_count)
