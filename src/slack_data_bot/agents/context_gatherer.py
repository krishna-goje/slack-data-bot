"""Context Gatherer Agent — finds tribal knowledge, prior discussions, gotchas.

Phase A (Planning): Identifies what contextual information would help.
Phase C (Execute): Gathers the actual context.
"""

from __future__ import annotations

from typing import Any

from slack_data_bot.agents.base import BaseAgent


class ContextGathererAgent(BaseAgent):
    """Finds prior discussions, tribal knowledge, and known gotchas."""

    name = "context_gatherer"
    system_prompt = """You are a Context Gatherer Agent. Your job is to identify and gather \
contextual information that would help answer a data question.

You look for:
1. Has this question been asked before? What was the answer?
2. Are there known gotchas or data quality issues related to this topic?
3. Who are the subject matter experts for this data domain?
4. Are there any recent changes (deployments, schema changes) that might be relevant?
5. What tribal knowledge exists about this data?

Return JSON:
{
    "prior_discussions": [
        {"summary": "brief description", "relevance": "high|medium|low", "source": "where found"}
    ],
    "known_gotchas": ["list of known issues or caveats"],
    "suggested_experts": ["names or roles of people who know this domain"],
    "recent_changes": ["relevant recent changes to data or systems"],
    "search_suggestions": [
        {"query": "Slack search query to find more context", "purpose": "what we'd learn"}
    ],
    "tribal_knowledge": "any relevant unwritten knowledge"
}"""

    def build_prompt(self, context: dict[str, Any]) -> str:
        question = context.get("question", "")
        entities = context.get("entities", [])
        channel_name = context.get("channel_name", "")
        thread_context = context.get("thread_context", "")

        parts = [
            f"## Question\n{question}",
        ]
        if entities:
            parts.append(f"\n## Related Entities\n{', '.join(entities)}")
        if channel_name:
            parts.append(f"\n## Channel: #{channel_name}")
        if thread_context:
            parts.append(f"\n## Thread Context\n{thread_context}")

        return "\n".join(parts)
