# Projects

Projects group related sessions under a shared name, workflow instructions, and a channel-prefix convention. A project can have a dedicated PM agent that coordinates child sessions on your behalf.

---

## What projects are

A project is a named record in the summon-claude registry that links together:

- A **display name** and optional **description**
- A **working directory** — the default `cwd` for sessions created under this project
- **Workflow instructions** — a block of text injected into the system prompt of every session in the project
- A **channel prefix** — the Slack channel-name prefix used when creating session channels for the project

Projects make it easier to keep related work organized: the PM agent knows which sessions belong together, and workflow instructions let you encode team conventions once rather than re-typing them in every session.

---

## Commands

!!! tip "Alias"
    `summon p` is shorthand for `summon project` — all subcommands work with either prefix.

### `summon project add`

Register a new project:

```bash
summon project add NAME [DIR]
```

`DIR` defaults to the current working directory if omitted.

```bash
# Register the current directory as a project
summon project add my-api

# Register a different directory
summon project add frontend ~/work/acme-frontend
```

**Options:**

| Option | Description |
|--------|-------------|
| `--description TEXT` | Human-readable description |
| `--channel-prefix TEXT` | Slack channel prefix for project sessions (default: project name, lowercased) |
| `--workflow-instructions TEXT` | Instructions injected into every session's system prompt |
| `--workflow-file PATH` | Read workflow instructions from a file instead |

**Channel prefix conventions:**

Channel prefixes must be valid Slack channel-name segments (lowercase letters, numbers, hyphens). summon-claude enforces uniqueness across projects so channels are unambiguous.

```bash
summon project add my-api --channel-prefix api
# Sessions get channels like: api-worker-a1b2c3, api-review-d4e5f6
```

### `summon project list`

Show all registered projects:

```bash
summon project list
```

The table includes each project's ID, name, directory, channel prefix, and PM status (running / stopped).

```bash
summon project list --output json
```

### `summon project up`

Start PM agents for all projects (or a specific one):

```bash
# Start PMs for all projects
summon project up

# Start PM for one project
summon project up my-api
```

Each project gets one PM session. If a PM is already running for a project, `up` skips it.

!!! note "Authentication still required"
    Each PM session starts with an authentication code, just like `summon start`. The PM prints its code so you can bind it to a Slack channel with `/summon CODE`.

### `summon project down`

Stop all sessions associated with a project:

```bash
summon project down my-api
```

`down` stops the PM and all child sessions it manages. All sessions (PM and children) are marked **suspended** rather than completed — this lets `project up` restart them deterministically later (cascade restart). Each session's Slack channel is renamed with a `zzz-` prefix on disconnect (e.g., `my-api-worker-a1b2c3` becomes `zzz-my-api-worker-a1b2c3`), making it easy to visually identify inactive sessions in the Slack sidebar.

```bash
# Stop all projects
summon project down --all
```

**Cascade restart:** When you run `summon project up` after a `down`, summon-claude finds all suspended sessions for the project and resumes them with full transcript continuity. Rather than creating fresh sessions, it creates new summon sessions that bind to the **existing** Slack channels — the `zzz-` prefix is removed, and the original channel name is restored. Canvas content, conversation history, and the Claude Code session transcript all carry over. The resumed sessions keep the same `cwd` and model they had before, so you can pause and resume an entire multi-session workflow without reconfiguring anything or losing context.

### `summon project remove`

Remove a project from the registry:

```bash
summon project remove my-api
# or by project ID
summon project remove proj-a1b2c3
```

!!! warning
    Removing a project does not stop running sessions — run `summon project down` first if needed. Suspended sessions are cleaned up (marked completed) automatically as part of removal.

---

## Workflow instructions

Workflow instructions are injected into the system prompt of every session created under the project. Use them to encode team conventions, coding standards, or project-specific context.

You can set initial workflow instructions when adding a project:

```bash
summon project add my-api \
  --workflow-instructions "Always run 'uv run pytest' before committing. Follow the existing module structure in src/. Open PRs to the 'main' branch."
```

For longer instructions, use a file:

```bash
summon project add my-api --workflow-file ./workflow.md
```

### Managing workflow instructions

Use `summon project workflow` to view, edit, and clear workflow instructions after a project is registered:

```bash
# Show global workflow defaults
summon project workflow show

# Show workflow for a specific project
summon project workflow show my-api

# Edit global workflow (opens $EDITOR)
summon project workflow set

# Edit project-specific workflow (opens $EDITOR)
summon project workflow set my-api

# Clear project-specific workflow (falls back to global defaults)
summon project workflow clear my-api

# Clear global workflow defaults
summon project workflow clear
```

`summon project workflow set` opens your `$EDITOR` with the current instructions pre-filled. Comment lines (starting with `#`) are stripped on save. If you close the editor without changes, nothing is updated.

### Global vs. project-specific workflow

There are two levels of workflow instructions:

- **Global workflow defaults** — applied to all projects that don't have their own override.
- **Project-specific workflow** — set per project, fully replaces the global defaults by default.

To include the global defaults inside a project-specific workflow, use the `$INCLUDE_GLOBAL` token. Place it anywhere in the project's workflow text and it will be expanded to the full global defaults at runtime:

```
# Project-specific rules come first
Always use TypeScript strict mode.
Run tests with `npm test` before committing.

# Include the shared global defaults here
$INCLUDE_GLOBAL
```

Without `$INCLUDE_GLOBAL`, project-specific instructions fully replace the global defaults. Clearing a project's workflow (`summon project workflow clear my-api`) removes the override so the project falls back to global defaults.

---

## What's next

- [PM Agents](pm-agents.md) — the orchestrator session that runs within a project
- [Scribe](scribe.md) — background monitoring agent
- [Configuration](configuration.md) — project-level config options
