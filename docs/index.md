# summon-claude

**Bridge Claude Code sessions to Slack channels**

Run long-running AI agents in the background. Interact, review permissions, and receive responses — all without leaving Slack.

---

<div class="grid cards" markdown>

-   **Real-time streaming**

    ---

    Responses stream to Slack as Claude types them. No waiting for full completions before you see results.

-   **Interactive permissions**

    ---

    Tool-use requests surface as Slack buttons. Approve or deny without switching to a terminal.

-   **Smart thread organization**

    ---

    Each turn gets its own thread. Subagent work is nested automatically so your channel stays readable.

-   **Canvas integration**

    ---

    Persistent markdown canvas per session. Claude can read and write structured notes that survive conversation compaction.

-   **Project management**

    ---

    Group sessions into projects with a PM agent coordinating work across multiple Claude sessions.

-   **Scheduled jobs and tasks**

    ---

    Create cron-style recurring jobs and track task progress directly from Slack.

</div>

---

## How it works

**1. Start a session**

```bash
summon start
```

summon-claude launches a Claude Code session in the background and prints a short authentication code.

**2. Authenticate in Slack**

In any Slack channel, type:

```
/summon ABC123
```

Claude connects to that channel. All interaction happens there from now on.

**3. Interact entirely through Slack**

Send messages, review tool permissions with buttons, and receive streaming responses — no terminal required.

---

## Quick install

=== "uv (Recommended)"
    ```bash
    uv tool install summon-claude
    ```

=== "pipx"
    ```bash
    pipx install summon-claude
    ```

=== "Homebrew"
    ```bash
    brew install summon-claude/summon/summon-claude
    ```

[Get started with the full setup guide](getting-started/quickstart.md){ .md-button .md-button--primary }
[Installation details](getting-started/installation.md){ .md-button }
