# Configuration

summon-claude is configured entirely through environment variables with the `SUMMON_` prefix. You can set them in a config file, a `.env` file in your working directory, or directly in your shell environment.

---

## Config file location

summon follows the [XDG Base Directory spec](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html):

| Variable | Config path |
|----------|-------------|
| `XDG_CONFIG_HOME` set | `$XDG_CONFIG_HOME/summon/config.env` |
| Default | `~/.config/summon/config.env` |
| Fallback (if `~/.config` missing) | `~/.summon/config.env` |

Data (database, logs) follows the same pattern under `XDG_DATA_HOME` / `~/.local/share/summon`.

Use `summon config path` to print the exact config file path in use.

---

## Loading priority

Settings are resolved in this order (later overrides earlier):

1. **Config file** (`~/.config/summon/config.env` or XDG override)
2. **`.env` file** in the current working directory
3. **Shell environment variables**

The `--config PATH` flag on the `summon` command overrides the config file path.

---

## Interactive setup

The fastest way to create a config is the setup wizard:

```bash
summon init
```

This runs a full interactive walkthrough of all configuration options. It starts with **core options** (Slack tokens, default model, effort level, channel prefix), then asks whether you want to configure **advanced settings** (display, behavior, thinking). Conditional sections appear based on your choices:

- **Scribe** options appear only when `scribe_enabled` is set to true
- **Google Workspace (Scribe)** options appear only when `scribe_google_enabled` is true and workspace-mcp is installed
- **Slack (Scribe)** options appear only when `scribe_slack_enabled` is true and Playwright is installed

The wizard pre-fills defaults and preserves existing values (press Enter to keep). After saving, it automatically runs `summon config check` to validate connectivity and show a feature inventory. The config file is created with `0600` permissions (owner read/write only).

---

## Required settings

``` { .bash .annotate }
# Required — Slack tokens
SUMMON_SLACK_BOT_TOKEN=xoxb-...    # (1)
SUMMON_SLACK_APP_TOKEN=xapp-...    # (2)
SUMMON_SLACK_SIGNING_SECRET=abc... # (3)
```

1. **Bot User OAuth Token** — found at **OAuth & Permissions** in your Slack app settings. Starts with `xoxb-`.
2. **App-Level Token** — found at **Basic Information → App-Level Tokens**. Must have `connections:write` scope. Starts with `xapp-`.
3. **Signing Secret** — found at **Basic Information → App Credentials**. A hex string used to verify incoming requests.

These three values must be set. summon validates token prefixes at startup and fails with a clear error if they are missing or malformed.

See [Slack Setup](../getting-started/slack-setup.md) for how to obtain these values.

---

## Core settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMON_DEFAULT_MODEL` | (Claude default) | Model name to use for new sessions |
| `SUMMON_DEFAULT_EFFORT` | `high` | Default effort level: `low`, `medium`, `high`, `max` |
| `SUMMON_CHANNEL_PREFIX` | `summon` | Prefix for created Slack channel names |
| `SUMMON_PERMISSION_DEBOUNCE_MS` | `500` | Milliseconds to batch permission requests |
| `SUMMON_MAX_INLINE_CHARS` | `2500` | Max characters before switching to file upload |
| `SUMMON_ENABLE_THINKING` | `true` | Enable extended thinking (passed to Claude SDK) |
| `SUMMON_SHOW_THINKING` | `false` | Post thinking blocks to Slack turn threads |
| `SUMMON_GITHUB_PAT` | (none) | GitHub PAT for GitHub MCP integration |
| `SUMMON_NO_UPDATE_CHECK` | `false` | Disable the background PyPI update check on `summon start` |

### Channel naming

With `SUMMON_CHANNEL_PREFIX=summon` and a session named `myapp-a3f9c1`, the Slack channel name is constructed as `{prefix}-{slug}-{MMDD}-{hex8}` — for example, `summon-myapp-a3f9c1-0322-9f2b41a3`. Channel names are capped at 80 characters.

### Inline vs file upload

When Claude produces output longer than `SUMMON_MAX_INLINE_CHARS` (default 2500 characters), summon uploads it as a Slack file snippet instead of posting it inline. This keeps channels readable for long outputs.

### Thinking blocks

- `SUMMON_ENABLE_THINKING=true` (default): passes `ThinkingConfigAdaptive` to the Claude SDK — Claude may think deeply when beneficial
- `SUMMON_SHOW_THINKING=true`: posts Claude's thinking content to the turn thread in Slack, visible as collapsible context blocks (useful for debugging or transparency)

