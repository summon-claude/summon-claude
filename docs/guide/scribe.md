# Scribe Agent

The scribe is a background monitoring agent that keeps an eye on your inboxes so you don't have to. It periodically checks Gmail, Google Calendar, Google Drive, and optionally Slack channels, then posts summaries and important signals to its Slack channel.

!!! note "Preview feature"
    The scribe agent system is a preview feature. Configuration uses `SUMMON_SCRIBE_*` environment variables and the behavior may change in future releases.

---

## What the scribe does

The scribe runs as a persistent Claude session that wakes up on a configurable interval (default: every 5 minutes), scans connected data sources, and posts notable items to Slack. It filters by importance, respects quiet hours, and maintains a canvas with a running summary.

The scribe is not interactive in the same way as a regular session — it is meant to run unattended in the background and surface information proactively.

---

## Setup

### Step 1: Authenticate with Google Workspace

```bash
summon config google-auth
```

This opens a browser for OAuth consent. Grant access to the Google services you want the scribe to monitor. Once complete, credentials are stored in summon's data directory.

To verify authentication status:

```bash
summon config google-status
```

This shows which Google services are authenticated and whether tokens are still valid.

### Step 2: Enable the scribe

Set the following in your config or environment:

```bash
# In ~/.config/summon/config.env
SUMMON_SCRIBE_ENABLED=true
```

### Step 3: Start the scribe

The scribe starts automatically when you run:

```bash
summon project up
```

Or start it manually alongside a project:

```bash
summon start --name scribe-main
```

Authenticate it in Slack with `/summon CODE`, and it begins monitoring immediately.

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
| `SUMMON_SCRIBE_IMPORTANCE_KEYWORDS` | (unset) | Comma-separated keywords that elevate item importance. Items containing these words are always surfaced. |
| `SUMMON_SCRIBE_QUIET_HOURS` | (unset) | Quiet hours in `HH:MM-HH:MM` format (e.g., `22:00-08:00`). Only critical items are posted during this window. |

**Example with keyword filtering and quiet hours:**

```bash
SUMMON_SCRIBE_IMPORTANCE_KEYWORDS=urgent,outage,deploy,PagerDuty
SUMMON_SCRIBE_QUIET_HOURS=23:00-07:00
```

### Google Workspace services

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMON_SCRIBE_GOOGLE_SERVICES` | `gmail,calendar,drive` | Comma-separated list of Google services to monitor |

Supported services: `gmail`, `calendar`, `drive`

```bash
# Monitor only Gmail and Calendar, not Drive
SUMMON_SCRIBE_GOOGLE_SERVICES=gmail,calendar
```

### Slack channel monitoring

The scribe can also monitor Slack channels using a browser-based scraping approach. This is separate from the native Slack bot integration used for session interaction.

!!! warning "Browser-based monitoring"
    Slack channel monitoring uses Playwright to scrape your Slack workspace in a browser. This requires Playwright to be installed and a browser to be available. It also requires you to be logged in to Slack in that browser profile.

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMMON_SCRIBE_SLACK_ENABLED` | `false` | Enable Slack channel monitoring |
| `SUMMON_SCRIBE_SLACK_BROWSER` | `chrome` | Browser to use: `chrome`, `firefox`, or `webkit` |
| `SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS` | (unset) | Comma-separated channel names to monitor (without `#`) |

**Example:**

```bash
SUMMON_SCRIBE_SLACK_ENABLED=true
SUMMON_SCRIBE_SLACK_BROWSER=chrome
SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS=engineering,on-call,deploys
```

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

# Monitor Gmail and Calendar only
SUMMON_SCRIBE_GOOGLE_SERVICES=gmail,calendar

# Also watch key Slack channels
SUMMON_SCRIBE_SLACK_ENABLED=true
SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS=engineering,incidents
```

---

## What's next

- [Projects](projects.md) — the project system the scribe runs within
- [Canvas](canvas.md) — how the scribe canvas is structured and synced
- [Configuration](configuration.md) — full configuration reference
