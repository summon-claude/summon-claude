# In-Session Commands

Once a session is active, you can control it from Slack using `!`-prefixed commands. Commands are detected anywhere in a message — you can embed them mid-sentence or chain multiple commands.

```
!help
Fix the login bug !stop
!model claude-opus-4-5 then continue with high effort !effort high
```

______________________________________________________________________

## Command syntax

- Commands start with `!` (or `/` for Claude CLI passthroughs)
- The command name is case-insensitive
- Arguments follow the command name, separated by spaces
- Commands may appear anywhere in a message — before, after, or between other text
- Unknown commands return a helpful error message

```
!help
!help status
!model claude-opus-4-5
!effort high
```

______________________________________________________________________

## Session commands

These commands are handled locally by summon without forwarding to Claude.

| Command                       | Aliases                     | Description                                                   |
| ----------------------------- | --------------------------- | ------------------------------------------------------------- |
| `!help [COMMAND]`             |                             | List all commands, or show details for one command            |
| `!status`                     |                             | Show session status (model, effort, cost, uptime, turn count) |
| `!end`                        | `!quit`, `!exit`, `!logout` | End the session gracefully                                    |
| `!stop`                       |                             | Cancel the current Claude turn (interrupt mid-response)       |
| `!clear`                      | `!new`, `!reset`            | Clear conversation history (start fresh context)              |
| `!model [MODEL]`              |                             | Show current model, or switch to a different model            |
| `!effort [LEVEL]`             |                             | Show current effort, or switch effort level                   |
| `!auto [on\|off\|rules]`      | `!automode`                 | Toggle or inspect the auto-mode classifier                    |
| `!compact [INSTRUCTIONS]`     |                             | Compact conversation context (reduces token usage)            |
| `!summon start`               |                             | Spawn a new child session in the current channel              |
| `!summon resume [SESSION_ID]` |                             | Resume a previous Claude Code session                         |
| `!diff FILE`                  |                             | Show a git diff for a file changed this session               |
| `!changes`                    |                             | Show all files changed in this session                        |

### !help

```
!help
!help status
!help model
!help global-commands   # list a plugin's skills
```

Without arguments, lists all available commands grouped by type. With an argument, shows usage and description for that command, including its type (local, passthrough, or blocked) and any aliases.

### !status

```
!status
```

Returns current session information:

```
*Session Status*
  Model: `claude-opus-4-6`
  Effort: `high`
  Session ID: `abc123...`
  Turns: 7
  Cost: $0.0342
  Uptime: 42m 15s
```

### !model

```
!model                        # show current model
!model claude-opus-4-6        # switch model
!model claude-sonnet-4-6
```

Lists available models when called without arguments. Switching takes effect on the next turn.

### !effort

```
!effort                 # show current effort
!effort low             # switch to low effort
!effort high            # switch to high effort
!effort max             # switch to max (extended thinking)
```

Valid levels: `low`, `medium`, `high`, `max`. Takes effect on the next turn.

Extended thinking

`!effort max` enables extended thinking (ultrathink mode). Claude will reason more deeply but responses will take longer and cost more.

### !auto

```
!auto                   # show classifier status
!auto on                # enable the classifier
!auto off               # disable the classifier
!auto rules             # show effective allow/deny rules
```

