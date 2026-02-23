---
name: summon
description: Start a Slack-bridged Claude Code session using summon-claude. Use when the user wants to "start a Slack session", "summon to Slack", "bridge to Slack", "share this session on Slack", or "connect to Slack".
---

# Summon — Bridge Claude Code to Slack

## Prerequisites
- summon-claude must be installed: `uv tool install summon-claude`
- Run `summon init` first to configure Slack credentials

## Starting a Session

Run in a terminal:
```bash
summon start
```

This will:
1. Print a 6-character auth code to the terminal
2. Wait for authentication via Slack

The user then types `/summon <CODE>` in Slack to authenticate.
Once authenticated, a dedicated Slack channel is created and all interaction happens there.

## Options

- `summon start --cwd /path/to/project` — Set working directory
- `summon start --name my-feature` — Name the session (affects channel name)
- `summon start --model claude-sonnet-4-20250514` — Override model
- `summon start --resume SESSION_ID` — Resume a previous session

## Managing Sessions

- `summon status` — Show active sessions
- `summon status SESSION_ID` — Detailed session info
- `summon stop SESSION_ID` — Stop a running session
- `summon sessions` — List all recent sessions
- `summon cleanup` — Remove stale entries

## Configuration

- `summon config show` — View current config
- `summon config set KEY VALUE` — Update a setting
- `summon config path` — Show config file location
