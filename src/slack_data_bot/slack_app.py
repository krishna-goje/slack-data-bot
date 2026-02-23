"""DataKrait — Slack agent powered by the slack-data-bot investigation engine.

Receives Slack events via Socket Mode (WebSocket), classifies questions,
runs the full investigation pipeline, and posts polished responses as @datakrait.

Usage:
    export SLACK_BOT_TOKEN="xoxb-..."
    export SLACK_APP_TOKEN="xapp-..."
    export ANTHROPIC_API_KEY="sk-ant-..."
    datakrait
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from typing import Any

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from slack_data_bot.anthropic_client import AnthropicClient
from slack_data_bot.classifier import classify_question
from slack_data_bot.config import BotConfig, load_config
from slack_data_bot.orchestrator import Orchestrator
from slack_data_bot.thread_context import ChannelContext, ThreadContextStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Suggested prompts shown when a user opens DataKrait
# ---------------------------------------------------------------------------

SUGGESTED_PROMPTS = [
    {
        "title": "Unanswered data questions",
        "message": "Show my unanswered data questions from the past week",
    },
    {
        "title": "Why did contracts drop?",
        "message": "Why did contracts drop last week?",
    },
    {
        "title": "Dashboard freshness",
        "message": "Is the WBR dashboard data up to date?",
    },
    {
        "title": "Metric definition",
        "message": "How is repair surplus calculated?",
    },
]


def _build_config() -> BotConfig:
    """Build config with env var overrides for Slack agent mode."""
    config = load_config()

    # Env vars override YAML for secrets
    if token := os.environ.get("SLACK_BOT_TOKEN"):
        config.slack.bot_token = token
    if api_key := os.environ.get("ANTHROPIC_API_KEY"):
        config.anthropic.api_key = api_key
    if app_token := os.environ.get("SLACK_APP_TOKEN"):
        config.slack.app_token = app_token
    if signing := os.environ.get("SLACK_SIGNING_SECRET"):
        config.slack.signing_secret = signing

    return config


def create_app(config: BotConfig | None = None) -> tuple[App, BotConfig]:
    """Create and configure the Slack Bolt app with assistant handlers.

    Returns (app, config) tuple for flexibility in testing.
    """
    if config is None:
        config = _build_config()

    app = App(
        token=config.slack.bot_token,
        # Socket Mode doesn't need signing_secret for verification,
        # but we pass it if available for completeness.
        signing_secret=config.slack.signing_secret or "not-used-in-socket-mode",
    )

    context_store = ThreadContextStore()

    # -----------------------------------------------------------------------
    # Assistant: thread_started — greeting + suggested prompts
    # -----------------------------------------------------------------------

    assistant = app.assistant()

    @assistant.thread_started
    def handle_thread_started(say: Any, set_suggested_prompts: Any) -> None:
        """Send greeting and suggested prompts when user opens DataKrait."""
        say(
            "Hi! I'm DataKrait — your data investigation agent. "
            "Ask me any data question and I'll research it using "
            "dashboards, Snowflake, dbt, and lineage tools.\n\n"
            "What would you like to know?"
        )
        set_suggested_prompts(prompts=SUGGESTED_PROMPTS)

    # -----------------------------------------------------------------------
    # Assistant: context_changed — track which channel user is viewing
    # -----------------------------------------------------------------------

    @assistant.thread_context_changed
    def handle_context_changed(
        payload: dict,
        set_title: Any,
        logger: Any,
    ) -> None:
        """Save channel context when user navigates in Slack."""
        assistant_thread: dict = payload.get("assistant_thread", {})
        context_data: dict = assistant_thread.get("context", {})

        channel_id = context_data.get("channel_id", "")
        channel_name = context_data.get("channel_name", "")
        title = context_data.get("title", "")

        # Extract user from the thread
        user_id = payload.get("user", "")
        if user_id and channel_id:
            context_store.set(
                user_id,
                ChannelContext(
                    channel_id=channel_id,
                    channel_name=channel_name,
                    title=title,
                ),
            )
            logger.info(f"Context updated for {user_id}: #{channel_name}")

    # -----------------------------------------------------------------------
    # Assistant: user_message — classify → investigate → respond
    # -----------------------------------------------------------------------

    @assistant.user_message
    def handle_user_message(
        payload: dict,
        say: Any,
        set_status: Any,
        set_title: Any,
        logger: Any,
    ) -> None:
        """Handle incoming user message: investigate and respond."""
        text = payload.get("text", "").strip()
        user_id = payload.get("user", "")

        if not text:
            say("I didn't catch that. Could you rephrase your question?")
            return

        # Set title to first ~40 chars of the question
        set_title(title=text[:40] + ("..." if len(text) > 40 else ""))

        try:
            # Phase 1: Classify
            set_status(status="Classifying question...")
            classification = classify_question(text)
            logger.info(
                f"Classified as {classification.question_type} "
                f"(confidence={classification.confidence})"
            )

            # Phase 2: Check for Anthropic API key
            if not config.anthropic.api_key:
                say(
                    "I'm not fully configured yet — missing an API key. "
                    "Please ask my admin to set the `ANTHROPIC_API_KEY` environment variable."
                )
                return

            # Phase 3: Investigate
            set_status(status="Investigating...")

            # Build context from stored channel info
            user_ctx = context_store.to_dict(user_id)

            client = AnthropicClient(
                api_key=config.anthropic.api_key,
                model=config.anthropic.model,
                max_tokens=config.anthropic.max_tokens,
                timeout=config.anthropic.timeout_seconds,
            )
            orchestrator = Orchestrator(
                client=client,
                max_quality_rounds=config.quality.max_rounds,
                min_pass_criteria=config.quality.min_pass_criteria,
            )

            context = {
                "channel_name": user_ctx.get("channel_name", ""),
                "thread_context": "",
            }

            # Run async investigation in sync handler
            loop = _get_or_create_event_loop()
            result = loop.run_until_complete(orchestrator.investigate(text, context))

            # Phase 4: Respond
            response = result.response
            if not response:
                response = (
                    "I investigated but couldn't find a clear answer. "
                    "Could you provide more context or rephrase?"
                )

            # Add quality metadata as context block
            quality_note = (
                f"\n\n_Quality: {result.quality_score}/{result.quality_total} "
                f"| Agents: {', '.join(result.agents_used)}_"
            )
            say(response + quality_note)

        except Exception as e:
            logger.error(f"Error handling message: {e}\n{traceback.format_exc()}")
            say(
                f"Something went wrong while investigating your question. "
                f"Error: `{type(e).__name__}: {e}`\n\n"
                f"Please try again or rephrase."
            )

    return app, config


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Get existing event loop or create a new one (for sync Bolt handlers)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def main() -> None:
    """Entry point: start DataKrait in Socket Mode."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = _build_config()

    # Validate required tokens
    if not config.slack.bot_token:
        print("ERROR: SLACK_BOT_TOKEN is required. Set it as an environment variable.")
        sys.exit(1)
    if not config.slack.app_token:
        print(
            "ERROR: SLACK_APP_TOKEN is required for Socket Mode. "
            "Set it as an environment variable."
        )
        sys.exit(1)

    app, config = create_app(config)

    print("=" * 60)
    print("  DataKrait — Slack Data Investigation Agent")
    print("  Connecting via Socket Mode...")
    print("=" * 60)

    handler = SocketModeHandler(app, config.slack.app_token)
    handler.start()


if __name__ == "__main__":
    main()
