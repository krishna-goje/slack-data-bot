"""Pydantic v2 input/output models for all MCP tools.

These models define the contract between MCP clients and the server.
All tool inputs are validated via Pydantic before processing.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class QuestionType(str, Enum):
    """Classification of data questions by type."""

    COUNT = "count"
    TREND = "trend"
    COMPARISON = "comparison"
    DEFINITION = "definition"
    ROOT_CAUSE = "root_cause"
    LINEAGE = "lineage"
    STATUS = "status"
    HOW_TO = "how_to"
    UNKNOWN = "unknown"


class Priority(str, Enum):
    """Message urgency levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ---------------------------------------------------------------------------
# Shared models
# ---------------------------------------------------------------------------


class SlackMessageInfo(BaseModel):
    """Serialized Slack message for MCP responses."""

    model_config = ConfigDict(str_strip_whitespace=True)

    ts: str = Field(..., description="Slack message timestamp")
    channel_id: str = Field(..., description="Channel ID")
    channel_name: str = Field(default="", description="Channel name")
    user_id: str = Field(default="", description="Author user ID")
    user_name: str = Field(default="", description="Author username")
    text: str = Field(default="", description="Message text (truncated to 500 chars)")
    permalink: str = Field(default="", description="Slack permalink URL")
    thread_ts: str | None = Field(default=None, description="Thread parent timestamp")
    is_direct_mention: bool = Field(default=False, description="Whether this is a direct @mention")
    is_dm: bool = Field(default=False, description="Whether this is a DM")
    priority: int = Field(default=0, description="Priority score (higher = more urgent)")
    relative_time: str = Field(default="", description="Human-readable time (e.g., '2h ago')")
    reply_count: int = Field(default=0, description="Number of thread replies")


class QualityCriteria(BaseModel):
    """Result of a single quality criterion check."""

    name: str
    passed: bool
    feedback: str = ""


# ---------------------------------------------------------------------------
# Tool 1: monitor_mentions
# ---------------------------------------------------------------------------


class MonitorMentionsInput(BaseModel):
    """Input for the monitor_mentions tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    lookback_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="How many days back to search (1-90)",
    )
    max_results: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of results to return",
    )


class MonitorMentionsOutput(BaseModel):
    """Output from the monitor_mentions tool."""

    messages: list[SlackMessageInfo] = Field(
        default_factory=list,
        description="Prioritized list of unanswered messages",
    )
    total_found: int = Field(default=0, description="Total messages before filtering")
    total_filtered: int = Field(default=0, description="Messages after filtering")
    strategies_used: int = Field(default=0, description="Number of search strategies executed")


# ---------------------------------------------------------------------------
# Tool 2: get_thread_context
# ---------------------------------------------------------------------------


class GetThreadContextInput(BaseModel):
    """Input for the get_thread_context tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    channel_id: str = Field(..., min_length=1, description="Slack channel ID")
    thread_ts: str = Field(..., min_length=1, description="Thread parent timestamp")
    include_reactions: bool = Field(
        default=False,
        description="Whether to include reaction data",
    )


class ThreadReply(BaseModel):
    """A single reply in a thread."""

    user_id: str = ""
    user_name: str = ""
    text: str = ""
    ts: str = ""
    is_bot: bool = False


class GetThreadContextOutput(BaseModel):
    """Output from the get_thread_context tool."""

    channel_id: str
    thread_ts: str
    parent_message: str = Field(default="", description="Original message text")
    parent_user: str = Field(default="", description="Original author")
    replies: list[ThreadReply] = Field(default_factory=list)
    reply_count: int = 0
    participant_count: int = 0


# ---------------------------------------------------------------------------
# Tool 3: classify_question
# ---------------------------------------------------------------------------