Toggles the auto-mode classifier, which automatically approves or blocks tool calls based on configurable prose rules. See [Permissions — Auto-mode classifier](https://summon-claude.github.io/summon-claude/latest/reference/permissions/#auto-mode-classifier) for details.

Requires worktree

`!auto on` only works after the agent has entered a worktree. Before worktree entry, the classifier is dormant regardless of configuration.

`!auto off` and `!auto rules` work at any time.

### !compact

```
!compact
!compact Focus on the authentication module
```

Compacts the conversation context to reduce token usage. Optional instructions tell Claude what to emphasize when summarizing the context. The conversation history is replaced with a summary.

### !summon

```
!summon start                   # spawn a new child session
!summon resume                  # resume most recent session
!summon resume <session-id>     # resume a specific session
```

Spawns or resumes sessions from within a running session. Child sessions appear as new Slack channels. Requires the PM agent feature — see [Projects](https://summon-claude.github.io/summon-claude/latest/guide/projects/index.md).

### !diff

```
!diff src/auth/login.py
!diff package.json
```

Shows a unified diff for the named file, covering changes made during this session. Rendered as a Slack snippet with syntax highlighting.

### !changes

```
!changes
```

Lists all files created or modified during this session, with line addition/deletion counts.

______________________________________________________________________

## Claude CLI passthroughs

These commands are forwarded directly to the Claude Code CLI subprocess. They trigger Claude's built-in slash commands.

| Command                      | Description                           |
| ---------------------------- | ------------------------------------- |
| `!review`                    | Review code changes                   |
| `!init`                      | Initialize project configuration      |
| `!pr-comments`               | Review PR comments                    |
| `!security-review`           | Run a security review                 |
| `!simplify`                  | Simplify and refine code              |
| `!debug`                     | Debug session issues                  |
| `!claude-developer-platform` | Claude developer platform information |

Passthrough commands produce output in the session channel, the same as if you had typed them in a local Claude terminal.

______________________________________________________________________

## Blocked commands

Some Claude CLI commands are blocked in Slack sessions because they depend on a local terminal or produce output that can't be rendered in Slack.

### Blocked with specific reasons

| Command          | Reason                                                |
| ---------------- | ----------------------------------------------------- |
| `!insights`      | Generates a local HTML report — not viewable in Slack |
| `!context`       | Use `!status` instead                                 |
| `!cost`          | Use `!status` instead                                 |
| `!release-notes` | Not available in Slack sessions                       |
| `!login`         | Not available in Slack sessions                       |

### CLI-only commands

These commands require the interactive Claude CLI and are blocked with: *"Only available in the interactive CLI"*

`!config` (`!settings`), `!doctor`, `!desktop` (`!app`), `!feedback` (`!bug`), `!permissions` (`!allowed-tools`), `!mobile` (`!ios`, `!android`), `!resume` (`!continue`), `!rewind` (`!checkpoint`), `!remote-control` (`!rc`), `!add-dir`, `!agents`, `!chrome`, `!copy`, `!export`, `!extra-usage`, `!fast`, `!fork`, `!hooks`, `!ide`, `!install-github-app`, `!install-slack-app`, `!keybindings`, `!mcp`, `!memory`, `!output-style`, `!passes`, `!plan`, `!plugin`, `!privacy-settings`, `!reload-plugins`, `!remote-env`, `!rename`, `!sandbox`, `!skills`, `!stats`, `!statusline`, `!stickers`, `!tasks`, `!terminal-setup`, `!theme`, `!upgrade`, `!usage`, `!vim`

When a blocked command is used, summon responds with a clear explanation rather than forwarding it to Claude.

______________________________________________________________________

## Plugin skills

If you have Claude Code plugins installed, their skills and commands are available in sessions using the `plugin:skill` syntax:

```
!global-commands:session-start
!dev-essentials:lint
```

Use `!help PLUGIN` to list all skills from a specific plugin:

```
!help global-commands
```

Plugin skills are discovered automatically at session startup from `~/.claude/plugins/installed_plugins.json`. Unambiguous skill names can be used without the plugin prefix:

```
!session-start    # if only one plugin has a skill named "session-start"
```

If two plugins provide the same skill name, the short form is ambiguous and disabled — use the full `plugin:skill` form instead.

______________________________________________________________________

## Mid-message detection

Commands are detected anywhere in a message using a regex that matches `!cmd` or `/cmd` tokens after whitespace or at the start of the message. URLs and file paths are excluded:

- `https://example.com` — not a command (URL)
- `repo/review` — not a command (path-like)
- `Run !review then !status` — two commands detected

For local commands with arguments (like `!model` and `!effort`), arguments are consumed from the text immediately following the command. The regex stops consuming at the next `!cmd` or `/cmd` token, so you can chain commands naturally:

```
Switch to opus !model claude-opus-4-6 and max effort !effort max
```
