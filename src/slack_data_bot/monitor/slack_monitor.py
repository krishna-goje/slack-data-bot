"""Async Slack monitor - orchestrates search, filter, dedup, and prioritize.

Rewritten for the MCP architecture: uses async SlackApiClient (httpx)
instead of sync slack-sdk WebClient.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from slack_data_bot.config import BotConfig
from slack_data_bot.monitor.dedup import SlackMessage, deduplicate_messages
from slack_data_bot.monitor.filter import MessageFilter
from slack_data_bot.monitor.priority import PriorityScorer
from slack_data_bot.monitor.search import (
    SearchStrategy,
    generate_search_strategies,
    parse_message,
)

logger = logging.getLogger(__name__)


class AsyncSlackSearchClient(Protocol):
    """Protocol for the async Slack client's search interface.

    Any object providing ``search_messages(query, count, page)`` as an
    async method will work. This keeps the monitor decoupled from the
    specific HTTP client implementation.
    """

    async def search_messages(
        self,
        query: str,
        count: int = 100,
        page: int = 1,
    ) -> dict[str, Any]: ...


class SlackMonitor:
    """Orchestrates the full monitoring cycle (async version).

    Lifecycle:
        1. Generate search strategies from config
        2. Execute each strategy against Slack search API (async)
        3. Parse raw results into ``SlackMessage`` objects
        4. Separate owner responses (strategy 8) for answered filtering
        5. Filter out bots and answered threads
        6. Deduplicate across strategies
        7. Score and sort by priority
    """

    def __init__(
        self,
        config: BotConfig,
        slack_client: AsyncSlackSearchClient | None = None,
    ) -> None:
        self.config = config
        self.monitoring = config.monitoring
        self.filter = MessageFilter(config.monitoring)
        self.scorer = PriorityScorer(config.monitoring)
        self.slack_client = slack_client

    async def find_unanswered(
        self,
        answered_cache: dict | None = None,
    ) -> list[SlackMessage]:
        """Run the full monitoring cycle and return prioritized unanswered messages.

        Args:
            answered_cache: Optional dict of ``channel_id:thread_ts`` keys for
                threads that have already been answered in previous cycles.

        Returns:
            Deduplicated, filtered, and priority-sorted list of messages that
            still need a response. Highest priority first.
        """
        if answered_cache is None:
            answered_cache = {}

        # Step 1: Compute lookback date
        lookback = datetime.now(timezone.utc) - timedelta(
            days=self.monitoring.lookback_days,
        )
        lookback_date = lookback.strftime("%Y-%m-%d")

        # Step 2: Generate strategies
        strategies = generate_search_strategies(self.monitoring, lookback_date)

        # Step 3-4: Search and parse, separating owner responses
        all_messages: list[SlackMessage] = []
        owner_responses: list[SlackMessage] = []

        for strategy in strategies:
            raw_results = await self._search_slack(strategy)
            parsed = self._parse_results(raw_results, strategy)

            if strategy.name == "owner_responses":
                owner_responses.extend(parsed)
            else:
                all_messages.extend(parsed)

        logger.info(
            "Collected %d candidate messages, %d owner responses",
            len(all_messages),
            len(owner_responses),
        )

        # Step 5: Score each message
        for msg in all_messages:
            strategy_name = msg.metadata.get("strategy", "")
            matched_strategy = next(
                (s for s in strategies if s.name == strategy_name),
                strategies[0] if strategies else SearchStrategy(name="fallback", query=""),
            )
            msg.priority = self.scorer.score(msg, matched_strategy, self.filter)

        # Step 6: Filter answered threads
        unanswered = self.filter.filter_answered(
            all_messages,
            owner_responses,
            answered_cache,
        )

        # Step 7: Deduplicate
        unique = deduplicate_messages(unanswered)

        # Step 8: Sort by priority descending
        unique.sort(key=lambda m: m.priority, reverse=True)

        logger.info(
            "Returning %d unanswered messages (from %d candidates)",
            len(unique),
            len(all_messages),
        )
        return unique

    async def _search_slack(self, strategy: SearchStrategy) -> list[dict]:
        """Execute a search strategy against the Slack API (async).

        Handles pagination automatically -- fetches up to ``strategy.count``
        results across multiple pages.
        """
        if self.slack_client is None:
            logger.warning("No Slack client configured; skipping search")
            return []

        results: list[dict] = []
        page = 1
        remaining = strategy.count

        while remaining > 0:
            page_size = min(remaining, 100)
            try:
                response = await self.slack_client.search_messages(
                    query=strategy.query,
                    count=page_size,
                    page=page,
                )
            except Exception:
                logger.exception(
                    "Slack search failed for strategy=%s page=%d",
                    strategy.name,
                    page,
                )
                break

            messages_data = response.get("messages", {})
            matches = messages_data.get("matches", [])
            if not matches:
                break

            results.extend(matches)
            remaining -= len(matches)

            paging = messages_data.get("paging", {})
            total_pages = paging.get("pages", 1)
            if page >= total_pages:
                break
            page += 1

        logger.debug(
            "Strategy '%s' returned %d results",
            strategy.name,
            len(results),
        )
        return results

    def _parse_results(
        self,
        raw_results: list[dict],
        strategy: SearchStrategy,
    ) -> list[SlackMessage]:
        """Convert raw Slack search results into SlackMessage objects.

        Silently drops messages that fail to parse or that are from bots.
        """
        parsed: list[SlackMessage] = []
        for raw in raw_results:
            if self.filter.is_bot_message(raw):
                continue

            msg = parse_message(raw, strategy, self.monitoring)
            if msg is not None:
                parsed.append(msg)

        return parsed
