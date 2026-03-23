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

This prompts for the three required Slack tokens and writes them to the config file. The file is created with `0600` permissions (owner read/write only).

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
| `SUMMON_NO_UPDATE_CHECK` | (unset) | Set to `1` to disable update checks |

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

Prints all current configuration values with tokens masked. Useful for verifying what summon is using.

<!-- terminal:config-show -->
```text
SUMMON_SLACK_BOT_TOKEN=configured
SUMMON_SLACK_APP_TOKEN=configured
SUMMON_SLACK_SIGNING_SECRET=configured
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
```

Sets a single key in the config file. Creates the file if it does not exist.

### summon config edit

```bash
summon config edit
```

Opens the config file in `$EDITOR`. If `$EDITOR` is not set, falls back to common editors.

### summon config check

```bash
summon config check
```

Validates configuration and tests connectivity to Slack. Exits with code 1 if any check fails. Run this after making changes to verify everything is correct.

<!-- terminal:config-check -->
```text
  [PASS] SUMMON_SLACK_BOT_TOKEN is set
  [PASS] SUMMON_SLACK_APP_TOKEN is set
  [PASS] SUMMON_SLACK_SIGNING_SECRET is set
  [PASS] Bot token format is valid (xoxb-)
  [PASS] App token format is valid (xapp-)
  [PASS] Signing secret format looks valid (hex)
  [PASS] DB path is writable: ~/.local/share/summon/registry.db
  [PASS] Schema version 12 (current)
  [PASS] Database integrity OK
  [INFO] Sessions: 0, Audit log: 0
  [PASS] Slack API reachable (team: my-workspace)
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
# SUMMON_NO_UPDATE_CHECK=1
```

!!! tip "Secret management"
    The config file is created with `0600` permissions by `summon init`. For team environments or CI, prefer injecting secrets via environment variables rather than committing a config file.
