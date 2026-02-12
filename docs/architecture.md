# Architecture

## System Overview

Slack Data Bot is composed of four core modules that form a pipeline: Monitor, Engine, Delivery, and Learning. Each module is self-contained with clean interfaces, making it straightforward to test, extend, or replace individual components.

```
                        +-----------+
                        |  Slack    |
                        |  Search   |
                        |  API      |
                        +-----+-----+
                              |
                              v
+------------------------------------------------------------+
|                       MONITOR                              |
|                                                            |
|  SearchStrategy ----> SlackMonitor ----> MessageFilter     |
|  (8 strategies)       (orchestrator)     (bot/noise)       |
|                            |                               |
|                            v                               |
|                      PriorityScorer ----> Deduplicate      |
|                      (scoring)            (by thread)      |
+-----------------------------+------------------------------+
                              |
                              | list[SlackMessage]
                              v
+------------------------------------------------------------+
|                       ENGINE                               |
|                                                            |
|  InvestigationEngine                                       |
|       |                                                    |
|       +----> ClaudeCodeEngine ----> subprocess             |
|       |      (claude --print)       (Claude Code CLI)      |
|       |                                                    |
|       +----> QualityReviewer                               |
|              (writer/reviewer loop, up to N rounds)        |
+-----------------------------+------------------------------+
                              |
                              | InvestigationResult
                              v
+------------------------------------------------------------+
|                       DELIVERY                             |
|                                                            |
|  Notifier ------> Owner DM (Block Kit)                     |
|                   [Approve] [Edit] [Reject]                |
|                            |                               |
|  ApprovalFlow <--- Slack Interactive Message               |
|       |                                                    |
|       +----> post_approved_response() ---> Original Thread |
+-----------------------------+------------------------------+
                              |
                              v
+------------------------------------------------------------+
|                       LEARNING                             |
|                                                            |
|  UsageTracker ----> JSONL event log (daily files)          |
|  FeedbackCollector ----> feedback.jsonl                    |
|  Optimizer ----> analyze() ----> Recommendations           |
+------------------------------------------------------------+
```

## Monitor Module

**Location**: `src/slack_data_bot/monitor/`

The monitor is responsible for discovering unanswered data questions in Slack. It operates as a pipeline:

### Search Strategies (`search.py`)

Generates 8 complementary search strategies from configuration, each targeting a different signal:

| # | Strategy | Query Pattern | Priority Boost |
|---|----------|---------------|----------------|
| 1 | `direct_mentions` | `@owner after:DATE` | +100 |
| 2 | `channel_questions` | `? in:#channel after:DATE` | +50 |
| 3-5 | `domain_keywords_N` | `(kw1 OR kw2) ? after:DATE` | +30 |
| 6 | `generic_data_questions` | `(model OR data OR ...) ? in:#channel after:DATE` | +20 |
| 7 | `direct_messages` | `to:@owner after:DATE` | +80 |
| 8 | `owner_responses` | `from:@owner after:DATE` | 0 (filtering only) |

Strategy 8 is special -- it finds the owner's own responses, used to filter out threads that have already been answered.

Domain keywords are split into up to 3 groups (strategies 3-5) for better coverage across Slack's search limits.

### Message Filtering (`filter.py`)

`MessageFilter` removes noise through several detection methods:

- **Bot detection**: Checks `username` against configured bot list, `subtype == "bot_message"`, and presence of `bot_id` field.
- **FYI detection**: Regex matches for `cc:`, `fyi:`, `looping in @`, `adding @`, `copying @`. These informational mentions are not questions.
- **Quoted mention detection**: Checks if the `@owner` mention is inside a code block (` ``` `), inline code span (`` ` ``), or blockquote (`>`). Quoted mentions are references, not requests.
- **Question detection**: Regex matches for `?`, `wondering`, `not sure`, `help`, `how do`, `what is`, `where`, `why`, `can you`, `could you`, `do you know`, `any idea`.
- **Domain keyword detection**: Case-insensitive substring match against configured keyword list.
- **Answered thread filtering**: Combines strategy-8 owner responses with the persistent answered cache. Messages whose `channel_id:thread_ts` key appears in either set are excluded.

### Priority Scoring (`priority.py`)

`PriorityScorer` applies additive scoring to each message:

| Signal | Points |
|--------|--------|
| Strategy base boost | varies (see table above) |
| Is a question | +20 |
| Contains domain keyword | +15 |
| FYI-style mention | -30 |
| Not a question | -10 |
| Quoted mention | -50 |

The final score is floored at 0.

### Deduplication (`dedup.py`)

Messages from multiple strategies may overlap. `deduplicate_messages()` groups by `message_id` (defined as `channel_id:thread_ts`) and keeps the version with the highest priority score.

### Orchestration (`slack_monitor.py`)

`SlackMonitor.find_unanswered()` runs the full pipeline:

1. Compute lookback date from config.
2. Generate search strategies.
3. Execute each strategy against Slack Search API (with pagination).
4. Parse results into `SlackMessage` objects, separating owner responses.
5. Score each message.
6. Filter out answered threads.
7. Deduplicate.
8. Sort by priority descending.

## Engine Module

**Location**: `src/slack_data_bot/engine/`

The engine investigates questions and produces quality-reviewed draft answers.

### Claude Code CLI (`claude_code.py`)

`ClaudeCodeEngine` wraps the Claude Code CLI binary:

