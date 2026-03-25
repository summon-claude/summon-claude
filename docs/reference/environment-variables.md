# Environment Variables

All `SUMMON_*` variables are read from the environment or from the config file
(`~/.config/summon/config.env` by default). Variables in the config file are
overridden by the actual environment.

Use `summon config show` to see resolved values (tokens masked).
Use `summon config set KEY VALUE` to set a value in the config file.

---

## Required

These three variables must be set before summon can start.

| Variable | Description | Example |
|----------|-------------|---------|
| `SUMMON_SLACK_BOT_TOKEN` | Slack Bot User OAuth token. Must start with `xoxb-`. | `xoxb-123-456-abc` |
| `SUMMON_SLACK_APP_TOKEN` | Slack App-Level token for Socket Mode. Must start with `xapp-`. | `xapp-1-A01...` |
| `SUMMON_SLACK_SIGNING_SECRET` | Slack signing secret for request verification. | `abc123def456...` |

See [Slack Setup](../getting-started/slack-setup.md) for instructions on obtaining these values.

---

## Session Defaults

| Variable | Default | Description | Example |
|----------|---------|-------------|---------|
| `SUMMON_DEFAULT_MODEL` | _(Claude's default)_ | Model to use for new sessions. Accepts any Claude model identifier. | `claude-opus-4-6` |
| `SUMMON_DEFAULT_EFFORT` | `high` | Default effort level for new sessions. Must be one of: `low`, `medium`, `high`, `max`. | `medium` |

See [Sessions](../guide/sessions.md) for how model and effort affect behavior.

---

## Display

| Variable | Default | Description | Example |
|----------|---------|-------------|---------|
| `SUMMON_CHANNEL_PREFIX` | `summon` | Prefix for auto-created Slack channel names. Channels are named `{prefix}-{session-name}`. | `claude` |
| `SUMMON_MAX_INLINE_CHARS` | `2500` | Maximum characters for inline Slack messages. Responses longer than this are uploaded as files. | `4000` |
| `SUMMON_PERMISSION_DEBOUNCE_MS` | `500` | Milliseconds to wait before posting a permission request to Slack. Batches rapid tool approvals into a single message. | `1000` |

---

## Thinking

| Variable | Default | Description | Example |
|----------|---------|-------------|---------|
| `SUMMON_ENABLE_THINKING` | `true` | Pass `ThinkingConfigAdaptive` to the Claude SDK, enabling extended thinking when the model decides it's useful. Set to `false` to disable. | `false` |
| `SUMMON_SHOW_THINKING` | `false` | Route `ThinkingBlock` content to the Slack turn thread so thinking is visible. By default thinking is processed but not posted. | `true` |

---

## GitHub Integration

| Variable | Default | Description | Example |
|----------|---------|-------------|---------|
| `SUMMON_GITHUB_PAT` | _(none)_ | GitHub Personal Access Token. Enables the GitHub remote MCP server for all sessions. Accepts classic (`ghp_*`) or fine-grained (`github_pat_*`) tokens. | `ghp_abc123...` |

See [GitHub Integration](../guide/github-integration.md) for setup details.

---

## Scribe Agent

The scribe is a background monitoring agent that watches external sources and surfaces important information in Slack.

| Variable | Default | Description | Example |
|----------|---------|-------------|---------|
| `SUMMON_SCRIBE_ENABLED` | `false` | Enable the scribe agent. | `true` |
| `SUMMON_SCRIBE_GOOGLE_ENABLED` | `false` | Enable the Google Workspace data collector for scribe. Requires workspace-mcp. | `true` |
| `SUMMON_SCRIBE_SCAN_INTERVAL_MINUTES` | `5` | How often the scribe scans for new information. Minimum 1. | `15` |
| `SUMMON_SCRIBE_CWD` | _(data dir)/scribe_ | Working directory for the scribe session. | `/home/user/scribe` |
| `SUMMON_SCRIBE_MODEL` | _(inherits `SUMMON_DEFAULT_MODEL`)_ | Model override for the scribe session. | `claude-haiku-4-5-20251001` |
| `SUMMON_SCRIBE_IMPORTANCE_KEYWORDS` | _(empty)_ | Comma-separated keywords that flag a message as high-priority. | `urgent,action required,deadline` |
| `SUMMON_SCRIBE_QUIET_HOURS` | _(empty)_ | Time window in `HH:MM-HH:MM` format during which only level-5 alerts are surfaced. | `22:00-07:00` |
| `SUMMON_SCRIBE_GOOGLE_SERVICES` | `gmail,calendar,drive` | Comma-separated list of Google Workspace services to monitor. Valid values: `gmail`, `drive`, `calendar`, `docs`, `sheets`, `chat`, `forms`, `slides`, `tasks`, `contacts`, `search`, `appscript`. Requires workspace-mcp. | `gmail,calendar` |
| `SUMMON_SCRIBE_SLACK_ENABLED` | `false` | Enable the Slack data collector (uses Playwright browser automation). | `true` |
| `SUMMON_SCRIBE_SLACK_BROWSER` | `chrome` | Browser for Slack monitoring. Must be one of: `chrome`, `firefox`, `webkit`. | `firefox` |
| `SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS` | _(empty)_ | Comma-separated Slack channel names to monitor. | `general,engineering` |

See [Scribe](../guide/scribe.md) for full setup and configuration details.

---

## System

| Variable | Default | Description | Example |
|----------|---------|-------------|---------|
| `SUMMON_NO_UPDATE_CHECK` | `false` | Disable the background PyPI update check on `summon start`. | `true` |

---

## Standard Variables That Affect summon

These are not summon-specific, but summon respects them:

| Variable | Description |
|----------|-------------|
| `NO_COLOR` | Disable colored terminal output. summon checks this alongside `--no-color`. |
| `EDITOR` | Editor opened by `summon config edit` and `summon hooks set` (when no JSON argument is given). Defaults to system editor. |
| `XDG_CONFIG_HOME` | Base for summon's config directory. Config is stored at `$XDG_CONFIG_HOME/summon/config.env`. Defaults to `~/.config/summon/`. Non-absolute values are ignored. |
| `XDG_DATA_HOME` | Base for summon's data directory (SQLite database, logs, update cache). Stored at `$XDG_DATA_HOME/summon/`. Defaults to `~/.local/share/summon/`. Non-absolute values are ignored. |
