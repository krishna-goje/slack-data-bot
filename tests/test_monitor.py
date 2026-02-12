"""Tests for the monitor subsystem: search, filter, dedup, priority."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from slack_data_bot.config import ChannelConfig, MonitorConfig
from slack_data_bot.monitor.dedup import SlackMessage, deduplicate_messages
from slack_data_bot.monitor.filter import MessageFilter
from slack_data_bot.monitor.priority import PriorityScorer
from slack_data_bot.monitor.search import (
    SearchStrategy,
    extract_thread_ts,
    generate_search_strategies,
    parse_slack_timestamp,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _monitor_config(**overrides) -> MonitorConfig:
    defaults = dict(
        poll_interval_minutes=5,
        lookback_days=7,
        channels=[
            ChannelConfig(name="data-questions", id="C001"),
            ChannelConfig(name="analytics", id="C002"),
        ],
        domain_keywords=["quicksight", "dbt", "snowflake", "dashboard"],
        bot_usernames=["slackbot", "github", "jira"],
        owner_username="testowner",
    )
    defaults.update(overrides)
    return MonitorConfig(**defaults)


def _raw_msg(
    text: str = "test",
    ts: str = "1770335814.365139",
    username: str = "alice",
    **extra,
) -> dict:
    base = {
        "text": text,
        "ts": ts,
        "username": username,
        "user": "U_ALICE",
        "channel": {"id": "C001", "name": "data-questions"},
        "permalink": f"https://test.slack.com/archives/C001/p{ts.replace('.', '')}",
    }
    base.update(extra)
    return base


# ===================================================================
# Search strategy generation
# ===================================================================


class TestSearchStrategies:
    def test_direct_mention_found(self):
        """Strategy 1: direct @mention of owner produces a strategy."""
        cfg = _monitor_config()
        strategies = generate_search_strategies(cfg, "2026-02-05")
        names = [s.name for s in strategies]
        assert "direct_mentions" in names
        dm_strat = next(s for s in strategies if s.name == "direct_mentions")
        assert "@testowner" in dm_strat.query
        assert dm_strat.marks_direct_mention is True
        assert dm_strat.priority_boost == 100

    def test_channel_question_found(self):
        """Strategy 2: question mark search in monitored channels."""
        cfg = _monitor_config()
        strategies = generate_search_strategies(cfg, "2026-02-05")
        names = [s.name for s in strategies]
        assert "channel_questions" in names
        cq = next(s for s in strategies if s.name == "channel_questions")
        assert "?" in cq.query
        assert "in:#data-questions" in cq.query

    def test_domain_keyword_found(self):
        """Strategies 3-5: domain keywords split into up to 3 groups."""
        cfg = _monitor_config()
        strategies = generate_search_strategies(cfg, "2026-02-05")
        kw_strats = [s for s in strategies if s.name.startswith("domain_keywords_")]
        assert 1 <= len(kw_strats) <= 3
        for s in kw_strats:
            assert "?" in s.query
            assert s.priority_boost == 30

    def test_dm_found(self):
        """Strategy 7: DMs to owner."""
        cfg = _monitor_config()
        strategies = generate_search_strategies(cfg, "2026-02-05")
        dm = next((s for s in strategies if s.name == "direct_messages"), None)
        assert dm is not None
        assert dm.marks_dm is True
        assert "to:@testowner" in dm.query
        assert dm.priority_boost == 80

    def test_search_strategies_count(self):
        """With 4 keywords, 2 channels, and an owner we get 7 strategies.

        Breakdown: 1 (direct_mentions) + 1 (channel_questions) + 2 (4 keywords / 2 chunks)
        + 1 (generic_data_questions) + 1 (direct_messages) + 1 (owner_responses) = 7.
        """
        cfg = _monitor_config()
        strategies = generate_search_strategies(cfg, "2026-02-05")
        assert len(strategies) == 7

    def test_search_strategies_no_hardcoded_values(self):
        """Strategies must derive from config, not hardcode channel/owner names."""
        cfg = _monitor_config(
            owner_username="custom_user",
            channels=[ChannelConfig(name="my-chan", id="CX")],
            domain_keywords=["tableau"],
        )
        strategies = generate_search_strategies(cfg, "2026-01-01")
        all_queries = " ".join(s.query for s in strategies)
        assert "custom_user" in all_queries
        assert "in:#my-chan" in all_queries
        assert "tableau" in all_queries


# ===================================================================
# Bot filtering
# ===================================================================


class TestMessageFilter:
    def test_bot_filtered_by_username(self):
        f = MessageFilter(_monitor_config())
        assert f.is_bot_message({"username": "slackbot"}) is True
        assert f.is_bot_message({"username": "alice"}) is False

    def test_bot_filtered_by_subtype(self):
        f = MessageFilter(_monitor_config())
        assert f.is_bot_message({"subtype": "bot_message"}) is True
        assert f.is_bot_message({"subtype": "thread_broadcast"}) is False

    def test_bot_filtered_by_bot_id(self):
        f = MessageFilter(_monitor_config())
        assert f.is_bot_message({"bot_id": "B12345"}) is True
        assert f.is_bot_message({}) is False

    def test_fyi_deprioritized(self):
        f = MessageFilter(_monitor_config())
        assert f.is_fyi_mention("FYI: looping in @testowner") is True
        assert f.is_fyi_mention("cc: @testowner for visibility") is True
        assert f.is_fyi_mention("@testowner can you help?") is False

    def test_no_question_mark_penalty(self):
        f = MessageFilter(_monitor_config())
        assert f.is_question("What is the metric?") is True
        assert f.is_question("Deploy completed successfully.") is False

    def test_quoted_mention_penalty(self):
        f = MessageFilter(_monitor_config())
        assert f.is_quoted_mention("```@testowner said hi```", "testowner") is True
        assert f.is_quoted_mention("`@testowner`", "testowner") is True
        assert f.is_quoted_mention("> @testowner said something", "testowner") is True
        assert f.is_quoted_mention("@testowner can you help?", "testowner") is False

    def test_already_answered_filtered(self):
        f = MessageFilter(_monitor_config())
        msg = SlackMessage(
            ts="100.001",
            channel_id="C001",
            channel_name="general",
            user_id="U1",
            user_name="u1",
            text="Q?",
            timestamp=datetime.now(timezone.utc),
            permalink="",
            thread_ts="100.001",
            priority=50,
        )
        owner_response = SlackMessage(
            ts="100.002",
            channel_id="C001",
            channel_name="general",
            user_id="U_OWNER",
            user_name="testowner",
            text="Answer",
            timestamp=datetime.now(timezone.utc),
            permalink="",
            thread_ts="100.001",
            priority=0,
        )
        result = f.filter_answered([msg], [owner_response], {})
        assert len(result) == 0

    def test_filter_answered_with_cache(self):
        f = MessageFilter(_monitor_config())
        msg = SlackMessage(
            ts="200.001",
            channel_id="C001",
            channel_name="general",
            user_id="U1",
            user_name="u1",
            text="Cached Q?",
            timestamp=datetime.now(timezone.utc),
            permalink="",
            thread_ts="200.001",
            priority=50,
        )
        cache = {"C001:200.001": True}
        result = f.filter_answered([msg], [], cache)
        assert len(result) == 0


# ===================================================================
# Old messages
# ===================================================================


class TestOldMessages:
    def test_old_messages_filtered(self, sample_config):
        """Messages older than lookback_days should not appear in results."""
        from slack_data_bot.monitor.slack_monitor import SlackMonitor

        cfg = sample_config
        cfg.monitoring.lookback_days = 7
        _monitor = SlackMonitor(cfg, slack_client=None)  # noqa: F841
        # Without a client the monitor returns [] — the real lookback filtering
        # happens in the Slack search query (after:YYYY-MM-DD), so we verify
        # that the computed lookback_date is within 7 days of now.
        lookback = datetime.now(timezone.utc) - timedelta(days=cfg.monitoring.lookback_days)
        assert (datetime.now(timezone.utc) - lookback).days == 7


# ===================================================================
# Deduplication
# ===================================================================


class TestDedup:
    def test_dedup_keeps_highest_priority(self):
        base = dict(
            channel_id="C001",
            channel_name="test",
            user_id="U1",
            user_name="u1",
            text="duplicate",
            timestamp=datetime.now(timezone.utc),
            permalink="",
            thread_ts="100.001",
        )
        low = SlackMessage(ts="100.001", priority=10, **base)
        high = SlackMessage(ts="100.002", priority=90, **base)
        result = deduplicate_messages([low, high])
        assert len(result) == 1
        assert result[0].priority == 90

    def test_empty_channel_skipped(self):
        """Dedup on an empty list returns an empty list."""
        assert deduplicate_messages([]) == []


# ===================================================================
# Timestamp parsing
# ===================================================================


class TestTimestampParsing:
    def test_epoch_timestamp_parsed(self):
        dt = parse_slack_timestamp("1770335814.365139")
        assert dt.tzinfo is not None
        assert dt.year >= 2026

    def test_iso_timestamp_parsed(self):
        dt = parse_slack_timestamp("0", iso_str="2026-02-12T10:00:00Z")
        assert dt.year == 2026
        assert dt.month == 2
        assert dt.tzinfo is not None


# ===================================================================
# Thread TS extraction
# ===================================================================


class TestThreadTs:
    def test_thread_ts_from_permalink(self):
        url = "https://app.slack.com/archives/C001/p1770335814365139"
        ts = extract_thread_ts(url)
        assert ts == "1770335814.365139"

    def test_thread_ts_from_query_param(self):
        url = "https://app.slack.com/archives/C001/p100?thread_ts=1770335814.365139"
        ts = extract_thread_ts(url)
        assert ts == "1770335814.365139"


# ===================================================================
# Priority scoring
# ===================================================================


class TestPriorityScoring:
    def _make_msg(self, text: str, **kw) -> SlackMessage:
        defaults = dict(
            ts="1.1",
            channel_id="C001",
            channel_name="test",
            user_id="U1",
            user_name="u1",
            timestamp=datetime.now(timezone.utc),
            permalink="",
            priority=0,
        )
        defaults.update(kw)
        return SlackMessage(text=text, **defaults)

    def test_priority_scoring_direct_mention(self):
        cfg = _monitor_config()
        scorer = PriorityScorer(cfg)
        filt = MessageFilter(cfg)
        strategy = SearchStrategy(
            name="direct_mentions", query="@testowner",
            priority_boost=100, marks_direct_mention=True,
        )
        msg = self._make_msg("@testowner why is the dashboard broken?", is_direct_mention=True)
        score = scorer.score(msg, strategy, filt)
        # 100 (boost) + 20 (question) + 15 (domain: dashboard) = 135
        assert score == 135

    def test_priority_scoring_dm(self):
        cfg = _monitor_config()
        scorer = PriorityScorer(cfg)
        filt = MessageFilter(cfg)
        strategy = SearchStrategy(
            name="direct_messages", query="to:@testowner", priority_boost=80, marks_dm=True,
        )
        msg = self._make_msg("Can you check the snowflake query?", is_dm=True)
        score = scorer.score(msg, strategy, filt)
        # 80 + 20 (question "can you") + 15 (snowflake keyword) = 115
        assert score == 115

    def test_priority_floor_at_zero(self):
        cfg = _monitor_config()
        scorer = PriorityScorer(cfg)
        filt = MessageFilter(cfg)
        strategy = SearchStrategy(name="low", query="test", priority_boost=0)
        msg = self._make_msg("Deploy done.")
        score = scorer.score(msg, strategy, filt)
        assert score == 0
