# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes                |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, email **krishna19.gk@gmail.com** with:

1. Description of the vulnerability
2. Steps to reproduce
3. Potential impact
4. Suggested fix (if any)

You will receive a response within 48 hours. If the issue is confirmed, a fix will be released as a patch version and you will be credited in the changelog (unless you prefer to remain anonymous).

## Security Considerations

This project interacts with Slack APIs and AI services. Users should be aware of:

- **Slack Tokens**: Never commit bot tokens, user tokens, or signing secrets. Use environment variables.
- **API Keys**: AI service API keys (Anthropic, OpenAI, etc.) must never be committed. Use environment variables or secrets managers.
- **Channel Data**: The bot reads Slack messages which may contain sensitive business data. Ensure your deployment follows your organization's data handling policies.
- **Configuration Files**: `config.yaml` and `.env` files may contain credentials. Both are in `.gitignore` but verify before committing.
- **State Files**: `state.json` tracks bot state and may contain channel/message IDs. It is in `.gitignore`.
