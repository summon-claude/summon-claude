# Context Management

Claude has a fixed context window — the total amount of text it can process at once. summon-claude actively manages this window so long-running sessions don't silently lose important context.

______________________________________________________________________

## How context tracking works

Every time Claude responds, summon reads the cumulative token usage from the SDK and calculates a **context percentage** — how full the context window is. This percentage is stored in the session database and displayed in `!status` output.

Context percentage is also synced to the session canvas (if one exists), so the PM agent can monitor child session health during periodic scans.

______________________________________________________________________

## Compaction

When context usage crosses a threshold (typically ~80%), summon triggers **compaction** — asking Claude to summarize the conversation so far into a structured summary. The summary replaces the conversation history, freeing context space while preserving key information.

The compaction summary follows a fixed structure:

- **Task Overview** — what was requested, success criteria, constraints
- **Current State** — what's done, in progress, and remaining
- **Files & Artifacts** — exact file paths read, created, or modified (verbatim, not paraphrased)
- **Key Decisions** — technical decisions and rationale
- **Errors & Resolutions** — issues encountered and how they were resolved
- **Next Steps** — actions needed, in priority order
- **Context to Preserve** — user preferences, promises made, domain details

After compaction, the summary is injected into the system prompt so Claude retains the context without the full conversation history.

Compaction is automatic

You don't need to trigger compaction manually. summon monitors context usage and compacts when needed. The `!status` command shows current context percentage.

______________________________________________________________________

## Overflow recovery

If a session's context is so full that even generating a compaction summary would fail, summon performs **overflow recovery** — it restarts the Claude session with a clean context and instructs Claude to recover context by reading the Slack channel's message history.

The recovery process:

1. Claude reads the channel history using `slack_read_history`
1. Identifies what was being worked on
1. Notes decisions, file changes, and errors
1. Confirms with the user what was recovered before proceeding

Overflow recovery is a last resort — compaction handles the vast majority of cases. If you see overflow recovery triggered frequently, consider breaking large tasks into smaller sessions.

______________________________________________________________________

## Scheduled job persistence

Compaction removes conversation history, which means Claude "forgets" about any scheduled jobs (cron tasks) it created. To handle this, summon re-injects scheduling context after compaction — Claude is prompted to re-create any lost scheduled jobs based on the compaction summary.

System-managed jobs (like the PM's scan timer) are handled by summon directly and survive compaction automatically.

______________________________________________________________________

## See also

- [Sessions](https://summon-claude.github.io/summon-claude/guide/sessions/index.md) — session lifecycle and management
- [Cron & Tasks](https://summon-claude.github.io/summon-claude/guide/cron-tasks/index.md) — scheduled jobs and task tracking
- [Canvas](https://summon-claude.github.io/summon-claude/guide/canvas/index.md) — persistent session documents that survive compaction
