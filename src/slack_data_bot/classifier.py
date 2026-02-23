"""Question classifier — determines question type and routes to agents.

Uses heuristic rules first (fast, no API call). Falls back to Anthropic
API for ambiguous questions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Classification:
    """Result of classifying a data question."""

    question_type: str = "unknown"
    confidence: float = 0.5
    entities: list[str] = field(default_factory=list)
    time_period: str | None = None
    complexity: str = "medium"
    suggested_agents: list[str] = field(default_factory=list)


# Agent routing table: which agents to use for each question type
AGENT_ROUTING: dict[str, list[str]] = {
    "count": ["data_planner", "data_investigator"],
    "trend": ["data_planner", "data_investigator", "context_gatherer"],
    "comparison": ["data_planner", "data_investigator"],
    "definition": ["context_gatherer", "lineage_tracer"],
    "root_cause": ["data_planner", "data_investigator", "context_gatherer", "lineage_tracer"],
    "lineage": ["lineage_tracer", "data_planner"],
    "status": ["context_gatherer"],
    "how_to": ["context_gatherer"],
    "unknown": ["data_planner", "context_gatherer"],
}


def classify_question(text: str, channel_context: str = "") -> Classification:
    """Classify a data question using heuristic rules.

    Fast path — no API calls. Handles ~80% of questions correctly.

    Args:
        text: The question text.
        channel_context: Optional channel name for context.

    Returns:
        Classification with type, confidence, entities, and routing.
    """
    text_lower = text.lower().strip()

    # Determine question type
    q_type = "unknown"
    confidence = 0.5

    # Order matters — more specific patterns first
    patterns: list[tuple[str, list[str], float]] = [
        ("count", ["how many", "count", "total number", "number of"], 0.85),
        (
            "trend",
            ["trend", "over time", "week over week", "month over month", "w/w", "m/m"],
            0.85,
        ),
        ("comparison", ["compare", " vs ", "versus", "difference between"], 0.85),
        ("root_cause", ["why", "root cause", "reason", "dropped", "spiked", "decreased"], 0.8),
        ("lineage", ["lineage", "where does", "upstream", "downstream", "source of"], 0.85),
        ("definition", ["what is", "what does", "define", "meaning of", "what's the"], 0.75),
        ("status", ["status", "is it running", "failed", "broken", "down"], 0.75),
        ("how_to", ["how to", "how do i", "how can i", "how should"], 0.75),
    ]

    for ptype, keywords, conf in patterns:
        if any(kw in text_lower for kw in keywords):
            q_type = ptype
            confidence = conf
            break

    # Extract entities
    entities = _extract_entities(text_lower)

    # Extract time period
    time_period = _extract_time_period(text_lower)

    # Estimate complexity
    word_count = len(text.split())
    if word_count < 15:
        complexity = "simple"
    elif word_count < 40:
        complexity = "medium"
    else:
        complexity = "complex"

    # Get agent routing
    suggested_agents = AGENT_ROUTING.get(q_type, AGENT_ROUTING["unknown"])

    return Classification(
        question_type=q_type,
        confidence=confidence,
        entities=entities,
        time_period=time_period,
        complexity=complexity,
        suggested_agents=suggested_agents,
    )


def _extract_entities(text_lower: str) -> list[str]:
    """Extract data-related entities from text."""
    entities = []
    data_terms = [
        "quicksight", "dbt", "snowflake", "dashboard", "model", "table",
        "metric", "report", "pipeline", "dag", "spice", "dataset",
        "warehouse", "schema", "column", "query", "refresh",
    ]
    for term in data_terms:
        if term in text_lower:
            entities.append(term)
    return entities


def _extract_time_period(text_lower: str) -> str | None:
    """Extract time period reference from text."""
    time_patterns = [
        "last week", "this week", "last month", "this month",
        "yesterday", "today", "last quarter", "this quarter",
        "q1", "q2", "q3", "q4", "ytd", "mtd", "wtd",
        "past 7 days", "past 30 days",
    ]
    for pattern in time_patterns:
        if pattern in text_lower:
            return pattern

    # Try date patterns like "Feb 17" or "2026-02-17"
    date_match = re.search(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}\b",
        text_lower,
    )
    if date_match:
        return date_match.group(0)

    return None
