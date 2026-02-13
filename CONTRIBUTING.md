# Contributing to Slack Data Bot

Thank you for your interest in contributing! This document outlines the development workflow and best practices.

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before participating. For security issues, see [SECURITY.md](SECURITY.md).

## Reporting Issues

Before writing code, check [existing issues](https://github.com/krishna-goje/slack-data-bot/issues) first.

- **Bugs**: Include the error message, Python version, and what triggered the issue
- **Features**: Describe the use case and expected behavior
- **Questions**: Open a discussion or issue with the `question` label

## Prerequisites

- Python 3.10 or higher
- Slack workspace with bot token (for running locally)
- `gh` CLI recommended for PR workflows

## Branch Strategy

```text
main (protected)          <-- production releases only, via PR
  └── feature/xxx         <-- all development work happens here
```

### Rules

- **Never push directly to `main`** -- all changes go through pull requests
- **Feature branches** are created from `main` and merged back via PR
- **Branch naming**: `feature/<description>`, `fix/<description>`, `docs/<description>`
- **Squash merge** PRs to keep `main` history clean
- **CI must pass** before merge (lint + tests run automatically on every PR)

## Development Workflow

### 1. Set Up

```bash
git clone https://github.com/krishna-goje/slack-data-bot.git
cd slack-data-bot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Create a Feature Branch

```bash
git checkout main
git pull origin main
git checkout -b feature/add-mention-detection
```

### 3. Make Changes

Follow these patterns:

- **Bot logic** goes in `src/slack_data_bot/`
- **Configuration** goes in `src/slack_data_bot/config/`
- **Tests** go in `tests/` mirroring the source structure
- Never commit Slack tokens, API keys, or credentials

### 4. Test

```bash
# Lint (must pass before PR)
ruff check src/ tests/

# Run tests
pytest tests/ -v
```

### 5. Commit

```bash
git add <specific-files>
git commit -m "Add @mention detection for data questions

- Parses channel messages for data-related keywords
- Queues matched messages for investigation
- Includes test coverage for keyword matching"
```

Commit message guidelines:
- First line: imperative mood, under 72 chars
- Body: explain *what* and *why*, not *how*
- Reference issue numbers if applicable (e.g., `Fixes #12`)

### 6. Push and Create PR

```bash
git push origin feature/add-mention-detection
gh pr create --title "Add @mention detection" --body "## Summary
- Detects data questions in channel messages
- Queues for AI investigation

## Test plan
- [ ] ruff check passes
- [ ] pytest passes
- [ ] Manual test with Slack test workspace"
```

### 7. Handling Common Issues

**Tests fail locally**: Fix before pushing. Do not open a PR with failing tests.

**PR has merge conflicts**: Rebase onto the latest main:
```bash
git fetch origin
git rebase origin/main
# Resolve conflicts, then:
git push --force-with-lease
```

**Reviewer requests changes**: Push additional commits to the same branch.

**CI fails after push**: Check the Actions tab on GitHub. Fix locally and push a new commit.

### 8. PR Review Checklist

Before merging, verify:

- [ ] CI passes (lint + tests)
- [ ] No secrets: Slack tokens, API keys, or credentials
- [ ] No hardcoded channel IDs or workspace-specific values
- [ ] CHANGELOG.md updated
- [ ] README.md updated if features added

## Release Process

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md` with new version section
3. Create PR: `release/v0.x.0`
4. After merge, tag and push:
   ```bash
   git tag -a v0.x.0 -m "v0.x.0: <summary>"
   git push origin v0.x.0
   ```
5. GitHub Actions automatically builds and publishes to PyPI
