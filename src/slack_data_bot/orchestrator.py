"""Multi-agent orchestrator — coordinates the Plan→Review→Execute→Quality pipeline.

Implements the internal plan-then-execute pattern:
  Phase A: Collaborative Planning (parallel agents)
  Phase B: Plan Review (Reviewer Agent)
  Phase C: Execute All At Once (parallel agents)
  Phase D: Quality Loop (Writer → Reviewer → Advocate, max 3 rounds)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from slack_data_bot.agents.base import AgentResult, BaseAgent
from slack_data_bot.agents.context_gatherer import ContextGathererAgent
from slack_data_bot.agents.data_investigator import DataInvestigatorAgent
from slack_data_bot.agents.data_planner import DataPlannerAgent
from slack_data_bot.agents.lineage_tracer import LineageTracerAgent
from slack_data_bot.agents.reviewer import ReviewerAgent
from slack_data_bot.agents.stakeholder import StakeholderAgent
from slack_data_bot.agents.stakeholder_advocate import StakeholderAdvocateAgent
from slack_data_bot.agents.writer import WriterAgent
from slack_data_bot.anthropic_client import AnthropicClient
from slack_data_bot.classifier import Classification, classify_question

logger = logging.getLogger(__name__)


@dataclass
class QualityIteration:
    """One round of the Writer → Reviewer → Advocate loop."""

    round_number: int
    draft: str
    passed_count: int
    total_criteria: int = 7
    reviewer_feedback: str = ""
    advocate_feedback: str = ""
    approved: bool = False


@dataclass
class InvestigationResult:
    """Complete result of an investigation pipeline run."""

    response: str = ""
    question_type: str = "unknown"
    classification: Classification | None = None
    agent_results: list[AgentResult] = field(default_factory=list)
    quality_iterations: list[QualityIteration] = field(default_factory=list)
    quality_score: int = 0
    quality_total: int = 7
    total_duration_ms: int = 0
    total_tokens: int = 0
    agents_used: list[str] = field(default_factory=list)


class Orchestrator:
    """Coordinates the multi-agent investigation pipeline.

    Usage::

        orchestrator = Orchestrator(client=AnthropicClient(...))
        result = await orchestrator.investigate(
            question="Why did contracts drop last week?",
            context={...},
        )
        print(result.response)  # Copy-paste ready Slack message
    """

    def __init__(
        self,
        client: AnthropicClient,
        max_quality_rounds: int = 3,
        min_pass_criteria: int = 5,
    ) -> None:
        self.client = client
        self.max_quality_rounds = max_quality_rounds
        self.min_pass_criteria = min_pass_criteria

        # Initialize all agents
        self.stakeholder = StakeholderAgent()
        self.data_planner = DataPlannerAgent()
        self.context_gatherer = ContextGathererAgent()
        self.lineage_tracer = LineageTracerAgent()
        self.data_investigator = DataInvestigatorAgent()
        self.reviewer = ReviewerAgent()
        self.writer = WriterAgent()
        self.advocate = StakeholderAdvocateAgent()

        self._agent_map: dict[str, BaseAgent] = {
            "stakeholder": self.stakeholder,
            "data_planner": self.data_planner,
            "context_gatherer": self.context_gatherer,
            "lineage_tracer": self.lineage_tracer,
            "data_investigator": self.data_investigator,
        }

    async def investigate(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> InvestigationResult:
        """Run the full investigation pipeline.

        Args:
            question: The data question to investigate.
            context: Optional context dict with keys like questioner_name,
                     channel_name, thread_context, schema_info, etc.

        Returns:
            InvestigationResult with the polished response and metadata.
        """
        start = time.monotonic()
        ctx = context or {}
        ctx["question"] = question
        result = InvestigationResult()

        # Step 0: Classify the question
        classification = classify_question(question, ctx.get("channel_name", ""))
        result.classification = classification
        result.question_type = classification.question_type
        ctx["question_type"] = classification.question_type
        ctx["entities"] = classification.entities

        logger.info(
            "Classified question as %s (confidence: %.2f). Agents: %s",
            classification.question_type,
            classification.confidence,
            classification.suggested_agents,
        )

        # Phase A: Collaborative Planning (parallel)
        logger.info("Phase A: Planning with %d agents", len(classification.suggested_agents) + 1)
        planning_agents = ["stakeholder"] + classification.suggested_agents
        plan_results = await self._run_agents_parallel(planning_agents, ctx)
        result.agent_results.extend(plan_results)
        result.agents_used.extend(a.agent_name for a in plan_results if a.success)

        # Merge planning findings into context
        combined_plan = self._merge_findings(plan_results)
        ctx["investigation_plan"] = combined_plan
        ctx["stakeholder_profile"] = next(
            (r.findings for r in plan_results if r.agent_name == "stakeholder" and r.success),
            {},
        )

        # Phase B: Plan Review
        logger.info("Phase B: Reviewing investigation plan")
        review_result = await self._review_plan(ctx)
        if review_result.success:
            # Incorporate reviewer suggestions into the plan
            review_findings = review_result.findings
            if review_findings.get("missing_angles"):
                combined_plan["reviewer_additions"] = review_findings["missing_angles"]
                ctx["investigation_plan"] = combined_plan

        # Phase C: Execute (parallel) — re-run investigation agents with plan context
        logger.info("Phase C: Executing investigation with plan")
        execute_agents = [
            a for a in classification.suggested_agents
            if a in ("data_investigator", "context_gatherer", "lineage_tracer")
        ]
        if not execute_agents:
            execute_agents = ["data_investigator"]
        exec_results = await self._run_agents_parallel(execute_agents, ctx)
        result.agent_results.extend(exec_results)

        # Merge all findings
        all_findings = self._merge_findings(result.agent_results)
        ctx["findings"] = all_findings

        # Phase D: Quality Loop (Writer → Reviewer → Advocate)
        logger.info("Phase D: Quality loop (max %d rounds)", self.max_quality_rounds)
        final_draft, iterations = await self._quality_loop(ctx)
        result.response = final_draft
        result.quality_iterations = iterations

        if iterations:
            last_iter = iterations[-1]
            result.quality_score = last_iter.passed_count
            result.quality_total = last_iter.total_criteria

        result.total_duration_ms = int((time.monotonic() - start) * 1000)
        result.total_tokens = self.client.usage.total_tokens

        logger.info(
            "Investigation complete: %d/%d quality, %d agents, %dms",
            result.quality_score,
            result.quality_total,
            len(result.agents_used),
            result.total_duration_ms,
        )

        return result

    async def _run_agents_parallel(
        self,
        agent_names: list[str],
        context: dict[str, Any],
    ) -> list[AgentResult]:
        """Run multiple agents in parallel."""
        tasks = []
        for name in agent_names:
            agent = self._agent_map.get(name)
            if agent:
                tasks.append(agent.run(self.client, context))
            else:
                logger.warning("Unknown agent: %s", name)

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)

        agent_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Agent %s raised exception: %s", agent_names[i], result)
                agent_results.append(
                    AgentResult(
                        agent_name=agent_names[i],
                        success=False,
                        error=str(result),
                    )
                )
            else:
                agent_results.append(result)

        return agent_results

    async def _review_plan(self, context: dict[str, Any]) -> AgentResult:
        """Phase B: Have the reviewer check the investigation plan."""
        prompt = self.reviewer.build_plan_review_prompt(context)
        try:
            response = await self.client.invoke_with_json(
                system_prompt=self.reviewer.system_prompt,
                user_prompt=prompt,
            )
            findings = self.reviewer._parse_json_response(response.text)
            return AgentResult(
                agent_name="reviewer",
                success=True,
                findings=findings,
                raw_text=response.text,
                duration_ms=response.duration_ms,
                tokens_used=response.input_tokens + response.output_tokens,
            )
        except Exception as e:
            logger.exception("Plan review failed: %s", e)
            return AgentResult(agent_name="reviewer", success=False, error=str(e))

    async def _quality_loop(
        self,
        context: dict[str, Any],
    ) -> tuple[str, list[QualityIteration]]:
        """Phase D: Writer → Reviewer → Advocate loop."""
        iterations: list[QualityIteration] = []
        previous_feedback = ""
        best_draft = ""
        best_score = 0

        for round_num in range(1, self.max_quality_rounds + 1):
            # Update context for this round
            context["round_number"] = round_num
            context["previous_feedback"] = previous_feedback

            # Writer: generate draft
            writer_result = await self.writer.run(self.client, context)
            draft = ""
            if writer_result.success:
                draft = writer_result.findings.get("response_text", writer_result.raw_text)
            else:
                draft = f"*Error generating response*: {writer_result.error}"
                iterations.append(QualityIteration(
                    round_number=round_num, draft=draft, passed_count=0, approved=False,
                ))
                break

            # Reviewer: check quality
            context["draft"] = draft
            reviewer_result = await self.reviewer.run(self.client, context)
            passed_count = 0
            reviewer_feedback = ""
            if reviewer_result.success:
                criteria = reviewer_result.findings.get("criteria", {})
                passed_count = sum(
                    1 for c in criteria.values()
                    if isinstance(c, dict) and c.get("status") == "PASS"
                )
                reviewer_feedback = reviewer_result.findings.get("revision_guidance", "")

            # Track best draft
            if passed_count > best_score:
                best_score = passed_count
                best_draft = draft

            iteration = QualityIteration(
                round_number=round_num,
                draft=draft,
                passed_count=passed_count,
                reviewer_feedback=reviewer_feedback,
                approved=passed_count >= self.min_pass_criteria,
            )

            # Check if approved
            if passed_count >= self.min_pass_criteria:
                logger.info("Quality approved on round %d: %d/7", round_num, passed_count)
                iterations.append(iteration)
                return draft, iterations

            # Stakeholder Advocate: get additional feedback (rounds 1-2 only)
            if round_num < self.max_quality_rounds:
                advocate_result = await self.advocate.run(self.client, context)
                advocate_feedback = ""
                if advocate_result.success:
                    advocate_feedback = advocate_result.findings.get("suggested_improvements", "")
                    if isinstance(advocate_feedback, list):
                        advocate_feedback = "\n".join(f"- {s}" for s in advocate_feedback)

                iteration.advocate_feedback = str(advocate_feedback)
                previous_feedback = (
                    f"Reviewer ({passed_count}/7): {reviewer_feedback}\n"
                    f"Stakeholder Advocate: {advocate_feedback}"
                )

            iterations.append(iteration)

        logger.info(
            "Quality loop exhausted after %d rounds. Best: %d/7",
            self.max_quality_rounds,
            best_score,
        )
        return best_draft or draft, iterations

    def _merge_findings(self, results: list[AgentResult]) -> dict[str, Any]:
        """Merge findings from multiple agents into a single dict."""
        merged: dict[str, Any] = {}
        for result in results:
            if result.success and result.findings:
                merged[result.agent_name] = result.findings
        return merged
