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

`down` stops the PM and all child sessions it manages. Child sessions are marked **suspended** rather than completed — this lets `project up` restart them deterministically later (cascade restart).

```bash
# Stop all projects
summon project down --all
```

**Cascade restart:** When you run `summon project up` after a `down`, summon-claude finds all suspended sessions for the project and restarts them with the same `cwd` and model they had before. This lets you pause and resume an entire multi-session workflow without reconfiguring anything.

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

Workflow instructions are injected into the system prompt of every session created under the project. Use them to encode team conventions, coding standards, or project-specific context:

```bash
summon project add my-api \
  --workflow-instructions "Always run 'uv run pytest' before committing. Follow the existing module structure in src/. Open PRs to the 'main' branch."
```

For longer instructions, use a file:

```bash
summon project add my-api --workflow-file ./workflow.md
```

Workflow instructions are stored in the registry and can be updated via `summon config set` or by re-running `project add` with the same name.

---

## What's next

- [PM Agents](pm-agents.md) — the orchestrator session that runs within a project
- [Scribe](scribe.md) — background monitoring agent
- [Configuration](configuration.md) — project-level config options
