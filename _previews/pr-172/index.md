# summon-claude

**Bridge Claude Code sessions to Slack channels**

Run long-running AI agents in the background. Interact, review permissions, and receive responses — all without leaving Slack.

______________________________________________________________________

- **[Project management](https://summon-claude.github.io/summon-claude/guide/projects/index.md)**

  ______________________________________________________________________

  Group sessions into projects with a PM agent that spawns, directs, and monitors multiple Claude sessions on your behalf.

- **[Real-time streaming](https://summon-claude.github.io/summon-claude/concepts/threading/index.md)**

  ______________________________________________________________________

  Responses stream to Slack as Claude types them. No waiting for full completions before you see results.

- **[Interactive permissions](https://summon-claude.github.io/summon-claude/reference/permissions/index.md)**

  ______________________________________________________________________

  Tool-use requests surface as Slack buttons. Approve or deny without switching to a terminal.

- **[Smart thread organization](https://summon-claude.github.io/summon-claude/concepts/threading/#subagent-threads)**

  ______________________________________________________________________

  Each turn gets its own thread. Subagent work is nested automatically so your channel stays readable.

- **[Canvas integration](https://summon-claude.github.io/summon-claude/guide/canvas/index.md)**

  ______________________________________________________________________

  Persistent markdown canvas per session. Claude can read and write structured notes that survive conversation compaction.

- **[Scheduled jobs and tasks](https://summon-claude.github.io/summon-claude/guide/cron-tasks/index.md)**

  ______________________________________________________________________

  Create cron-style recurring jobs and track task progress directly from Slack.

______________________________________________________________________

## How it works

**1. Register a project**

```
summon project add my-api ~/code/my-api
```

Link a name, working directory, and Slack channel prefix to a project.

**2. Set workflow instructions**

```
summon project workflow set my-api
```

Encode team conventions, coding standards, or project context into every session's system prompt.

**3. Start your PM agents**

```
summon project up
```

PM agents launch in the background for all registered projects. Authenticate each one in Slack with `/summon CODE`, then give it instructions — the PM spawns, directs, and monitors child sessions on your behalf.

**4. Interact entirely through Slack**

Send messages, review tool permissions with buttons, and receive streaming responses — no terminal required. The PM coordinates everything.

Quick ad-hoc sessions

Don't need the full project setup? Run `summon start` to launch a single session directly. See the [Quick Start guide](https://summon-claude.github.io/summon-claude/getting-started/quickstart/index.md).

______________________________________________________________________

## Quick install

```
uv tool install summon-claude
```

```
pipx install summon-claude
```

```
brew install summon-claude/summon/summon-claude
```

Then run the interactive setup wizard:

```
summon init
```

[Get started with the full setup guide](https://summon-claude.github.io/summon-claude/getting-started/quickstart/index.md) [Installation details](https://summon-claude.github.io/summon-claude/getting-started/installation/index.md)
