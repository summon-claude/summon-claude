# Installation

## Prerequisites

- **Python 3.12 or later** — required by summon-claude
- **Claude Code CLI** — must be installed and authenticated before using summon-claude

Claude Code authentication

summon-claude launches Claude Code sessions on your behalf. Run `claude` at least once to complete authentication before proceeding.

______________________________________________________________________

## Install summon-claude

[uv](https://docs.astral.sh/uv/) installs summon-claude as an isolated tool with its own managed Python environment.

```
uv tool install summon-claude
```

uv is the recommended method because it handles Python version management automatically and produces the fastest install times.

[pipx](https://pipx.pypa.io/stable/) installs summon-claude in an isolated virtualenv and exposes the `summon` command globally.

```
pipx install summon-claude
```

Install via the summon-claude tap:

```
brew install summon-claude/summon/summon-claude
```

Note

The Homebrew formula bundles its own Python, so your system Python version does not matter.

______________________________________________________________________

## Optional extras

Some features require additional dependencies that are not included in the base install. Install them as **extras** when you need them:

| Extra           | Feature                                                                                                                                           | Dependency                                                             |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `google`        | Google Workspace integration (Gmail, Calendar, Drive) for the [scribe](https://summon-claude.github.io/summon-claude/guide/scribe/index.md) agent | [workspace-mcp](https://github.com/taylorwilsdon/google_workspace_mcp) |
| `slack-browser` | Slack browser monitoring for the [scribe](https://summon-claude.github.io/summon-claude/guide/scribe/index.md) agent                              | [Playwright](https://playwright.dev/python/)                           |
| `all`           | All optional extras                                                                                                                               | Both of the above                                                      |

```
# Google Workspace integration (for scribe)
uv tool install "summon-claude[google]"

# Slack browser monitoring (for scribe)
uv tool install "summon-claude[slack-browser]"

# All optional extras
uv tool install "summon-claude[all]"
```

```
# Google Workspace integration (for scribe)
pipx install "summon-claude[google]"

# Slack browser monitoring (for scribe)
pipx install "summon-claude[slack-browser]"

# All optional extras
pipx install "summon-claude[all]"
```

No extras needed — the Homebrew formula includes all dependencies.

```
brew install summon-claude/summon/summon-claude
```

Already installed without extras?

If you already installed summon-claude and need to add extras, reinstall with the extra specified. See [Troubleshooting: extras not found](https://summon-claude.github.io/summon-claude/troubleshooting/#installation) if you encounter `ImportError` for `workspace_mcp` or `playwright`.

______________________________________________________________________

## Verify the installation

```
summon version
```

You should see output like:

```
summon, version 1.2.3
Python:      3.12.x
Platform:    darwin
Config file: ~/.config/summon/config.env
Data dir:    ~/.local/share/summon
DB path:     ~/.local/share/summon/registry.db
```

______________________________________________________________________

## Shell completion

summon-claude uses Click, which supports tab completion for bash, zsh, and fish.

Add to `~/.bashrc`:

```
eval "$(_SUMMON_COMPLETE=bash_source summon)"
```

Add to `~/.zshrc`:

```
eval "$(_SUMMON_COMPLETE=zsh_source summon)"
```

Add to `~/.config/fish/completions/summon.fish`:

```
_SUMMON_COMPLETE=fish_source summon | source
```

______________________________________________________________________

## Upgrading

| Install method | Upgrade command                 |
| -------------- | ------------------------------- |
| uv             | `uv tool upgrade summon-claude` |
| pipx           | `pipx upgrade summon-claude`    |
| Homebrew       | `brew upgrade summon-claude`    |

See [Upgrading](https://summon-claude.github.io/summon-claude/getting-started/upgrading/index.md) for details on checking versions and handling breaking changes.

______________________________________________________________________

## Disabling update checks

summon-claude checks for new versions on startup. To disable this:

```
summon config set SUMMON_NO_UPDATE_CHECK true
```

Or set `SUMMON_NO_UPDATE_CHECK=true` in your config file (`~/.config/summon/config.env`).