---

## GitHub integration

```bash
SUMMON_GITHUB_PAT=ghp_xxxxxxxxxxxx
```

Enables the GitHub remote MCP server for all sessions. Accepts classic (`ghp_*`) and fine-grained (`github_pat_*`) personal access tokens. See [GitHub Integration](github-integration.md) for details.

---

## Scribe settings

The Scribe agent monitors external sources (email, calendar, Slack) and surfaces important items. All Scribe settings are optional and take effect only when `SUMMON_SCRIBE_ENABLED=true`.

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMON_SCRIBE_ENABLED` | `false` | Enable the Scribe monitoring agent |
| `SUMMON_SCRIBE_SCAN_INTERVAL_MINUTES` | `5` | How often Scribe scans for new items (minimum: 1) |
| `SUMMON_SCRIBE_CWD` | data dir | Working directory for the Scribe session |
| `SUMMON_SCRIBE_MODEL` | (default model) | Model for the Scribe agent |
| `SUMMON_SCRIBE_IMPORTANCE_KEYWORDS` | (empty) | Comma-separated keywords that flag items as important |
| `SUMMON_SCRIBE_QUIET_HOURS` | (none) | Time window for reduced alerts, e.g. `22:00-07:00` |

### Google Workspace (Scribe)

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMON_SCRIBE_GOOGLE_ENABLED` | `false` | Enable the Google Workspace data collector for scribe. Requires workspace-mcp. |
| `SUMMON_SCRIBE_GOOGLE_SERVICES` | `gmail,calendar,drive` | Comma-separated Google services to monitor |

Valid services: `gmail`, `drive`, `calendar`, `docs`, `sheets`, `chat`, `forms`, `slides`, `tasks`, `contacts`, `search`, `appscript`.

Requires Google OAuth credentials. Set up with:

```bash
summon config google-auth
```

### Slack monitoring (Scribe)

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMON_SCRIBE_SLACK_ENABLED` | `false` | Enable Slack channel monitoring via browser automation |
| `SUMMON_SCRIBE_SLACK_BROWSER` | `chrome` | Browser for Playwright: `chrome`, `firefox`, or `webkit` |
| `SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS` | (empty) | Comma-separated channel names to monitor |

See [Scribe](scribe.md) for full setup instructions.

---

## Config subcommands

### summon config show

```bash
summon config show
```

Displays all configuration options organized by section (Slack Credentials, Session Defaults, Scribe, Scribe Google, Scribe Slack, GitHub, Display, Behavior, Thinking). Each option shows a source indicator:

- **(set)** — explicitly configured in the config file
- **(default)** — using the built-in default value
- **(not set)** — a required value that is missing
- **(optional)** — an optional secret that has not been configured

Disabled sections (e.g., Scribe Google when `scribe_google_enabled` is false) are shown dimmed with a "disabled" label.

<!-- terminal:config-show -->
```text
  Slack Credentials
    SUMMON_SLACK_BOT_TOKEN                   configured                     (set)
    SUMMON_SLACK_APP_TOKEN                   configured                     (set)
    SUMMON_SLACK_SIGNING_SECRET              configured                     (set)

  Session Defaults
    SUMMON_DEFAULT_MODEL                     claude-opus-4-6                (set)
    SUMMON_DEFAULT_EFFORT                    high                           (default)
    SUMMON_CHANNEL_PREFIX                    summon                         (default)

  Scribe: disabled

  GitHub
    SUMMON_GITHUB_PAT                        configured                     (set)
