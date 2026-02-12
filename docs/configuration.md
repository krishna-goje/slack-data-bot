# Configuration Reference

Slack Data Bot is configured via a YAML file with optional environment variable expansion.

## Config Resolution Order

The bot searches for configuration in this order, using the first one found:

1. **Explicit path**: `slack-data-bot --config /path/to/config.yaml`
2. **Environment variable**: `SLACK_DATA_BOT_CONFIG=/path/to/config.yaml`
3. **Local file**: `./config.yaml` (current working directory)
4. **Home directory**: `~/.slack-data-bot/config.yaml`
5. **Built-in defaults**: All settings have sensible defaults (bot runs but does nothing without Slack tokens)

## Environment Variable Expansion

Any string value in the YAML can reference environment variables using `${VAR_NAME}` syntax:

```yaml
slack:
  bot_token: ${SLACK_BOT_TOKEN}
  app_token: ${SLACK_APP_TOKEN}
```

If a referenced variable is not set, the bot raises a `ValueError` at startup with a clear message identifying the missing variable.

## Full Configuration Reference

### `slack` -- Slack Connection

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `bot_token` | string | `""` | Slack Bot User OAuth Token (`xoxb-...`). Required for all Slack operations. |
| `app_token` | string | `""` | Slack App-Level Token (`xapp-...`). Required for Socket Mode (interactive buttons). |
| `signing_secret` | string | `""` | Slack Signing Secret. Required for verifying interactive message payloads. |
| `owner_user_id` | string | `""` | Slack User ID of the bot owner. Receives DM notifications and approval requests. |

```yaml
slack:
  bot_token: ${SLACK_BOT_TOKEN}
  app_token: ${SLACK_APP_TOKEN}
  signing_secret: ${SLACK_SIGNING_SECRET}
  owner_user_id: ${SLACK_OWNER_ID}
```

### `monitoring` -- Channel Monitoring

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `poll_interval_minutes` | int | `5` | Minutes between poll cycles. |
| `lookback_days` | int | `7` | How far back to search for unanswered questions. |
| `channels` | list | `[]` | Channels to monitor. Each entry needs `name` and `id`. |
| `domain_keywords` | list | `["quicksight", "dbt", "snowflake", "dashboard"]` | Keywords that indicate a data-related question. |
| `bot_usernames` | list | `["slackbot", "github", "jira"]` | Usernames to treat as bots (messages filtered out). |
| `owner_username` | string | `""` | Your Slack display name. Used for @mention detection and response filtering. |

```yaml
monitoring:
  poll_interval_minutes: 5
  lookback_days: 7
  channels:
    - name: ask-data-team
      id: C01ABCDEF
    - name: analytics-help
      id: C02GHIJKL
  domain_keywords:
    - quicksight
    - dbt
    - snowflake
    - dashboard
    - data model
    - data issue
    - metric
    - report
  bot_usernames:
    - slackbot
    - github
    - jira
    - datadog
    - pagerduty
    - sentry
    - circleci
    - jenkins
  owner_username: your.username
```

### `engine` -- Investigation Engine

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `backend` | string | `"claude_code"` | Investigation backend. Currently supported: `claude_code`. |
| `claude_code_path` | string | `"claude"` | Path to the Claude Code CLI binary. |
| `investigation_timeout` | int | `300` | Maximum seconds per investigation subprocess. |
| `review_timeout` | int | `120` | Maximum seconds per quality review subprocess. |
| `max_concurrent` | int | `3` | Maximum parallel investigation subprocesses. |

```yaml
engine:
  backend: claude_code
  claude_code_path: /usr/local/bin/claude
  investigation_timeout: 300
  review_timeout: 120
  max_concurrent: 3
```

### `delivery` -- Response Delivery

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `mode` | string | `"human_approval"` | `human_approval` sends drafts for review. `auto_respond` posts automatically above the confidence threshold. |
| `auto_respond_confidence` | float | `0.9` | Quality score ratio (score/total) threshold for auto-posting. Only applies when `mode` is `auto_respond`. |

