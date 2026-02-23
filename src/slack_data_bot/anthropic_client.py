"""Async Anthropic API wrapper for agent orchestration.

Uses Claude Opus 4.6 with adaptive thinking for all agent invocations.
Each agent call is a single-turn API call (no multi-turn conversations).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import anthropic

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Structured response from an agent invocation."""

    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    duration_ms: int = 0
    stop_reason: str = ""


@dataclass
class TokenUsage:
    """Accumulated token usage across multiple agent calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    total_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.thinking_tokens

    def add(self, response: AgentResponse) -> None:
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.thinking_tokens += response.thinking_tokens
        self.total_calls += 1


class AnthropicClient:
    """Async client for invoking specialist agents via the Anthropic API.

    Each agent invocation is a single-turn call with:
    - A system prompt defining the agent's role
    - A user prompt with the specific task
    - Adaptive thinking enabled (Opus 4.6 auto-calibrates depth)

    Usage::

        client = AnthropicClient(api_key="sk-ant-...")
        response = await client.invoke(
            system_prompt="You are a data investigator...",
            user_prompt="Investigate: Why did contracts drop?",
        )
        print(response.text)
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "claude-opus-4-6-20250219",
        max_tokens: int = 16000,
        timeout: int = 300,
    ) -> None:
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key

        self._client = anthropic.AsyncAnthropic(**kwargs)
        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._usage = TokenUsage()

    @property
    def usage(self) -> TokenUsage:
        """Accumulated token usage across all invocations."""
        return self._usage

    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
    ) -> AgentResponse:
        """Invoke an agent with a single-turn API call.

        Args:
            system_prompt: The agent's role and instructions.
            user_prompt: The specific task/question for this invocation.
            max_tokens: Override default max_tokens for this call.
            temperature: Temperature for response generation (default 1.0).

        Returns:
            AgentResponse with the text output and token usage.
        """
        start = time.monotonic()

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens or self._max_tokens,
                temperature=temperature,
                thinking={
                    "type": "enabled",
                    "budget_tokens": min(10000, (max_tokens or self._max_tokens) // 2),
                },
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            raise

        duration_ms = int((time.monotonic() - start) * 1000)

        # Extract text content (skip thinking blocks)
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)

        usage = response.usage
        agent_response = AgentResponse(
            text="\n".join(text_parts),
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            thinking_tokens=getattr(usage, "thinking_tokens", 0),
            duration_ms=duration_ms,
            stop_reason=response.stop_reason or "",
        )

        self._usage.add(agent_response)

        logger.debug(
            "Agent invocation: %d input + %d output tokens, %dms",
            agent_response.input_tokens,
            agent_response.output_tokens,
            agent_response.duration_ms,
        )

        return agent_response

    async def invoke_with_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
    ) -> AgentResponse:
        """Invoke an agent expecting JSON output.

        Adds a JSON instruction to the system prompt and validates the response.
        """
        json_system = (
            f"{system_prompt}\n\n"
            "IMPORTANT: Return your response as valid JSON. "
            "Do not include any text outside the JSON object."
        )
        return await self.invoke(
            system_prompt=json_system,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
        )
