# Slack Data Bot

Autonomous Slack bot that monitors channels for data questions, investigates answers using AI (Claude Code CLI), and drafts responses with human-in-the-loop approval.

Built for data teams who get the same kinds of questions in Slack -- dashboard issues, metric definitions, data freshness, broken reports. Instead of context-switching every time, the bot watches your channels, investigates autonomously, and sends you a draft to approve with one click.

## Architecture

```
Slack Channels          slack-data-bot                    Claude Code CLI
+---------------+    +--------------------+             +----------------+
|               |    |                    |             |                |
| #ask-data     |--->|  Monitor           |             |  Investigation |
| #analytics    |    |  - 8 search strats |------------>|  - Query data  |
| DMs to owner  |    |  - Bot filtering   |   question  |  - Read code   |
|               |    |  - Dedup + scoring  |             |  - Verify      |
+---------------+    |                    |<------------|  - Draft reply |
                     |  Engine            |    draft    |                |
                     |  - Claude Code CLI |             +----------------+
                     |  - Quality loop    |
                     |  - Writer/Reviewer |
                     |                    |
                     |  Delivery          |    +-------------------+
                     |  - DM to owner     |--->| Owner's DM        |
                     |  - Approve/Edit/   |    | [Approve] [Edit]  |
                     |    Reject buttons  |    | [Reject]          |
                     |  - Post to thread  |    +-------------------+
                     |                    |             |
                     |  Learning          |             | approved
                     |  - Usage tracking  |             v
                     |  - Feedback loop   |    +-------------------+
                     |  - Optimizer       |    | Original Thread   |
                     +--------------------+    | Bot: "Here's..." |
                                               +-------------------+
```

## Features

- **8-strategy Slack search** -- direct mentions, channel questions, domain keywords, generic data questions, DMs, and owner-response filtering. No blind spots.
- **Bot and noise filtering** -- configurable bot username list, FYI-mention detection, quoted-mention suppression, question-word matching.
- **Priority scoring** -- additive scoring with strategy boosts, question signals, domain keyword signals, and FYI/quoted penalties. Highest-priority questions processed first.
- **Thread deduplication** -- messages from multiple strategies merged by thread ID, keeping the highest-priority version.
- **Claude Code CLI investigation** -- spawns `claude --print -p "prompt"` subprocess with configurable timeout and concurrency semaphore.
- **Writer/Reviewer quality loop** -- iterates up to N rounds evaluating the draft against 7 quality criteria (accuracy, completeness, root cause, time period, tone, actionability, caveats). Stops early when threshold met.
- **Human approval flow** -- sends Block Kit notification to your DM with Approve/Edit/Reject buttons. Approved drafts posted as thread replies.
- **Learning engine** -- tracks questions, investigations, approvals, and rejections in JSONL files. Feedback collector analyzes correction patterns. Optimizer produces actionable recommendations.
- **YAML configuration** -- environment variable expansion (`${VAR}`), sensible defaults, resolution order (CLI flag > env var > local file > home dir > defaults).

## Quick Start

### Install

```bash
pip install slack-data-bot
```

Or from source:

```bash
git clone https://github.com/krishna-goje/slack-data-bot.git
cd slack-data-bot
pip install -e ".[dev]"
```

### Configure

```bash
cp examples/config.yaml.example config.yaml
# Edit config.yaml with your Slack tokens and channel IDs
```

Set environment variables for secrets:

```bash
export SLACK_BOT_TOKEN=xoxb-your-bot-token
export SLACK_APP_TOKEN=xapp-your-app-token
export SLACK_SIGNING_SECRET=your-signing-secret
export SLACK_OWNER_ID=U_YOUR_USER_ID
```

### Run

```bash
# Validate configuration
slack-data-bot --dry-run

# Run a single poll cycle
slack-data-bot --once

# Run continuously
slack-data-bot --config config.yaml
```

## Configuration Reference

See [docs/configuration.md](docs/configuration.md) for the complete reference. Key sections:

| Section | Purpose |
|---------|---------|
| `slack` | Bot token, app token, signing secret, owner user ID |
| `monitoring` | Poll interval, lookback window, channels, keywords, bot filter list |
| `engine` | Backend selection, CLI path, timeouts, concurrency |
| `delivery` | Approval mode (human_approval or auto_respond), confidence threshold |
| `quality` | Max review rounds, minimum pass criteria, criteria list |
| `learning` | Enable/disable, storage directory, feedback tracking |
| `cache` | State directory, answer TTL |

## How It Works

### 1. Poll

Every N minutes (default: 5), the monitor generates 8 search strategies from your config and queries the Slack Search API. Results are parsed, filtered (bots removed, answered threads excluded), deduplicated, and priority-sorted.

### 2. Investigate

The top questions (up to `max_concurrent`) are sent to the Claude Code CLI. Each investigation spawns a subprocess that has access to your data tools (Snowflake, dbt, dashboards) through Claude Code's MCP integrations.

### 3. Quality Review

The draft answer goes through a writer/reviewer loop. Claude reviews the draft against 7 criteria. If fewer than `min_pass_criteria` pass, the feedback is fed back for revision. Up to `max_rounds` iterations.

### 4. Notify

The owner receives a DM with:
- Original question summary and link
- Quality score indicator
- Draft response text
- Approve / Edit / Reject buttons

### 5. Approve and Post

On **Approve**, the bot posts the draft as a threaded reply in the original channel. On **Reject**, the feedback is logged for the learning engine. On **Edit**, the owner modifies the draft manually.

## Development

```bash
# Clone and install
git clone https://github.com/krishna-goje/slack-data-bot.git
cd slack-data-bot
pip install -e ".[dev]"

# Lint
ruff check src/ tests/

# Test
pytest tests/ -v

# Run locally
slack-data-bot --config config.yaml --verbose
```

### Project Structure

```
src/slack_data_bot/
    bot.py              # Main orchestrator and CLI entry point
    config.py           # YAML config with env var expansion
    monitor/
        slack_monitor.py    # Search + filter + dedup + prioritize
        search.py           # 8-strategy search generation
        filter.py           # Bot detection, FYI filtering, answer tracking
        priority.py         # Additive priority scoring
        dedup.py            # SlackMessage dataclass + deduplication
    engine/
        claude_code.py      # Claude Code CLI subprocess wrapper
        investigator.py     # Investigation orchestration
        quality.py          # Writer/Reviewer quality loop
    delivery/
        notifier.py         # Block Kit DM notifications
        approval.py         # Approve/Edit/Reject flow
    learning/
        tracker.py          # JSONL usage event tracking
        feedback.py         # Human correction patterns
        optimizer.py        # Improvement recommendations
    cache/
        state.py            # Bot state persistence (answered, queue, stats)
```

## License

MIT License. See [LICENSE](LICENSE) for details.
