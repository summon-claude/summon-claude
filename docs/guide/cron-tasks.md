# Cron & Tasks

??? info "Prerequisites"
    This guide assumes you've completed the [Quick Start](../getting-started/quickstart.md) and have a working `summon config check`.

summon-claude gives Claude two tools for managing ongoing work: **cron jobs** for time-based recurring actions, and **tasks** for tracking discrete units of work. Both are session-scoped and integrate with the canvas for visibility.

## How you use cron and tasks

You don't need to know the tool names or parameters — just tell Claude what you want in your Slack session, and it handles the rest.

**Scheduling recurring work:**

> "Check for new GitHub issues every hour and post a summary"

Claude creates a cron job that fires every hour with a prompt to check GitHub and summarize new issues. You see the results in your Slack channel each time the job runs.

**Setting one-shot reminders:**

> "Remind me to review the PR at 3pm"

Claude creates a one-shot cron job scheduled for 3pm. When it fires, Claude posts a reminder in your channel. The job deletes itself after running once.

**Tracking work items:**

> "Create a task to review the auth module — high priority"

Claude creates a task entry that appears on the session canvas. You can ask about task status anytime, and Claude updates tasks as work progresses.

Under the hood, Claude translates your requests into MCP tool calls (`CronCreate`, `TaskCreate`, etc.). The sections below document these tools for reference — but in practice, you just ask Claude in plain language.

---

## Conversational examples

Here are examples of what you might type in Slack and what happens:

**Setting up a recurring check:**

> "Set up a recurring check every 30 minutes for any failing CI jobs"

Claude creates a cron job with a 30-minute interval. Every 30 minutes, Claude checks CI status and posts in your channel only if there are failures. The job shows up on the canvas under **Scheduled Jobs** with its next run time.

**Creating and querying tasks:**

> "Create a task to review the auth module — high priority"

Claude creates a high-priority task and confirms it. Later, you can ask:

> "What tasks are open right now?"

Claude lists all pending and in-progress tasks for the session, showing their priority and current status.

**Canceling a scheduled job:**

> "Stop checking for CI failures, I fixed the pipeline"

Claude finds the relevant cron job and cancels it. The job disappears from the canvas.

---

## Cron jobs

### How cron works

Each session has a `SessionScheduler` — a per-session asyncio scheduler that uses standard cron expressions to trigger Claude prompts on a schedule. When a job fires, the scheduler injects a message into the session as if a human sent it. Claude then processes the message and responds in Slack.

Cron jobs are agent-facing: Claude creates and manages them through MCP tools. They are not available from the terminal or Slack commands.

!!! note "SDK session limitation"
    Cron tools (`CronCreate`, `CronDelete`, `CronList`) are only available in regular summon-claude sessions, not in SDK-spawned child sessions. Child sessions spawned by the PM should use `TaskCreate`/`TaskUpdate` for work tracking instead.

### `CronCreate`

Create a scheduled job:

```
CronCreate(
  expression="0 9 * * 1-5",
  prompt="Check for new GitHub issues labeled 'needs-triage' and post a summary",
  recurring=true
)
```

**Parameters:**

| Parameter | Description | Limit |
|-----------|-------------|-------|
| `expression` | Cron expression (5-field format) | Minimum 60-second interval |
| `prompt` | Message sent to Claude when the job fires | 1,000 characters max |
| `recurring` | If `true`, repeats on schedule. If `false`, runs once then deletes itself. | — |

**Limits:**

- Maximum 10 agent-created cron jobs per session
- Minimum interval: 60 seconds (expressions resolving to sub-minute intervals are rejected)
- Jobs expire after 24 hours regardless of the expression — create a new job if you need longer schedules
- System jobs (created by summon-claude internally) cannot be created or deleted through MCP tools

### `CronDelete`

Cancel a job by its ID:

```
CronDelete(job_id="cron-a1b2c3")
```

!!! warning "Cannot delete system jobs"
    Jobs with `system=true` are created by summon-claude for internal housekeeping. `CronDelete` rejects attempts to cancel them.

