"""Tests for the multi-agent orchestrator."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from slack_data_bot.anthropic_client import AgentResponse
from slack_data_bot.orchestrator import Orchestrator


@pytest.fixture
def mock_anthropic_client():
    """Create a mock AnthropicClient that returns canned responses."""
    client = AsyncMock()

    # Default response for any invoke call
    def make_response(text: str = '{"findings": "test"}') -> AgentResponse:
        return AgentResponse(
            text=text,
            model="claude-opus-4-6-20250219",
            input_tokens=100,
            output_tokens=200,
            thinking_tokens=50,
            duration_ms=500,
            stop_reason="end_turn",
        )

    # Set up invoke to return appropriate responses
    client.invoke_with_json.return_value = make_response(
        json.dumps({
            "key_findings": [{"finding": "Test finding", "evidence": "123", "confidence": "high"}],
            "analysis_summary": "Test analysis",
        })
    )

    # Writer returns plain text
    client.invoke.return_value = make_response(
        "*Answer*\n\nContracts dropped by 10% last week due to seasonal patterns."
    )

    # Usage tracking
    client.usage = AsyncMock()
    client.usage.total_tokens = 1000

    return client


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_investigate_basic(self, mock_anthropic_client):
        """Basic investigation flow completes without errors."""
        orchestrator = Orchestrator(
            client=mock_anthropic_client,
            max_quality_rounds=1,
            min_pass_criteria=0,  # Accept any quality for this test
        )

        result = await orchestrator.investigate(
            question="How many contracts this week?",
            context={"questioner_name": "Alice"},
        )

        assert result.response != ""
        assert result.question_type == "count"
        assert result.classification is not None
        assert result.classification.question_type == "count"

    @pytest.mark.asyncio
    async def test_investigate_classifies_correctly(self, mock_anthropic_client):
        """Orchestrator classifies the question type."""
        orchestrator = Orchestrator(
            client=mock_anthropic_client,
            max_quality_rounds=1,
            min_pass_criteria=0,
        )

        result = await orchestrator.investigate("Why did revenue drop?")
        assert result.question_type == "root_cause"

    @pytest.mark.asyncio
    async def test_investigate_uses_agents(self, mock_anthropic_client):
        """Orchestrator invokes specialist agents."""
        orchestrator = Orchestrator(
            client=mock_anthropic_client,
            max_quality_rounds=1,
            min_pass_criteria=0,
        )

        result = await orchestrator.investigate("How many contracts?")
        # Should have used agents
        assert len(result.agent_results) > 0

    @pytest.mark.asyncio
    async def test_quality_loop_runs(self, mock_anthropic_client):
        """Quality loop produces iterations."""
        # Make reviewer pass on first round
        responses = [
            # Planning agents
            AgentResponse(text='{"test": true}', model="test", input_tokens=50, output_tokens=50),
            AgentResponse(text='{"test": true}', model="test", input_tokens=50, output_tokens=50),
            AgentResponse(text='{"test": true}', model="test", input_tokens=50, output_tokens=50),
            # Plan review
            AgentResponse(
                text='{"plan_assessment": "APPROVED"}',
                model="test", input_tokens=50, output_tokens=50,
            ),
            # Execute agents
            AgentResponse(
                text='{"key_findings": [{"finding": "42 contracts"}]}',
                model="test", input_tokens=50, output_tokens=50,
            ),
        ]
        mock_anthropic_client.invoke_with_json.side_effect = responses

        # Writer
        mock_anthropic_client.invoke.return_value = AgentResponse(
            text="*42 contracts* this week, up from 38 last week.",
            model="test", input_tokens=50, output_tokens=100,
        )

        orchestrator = Orchestrator(
            client=mock_anthropic_client,
            max_quality_rounds=1,
            min_pass_criteria=0,
        )

        result = await orchestrator.investigate("How many contracts?")
        assert len(result.quality_iterations) >= 1

    @pytest.mark.asyncio
    async def test_merge_findings(self, mock_anthropic_client):
        """Findings from multiple agents are merged correctly."""
        orchestrator = Orchestrator(client=mock_anthropic_client)

        from slack_data_bot.agents.base import AgentResult

        results = [
            AgentResult(agent_name="a", success=True, findings={"key_a": "val_a"}),
            AgentResult(agent_name="b", success=True, findings={"key_b": "val_b"}),
            AgentResult(agent_name="c", success=False, error="failed"),
        ]

        merged = orchestrator._merge_findings(results)
        assert "a" in merged
        assert "b" in merged
        assert "c" not in merged  # Failed agent excluded
