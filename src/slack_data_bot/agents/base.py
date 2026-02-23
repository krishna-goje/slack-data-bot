"""Base agent abstract class and shared result types.

All specialist agents inherit from BaseAgent and implement the
``build_prompt`` method. The actual API call is handled by the
AnthropicClient passed at invocation time.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from slack_data_bot.anthropic_client import AgentResponse, AnthropicClient

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Structured result from a specialist agent."""

    agent_name: str
    success: bool
    findings: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    error: str | None = None
    duration_ms: int = 0
    tokens_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "success": self.success,
            "findings": self.findings,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
        }


class BaseAgent(ABC):
    """Abstract base class for specialist agents.

    Each agent defines:
    - ``name``: Unique identifier
    - ``system_prompt``: The agent's role and instructions
    - ``build_prompt``: Constructs the user prompt from context

    Invocation is handled by the ``run`` method, which calls the
    AnthropicClient and parses the response.
    """

    name: str = "base_agent"
    system_prompt: str = ""

    @abstractmethod
    def build_prompt(self, context: dict[str, Any]) -> str:
        """Build the user prompt from investigation context.

        Args:
            context: Dict with keys like 'question', 'entities',
                     'thread_context', 'schema_info', etc.

        Returns:
            The user prompt string for this agent.
        """
        ...

    async def run(
        self,
        client: AnthropicClient,
        context: dict[str, Any],
    ) -> AgentResult:
        """Execute this agent using the Anthropic API.

        Args:
            client: The async Anthropic client.
            context: Investigation context dict.

        Returns:
            AgentResult with findings or error information.
        """
        try:
            user_prompt = self.build_prompt(context)
            response: AgentResponse = await client.invoke_with_json(
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
            )

            # Try to parse as JSON
            findings = self._parse_json_response(response.text)

            return AgentResult(
                agent_name=self.name,
                success=True,
                findings=findings,
                raw_text=response.text,
                duration_ms=response.duration_ms,
                tokens_used=response.input_tokens + response.output_tokens,
            )

        except Exception as e:
            logger.exception("Agent %s failed: %s", self.name, e)
            return AgentResult(
                agent_name=self.name,
                success=False,
                error=str(e),
            )

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """Try to parse agent response as JSON, with fallback."""
        # Try direct JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code block
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

        # Try extracting any JSON object
        for i, char in enumerate(text):
            if char == "{":
                for j in range(len(text) - 1, i, -1):
                    if text[j] == "}":
                        try:
                            return json.loads(text[i : j + 1])
                        except json.JSONDecodeError:
                            break

        # Fallback: return raw text as a finding
        return {"raw_response": text}
