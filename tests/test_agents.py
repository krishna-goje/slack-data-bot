"""Tests for the specialist agents."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from slack_data_bot.agents.base import BaseAgent
from slack_data_bot.agents.context_gatherer import ContextGathererAgent
from slack_data_bot.agents.data_investigator import DataInvestigatorAgent
from slack_data_bot.agents.data_planner import DataPlannerAgent
from slack_data_bot.agents.lineage_tracer import LineageTracerAgent
from slack_data_bot.agents.reviewer import ReviewerAgent
from slack_data_bot.agents.stakeholder import StakeholderAgent
from slack_data_bot.agents.stakeholder_advocate import StakeholderAdvocateAgent
from slack_data_bot.agents.writer import WriterAgent


class TestBaseAgent:
    def test_parse_json_response_direct(self):
        """JSON response parsed directly."""

        class TestAgent(BaseAgent):
            name = "test"
            system_prompt = "test"

            def build_prompt(self, context):
                return "test"

        agent = TestAgent()
        result = agent._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_response_code_block(self):
        """JSON extracted from markdown code block."""

        class TestAgent(BaseAgent):
            name = "test"
            system_prompt = "test"

            def build_prompt(self, context):
                return "test"

        agent = TestAgent()
        text = 'Here is the result:\n```json\n{"key": "value"}\n```\nDone.'
        result = agent._parse_json_response(text)
        assert result == {"key": "value"}

    def test_parse_json_response_embedded(self):
        """JSON extracted from text with surrounding content."""

        class TestAgent(BaseAgent):
            name = "test"
            system_prompt = "test"

            def build_prompt(self, context):
                return "test"

        agent = TestAgent()
        text = 'Some preamble {"key": "value"} some epilogue'
        result = agent._parse_json_response(text)
        assert result == {"key": "value"}

    def test_parse_json_response_fallback(self):
        """Non-JSON text returns raw_response dict."""

        class TestAgent(BaseAgent):
            name = "test"
            system_prompt = "test"

            def build_prompt(self, context):
                return "test"

        agent = TestAgent()
        result = agent._parse_json_response("Just plain text")
        assert "raw_response" in result


class TestAgentPrompts:
    """Test that each agent builds prompts correctly."""

    def test_stakeholder_prompt(self):
        agent = StakeholderAgent()
        prompt = agent.build_prompt({
            "question": "Why did contracts drop?",
            "questioner_name": "Alice",
            "questioner_role": "Product Manager",
            "channel_name": "ask-data-team",
        })
        assert "Why did contracts drop?" in prompt
        assert "Alice" in prompt
        assert "Product Manager" in prompt
        assert "#ask-data-team" in prompt

    def test_data_planner_prompt(self):
        agent = DataPlannerAgent()
        prompt = agent.build_prompt({
            "question": "How many contracts this week?",
            "entities": ["contracts"],
            "question_type": "count",
        })
        assert "How many contracts this week?" in prompt
        assert "count" in prompt
        assert "contracts" in prompt

    def test_context_gatherer_prompt(self):
        agent = ContextGathererAgent()
        prompt = agent.build_prompt({
            "question": "Why is the dashboard broken?",
            "entities": ["dashboard"],
            "channel_name": "data-questions",
        })
        assert "dashboard broken" in prompt
        assert "dashboard" in prompt

    def test_lineage_tracer_prompt(self):
        agent = LineageTracerAgent()
        prompt = agent.build_prompt({
            "question": "Where does revenue come from?",
            "entities": ["revenue"],
            "question_type": "lineage",
        })
        assert "revenue" in prompt
        assert "lineage" in prompt

    def test_data_investigator_prompt(self):
        agent = DataInvestigatorAgent()
        prompt = agent.build_prompt({
            "question": "How many contracts?",
            "investigation_plan": {"planned_queries": []},
            "entities": ["contracts"],
        })
        assert "How many contracts?" in prompt
        assert "Investigation Plan" in prompt

    def test_reviewer_prompt(self):
        agent = ReviewerAgent()
        prompt = agent.build_prompt({
            "question": "Test question",
            "draft": "Test draft response",
            "round_number": 1,
        })
        assert "Test question" in prompt
        assert "Test draft response" in prompt
        assert "Round 1" in prompt

    def test_reviewer_plan_review_prompt(self):
        agent = ReviewerAgent()
        prompt = agent.build_plan_review_prompt({
            "question": "Test question",
            "investigation_plan": {"planned_queries": []},
        })
        assert "Test question" in prompt
        assert "Investigation Plan" in prompt

    def test_writer_prompt(self):
        agent = WriterAgent()
        prompt = agent.build_prompt({
            "question": "Why did contracts drop?",
            "questioner_name": "Alice",
            "findings": {"data_investigator": {"key_findings": []}},
        })
        assert "Why did contracts drop?" in prompt
        assert "Alice" in prompt
        assert "Investigation Findings" in prompt

    def test_stakeholder_advocate_prompt(self):
        agent = StakeholderAdvocateAgent()
        prompt = agent.build_prompt({
            "question": "Why did contracts drop?",
            "draft": "Contracts dropped because...",
            "questioner_name": "Alice",
        })
        assert "Why did contracts drop?" in prompt
        assert "Contracts dropped because..." in prompt
        assert "Alice" in prompt


class TestAgentRun:
    @pytest.mark.asyncio
    async def test_agent_run_success(self):
        """Agent run with mock client returns successful result."""
        agent = DataPlannerAgent()

        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.text = json.dumps({
            "relevant_tables": [{"table": "schema.test", "reason": "test"}],
            "planned_queries": [],
        })
        mock_response.duration_ms = 100
        mock_response.input_tokens = 50
        mock_response.output_tokens = 100
        mock_client.invoke_with_json.return_value = mock_response

        result = await agent.run(mock_client, {"question": "Test?"})
        assert result.success is True
        assert result.agent_name == "data_planner"
        assert "relevant_tables" in result.findings

    @pytest.mark.asyncio
    async def test_agent_run_error(self):
        """Agent run with API error returns failed result."""
        agent = DataPlannerAgent()

        mock_client = AsyncMock()
        mock_client.invoke_with_json.side_effect = Exception("API error")

        result = await agent.run(mock_client, {"question": "Test?"})
        assert result.success is False
        assert "API error" in result.error
