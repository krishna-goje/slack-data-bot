#!/usr/bin/env bash
#
# install-daemon.sh - macOS launchd setup for Slack Data Bot
#
# Usage:
#   ./scripts/install-daemon.sh install    # Create and load the plist
#   ./scripts/install-daemon.sh uninstall  # Unload and remove the plist
#   ./scripts/install-daemon.sh status     # Check if running
#
set -euo pipefail

PLIST_LABEL="com.slack-data-bot"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
CONFIG_PATH="$HOME/.slack-data-bot/config.yaml"
LOG_DIR="$HOME/.slack-data-bot/logs"
BOT_BIN="$(command -v slack-data-bot 2>/dev/null || echo "")"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

usage() {
    echo "Usage: $0 {install|uninstall|status}"
    echo ""
    echo "Commands:"
    echo "  install    Create launchd plist and load it"
    echo "  uninstall  Unload and remove the launchd plist"
    echo "  status     Check if the daemon is running"
    exit 1
}

check_binary() {
    if [ -z "$BOT_BIN" ]; then
        echo "Error: slack-data-bot not found in PATH."
        echo "Install it first: pip install slack-data-bot"
        exit 1
    fi
    echo "Found binary: $BOT_BIN"
}

check_config() {
    if [ ! -f "$CONFIG_PATH" ]; then
        echo "Warning: Config not found at $CONFIG_PATH"
        echo "Create it from the example:"
        echo "  mkdir -p ~/.slack-data-bot"
        echo "  cp examples/config.yaml.example ~/.slack-data-bot/config.yaml"
        echo ""
    fi
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

do_install() {
    check_binary
    check_config

    # Create log directory
    mkdir -p "$LOG_DIR"

    # Create plist
    cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${BOT_BIN}</string>
        <string>--config</string>
        <string>${CONFIG_PATH}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${HOME}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>60</integer>

    <key>StandardOutPath</key>
    <string>${LOG_DIR}/stdout.log</string>

    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:${HOME}/.local/bin</string>
    </dict>
</dict>
</plist>
PLIST

    echo "Created plist at $PLIST_PATH"

    # Load the daemon
    launchctl load "$PLIST_PATH"
    echo "Daemon loaded. Slack Data Bot will start on login."
    echo ""
    echo "Logs:"
    echo "  stdout: $LOG_DIR/stdout.log"
    echo "  stderr: $LOG_DIR/stderr.log"
    echo ""
    echo "Manage:"
    echo "  Status:    $0 status"
    echo "  Stop:      launchctl unload $PLIST_PATH"
    echo "  Start:     launchctl load $PLIST_PATH"
    echo "  Uninstall: $0 uninstall"
}

do_uninstall() {
    if [ ! -f "$PLIST_PATH" ]; then
        echo "No plist found at $PLIST_PATH. Nothing to uninstall."
        exit 0
    fi

    # Unload (ignoring errors if not loaded)
    launchctl unload "$PLIST_PATH" 2>/dev/null || true

    # Remove plist
    rm -f "$PLIST_PATH"
    echo "Daemon uninstalled. Plist removed from $PLIST_PATH"
    echo "Log files preserved at $LOG_DIR"
}

do_status() {
    if launchctl list 2>/dev/null | grep -q "$PLIST_LABEL"; then
        echo "Slack Data Bot daemon is LOADED"
        launchctl list "$PLIST_LABEL" 2>/dev/null || true
    else
        echo "Slack Data Bot daemon is NOT loaded"
    fi

    if [ -f "$PLIST_PATH" ]; then
        echo "Plist exists at $PLIST_PATH"
    else
        echo "No plist found (not installed)"
    fi

    if [ -f "$LOG_DIR/stdout.log" ]; then
        echo ""
        echo "Last 5 lines of stdout:"
        tail -5 "$LOG_DIR/stdout.log" 2>/dev/null || echo "  (empty)"
    fi

    if [ -f "$LOG_DIR/stderr.log" ]; then
        echo ""
        echo "Last 5 lines of stderr:"
        tail -5 "$LOG_DIR/stderr.log" 2>/dev/null || echo "  (empty)"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in
    install)   do_install ;;
    uninstall) do_uninstall ;;
    status)    do_status ;;
    *)         usage ;;
esac
