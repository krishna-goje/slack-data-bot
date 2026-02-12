"""Investigation orchestration - coordinates Claude Code investigation and quality review."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from slack_data_bot.engine.claude_code import ClaudeCodeEngine
from slack_data_bot.engine.quality import QualityReviewer

if TYPE_CHECKING:
    from slack_data_bot.config import BotConfig
    from slack_data_bot.monitor.dedup import SlackMessage

logger = logging.getLogger(__name__)


@dataclass
class InvestigationResult:
    """Outcome of a full investigation pipeline run."""

    question: str
    draft: str
    quality_score: int
    quality_total: int
    rounds: int
    approved: bool
    message: SlackMessage


class InvestigationEngine:
    """Orchestrates the full investigation pipeline.

    Pipeline steps:
      1. Build context from the incoming Slack message.
      2. Run an initial investigation via Claude Code CLI.
      3. Iteratively review and improve the draft through the quality loop.
      4. Return a structured :class:`InvestigationResult`.
    """

    def __init__(self, config: BotConfig) -> None:
        self.claude = ClaudeCodeEngine(config.engine)
        self.quality = QualityReviewer(config.quality)

    def investigate(self, message: SlackMessage) -> InvestigationResult:
        """Run the full investigation pipeline for a Slack message.

        Parameters
        ----------
        message:
            The incoming Slack message to investigate.

        Returns
        -------
        InvestigationResult
            Contains the final draft, quality score, and approval status.
        """
        question = message.text
        context = self._build_context(message)

        logger.info(
            "Starting investigation for message %s in #%s",
            message.ts,
            message.channel_name,
        )

        # Step 1: Initial investigation
        try:
            initial_draft = self.claude.investigate(question, context)
        except Exception:
            logger.exception("Investigation failed for message %s", message.ts)
            return InvestigationResult(
                question=question,
                draft="I was unable to complete the investigation due to an internal error.",
                quality_score=0,
                quality_total=0,
                rounds=0,
                approved=False,
                message=message,
            )

        # Step 2: Quality review loop
        try:
            final_draft, quality_result = self.quality.review_and_improve(
                question=question,
                initial_draft=initial_draft,
                engine=self.claude,
            )
        except Exception:
            logger.exception(
                "Quality review failed for message %s; using initial draft",
                message.ts,
            )
            return InvestigationResult(
                question=question,
                draft=initial_draft,
                quality_score=0,
                quality_total=0,
                rounds=0,
                approved=False,
                message=message,
            )

        logger.info(
            "Investigation complete for %s: score=%d/%d, approved=%s, rounds=%d",
            message.ts,
            quality_result.score,
            quality_result.total,
            quality_result.passed,
            quality_result.rounds if hasattr(quality_result, "rounds") else 0,
        )

        return InvestigationResult(
            question=question,
            draft=final_draft,
            quality_score=quality_result.score,
            quality_total=quality_result.total,
            rounds=quality_result.rounds if hasattr(quality_result, "rounds") else 1,
            approved=quality_result.passed,
            message=message,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(message: SlackMessage) -> str:
        """Format a Slack message into context for the investigation prompt.

        Includes channel info, user info, thread context, and message
        metadata so the investigator has full situational awareness.
        """
        parts: list[str] = []

        # Channel context
        if message.channel_name:
            parts.append(f"Channel: #{message.channel_name}")
        if message.is_dm:
            parts.append("This is a direct message to the bot.")

        # User context
        if message.user_name:
            parts.append(f"Asked by: {message.user_name}")

        # Thread context
        if message.thread_ts and message.thread_ts != message.ts:
            parts.append("This message is part of a thread.")
            if message.reply_count:
                parts.append(f"Thread has {message.reply_count} replies.")

        # Mention context
        if message.is_direct_mention:
            parts.append("The bot was directly mentioned in this message.")

        # Priority
        if message.priority:
            parts.append(f"Priority: {message.priority}")

        # Permalink for reference
        if message.permalink:
            parts.append(f"Permalink: {message.permalink}")

        return "\n".join(parts)
