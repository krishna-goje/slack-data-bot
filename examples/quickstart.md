# Quickstart Guide

Get Slack Data Bot running in 5 steps.

## Step 1: Install

```bash
pip install slack-data-bot
```

Or from source:

```bash
git clone https://github.com/krishna-goje/slack-data-bot.git
cd slack-data-bot
pip install -e ".[dev]"
```

Verify the installation:

```bash
slack-data-bot --help
```

## Step 2: Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) > **Create New App** > **From scratch**.
2. Name it (e.g., "Data Bot"), select your workspace.
3. Under **OAuth & Permissions**, add these **Bot Token Scopes**:
   - `channels:history`
   - `channels:read`
   - `chat:write`
   - `search:read`
   - `users:read`
   - `reactions:read`
   - `im:read`
   - `im:write`
   - `im:history`
4. Under **Socket Mode**, toggle it **on** to create an App-Level Token.
5. Under **Interactivity & Shortcuts**, toggle **Interactivity** on.
6. Click **Install to Workspace** and authorize.

Collect these values:
- **Bot User OAuth Token** (`xoxb-...`)
- **App-Level Token** (`xapp-...`)
- **Signing Secret** (from Basic Information page)
- **Your Slack User ID** (Profile > ... > Copy member ID)
- **Channel IDs** to monitor (right-click channel > View details > scroll to bottom)

## Step 3: Configure

Set environment variables:

```bash
export SLACK_BOT_TOKEN=xoxb-your-bot-token-here
export SLACK_APP_TOKEN=xapp-your-app-token-here
export SLACK_SIGNING_SECRET=your-signing-secret-here
export SLACK_OWNER_ID=U01ABCDEFG
```

Create a config file:

```bash
mkdir -p ~/.slack-data-bot
cat > ~/.slack-data-bot/config.yaml << 'EOF'
slack:
  bot_token: ${SLACK_BOT_TOKEN}
  app_token: ${SLACK_APP_TOKEN}
  signing_secret: ${SLACK_SIGNING_SECRET}
  owner_user_id: ${SLACK_OWNER_ID}

monitoring:
  poll_interval_minutes: 5
  lookback_days: 7
  channels:
    - name: ask-data-team
      id: C_YOUR_CHANNEL_ID
  domain_keywords:
    - quicksight
    - dbt
    - snowflake
    - dashboard
    - data model
  owner_username: your.slack.username

engine:
  backend: claude_code
  claude_code_path: claude
  investigation_timeout: 300
  max_concurrent: 3

delivery:
  mode: human_approval
EOF
```

Replace `C_YOUR_CHANNEL_ID`, `your.slack.username`, and any other placeholders with your actual values.

## Step 4: Test with Dry Run

Validate your configuration:

```bash
slack-data-bot --config ~/.slack-data-bot/config.yaml --dry-run
```

Expected output:

```
2026-02-12 10:00:00 [INFO] slack_data_bot.bot: Configuration loaded successfully
2026-02-12 10:00:00 [INFO] slack_data_bot.bot: Dry run complete - configuration is valid
```

Run a single poll cycle to see what the bot finds:

```bash
slack-data-bot --config ~/.slack-data-bot/config.yaml --once --verbose
```

This will:
1. Search your configured channels for unanswered questions.
2. Investigate the top questions using Claude Code CLI.
3. Send you DM notifications with draft responses.
4. Exit after one cycle.

## Step 5: Run Continuously

Start the bot as a long-running process:

```bash
slack-data-bot --config ~/.slack-data-bot/config.yaml
```

The bot will:
- Poll every 5 minutes (configurable).
- Listen for interactive button clicks via Socket Mode.
- Send you DM notifications when it finds and investigates questions.
- Post approved responses as thread replies.

For production, set up as a daemon. See [deployment.md](../docs/deployment.md) for launchd (macOS) and systemd (Linux) instructions.

## What Happens Next

1. Someone asks a data question in one of your monitored channels.
2. The bot detects it on the next poll cycle.
3. Claude Code investigates (queries data, reads code, drafts an answer).
4. The draft goes through quality review (up to 3 rounds).
5. You receive a DM with the draft, quality score, and Approve/Edit/Reject buttons.
6. You click **Approve**, and the bot posts the response as a thread reply.

## Troubleshooting

**Bot token not working?**
Make sure all required scopes are added and the app is reinstalled to the workspace after scope changes.

**No questions found?**
Check that `owner_username` matches your Slack display name exactly, and that the channel IDs are correct. Use `--verbose` to see search queries.

**Claude Code not found?**
Verify `claude --help` works in your terminal. If installed to a non-standard path, set `engine.claude_code_path` in your config.

**Interactive buttons not working?**
Socket Mode requires the `app_token` (`xapp-...`). Verify it is set and that Interactivity is enabled in your Slack app settings.
