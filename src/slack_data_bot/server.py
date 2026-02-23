"""FastMCP server for Slack Data Bot.

Exposes 6 tools and 3 resources for monitoring Slack data questions,
investigating them with parallel AI agents, and drafting polished responses.

Tools:
    1. monitor_mentions — 8-strategy search → filter → dedup → prioritized queue
    2. get_thread_context — Full thread + replies for a message
    3. classify_question — Question type + entity extraction
    4. investigate_question — Full pipeline: agents → quality loop → polished response
    5. draft_response — Format pre-gathered findings (no investigation)
    6. mark_answered — Update cache to prevent re-surfacing

Resources:
    - slack://mentions/unanswered — Current unanswered mentions
    - slack://mentions/recent — Recent mentions (answered + unanswered)
    - slack://config — Current server configuration
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from slack_data_bot.cache.state import BotState
from slack_data_bot.config import BotConfig, load_config
from slack_data_bot.models import (
    ClassifyQuestionInput,
    ClassifyQuestionOutput,
    DraftResponseInput,
    DraftResponseOutput,
    GetThreadContextInput,
    GetThreadContextOutput,
    InvestigateQuestionInput,
    InvestigateQuestionOutput,
    MarkAnsweredInput,
    MarkAnsweredOutput,
    MonitorMentionsInput,
    MonitorMentionsOutput,
    QuestionType,
    SlackMessageInfo,
    ThreadReply,
)
from slack_data_bot.monitor.slack_monitor import SlackMonitor
from slack_data_bot.slack_client import SlackApiClient

logger = logging.getLogger(__name__)

# Initialize the MCP server
mcp = FastMCP("slack_data_bot")

# Module-level state (initialized on startup)
_config: BotConfig | None = None
_state: BotState | None = None


def _get_config() -> BotConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _get_state() -> BotState:
    global _state
    if _state is None:
        _state = BotState(_get_config().cache)
    return _state


# ---------------------------------------------------------------------------
# Tool 1: monitor_mentions
# ---------------------------------------------------------------------------


@mcp.tool(
    name="monitor_mentions",
    annotations={
        "title": "Monitor Slack Mentions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def monitor_mentions(
    lookback_days: int = 7,
    max_results: int = 20,
) -> str:
    """Find unanswered @mentions and data questions across Slack.

    Uses 8 complementary search strategies to find messages that need
    a response: direct @mentions, channel questions, domain keywords,
    DMs, and more. Filters out bots, FYI mentions, and already-answered
    threads. Returns results prioritized by urgency.

    Args:
        lookback_days: How many days back to search (1-90, default 7)
        max_results: Maximum number of results to return (1-100, default 20)
    """
    params = MonitorMentionsInput(lookback_days=lookback_days, max_results=max_results)
    config = _get_config()
    state = _get_state()

    if not config.slack.bot_token:
        return json.dumps({"error": "No Slack bot token configured"})

    async with SlackApiClient(token=config.slack.bot_token) as client:
        # Override lookback days from params
        config.monitoring.lookback_days = params.lookback_days

        monitor = SlackMonitor(config=config, slack_client=client)
        answered_cache = await state.aget_answered_cache()
        messages = await monitor.find_unanswered(answered_cache=answered_cache)

    # Convert to output model
    message_infos = [
        SlackMessageInfo(
            ts=msg.ts,
            channel_id=msg.channel_id,
            channel_name=msg.channel_name,
            user_id=msg.user_id,
            user_name=msg.user_name,
            text=msg.text[:500],
            permalink=msg.permalink,
            thread_ts=msg.thread_ts,
            is_direct_mention=msg.is_direct_mention,
            is_dm=msg.is_dm,
            priority=msg.priority,
            relative_time=msg.relative_time,
            reply_count=msg.reply_count,
        )
        for msg in messages[: params.max_results]
    ]

    output = MonitorMentionsOutput(
        messages=message_infos,
        total_found=len(messages),
        total_filtered=len(message_infos),
        strategies_used=8,
    )
    return output.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# Tool 2: get_thread_context
# ---------------------------------------------------------------------------


@mcp.tool(
    name="get_thread_context",
    annotations={
        "title": "Get Thread Context",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_thread_context(
    channel_id: str,
    thread_ts: str,
    include_reactions: bool = False,
) -> str:
    """Get the full thread context for a Slack message.

    Retrieves the parent message and all replies in a thread.
    Useful for understanding the full conversation before investigating
    a data question.

    Args:
        channel_id: Slack channel ID containing the thread
        thread_ts: Thread parent timestamp
        include_reactions: Whether to include reaction data (default False)
    """
    params = GetThreadContextInput(
        channel_id=channel_id,
        thread_ts=thread_ts,
        include_reactions=include_reactions,
    )
    config = _get_config()

    if not config.slack.bot_token:
        return json.dumps({"error": "No Slack bot token configured"})

    async with SlackApiClient(token=config.slack.bot_token) as client:
        response = await client.get_thread_replies(
            channel=params.channel_id,
            ts=params.thread_ts,
        )

    messages = response.get("messages", [])
    parent = messages[0] if messages else {}
    replies = messages[1:] if len(messages) > 1 else []

    # Count unique participants
    participants = {m.get("user", "") for m in messages if m.get("user")}

    thread_replies = [
        ThreadReply(
            user_id=r.get("user", ""),
            user_name=r.get("username", ""),
            text=r.get("text", ""),
            ts=r.get("ts", ""),
            is_bot=bool(r.get("bot_id")),
        )
        for r in replies
    ]

    output = GetThreadContextOutput(
        channel_id=params.channel_id,
        thread_ts=params.thread_ts,
        parent_message=parent.get("text", ""),
        parent_user=parent.get("user", ""),
        replies=thread_replies,
        reply_count=len(replies),
        participant_count=len(participants),
    )
    return output.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# Tool 3: classify_question
# ---------------------------------------------------------------------------


@mcp.tool(
    name="classify_question",
    annotations={
        "title": "Classify Data Question",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def classify_question(
    text: str,
    channel_context: str = "",
) -> str:
    """Classify a data question by type and extract entities.

    Uses heuristic rules to determine the question type (count, trend,
    comparison, definition, root_cause, lineage, etc.) and extract
    relevant entities like table names, metric names, and time periods.

    Args:
        text: The question text to classify
        channel_context: Optional channel name for additional context
    """
    params = ClassifyQuestionInput(text=text, channel_context=channel_context)

    # Heuristic classification (fast, no API call needed)
    text_lower = params.text.lower()

    question_type = QuestionType.UNKNOWN
    confidence = 0.5

    # Pattern matching for question types
    if any(w in text_lower for w in ["how many", "count", "total", "number of"]):
        question_type = QuestionType.COUNT
        confidence = 0.8
    elif any(w in text_lower for w in ["trend", "over time", "week over week", "month over month"]):
        question_type = QuestionType.TREND
        confidence = 0.8
    elif any(w in text_lower for w in ["compare", "vs", "versus", "difference between"]):
        question_type = QuestionType.COMPARISON
        confidence = 0.8
    elif any(w in text_lower for w in ["what is", "what does", "define", "meaning of"]):
        question_type = QuestionType.DEFINITION
        confidence = 0.7
    elif any(w in text_lower for w in ["why", "root cause", "reason", "dropped", "spiked"]):
        question_type = QuestionType.ROOT_CAUSE
        confidence = 0.7
    elif any(
        w in text_lower for w in ["lineage", "where does", "source", "upstream", "downstream"]
    ):
        question_type = QuestionType.LINEAGE
        confidence = 0.8
    elif any(w in text_lower for w in ["status", "is it running", "failed", "broken"]):
        question_type = QuestionType.STATUS
        confidence = 0.7
    elif any(w in text_lower for w in ["how to", "how do i", "how can i"]):
        question_type = QuestionType.HOW_TO
        confidence = 0.7

    # Extract potential entities (simple heuristic)
    entities: list[str] = []
    # Look for common data terms
    data_terms = [
        "quicksight", "dbt", "snowflake", "dashboard", "model", "table",
        "metric", "report", "pipeline", "dag", "spice", "dataset",
    ]
    for term in data_terms:
        if term in text_lower:
            entities.append(term)

    # Time period extraction
    time_period = None
    time_patterns = [
        "last week", "this week", "last month", "this month",
        "yesterday", "today", "last quarter", "this quarter",
        "q1", "q2", "q3", "q4", "ytd", "mtd", "wtd",
    ]
    for pattern in time_patterns:
        if pattern in text_lower:
            time_period = pattern
            break

    # Complexity estimation
    word_count = len(params.text.split())
    if word_count < 15:
        complexity = "simple"
    elif word_count < 40:
        complexity = "medium"
    else:
        complexity = "complex"

    output = ClassifyQuestionOutput(
        question_type=question_type,
        confidence=confidence,
        entities=entities,
        time_period=time_period,
        suggested_tables=[],
        complexity=complexity,
    )
    return output.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# Tool 4: investigate_question (stub for Sprint 1, full impl in Sprint 2)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="investigate_question",
    annotations={
        "title": "Investigate Data Question",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def investigate_question(
    question: str,
    thread_context: str = "",
    questioner_name: str = "",
    questioner_role: str = "",
    channel_name: str = "",
    max_agent_rounds: int = 3,
) -> str:
    """Investigate a data question using parallel specialist agents.

    Runs the full investigation pipeline:
    1. Plan: Parallel agents design investigation strategy
    2. Review: Reviewer agent validates the plan
    3. Execute: All planned queries/searches run in parallel
    4. Quality: Writer/Reviewer loop until quality threshold met

    Returns a copy-paste ready Slack response.

    NOTE: Full agent orchestration is implemented in Sprint 2.
    This Sprint 1 version returns a placeholder.

    Args:
        question: The data question to investigate
        thread_context: Optional thread context (prior messages)
        questioner_name: Name of the person asking (for tone calibration)
        questioner_role: Role/title of the questioner
        channel_name: Channel where the question was asked
        max_agent_rounds: Maximum quality review rounds (1-5, default 3)
    """
    params = InvestigateQuestionInput(
        question=question,
        thread_context=thread_context,
        questioner_name=questioner_name,
        questioner_role=questioner_role,
        channel_name=channel_name,
        max_agent_rounds=max_agent_rounds,
    )

    # Sprint 1 stub - full agent orchestration comes in Sprint 2
    output = InvestigateQuestionOutput(
        response=(
            f"*Investigation pending (Sprint 2)*\n\n"
            f"Question: {params.question}\n"
            f"Agent orchestration will be implemented in Sprint 2.\n"
            f"Use `classify_question` and `draft_response` for now."
        ),
        question_type=QuestionType.UNKNOWN,
        findings=[],
        quality_score=0,
        quality_total=7,
        review_rounds=0,
        agents_used=[],
    )
    return output.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# Tool 5: draft_response (stub for Sprint 1, full impl in Sprint 3)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="draft_response",
    annotations={
        "title": "Draft Response",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def draft_response(
    question: str,
    findings: str,
    tone: str = "thought_partner",
    format: str = "slack_mrkdwn",
) -> str:
    """Format pre-gathered findings into a polished response.

    Takes raw findings (from manual investigation or other tools)
    and formats them into a copy-paste ready Slack response using
    the Writer/Reviewer quality loop.

    NOTE: Full writer/reviewer loop is implemented in Sprint 3.
    This Sprint 1 version returns findings with basic formatting.

    Args:
        question: The original question
        findings: Pre-gathered findings to format
        tone: Response tone (thought_partner, concise, detailed, casual)
        format: Output format (slack_mrkdwn, plain_text, markdown)
    """
    params = DraftResponseInput(
        question=question,
        findings=findings,
        tone=tone,
        format=format,
    )

    # Sprint 1 basic formatting (full writer/reviewer in Sprint 3)
    response = (
        f"*Re: {params.question}*\n\n"
        f"{params.findings}\n\n"
        f"_Draft generated with basic formatting. "
        f"Full Writer/Reviewer loop coming in Sprint 3._"
    )

    output = DraftResponseOutput(
        response=response,
        format=params.format,
        quality_score=0,
        quality_total=7,
        review_rounds=0,
    )
    return output.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# Tool 6: mark_answered
# ---------------------------------------------------------------------------


@mcp.tool(
    name="mark_answered",
    annotations={
        "title": "Mark as Answered",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mark_answered(
    channel_id: str,
    message_ts: str,
    summary: str = "",
) -> str:
    """Mark a message as answered to prevent re-surfacing.

    Updates the answer cache so that future monitor_mentions calls
    will not return this message. The summary is stored for reference.

    Args:
        channel_id: Slack channel ID
        message_ts: Message timestamp to mark as answered
        summary: Brief summary of the answer provided
    """
    params = MarkAnsweredInput(
        channel_id=channel_id,
        message_ts=message_ts,
        summary=summary,
    )
    state = _get_state()

    await state.amark_answered(
        message_ts=params.message_ts,
        channel_id=params.channel_id,
        summary=params.summary,
    )

    thread_key = f"{params.channel_id}:{params.message_ts}"
    output = MarkAnsweredOutput(
        success=True,
        message=f"Marked {thread_key} as answered",
        thread_key=thread_key,
    )
    return output.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("slack://mentions/unanswered")
async def get_unanswered_mentions() -> str:
    """Current unanswered mentions (cached from last monitor_mentions run)."""
    state = _get_state()
    queue = state.get_queue()
    return json.dumps({"unanswered": queue, "count": len(queue)}, indent=2)


@mcp.resource("slack://mentions/recent")
async def get_recent_mentions() -> str:
    """Recent mentions including both answered and unanswered."""
    state = _get_state()
    full_state = state.load()
    return json.dumps(
        {
            "answered": full_state.get("answered", {}),
            "queue": full_state.get("queue", []),
            "stats": full_state.get("stats", {}),
        },
        indent=2,
    )


@mcp.resource("slack://config")
async def get_config() -> str:
    """Current server configuration (sensitive values redacted)."""
    config = _get_config()
    return json.dumps(
        {
            "monitoring": {
                "lookback_days": config.monitoring.lookback_days,
                "channels": [
                    {"name": ch.name, "id": ch.id} for ch in config.monitoring.channels
                ],
                "owner_username": config.monitoring.owner_username,
                "domain_keywords": config.monitoring.domain_keywords,
            },
            "anthropic": {
                "model": config.anthropic.model,
                "thinking": config.anthropic.thinking,
                "max_concurrent_agents": config.anthropic.max_concurrent_agents,
            },
            "quality": {
                "max_rounds": config.quality.max_rounds,
                "min_pass_criteria": config.quality.min_pass_criteria,
                "criteria": config.quality.criteria,
            },
            "cache": {
                "directory": config.cache.directory,
                "answer_ttl_days": config.cache.answer_ttl_days,
            },
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server via stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
