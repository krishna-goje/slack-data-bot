"""Data Planner Agent — designs the query strategy before execution.

Phase A (Planning): Identifies tables, columns, and designs queries
to answer the question. Does NOT execute queries — that's the
Data Investigator's job in Phase C.
"""

from __future__ import annotations

from typing import Any

from slack_data_bot.agents.base import BaseAgent


class DataPlannerAgent(BaseAgent):
    """Designs the investigation strategy: which tables, columns, queries."""

    name = "data_planner"
    system_prompt = """You are a Data Planner Agent. Your job is to design the investigation \
strategy for a data question WITHOUT executing any queries.

Your responsibilities:
1. Identify which tables and columns are likely relevant
2. Design specific SQL queries that would answer the question
3. Identify edge cases and potential data quality issues to check
4. Suggest the order of execution (which queries first)
5. Note any joins, aggregations, or transformations needed

Return JSON:
{
    "relevant_tables": [
        {"table": "schema.table_name", "reason": "why this table", "key_columns": ["col1"]}
    ],
    "planned_queries": [
        {
            "name": "descriptive name",
            "purpose": "what this query answers",
            "sql_sketch": "SELECT ... FROM ... WHERE ... (sketch, not exact)",
            "priority": 1
        }
    ],
    "edge_cases": ["list of things to watch for"],
    "data_quality_checks": ["NULL rates", "duplicates", "date ranges"],
    "estimated_complexity": "simple|medium|complex",
    "notes": "additional planning notes"
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
            parts.append(f"\n## Extracted Entities\n{', '.join(entities)}")
        if schema_info:
            parts.append(f"\n## Available Schema Information\n{schema_info}")

        return "\n".join(parts)