```
<!-- /terminal:config-show -->

### summon config path

```bash
summon config path
```

Prints the absolute path to the config file in use.

### summon config set

```bash
summon config set SUMMON_DEFAULT_MODEL claude-opus-4-6
summon config set SUMMON_CHANNEL_PREFIX my-team
summon config set SUMMON_SCRIBE_ENABLED true
```

Sets a single key in the config file. Creates the file if it does not exist. The key must be a valid `SUMMON_*` configuration variable — unknown keys are rejected with an error listing all valid options.

Boolean values are normalized: `true`, `false`, `yes`, `no`, `on`, `off`, `1`, and `0` are all accepted and stored as `true` or `false`. Choice-type options (like `SUMMON_DEFAULT_EFFORT`) are validated against their allowed values.

### summon config edit

```bash
summon config edit
```

Opens the config file in `$EDITOR`. If `$EDITOR` is not set, falls back to common editors.

### summon config check

```bash
summon config check
```

Validates configuration and tests connectivity. Exits with code 1 if any check fails. Run this after making changes to verify everything is correct. The check covers:

- **Claude CLI** — verifies the `claude` command is available and reports its version
- **Required config keys** — ensures Slack tokens and signing secret are set
- **Token format** — validates `xoxb-`, `xapp-`, and hex prefixes
- **Config validation** — runs pydantic validation on all values (effort level, channel prefix format, etc.)
- **Database** — checks writability, schema version, and integrity
- **Slack API** — tests connectivity and verifies bot scopes
- **GitHub PAT** — validates token against the GitHub API (if configured)
- **Google Workspace** — checks credential status and scope coverage (if configured)
- **Feature inventory** — shows status of projects, workflow instructions, lifecycle hooks, and the hook bridge

<!-- terminal:config-check -->
```text
  [PASS] Claude CLI found (1.0.33)
  [PASS] SUMMON_SLACK_BOT_TOKEN is set
  [PASS] SUMMON_SLACK_APP_TOKEN is set
  [PASS] SUMMON_SLACK_SIGNING_SECRET is set
  [PASS] Bot token format is valid (xoxb-)
  [PASS] App token format is valid (xapp-)
  [PASS] Signing secret format looks valid (hex)
  [PASS] Config values pass validation
  [PASS] DB path is writable: ~/.local/share/summon/registry.db
  [PASS] Schema version 14 (current)
  [PASS] Database integrity OK
  [INFO] Sessions: 0, Audit log: 0
  [PASS] Slack API reachable (team: my-workspace)
  [PASS] Slack bot scopes: all 16 required scopes granted
  [PASS] GitHub PAT: valid (user: myuser)
  [INFO] Google Workspace: not configured (summon config google-auth)
  [INFO] workspace-mcp (Google): installed
  [INFO] playwright (Slack browser): not installed

Features:
  [INFO] Projects: none registered (summon project add)
  [INFO] Workflow instructions: not set (summon project workflow set)
  [INFO] Lifecycle hooks: not set (summon hooks set)
  [INFO] Hook bridge: not installed (summon hooks install)
```
<!-- /terminal:config-check -->

### summon config google-auth

```bash
summon config google-auth
```

Initiates the Google OAuth flow for Scribe's Google Workspace integration. Opens a browser for authentication. Credentials are stored in the summon data directory (`google-credentials/`).

### summon config google-status

```bash
summon config google-status
```

Shows current Google authentication status: whether credentials exist, which scopes are granted, and whether the token is still valid.

### External Slack workspace commands

These commands manage authentication with an **external** Slack workspace for Scribe's browser-based monitoring. This is separate from the bot's own workspace (which uses the `SUMMON_SLACK_BOT_TOKEN`).

#### summon config slack-auth

```bash
summon config slack-auth myteam
summon config slack-auth acme.enterprise
summon config slack-auth https://myteam.slack.com
```

Opens a browser window for you to log in to the external Slack workspace. Accepts a workspace name, enterprise name, or full URL. After login, saves auth state and prompts for channel selection. Requires the `slack-browser` extra (`uv pip install summon-claude[slack-browser]`).

#### summon config slack-channels

```bash
summon config slack-channels
summon config slack-channels --refresh
```

Update the set of monitored channels without re-authenticating. Uses the cached channel list by default. Pass `--refresh` to re-fetch the channel list from Slack via Playwright.

#### summon config slack-status

```bash
summon config slack-status
```

Shows external Slack workspace auth and channel configuration: workspace URL, user ID, auth state age, and monitored channels.

#### summon config slack-remove

```bash
summon config slack-remove
```

Removes the external Slack workspace auth state (browser cookies and workspace config). Prompts for confirmation.

---

## Example config file

```bash
# ~/.config/summon/config.env

# Required: Slack credentials
SUMMON_SLACK_BOT_TOKEN=xoxb-your-bot-token
SUMMON_SLACK_APP_TOKEN=xapp-your-app-token
SUMMON_SLACK_SIGNING_SECRET=your-signing-secret

# Optional: model and behavior
SUMMON_DEFAULT_MODEL=claude-opus-4-6
SUMMON_DEFAULT_EFFORT=high
SUMMON_CHANNEL_PREFIX=ai

# Optional: GitHub integration
SUMMON_GITHUB_PAT=ghp_your-personal-access-token

# Optional: disable update checks
# SUMMON_NO_UPDATE_CHECK=true
```

!!! tip "Secret management"
    The config file is created with `0600` permissions by `summon init`. For team environments or CI, prefer injecting secrets via environment variables rather than committing a config file.
