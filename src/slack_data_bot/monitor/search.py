"""Search strategy generation for Slack monitoring.

Generates multiple complementary search strategies to eliminate blind spots.
All strategies are derived from configuration - no hardcoded values.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from slack_data_bot.config import MonitorConfig
from slack_data_bot.monitor.dedup import SlackMessage

logger = logging.getLogger(__name__)


@dataclass
class SearchStrategy:
    """A single search strategy with its query and scoring metadata."""

    name: str
    query: str
    count: int = 100
    priority_boost: int = 0
    marks_direct_mention: bool = False
    marks_dm: bool = False


def generate_search_strategies(
    config: MonitorConfig,
    lookback_date: str,
) -> list[SearchStrategy]:
    """Generate all search strategies from configuration.

    Produces 8 complementary strategies that together cover direct
    mentions, channel questions, domain keywords, generic data questions,
    DMs, and owner responses (used for filtering answered threads).

    Args:
        config: Monitoring configuration with channels, keywords, owner, etc.
        lookback_date: ISO date string (YYYY-MM-DD) for the ``after:`` filter.

    Returns:
        List of ``SearchStrategy`` instances ready to execute.
    """
    strategies: list[SearchStrategy] = []
    owner = config.owner_username
    after = f"after:{lookback_date}"

    # Build channel name list from configured channels
    channel_names = [ch.name for ch in config.channels]

    # --- Strategy 1: Direct @mentions of owner ---
    if owner:
        strategies.append(
            SearchStrategy(
                name="direct_mentions",
                query=f"@{owner} {after}",
                priority_boost=100,
                marks_direct_mention=True,
            )
        )

    # --- Strategy 2: Questions in monitored channels ---
    if channel_names:
        # Slack search supports multiple in: clauses (OR logic)
        in_channels = " ".join(f"in:#{name}" for name in channel_names)
        strategies.append(
            SearchStrategy(
                name="channel_questions",
                query=f"? {in_channels} {after}",
                priority_boost=50,
            )
        )

    # --- Strategies 3-5: Domain keyword questions by category ---
    keywords = config.domain_keywords
    if keywords:
        # Split keywords into up to 3 groups for separate strategies
        chunk_size = max(1, len(keywords) // 3 + (1 if len(keywords) % 3 else 0))
        chunks = [
            keywords[i : i + chunk_size]
            for i in range(0, len(keywords), chunk_size)
        ]
        for idx, chunk in enumerate(chunks[:3]):
            kw_query = " OR ".join(chunk)
            strategies.append(
                SearchStrategy(
                    name=f"domain_keywords_{idx + 1}",
                    query=f"({kw_query}) ? {after}",
                    priority_boost=30,
                )
            )

    # --- Strategy 6: Generic model/data questions ---
    generic_terms = ["model", "data", "metric", "report", "number", "query"]
    generic_query = " OR ".join(generic_terms)
    if channel_names:
        in_channels = " ".join(f"in:#{name}" for name in channel_names)
        strategies.append(
            SearchStrategy(
                name="generic_data_questions",
                query=f"({generic_query}) ? {in_channels} {after}",
                priority_boost=20,
            )
        )
    else:
        strategies.append(
            SearchStrategy(
                name="generic_data_questions",
                query=f"({generic_query}) ? {after}",
                priority_boost=20,
            )
        )

    # --- Strategy 7: DMs to owner ---
    if owner:
        strategies.append(
            SearchStrategy(
                name="direct_messages",
                query=f"to:@{owner} {after}",
                priority_boost=80,
                marks_dm=True,
            )
        )

    # --- Strategy 8: Owner's responses (for answered-thread filtering) ---
    if owner:
        strategies.append(
            SearchStrategy(
                name="owner_responses",
                query=f"from:@{owner} {after}",
                priority_boost=0,
            )
        )

    logger.info("Generated %d search strategies", len(strategies))
    return strategies


def parse_slack_timestamp(
    ts_str: str,
    iso_str: str | None = None,
) -> datetime:
    """Parse a Slack timestamp into a UTC datetime.

    Handles two common formats:
    - Epoch with microseconds: ``1770335814.365139``
    - ISO-8601 string: ``2025-06-10T12:30:00Z``

    Args:
        ts_str: The Slack ``ts`` field (epoch format).
        iso_str: Optional ISO-8601 timestamp (takes precedence if parseable).

    Returns:
        Timezone-aware UTC datetime.
    """
    if iso_str:
        try:
            # Handle both Z-suffix and +00:00 offset
            cleaned = iso_str.replace("Z", "+00:00")
            return datetime.fromisoformat(cleaned)
        except (ValueError, TypeError):
            pass

    try:
        epoch = float(ts_str)
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (ValueError, TypeError):
        logger.warning("Could not parse timestamp ts=%s iso=%s", ts_str, iso_str)
        return datetime.now(timezone.utc)


def extract_thread_ts(permalink: str) -> str | None:
    """Extract the thread_ts from a Slack permalink URL.

    Handles two permalink formats:
    - Query parameter: ``...?thread_ts=1770335814.365139``
    - Path-based: ``.../p1770335814365139``

    Args:
        permalink: Full Slack permalink URL.

    Returns:
        The thread_ts string, or ``None`` if not found.
    """
    if not permalink:
        return None

    # Try query parameter first
    parsed = urlparse(permalink)
    params = parse_qs(parsed.query)
    if "thread_ts" in params:
        return params["thread_ts"][0]

    # Try path-based format: /p{digits}
    match = re.search(r"/p(\d{10})(\d{6})(?:\?|$)", permalink)
    if match:
        return f"{match.group(1)}.{match.group(2)}"

    return None


def parse_message(
    msg: dict,
    strategy: SearchStrategy,
    config: MonitorConfig,
) -> SlackMessage | None:
    """Parse a raw Slack search result into a SlackMessage.

    Args:
        msg: Raw message dict from Slack search API.
        strategy: The strategy that produced this result (for flag propagation).
        config: Monitor config for owner/keyword lookups.

    Returns:
        A ``SlackMessage`` instance, or ``None`` if the message lacks required fields.
    """
    text = msg.get("text", "")
    ts = msg.get("ts", "")
    if not ts:
        return None

    # Extract channel info - Slack search nests it under 'channel'
    channel_info = msg.get("channel", {})
    if isinstance(channel_info, dict):
        channel_id = channel_info.get("id", "")
        channel_name = channel_info.get("name", "")
    else:
        # Sometimes channel is just an ID string
        channel_id = str(channel_info)
        channel_name = ""

    permalink = msg.get("permalink", "")
    thread_ts = msg.get("thread_ts") or extract_thread_ts(permalink)
    iso_ts = msg.get("iid", msg.get("date_str"))

    # Determine if this is a domain-keyword question
    text_lower = text.lower()
    is_domain = any(kw.lower() in text_lower for kw in config.domain_keywords)

    # Check for direct @mention of owner in the text
    owner = config.owner_username
    is_mention = bool(owner and f"@{owner}" in text.lower())

    return SlackMessage(
        ts=ts,
        channel_id=channel_id,
        channel_name=channel_name,
        user_id=msg.get("user", msg.get("user_id", "")),
        user_name=msg.get("username", ""),
        text=text,
        timestamp=parse_slack_timestamp(ts, iso_str=iso_ts),
        permalink=permalink,
        thread_ts=thread_ts,
        is_direct_mention=strategy.marks_direct_mention or is_mention,
        is_domain_question=is_domain,
        is_dm=strategy.marks_dm,
        reply_count=msg.get("reply_count", 0),
        priority=strategy.priority_boost,
        metadata={
            "strategy": strategy.name,
            "raw_type": msg.get("type", ""),
            "subtype": msg.get("subtype", ""),
        },
    )
