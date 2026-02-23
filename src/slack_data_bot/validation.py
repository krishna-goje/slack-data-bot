"""Configuration validation -- fail fast on invalid settings."""

from __future__ import annotations

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

    An empty list means the configuration is valid.
    """
    errors: list[str] = []

    # -- Slack tokens -------------------------------------------------------
    if config.slack.bot_token and not config.slack.bot_token.startswith("xoxb-"):
        errors.append("slack.bot_token must start with 'xoxb-'")

    if config.slack.owner_user_id and not config.slack.owner_user_id.startswith("U"):
        errors.append(
            f"slack.owner_user_id must start with 'U' "
            f"(got '{config.slack.owner_user_id[:8]}')"
        )

    # -- Anthropic ----------------------------------------------------------
    if config.anthropic.max_tokens <= 0:
        errors.append(
            f"anthropic.max_tokens must be > 0 (got {config.anthropic.max_tokens})"
        )

    if config.anthropic.timeout_seconds <= 0:
        errors.append(
            f"anthropic.timeout_seconds must be > 0 (got {config.anthropic.timeout_seconds})"
        )

    if config.anthropic.max_concurrent_agents <= 0:
        errors.append(
            f"anthropic.max_concurrent_agents must be > 0 "
            f"(got {config.anthropic.max_concurrent_agents})"
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
            f"cache.answer_ttl_days must be > 0 (got {config.cache.answer_ttl_days})"
        )

    # -- Monitoring ---------------------------------------------------------
    if config.monitoring.poll_interval_minutes <= 0:
        errors.append(
            f"monitoring.poll_interval_minutes must be > 0 "
            f"(got {config.monitoring.poll_interval_minutes})"
        )

    return errors


def validate_config_or_raise(config: BotConfig) -> None:
    """Validate *config* and raise :class:`ConfigValidationError` on failure."""
    errors = validate_config(config)
    if errors:
        raise ConfigValidationError(errors)
