"""Tests for the question classifier."""

from __future__ import annotations

from slack_data_bot.classifier import classify_question


class TestClassifier:
    def test_count_question(self):
        result = classify_question("How many contracts this week?")
        assert result.question_type == "count"
        assert result.confidence >= 0.8

    def test_trend_question(self):
        result = classify_question("What's the trend over time for revenue?")
        assert result.question_type == "trend"

    def test_comparison_question(self):
        result = classify_question("Compare Phoenix vs Atlanta contracts")
        assert result.question_type == "comparison"

    def test_root_cause_question(self):
        result = classify_question("Why did contracts drop last week?")
        assert result.question_type == "root_cause"

    def test_lineage_question(self):
        result = classify_question("Where does revenue data come from upstream?")
        assert result.question_type == "lineage"

    def test_definition_question(self):
        result = classify_question("What is repair surplus?")
        assert result.question_type == "definition"

    def test_status_question(self):
        result = classify_question("Is the snowflake warehouse down?")
        assert result.question_type == "status"

    def test_how_to_question(self):
        result = classify_question("How do I query the acq_l2 table?")
        assert result.question_type == "how_to"

    def test_unknown_question(self):
        result = classify_question("Hello there")
        assert result.question_type == "unknown"

    def test_entity_extraction(self):
        result = classify_question("The quicksight dashboard is broken")
        assert "quicksight" in result.entities
        assert "dashboard" in result.entities

    def test_time_period_extraction(self):
        result = classify_question("What happened last week?")
        assert result.time_period == "last week"

    def test_no_time_period(self):
        result = classify_question("What is a metric?")
        assert result.time_period is None

    def test_complexity_simple(self):
        result = classify_question("How many contracts?")
        assert result.complexity == "simple"

    def test_complexity_complex(self):
        long_q = (
            "Can you investigate why the QuickSight dashboard is showing different numbers "
            "than what we see in Snowflake for the WBR contracts metric? We noticed the "
            "discrepancy started last week and it seems to affect multiple markets including "
            "Phoenix, Atlanta, and Dallas. Please also check the dbt model and SPICE refresh."
        )
        result = classify_question(long_q)
        assert result.complexity == "complex"

    def test_agent_routing(self):
        result = classify_question("Why did contracts drop?")
        assert "data_planner" in result.suggested_agents
        assert "data_investigator" in result.suggested_agents

    def test_lineage_routing(self):
        result = classify_question("Where does this data come from?")
        assert "lineage_tracer" in result.suggested_agents
