"""Slack mrkdwn response formatting utilities.

Converts investigation results into copy-paste ready Slack messages.
"""

from __future__ import annotations


def format_monitor_summary(messages: list[dict], total: int) -> str:
    """Format the monitor_mentions output as a readable summary.

    Args:
        messages: List of message dicts from MonitorMentionsOutput.
        total: Total number of messages found before filtering.

    Returns:
        Formatted Slack mrkdwn string.
    """
    if not messages:
        return "*No unanswered mentions found.* All caught up!"

    lines = [f"*{len(messages)} unanswered mentions* (from {total} total)\n"]

    for i, msg in enumerate(messages, 1):
        priority = msg.get("priority", 0)
        urgency = _priority_emoji(priority)
        text = msg.get("text", "")[:80]
        user = msg.get("user_name", "unknown")
        time_ago = msg.get("relative_time", "")
        permalink = msg.get("permalink", "")

        line = f"{urgency} *{i}.* {user} ({time_ago})"
        if permalink:
            line += f" <{permalink}|View>"
        lines.append(line)
        lines.append(f"   _{text}_")

    return "\n".join(lines)


def format_investigation_result(
    response: str,
    quality_score: int,
    quality_total: int,
    agents_used: list[str],
    duration_ms: int,
) -> str:
    """Wrap an investigation response with metadata footer.

    Args:
        response: The main response text.
        quality_score: Number of quality criteria passed.
        quality_total: Total quality criteria.
        agents_used: List of agent names that contributed.
        duration_ms: Total investigation time.

    Returns:
        Response with metadata footer appended.
    """
    footer_parts = [
        f"Quality: {quality_score}/{quality_total}",
        f"Agents: {', '.join(agents_used)}" if agents_used else None,
        f"Time: {duration_ms / 1000:.1f}s" if duration_ms else None,
    ]
    footer = " | ".join(p for p in footer_parts if p)

    return f"{response}\n\n_({footer})_"


def _priority_emoji(priority: int) -> str:
    """Convert priority score to a text indicator."""
    if priority >= 100:
        return "[!!!]"
    if priority >= 70:
        return "[!!]"
    if priority >= 40:
        return "[!]"
    return "[-]"
