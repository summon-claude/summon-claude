# GitHub Integration

summon-claude can connect Claude sessions to the GitHub remote MCP server, giving Claude access to GitHub tools (read repositories, search code, create issues, review PRs, etc.) directly from Slack.

---

## Setup

Set your GitHub Personal Access Token in the summon config:

```bash
summon config set SUMMON_GITHUB_PAT ghp_your_token_here
```

Or add it to your config file:

```bash
# ~/.config/summon/config.env
SUMMON_GITHUB_PAT=ghp_your_token_here
```

!!! note "No Copilot subscription required"
    The GitHub remote MCP server at `api.githubcopilot.com/mcp/` works with a standard GitHub PAT (classic `ghp_*` or fine-grained `github_pat_*`). A GitHub Copilot subscription is not required.

Once set, the GitHub MCP server is wired into **all** sessions automatically — no per-session configuration needed.

---

## How it works

When `SUMMON_GITHUB_PAT` is configured, summon adds the GitHub remote MCP server to every Claude session's `mcp_servers` list:

```
https://api.githubcopilot.com/mcp/
Authorization: Bearer <your-pat>
```

This uses GitHub's HTTP transport (no local binary or Go install required). The MCP connection is lazy — it only connects when Claude first uses a GitHub tool, so startup time is unaffected.

---

## Available tools

Claude gets access to the full GitHub MCP tool set, including:

- Repository browsing and file contents
- Code search across repositories
- Issue and pull request reading and creation
- PR review submission
- Branch and commit inspection
- Security advisory lookups

The specific tools available depend on GitHub's MCP server version. Claude will report any tool-not-found errors if a tool it tries to use is not available.

---

## Permission tiers

Not all GitHub operations require your approval. summon enforces a three-tier permission model:

### Tier 1: Auto-approved (read-only)

These tools are approved automatically without prompting you:

- Any tool with a name starting with `get_`, `list_`, or `search_`
- `pull_request_read`
- `get_file_contents`

### Tier 2: Requires your approval (writes)

These operations are routed through the standard summon HITL (human-in-the-loop) flow — Claude posts a request to Slack and waits for you to approve or deny:

**Destructive or irreversible operations:**

- `merge_pull_request`
- `delete_branch`
- `close_issue`
- `close_pull_request`
- `push_files`

**Visible-to-others operations:**

- `create_pull_request`
- `create_issue`
- `add_comment` (PR and issue comments)
- `pull_request_review_write`

!!! tip "Why are comments in Tier 2?"
    Comments, PR reviews, and new issues are visible to everyone in your repository. summon routes these through HITL so you can review what Claude is about to post before it goes public.

### Tier 3: Unknown tools (fail-closed)

If a GitHub tool is not in either of the above tiers, it is treated as requiring approval. summon never auto-approves unknown tools.

---

## Secret redaction

GitHub tokens are automatically redacted from all Slack output and log files. The following patterns are scrubbed:

| Token type | Pattern |
|---|---|
| Classic PAT | `ghp_...` |
| Fine-grained PAT | `github_pat_...` |
| OAuth token | `gho_...` |
| User token | `ghu_...` |
| Server-to-server | `ghs_...` |
| Refresh token | `ghr_...` |

Redaction happens at the Slack output boundary — tokens cannot appear in messages, file uploads, canvas content, or channel topics.

---

## PR reviewer sessions

A common pattern is to have the PM agent spawn a dedicated PR reviewer session:

```
Review the open pull requests in github.com/myorg/myrepo.
Spawn a worker to do a thorough code review on PR #42 and post
a summary to the canvas when done.
```

The PM spawns a worker session, which uses the GitHub MCP tools to read the PR diff, files, and existing comments, then posts a review. The PM receives the results and can present them to you or trigger further actions.

The reviewer session uses Opus for thorough code analysis. Approval of the actual PR review submission (`pull_request_review_write`) still requires your Slack approval.

---

## Troubleshooting

**Claude says GitHub tools are not available**

Check that `SUMMON_GITHUB_PAT` is set:

```bash
summon config show
```

The token should appear (masked) in the output. If it is missing, re-run `summon config set SUMMON_GITHUB_PAT <token>`.

**Permission denied errors from GitHub**

The PAT may lack the required scopes. For most operations, a classic PAT needs:
- `repo` — full repository access
- `read:org` — for organization repositories

For fine-grained PATs, grant repository read/write access for the specific repos.

**Tool calls time out**

The GitHub MCP server is remote — network latency affects tool response times. This is expected. If the server is unreachable, Claude will receive an error and adapt its approach without the session failing.

---

## Related

- [Sessions](sessions.md) — session lifecycle
- [PM Agents](pm-agents.md) — spawning reviewer sessions
- [Configuration](configuration.md) — full config reference
