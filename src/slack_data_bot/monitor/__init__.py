"""Monitor module - Slack monitoring, search, filtering, and prioritization."""

from slack_data_bot.monitor.dedup import SlackMessage, deduplicate_messages
from slack_data_bot.monitor.filter import MessageFilter
from slack_data_bot.monitor.priority import PriorityScorer
from slack_data_bot.monitor.search import SearchStrategy, generate_search_strategies
from slack_data_bot.monitor.slack_monitor import SlackMonitor

__all__ = [
    "SlackMessage",
    "deduplicate_messages",
    "SearchStrategy",
    "generate_search_strategies",
    "MessageFilter",
    "PriorityScorer",
    "SlackMonitor",
]
