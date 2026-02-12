"""Self-improvement optimizer - analyzes patterns and suggests improvements."""

from __future__ import annotations

from dataclasses import dataclass, field

from slack_data_bot.config import LearningConfig
from slack_data_bot.learning.feedback import FeedbackCollector
from slack_data_bot.learning.tracker import UsageTracker


@dataclass
class Recommendation:
    """A single improvement recommendation derived from usage analysis."""

    category: str
    message: str
    priority: str = "low"  # "low" | "medium" | "high"
    data: dict = field(default_factory=dict)


class Optimizer:
    """Analyzes tracked usage and feedback to produce actionable recommendations."""

    # Thresholds that trigger recommendations
    HIGH_REJECTION_RATE = 0.30
    SLOW_INVESTIGATION_SECONDS = 120.0
    MIN_SAMPLES_FOR_ANALYSIS = 5

    def __init__(
        self,
        config: LearningConfig,
        tracker: UsageTracker | None = None,
        feedback: FeedbackCollector | None = None,
    ) -> None:
        self.config = config
        self.tracker = tracker or UsageTracker(config)
        self.feedback = feedback or FeedbackCollector(config)

    def analyze(self) -> list[Recommendation]:
        """Analyze tracked data and return improvement recommendations."""
        recommendations: list[Recommendation] = []
        stats = self.tracker.get_stats(days=30)
        corrections = self.feedback.get_common_corrections(limit=10)

        self._check_rejection_rate(stats, recommendations)
        self._check_investigation_time(stats, recommendations)
        self._check_rejected_channels(stats, recommendations)
        self._check_common_corrections(corrections, recommendations)

        # Sort by priority: high > medium > low
        priority_order = {"high": 0, "medium": 1, "low": 2}
        recommendations.sort(key=lambda r: priority_order.get(r.priority, 3))

        return recommendations

    def generate_report(self) -> str:
        """Produce a human-readable report of stats and recommendations."""
        stats = self.tracker.get_stats(days=30)
        recommendations = self.analyze()

        lines = [
            "=== Bot Performance Report (Last 30 Days) ===",
            "",
            f"Questions detected:    {stats['total_questions']}",
            f"Investigations run:    {stats['total_investigations']}",
            f"Approved responses:    {stats['total_approved']}",
            f"Rejected responses:    {stats['total_rejected']}",
            f"Avg investigation time: {stats['avg_investigation_time']}s",
            f"Avg approval time:     {stats['avg_response_time']}s",
            "",
        ]

        if stats["top_channels"]:
            lines.append("Top channels:")
            for channel, count in stats["top_channels"][:5]:
                lines.append(f"  {channel}: {count}")
            lines.append("")

        if stats["top_question_types"]:
            lines.append("Top question types:")
            for qtype, count in stats["top_question_types"][:5]:
                lines.append(f"  {qtype}: {count}")
            lines.append("")

        if recommendations:
            lines.append(f"--- {len(recommendations)} Recommendation(s) ---")
            lines.append("")
            for i, rec in enumerate(recommendations, 1):
                lines.append(f"{i}. [{rec.priority.upper()}] {rec.category}")
                lines.append(f"   {rec.message}")
                lines.append("")
        else:
            lines.append("No recommendations at this time.")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private analysis helpers
    # ------------------------------------------------------------------

    def _check_rejection_rate(
        self, stats: dict, recs: list[Recommendation]
    ) -> None:
        total = stats["total_approved"] + stats["total_rejected"]
        if total < self.MIN_SAMPLES_FOR_ANALYSIS:
            return
        rejection_rate = stats["total_rejected"] / total
        if rejection_rate > self.HIGH_REJECTION_RATE:
            recs.append(Recommendation(
                category="high_rejection_rate",
                message=(
                    f"Rejection rate is {rejection_rate:.0%} "
                    f"({stats['total_rejected']}/{total}). "
                    "Consider refining prompts or adjusting classification thresholds."
                ),
                priority="high",
                data={"rejection_rate": round(rejection_rate, 3), "total": total},
            ))

    def _check_investigation_time(
        self, stats: dict, recs: list[Recommendation]
    ) -> None:
        avg = stats["avg_investigation_time"]
        enough_data = stats["total_investigations"] >= self.MIN_SAMPLES_FOR_ANALYSIS
        if avg > self.SLOW_INVESTIGATION_SECONDS and enough_data:
            recs.append(Recommendation(
                category="slow_investigations",
                message=(
                    f"Average investigation takes {avg:.0f}s (threshold: "
                    f"{self.SLOW_INVESTIGATION_SECONDS:.0f}s). "
                    "Consider enabling answer caching or pre-computing frequent queries."
                ),
                priority="medium",
                data={"avg_seconds": avg},
            ))

    def _check_rejected_channels(
        self, stats: dict, recs: list[Recommendation]
    ) -> None:
        """Identify channels with disproportionately high rejection rates."""
        # This requires per-channel data which we approximate from top_channels
        # For a deeper analysis, would need per-channel approval tracking
        if stats["total_rejected"] > 5:
            recs.append(Recommendation(
                category="channel_tuning",
                message=(
                    f"{stats['total_rejected']} rejections in the last 30 days. "
                    "Review per-channel feedback to identify channels that need "
                    "custom response strategies."
                ),
                priority="medium",
                data={"total_rejected": stats["total_rejected"]},
            ))

    def _check_common_corrections(
        self, corrections: list[dict], recs: list[Recommendation]
    ) -> None:
        rejection_reasons = [
            c for c in corrections if c.get("type") == "rejection_reason"
        ]
        if rejection_reasons:
            top = rejection_reasons[0]
            recs.append(Recommendation(
                category="common_correction",
                message=(
                    f"Most common rejection reason: \"{top['value']}\" "
                    f"({top['count']} occurrences). "
                    "Consider adding this as guidance in the investigation prompt."
                ),
                priority="medium" if top["count"] >= 3 else "low",
                data={"reason": top["value"], "count": top["count"]},
            ))