```yaml
delivery:
  mode: human_approval
  auto_respond_confidence: 0.9
```

### `quality` -- Quality Review

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_rounds` | int | `3` | Maximum writer/reviewer iterations. |
| `min_pass_criteria` | int | `5` | Minimum criteria that must PASS to accept the draft (out of total criteria count). |
| `criteria` | list | *(see below)* | Quality criteria names evaluated in each review round. |

Default criteria:
- `data_accuracy` -- Are facts and numbers correct?
- `completeness` -- Does the answer fully address the question?
- `root_cause` -- Does it explain why, not just what?
- `time_period` -- Are time references explicit and correct?
- `tone` -- Is the tone appropriate for the channel?
- `actionable` -- Does it help the user take next steps?
- `caveats` -- Are limitations and assumptions noted?

```yaml
quality:
  max_rounds: 3
  min_pass_criteria: 5
  criteria:
    - data_accuracy
    - completeness
    - root_cause
    - time_period
    - tone
    - actionable
    - caveats
```

### `learning` -- Learning Engine

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `true` | Enable usage tracking and feedback collection. |
| `storage_dir` | string | `"~/.slack-data-bot/learning"` | Directory for JSONL event logs and feedback data. |
| `feedback_tracking` | bool | `true` | Track human corrections (edits, rejections) for analysis. |

```yaml
learning:
  enabled: true
  storage_dir: ~/.slack-data-bot/learning
  feedback_tracking: true
```

### `cache` -- State Persistence

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `directory` | string | `"~/.slack-data-bot"` | Directory for bot state file (`state.json`). |
| `answer_ttl_days` | int | `30` | Days to keep answered-thread entries before pruning. |

```yaml
cache:
  directory: ~/.slack-data-bot
  answer_ttl_days: 30
```

## Example Configurations

### Minimal (poll-only, no interactive buttons)

```yaml
slack:
  bot_token: ${SLACK_BOT_TOKEN}
  owner_user_id: ${SLACK_OWNER_ID}

monitoring:
  channels:
    - name: ask-data-team
      id: C01ABCDEF
  owner_username: krishna.goje
```

### Full Production Setup

```yaml
slack:
  bot_token: ${SLACK_BOT_TOKEN}
  app_token: ${SLACK_APP_TOKEN}
  signing_secret: ${SLACK_SIGNING_SECRET}
  owner_user_id: ${SLACK_OWNER_ID}

monitoring:
  poll_interval_minutes: 3
  lookback_days: 14
  channels:
    - name: ask-data-team
      id: C01ABCDEF
    - name: analytics-help
      id: C02GHIJKL
    - name: data-engineering
      id: C03MNOPQR
  domain_keywords:
    - quicksight
    - dbt
    - snowflake
    - dashboard
    - data model
    - data issue
    - metric
    - pipeline
    - freshness
    - broken
  bot_usernames:
    - slackbot
    - github
    - jira
    - datadog
    - pagerduty
    - sentry
    - circleci
    - jenkins
    - dependabot
  owner_username: krishna.goje

engine:
  backend: claude_code
  claude_code_path: claude
  investigation_timeout: 300
  review_timeout: 120
  max_concurrent: 3

delivery:
  mode: human_approval

quality:
  max_rounds: 3
  min_pass_criteria: 5

learning:
  enabled: true
  storage_dir: ~/.slack-data-bot/learning
  feedback_tracking: true

cache:
  directory: ~/.slack-data-bot
  answer_ttl_days: 60
```

### Auto-Respond Mode (no human approval)

```yaml
slack:
  bot_token: ${SLACK_BOT_TOKEN}
  owner_user_id: ${SLACK_OWNER_ID}

monitoring:
  channels:
    - name: data-faq
      id: C04STUVWX
  owner_username: data.bot

delivery:
  mode: auto_respond
  auto_respond_confidence: 0.85

quality:
  max_rounds: 3
  min_pass_criteria: 6  # stricter for auto mode
```
