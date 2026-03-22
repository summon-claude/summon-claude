# Installation

## Prerequisites

- **Python 3.12 or later** — required by summon-claude
- **Claude Code CLI** — must be installed and authenticated before using summon-claude

!!! note "Claude Code authentication"
    summon-claude launches Claude Code sessions on your behalf. Run `claude` at least once to complete authentication before proceeding.

---

## Install summon-claude

=== "uv (Recommended)"
    [uv](https://docs.astral.sh/uv/) installs summon-claude as an isolated tool with its own managed Python environment.

    ```bash
    uv tool install summon-claude
    ```

    uv is the recommended method because it handles Python version management automatically and produces the fastest install times.

=== "pipx"
    [pipx](https://pipx.pypa.io/) installs summon-claude in an isolated virtualenv and exposes the `summon` command globally.

    ```bash
    pipx install summon-claude
    ```

=== "Homebrew"
    Install via the summon-claude tap:

    ```bash
    brew install summon-claude/summon/summon-claude
    ```

    !!! note
        The Homebrew formula bundles its own Python, so your system Python version does not matter.

---

## Verify the installation

```bash
summon --version
```

You should see output like:

```
summon-claude, version 1.2.3
```

---

## Shell completion

summon-claude uses Click, which supports tab completion for bash, zsh, and fish.

=== "bash"
    Add to `~/.bashrc`:

    ```bash
    eval "$(_SUMMON_COMPLETE=bash_source summon)"
    ```

=== "zsh"
    Add to `~/.zshrc`:

    ```zsh
    eval "$(_SUMMON_COMPLETE=zsh_source summon)"
    ```

=== "fish"
    ```fish
    _SUMMON_COMPLETE=fish_source summon | source
    ```

    Or to make it persistent, add to `~/.config/fish/completions/summon.fish`:

    ```fish
    _SUMMON_COMPLETE=fish_source summon | source
    ```

---

## Upgrading

| Install method | Upgrade command |
|----------------|-----------------|
| uv | `uv tool upgrade summon-claude` |
| pipx | `pipx upgrade summon-claude` |
| Homebrew | `brew upgrade summon-claude` |

See [Upgrading](upgrading.md) for details on checking versions and handling breaking changes.

---

## Disabling update checks

summon-claude checks for new versions on startup. To disable this:

```bash
export SUMMON_NO_UPDATE_CHECK=1
```

Add this to your shell profile to make it permanent.
