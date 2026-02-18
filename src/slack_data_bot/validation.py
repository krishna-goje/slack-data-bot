"""Configuration validation -- fail fast on invalid settings."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_data_bot.config import BotConfig


class ConfigValidationError(Exception):
    """Raised when configuration validation fails.

    Attributes:
        errors: Individual validation failure messages.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        bullet_list = "\n  - ".join(errors)
        super().__init__(f"Configuration validation failed:\n  - {bullet_list}")


def validate_config(config: BotConfig) -> list[str]:
    """Validate a :class:`BotConfig` and return a list of error strings.

    An empty list means the configuration is valid.  Each entry describes
    a single validation failure so callers can report them all at once
    rather than fixing one-at-a-time.
    """
    errors: list[str] = []

    # -- Slack tokens -------------------------------------------------------
    if config.slack.bot_token and not config.slack.bot_token.startswith("xoxb-"):
        errors.append(
            "slack.bot_token must start with 'xoxb-'"
        )

    if config.slack.app_token and not config.slack.app_token.startswith("xapp-"):
        errors.append(
            "slack.app_token must start with 'xapp-'"
        )

    if config.slack.owner_user_id and not config.slack.owner_user_id.startswith("U"):
        errors.append(
            "slack.owner_user_id must start with 'U' "
            f"(got '{config.slack.owner_user_id[:8]}')"
        )

    # -- Engine -------------------------------------------------------------
    if config.engine.backend == "claude_code" and config.engine.claude_code_path:
        if shutil.which(config.engine.claude_code_path) is None:
            errors.append(
                f"engine.claude_code_path '{config.engine.claude_code_path}' "
                "not found on PATH"
            )

    if config.engine.investigation_timeout <= 0:
        errors.append(
            "engine.investigation_timeout must be > 0 "
            f"(got {config.engine.investigation_timeout})"
        )

    # -- Quality ------------------------------------------------------------
    if config.quality.min_pass_criteria > len(config.quality.criteria):
        errors.append(
            f"quality.min_pass_criteria ({config.quality.min_pass_criteria}) "
            f"exceeds number of criteria ({len(config.quality.criteria)})"
        )

    # -- Cache --------------------------------------------------------------
    if config.cache.answer_ttl_days <= 0:
        errors.append(
            "cache.answer_ttl_days must be > 0 "
            f"(got {config.cache.answer_ttl_days})"
        )

    # -- Monitoring ---------------------------------------------------------
    if config.monitoring.poll_interval_minutes <= 0:
        errors.append(
            "monitoring.poll_interval_minutes must be > 0 "
            f"(got {config.monitoring.poll_interval_minutes})"
        )

    return errors


def validate_config_or_raise(config: BotConfig) -> None:
    """Validate *config* and raise :class:`ConfigValidationError` on failure.

    Call this at startup to fail fast before any work begins.
    """
    errors = validate_config(config)
    if errors:
        raise ConfigValidationError(errors)
