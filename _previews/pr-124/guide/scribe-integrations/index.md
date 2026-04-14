# Scribe Integrations

Prerequisites

This guide assumes you've completed the [Quick Start](https://summon-claude.github.io/summon-claude/getting-started/quickstart/index.md), have a working `summon config check`, and have [enabled the Scribe](https://summon-claude.github.io/summon-claude/guide/scribe/#setup).

The [Scribe agent](https://summon-claude.github.io/summon-claude/guide/scribe/index.md) can monitor external data sources and surface important information to your Slack channel. Each integration is optional — enable whichever ones are useful for your workflow.

| Integration                                           | What it provides                    | Extra required                 |
| ----------------------------------------------------- | ----------------------------------- | ------------------------------ |
| [Google Workspace](#google-workspace)                 | Gmail, Calendar, Drive monitoring   | `summon-claude[google]`        |
| [Slack Browser Monitoring](#slack-browser-monitoring) | External Slack workspace monitoring | `summon-claude[slack-browser]` |

______________________________________________________________________

## Google Workspace

The Scribe can monitor Gmail, Google Calendar, and Google Drive for important updates.

### Setup

Install the Google extra if you haven't already:

```
uv pip install 'summon-claude[google]'
```

```
pipx inject summon-claude workspace-mcp
```

Run the guided setup to create Google OAuth credentials:

```
summon auth google setup
```

The setup is an interactive wizard with a progress roadmap — each step gets a clean screen showing where you are and what's next:

1. **Google Cloud Project** — select an existing project or create a new one. If `gcloud` is installed, the wizard detects your current project and offers it as the default, and can create new projects for you. Console links route through Google's account chooser for multi-account users.
1. **Enable APIs** — enable Gmail, Calendar, and Drive APIs. If `gcloud` is installed, offers to run the command directly; otherwise provides browser links with an option to open them automatically.
1. **OAuth Consent Screen** — configure branding and set publishing status to Production (avoids 7-day token expiry). Links open directly in your browser.
1. **Create OAuth Client** — create a "Desktop app" OAuth client and download `client_secret.json`. The wizard accepts either the JSON file path or a manually pasted Client ID + Secret.

Already have a GCP project with OAuth configured?

In step 1, choose "Skip this step" to proceed directly to API enablement and credentials.

Then authenticate with Google:

```
summon auth google login
```

This prompts which services need write access (all are read-only by default), then opens a browser for OAuth consent. Credentials are stored in summon's config directory (`google-credentials/`).

To re-run later and change scope access (e.g., grant or revoke write access for a service), run `summon auth google login` again — prompt defaults match your current grants so you won't accidentally downgrade.

To verify authentication status:

```
summon auth google status
```

This shows whether credentials exist, which scopes are granted (read-only vs read-write per service), and whether the token is still valid.

### Enabling the Google collector

The Google collector is **auto-detected**: when workspace-mcp is installed and Google credentials exist, the scribe automatically uses Google tools. No manual config flag is needed.

To explicitly disable it: `summon config set SUMMON_SCRIBE_GOOGLE_ENABLED false`

Available Google services are auto-detected from the OAuth scopes granted during `summon auth google login`. The scribe automatically monitors whichever services the credential supports (e.g., Gmail, Calendar, Drive).

______________________________________________________________________

## Slack Browser Monitoring

The Scribe can monitor an external Slack workspace using browser-based WebSocket interception. This is separate from the native Slack bot integration used for session interaction — it watches a different workspace (e.g., your company's Slack) via a real browser session.

Browser-based monitoring

Slack channel monitoring uses Playwright to capture WebSocket frames from your Slack workspace. This requires the `slack-browser` extra and a Chromium-based browser installed on the host.

### Setup

Install the Slack browser extra if you haven't already:

```
uv pip install 'summon-claude[slack-browser]'
```

```
pipx inject summon-claude playwright
```

### Authenticate with a Slack workspace

```
summon auth slack login myteam
```

This opens a visible browser window at your Slack workspace. Log in normally — the browser closes automatically after detecting your session. Auth state (cookies and localStorage) is saved to summon's data directory.

The `WORKSPACE` argument accepts:

- A workspace name: `myteam` (becomes `https://myteam.slack.com`)
- An enterprise name: `acme.enterprise` (becomes `https://acme.enterprise.slack.com`)
- A full URL: `https://myteam.slack.com`

After login, the command prompts you to select which channels to monitor using an interactive picker.

Enterprise Grid workspaces

Enterprise Grid workspaces serve a workspace picker at their enterprise URL. The scribe handles this automatically by extracting team IDs from the saved browser state and navigating directly to `app.slack.com/client/{TEAM_ID}`.

### Select monitored channels

To change which channels are monitored without re-authenticating:

```
summon auth slack channels
```

This uses the cached channel list from the last authentication. To refresh the channel list from Slack:

```
summon auth slack channels --refresh
```

### Check auth status

```
summon auth slack status
```

Shows the configured workspace URL, user ID, auth state age, and monitored channels.

### Remove auth state

```
summon auth slack logout
```

Removes saved browser auth state and workspace config. This cannot be undone.

### Enabling the Slack collector

Once authenticated, the Slack collector auto-enables on the next `summon project up`. Optionally configure monitored channels and browser:

```
summon config set SUMMON_SCRIBE_SLACK_BROWSER chrome
summon config set SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS C01ABC123,C02DEF456
```

DMs and @mentions are always captured regardless of the channel list. The channel list controls which channels have *all* messages monitored.

### How it works

The browser user must be a member of any channel being monitored — the WebSocket only delivers messages for channels the authenticated user belongs to.

The primary auth cookie (`d`) has a roughly 1-year TTL, so re-authentication is rarely needed. The `x` cookie (CSRF) is not required.

______________________________________________________________________

## See also

- [Scribe](https://summon-claude.github.io/summon-claude/guide/scribe/index.md) — the background monitoring agent
- [GitHub Integration](https://summon-claude.github.io/summon-claude/guide/github-integration/index.md) — GitHub tools for all sessions
- [Configuration](https://summon-claude.github.io/summon-claude/guide/configuration/index.md) — full configuration reference
