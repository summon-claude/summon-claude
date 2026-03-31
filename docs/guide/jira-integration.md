# Jira Integration

??? info "Prerequisites"
    This guide assumes you've completed the [Quick Start](../getting-started/quickstart.md) and have a working `summon config check`.

summon-claude integrates with Jira via the Atlassian Rovo MCP server, giving Claude read-only access to Jira issues, projects, and Confluence pages.

---

## Setup

Authenticate with Jira using OAuth 2.1:

```{ .bash .notest }
summon auth jira login
```

This opens a browser for Atlassian OAuth consent (PKCE + Dynamic Client Registration). No admin privileges are required — the flow uses your personal Atlassian account.

To skip interactive site discovery, pass the `--site` flag:

```{ .bash .notest }
summon auth jira login --site myorg
# or with a full hostname:
summon auth jira login --site myorg.atlassian.net
```

To verify authentication status:

```{ .bash .notest }
summon auth jira status
```

Credentials are stored locally in `~/.config/summon/jira-credentials/` with 0600 permissions. The refresh token is used automatically — you should not need to re-authenticate unless you revoke access.

---

## Removing Credentials

```{ .bash .notest }
summon auth jira logout
```

---

## Per-Project JQL Filters

When using PM agents (`summon project`), you can associate a JQL filter with each project. The PM agent uses this filter during periodic scans to triage relevant Jira issues:

```{ .bash .notest }
# Set a JQL filter when registering a project
summon project add myproject ./myproject --jql "project = MYPROJ AND status != Done"

# Update the filter for an existing project
summon project update myproject --jql "project = MYPROJ AND assignee = currentUser()"

# Clear the filter
summon project update myproject --jql ""
```

Without a `--jql` filter, the PM agent scans all issues visible to the authenticated user.

### Common JQL Patterns

| Use case | JQL |
|----------|-----|
| Single project | `project = MYPROJ AND status != Done` |
| Assigned to me | `assignee = currentUser() AND status != Done` |
| High priority | `project = MYPROJ AND priority in (Critical, Blocker)` |
| Recently updated | `project = MYPROJ AND updated >= -7d` |

---

## Permission Model

All Jira MCP tools are classified into permission tiers:

- **Auto-approved (read-only):** Tools matching `get*`, `search*`, `lookup*` prefixes, plus `atlassianUserInfo`. These run without user confirmation.
- **Hard-denied (write operations):** `createJiraIssue`, `editJiraIssue`, `transitionJiraIssue`, `addCommentToJiraIssue`, `addWorklogToJiraIssue`, and all Confluence write tools. Claude cannot perform write operations even if prompted.
- **Hard-denied (security):** `fetchAtlassian` — a generic accessor that bypasses tool-level gating.
- **Fail-closed:** Any unknown Jira tool (e.g., from a future Rovo MCP update) is denied by default until explicitly classified.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `summon auth jira status` says "no cloud_id" | Re-run `summon auth jira login` — site discovery may have failed on first attempt |
| Browser doesn't open during login | Check that `$BROWSER` is set or open the printed URL manually |
| "DCR failed" error | Atlassian's Dynamic Client Registration endpoint may be temporarily unavailable — retry after a few minutes |
| Token refresh failures in logs | Automatic — sessions proceed without Jira if refresh fails. Re-login if persistent: `summon auth jira login` |
