# Configuration

summon-claude is configured entirely through environment variables with the `SUMMON_` prefix. You can set them in a config file, a `.env` file in your working directory, or directly in your shell environment.

______________________________________________________________________

## Config file location

summon follows the [XDG Base Directory spec](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html):

| Variable                          | Config path                          |
| --------------------------------- | ------------------------------------ |
| `XDG_CONFIG_HOME` set             | `$XDG_CONFIG_HOME/summon/config.env` |
| Default                           | `~/.config/summon/config.env`        |
| Fallback (if `~/.config` missing) | `~/.summon/config.env`               |

Data (database, logs) follows the same pattern under `XDG_DATA_HOME` / `~/.local/share/summon`.

Use `summon config path` to print the exact config file path in use.

______________________________________________________________________

## Loading priority

Settings are resolved in this order (later overrides earlier):

1. **Config file** (`~/.config/summon/config.env` or XDG override)
1. **`.env` file** in the current working directory
1. **Shell environment variables**

The `--config PATH` flag on the `summon` command overrides the config file path.

______________________________________________________________________

## Initial setup

Use the interactive setup wizard to create your configuration:

```
summon init
```

See [Configuring Summon](https://summon-claude.github.io/summon-claude/latest/getting-started/configuration/index.md) for the full wizard walkthrough and credential setup details.

The three required Slack credentials are covered in [Slack Setup](https://summon-claude.github.io/summon-claude/latest/getting-started/slack-setup/index.md).

______________________________________________________________________

## Configuration options

For the complete list of all configuration options with config keys, environment variables, types, defaults, and descriptions, see the [Configuration Reference](https://summon-claude.github.io/summon-claude/latest/reference/environment-variables/index.md).

______________________________________________________________________

## Config subcommands

### summon config show

```
summon config show
```

Displays all configuration options organized by section (Slack Credentials, Session Defaults, Scribe, Scribe Google, Scribe Slack, GitHub, Display, Behavior, Thinking). Each option shows a source indicator:

- **(set)** — explicitly configured in the config file
- **(default)** — using the built-in default value
- **(not set)** — a required value that is missing
- **(optional)** — an optional secret that has not been configured

Disabled sections (e.g., Scribe Google when `scribe_google_enabled` is false) are shown dimmed with a "disabled" label.

```
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
    GitHub: configured (OAuth)
```

### summon config path

```
summon config path
```

Prints the absolute path to the config file in use.

### summon config set

```
summon config set SUMMON_DEFAULT_MODEL claude-opus-4-6
summon config set SUMMON_CHANNEL_PREFIX my-team
summon config set SUMMON_SCRIBE_ENABLED true
```

Sets a single key in the config file. Creates the file if it does not exist. The key must be a valid `SUMMON_*` configuration variable — unknown keys are rejected with an error listing all valid options.

Boolean values are normalized: `true`, `false`, `yes`, `no`, `on`, `off`, `1`, and `0` are all accepted and stored as `true` or `false`. Choice-type options (like `SUMMON_DEFAULT_EFFORT`) are validated against their allowed values.

### summon config edit

```
summon config edit
```

Opens the config file in `$EDITOR`. If `$EDITOR` is not set, falls back to `vi`.

### summon config check

```
summon config check
```

Validates configuration and tests connectivity. See [Configuring Summon](https://summon-claude.github.io/summon-claude/latest/getting-started/configuration/#running-summon-config-check) for detailed output interpretation.

______________________________________________________________________

For external Slack workspace commands (browser-based monitoring), see [Scribe](https://summon-claude.github.io/summon-claude/latest/guide/scribe/#slack-browser-monitoring).

______________________________________________________________________

## Example config file

```
# ~/.config/summon/config.env

# Required: Slack credentials
SUMMON_SLACK_BOT_TOKEN=xoxb-your-bot-token
SUMMON_SLACK_APP_TOKEN=xapp-your-app-token
SUMMON_SLACK_SIGNING_SECRET=your-signing-secret

# Optional: model and behavior
SUMMON_DEFAULT_MODEL=claude-opus-4-6
SUMMON_DEFAULT_EFFORT=high
SUMMON_CHANNEL_PREFIX=ai

# Optional: disable update checks
# SUMMON_NO_UPDATE_CHECK=true
```

Secret management

The config file is created with `0600` permissions by `summon init`. For team environments or CI, prefer injecting secrets via environment variables rather than committing a config file.
