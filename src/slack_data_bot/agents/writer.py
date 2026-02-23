"""Writer Agent — drafts Slack-formatted responses from investigation findings.

Phase D (Quality Loop): Converts raw agent findings into a polished,
copy-paste ready Slack message.
"""

from __future__ import annotations

from typing import Any

from slack_data_bot.agents.base import BaseAgent


class WriterAgent(BaseAgent):
    """Drafts polished Slack responses from raw investigation findings."""

    name = "writer"
    system_prompt = """You are a Response Writer Agent. Your job is to convert raw \
investigation findings into a polished Slack message.

## Style Rules (CRITICAL)

1. **Thought partner, not support team**: Don't just answer — drive insights.
   Lead with what's now possible, not just what was found.

2. **Lead with the answer**: First sentence should directly answer the question.
   Details come after.

3. **Slack mrkdwn formatting**:
   - Use *bold* for emphasis (NOT **markdown bold**)
   - Use `code` for table names, column names, metric names
   - Use > for important callouts or quotes
   - Use bullet lists (- item) for multiple points
   - Keep paragraphs short and scannable

4. **Include specific numbers**: Every claim must have a number.
   "Contracts are down" → "Contracts dropped from 142 to 98 (-31%) last week"

5. **Time periods explicit**: Never say "recently" — use specific dates.

6. **Offer next steps**: End with an invitation to dig deeper or a suggested follow-up.

7. **Caveats when needed**: If data has limitations, mention them briefly.

## Output

Return ONLY the Slack message text (not JSON). The message should be ready
to copy-paste into Slack. Do not include any meta-commentary about the message itself."""

    def build_prompt(self, context: dict[str, Any]) -> str:
        question = context.get("question", "")
        questioner_name = context.get("questioner_name", "")
        findings = context.get("findings", {})
        stakeholder_profile = context.get("stakeholder_profile", {})
        previous_feedback = context.get("previous_feedback", "")
        round_num = context.get("round_number", 1)

        import json

        parts = [
            f"## Original Question\n{question}",
        ]

        if questioner_name:
            parts.append(f"\nAsked by: {questioner_name}")

        if stakeholder_profile:
            calibration = stakeholder_profile.get("response_calibration", {})
            if calibration:
                parts.append(
                    f"\n## Response Calibration\n"
                    f"Depth: {calibration.get('depth', 'standard')}\n"
                    f"Tone: {calibration.get('tone', 'thought_partner')}"
                )

        parts.append(f"\n## Investigation Findings\n```json\n{json.dumps(findings, indent=2)}\n```")

        if previous_feedback and round_num > 1:
            parts.append(
                f"\n## Revision Guidance (Round {round_num})\n"
                f"The previous draft received this feedback:\n{previous_feedback}\n\n"
                f"Address ALL feedback points in this revision."
            )

        parts.append(
            "\n## Your Task\n"
            "Write a Slack message that answers the question using the findings above. "
            "Follow ALL style rules. Return ONLY the message text."
        )

        return "\n".join(parts)

    async def run(self, client, context):
        """Override to return raw text instead of JSON parsing."""
        try:

            user_prompt = self.build_prompt(context)
            response = await client.invoke(
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
            )

            return type("AgentResult", (), {
                "agent_name": self.name,
                "success": True,
                "findings": {"response_text": response.text},
                "raw_text": response.text,
                "error": None,
                "duration_ms": response.duration_ms,
                "tokens_used": response.input_tokens + response.output_tokens,
                "to_dict": lambda self: {
                    "agent_name": self.agent_name,
                    "success": self.success,
                    "findings": self.findings,
                },
            })()

        except Exception as e:
            from slack_data_bot.agents.base import AgentResult

            return AgentResult(
                agent_name=self.name,
                success=False,
                error=str(e),
            )
