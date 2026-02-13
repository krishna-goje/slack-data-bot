#!/bin/bash
# Install/uninstall/status the Slack Data Bot launchd daemon
#
# Usage:
#   ~/.slack-data-bot/install-daemon.sh install    # install + start
#   ~/.slack-data-bot/install-daemon.sh uninstall  # stop + remove
#   ~/.slack-data-bot/install-daemon.sh status     # check status + recent logs
#   ~/.slack-data-bot/install-daemon.sh logs       # tail today's log

set -euo pipefail

PLIST_NAME="com.krishna.slack-data-bot"
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

        # Ensure script is executable
        chmod +x "$SCRIPT"

        # Create plist
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

        # Load the daemon
        launchctl load "$PLIST_FILE"
        echo "Installed and loaded: $PLIST_FILE"
        echo "Bot will run every $(( INTERVAL / 60 )) minutes"
        echo "Logs: $LOG_DIR/"
        echo ""
        echo "To start immediately: launchctl start $PLIST_NAME"
        echo "To check status:      ~/.slack-data-bot/install-daemon.sh status"
        echo "To view logs:         ~/.slack-data-bot/install-daemon.sh logs"
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
        if launchctl list | grep -q "$PLIST_NAME"; then
            echo "Status: LOADED"
            launchctl list "$PLIST_NAME" 2>/dev/null || true
        else
            echo "Status: NOT LOADED"
        fi
        echo ""
        echo "=== Recent Cycles ==="
        TODAY=$(date +%Y-%m-%d)
        if [ -f "$LOG_DIR/$TODAY.log" ]; then
            grep "CYCLE START\|CYCLE END\|FOUND:" "$LOG_DIR/$TODAY.log" | tail -20
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
            ls -t "$LOG_DIR"/*.log 2>/dev/null | head -1 | xargs tail -50 2>/dev/null || echo "No logs found."
        fi
        ;;

    run)
        echo "Running single cycle now..."
        bash "$SCRIPT" --learn
        echo "Done. Check: ~/.slack-data-bot/install-daemon.sh logs"
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
        ;;
esac
