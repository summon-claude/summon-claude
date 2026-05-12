# CLI Reference

Auto-generated from Click command definitions.

### summon

Bridge Claude Code sessions to Slack channels.

**Usage:**

```
summon [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name               | Type    | Description                   | Default |
| ------------------ | ------- | ----------------------------- | ------- |
| `--version`        | boolean | Show the version and exit.    | `False` |
| `-v`, `--verbose`  | boolean | Enable verbose logging        | `False` |
| `-q`, `--quiet`    | boolean | Suppress non-essential output | `False` |
| `--no-color`       | boolean | Disable colored output        | `False` |
| `--config`         | file    | Override config file path     | None    |
| `--no-interactive` | boolean | Disable interactive prompts   | `False` |
| `-h`, `--help`     | boolean | Show this message and exit.   | `False` |

#### summon auth

Manage authentication for external services.

**Usage:**

```
summon auth [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon auth github

GitHub authentication for MCP tools.

**Usage:**

```
summon auth github [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon auth github login

Authenticate with GitHub using the device flow.

**Usage:**

```
summon auth github login [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon auth github logout

Remove stored GitHub authentication.

**Usage:**

```
summon auth github logout [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon auth github status

Check GitHub authentication status.

**Usage:**

```
summon auth github status [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon auth google

Google authentication.

**Usage:**

```
summon auth google [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon auth google login

Authenticate with Google.

**Usage:**

```
summon auth google login [OPTIONS]
```

**Options:**

| Name           | Type    | Description                          | Default |
| -------------- | ------- | ------------------------------------ | ------- |
| `--account`    | text    | Account label (e.g., personal, work) | None    |
| `-h`, `--help` | boolean | Show this message and exit.          | `False` |

###### summon auth google logout

Remove stored Google credentials.

**Usage:**

```
summon auth google logout [OPTIONS]
```

**Options:**

| Name           | Type    | Description                          | Default |
| -------------- | ------- | ------------------------------------ | ------- |
| `--account`    | text    | Account label (e.g., personal, work) | None    |
| `-h`, `--help` | boolean | Show this message and exit.          | `False` |

###### summon auth google setup

Interactive guided setup for Google OAuth credentials.

**Usage:**

```
summon auth google setup [OPTIONS]
```

**Options:**

| Name           | Type    | Description                          | Default |
| -------------- | ------- | ------------------------------------ | ------- |
| `--account`    | text    | Account label (e.g., personal, work) | None    |
| `-h`, `--help` | boolean | Show this message and exit.          | `False` |

###### summon auth google status

Check Google authentication status.

**Usage:**

```
summon auth google status [OPTIONS]
```

**Options:**

| Name           | Type    | Description                          | Default |
| -------------- | ------- | ------------------------------------ | ------- |
| `--account`    | text    | Account label (e.g., personal, work) | None    |
| `-h`, `--help` | boolean | Show this message and exit.          | `False` |

##### summon auth jira

Jira authentication for MCP tools.

**Usage:**

```
summon auth jira [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon auth jira login

Authenticate with Jira via OAuth 2.1.

**Usage:**

```
summon auth jira login [OPTIONS]
```

**Options:**

| Name           | Type    | Description                                                                                                       | Default |
| -------------- | ------- | ----------------------------------------------------------------------------------------------------------------- | ------- |
| `--site`       | text    | Atlassian site (e.g. 'myorg' or 'myorg.atlassian.net'). Resolves to a cloud UUID via API discovery when possible. | None    |
| `-h`, `--help` | boolean | Show this message and exit.                                                                                       | `False` |

###### summon auth jira logout

Remove stored Jira OAuth credentials.

**Usage:**

```
summon auth jira logout [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon auth jira status

Check Jira authentication status.

**Usage:**

```
summon auth jira status [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon auth slack

External Slack workspace authentication.

**Usage:**

```
summon auth slack [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon auth slack channels

Update monitored channel selection (no re-auth needed).

**Usage:**

```
summon auth slack channels [OPTIONS]
```

**Options:**

| Name           | Type    | Description                  | Default |
| -------------- | ------- | ---------------------------- | ------- |
| `--refresh`    | boolean | Re-fetch channels from Slack | `False` |
| `-h`, `--help` | boolean | Show this message and exit.  | `False` |

###### summon auth slack login

Authenticate with an external Slack workspace.

WORKSPACE can be a name (myteam), enterprise (acme.enterprise), or full URL (https://myteam.slack.com).

**Usage:**

```
summon auth slack login [OPTIONS] WORKSPACE
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon auth slack logout

Remove stored Slack credentials.

**Usage:**

```
summon auth slack logout [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon auth slack status

Show external Slack workspace auth status.

**Usage:**

```
summon auth slack status [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon auth status

Show authentication status for all configured providers.

**Usage:**

```
summon auth status [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `--json`       | boolean | Output as JSON              | `False` |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

#### summon config

Manage summon-claude configuration.

**Usage:**

```
summon config [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon config check

Validate configuration and check connectivity.

**Usage:**

```
summon config check [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon config edit

Open config file in $EDITOR.

**Usage:**

```
summon config edit [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon config path

Print the config file path.

**Usage:**

```
summon config path [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon config set

Set a configuration value (e.g. SUMMON_SLACK_BOT_TOKEN).

**Usage:**

```
summon config set [OPTIONS] KEY VALUE
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon config show

Show current configuration with grouped display and source indicators.

**Usage:**

```
summon config show [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

#### summon db

Database maintenance commands.

**Usage:**

```
summon db [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon db purge

Purge old sessions, audit logs, and expired auth tokens.

**Usage:**

```
summon db purge [OPTIONS]
```

**Options:**

| Name           | Type                          | Description                     | Default |
| -------------- | ----------------------------- | ------------------------------- | ------- |
| `--older-than` | integer range (`1` and above) | Purge records older than N days | `30`    |
| `--yes`, `-y`  | boolean                       | Skip confirmation prompt        | `False` |
| `-h`, `--help` | boolean                       | Show this message and exit.     | `False` |

##### summon db status

Show schema version, integrity, and row counts.

**Usage:**

```
summon db status [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon db vacuum

Compact the database and check integrity.

**Usage:**

```
summon db vacuum [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

#### summon doctor

Run comprehensive diagnostics and display pass/fail results.

**Usage:**

```
summon doctor [OPTIONS]
```

**Options:**

| Name           | Type    | Description                                                  | Default |
| -------------- | ------- | ------------------------------------------------------------ | ------- |
| `--export`     | file    | Export results as JSON to this file path                     | None    |
| `--submit`     | boolean | Submit a redacted report as a GitHub issue (requires gh CLI) | `False` |
| `-h`, `--help` | boolean | Show this message and exit.                                  | `False` |

#### summon hooks

Manage lifecycle hooks and the Claude Code hook bridge.

**Usage:**

```
summon hooks [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon hooks clear

Clear lifecycle hooks (sets to NULL, falling back to global defaults).

**Usage:**

```
summon hooks clear [OPTIONS]
```

**Options:**

| Name           | Type    | Description                                     | Default |
| -------------- | ------- | ----------------------------------------------- | ------- |
| `--project`    | text    | Project ID to clear hooks for (default: global) | None    |
| `-h`, `--help` | boolean | Show this message and exit.                     | `False` |

##### summon hooks install

Install the Claude Code hook bridge (shell wrappers + settings.json entries).

Writes summon-pre-worktree.sh and summon-post-worktree.sh to ~/.claude/hooks/ and registers them in ~/.claude/settings.json as PreToolUse/PostToolUse handlers for EnterWorktree. Idempotent.

**Usage:**

```
summon hooks install [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon hooks set

Set lifecycle hooks via $EDITOR or from a JSON string.

If HOOKS_JSON is omitted, opens $EDITOR with current hooks for editing. If provided, parses the JSON and stores it directly.

Hook types: worktree_create, project_up, project_down. Use "$INCLUDE_GLOBAL" in per-project hooks to include global hooks.

Examples: summon hooks set # opens $EDITOR summon hooks set '{"worktree_create": ["make setup"]}' # inline JSON summon hooks set --project ID '{"worktree_create": ["$INCLUDE_GLOBAL", "make setup"]}'

**Usage:**

```
summon hooks set [OPTIONS] [HOOKS_JSON]
```

**Options:**

| Name           | Type    | Description                                   | Default |
| -------------- | ------- | --------------------------------------------- | ------- |
| `--project`    | text    | Project ID to set hooks for (default: global) | None    |
| `-h`, `--help` | boolean | Show this message and exit.                   | `False` |

##### summon hooks show

Show configured lifecycle hooks.

**Usage:**

```
summon hooks show [OPTIONS]
```

**Options:**

| Name           | Type    | Description                                    | Default |
| -------------- | ------- | ---------------------------------------------- | ------- |
| `--project`    | text    | Project ID to show hooks for (default: global) | None    |
| `-h`, `--help` | boolean | Show this message and exit.                    | `False` |

##### summon hooks uninstall

Remove summon-owned hook entries from settings.json and delete shell wrappers.

**Usage:**

```
summon hooks uninstall [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

#### summon init

Interactive setup wizard for summon-claude configuration.

**Usage:**

```
summon init [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

#### summon project

Manage summon projects.

**Usage:**

```
summon project [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon project add

Register a project directory for PM agent management.

**Usage:**

```
summon project add [OPTIONS] NAME [DIRECTORY]
```

**Options:**

| Name           | Type    | Description                                  | Default |
| -------------- | ------- | -------------------------------------------- | ------- |
| `--jql`        | text    | JQL filter for Jira issue triage (optional). | None    |
| `-h`, `--help` | boolean | Show this message and exit.                  | `False` |

##### summon project down

Stop PM sessions for registered projects.

If NAME is given, stop only that project's sessions. Otherwise stop all.

**Usage:**

```
summon project down [OPTIONS] [NAME]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon project list

List all registered projects.

**Usage:**

```
summon project list [OPTIONS]
```

**Options:**

| Name             | Type           | Description                 | Default       |
| ---------------- | -------------- | --------------------------- | ------------- |
| `-o`, `--output` | choice (`json` | `table`)                    | Output format |
| `-h`, `--help`   | boolean        | Show this message and exit. | `False`       |

##### summon project remove

Remove a registered project.

**Usage:**

```
summon project remove [OPTIONS] NAME_OR_ID
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon project up

Start PM agents for all registered projects that don't have one running.

**Usage:**

```
summon project up [OPTIONS]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon project update

Update a project's configuration.

NAME_OR_ID can be the project name or project ID prefix. Pass --jql "" to clear the Jira JQL filter.

**Usage:**

```
summon project update [OPTIONS] NAME_OR_ID
```

**Options:**

| Name                 | Type    | Description                                   | Default |
| -------------------- | ------- | --------------------------------------------- | ------- |
| `--jql`              | text    | JQL filter for Jira triage. Pass "" to clear. | None    |
| `--auto-deny`        | text    | Auto-mode deny rules (project-specific)       | None    |
| `--auto-allow`       | text    | Auto-mode allow rules (project-specific)      | None    |
| `--auto-environment` | text    | Auto-mode environment description             | None    |
| `-h`, `--help`       | boolean | Show this message and exit.                   | `False` |

##### summon project workflow

Manage PM workflow instructions.

**Usage:**

```
summon project workflow [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon project workflow clear

Clear workflow instructions. Without PROJECT_NAME, clears global defaults.

**Usage:**

```
summon project workflow clear [OPTIONS] [PROJECT_NAME]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon project workflow set

Set workflow instructions via $EDITOR. Without PROJECT_NAME, sets global defaults.

**Usage:**

```
summon project workflow set [OPTIONS] [PROJECT_NAME]
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

###### summon project workflow show

Show workflow instructions. Without PROJECT_NAME, shows global defaults.

**Usage:**

```
summon project workflow show [OPTIONS] [PROJECT_NAME]
```

**Options:**

| Name           | Type    | Description                                         | Default |
| -------------- | ------- | --------------------------------------------------- | ------- |
| `--raw`        | boolean | Show raw template without expanding $INCLUDE_GLOBAL | `False` |
| `-h`, `--help` | boolean | Show this message and exit.                         | `False` |

#### summon reset

Reset summon data or configuration to a clean state.

**Usage:**

```
summon reset [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon reset config

Delete all configuration (Slack tokens, Google OAuth credentials).

**Usage:**

```
summon reset config [OPTIONS]
```

**Options:**

| Name           | Type    | Description                                                             | Default |
| -------------- | ------- | ----------------------------------------------------------------------- | ------- |
| `--force`      | boolean | Bypass symlink/outside-home safety checks. Still requires confirmation. | `False` |
| `-h`, `--help` | boolean | Show this message and exit.                                             | `False` |

##### summon reset data

Delete all runtime data and start fresh.

**Usage:**

```
summon reset data [OPTIONS]
```

**Options:**

| Name           | Type    | Description                                                             | Default |
| -------------- | ------- | ----------------------------------------------------------------------- | ------- |
| `--force`      | boolean | Bypass symlink/outside-home safety checks. Still requires confirmation. | `False` |
| `-h`, `--help` | boolean | Show this message and exit.                                             | `False` |

#### summon session

Manage summon sessions.

**Usage:**

```
summon session [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

##### summon session cleanup

Mark sessions with dead processes as errored.

**Usage:**

```
summon session cleanup [OPTIONS]
```

**Options:**

| Name           | Type    | Description                                                                  | Default |
| -------------- | ------- | ---------------------------------------------------------------------------- | ------- |
| `--archive`    | boolean | Archive Slack channels of stale sessions (channels are preserved by default) | `False` |
| `-h`, `--help` | boolean | Show this message and exit.                                                  | `False` |

##### summon session info

Show detailed information for a session (by name or ID).

**Usage:**

```
summon session info [OPTIONS] SESSION
```

**Options:**

| Name             | Type           | Description                 | Default       |
| ---------------- | -------------- | --------------------------- | ------------- |
| `-o`, `--output` | choice (`json` | `table`)                    | Output format |
| `-h`, `--help`   | boolean        | Show this message and exit. | `False`       |

##### summon session list

List sessions. Shows active sessions by default; use --all for all recent.

**Usage:**

```
summon session list [OPTIONS]
```

**Options:**

| Name             | Type           | Description                                | Default       |
| ---------------- | -------------- | ------------------------------------------ | ------------- |
| `--all`, `-a`    | boolean        | Show all recent sessions (not just active) | `False`       |
| `--name`         | text           | Filter sessions by name                    | None          |
| `-o`, `--output` | choice (`json` | `table`)                                   | Output format |
| `-h`, `--help`   | boolean        | Show this message and exit.                | `False`       |

##### summon session logs

Show session logs. Pass a session name or ID, or list available logs.

**Usage:**

```
summon session logs [OPTIONS] SESSION
```

**Options:**

| Name           | Type    | Description                           | Default |
| -------------- | ------- | ------------------------------------- | ------- |
| `--tail`, `-n` | integer | Number of lines to show (default: 50) | `50`    |
| `-h`, `--help` | boolean | Show this message and exit.           | `False` |

#### summon start

Start a new summon session (thin client — delegates to the daemon).

**Usage:**

```
summon start [OPTIONS]
```

**Options:**

| Name           | Type          | Description                                               | Default |
| -------------- | ------------- | --------------------------------------------------------- | ------- |
| `--cwd`        | text          | Working directory for Claude (default: current directory) | None    |
| `--resume`     | text          | Resume an existing Claude Code session by ID              | None    |
| `--name`       | text          | Session name (used for Slack channel naming)              | None    |
| `--model`      | text          | Model override (default: from config)                     | None    |
| `--effort`     | choice (`low` | `medium`                                                  | `high`  |
| `-h`, `--help` | boolean       | Show this message and exit.                               | `False` |

#### summon stop

Stop a session (by name or ID) or all sessions via the daemon.

**Usage:**

```
summon stop [OPTIONS] SESSION
```

**Options:**

| Name           | Type    | Description                 | Default |
| -------------- | ------- | --------------------------- | ------- |
| `--all`, `-a`  | boolean | Stop all active sessions    | `False` |
| `-h`, `--help` | boolean | Show this message and exit. | `False` |

#### summon version

Show extended version and environment information.

**Usage:**

```
summon version [OPTIONS]
```

**Options:**

| Name             | Type           | Description                 | Default       |
| ---------------- | -------------- | --------------------------- | ------------- |
| `-o`, `--output` | choice (`json` | `table`)                    | Output format |
| `-h`, `--help`   | boolean        | Show this message and exit. | `False`       |

Command Aliases

`summon s` is shorthand for `summon session`. `summon p` is shorthand for `summon project`.
