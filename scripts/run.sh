#!/usr/bin/env bash
#
# run.sh - Quick start script for Slack Data Bot
#
# Checks prerequisites, activates virtualenv if present, and runs the bot.
# All arguments are passed through to slack-data-bot.
#
# Usage:
#   ./scripts/run.sh                          # Run with default config
#   ./scripts/run.sh --config config.yaml     # Run with specific config
#   ./scripts/run.sh --dry-run                # Validate config only
#   ./scripts/run.sh --once --verbose         # Single verbose cycle
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

# Check Python version (3.10+)
check_python() {
    local python_cmd=""

    if command -v python3 &>/dev/null; then
        python_cmd="python3"
    elif command -v python &>/dev/null; then
        python_cmd="python"
    else
        echo "Error: Python not found. Install Python 3.10 or later."
        exit 1
    fi

    local version
    version=$($python_cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)

    if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 10 ]; }; then
        echo "Error: Python 3.10+ required, found $version"
        exit 1
    fi

    echo "Python $version OK"
}

# Check for config file
check_config() {
    # Skip check if user passed --config or --dry-run with no config
    for arg in "$@"; do
        if [ "$arg" = "--config" ] || [ "$arg" = "-c" ]; then
            return 0
        fi
    done

    # Check default locations
    if [ -f "$PROJECT_DIR/config.yaml" ]; then
        echo "Config: $PROJECT_DIR/config.yaml"
        return 0
    fi

    if [ -f "$HOME/.slack-data-bot/config.yaml" ]; then
        echo "Config: $HOME/.slack-data-bot/config.yaml"
        return 0
    fi

    if [ -n "${SLACK_DATA_BOT_CONFIG:-}" ]; then
        echo "Config: $SLACK_DATA_BOT_CONFIG (from env)"
        return 0
    fi

    echo "Warning: No config file found. The bot will use default settings."
    echo "  Create one: cp examples/config.yaml.example config.yaml"
    echo ""
}

# Activate virtualenv if present
activate_venv() {
    # Check common virtualenv locations
    local venv_dirs=(
        "$PROJECT_DIR/.venv"
        "$PROJECT_DIR/venv"
        "$HOME/.slack-data-bot/venv"
    )

    for venv_dir in "${venv_dirs[@]}"; do
        if [ -f "$venv_dir/bin/activate" ]; then
            echo "Activating virtualenv: $venv_dir"
            # shellcheck disable=SC1091
            source "$venv_dir/bin/activate"
            return 0
        fi
    done

    # No virtualenv found; that is fine
    return 0
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

echo "=== Slack Data Bot ==="
echo ""

check_python
activate_venv
check_config "$@"

# Check if slack-data-bot is installed
if ! command -v slack-data-bot &>/dev/null; then
    echo "slack-data-bot not found in PATH."
    echo "Installing from project directory..."
    pip install -e "$PROJECT_DIR" --quiet
    echo "Installed."
    echo ""
fi

echo "Starting slack-data-bot..."
echo ""

exec slack-data-bot "$@"
