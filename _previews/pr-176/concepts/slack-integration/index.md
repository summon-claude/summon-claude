# Slack Integration

summon-claude uses the Slack Bolt framework with Socket Mode for bidirectional communication. All Slack input flows through a single `BoltRouter`; all output goes through per-session `SlackClient` instances.

## BoltRouter

`BoltRouter` owns exactly one `AsyncApp` + `AsyncSocketModeHandler` pair for the lifetime of the daemon. This means a single WebSocket connection to Slack handles all concurrent sessions.

Bolt handlers are registered in `_register_handlers()`:

| Event / Action                                   | Handler                                                                      |
| ------------------------------------------------ | ---------------------------------------------------------------------------- |
| `/summon` slash command                          | `_on_summon_command` → rate limit check → `EventDispatcher.dispatch_command` |
| `message` event                                  | `_on_message` → `EventDispatcher.dispatch_message`                           |
| `reaction_added` event                           | `_on_reaction_added` → `EventDispatcher.dispatch_reaction`                   |
| `permission_approve` / `permission_deny` actions | `_on_dispatch_action` → `EventDispatcher.dispatch_action`                    |
| `ask_user_*` actions                             | `_on_dispatch_action` → `EventDispatcher.dispatch_action`                    |

Handlers are re-registered on every `reconnect()` call because `AsyncApp` instances are created fresh — Bolt does not support attaching handlers to an existing app after construction.

## Socket Mode

Socket Mode connects to Slack over a bidirectional WebSocket (no public HTTP endpoint required). The `AsyncSocketModeHandler` manages the WebSocket lifecycle. `BoltRouter.start()` calls `handler.connect_async()` and caches the bot's `user_id` via `auth.test`.

The `_RateLimiter` class enforces a 2-second per-user cooldown on `/summon` commands to prevent brute-force short-code guessing.

The `AsyncWebClient` is created once and shared across reconnects — it uses `AsyncRateLimitErrorRetryHandler` and `AsyncServerErrorRetryHandler` from the Slack SDK for automatic retry on HTTP 429 and 5xx responses.

## EventDispatcher

`EventDispatcher` maintains a `dict[channel_id, SessionHandle]` — the in-memory registry of running sessions. It routes incoming Slack events by channel ID.

Events for channels with no registered session are silently dropped. This is intentional: channels from previous sessions, bot DMs, and unrelated workspace activity are all ignored.

Each `SessionHandle` contains:

- `message_queue`: asyncio queue the session reads user messages from
- `permission_handler`: handles button-click actions for tool approval
- `abort_callback`: zero-argument callable that cancels the current Claude turn
- `authenticated_user_id`: the Slack user who owns the session

## SlackClient

`SlackClient` is a channel-bound output client created after a session channel exists. All session output goes through it.

Output methods:

| Method               | Description                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------- |
| `post()`             | Post a message (with optional thread_ts and Block Kit blocks)                               |
| `update()`           | Edit an existing message by timestamp                                                       |
| `react()`            | Add a reaction emoji to a message                                                           |
| `unreact()`          | Remove a reaction emoji                                                                     |
| `upload_file()`      | Upload a file snippet (for large outputs)                                                   |
| `post_ephemeral()`   | Post a message visible only to one user                                                     |
| `post_interactive()` | Post a message with interactive buttons (for permission prompts, deleted after interaction) |
| `delete_message()`   | Delete a message by timestamp (best-effort)                                                 |
| `canvas_create()`    | Create a channel canvas                                                                     |
| `canvas_sync()`      | Replace canvas body content                                                                 |
| `canvas_rename()`    | Update canvas title                                                                         |
| `get_canvas_id()`    | Look up the canvas ID for the channel                                                       |

Every output method calls `redact_secrets()` before sending to Slack. See [Security](https://summon-claude.github.io/summon-claude/concepts/security/index.md) for the redaction pattern.

## ThreadRouter

`ThreadRouter` provides three routing destinations within a session channel:

| Destination            | When used                                                                                                         |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------- |
| **Main channel**       | Text output before any tool use in a turn; conclusion text after tool use (with `@mention` prefix on first chunk) |
| **Active turn thread** | Tool use, tool results, permission requests, streaming tool output                                                |
| **Subagent thread**    | Activity from `Task` tool subagents (nested Claude instances)                                                     |

Each Claude turn opens a thread starter message (`Turn N: re: <snippet>`). The starter updates with a summary on completion: file counts, tool call count, context usage (`42k/200k (21%)`).

## Rate Limiting and Retry

The `AsyncWebClient` has automatic retry built in via `AsyncRateLimitErrorRetryHandler` (respects Slack's `Retry-After` header on HTTP 429) and `AsyncServerErrorRetryHandler` (retries on 5xx responses).

The `/summon` slash command has an additional in-process rate limiter: 2-second cooldown per Slack user ID, enforced before any database lookup.

## Markdown Conversion

Claude responses are formatted as CommonMark markdown. Before posting to Slack, they are converted to Slack mrkdwn format using the `markdown-to-mrkdwn` library (`slack/formatting.py`).

Conversion handles:

- Headers (`# H1` → `*H1*` bold)
- Bold and italic (`**text**`, `_text_`)
- Inline code and fenced code blocks (preserved as ``` `` ``` or triple-backtick blocks)
- Lists (bullets and numbered)
- Links (`[text](url)` → `<url|text>`)

Large outputs (over `SUMMON_MAX_INLINE_CHARS`, default 2500 characters) are uploaded as file snippets instead of posted inline.

## Canvas Integration

Each session channel can have one Slack canvas. `CanvasStore` (`slack/canvas_store.py`) maintains a local SQLite copy of the canvas markdown content and synchronizes to Slack in the background.

**Write path:**

1. Claude calls `summon_canvas_write` or `summon_canvas_update_section` via MCP.
1. `CanvasStore` updates the local SQLite record immediately (synchronous from Claude's perspective).
1. The store marks itself dirty and schedules a sync.

**Sync path:**

- A background asyncio task runs continuously.
- On dirty state: waits 2 seconds (debounce), then calls `SlackClient.canvas_sync()`.
- Periodic sync: every 60 seconds regardless of dirty state.
- On failure: after 3 consecutive failures, switches from 60-second to 300-second intervals. Resets on success.

**Canvas API constraints:**

Free plan limitation

On free Slack workspaces, `canvases.edit` with `changes` array must have exactly 1 item. `canvases.create` with a `channel_id` is required — standalone canvases (no channel) are not available on free plans.

Canvas reads are served from the local SQLite copy — there is no Slack API endpoint that returns canvas content as markdown. This eliminates a round-trip and avoids the HTML-based read API.

## Emoji Lifecycle

Each user message goes through a lifecycle tracked by emoji reactions on the original message:

| Emoji                | Meaning                                                  |
| -------------------- | -------------------------------------------------------- |
| `:inbox_tray:`       | summon received the message (pre-Claude acknowledgement) |
| `:gear:`             | Claude is actively processing the turn                   |
| `:white_check_mark:` | Turn completed successfully                              |
| `:octagonal_sign:`   | Turn was cancelled via `!stop`                           |
| `:warning:`          | An error occurred during the turn                        |

The `:gear:` emoji replaces `:inbox_tray:` when Claude starts, and is itself replaced by one of the completion states when the turn finishes.
