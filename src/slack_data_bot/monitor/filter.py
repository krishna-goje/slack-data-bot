"""Message filtering for bot detection, noise removal, and answer tracking."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from slack_data_bot.config import MonitorConfig
from slack_data_bot.monitor.dedup import SlackMessage

if TYPE_CHECKING:
    pass


class MessageFilter:
    """Filters messages to remove bots, noise, and already-answered threads.

    All filter logic is driven by ``MonitorConfig`` -- no hardcoded values.
    """

    # FYI patterns that indicate the @mention is informational, not a question
    _FYI_PATTERNS = re.compile(
        r"(?i)\b(?:cc:|fyi:|looping\s+in\s+@|adding\s+@|copying\s+@|cc\s+@|cc'ing)",
    )

    # Question indicators
    _QUESTION_WORDS = re.compile(
        r"(?i)(?:"
        r"\?"
        r"|\bwondering\b"
        r"|\bnot\s+sure\b"
        r"|\bhelp\b"
        r"|\bhow\s+do\b"
        r"|\bwhat\s+is\b"
        r"|\bwhere\b"
        r"|\bwhy\b"
        r"|\bcan\s+you\b"
        r"|\bcould\s+you\b"
        r"|\bdo\s+you\s+know\b"
        r"|\bany\s+idea\b"
        r")",
    )

    def __init__(self, config: MonitorConfig) -> None:
        self.config = config
        self._bot_usernames = {u.lower() for u in config.bot_usernames}
        self._domain_keywords = [kw.lower() for kw in config.domain_keywords]

    def is_bot_message(self, msg: dict) -> bool:
        """Check if a raw Slack message dict is from a bot.

        Detects bots via:
        - Username in configured bot_usernames list
        - ``subtype`` == ``"bot_message"``
        - Presence of ``bot_id`` field
        """
        username = msg.get("username", "").lower()
        if username in self._bot_usernames:
            return True
        if msg.get("subtype") == "bot_message":
            return True
        if msg.get("bot_id"):
            return True
        return False

    def is_fyi_mention(self, text: str) -> bool:
        """Detect informational @mentions (cc, fyi, looping in, etc.)."""
        return bool(self._FYI_PATTERNS.search(text))

    def is_quoted_mention(self, text: str, owner_username: str) -> bool:
        """Detect @mention of the owner inside code blocks or blockquotes.

        A quoted mention is not a true request for attention -- the person is
        pasting logs, quoting someone else, or referencing in a code snippet.
        """
        if not owner_username:
            return False

        mention = f"@{owner_username}".lower()
        text_lower = text.lower()

        if mention not in text_lower:
            return False

        # Check if mention is inside a code block (``` ... ```)
        code_blocks = re.findall(r"```.*?```", text, flags=re.DOTALL)
        for block in code_blocks:
            if mention in block.lower():
                return True

        # Check if mention is inside an inline code span (` ... `)
        inline_code = re.findall(r"`[^`]+`", text)
        for span in inline_code:
            if mention in span.lower():
                return True

        # Check if mention is on a blockquote line (> ...)
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith(">") and mention in stripped.lower():
                return True

        return False

    def is_question(self, text: str) -> bool:
        """Detect whether text contains a question or request for help."""
        return bool(self._QUESTION_WORDS.search(text))

    def has_domain_keyword(self, text: str) -> bool:
        """Check if text contains any configured domain keywords."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in self._domain_keywords)

    def filter_answered(
        self,
        messages: list[SlackMessage],
        owner_responses: list[SlackMessage],
        answered_cache: dict,
    ) -> list[SlackMessage]:
        """Remove messages the owner has already replied to.

        A message is considered answered if:
        1. The owner posted a response in the same thread (matched by
           ``channel_id:thread_ts``), **or**
        2. The message's thread key appears in ``answered_cache``.

        Args:
            messages: Candidate messages that might need a response.
            owner_responses: Messages authored by the owner (strategy 8).
            answered_cache: Dict mapping ``channel_id:thread_ts`` to any truthy
                value for threads previously marked answered.

        Returns:
            Filtered list with answered messages removed.
        """
        # Build set of thread keys the owner has responded to
        answered_threads: set[str] = set()
        for resp in owner_responses:
            thread_key = resp.thread_ts or resp.ts
            answered_threads.add(f"{resp.channel_id}:{thread_key}")

        # Merge with cache
        for key in answered_cache:
            answered_threads.add(key)

        result: list[SlackMessage] = []
        for msg in messages:
            thread_key = msg.thread_ts or msg.ts
            lookup = f"{msg.channel_id}:{thread_key}"
            if lookup in answered_threads:
                continue
            result.append(msg)

        return result
