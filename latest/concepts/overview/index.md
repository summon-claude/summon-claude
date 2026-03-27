# Architecture Overview

summon-claude bridges Slack to Claude Code sessions through a long-running background daemon. All Slack input and output flows through a single daemon process that manages concurrent sessions, each of which runs a Claude SDK subprocess.

## System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          Slack                                  │
│  (channels, messages, files, interactive buttons, slash cmd)    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Socket Mode (bidirectional WebSocket)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  BoltRouter (single Bolt app for the daemon)                    │
│  Rate limiter · Health monitor · Event routing                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  EventDispatcher (routes events by channel → session)            │
└──────────────────────────┬───────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
┌──────────────────┐ ┌──────────┐ ┌──────────┐
│  SessionManager  │ │ Session  │ │ Session  │  (N concurrent sessions)
│  IPC · lifecycle │ │          │ │          │
└──────────────────┘ └─────┬────┘ └──────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
  ┌──────────────┐  ┌─────────────┐  ┌───────────────┐
  │  SlackClient │  │ ThreadRouter│  │ResponseStreamer│
  │  (output)    │  │ (routing)   │  │ (streaming)   │
  └──────┬───────┘  └─────────────┘  └───────────────┘
         │
         ▼
  ┌──────────────┐
  │  CanvasStore │  (SQLite-backed canvas sync)
  └──────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  summon CLI MCP server (summon_cli_mcp.py)                       │