- Spawns `claude --print -p "prompt"` as a subprocess.
- Uses a `threading.Semaphore` to limit concurrent CLI processes to `max_concurrent`.
- Configurable investigation timeout (default 300s) and review timeout (default 120s).
- Strips ANSI escape codes and CLI chrome from output.
- Raises `ClaudeCodeError` on timeout, non-zero exit, empty output, or binary-not-found.

Two public methods:
- `investigate(question, context)` -- builds an investigation prompt and runs it.
- `review_draft(question, draft)` -- builds a quality review prompt and runs it.

### Investigation Orchestrator (`investigator.py`)

`InvestigationEngine.investigate(message)` coordinates the full pipeline:

1. Build context string from the `SlackMessage` (channel, user, thread info, priority, permalink).
2. Call `ClaudeCodeEngine.investigate()` to get the initial draft.
3. Pass the draft through `QualityReviewer.review_and_improve()`.
4. Return an `InvestigationResult` with the final draft, quality score, round count, and approval status.

Error handling is defensive -- if investigation fails, returns an error message with `quality_score=0`. If quality review fails, returns the initial draft unreviewed.

### Quality Reviewer (`quality.py`)

`QualityReviewer` implements a writer/reviewer loop:

1. Ask Claude Code to review the draft against configured criteria.
2. Parse the output for `CRITERION_NAME: PASS/FAIL` lines and a `## Feedback` section.
3. If the score meets `min_pass_criteria` (default: 5 of 7), stop and return.
4. Otherwise, feed the failed criteria and feedback back as revision context.
5. After `max_rounds` (default: 3), return the best version seen across all rounds.

Default quality criteria:
- `data_accuracy`
- `completeness`
- `root_cause`
- `time_period`
- `tone`
- `actionable`
- `caveats`

## Delivery Module

**Location**: `src/slack_data_bot/delivery/`

### Notifier (`notifier.py`)

`Notifier` sends Block Kit DM notifications to the bot owner containing:

- Header: "New Question for Review"
- Question block: channel, user, relative time, permalink
- Draft block: quality score bar (`[####--] 4/6`), draft text (truncated at 2900 chars)
- Action block: Approve (primary), Edit, Reject (danger) buttons

Also sends error notifications when investigation fails.

### Approval Flow (`approval.py`)

`ApprovalFlow` manages the lifecycle of pending approvals:

- **Submit**: Stores `PendingApproval(message, draft)` indexed by both `approval_id` and `message_id`. Evicts oldest entries when exceeding 200 pending.
- **Handle action**: Maps `action_id` string to `ApprovalAction` enum (APPROVE, EDIT, REJECT).
- **Post**: On approval, posts the draft as a threaded reply via `chat.postMessage` with `thread_ts`.

## Learning Module

**Location**: `src/slack_data_bot/learning/`

### Usage Tracker (`tracker.py`)

Logs events to daily JSONL files (`~/.slack-data-bot/learning/events/YYYY-MM-DD.jsonl`):

- `question`: channel, user, classification, priority
- `investigation`: duration, success/failure
- `approval`: action (approved/rejected), response time

`get_stats(days)` aggregates across files for reporting.

### Feedback Collector (`feedback.py`)

Records human corrections in `feedback.jsonl`:

- Original draft, action taken, edited text (if edited), rejection reason (if rejected).
- `get_common_corrections()` counts rejection reasons and edit-heavy channels.

### Optimizer (`optimizer.py`)

Analyzes tracker and feedback data to produce `Recommendation` objects:

- **High rejection rate** (>30%): suggests prompt refinement.
- **Slow investigations** (>120s average): suggests caching or pre-computation.
- **Channel tuning**: flags channels with many rejections.
- **Common corrections**: surfaces the most frequent rejection reason.

`generate_report()` produces a human-readable performance summary.

## Data Flow

```
1. Timer fires (every 5 min)
        |
2. SlackMonitor.find_unanswered()
        |-- generate_search_strategies() --> 8 strategies
        |-- _search_slack() x 8          --> raw results
        |-- _parse_results()             --> SlackMessage list
        |-- PriorityScorer.score()       --> scored messages
        |-- filter_answered()            --> unanswered only
        |-- deduplicate_messages()       --> unique messages
        |
3. SlackDataBot._process_question() for each (up to max_concurrent)
        |
4. InvestigationEngine.investigate(message)
        |-- ClaudeCodeEngine.investigate()   --> initial draft
        |-- QualityReviewer.review_and_improve()
        |       |-- review round 1 --> score < threshold? --> revise
        |       |-- review round 2 --> score < threshold? --> revise
        |       |-- review round 3 --> return best
        |
5. Notifier.notify_human() --> DM to owner with Block Kit
        |
6. ApprovalFlow.submit_for_approval() --> store pending
        |
7. Human clicks [Approve]
        |-- ApprovalFlow.post_approved_response() --> thread reply
        |-- BotState.mark_answered()
        |-- UsageTracker.record_approval()
```

## Configuration Flow

```
load_config(path)
    |
    +-- Explicit path argument?  --> BotConfig.from_yaml(path)
    |
    +-- SLACK_DATA_BOT_CONFIG env var?  --> BotConfig.from_yaml(env_path)
    |
    +-- ./config.yaml exists?  --> BotConfig.from_yaml("config.yaml")
    |
    +-- ~/.slack-data-bot/config.yaml exists?  --> BotConfig.from_yaml(home_path)
    |
    +-- None of the above?  --> BotConfig.default()

BotConfig.from_yaml(path):
    1. Read YAML file
    2. Recursively expand ${ENV_VAR} references
    3. Parse into dataclass hierarchy
```
