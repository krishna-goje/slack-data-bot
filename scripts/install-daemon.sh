#!/usr/bin/env bash
# Slack Data Bot - macOS launchd daemon manager
#
# Setup:
#   1. Copy scripts to ~/.slack-data-bot/:
#      mkdir -p ~/.slack-data-bot/{prompts,logs,learnings}
#      cp scripts/run-cycle.sh ~/.slack-data-bot/
#      cp examples/poll-prompt.md ~/.slack-data-bot/prompts/poll.md
#      chmod +x ~/.slack-data-bot/run-cycle.sh
#
#   2. Customize ~/.slack-data-bot/prompts/poll.md with your username and channels
#
#   3. Install the daemon:
#      ~/.slack-data-bot/install-daemon.sh install
#
# Usage:
#   ~/.slack-data-bot/install-daemon.sh install    # install + load
#   ~/.slack-data-bot/install-daemon.sh uninstall  # stop + remove
#   ~/.slack-data-bot/install-daemon.sh status     # check status + recent logs
#   ~/.slack-data-bot/install-daemon.sh logs       # tail today's log
#   ~/.slack-data-bot/install-daemon.sh run        # single cycle now

set -euo pipefail

PLIST_NAME="com.slack-data-bot.daemon"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/$PLIST_NAME.plist"
BOT_DIR="$HOME/.slack-data-bot"
LOG_DIR="$BOT_DIR/logs"
SCRIPT="$BOT_DIR/run-cycle.sh"
# Run every 5 minutes (300 seconds)
INTERVAL=300

case "${1:-help}" in
    install)
        echo "Installing Slack Data Bot daemon..."

        # Preflight checks
        if [ ! -f "$SCRIPT" ]; then
            echo "ERROR: $SCRIPT not found."
            echo "Run: cp scripts/run-cycle.sh $SCRIPT && chmod +x $SCRIPT"
            exit 1
        fi
        if [ ! -f "$BOT_DIR/prompts/poll.md" ]; then
            echo "ERROR: $BOT_DIR/prompts/poll.md not found."
            echo "Run: cp examples/poll-prompt.md $BOT_DIR/prompts/poll.md"
            echo "Then customize with your Slack username and channels."
            exit 1
        fi

        chmod +x "$SCRIPT"

        mkdir -p "$PLIST_DIR" "$LOG_DIR"
        cat > "$PLIST_FILE" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$SCRIPT</string>
        <string>--learn</string>
    </array>

    <key>StartInterval</key>
    <integer>$INTERVAL</integer>

    <key>WorkingDirectory</key>
    <string>$BOT_DIR</string>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/daemon-stdout.log</string>

    <key>StandardErrorPath</key>
    <string>$LOG_DIR/daemon-stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$HOME/.local/bin:$HOME/bin</string>
        <key>HOME</key>
        <string>$HOME</string>
    </dict>

    <key>RunAtLoad</key>
    <false/>

    <key>KeepAlive</key>
    <false/>

    <key>ThrottleInterval</key>
    <integer>60</integer>
</dict>
</plist>
PLIST

        launchctl load "$PLIST_FILE"
        echo "Installed and loaded: $PLIST_FILE"
        echo "Bot will run every $(( INTERVAL / 60 )) minutes"
        echo "Logs: $LOG_DIR/"
        echo ""
        echo "To start immediately: launchctl start $PLIST_NAME"
        echo "To check status:      $0 status"
        echo "To view logs:         $0 logs"
        ;;

    uninstall)
        echo "Uninstalling Slack Data Bot daemon..."
        if [ -f "$PLIST_FILE" ]; then
            launchctl unload "$PLIST_FILE" 2>/dev/null || true
            rm "$PLIST_FILE"
            echo "Removed: $PLIST_FILE"
        else
            echo "Not installed."
        fi
        ;;

    status)
        echo "=== Slack Data Bot Status ==="
        if launchctl list 2>/dev/null | grep -q "$PLIST_NAME"; then
            echo "Status: LOADED"
            launchctl list "$PLIST_NAME" 2>/dev/null || true
        else
            echo "Status: NOT LOADED"
        fi
        echo ""
        echo "=== Recent Cycles ==="
        TODAY=$(date +%Y-%m-%d)
        if [ -f "$LOG_DIR/$TODAY.log" ]; then
            grep "CYCLE START\|CYCLE END\|FOUND:\|SKIPPED" "$LOG_DIR/$TODAY.log" | tail -20
        else
            echo "No logs for today yet."
        fi
        echo ""
        echo "=== Learnings ==="
        if [ -f "$BOT_DIR/learnings/improvements.jsonl" ]; then
            echo "$(wc -l < "$BOT_DIR/learnings/improvements.jsonl") improvement entries"
            tail -3 "$BOT_DIR/learnings/improvements.jsonl"
        else
            echo "No learnings yet."
        fi
        ;;

    logs)
        TODAY=$(date +%Y-%m-%d)
        LOG="$LOG_DIR/$TODAY.log"
        if [ -f "$LOG" ]; then
            tail -100 "$LOG"
        else
            echo "No log file for today: $LOG"
            echo "Most recent log:"
            # shellcheck disable=SC2012
            ls -t "$LOG_DIR"/*.log 2>/dev/null | head -1 | xargs tail -50 2>/dev/null || echo "No logs found."
        fi
        ;;

    run)
        echo "Running single cycle now..."
        bash "$SCRIPT" --learn
        echo "Done. Check: $0 logs"
        ;;

    *)
        echo "Slack Data Bot Daemon"
        echo ""
        echo "Usage: $0 {install|uninstall|status|logs|run}"
        echo ""
        echo "  install    Install launchd daemon (runs every 5 min)"
        echo "  uninstall  Remove launchd daemon"
        echo "  status     Show daemon status + recent cycles"
        echo "  logs       Show today's log"
        echo "  run        Run one cycle now (with self-learning)"
        echo ""
        echo "Setup:"
        echo "  mkdir -p ~/.slack-data-bot/{prompts,logs,learnings}"
        echo "  cp scripts/run-cycle.sh ~/.slack-data-bot/"
        echo "  cp examples/poll-prompt.md ~/.slack-data-bot/prompts/poll.md"
        echo "  chmod +x ~/.slack-data-bot/run-cycle.sh"
        echo "  # Edit ~/.slack-data-bot/prompts/poll.md with your username + channels"
        ;;
esac
