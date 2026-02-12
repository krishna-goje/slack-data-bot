"""Priority scoring for message urgency ranking."""

from __future__ import annotations

from slack_data_bot.config import MonitorConfig
from slack_data_bot.monitor.dedup import SlackMessage
from slack_data_bot.monitor.filter import MessageFilter
from slack_data_bot.monitor.search import SearchStrategy


class PriorityScorer:
    """Scores messages by urgency using strategy boosts and content signals.

    Scoring rules (additive):
        - Base score = ``strategy.priority_boost``
        - +20 if the message is a question
        - +15 if the message contains a domain keyword
        - -30 if the mention is FYI-style (cc, looping in, etc.)
        - -10 if the message is *not* a question
        - -50 if the mention is inside a code block or blockquote

    The final score is floored at 0 (never negative).
    """

    def __init__(self, config: MonitorConfig) -> None:
        self.config = config

    def score(
        self,
        msg: SlackMessage,
        strategy: SearchStrategy,
        message_filter: MessageFilter,
    ) -> int:
        """Calculate priority score for a message.

        Args:
            msg: The parsed Slack message.
            strategy: The search strategy that found this message.
            message_filter: Filter instance for content analysis helpers.

        Returns:
            Non-negative integer priority score (higher = more urgent).
        """
        points = strategy.priority_boost

        text = msg.text
        owner = self.config.owner_username

        # Positive signals
        if message_filter.is_question(text):
            points += 20
        if message_filter.has_domain_keyword(text):
            points += 15

        # Negative signals
        if message_filter.is_fyi_mention(text):
            points -= 30
        if not message_filter.is_question(text):
            points -= 10
        if message_filter.is_quoted_mention(text, owner):
            points -= 50

        # Floor at zero
        return max(0, points)