class ClassifyQuestionInput(BaseModel):
    """Input for the classify_question tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The question text to classify",
    )
    channel_context: str = Field(
        default="",
        description="Optional channel name for context (e.g., 'ask-data-team')",
    )


class ClassifyQuestionOutput(BaseModel):
    """Output from the classify_question tool."""

    question_type: QuestionType = Field(
        default=QuestionType.UNKNOWN,
        description="Classified question type",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Classification confidence (0-1)",
    )
    entities: list[str] = Field(
        default_factory=list,
        description="Extracted entities (table names, metric names, etc.)",
    )
    time_period: str | None = Field(
        default=None,
        description="Extracted time period reference (e.g., 'last week', 'Q1 2026')",
    )
    suggested_tables: list[str] = Field(
        default_factory=list,
        description="Suggested data tables that might be relevant",
    )
    complexity: str = Field(
        default="medium",
        description="Estimated complexity: simple, medium, complex",
    )


# ---------------------------------------------------------------------------
# Tool 4: investigate_question
# ---------------------------------------------------------------------------


class InvestigateQuestionInput(BaseModel):
    """Input for the investigate_question tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The data question to investigate",
    )
    thread_context: str = Field(
        default="",
        description="Optional thread context (prior messages in the thread)",
    )
    questioner_name: str = Field(
        default="",
        description="Name of the person asking (for tone calibration)",
    )
    questioner_role: str = Field(
        default="",
        description="Role/title of the questioner (for depth calibration)",
    )
    channel_name: str = Field(
        default="",
        description="Channel where the question was asked",
    )
    max_agent_rounds: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum quality review rounds",
    )


class AgentFinding(BaseModel):
    """A finding from one of the specialist agents."""

    agent_name: str = Field(..., description="Which agent produced this finding")
    finding_type: str = Field(
        default="insight",
        description="Type: insight, data_point, context, lineage, caveat",
    )
    content: str = Field(..., description="The finding content")
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Agent confidence in this finding",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Data sources used (table names, Slack threads, etc.)",
    )


class InvestigateQuestionOutput(BaseModel):
    """Output from the investigate_question tool."""

    response: str = Field(
        ...,
        description="Copy-paste ready Slack response (mrkdwn formatted)",
    )
    question_type: QuestionType = Field(default=QuestionType.UNKNOWN)
    findings: list[AgentFinding] = Field(
        default_factory=list,
        description="Raw findings from specialist agents",
    )
    quality_score: int = Field(
        default=0,
        ge=0,
        le=7,
        description="Quality review score (0-7 criteria passed)",
    )
    quality_total: int = Field(default=7)
    review_rounds: int = Field(
        default=0,
        description="How many quality review rounds were needed",
    )
    agents_used: list[str] = Field(
        default_factory=list,
        description="Which specialist agents contributed",
    )


# ---------------------------------------------------------------------------
# Tool 5: draft_response
# ---------------------------------------------------------------------------


class DraftResponseInput(BaseModel):
    """Input for the draft_response tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The original question",
    )
    findings: str = Field(
        ...,
        min_length=1,
        description="Pre-gathered findings to format into a response",
    )
    tone: str = Field(
        default="thought_partner",
        description="Response tone: thought_partner, concise, detailed, casual",
    )
    format: str = Field(
        default="slack_mrkdwn",
        description="Output format: slack_mrkdwn, plain_text, markdown",
    )


class DraftResponseOutput(BaseModel):
    """Output from the draft_response tool."""

    response: str = Field(
        ...,
        description="Formatted response ready for delivery",
    )
    format: str = Field(default="slack_mrkdwn")
    quality_score: int = Field(default=0, ge=0, le=7)
    quality_total: int = Field(default=7)
    review_rounds: int = Field(default=0)


# ---------------------------------------------------------------------------
# Tool 6: mark_answered
# ---------------------------------------------------------------------------


class MarkAnsweredInput(BaseModel):
    """Input for the mark_answered tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    channel_id: str = Field(..., min_length=1, description="Slack channel ID")
    message_ts: str = Field(..., min_length=1, description="Message timestamp to mark")
    summary: str = Field(
        default="",
        description="Brief summary of the answer provided",
    )


class MarkAnsweredOutput(BaseModel):
    """Output from the mark_answered tool."""

    success: bool = Field(default=True)
    message: str = Field(default="Marked as answered")
    thread_key: str = Field(
        default="",
        description="The cache key used (channel_id:message_ts)",
    )
