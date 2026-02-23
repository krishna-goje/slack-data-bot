"""Stakeholder Advocate Agent — evaluates response from questioner's perspective.

Phase D (Quality Loop): Determines if the response would satisfy the
person who asked the question. Provides targeted feedback.
"""

from __future__ import annotations

from typing import Any

from slack_data_bot.agents.base import BaseAgent


class StakeholderAdvocateAgent(BaseAgent):
    """Evaluates a draft response from the questioner's perspective."""

    name = "stakeholder_advocate"
    system_prompt = """You are a Stakeholder Advocate. You represent the person who asked \
the data question. Your job is to evaluate whether a draft response \
would actually satisfy them.

Think from THEIR perspective:
1. Would they understand this response? (clarity)
2. Does it actually answer what they asked? (relevance)
3. Is the technical depth appropriate for their role? (calibration)
4. Would they need to ask follow-up questions? (completeness)
5. Does it feel like a thought partner helping them, or a support ticket being closed? (tone)
6. Can they take action based on this response? (actionability)

Be critical. If the response is not satisfying, say exactly what's missing.

Return JSON:
{
    "satisfied": true or false,
    "satisfaction_score": 1-10,
    "gaps": ["list of things the questioner would still wonder about"],
    "clarity_issues": ["anything confusing or unclear"],
    "tone_feedback": "assessment of how the response feels",
    "suggested_improvements": ["specific changes that would improve satisfaction"],
    "would_need_follow_up": true or false,
    "follow_up_questions": ["questions the questioner would likely ask next"]
}"""

    def build_prompt(self, context: dict[str, Any]) -> str:
        question = context.get("question", "")
        draft = context.get("draft", "")
        questioner_name = context.get("questioner_name", "colleague")
        questioner_role = context.get("questioner_role", "")
        stakeholder_profile = context.get("stakeholder_profile", {})

        parts = [
            f"## Original Question\n{question}",
            f"\n## Asked by: {questioner_name}",
        ]

        if questioner_role:
            parts.append(f"Role: {questioner_role}")

        if stakeholder_profile:
            profile = stakeholder_profile.get("questioner_profile", {})
            if profile:
                parts.append(
                    f"\n## Questioner Profile\n"
                    f"Likely role: {profile.get('likely_role', 'unknown')}\n"
                    f"Expertise: {profile.get('expertise_level', 'unknown')}\n"
                    f"Intent: {profile.get('likely_intent', 'unknown')}"
                )

        parts.append(f"\n## Draft Response\n{draft}")
        parts.append(
            "\n## Your Task\n"
            "Evaluate this response from the questioner's perspective. "
            "Be honest and critical — would they actually be satisfied?"
        )

        return "\n".join(parts)
