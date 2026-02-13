#!/usr/bin/env bash
# Slack Data Bot - Single Poll Cycle
# Runs claude -p with the poll prompt, logs output to dated file.
#
# Prerequisites:
#   - Claude Code CLI installed and authenticated
#   - ~/.slack-data-bot/prompts/poll.md exists (copy from examples/poll-prompt.md)
#
# Usage:
#   ~/.slack-data-bot/run-cycle.sh              # single run
#   ~/.slack-data-bot/run-cycle.sh --learn      # run + self-learn after

set -euo pipefail

BOT_DIR="$HOME/.slack-data-bot"
LOG_DIR="$BOT_DIR/logs"
PROMPT_FILE="$BOT_DIR/prompts/poll.md"
LEARNINGS_DIR="$BOT_DIR/learnings"
LOCKFILE="$BOT_DIR/.cycle.lock"
TODAY=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
LOG_FILE="$LOG_DIR/$TODAY.log"

# Max cycle duration in seconds (10 minutes)
MAX_CYCLE_SECONDS=600
# Max self-learn duration in seconds (2 minutes)
MAX_LEARN_SECONDS=120

mkdir -p "$LOG_DIR" "$LEARNINGS_DIR"

# --- Lock file to prevent concurrent cycles ---
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== CYCLE SKIPPED $TIMESTAMP (PID $LOCK_PID still running) ===" >> "$LOG_FILE"
        exit 0
    fi
    # Stale lock file — remove it
    rm -f "$LOCKFILE"
fi
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

# --- Preflight checks ---
if ! command -v claude &>/dev/null; then
    echo "=== CYCLE ERROR $TIMESTAMP: claude CLI not found in PATH ===" >> "$LOG_FILE"
    exit 1
fi

if [ ! -f "$PROMPT_FILE" ]; then
    echo "=== CYCLE ERROR $TIMESTAMP: Prompt file not found: $PROMPT_FILE ===" >> "$LOG_FILE"
    echo "Copy examples/poll-prompt.md to $PROMPT_FILE and customize it." >> "$LOG_FILE"
    exit 1
fi

# --- Run poll cycle ---
echo "=== CYCLE START $TIMESTAMP ===" >> "$LOG_FILE"

# Run Claude Code with the poll prompt
# --print = non-interactive, output only
# Use perl-based timeout for macOS compatibility (no GNU coreutils needed)
_run_with_timeout() {
    local max_seconds="$1"
    shift
    "$@" &
    local cmd_pid=$!
    ( sleep "$max_seconds" && kill "$cmd_pid" 2>/dev/null ) &
    local watchdog_pid=$!
    if wait "$cmd_pid" 2>/dev/null; then
        kill "$watchdog_pid" 2>/dev/null || true
        wait "$watchdog_pid" 2>/dev/null || true
        return 0
    else
        local exit_code=$?
        kill "$watchdog_pid" 2>/dev/null || true
        wait "$watchdog_pid" 2>/dev/null || true
        return $exit_code
    fi
}

if _run_with_timeout "$MAX_CYCLE_SECONDS" claude --print -p "$(cat "$PROMPT_FILE")" >> "$LOG_FILE" 2>&1; then
    echo "=== CYCLE END $(date +%Y-%m-%d_%H-%M-%S) STATUS=success ===" >> "$LOG_FILE"
else
    EXIT_CODE=$?
    echo "=== CYCLE END $(date +%Y-%m-%d_%H-%M-%S) STATUS=error EXIT=$EXIT_CODE ===" >> "$LOG_FILE"
fi

echo "" >> "$LOG_FILE"

# --- Self-learning step (if --learn flag passed) ---
if [[ "${1:-}" == "--learn" ]]; then
    echo "=== SELF-LEARN START $(date +%Y-%m-%d_%H-%M-%S) ===" >> "$LOG_FILE"

    # Extract just the latest cycle output for the learner
    CYCLE_OUTPUT=$(sed -n "/=== CYCLE START $TIMESTAMP ===/,/=== CYCLE END/p" "$LOG_FILE")

    LEARN_PROMPT="Analyze this bot cycle output and identify improvements.

--- CYCLE OUTPUT ---
$CYCLE_OUTPUT
--- END OUTPUT ---

Analyze:
1. Did the search find relevant questions? If not, what strategies should be added?
2. Did the filter correctly remove bots and answered threads? Any false positives/negatives?
3. Were scheduling messages incorrectly classified as data questions?
4. Was the investigation thorough? What was missed?
5. Any new patterns to remember?

Output a brief JSON summary to stdout:
{
  \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
  \"questions_found\": N,
  \"questions_investigated\": N,
  \"quality_score\": \"X/7\",
  \"improvements\": [\"...\"],
  \"new_patterns\": [\"...\"]
}"

    _run_with_timeout "$MAX_LEARN_SECONDS" claude --print -p "$LEARN_PROMPT" >> "$LOG_FILE" 2>&1 || true

    echo "=== SELF-LEARN END $(date +%Y-%m-%d_%H-%M-%S) ===" >> "$LOG_FILE"
fi

# --- Log rotation: clean up logs older than 30 days ---
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
