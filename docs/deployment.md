# Deployment Guide

## Prerequisites

- **Python 3.10+** (3.12 recommended)
- **Claude Code CLI** installed and authenticated (`claude --help` works)
- **Slack App** with the required bot token scopes (see below)
- **Network access** to Slack API from the deployment host

## Slack App Setup

### 1. Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**.
2. Choose **From scratch**.
3. Name it (e.g., "Data Bot") and select your workspace.

### 2. Configure Bot Token Scopes

Under **OAuth & Permissions** > **Scopes** > **Bot Token Scopes**, add:

| Scope | Purpose |
|-------|---------|
| `channels:history` | Read messages in public channels |
| `channels:read` | List channels and get channel info |
| `chat:write` | Post approved responses as the bot |
| `search:read` | Search messages across channels |
| `users:read` | Resolve user IDs to display names |
| `reactions:read` | Read emoji reactions (for feedback signals) |
| `im:read` | Read DMs sent to the bot |
| `im:write` | Send DM notifications to the owner |
| `im:history` | Read DM history for context |

### 3. Enable Socket Mode (for interactive buttons)

Under **Socket Mode**, toggle it on. This generates an **App-Level Token** (`xapp-...`).

Under **Interactivity & Shortcuts**, toggle **Interactivity** on. Socket Mode handles the request URL automatically.

### 4. Install to Workspace

Under **Install App**, click **Install to Workspace** and authorize. Copy:

- **Bot User OAuth Token** (`xoxb-...`) -> `SLACK_BOT_TOKEN`
- **App-Level Token** (`xapp-...`) -> `SLACK_APP_TOKEN`
- **Signing Secret** (from Basic Information) -> `SLACK_SIGNING_SECRET`

### 5. Get Your User ID

In Slack, click your profile picture > **Profile** > click the **...** menu > **Copy member ID**. This is your `SLACK_OWNER_ID`.

### 6. Get Channel IDs

Right-click a channel name > **View channel details** > scroll to the bottom to find the Channel ID (`C...`).

## Installation Methods

### Method 1: pip install (recommended)

```bash
pip install slack-data-bot
```

### Method 2: From source

```bash
git clone https://github.com/krishna-goje/slack-data-bot.git
cd slack-data-bot
pip install -e .
```

### Method 3: In a virtualenv

```bash
python3 -m venv ~/.slack-data-bot/venv
source ~/.slack-data-bot/venv/bin/activate
pip install slack-data-bot
```

## macOS: launchd Daemon

The included `scripts/install-daemon.sh` script sets up a macOS launchd agent that runs on login.

### Install

```bash
# Make executable
chmod +x scripts/install-daemon.sh

# Install the daemon
./scripts/install-daemon.sh install
```

This creates `~/Library/LaunchAgents/com.slack-data-bot.plist` with:
- Runs on load (login)
- Restarts on failure (with 60s throttle)
- Logs to `~/.slack-data-bot/logs/`
- Uses your config at `~/.slack-data-bot/config.yaml`

### Manage

```bash
# Check status
./scripts/install-daemon.sh status

# Uninstall
./scripts/install-daemon.sh uninstall
```

### Manual launchd commands

```bash
# Load (start)
launchctl load ~/Library/LaunchAgents/com.slack-data-bot.plist

# Unload (stop)
launchctl unload ~/Library/LaunchAgents/com.slack-data-bot.plist

# Check if running
launchctl list | grep slack-data-bot
```

## Linux: systemd Service

### Create the service file

```bash
sudo tee /etc/systemd/system/slack-data-bot.service > /dev/null << 'EOF'
[Unit]
Description=Slack Data Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USERNAME
Group=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME
ExecStart=/home/YOUR_USERNAME/.local/bin/slack-data-bot --config /home/YOUR_USERNAME/.slack-data-bot/config.yaml
Restart=on-failure
RestartSec=60
StandardOutput=journal
StandardError=journal

# Environment variables
EnvironmentFile=/home/YOUR_USERNAME/.slack-data-bot/env

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/YOUR_USERNAME/.slack-data-bot

[Install]
WantedBy=multi-user.target
EOF
```

### Create the environment file

```bash
cat > ~/.slack-data-bot/env << 'EOF'
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_APP_TOKEN=xapp-your-token
SLACK_SIGNING_SECRET=your-secret
SLACK_OWNER_ID=U_YOUR_ID
EOF
chmod 600 ~/.slack-data-bot/env
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable slack-data-bot
sudo systemctl start slack-data-bot
```

### Manage

```bash
sudo systemctl status slack-data-bot   # Check status
sudo systemctl restart slack-data-bot  # Restart
sudo systemctl stop slack-data-bot     # Stop
journalctl -u slack-data-bot -f        # Follow logs
```

## Docker (Optional)

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install Claude Code CLI (adjust for your setup)
# RUN npm install -g @anthropic/claude-code

COPY . .
RUN pip install --no-cache-dir .

# Config and state volumes
VOLUME ["/config", "/data"]

ENV SLACK_DATA_BOT_CONFIG=/config/config.yaml

CMD ["slack-data-bot", "--config", "/config/config.yaml"]
```

### Build and run

```bash
docker build -t slack-data-bot .
docker run -d \
  --name slack-data-bot \
  --restart unless-stopped \
  -v ~/.slack-data-bot:/config:ro \
  -v ~/.slack-data-bot:/data \
  -e SLACK_BOT_TOKEN \
  -e SLACK_APP_TOKEN \
  -e SLACK_SIGNING_SECRET \
  -e SLACK_OWNER_ID \
  slack-data-bot
```

**Note**: Docker deployment requires Claude Code CLI to be available inside the container. This may require additional setup depending on your Claude Code installation method and authentication.

## Monitoring and Logs

### Log locations

| Method | Location |
|--------|----------|
| Foreground | stdout/stderr |
| launchd | `~/.slack-data-bot/logs/stdout.log`, `~/.slack-data-bot/logs/stderr.log` |
| systemd | `journalctl -u slack-data-bot` |
| Docker | `docker logs slack-data-bot` |

### Verbose logging

Add `--verbose` to the command for DEBUG-level output:

```bash
slack-data-bot --config config.yaml --verbose
```

### Health checks

Run a single cycle to verify the bot is working:

```bash
slack-data-bot --once --verbose
```

### Performance report

The learning module tracks usage. To generate a report, use the optimizer programmatically:

```python
from slack_data_bot.config import load_config
from slack_data_bot.learning import UsageTracker
from slack_data_bot.learning.optimizer import Optimizer

config = load_config()
tracker = UsageTracker(config.learning)
optimizer = Optimizer(config.learning, tracker=tracker)
print(optimizer.generate_report())
```

### State file

The bot persists state to `~/.slack-data-bot/state.json`, including:

- `answered`: Messages already responded to (prevents re-processing).
- `in_progress`: Messages currently being investigated.
- `queue`: Pending investigation queue.
- `stats`: Counters for total questions and answers.

Old entries are pruned after `answer_ttl_days` (default: 30).
