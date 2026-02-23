"""Tests for the DataKrait Slack agent (slack_app.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from slack_data_bot.config import BotConfig
from slack_data_bot.slack_app import SUGGESTED_PROMPTS, create_app
from slack_data_bot.thread_context import ChannelContext, ThreadContextStore

# ---------------------------------------------------------------------------
# ThreadContextStore tests
# ---------------------------------------------------------------------------


class TestThreadContextStore:
    def test_set_and_get(self) -> None:
        store = ThreadContextStore()
        ctx = ChannelContext(channel_id="C123", channel_name="general")
        store.set("U001", ctx)
        assert store.get("U001") is ctx

    def test_get_missing_returns_none(self) -> None:
        store = ThreadContextStore()
        assert store.get("U999") is None

    def test_remove(self) -> None:
        store = ThreadContextStore()
        store.set("U001", ChannelContext(channel_id="C123"))
        store.remove("U001")
        assert store.get("U001") is None

    def test_remove_missing_is_noop(self) -> None:
        store = ThreadContextStore()
        store.remove("U999")  # should not raise

    def test_to_dict_with_context(self) -> None:
        store = ThreadContextStore()
        store.set(
            "U001",
            ChannelContext(channel_id="C123", channel_name="data-team", title="Contracts"),
        )
        d = store.to_dict("U001")
        assert d == {
            "channel_id": "C123",
            "channel_name": "data-team",
            "title": "Contracts",
        }

    def test_to_dict_without_context(self) -> None:
        store = ThreadContextStore()
        assert store.to_dict("U999") == {}

    def test_overwrite_context(self) -> None:
        store = ThreadContextStore()
        store.set("U001", ChannelContext(channel_id="C111"))
        store.set("U001", ChannelContext(channel_id="C222"))
        assert store.get("U001").channel_id == "C222"


# ---------------------------------------------------------------------------
# Suggested prompts tests
# ---------------------------------------------------------------------------


class TestSuggestedPrompts:
    def test_has_four_prompts(self) -> None:
        assert len(SUGGESTED_PROMPTS) == 4

    def test_each_prompt_has_title_and_message(self) -> None:
        for prompt in SUGGESTED_PROMPTS:
            assert "title" in prompt
            assert "message" in prompt
            assert len(prompt["title"]) > 0
            assert len(prompt["message"]) > 0


# ---------------------------------------------------------------------------
# create_app tests
# ---------------------------------------------------------------------------


class TestCreateApp:
    @patch("slack_data_bot.slack_app.App")
    def test_create_app_returns_tuple(self, mock_app_cls: MagicMock) -> None:
        """create_app returns (app, config) tuple."""
        mock_app_cls.return_value = MagicMock()
        mock_app_cls.return_value.assistant.return_value = MagicMock()

        config = BotConfig.default()
        config.slack.bot_token = "xoxb-test"
        config.slack.signing_secret = "test-secret"

        app, returned_config = create_app(config)
        assert app is not None
        assert returned_config is config

    @patch("slack_data_bot.slack_app.App")
    def test_create_app_uses_bot_token(self, mock_app_cls: MagicMock) -> None:
        """create_app passes bot token to Slack App."""
        mock_app_cls.return_value = MagicMock()
        mock_app_cls.return_value.assistant.return_value = MagicMock()

        config = BotConfig.default()
        config.slack.bot_token = "xoxb-my-token"

        create_app(config)
        mock_app_cls.assert_called_once()
        call_kwargs = mock_app_cls.call_args[1]
        assert call_kwargs["token"] == "xoxb-my-token"
