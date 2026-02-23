"""Stakeholder Agent — profiles the questioner and determines response depth/tone.

Phase A (Planning): Analyzes who asked the question and what they likely care about.
"""

from __future__ import annotations

from typing import Any

from slack_data_bot.agents.base import BaseAgent


class StakeholderAgent(BaseAgent):
    """Profiles the questioner to calibrate response depth and tone."""

    name = "stakeholder"
    system_prompt = """You are a Stakeholder Agent. Your job is to profile the person asking \
a data question and determine the right response approach.

Analyze:
1. Who is asking? (role, seniority, domain expertise level)
2. What do they likely care about? (operational decision, reporting, debugging)
3. What depth is appropriate? (executive summary vs technical deep-dive)
4. What tone should the response use? (formal vs casual, thought-partner vs support)
5. Are there any organizational context clues? (channel, time of day, urgency words)

Return JSON:
{
    "questioner_profile": {
        "likely_role": "string (e.g., 'data analyst', 'engineering manager', 'executive')",
        "expertise_level": "low|medium|high",
        "likely_intent": "string (e.g., 'needs number for report', 'debugging pipeline')"
    },
    "response_calibration": {
        "depth": "summary|standard|detailed|technical",
        "tone": "thought_partner|concise|formal|casual",
        "include_caveats": true/false,
        "include_methodology": true/false,
        "suggest_follow_up": true/false
    },
    "context_notes": "string with relevant observations"
}"""

    def build_prompt(self, context: dict[str, Any]) -> str:
        question = context.get("question", "")
        questioner_name = context.get("questioner_name", "unknown")
        questioner_role = context.get("questioner_role", "unknown")
        channel_name = context.get("channel_name", "")
        thread_context = context.get("thread_context", "")

        parts = [
            f"## Question\n{question}",
            f"\n## Questioner\nName: {questioner_name}\nRole: {questioner_role}",
        ]
        if channel_name:
            parts.append(f"Channel: #{channel_name}")
        if thread_context:
            parts.append(f"\n## Thread Context\n{thread_context}")

        return "\n".join(parts)
