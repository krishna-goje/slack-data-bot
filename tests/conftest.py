"""Shared fixtures for Slack Data Bot test suite."""

from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slack_data_bot.config import (
    BotConfig,
    CacheConfig,
    ChannelConfig,
    DeliveryConfig,
    EngineConfig,
    LearningConfig,
    MonitorConfig,
    QualityConfig,
    SlackConfig,
)
from slack_data_bot.monitor.dedup import SlackMessage

# ---------------------------------------------------------------------------
# Configuration fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_config() -> BotConfig:
    """BotConfig with sensible test-only values (no real tokens)."""
    return BotConfig(
        slack=SlackConfig(
            bot_token="xoxb-test-token-000",
            app_token="xapp-test-token-000",
            signing_secret="test_signing_secret_000",
            owner_user_id="U_TEST_OWNER",
        ),
        monitoring=MonitorConfig(
            poll_interval_minutes=1,
            lookback_days=7,
            channels=[
                ChannelConfig(name="data-questions", id="C_TEST_001"),
                ChannelConfig(name="analytics", id="C_TEST_002"),
            ],
            domain_keywords=["quicksight", "dbt", "snowflake", "dashboard"],
            bot_usernames=["slackbot", "github", "jira"],
            owner_username="testowner",
        ),
        engine=EngineConfig(
            backend="claude_code",
            claude_code_path="/usr/local/bin/claude",
            investigation_timeout=60,
            review_timeout=30,
            max_concurrent=2,
        ),
        delivery=DeliveryConfig(mode="human_approval", auto_respond_confidence=0.9),
        quality=QualityConfig(
            max_rounds=3,
            min_pass_criteria=5,
            criteria=[
                "data_accuracy",
                "completeness",
                "root_cause",
                "time_period",
                "tone",
                "actionable",
                "caveats",
            ],
        ),
        learning=LearningConfig(
            enabled=True,
            storage_dir="/tmp/sdb-test-learning",
            feedback_tracking=True,
        ),
        cache=CacheConfig(directory="/tmp/sdb-test-cache", answer_ttl_days=30),
    )


# ---------------------------------------------------------------------------
# Message fixtures
# ---------------------------------------------------------------------------


def _make_message(
    *,
    ts: str = "1770335814.365139",
    channel_id: str = "C_TEST_001",
    channel_name: str = "data-questions",
    user_id: str = "U_ALICE",
    user_name: str = "alice",
    text: str = "Why is the dashboard showing wrong numbers?",
    timestamp: datetime | None = None,
    permalink: str = "https://test.slack.com/archives/C_TEST_001/p1770335814365139",
    thread_ts: str | None = None,
    is_direct_mention: bool = False,
    is_domain_question: bool = False,
    is_dm: bool = False,
    reply_count: int = 0,
    priority: int = 50,
    metadata: dict | None = None,
) -> SlackMessage:
    return SlackMessage(
        ts=ts,
        channel_id=channel_id,
        channel_name=channel_name,
        user_id=user_id,
        user_name=user_name,
        text=text,
        timestamp=timestamp or datetime(2026, 2, 12, 10, 0, 0, tzinfo=timezone.utc),
        permalink=permalink,
        thread_ts=thread_ts,
        is_direct_mention=is_direct_mention,
        is_domain_question=is_domain_question,
        is_dm=is_dm,
        reply_count=reply_count,
        priority=priority,
        metadata=metadata or {},
    )


@pytest.fixture()
def sample_message() -> SlackMessage:
    """A single realistic Slack message."""
    return _make_message()


@pytest.fixture()
def sample_messages() -> list[SlackMessage]:
    """Five diverse messages with varying priorities, channels, and types."""
    return [
        _make_message(
            ts="1770335001.000001",
            text="@testowner why did acq numbers drop?",
            is_direct_mention=True,
            priority=100,
        ),
        _make_message(
            ts="1770335002.000002",
            channel_id="C_TEST_002",
            channel_name="analytics",
            text="Can someone check the dbt model for revenue?",
            is_domain_question=True,
            priority=65,
        ),
        _make_message(
            ts="1770335003.000003",
            user_id="U_BOB",
            user_name="bob",
            text="FYI: looping in @testowner on this thread",
            priority=20,
        ),
        _make_message(
            ts="1770335004.000004",
            text="Is the snowflake warehouse down?",
            is_domain_question=True,
            is_dm=True,
            priority=80,
        ),
        _make_message(
            ts="1770335005.000005",
            text="Just a heads-up, deploy completed.",
            priority=0,
        ),
    ]


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_slack_client() -> MagicMock:
    """Mock Slack WebClient with common methods stubbed."""
    client = MagicMock()
    client.search_messages.return_value = {"messages": {"matches": [], "paging": {"pages": 1}}}
    client.chat_postMessage.return_value = {"ok": True, "ts": "1770000000.000001"}
    return client


# ---------------------------------------------------------------------------
# Temporary file system fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_config_file(tmp_path: Path) -> Path:
    """Write a minimal YAML config to a temp file and return the path."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""\
        slack:
          bot_token: "xoxb-tmp-token"
          owner_user_id: "U_TMP_OWNER"
        monitoring:
          poll_interval_minutes: 2
          lookback_days: 3
          channels:
            - name: general
              id: C_GEN
          domain_keywords:
            - quicksight
            - dbt
          bot_usernames:
            - slackbot
          owner_username: "tmpowner"
        engine:
          investigation_timeout: 30
        cache:
          directory: "{cache_dir}"
    """).format(cache_dir=str(tmp_path / "cache")))
    return cfg


@pytest.fixture()
def tmp_cache_dir(tmp_path: Path) -> Path:
    """Return a fresh temporary directory for cache/state files."""
    cache = tmp_path / "bot_cache"
    cache.mkdir()
    return cache
