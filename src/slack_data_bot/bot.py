"""Slack Data Bot - main application loop.

Orchestrates monitoring, investigation, delivery, and learning.
Runs as a long-lived process with periodic polling and event handling.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from typing import Any

from slack_data_bot.config import BotConfig, load_config
from slack_data_bot.delivery.approval import ApprovalAction, ApprovalFlow
from slack_data_bot.delivery.notifier import Notifier
from slack_data_bot.engine.investigator import InvestigationEngine
from slack_data_bot.monitor.dedup import SlackMessage

logger = logging.getLogger(__name__)


class SlackDataBot:
    """Main bot orchestrator.

    Coordinates the full lifecycle:
      1. Poll Slack for unanswered questions (via monitor).
      2. Investigate each question (via engine).
      3. Send draft to owner for review (via notifier).
      4. Handle approve/edit/reject buttons (via approval flow).
      5. Track usage and learn from feedback (via learning).
    """

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._running = False
        self._scheduler: Any = None
        self._bolt_app: Any = None

        # Slack client (lazy — only created when tokens are present)
        self._slack_client = self._create_slack_client()

        # Core subsystems
        self.engine = InvestigationEngine(config)
        self.notifier = Notifier(config, slack_client=self._slack_client)
        self.approval = ApprovalFlow(config, slack_client=self._slack_client)

        # Optional subsystems (imported lazily to avoid hard failures)
        self.monitor = self._create_monitor()
        self.state = self._create_state()
        self.tracker = self._create_tracker()

        # Slack Bolt app for interactive messages
        self._setup_bolt_app()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the bot: scheduler for polling + Bolt for interactions."""
        self._running = True
        logger.info("Starting Slack Data Bot")

        # Schedule periodic polling
        self._setup_scheduler()
        if self._scheduler is not None:
            self._scheduler.start()
            logger.info(
                "Scheduler started (poll every %d minutes)",
                self.config.monitoring.poll_interval_minutes,
            )

        # Start Bolt socket-mode listener (blocks if available)
        if self._bolt_app is not None and self.config.slack.app_token:
            try:
                from slack_bolt.adapter.socket_mode import SocketModeHandler
                handler = SocketModeHandler(self._bolt_app, self.config.slack.app_token)
                logger.info("Starting Slack Bolt socket-mode listener")
                handler.start()  # Blocks until stopped
            except ImportError:
                logger.warning("slack_bolt not installed; running in poll-only mode")
            except Exception:
                logger.exception("Bolt socket-mode listener failed")
        else:
            # No Bolt; keep alive via scheduler
            logger.info("Running in poll-only mode (no app_token configured)")
            try:
                if self._scheduler is not None:
                    import threading
                    threading.Event().wait()
            except (KeyboardInterrupt, SystemExit):
                pass

    def stop(self) -> None:
        """Gracefully shut down all subsystems."""
        logger.info("Stopping Slack Data Bot")
        self._running = False

        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                logger.debug("Scheduler already shut down")

        logger.info("Slack Data Bot stopped")

    def run_once(self) -> int:
        """Run a single poll cycle and return the number of questions processed."""
        return self.poll_cycle()

    # ------------------------------------------------------------------
    # Main poll loop
    # ------------------------------------------------------------------

    def poll_cycle(self) -> int:
        """Execute one monitoring + investigation cycle.

        Returns the number of questions processed in this cycle.
        """
        if not self._running and self._scheduler is not None:
            return 0

        logger.info("Starting poll cycle")
        processed = 0

        try:
            # Load answered message cache
            answered_ids: set[str] = set()
            if self.state is not None:
                answered_ids = self.state.load_answered_ids()

            # Find unanswered questions
            if self.monitor is None:
                logger.warning("No monitor configured; skipping poll cycle")
                return 0

            questions: list[SlackMessage] = self.monitor.find_unanswered(answered_ids)
            if not questions:
                logger.info("No unanswered questions found")
                return 0

            logger.info("Found %d unanswered questions", len(questions))

            # Process up to max_concurrent questions
            limit = self.config.engine.max_concurrent
            for question in questions[:limit]:
                try:
                    self._process_question(question)
                    processed += 1
                except Exception:
                    logger.exception(
                        "Failed to process question %s", question.message_id,
                    )

            # Persist state
            if self.state is not None:
                self.state.save()

        except Exception:
            logger.exception("Poll cycle failed")

        logger.info("Poll cycle complete: processed %d questions", processed)
        return processed

    # ------------------------------------------------------------------
    # Question processing
    # ------------------------------------------------------------------

    def _process_question(self, question: SlackMessage) -> None:
        """Investigate a single question and send for human review."""
        logger.info(
            "Investigating: [#%s] %s — %s",
            question.channel_name,
            question.user_name,
            question.text[:80],
        )

        result = self.engine.investigate(question)

        if result.quality_score == 0 and not result.draft:
            self.notifier.notify_error(question, "Investigation produced no results.")
            return

        # Send draft to owner for review
        self.notifier.notify_human(
            message=question,
            draft=result.draft,
            quality_score=result.quality_score,
            quality_total=result.quality_total,
        )

        # Register pending approval
        self.approval.submit_for_approval(question, result.draft)

        # Track usage
        if self.tracker is not None:
            self.tracker.record_investigation(question, result)

    # ------------------------------------------------------------------
    # Slack Bolt interaction handlers
    # ------------------------------------------------------------------

    def _handle_approval_action(self, ack: Any, body: dict, action: dict) -> None:
        """Handle approve/edit/reject button clicks from Slack."""
        ack()

        action_id = action.get("action_id", "")
        approval_key = action.get("value", "")
        user_id = body.get("user", {}).get("id", "")

        pending = self.approval.get_pending(approval_key)
        if pending is None:
            logger.warning("No pending approval found for key %s", approval_key)
            return

        decision = self.approval.handle_action(action_id, approval_key, user_id)

        if decision == ApprovalAction.APPROVE:
            self._on_approval(pending.message, pending.draft)
        elif decision == ApprovalAction.REJECT:
            self._on_rejection(pending.message, pending.draft, feedback="Rejected by reviewer")
        elif decision == ApprovalAction.EDIT:
            # Edit flow: human will modify the draft manually.
            logger.info("Edit requested for %s; awaiting manual follow-up", approval_key)

        # Clean up pending state
        self.approval.remove_pending(approval_key)

    def _on_approval(self, message: SlackMessage, draft: str) -> None:
        """Post the approved draft and record success."""
        self.approval.post_approved_response(message, draft)

        if self.state is not None:
            self.state.mark_answered(message.message_id)

        if self.tracker is not None:
            self.tracker.record_approval(message)

        logger.info("Approved and posted response for %s", message.message_id)

    def _on_rejection(self, message: SlackMessage, draft: str, feedback: str) -> None:
        """Record the rejection for learning."""
        if self.tracker is not None:
            self.tracker.record_rejection(message, feedback)

        logger.info("Rejected response for %s: %s", message.message_id, feedback)

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _create_slack_client(self) -> Any:
        """Create a Slack WebClient if a bot token is configured."""
        if not self.config.slack.bot_token:
            return None
        try:
            from slack_sdk import WebClient
            return WebClient(token=self.config.slack.bot_token)
        except ImportError:
            logger.warning("slack_sdk not installed; Slack integration disabled")
            return None

    def _create_monitor(self) -> Any:
        """Create the Slack monitor if configured."""
        try:
            from slack_data_bot.monitor import SlackMonitor  # type: ignore[attr-defined]
            return SlackMonitor(self.config, slack_client=self._slack_client)
        except (ImportError, AttributeError):
            logger.debug("SlackMonitor not available yet; polling disabled")
            return None

    def _create_state(self) -> Any:
        """Create the bot state manager."""
        try:
            from slack_data_bot.cache import BotState
            return BotState(self.config.cache)
        except (ImportError, AttributeError):
            logger.debug("BotState not available yet; state persistence disabled")
            return None

    def _create_tracker(self) -> Any:
        """Create the usage tracker."""
        try:
            from slack_data_bot.learning import UsageTracker
            return UsageTracker(self.config.learning)
        except (ImportError, AttributeError):
            logger.debug("UsageTracker not available yet; usage tracking disabled")
            return None

    def _setup_bolt_app(self) -> None:
        """Configure Slack Bolt app for interactive message handling."""
        if not self.config.slack.bot_token or not self.config.slack.signing_secret:
            return

        try:
            from slack_bolt import App
            self._bolt_app = App(
                token=self.config.slack.bot_token,
                signing_secret=self.config.slack.signing_secret,
            )
            # Register action handlers for all three buttons
            for action_id in ("approve", "edit", "reject"):
                self._bolt_app.action(action_id)(self._handle_approval_action)

            logger.info("Slack Bolt app initialized with action handlers")
        except ImportError:
            logger.warning("slack_bolt not installed; interactive messages disabled")

    def _setup_scheduler(self) -> None:
        """Configure APScheduler for periodic polling."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self._scheduler = BackgroundScheduler()
            self._scheduler.add_job(
                self.poll_cycle,
                "interval",
                minutes=self.config.monitoring.poll_interval_minutes,
                id="poll_cycle",
                max_instances=1,
            )
        except ImportError:
            logger.warning("apscheduler not installed; scheduled polling disabled")


# ======================================================================
# CLI entry point
# ======================================================================


def main() -> None:
    """Command-line entry point for the Slack Data Bot."""
    parser = argparse.ArgumentParser(
        description="Slack Data Bot - Autonomous assistant for data questions",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to config YAML file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and exit",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll cycle and exit",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load configuration
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    logger.info("Configuration loaded successfully")

    if args.dry_run:
        logger.info("Dry run complete - configuration is valid")
        sys.exit(0)

    # Create and run bot
    bot = SlackDataBot(config)

    # Graceful shutdown on signals
    def _shutdown(signum: int, _frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, shutting down...", sig_name)
        bot.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if args.once:
        count = bot.run_once()
        logger.info("Single cycle complete: %d questions processed", count)
        sys.exit(0)

    bot.start()


if __name__ == "__main__":
    main()
