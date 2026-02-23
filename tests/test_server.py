"""Tests for the FastMCP server tools."""

from __future__ import annotations

import json

import pytest

from slack_data_bot.server import classify_question, mark_answered


class TestClassifyQuestion:
    @pytest.mark.asyncio
    async def test_count_question(self):
        result = json.loads(await classify_question("How many contracts this week?"))
        assert result["question_type"] == "count"
        assert result["confidence"] >= 0.7

    @pytest.mark.asyncio
    async def test_trend_question(self):
        result = json.loads(await classify_question("What's the trend over time for revenue?"))
        assert result["question_type"] == "trend"

    @pytest.mark.asyncio
    async def test_comparison_question(self):
        result = json.loads(await classify_question("Compare Phoenix vs Atlanta contracts"))
        assert result["question_type"] == "comparison"

    @pytest.mark.asyncio
    async def test_definition_question(self):
        result = json.loads(await classify_question("What is repair surplus?"))
        assert result["question_type"] == "definition"

    @pytest.mark.asyncio
    async def test_root_cause_question(self):
        result = json.loads(await classify_question("Why did the numbers drop last week?"))
        assert result["question_type"] == "root_cause"

    @pytest.mark.asyncio
    async def test_lineage_question(self):
        result = json.loads(
            await classify_question("Where does the revenue data come from upstream?")
        )
        assert result["question_type"] == "lineage"

    @pytest.mark.asyncio
    async def test_unknown_question(self):
        result = json.loads(await classify_question("Hello"))
        assert result["question_type"] == "unknown"

    @pytest.mark.asyncio
    async def test_entity_extraction(self):
        result = json.loads(
            await classify_question("Why is the quicksight dashboard broken?")
        )
        assert "quicksight" in result["entities"]
        assert "dashboard" in result["entities"]

    @pytest.mark.asyncio
    async def test_time_period_extraction(self):
        result = json.loads(await classify_question("What happened last week with contracts?"))
        assert result["time_period"] == "last week"

    @pytest.mark.asyncio
    async def test_complexity_simple(self):
        result = json.loads(await classify_question("How many contracts?"))
        assert result["complexity"] == "simple"

    @pytest.mark.asyncio
    async def test_complexity_complex(self):
        long_q = (
            "Can you investigate why the QuickSight dashboard is showing different numbers "
            "than what we see in Snowflake for the WBR contracts metric? We noticed the "
            "discrepancy started last week and it seems to affect multiple markets including "
            "Phoenix, Atlanta, and Dallas. Please check the dbt model and the SPICE refresh."
        )
        result = json.loads(await classify_question(long_q))
        assert result["complexity"] == "complex"


class TestMarkAnswered:
    @pytest.mark.asyncio
    async def test_mark_answered_success(self, tmp_path, monkeypatch):
        """mark_answered writes to cache and returns success."""
        from slack_data_bot import server
        from slack_data_bot.cache.state import BotState
        from slack_data_bot.config import CacheConfig

        cache_config = CacheConfig(directory=str(tmp_path))
        state = BotState(cache_config)
        monkeypatch.setattr(server, "_state", state)

        result = json.loads(
            await mark_answered(
                channel_id="C123",
                message_ts="1234.5678",
                summary="Answered with data",
            )
        )
        assert result["success"] is True
        assert result["thread_key"] == "C123:1234.5678"

        # Verify it's in the cache
        assert state.is_answered("1234.5678", "C123") is True
