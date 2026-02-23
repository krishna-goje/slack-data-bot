"""Specialist agents for the investigation pipeline.

Agents:
    - StakeholderAgent: Profiles questioner, determines depth/tone
    - DataPlannerAgent: Designs query strategy
    - ContextGathererAgent: Finds tribal knowledge
    - LineageTracerAgent: Traces data origins
    - DataInvestigatorAgent: Executes queries, analyzes results
    - ReviewerAgent: Quality-checks plans and responses
    - WriterAgent: Drafts Slack-formatted responses
    - StakeholderAdvocateAgent: Evaluates from questioner's perspective
"""

from slack_data_bot.agents.base import AgentResult, BaseAgent
from slack_data_bot.agents.context_gatherer import ContextGathererAgent
from slack_data_bot.agents.data_investigator import DataInvestigatorAgent
from slack_data_bot.agents.data_planner import DataPlannerAgent
from slack_data_bot.agents.lineage_tracer import LineageTracerAgent
from slack_data_bot.agents.reviewer import ReviewerAgent
from slack_data_bot.agents.stakeholder import StakeholderAgent
from slack_data_bot.agents.stakeholder_advocate import StakeholderAdvocateAgent
from slack_data_bot.agents.writer import WriterAgent

__all__ = [
    "AgentResult",
    "BaseAgent",
    "ContextGathererAgent",
    "DataInvestigatorAgent",
    "DataPlannerAgent",
    "LineageTracerAgent",
    "ReviewerAgent",
    "StakeholderAgent",
    "StakeholderAdvocateAgent",
    "WriterAgent",
]
