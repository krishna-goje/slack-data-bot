"""Claude Code CLI integration for AI-powered investigation.

Spawns Claude Code CLI processes to investigate data questions.
Supports configurable backends (claude_code, claude_api, openai).
"""

from __future__ import annotations

import logging
import subprocess
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_data_bot.config import EngineConfig

logger = logging.getLogger(__name__)


class ClaudeCodeError(Exception):
    """Raised when Claude Code CLI execution fails."""

    def __init__(self, message: str, returncode: int | None = None, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class ClaudeCodeEngine:
    """Spawns Claude Code CLI processes to investigate data questions.

    Uses ``claude --print -p "prompt"`` to run non-interactive investigations.
    A threading semaphore limits the number of concurrent CLI processes.
    """

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self._semaphore = threading.Semaphore(config.max_concurrent)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def investigate(self, question: str, context: str = "") -> str:
        """Run an investigation for *question* and return the draft answer.

        Parameters
        ----------
        question:
            The user's data question (plain text).
        context:
            Optional contextual information (channel name, thread history,
            user details, etc.).

        Returns
        -------
        str
            The investigation result produced by Claude Code.

        Raises
        ------
        ClaudeCodeError
            If the CLI process fails or times out.
        """
        prompt = self._build_investigation_prompt(question, context)
        return self._run_claude(prompt, timeout=self.config.investigation_timeout)

    def review_draft(self, question: str, draft: str) -> str:
        """Ask Claude Code to review an existing draft answer.

        Parameters
        ----------
        question:
            The original user question.
        draft:
            The current draft answer to evaluate.

        Returns
        -------
        str
            The review output containing pass/fail assessments and feedback.
        """
        prompt = self._build_review_prompt(question, draft)
        return self._run_claude(prompt, timeout=self.config.review_timeout)

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_investigation_prompt(self, question: str, context: str) -> str:
        """Build the prompt sent to Claude Code for investigation."""
        parts: list[str] = [
            "You are a data investigation assistant. A user asked a question "
            "in a team chat channel. Investigate and provide a clear, accurate "
            "answer.",
            "",
            "## Question",
            question,
        ]

        if context:
            parts += ["", "## Context", context]

        parts += [
            "",
            "## Instructions",
            "1. Use available tools to query data sources and explore the codebase.",
            "2. Verify your findings before presenting them.",
            "3. Provide a concise answer suitable for posting back to the chat channel.",
            "4. Include relevant numbers, SQL snippets, or references where helpful.",
            "5. If you cannot determine the answer, explain what you tried and "
            "   suggest next steps.",
        ]

        return "\n".join(parts)

    def _build_review_prompt(self, question: str, draft: str) -> str:
        """Build the prompt sent to Claude Code for quality review."""
        criteria_block = "\n".join(
            f"- {c}" for c in getattr(self.config, "_quality_criteria", [])
        )
        if not criteria_block:
            criteria_block = (
                "- Accuracy: Are the facts and numbers correct?\n"
                "- Completeness: Does the answer fully address the question?\n"
                "- Clarity: Is the answer easy to understand?\n"
                "- Actionability: Does it help the user take next steps?"
            )

        return "\n".join([
            "You are a quality reviewer. Evaluate the following draft answer "
            "against each criterion below.",
            "",
            "## Original Question",
            question,
            "",
            "## Draft Answer",
            draft,
            "",
            "## Review Criteria",
            criteria_block,
            "",
            "## Instructions",
            "For EACH criterion, output exactly one line in this format:",
            "  CRITERION_NAME: PASS or FAIL",
            "followed by a brief explanation.",
            "",
            "After all criteria, add a section:",
            "  ## Feedback",
            "with specific, actionable suggestions for improvement. "
            "If everything passes, write 'No changes needed.'",
        ])

    # ------------------------------------------------------------------
    # Low-level execution
    # ------------------------------------------------------------------

    def _run_claude(self, prompt: str, timeout: int) -> str:
        """Execute a Claude Code CLI process and return parsed output.

        Acquires the concurrency semaphore before spawning the subprocess
        and releases it when done (even on failure).

        Parameters
        ----------
        prompt:
            The full prompt string to pass via ``-p``.
        timeout:
            Maximum wall-clock seconds to wait.

        Returns
        -------
        str
            Parsed CLI output.

        Raises
        ------
        ClaudeCodeError
            On non-zero exit, timeout, or empty output.
        """
        cmd = [self.config.claude_code_path, "--print", "-p", prompt]

        self._semaphore.acquire()
        try:
            logger.debug("Spawning Claude Code CLI (timeout=%ds)", timeout)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Claude Code CLI timed out after %ds", timeout)
            raise ClaudeCodeError(
                f"Claude Code timed out after {timeout}s", returncode=None
            )
        except FileNotFoundError:
            raise ClaudeCodeError(
                f"Claude Code binary not found at {self.config.claude_code_path!r}"
            )
        except OSError as exc:
            raise ClaudeCodeError(f"Failed to spawn Claude Code: {exc}")
        finally:
            self._semaphore.release()

        if result.returncode != 0:
            logger.error(
                "Claude Code exited with code %d: %s",
                result.returncode,
                result.stderr[:500],
            )
            raise ClaudeCodeError(
                f"Claude Code exited with code {result.returncode}",
                returncode=result.returncode,
                stderr=result.stderr,
            )

        output = self._parse_output(result.stdout)
        if not output.strip():
            raise ClaudeCodeError("Claude Code returned empty output")

        return output

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_output(stdout: str) -> str:
        """Extract useful content from Claude Code CLI stdout.

        The CLI may emit progress indicators, ANSI escape sequences, or
        framing text before/after the actual answer.  This method strips
        those artifacts and returns the meaningful content.
        """
        if not stdout:
            return ""

        lines: list[str] = []
        for line in stdout.splitlines():
            # Strip ANSI escape codes
            cleaned = line
            while "\x1b[" in cleaned:
                start = cleaned.index("\x1b[")
                end = start + 2
                while end < len(cleaned) and not cleaned[end].isalpha():
                    end += 1
                if end < len(cleaned):
                    end += 1  # include the terminating letter
                cleaned = cleaned[:start] + cleaned[end:]

            # Skip common CLI chrome lines
            stripped = cleaned.strip()
            if not stripped:
                lines.append("")
                continue
            if stripped.startswith(("╭", "╰", "│", "├", "└")):
                continue
            if stripped.startswith("Running ") and stripped.endswith("..."):
                continue

            lines.append(cleaned)

        # Trim leading/trailing blank lines
        text = "\n".join(lines).strip()
        return text
