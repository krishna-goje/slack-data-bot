"""Lineage Tracer Agent — traces data origins and transformations.

Phase A (Planning): Identifies lineage paths to trace.
Phase C (Execute): Traces actual lineage.
"""

from __future__ import annotations

from typing import Any

from slack_data_bot.agents.base import BaseAgent


class LineageTracerAgent(BaseAgent):
    """Traces data origins, transformations, and upstream/downstream dependencies."""

    name = "lineage_tracer"
    system_prompt = """You are a Lineage Tracer Agent. Your job is to trace where data comes \
from and how it's transformed.

You investigate:
1. What is the original source system for this data?
2. What transformations happen between source and the table being asked about?
3. Are there any intermediate tables or views in the path?
4. What is the refresh cadence (how fresh is the data)?
5. Are there any known data quality issues in the lineage?

Return JSON:
{
    "lineage_path": [
        {
            "table": "schema.table_name",
            "role": "source|intermediate|final",
            "transformation": "description of what happens at this step",
            "refresh_cadence": "real-time|hourly|daily|weekly"
        }
    ],
    "original_source": "the ultimate source system (e.g., 'Salesforce', 'web events')",
    "key_transformations": ["list of important business logic transformations"],
    "data_freshness": "description of how current the data is",
    "quality_notes": ["any data quality observations along the lineage"],
    "related_models": ["dbt model names or other relevant models"]
}"""

    def build_prompt(self, context: dict[str, Any]) -> str:
        question = context.get("question", "")
        entities = context.get("entities", [])
        question_type = context.get("question_type", "unknown")
        schema_info = context.get("schema_info", "")

        parts = [
            f"## Question\n{question}",
            f"\n## Question Type: {question_type}",
        ]
        if entities:
            parts.append(f"\n## Entities to Trace\n{', '.join(entities)}")
        if schema_info:
            parts.append(f"\n## Schema Information\n{schema_info}")

        return "\n".join(parts)
