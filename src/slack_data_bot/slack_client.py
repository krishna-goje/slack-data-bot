"""Async Slack API client using httpx.

Replaces slack-sdk WebClient with a minimal async client that only
implements the 3 endpoints we actually need:
- search.messages
- conversations.replies
- users.info

Uses httpx for async HTTP, with built-in rate limiting via the
RateLimiter from resilience.py.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


class SlackApiError(Exception):
    """Raised when a Slack API call fails."""

    def __init__(self, method: str, error: str, response: dict | None = None) -> None:
        self.method = method
        self.error = error
        self.response = response or {}
        super().__init__(f"Slack API error in {method}: {error}")


class SlackApiClient:
    """Async Slack API client using httpx.

    Only implements the endpoints needed for monitoring:
    - ``search_messages``: Search for messages across the workspace
    - ``get_thread_replies``: Get all replies in a thread
    - ``get_user_info``: Look up user profile by ID

    Usage::

        async with SlackApiClient(token="xoxb-...") as client:
            results = await client.search_messages("@krishna.goje after:2026-01-01")
    """

    def __init__(
        self,
        token: str,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        if not token:
            raise ValueError("Slack bot token is required")
        self._token = token
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> SlackApiClient:
        self._client = httpx.AsyncClient(
            base_url=SLACK_API_BASE,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=httpx.Timeout(self._timeout),
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("SlackApiClient must be used as async context manager")
        return self._client

    async def _api_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Make a Slack API call with retry logic.

        Args:
            method: Slack API method (e.g., 'search.messages')
            params: Query parameters for the API call

        Returns:
            Parsed JSON response dict

        Raises:
            SlackApiError: If the API returns ok=false after all retries
        """
        last_error = ""
        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self.client.post(
                    f"/{method}",
                    data=params,
                )
                response.raise_for_status()
                data = response.json()

                if data.get("ok"):
                    return data

                error = data.get("error", "unknown_error")

                # Rate limited - respect Retry-After header
                if error == "ratelimited":
                    retry_after = int(response.headers.get("Retry-After", "5"))
                    logger.warning(
                        "Rate limited on %s, waiting %ds (attempt %d/%d)",
                        method,
                        retry_after,
                        attempt,
                        self._max_retries,
                    )
                    import asyncio

                    await asyncio.sleep(retry_after)
                    continue

                last_error = error
                logger.warning(
                    "Slack API error on %s: %s (attempt %d/%d)",
                    method,
                    error,
                    attempt,
                    self._max_retries,
                )

            except httpx.HTTPStatusError as exc:
                last_error = f"HTTP {exc.response.status_code}"
                logger.warning(
                    "HTTP error on %s: %s (attempt %d/%d)",
                    method,
                    last_error,
                    attempt,
                    self._max_retries,
                )
            except httpx.RequestError as exc:
                last_error = str(exc)
                logger.warning(
                    "Request error on %s: %s (attempt %d/%d)",
                    method,
                    last_error,
                    attempt,
                    self._max_retries,
                )

        raise SlackApiError(method, last_error)

    async def search_messages(
        self,
        query: str,
        count: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """Search for messages across the workspace.

        Args:
            query: Slack search query string (supports all Slack search operators)
            count: Number of results per page (max 100)
            page: Page number for pagination

        Returns:
            Slack API response with messages.matches array
        """
        return await self._api_call(
            "search.messages",
            {
                "query": query,
                "count": min(count, 100),
                "page": page,
                "sort": "timestamp",
                "sort_dir": "desc",
            },
        )

    async def get_thread_replies(
        self,
        channel: str,
        ts: str,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Get all replies in a thread.

        Args:
            channel: Channel ID containing the thread
            ts: Thread parent timestamp
            limit: Maximum number of replies to fetch

        Returns:
            Slack API response with messages array (includes parent)
        """
        return await self._api_call(
            "conversations.replies",
            {
                "channel": channel,
                "ts": ts,
                "limit": min(limit, 1000),
                "inclusive": "true",
            },
        )

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Look up user profile by ID.

        Args:
            user_id: Slack user ID (e.g., 'U12345678')

        Returns:
            Slack API response with user object
        """
        return await self._api_call(
            "users.info",
            {"user": user_id},
        )
