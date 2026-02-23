"""Tests for Pydantic input/output models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from slack_data_bot.models import (
    ClassifyQuestionInput,
    ClassifyQuestionOutput,
    DraftResponseInput,
    GetThreadContextInput,
    InvestigateQuestionInput,
    MarkAnsweredInput,
    MonitorMentionsInput,
    MonitorMentionsOutput,
    QuestionType,
    SlackMessageInfo,
)


class TestMonitorMentionsInput:
    def test_defaults(self):
        params = MonitorMentionsInput()
        assert params.lookback_days == 7
        assert params.max_results == 20

    def test_custom_values(self):
        params = MonitorMentionsInput(lookback_days=30, max_results=50)
        assert params.lookback_days == 30
        assert params.max_results == 50

    def test_lookback_days_validation(self):
        with pytest.raises(ValidationError):
            MonitorMentionsInput(lookback_days=0)
        with pytest.raises(ValidationError):
            MonitorMentionsInput(lookback_days=91)

    def test_max_results_validation(self):
        with pytest.raises(ValidationError):
            MonitorMentionsInput(max_results=0)
        with pytest.raises(ValidationError):
            MonitorMentionsInput(max_results=101)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            MonitorMentionsInput(lookback_days=7, unknown_field="bad")


class TestGetThreadContextInput:
    def test_required_fields(self):
        params = GetThreadContextInput(channel_id="C123", thread_ts="1234.5678")
        assert params.channel_id == "C123"
        assert params.thread_ts == "1234.5678"
        assert params.include_reactions is False

    def test_empty_channel_id_rejected(self):
        with pytest.raises(ValidationError):
            GetThreadContextInput(channel_id="", thread_ts="1234.5678")


class TestClassifyQuestionInput:
    def test_basic(self):
        params = ClassifyQuestionInput(text="Why did contracts drop?")
        assert params.text == "Why did contracts drop?"
        assert params.channel_context == ""

    def test_empty_text_rejected(self):
        with pytest.raises(ValidationError):
            ClassifyQuestionInput(text="")

    def test_max_length(self):
        long_text = "a" * 10001
        with pytest.raises(ValidationError):
            ClassifyQuestionInput(text=long_text)


class TestInvestigateQuestionInput:
    def test_required_question(self):
        params = InvestigateQuestionInput(question="How many contracts this week?")
        assert params.question == "How many contracts this week?"
        assert params.max_agent_rounds == 3

    def test_max_agent_rounds_validation(self):
        with pytest.raises(ValidationError):
            InvestigateQuestionInput(question="test", max_agent_rounds=0)
        with pytest.raises(ValidationError):
            InvestigateQuestionInput(question="test", max_agent_rounds=6)


class TestDraftResponseInput:
    def test_required_fields(self):
        params = DraftResponseInput(question="Q?", findings="Data shows X")
        assert params.question == "Q?"
        assert params.findings == "Data shows X"
        assert params.tone == "thought_partner"
        assert params.format == "slack_mrkdwn"


class TestMarkAnsweredInput:
    def test_required_fields(self):
        params = MarkAnsweredInput(channel_id="C123", message_ts="1234.5678")
        assert params.channel_id == "C123"
        assert params.message_ts == "1234.5678"
        assert params.summary == ""


class TestOutputModels:
    def test_monitor_mentions_output_serialization(self):
        output = MonitorMentionsOutput(
            messages=[
                SlackMessageInfo(
                    ts="1.1",
                    channel_id="C1",
                    text="test",
                    priority=50,
                )
            ],
            total_found=10,
            total_filtered=1,
            strategies_used=8,
        )
        data = output.model_dump()
        assert len(data["messages"]) == 1
        assert data["total_found"] == 10

    def test_classify_output_enum(self):
        output = ClassifyQuestionOutput(
            question_type=QuestionType.COUNT,
            confidence=0.9,
            entities=["contracts"],
        )
        assert output.question_type == QuestionType.COUNT
        assert output.confidence == 0.9

    def test_question_type_values(self):
        assert QuestionType.COUNT.value == "count"
        assert QuestionType.TREND.value == "trend"
        assert QuestionType.ROOT_CAUSE.value == "root_cause"
        assert QuestionType.UNKNOWN.value == "unknown"
