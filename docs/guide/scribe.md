# Scribe Agent

??? info "Prerequisites"
    This guide assumes you've completed the [Quick Start](../getting-started/quickstart.md) and have a working `summon config check`.

The scribe is a background monitoring agent that keeps an eye on your inboxes so you don't have to. It periodically checks Gmail, Google Calendar, Google Drive, and optionally external Slack channels, then posts alerts, daily summaries, and important signals to its persistent `#0-summon-scribe` channel.

---

## What the scribe does

The scribe runs as a persistent Claude session that wakes up on a configurable interval (default: every 5 minutes), scans connected data sources, and posts notable items to Slack. It triages items by importance on a 1--5 scale, respects quiet hours, tracks notes and action items, and produces daily summary reports.

The scribe is not interactive in the same way as a regular session — it is meant to run unattended in the background and surface information proactively.

Key behaviors:

- **Alert triage** — each item is scored 1--5 and formatted by importance level (see [Alert formatting](#alert-formatting) below)
- **Quiet hours** — only critical (level 5) alerts are posted during the configured quiet window
- **Note-taking** — messages posted to the scribe channel are tracked as notes or action items
- **Daily summaries** — generated automatically when activity is quiet, when quiet hours begin, or on request
- **State checkpoints** — the scribe posts periodic checkpoints to its channel so it can resume after a restart without re-alerting

---

## Setup

### Step 1: Enable the scribe

```bash
summon config set SUMMON_SCRIBE_ENABLED true
```

### Step 2: Enable data sources

The scribe has two data collectors, each with its own enable flag. Enable at least one.

#### Google Workspace

```bash
summon config set SUMMON_SCRIBE_GOOGLE_ENABLED true
```

Then authenticate with Google:

```bash
summon config google-auth
```

This opens a browser for OAuth consent. Grant access to the Google services you want the scribe to monitor. Once complete, credentials are stored in summon's config directory.

To verify authentication status:

```bash
summon config google-status
```

#### External Slack monitoring

See the [Slack browser monitoring](#slack-browser-monitoring) section below for full setup instructions.

### Step 3: Start the scribe

The scribe auto-spawns when you run:

```bash
summon project up
```

It creates (or reuses) a persistent private channel called `#0-summon-scribe`. No manual start or `/summon CODE` authentication is needed — the scribe inherits the authenticated user from `project up`.

If the scribe was previously suspended by `project down`, `project up` resumes it with transcript continuity.

---

## Configuration

All scribe configuration uses `SUMMON_SCRIBE_*` environment variables. These can be set in the summon config file or as shell environment variables.

### Core settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMON_SCRIBE_ENABLED` | `false` | Enable the scribe agent |
| `SUMMON_SCRIBE_MODEL` | (inherits `SUMMON_DEFAULT_MODEL`) | Model to use for the scribe session |
| `SUMMON_SCRIBE_SCAN_INTERVAL_MINUTES` | `5` | How often the scribe polls for new data |
| `SUMMON_SCRIBE_CWD` | `<data-dir>/scribe` | Working directory for the scribe session |

### Filtering and quiet hours

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMON_SCRIBE_IMPORTANCE_KEYWORDS` | (unset) | Comma-separated keywords that elevate item importance. Items containing these words are always flagged as importance level 4+. |
| `SUMMON_SCRIBE_QUIET_HOURS` | (unset) | Quiet hours in `HH:MM-HH:MM` format (e.g., `22:00-08:00`). Only level-5 (urgent) items are posted during this window. |

**Example with keyword filtering and quiet hours:**

```bash
summon config set SUMMON_SCRIBE_IMPORTANCE_KEYWORDS urgent,outage,deploy,PagerDuty
summon config set SUMMON_SCRIBE_QUIET_HOURS 23:00-07:00
```

### Google Workspace

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMON_SCRIBE_GOOGLE_ENABLED` | `false` | Enable the Google Workspace data collector |
| `SUMMON_SCRIBE_GOOGLE_SERVICES` | `gmail,calendar,drive` | Comma-separated list of Google services to monitor |

The default services are `gmail`, `calendar`, `drive`. The full set of supported services is: `gmail`, `calendar`, `drive`, `docs`, `sheets`, `chat`, `forms`, `slides`, `tasks`, `contacts`, `search`, `appscript`.

```bash
# Monitor only Gmail and Calendar, not Drive
summon config set SUMMON_SCRIBE_GOOGLE_SERVICES gmail,calendar
```

!!! note "Requires workspace-mcp"
    The Google collector requires the `google` extra: `pip install summon-claude[google]`. Google OAuth credentials must also be configured via `summon config google-auth`.

### Slack channel monitoring

The scribe can monitor an external Slack workspace using browser-based WebSocket interception. This is separate from the native Slack bot integration used for session interaction — it watches a different workspace (e.g., your company's Slack) via a real browser session.

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMON_SCRIBE_SLACK_ENABLED` | `false` | Enable Slack channel monitoring |
| `SUMMON_SCRIBE_SLACK_BROWSER` | `chrome` | Browser to use: `chrome`, `chromium`, `firefox`, or `webkit` |
| `SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS` | (unset) | Comma-separated channel IDs to monitor |

DMs and @mentions are always captured regardless of `SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS`. The channel list controls which channels have *all* messages monitored.

**Example:**

```bash
summon config set SUMMON_SCRIBE_SLACK_ENABLED true
summon config set SUMMON_SCRIBE_SLACK_BROWSER chrome
summon config set SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS C01ABC123,C02DEF456
```

---

## Slack browser monitoring

The scribe's Slack data collector uses Playwright to authenticate with an external Slack workspace, then intercepts WebSocket frames to capture messages in real time. This section covers the setup commands.

!!! warning "Browser-based monitoring"
    Slack channel monitoring uses Playwright to capture WebSocket frames from your Slack workspace. This requires the `slack-browser` extra (`pip install summon-claude[slack-browser]`) and a Chromium-based browser installed on the host.

### Authenticate with a Slack workspace

```bash
summon config slack-auth myteam
```

This opens a visible browser window at your Slack workspace. Log in normally — the browser closes automatically after detecting your session. Auth state (cookies and localStorage) is saved to summon's data directory.

The `WORKSPACE` argument accepts:

- A workspace name: `myteam` (becomes `https://myteam.slack.com`)
- An enterprise name: `acme.enterprise` (becomes `https://acme.enterprise.slack.com`)
- A full URL: `https://myteam.slack.com`

After login, the command prompts you to select which channels to monitor using an interactive picker.

!!! tip "Enterprise Grid workspaces"
    Enterprise Grid workspaces serve a workspace picker at their enterprise URL. The scribe handles this automatically by extracting team IDs from the saved browser state and navigating directly to `app.slack.com/client/{TEAM_ID}`.

### Select monitored channels

To change which channels are monitored without re-authenticating:

```bash
summon config slack-channels
```

This uses the cached channel list from the last authentication. To refresh the channel list from Slack:

```bash
summon config slack-channels --refresh
```

### Check auth status

```bash
summon config slack-status
```

Shows the configured workspace URL, user ID, auth state age, and monitored channels.

### Remove auth state

```bash
summon config slack-remove
```

Removes saved browser auth state and workspace config. This cannot be undone.

### How it works

The browser user must be a member of any channel being monitored — the WebSocket only delivers messages for channels the authenticated user belongs to.

The primary auth cookie (`d`) has a roughly 1-year TTL, so re-authentication is rarely needed. The `x` cookie (CSRF) is not required.

---

## Alert formatting

The scribe triages each item on a 1--5 importance scale and formats alerts accordingly:

| Level | Label | Format | Notification |
|-------|-------|--------|--------------|
| 5 | Urgent | `:rotating_light:` **URGENT** with detail block | @mentions the user |
| 4 | Important | `:warning:` **Source**: summary with detail block | No @mention |
| 3 | Normal | Source: summary (one line) | None |
| 1--2 | Low/Noise | Batched into a single "_Low priority (N items)_" line | None |

Items matching configured importance keywords are always elevated to level 4+.

During quiet hours, only level-5 items are posted.

---

## Daily summaries

The scribe produces daily summary reports covering all monitored sources. A summary includes:

- **Email** — count received, important items highlighted
- **Calendar** — events, notable meetings or changes
- **Drive** — documents modified or shared
- **Slack** — message counts, DMs, mentions, key conversations
- **Notes & Action Items** — user-posted notes tracked during the day
- **Agent Work** — summary of what project sessions accomplished (read from the Global PM channel)
- **Alerts** — total items flagged as important

Summaries are generated when:

- Activity has been quiet for 3+ consecutive scans
- The user explicitly asks for a summary
- Quiet hours begin (if configured)

---

## Prompt injection defense

The scribe processes content from external sources (emails, Slack messages, calendar events, documents) that may contain text designed to manipulate the agent. The scribe's system prompt includes explicit defenses against prompt injection attacks — it treats all external content as untrusted data, never as instructions. If a suspected injection attempt is detected, the scribe posts a warning to its channel rather than acting on the content.

---

## Scribe canvas

The scribe's Slack channel has a canvas with a summary layout:

- **Recent Signals** — items surfaced in the last scan
- **Active Items** — ongoing calendar events or long-running threads
- **Suppressed** — items seen but filtered below the importance threshold

The canvas is updated after each scan cycle. See [Canvas Integration](canvas.md) for how the canvas sync works.

---

## Full configuration example

```bash
# ~/.config/summon/config.env (or environment variables)

# Enable scribe
SUMMON_SCRIBE_ENABLED=true

# Use a lighter model to reduce cost
SUMMON_SCRIBE_MODEL=claude-haiku-4-5-20251001

# Scan every 10 minutes
SUMMON_SCRIBE_SCAN_INTERVAL_MINUTES=10

# Elevate items with these keywords regardless of importance scoring
SUMMON_SCRIBE_IMPORTANCE_KEYWORDS=urgent,sev1,sev2,outage,on-call

# Don't post non-critical items overnight
SUMMON_SCRIBE_QUIET_HOURS=22:00-08:00

# Google Workspace collector
SUMMON_SCRIBE_GOOGLE_ENABLED=true
SUMMON_SCRIBE_GOOGLE_SERVICES=gmail,calendar

# External Slack collector
SUMMON_SCRIBE_SLACK_ENABLED=true
SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS=C01ABC123,C02DEF456
```

---

## See also

- [Projects](projects.md) — the project system the scribe runs within
- [Configuration](configuration.md) — full configuration reference
