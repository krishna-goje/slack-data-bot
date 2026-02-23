"""Data Investigator Agent — executes planned queries and analyzes results.

Phase C (Execute): Takes the investigation plan from Phase A/B and
executes queries, analyzes the results, and produces findings.
"""

from __future__ import annotations

from typing import Any

from slack_data_bot.agents.base import BaseAgent


class DataInvestigatorAgent(BaseAgent):
    """Executes the investigation plan and analyzes data results."""

    name = "data_investigator"
    system_prompt = """You are a Data Investigator Agent. Your job is to analyze data and \
produce findings that answer the question.

You receive an investigation plan and any available data. Your responsibilities:
1. Analyze the data evidence provided
2. Calculate relevant metrics (counts, percentages, trends)
3. Identify anomalies or unexpected patterns
4. Draw conclusions supported by the data
5. Flag any data quality issues or caveats

Be specific with numbers. Never speculate without data evidence.
If data is insufficient, say exactly what additional data would be needed.

Return JSON:
{
    "key_findings": [
        {
            "finding": "specific data-backed finding",
            "evidence": "the number or data point supporting this",
            "confidence": "high|medium|low"
        }
    ],
    "metrics": {
        "metric_name": "metric_value (with units and time period)"
    },
    "anomalies": ["list of unexpected patterns or outliers"],
    "data_quality_issues": ["any issues found with the data"],
    "additional_data_needed": ["what else would strengthen the answer"],
    "analysis_summary": "2-3 sentence summary of what the data shows"
}"""

    def build_prompt(self, context: dict[str, Any]) -> str:
        question = context.get("question", "")
        plan = context.get("investigation_plan", {})
        entities = context.get("entities", [])
        schema_info = context.get("schema_info", "")

        parts = [
            f"## Question\n{question}",
        ]

        if plan:
            import json

            parts.append(f"\n## Investigation Plan\n```json\n{json.dumps(plan, indent=2)}\n```")

        if entities:
            parts.append(f"\n## Key Entities\n{', '.join(entities)}")
        if schema_info:
            parts.append(f"\n## Schema Information\n{schema_info}")

        parts.append(
            "\n## Instructions\n"
            "Based on the investigation plan and available information, "
            "analyze the data and produce your findings. "
            "Be specific with numbers and cite your evidence."
        )

        return "\n".join(parts)