### `CronList`

List all jobs for the current session:

```
CronList()
```

Returns a markdown table showing:

| Column | Description |
|--------|-------------|
| ID | Job identifier |
| Expression | Cron expression |
| Next run | Next scheduled fire time |
| Recurring | Yes / No (one-shot) |
| System | Whether the job is an internal summon job |
| Prompt | Truncated prompt text |

---

## Cron expression reference

summon-claude uses 5-field cron expressions (no seconds field):

```
┌─── minute (0-59)
│ ┌─── hour (0-23)
│ │ ┌─── day of month (1-31)
│ │ │ ┌─── month (1-12)
│ │ │ │ ┌─── day of week (0-7, where 0 and 7 are Sunday)
│ │ │ │ │
* * * * *
```

**Common patterns:**

| Expression | Meaning |
|------------|---------|
| `*/5 * * * *` | Every 5 minutes |
| `0 * * * *` | Every hour, on the hour |
| `0 9 * * 1-5` | 9:00 AM on weekdays |
| `0 9,17 * * *` | 9:00 AM and 5:00 PM daily |
| `0 0 * * 0` | Midnight every Sunday |
| `30 8 1 * *` | 8:30 AM on the 1st of each month |

---

## Tasks

Tasks are structured units of work tracked per session. Claude can create, update, and query tasks through MCP tools. The PM agent can query tasks across multiple child sessions to get a unified view of project progress.

### `TaskCreate`

Create a new task:

```
TaskCreate(
  content="Review the authentication module for security issues",
  priority="high"
)
```

**Parameters:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `content` | Any text | Task description |
| `priority` | `high`, `medium`, `low` | Task priority (default: `medium`) |

**Limit:** 100 tasks per session maximum.

### `TaskUpdate`

Update an existing task:

```
TaskUpdate(
  task_id="task-a1b2c3",
  status="in_progress",
  content="Reviewing auth module — found JWT expiry issue",
  priority="high"
)
```

**Parameters:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `task_id` | Task ID | Required |
| `status` | `pending`, `in_progress`, `completed` | Update task status |
| `content` | Any text | Update task description |
| `priority` | `high`, `medium`, `low` | Update priority |

All update fields are optional — only include what you want to change.

### `TaskList`

List tasks for the current session:

```
TaskList()
# All tasks for this session

TaskList(status="in_progress")
# Filter by status

TaskList(session_ids=["sess-a1b2c3", "sess-d4e5f6"])
# PM cross-session query (PM only, max 20 sessions)
```

**Parameters:**

| Parameter | Description |
|-----------|-------------|
| `status` | Optional filter: `pending`, `in_progress`, `completed` |
| `session_ids` | List of session IDs to query (PM only, up to 20 sessions) |

The cross-session `session_ids` parameter is only available to PM agents. Regular sessions can only list their own tasks.

---

## Canvas integration

Cron jobs and tasks both sync to the session canvas:

- **Cron jobs** appear in a **Scheduled Jobs** section showing active jobs and their next run times
- **Tasks** appear in a **Tasks** section grouped by status

The canvas updates automatically when jobs fire or tasks change status, so the PM (or you) can check the canvas for a snapshot of what each session is doing without asking Claude directly.

---

## Example: PM-coordinated task workflow

Here is how a PM agent might use tasks to coordinate work across child sessions:

1. PM spawns `worker-1` to handle authentication review
2. PM calls `session_message` to tell `worker-1` to create a task for the review
3. `worker-1` calls `TaskCreate(content="Auth review", priority="high")`
4. PM periodically calls `TaskList(session_ids=["sess-worker-1"])` to check progress
5. PM updates the canvas Active Work table via `summon_canvas_update_section`

This gives you full visibility into the work distribution from the PM's Slack channel.

---

## See also

- [PM Agents](pm-agents.md) — how the PM coordinates tasks across sessions
- [Canvas](canvas.md) — how cron and task data appears on the canvas
- [Configuration](configuration.md) — session-level configuration options
