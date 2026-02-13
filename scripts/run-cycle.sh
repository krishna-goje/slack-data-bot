#!/bin/bash
# Slack Data Bot - Single Poll Cycle
# Runs claude -p with the poll prompt, logs output to dated file.
#
# Usage:
#   ~/.slack-data-bot/run-cycle.sh              # single run
#   ~/.slack-data-bot/run-cycle.sh --learn      # run + self-learn after

set -euo pipefail

BOT_DIR="$HOME/.slack-data-bot"
LOG_DIR="$BOT_DIR/logs"
PROMPT_FILE="$BOT_DIR/prompts/poll.md"
LEARNINGS_DIR="$BOT_DIR/learnings"
TODAY=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
LOG_FILE="$LOG_DIR/$TODAY.log"

mkdir -p "$LOG_DIR" "$LEARNINGS_DIR"

echo "=== CYCLE START $TIMESTAMP ===" >> "$LOG_FILE"

# Run Claude Code with the poll prompt
# --print = non-interactive, output only
# Timeout after 10 minutes
if timeout 600 claude --print -p "$(cat "$PROMPT_FILE")" >> "$LOG_FILE" 2>&1; then
    echo "=== CYCLE END $(date +%Y-%m-%d_%H-%M-%S) STATUS=success ===" >> "$LOG_FILE"
else
    EXIT_CODE=$?
    echo "=== CYCLE END $(date +%Y-%m-%d_%H-%M-%S) STATUS=error EXIT=$EXIT_CODE ===" >> "$LOG_FILE"
fi

echo "" >> "$LOG_FILE"

# Self-learning step (if --learn flag passed)
if [[ "${1:-}" == "--learn" ]]; then
    echo "=== SELF-LEARN START $(date +%Y-%m-%d_%H-%M-%S) ===" >> "$LOG_FILE"

    LEARN_PROMPT="Read the latest cycle output from $LOG_FILE.
Analyze:
1. Did the search find relevant questions? If not, what strategies should be added?
2. Did the filter correctly remove bots and answered threads? Any false positives/negatives?
3. Was the investigation thorough? What was missed?
4. Was the draft quality good? What criteria failed?
5. Any new patterns to remember?

Output a brief JSON summary:
{
  \"questions_found\": N,
  \"questions_investigated\": N,
  \"quality_score\": \"X/7\",
  \"improvements\": [\"...\"],
  \"new_patterns\": [\"...\"],
  \"false_positives\": [\"...\"],
  \"false_negatives\": [\"...\"]
}

Then, if there are improvements, append them to $BOT_DIR/learnings/improvements.jsonl as one JSON line."

    timeout 120 claude --print -p "$LEARN_PROMPT" >> "$LOG_FILE" 2>&1 || true

    echo "=== SELF-LEARN END $(date +%Y-%m-%d_%H-%M-%S) ===" >> "$LOG_FILE"
fi