│  session_list · session_info · session_start · session_stop      │
│  session_message · session_resume · session_status_update        │
│  (wired into Claude sessions via SessionManager + Registry)      │
└──────────────────────────────────────────────────────────────────┘
```

## Data Flow

A message from a Slack user to Claude follows this path:

1. **Slack → BoltRouter**: Slack delivers the message event over Socket Mode WebSocket. BoltRouter's `_on_message` handler receives it and calls `EventDispatcher.dispatch_message`.
1. **EventDispatcher → Session**: The dispatcher looks up the channel ID in its `_sessions` dict and pushes the message onto the matching `SessionHandle.message_queue`.
1. **Session → Claude SDK**: The session task reads from its queue and calls `claude_agent_sdk` with the message text. Claude runs as a subprocess.
1. **Claude SDK → Response streaming**: SDK events stream back as `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`, and `ResultMessage`. The response streamer converts these to Slack output.
1. **SlackClient → Slack**: Output posts to the session channel via `AsyncWebClient`, organized into threads by `ThreadRouter`.

## Component Responsibilities

| Component           | Responsibility                                                                                                                                     |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **BoltRouter**      | Owns the single Slack `AsyncApp` + `AsyncSocketModeHandler`. Registers Bolt event/action/command handlers. Manages socket health and reconnection. |
| **EventDispatcher** | Maps `channel_id → SessionHandle`. Routes messages, reactions, and interactive actions to the correct session's queue.                             |
| **SessionManager**  | Lifecycle for all session asyncio tasks. Handles the Unix socket IPC control API. Bridges `/summon` auth codes to waiting sessions.                |
| **SummonSession**   | Per-session orchestrator. Runs the Claude SDK query loop, manages threading, permissions, and streaming.                                           |
| **SessionRegistry** | SQLite session store. Single source of truth for session state visible to the CLI and across daemon restarts.                                      |
| **SlackClient**     | Channel-bound output client. All posts, reactions, uploads, and canvas writes go through here. Redacts secrets before any output.                  |
| **ThreadRouter**    | Routes messages to the main channel, the active turn thread, or a subagent thread depending on context.                                            |
| **CanvasStore**     | SQLite-backed canvas markdown state. Synchronizes to Slack canvas API in the background with debounce and backoff.                                 |

## Package Structure

```
src/summon_claude/
├── config.py              # pydantic-settings config, XDG paths, plugin discovery
├── canvas_mcp.py          # Canvas MCP tools (standalone server)
├── daemon.py              # Daemon lifecycle, IPC framing, watchdog layers
├── event_dispatcher.py    # Slack event → session routing
├── github_auth.py         # GitHub OAuth App device flow authentication
├── mcp_untrusted_proxy.py # MCP stdio proxy for untrusted tool results
├── security.py            # Prompt injection defense utilities
├── slack_browser.py       # External Slack monitoring via Playwright
├── summon_cli_mcp.py      # MCP tools for Claude agent session management
├── cli/
│   ├── __init__.py        # CLI entry point, global flags, subcommands
│   ├── auth.py            # Auth group: unified auth for GitHub, Google, Slack
│   ├── config.py          # Config subcommand handlers
│   ├── daemon_client.py   # Typed async client for daemon Unix socket API
│   ├── db.py              # DB maintenance commands (status, vacuum, purge)
│   ├── formatting.py      # CLI output formatting helpers
│   ├── helpers.py         # Session resolution, stop helpers
│   ├── hooks.py           # Lifecycle hooks CLI
│   ├── interactive.py     # TTY-aware interactive selection
│   ├── preflight.py       # Claude CLI preflight checks
│   ├── project.py         # Project subcommand implementations
│   ├── reset.py           # Reset commands (data, config)
│   ├── session.py         # Session subcommand logic (list, info, logs, cleanup)
│   ├── slack_auth.py      # External Slack workspace auth helpers
│   ├── start.py           # Start command (auth code flow, daemon delegation)
│   ├── stop.py            # Stop command logic
│   └── update_check.py    # PyPI update checker (24h cache)
├── sessions/
│   ├── session.py         # Session orchestrator: SDK + Slack + permissions + streaming
│   ├── manager.py         # Session lifecycle, IPC control plane
│   ├── registry.py        # SQLite registry, WAL mode, audit log
│   ├── migrations.py      # Schema versioning, single source of truth
│   ├── auth.py            # Short-code generation, verification, spawn tokens
│   ├── commands.py        # !-prefixed command dispatch and passthrough
│   ├── context.py         # Context window tracking via JSONL transcript
│   ├── hook_types.py      # Hook type constants
│   ├── hooks.py           # Lifecycle hook execution
│   ├── permissions.py     # Debounced permission batching, Slack buttons
│   ├── response.py        # Response streaming, turn threads, emoji lifecycle
│   ├── scheduler.py       # SessionScheduler for cron jobs
│   └── types.py           # Session type definitions
└── slack/
    ├── bolt.py            # Bolt app, rate limiter, health monitor
    ├── client.py          # Channel-bound output client, secret redaction
    ├── router.py          # Thread-aware message routing
    ├── canvas_store.py    # SQLite-backed canvas sync
    ├── canvas_templates.py # Canvas markdown templates
    ├── formatting.py      # Markdown → Slack mrkdwn conversion
    ├── markdown_split.py  # Markdown splitting for Slack limits
    └── mcp.py             # MCP tools for Claude to interact with Slack
```

## Threading Model

All concurrent sessions run as asyncio tasks within the single daemon process. The event loop is single-threaded — no mutex is needed for in-memory state like `EventDispatcher._sessions`. SQLite access uses `aiosqlite` for non-blocking I/O.

File I/O (logging) uses `QueueHandler` + `QueueListener`: log records are enqueued instantly in the event loop and written to disk by a background thread, preventing file I/O from stalling the event loop.

## Related Pages

- [Daemon Process](https://summon-claude.github.io/summon-claude/latest/concepts/daemon/index.md) — daemonization, IPC, watchdog
- [Slack Integration](https://summon-claude.github.io/summon-claude/latest/concepts/slack-integration/index.md) — BoltRouter, Socket Mode, canvas
- [Database](https://summon-claude.github.io/summon-claude/latest/concepts/database/index.md) — SQLite schema, migrations
- [Security](https://summon-claude.github.io/summon-claude/latest/concepts/security/index.md) — auth, permissions, secret redaction
