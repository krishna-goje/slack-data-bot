"""Quality review loop - iterates draft through review criteria."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_data_bot.config import QualityConfig
    from slack_data_bot.engine.claude_code import ClaudeCodeEngine

logger = logging.getLogger(__name__)


@dataclass
class QualityResult:
    """Structured outcome of a quality review pass."""

    score: int
    total: int
    passed: bool
    feedback: str
    criteria_results: dict[str, bool] = field(default_factory=dict)
    rounds: int = 0


class QualityReviewer:
    """Runs the writer/reviewer quality loop.

    Each round:
      1. Ask Claude Code to review the current draft against configured criteria.
      2. Parse the review into a :class:`QualityResult`.
      3. If the score meets the minimum pass threshold, stop and return.
      4. Otherwise, feed the feedback back into a revision pass.
      5. After *max_rounds*, return the best version seen so far.
    """

    def __init__(self, config: QualityConfig) -> None:
        self.config = config

    def review_and_improve(
        self,
        question: str,
        initial_draft: str,
        engine: ClaudeCodeEngine,
    ) -> tuple[str, QualityResult]:
        """Iteratively review and improve a draft answer.

        Parameters
        ----------
        question:
            The original user question.
        initial_draft:
            The first-pass answer from the investigator.
        engine:
            The :class:`ClaudeCodeEngine` used for review and revision calls.

        Returns
        -------
        tuple[str, QualityResult]
            The final (possibly improved) draft and its quality assessment.
        """
        current_draft = initial_draft
        best_draft = initial_draft
        best_result = QualityResult(
            score=0, total=0, passed=False, feedback="", rounds=0
        )

        for round_num in range(1, self.config.max_rounds + 1):
            logger.debug("Quality review round %d/%d", round_num, self.config.max_rounds)

            # Review the current draft
            review_text = engine.review_draft(question, current_draft)
            result = self._parse_review(review_text)
            result.rounds = round_num

            # Track the best version
            if result.score > best_result.score:
                best_draft = current_draft
                best_result = result

            # Early exit if quality threshold met
            if result.score >= self.config.min_pass_criteria:
                logger.info(
                    "Quality passed on round %d: %d/%d",
                    round_num,
                    result.score,
                    result.total,
                )
                return current_draft, result

            # Last round - no point revising further
            if round_num == self.config.max_rounds:
                logger.info(
                    "Max rounds reached (%d). Best score: %d/%d",
                    self.config.max_rounds,
                    best_result.score,
                    best_result.total,
                )
                break

            # Revise the draft using the feedback
            logger.debug("Revising draft based on feedback")
            revision_context = (
                f"## Previous Feedback\n{result.feedback}\n\n"
                f"## Failed Criteria\n"
                + "\n".join(
                    f"- {name}" for name, passed in result.criteria_results.items()
                    if not passed
                )
            )
            current_draft = engine.investigate(
                question=question,
                context=revision_context,
            )

        return best_draft, best_result

    def _parse_review(self, review_text: str) -> QualityResult:
        """Parse Claude's review output into a structured QualityResult.

        Expects lines matching the pattern ``CRITERION_NAME: PASS`` or
        ``CRITERION_NAME: FAIL``, plus a ``## Feedback`` section.
        """
        criteria_results: dict[str, bool] = {}
        feedback_lines: list[str] = []
        in_feedback = False

        for line in review_text.splitlines():
            stripped = line.strip()

            # Detect feedback section
            if stripped.lower().startswith("## feedback") or stripped.lower() == "feedback:":
                in_feedback = True
                continue

            if in_feedback:
                feedback_lines.append(line)
                continue

            # Try to match criterion result lines: "Name: PASS" / "Name: FAIL"
            match = re.match(
                r"^[-*]?\s*(.+?):\s*(PASS|FAIL)\b",
                stripped,
                re.IGNORECASE,
            )
            if match:
                name = match.group(1).strip()
                verdict = match.group(2).upper() == "PASS"
                criteria_results[name] = verdict

        # If no criteria were parsed from the output, fall back to
        # checking configured criteria names against the raw text.
        if not criteria_results and self.config.criteria:
            for criterion in self.config.criteria:
                pattern = re.compile(
                    rf"{re.escape(criterion)}.*?(PASS|FAIL)", re.IGNORECASE
                )
                m = pattern.search(review_text)
                if m:
                    criteria_results[criterion] = m.group(1).upper() == "PASS"

        score = sum(1 for v in criteria_results.values() if v)
        total = len(criteria_results) or len(self.config.criteria)
        feedback = "\n".join(feedback_lines).strip() or "No feedback provided."

        return QualityResult(
            score=score,
            total=total,
            passed=score >= self.config.min_pass_criteria,
            feedback=feedback,
            criteria_results=criteria_results,
        )

    def _format_review_prompt(self, question: str, draft: str) -> str:
        """Build the review prompt asking Claude to evaluate each criterion.

        This is a convenience method for external callers that want the
        raw prompt without executing it.
        """
        criteria_block = "\n".join(f"- {c}" for c in self.config.criteria)
        return "\n".join([
            "Evaluate the following draft answer against each criterion.",
            "",
            "## Original Question",
            question,
            "",
            "## Draft Answer",
            draft,
            "",
            "## Criteria",
            criteria_block,
            "",
            "For EACH criterion, output exactly one line:",
            "  CRITERION_NAME: PASS or FAIL",
            "followed by a brief explanation.",
            "",
            "Then add:",
            "  ## Feedback",
            "with specific, actionable suggestions for improvement.",
        ])
