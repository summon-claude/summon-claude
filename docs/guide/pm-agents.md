# PM Agents

A PM (project manager) agent is a long-running Claude session that orchestrates work across multiple child sessions. Instead of running tasks yourself, you describe what needs to be done and the PM spawns, directs, and monitors the sessions that do the work.

---

## What the PM agent does

The PM agent runs as a standard summon-claude session with an elevated set of MCP tools unavailable to regular sessions. It can:

- Spawn new child sessions with specific instructions
- Send messages to running children
- Stop children that have finished or gone off-track
- Resume sessions that errored or completed
- Log structured status updates to the audit trail
- Read and write to the project canvas

The PM agent has a dedicated Slack channel with a project canvas. The canvas shows an **Active Work** table: what each child session is doing, its status, and any relevant links.

---

## Starting a PM

PM agents are started as part of a project:

```bash
summon project up my-api
```

This starts one PM session per project. You authenticate it in Slack the same way as a regular session:

```
/summon ABC123
```

Once bound to a channel, the PM is ready to receive instructions from you. Send it a message describing the task and it will plan and coordinate the work.

!!! tip "Naming"
    PM sessions are named with `-pm-` in the middle (e.g., `my-api-pm-a1b2c3`) so summon-claude can identify them for special handling like cascade restart and PM-awareness checks in `summon stop`.

---

## PM-only MCP tools

The PM agent has access to five MCP tools that are not available to regular sessions. These tools use the daemon's IPC layer to manage sessions directly.

### `session_start`

Spawn a new child session:

```
session_start(
  name="worker-1",
  cwd="/path/to/project",
  initial_message="Review PR #42 and post a summary to this channel",
  model="claude-opus-4-5",           # optional override
  system_prompt="Focus on security"  # optional, up to 10K chars
)
```

**Constraints:**

| Parameter | Limit |
|-----------|-------|
| `name` | Required. Must be unique within active sessions. |
| `cwd` | Must be a descendant of the parent session's `cwd` (prevents directory escapes). CLI-originated spawns skip this restriction. |
| `system_prompt` | Up to 10,000 characters |
| `initial_message` | Up to 10,000 characters |
| Concurrent children | `MAX_SPAWN_CHILDREN_PM` (see source) |
| Spawn depth | 2 levels max (root PM → child → grandchild) |

**Spawn depth limit:** summon-claude allows at most 3 levels of nesting: the PM itself (depth 0), its direct children (depth 1), and grandchildren spawned by children (depth 2). Attempts to spawn deeper are rejected. This prevents runaway recursive spawning.

The spawned session starts with an authentication code and must be authenticated in Slack before it can receive messages. The PM receives the auth code and can direct you (or a human) to authenticate it.

### `session_stop`

Stop a child session:

```
session_stop(session_id="sess-a1b2c3")
```

!!! warning "Cannot stop self"
    A PM cannot stop its own session via `session_stop`. Use `!end` in the Slack channel or `summon stop` from the terminal.

### `session_message`

Send a message to a child session as if a human typed it in Slack:

```
session_message(
  session_id="sess-a1b2c3",
  message="The PR was merged. Switch to the migration task now."
)
```

**Constraints:**

- Message must be 10,000 characters or fewer
- The calling session must be the parent of the target session

### `session_resume`

Resume a child session that has completed or errored, binding it to its existing Slack channel:

```
session_resume(session_id="sess-a1b2c3")
```

This is useful when a child session ends (normally or due to an error) but you want to continue the work in the same channel without losing conversation history.

### `session_log_status`

Write a structured status entry to the audit log (not posted to Slack):

```
session_log_status(
  status="in_progress",
  note="Reviewing auth module — found 3 issues"
)
```

This is for audit-trail logging and canvas updates. It does not post a message to any Slack channel.

---

## Spawn authentication

When the PM spawns a child session, the child needs to be authenticated in Slack before it can post or receive messages. The authentication flow is the same as a regular `summon start`:

1. PM calls `session_start` — gets back a short code
2. PM posts the code to its own channel (or directs you)
3. You (or the PM directing you) type `/summon CODE` in the target channel
4. The child binds to that channel and begins working

!!! note "Spawn tokens"
    Spawned sessions use a spawn-token mechanism that enforces the CWD ancestry constraint server-side. The token is consumed atomically on authentication so it cannot be replayed.

---

## PM canvas

The PM session gets a project canvas tab in its Slack channel. The canvas shows:

- **Active Work** — table of current child sessions with status, cwd, and task description
- **Completed Work** — summary of finished sessions
- **Notes** — free-form notes the PM can write

The PM can update the canvas at any time using the `summon_canvas_update_section` MCP tool. See [Canvas Integration](canvas.md) for details.

![PM canvas showing Active Work table](../assets/screenshots/pm-canvas-active-work.png)

---

## Interacting with the PM

From your perspective, the PM is just a Claude session in a Slack channel. Send it natural-language instructions:

```
Break the authentication refactor into parallel tasks. One session should handle
the JWT middleware, another the OAuth provider integrations.
```

The PM will plan, spawn child sessions, direct them, and report back — all coordinated through Slack channels.

!!! tip "Stop a PM gracefully"
    If you stop a PM session while it has active children, summon-claude warns you that children will be orphaned. Use `summon project down` instead to stop everything together and preserve the suspended state for cascade restart.

---

## What's next

- [Projects](projects.md) — setting up and managing projects
- [Canvas](canvas.md) — persistent markdown in Slack channel tabs
- [Cron & Tasks](cron-tasks.md) — scheduled jobs and task tracking
