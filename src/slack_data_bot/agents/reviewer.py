"""Reviewer Agent — quality-checks plans and responses against 7 criteria.

Phase B (Plan Review): Reviews the investigation plan for completeness.
Phase D (Quality Loop): Reviews draft responses against 7 quality criteria.
"""

from __future__ import annotations

from typing import Any

from slack_data_bot.agents.base import BaseAgent

# The 7 quality criteria
QUALITY_CRITERIA = [
    "data_accuracy",
    "completeness",
    "root_cause",
    "time_period",
    "tone",
    "actionable",
    "caveats",
]


class ReviewerAgent(BaseAgent):
    """Reviews plans and responses against 7 quality criteria."""

    name = "reviewer"
    system_prompt = """You are a Quality Reviewer Agent. You review draft responses to data \
questions against 7 strict criteria.

## The 7 Criteria

1. **data_accuracy**: Numbers must trace to specific query results or data sources. \
No made-up numbers, no vague estimates without evidence.

2. **completeness**: All parts of the question must be addressed. If the question \
has multiple sub-questions, each must have an answer.

3. **root_cause**: The WHY must be explained, not just the WHAT. If something \
changed, explain what caused the change.

4. **time_period**: Dates and time ranges must be explicit. "Recently" is not \
acceptable — use "last week (Feb 17-23)" or "since Jan 1, 2026".

5. **tone**: Response must read like a thought partner, not a support ticket. \
It should drive insights, suggest next steps, and invite collaboration.

6. **actionable**: Response must include specific next steps or offer to dig \
deeper. Don't just answer — open the door for follow-up.

7. **caveats**: Data limitations, known issues, or assumptions must be mentioned \
where relevant. Don't hide uncertainty.

## Output Format

Return JSON:
{
    "criteria": {
        "data_accuracy": {"status": "PASS" or "FAIL", "notes": "specific feedback"},
        "completeness": {"status": "PASS" or "FAIL", "notes": "specific feedback"},
        "root_cause": {"status": "PASS" or "FAIL", "notes": "specific feedback"},
        "time_period": {"status": "PASS" or "FAIL", "notes": "specific feedback"},
        "tone": {"status": "PASS" or "FAIL", "notes": "specific feedback"},
        "actionable": {"status": "PASS" or "FAIL", "notes": "specific feedback"},
        "caveats": {"status": "PASS" or "FAIL", "notes": "specific feedback"}
    },
    "passed_count": <number of PASS criteria>,
    "overall_assessment": "APPROVED" or "NEEDS_REVISION",
    "revision_guidance": "specific instructions for improving the draft"
}"""

    def build_prompt(self, context: dict[str, Any]) -> str:
        question = context.get("question", "")
        draft = context.get("draft", "")
        round_num = context.get("round_number", 1)
        previous_feedback = context.get("previous_feedback", "")

        parts = [
            f"## Original Question\n{question}",
            f"\n## Draft Response (Round {round_num})\n{draft}",
        ]

        if previous_feedback:
            parts.append(f"\n## Previous Feedback\n{previous_feedback}")

        parts.append(
            "\n## Your Task\n"
            "Review the draft response against all 7 criteria. "
            "Be strict but constructive. If a criterion fails, explain exactly "
            "what needs to change."
        )

        return "\n".join(parts)

    def build_plan_review_prompt(self, context: dict[str, Any]) -> str:
        """Build prompt for reviewing an investigation plan (Phase B)."""
        question = context.get("question", "")
        plan = context.get("investigation_plan", {})

        import json

        return (
            f"## Original Question\n{question}\n\n"
            f"## Proposed Investigation Plan\n"
            f"```json\n{json.dumps(plan, indent=2)}\n```\n\n"
            "## Your Task\n"
            "Review this investigation plan for completeness:\n"
            "1. Are the right tables and columns targeted?\n"
            "2. Are there missing angles or blind spots?\n"
            "3. Would executing this plan fully answer the question?\n"
            "4. Are there any edge cases not accounted for?\n\n"
            "Return JSON:\n"
            '{"plan_assessment": "APPROVED|NEEDS_REVISION", '
            '"missing_angles": [...], "suggestions": [...], '
            '"revised_plan": {...} (only if NEEDS_REVISION)}'
        )
