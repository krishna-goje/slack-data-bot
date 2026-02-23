"""Configuration management for Slack Data Bot MCP Server.

Loads from YAML file with environment variable expansion.
All values have sensible defaults for quick start.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ${ENV_VAR} references in config values."""
    if isinstance(value, str):
        pattern = re.compile(r"\$\{([^}]+)\}")

        def replacer(match: re.Match) -> str:
            env_key = match.group(1)
            env_val = os.environ.get(env_key)
            if env_val is None:
                raise ValueError(f"Environment variable '{env_key}' not set")
            return env_val

        return pattern.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


@dataclass
class ChannelConfig:
    """A Slack channel to monitor."""

    name: str
    id: str


@dataclass
class SlackConfig:
    """Slack API connection settings (token-only, no bolt)."""

    bot_token: str = ""
    owner_user_id: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> SlackConfig:
        return cls(
            bot_token=data.get("bot_token", ""),
            owner_user_id=data.get("owner_user_id", ""),
        )


@dataclass
class MonitorConfig:
    """Monitoring behavior settings."""

    poll_interval_minutes: int = 5
    lookback_days: int = 7
    channels: list[ChannelConfig] = field(default_factory=list)
    domain_keywords: list[str] = field(
        default_factory=lambda: [
            "quicksight",
            "dbt",
            "snowflake",
            "dashboard",
        ]
    )
    bot_usernames: list[str] = field(
        default_factory=lambda: [
            "slackbot",
            "github",
            "jira",
        ]
    )
    owner_username: str = ""

    _DEFAULT_DOMAIN_KEYWORDS = ["quicksight", "dbt", "snowflake", "dashboard"]
    _DEFAULT_BOT_USERNAMES = ["slackbot", "github", "jira"]

    @classmethod
    def from_dict(cls, data: dict) -> MonitorConfig:
        channels = [
            ChannelConfig(name=ch["name"], id=ch["id"]) for ch in data.get("channels", [])
        ]
        return cls(
            poll_interval_minutes=data.get("poll_interval_minutes", 5),
            lookback_days=data.get("lookback_days", 7),
            channels=channels,
            domain_keywords=data.get("domain_keywords", cls._DEFAULT_DOMAIN_KEYWORDS),
            bot_usernames=data.get("bot_usernames", cls._DEFAULT_BOT_USERNAMES),
            owner_username=data.get("owner_username", ""),
        )


@dataclass
class AnthropicConfig:
    """Anthropic API settings for the agent orchestration layer."""

    api_key: str = ""
    model: str = "claude-opus-4-6-20250219"
    max_tokens: int = 4096
    thinking: str = "adaptive"
    temperature: float = 1.0
    max_concurrent_agents: int = 5
    timeout_seconds: int = 300

    @classmethod
    def from_dict(cls, data: dict) -> AnthropicConfig:
        return cls(
            api_key=data.get("api_key", ""),
            model=data.get("model", "claude-opus-4-6-20250219"),
            max_tokens=data.get("max_tokens", 4096),
            thinking=data.get("thinking", "adaptive"),
            temperature=data.get("temperature", 1.0),
            max_concurrent_agents=data.get("max_concurrent_agents", 5),
            timeout_seconds=data.get("timeout_seconds", 300),
        )


@dataclass
class QualityConfig:
    """Quality review settings."""

    max_rounds: int = 3
    min_pass_criteria: int = 5
    criteria: list[str] = field(
        default_factory=lambda: [
            "data_accuracy",
            "completeness",
            "root_cause",
            "time_period",
            "tone",
            "actionable",
            "caveats",
        ]
    )

    _DEFAULT_CRITERIA = [
        "data_accuracy",
        "completeness",
        "root_cause",
        "time_period",
        "tone",
        "actionable",
        "caveats",
    ]

    @classmethod
    def from_dict(cls, data: dict) -> QualityConfig:
        return cls(
            max_rounds=data.get("max_rounds", 3),
            min_pass_criteria=data.get("min_pass_criteria", 5),
            criteria=data.get("criteria", cls._DEFAULT_CRITERIA),
        )


@dataclass
class CacheConfig:
    """Cache settings."""

    directory: str = "~/.slack-data-bot"
    answer_ttl_days: int = 30

    @classmethod
    def from_dict(cls, data: dict) -> CacheConfig:
        return cls(
            directory=data.get("directory", "~/.slack-data-bot"),
            answer_ttl_days=data.get("answer_ttl_days", 30),
        )

    @property
    def cache_path(self) -> Path:
        return Path(self.directory).expanduser()


@dataclass
class BotConfig:
    """Top-level bot configuration."""

    slack: SlackConfig = field(default_factory=SlackConfig)
    monitoring: MonitorConfig = field(default_factory=MonitorConfig)
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)

    @classmethod
    def from_dict(cls, data: dict) -> BotConfig:
        return cls(
            slack=SlackConfig.from_dict(data.get("slack", {})),
            monitoring=MonitorConfig.from_dict(data.get("monitoring", {})),
            anthropic=AnthropicConfig.from_dict(data.get("anthropic", {})),
            quality=QualityConfig.from_dict(data.get("quality", {})),
            cache=CacheConfig.from_dict(data.get("cache", {})),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> BotConfig:
        """Load config from YAML file with env var expansion."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path) as f:
            raw = yaml.safe_load(f)
        if raw is None:
            raw = {}
        expanded = _expand_env_vars(raw)
        return cls.from_dict(expanded)

    @classmethod
    def default(cls) -> BotConfig:
        """Create config with all defaults."""
        return cls()


def load_config(path: str | Path | None = None) -> BotConfig:
    """Load configuration from file or use defaults.

    Resolution order:
    1. Explicit path argument
    2. SLACK_DATA_BOT_CONFIG environment variable
    3. ./config.yaml
    4. ~/.slack-data-bot/config.yaml
    5. Default values
    """
    if path:
        return BotConfig.from_yaml(path)

    env_path = os.environ.get("SLACK_DATA_BOT_CONFIG")
    if env_path:
        return BotConfig.from_yaml(env_path)

    local_path = Path("config.yaml")
    if local_path.exists():
        return BotConfig.from_yaml(local_path)

    home_path = Path.home() / ".slack-data-bot" / "config.yaml"
    if home_path.exists():
        return BotConfig.from_yaml(home_path)

    return BotConfig.default()
