"""Tests for the async Slack API client."""

from __future__ import annotations

import pytest

from slack_data_bot.slack_client import SlackApiClient, SlackApiError


class TestSlackApiClient:
    def test_empty_token_raises(self):
        """Client requires a non-empty token."""
        with pytest.raises(ValueError, match="Slack bot token is required"):
            SlackApiClient(token="")

    def test_context_manager_required(self):
        """Accessing client property without context manager raises."""
        client = SlackApiClient(token="xoxb-test-123")
        with pytest.raises(RuntimeError, match="must be used as async context manager"):
            _ = client.client

    @pytest.mark.asyncio
    async def test_context_manager_lifecycle(self):
        """Client opens and closes properly."""
        async with SlackApiClient(token="xoxb-test-123") as client:
            assert client._client is not None
        # After exit, client should be closed
        assert client._client is None

    @pytest.mark.asyncio
    async def test_search_messages_params(self, httpx_mock):
        """search_messages sends correct parameters."""
        httpx_mock.add_response(
            url="https://slack.com/api/search.messages",
            json={
                "ok": True,
                "messages": {
                    "matches": [{"text": "test", "ts": "1.1"}],
                    "paging": {"pages": 1},
                },
            },
        )
        async with SlackApiClient(token="xoxb-test-123") as client:
            result = await client.search_messages("@testowner after:2026-01-01", count=50)
            assert result["ok"] is True
            assert len(result["messages"]["matches"]) == 1

    @pytest.mark.asyncio
    async def test_get_thread_replies(self, httpx_mock):
        """get_thread_replies calls the correct API endpoint."""
        httpx_mock.add_response(
            url="https://slack.com/api/conversations.replies",
            json={
                "ok": True,
                "messages": [
                    {"text": "parent msg", "ts": "1.0", "user": "U1"},
                    {"text": "reply", "ts": "1.1", "user": "U2"},
                ],
            },
        )
        async with SlackApiClient(token="xoxb-test-123") as client:
            result = await client.get_thread_replies(channel="C123", ts="1.0")
            assert len(result["messages"]) == 2

    @pytest.mark.asyncio
    async def test_get_user_info(self, httpx_mock):
        """get_user_info calls the correct endpoint."""
        httpx_mock.add_response(
            url="https://slack.com/api/users.info",
            json={
                "ok": True,
                "user": {"id": "U123", "name": "testuser"},
            },
        )
        async with SlackApiClient(token="xoxb-test-123") as client:
            result = await client.get_user_info("U123")
            assert result["user"]["name"] == "testuser"

    @pytest.mark.asyncio
    async def test_api_error_raises(self, httpx_mock):
        """Non-ok response raises SlackApiError after retries."""
        httpx_mock.add_response(
            url="https://slack.com/api/search.messages",
            json={"ok": False, "error": "invalid_auth"},
        )
        async with SlackApiClient(token="xoxb-test-123", max_retries=1) as client:
            with pytest.raises(SlackApiError, match="invalid_auth"):
                await client.search_messages("test")
