# Troubleshooting & FAQ

This page covers common problems and their solutions. Issues are grouped by category.

---

## Installation

???+ tip "Claude CLI not found"
    **Symptom:** `summon start` fails with "claude: command not found" or similar error.

    **Cause:** The Claude Code CLI is not installed or not on your `PATH`.

    **Fix:** Install the Claude Code CLI globally:
    ```bash
    npm install -g @anthropic-ai/claude-code
    ```
    Then verify:
    ```bash
    claude --version
    ```

???+ tip "Python version mismatch"
    **Symptom:** Installation fails with "requires Python >=3.12" or similar.

    **Cause:** summon-claude requires Python 3.12 or later.

    **Fix:** Check your Python version and upgrade if needed:
    ```bash
    python3 --version
    ```
    Install Python 3.12+ via your package manager or from [python.org](https://python.org). If using `uv`, it manages Python versions for you:
    ```bash
    uv python install 3.12
    ```

???+ tip "Should I use uv or pip?"
    **Use `uv`.** summon-claude is tested and distributed with `uv`. The recommended install is:
    ```bash
    uv tool install summon-claude
    ```
    If you install with pip and encounter import or dependency issues, try switching to `uv tool install`.

    To upgrade:
    ```bash
    uv tool upgrade summon-claude
    ```

???+ tip "google or slack-browser extras not found"
    **Symptom:** `ImportError` for `workspace_mcp` or `playwright`.

    **Cause:** Optional extras were not installed.

    **Fix:** Install with the appropriate extra:
    ```bash
    uv tool install "summon-claude[google]"        # Google Workspace integration
    uv tool install "summon-claude[slack-browser]" # Slack browser-based auth
    uv tool install "summon-claude[all]"           # All extras
    ```

---

## Slack Setup

???+ tip "Wrong Slack scopes — bot can't post or read messages"
    **Symptom:** Slack returns `missing_scope` errors in logs, or summon cannot post to channels.

    **Cause:** The Slack app is missing required OAuth scopes.

    **Fix:** Go to **api.slack.com/apps → Your App → OAuth & Permissions → Scopes** and add the required bot token scopes. After adding scopes, reinstall the app to your workspace. See [Slack Setup](getting-started/slack-setup.md) for the full scope list.

???+ tip "Messages sent but Claude never responds"
    **Symptom:** You can authenticate with `/summon`, the session channel is created, but messages you type in the channel get no response from Claude. `summon session info` shows `Turns: 0`.

    **Cause:** Event Subscriptions are disabled in the Slack app settings. Without events enabled, Slack delivers slash commands (so `/summon` works) but does NOT deliver `message.channels` events, so the daemon never sees your messages.

    **Fix:**

    1. Go to **api.slack.com/apps → Your App → Event Subscriptions**
    2. Toggle **Enable Events** to **On** (Socket Mode means no Request URL is needed)
    3. Expand **Subscribe to bot events** and verify these events are listed: `message.channels`, `message.groups`, `reaction_added`, `app_home_opened`, `file_shared`
    4. Click **Save Changes**
    5. If prompted, **reinstall the app** to the workspace

    !!! note "The manifest should set this automatically"
        If you created the app from `slack-app-manifest.yaml`, events should be pre-configured. If the toggle is off despite using the manifest, you may need to reinstall the app or re-apply the manifest.

    **How to verify:** Run `summon config check` — if it reports "Slack API reachable" but sessions show 0 turns, event subscriptions are the likely cause.

???+ tip "Socket Mode not enabled"
    **Symptom:** The daemon starts but does not receive Slack events. No messages appear in session channels.

    **Cause:** Socket Mode is not enabled in the Slack app settings.

    **Fix:** Go to **api.slack.com/apps → Your App → Socket Mode** and toggle it on. You also need an app-level token (starts with `xapp-`) — generate one under **Basic Information → App-Level Tokens** with the `connections:write` scope.

???+ tip "Missing app-level token or connections:write scope"
    **Symptom:** Daemon fails to start with an authentication or connection error related to the app-level token.

    **Cause:** The `SUMMON_SLACK_APP_TOKEN` is missing, or the token lacks the `connections:write` scope.

    **Fix:**
    1. In your Slack app settings, go to **Basic Information → App-Level Tokens**.
    2. Create or select a token — it must have the `connections:write` scope.
    3. Set it in your config:
    ```bash
    summon config set slack_app_token xapp-...
    ```

???+ tip "Bot not added to channel"
    **Symptom:** summon starts a session but posts nothing to the expected channel, or returns a `not_in_channel` error.

    **Cause:** The Slack bot user has not been invited to the channel.

    **Fix:** In Slack, open the channel and type `/invite @your-bot-name`. The bot must be a member of every channel it uses.

---

## Authentication

???+ tip "Auth code expired"
    **Symptom:** Pasting the auth code into Slack shows "code expired" or the session never activates.

    **Cause:** Auth codes expire after 5 minutes by default.

    **Fix:** Run `summon start` again to get a fresh code. Codes are single-use and time-limited.

???+ tip "Auth code locked after failed attempts"
    **Symptom:** The session shows "code locked" and won't accept new attempts.

    **Cause:** 5 consecutive failed verification attempts lock the code as a security measure.

    **Fix:** The locked code cannot be unlocked. Run `summon start` again to generate a new session with a fresh code.

???+ tip "/summon not recognized in Slack"
    **Symptom:** Typing `/summon` in Slack shows "unknown command" or nothing happens.

    **Cause:** The `/summon` slash command is not configured in the Slack app, or the app has not been reinstalled after adding it.

    **Fix:** Go to **api.slack.com/apps → Your App → Slash Commands** and add the `/summon` command. Then reinstall the app to the workspace. The request URL should point to your summon daemon's HTTP endpoint (if using HTTP mode) or is not needed for Socket Mode.

---

## Sessions

???+ tip "Session won't start"
    **Symptom:** `summon start` hangs, exits with an error, or the session never appears in `summon session list`.

    **Cause:** Common causes include: daemon not running, Claude CLI not found, bad config, or a port/socket conflict.

    **Fix:**
    1. Check the daemon is running: `summon daemon status`
    2. If not running, start it: `summon daemon start`
    3. Check logs for errors: `summon daemon logs` or view `~/.summon/sessions/` directly
    4. Verify Claude CLI is available: `claude --version`
    5. Validate config: `summon config check`

???+ tip "Daemon already running / can't start daemon"
    **Symptom:** `summon daemon start` says the daemon is already running, but sessions aren't working.

    **Cause:** A stale PID file or socket from a previous daemon crash.

    **Fix:**
    ```bash
    summon daemon stop
    summon daemon start
    ```
    If `daemon stop` fails, find and kill the process manually:
    ```bash
    # Check if daemon process is actually running
    summon daemon status
    ```
    If the status shows no live process, delete the stale lock file and restart.

???+ tip "Stale sessions in session list"
    **Symptom:** `summon session list` shows sessions that are no longer running (status stuck at "active").

    **Cause:** Sessions from a previous daemon instance were not cleaned up when the daemon stopped or crashed.

    **Fix:** Run the cleanup command:
    ```bash
    summon session cleanup
    ```
    This marks orphaned sessions (present in the database but not tracked by the current daemon) as errored.

???+ tip "Session list shows wrong status"
    **Symptom:** A session shows "active" but the Claude process is not responding.

    **Cause:** The Claude subprocess may have crashed without the daemon detecting it.

    **Fix:**
    ```bash
    summon session cleanup   # Mark orphaned sessions
    summon session list      # Verify status updated
    ```
    If the session persists, stop it explicitly:
    ```bash
    summon stop <session-name>
    ```

---

## Permissions

???+ tip "Approval buttons not appearing in Slack"
    **Symptom:** Claude requests a tool use that should require approval, but no Approve/Deny buttons appear in Slack.

    **Cause:** The Slack app is missing the `chat:write` scope, interactivity is not enabled, or the bot is not in the channel.

    **Fix:**
    1. Verify the bot has `chat:write` scope.
    2. Enable interactivity: **api.slack.com/apps → Your App → Interactivity & Shortcuts → On**.
    3. Ensure the bot is in the channel (`/invite @your-bot-name`).

???+ tip "Permission request times out"
    **Symptom:** A pending permission request disappears after a while without being acted on, and Claude proceeds or aborts.

    **Cause:** Permission requests have a configurable timeout. After the timeout, summon defaults to denying the request (fail-safe).

    **Fix:** Respond to permission requests promptly. To adjust the timeout, check your configuration:
    ```bash
    summon config show
    ```
    Look for `permission_timeout_seconds` and adjust as needed.

???+ tip "Ephemeral permission messages visible to wrong people"
    **Symptom:** Permission request messages are visible only to you, not to other team members who should see them.

    **Cause:** Ephemeral messages in Slack are only visible to the user who triggered them. This is a Slack platform limitation.

    **Behavior:** Permission requests are posted as regular (visible) messages so the whole channel can see and respond to them. If you are seeing ephemeral-only messages, this is a configuration issue.

    **Fix:** Check that `permission_visibility` is not set to `ephemeral` in your config.

---

## Canvas

???+ tip "Canvas not created on free Slack plan"
    **Symptom:** Canvas creation fails with an error like `free_team_canvas_tab_already_exists` or `free_teams_cannot_create_non_tabbed_canvases`.

    **Cause:** Slack's free plan allows only one canvas per channel, and standalone (non-channel) canvases are not allowed.

    **Fix:** summon automatically uses the existing channel canvas if one already exists. If creation still fails:
    1. Check that the channel doesn't already have a canvas associated with it.
    2. If a canvas exists, summon will sync to it automatically once discovered.

    Note: On the free plan, you cannot have more than one canvas per channel. Plan your channel usage accordingly.

???+ tip "Canvas not syncing / content outdated"
    **Symptom:** The Slack canvas for a session shows stale content and isn't updating.

    **Cause:** Canvas syncs are debounced (2-second dirty delay, 60-second background interval) to avoid hitting Slack API rate limits.

    **Fix:**
    - Wait up to 60 seconds for the next sync cycle.
    - If it has been longer than a few minutes, check for errors in the session logs:
      ```bash
      summon session logs <session-name>
      ```
    - After 3 consecutive sync failures, the sync interval increases to 5 minutes. Check for Slack API errors in the logs.

???+ tip "Canvas edits trigger unwanted Slack channel notifications"
    **Symptom:** The channel receives update messages each time the canvas is edited.

    **Cause:** Slack sends a channel notification when a canvas is edited, with some consolidation within a 4-hour window.

    **Fix:** This is Slack platform behavior and cannot be fully suppressed from the client side. Workspace admins can disable canvas edit notifications in workspace settings.

---

## Daemon

???+ tip "Checking daemon status and health"
    Use the built-in status command:
    ```bash
    summon daemon status
    ```
    This shows whether the daemon is running, its PID, and basic health info.

???+ tip "Finding daemon logs"
    Session logs are written to `~/.summon/sessions/`. Each session has its own log file named by session ID.

    To view logs for a specific session:
    ```bash
    summon session logs <session-name>
    ```

    For daemon-level logs, start the daemon with verbose logging:
    ```bash
    summon daemon start -v
    ```
    Or check the daemon log file directly in `~/.summon/`.

???+ tip "Enabling verbose logging for debugging"
    Pass `-v` (or `-vv` for more detail) to the daemon or session commands:
    ```bash
    summon daemon start -v
    summon start -v my-session
    ```
    Verbose logs include SDK events, Slack API calls, and permission flow details.

???+ tip "Daemon won't stop cleanly"
    **Symptom:** `summon daemon stop` hangs or the daemon process remains after stopping.

    **Cause:** Active sessions may be taking time to shut down gracefully, or the daemon is waiting for in-flight Slack API calls.

    **Fix:** Wait a few seconds — the daemon performs a graceful shutdown that stops all active sessions first. If it hangs for more than 30 seconds, you can force-kill it:
    ```bash
    summon daemon stop --force
    ```

---

## Google Workspace

???+ tip "Google OAuth flow fails or never completes"
    **Symptom:** `summon config google-auth` hangs, fails with an auth error, or the browser window doesn't open.

    **Cause:** Missing or invalid `client_secret.json`, or the OAuth redirect URI is not configured.

    **Fix:**
    1. Download `client_secret.json` from the Google Cloud Console for your OAuth app.
    2. Place it in your summon data directory (check `summon config path` for the location).
    3. Run the auth flow:
    ```bash
    summon config google-auth
    ```
    4. Complete the browser-based consent flow.

???+ tip "Google scope validation fails"
    **Symptom:** summon reports that required Google scopes are missing even after authorizing.

    **Cause:** The OAuth consent was granted with insufficient scopes, or the stored credentials don't include all required scopes.

    **Fix:** Re-run the auth flow — it will request all required scopes:
    ```bash
    summon config google-auth
    ```
    If scope issues persist, revoke the app's access in your Google account settings and re-authorize.

???+ tip "Google credentials not found"
    **Symptom:** Google Workspace tools fail with a credentials or authentication error after setup appeared to succeed.

    **Cause:** Credentials are stored in `~/.summon/google-credentials/` (or the XDG data directory equivalent). If this path differs from what workspace-mcp expects, credentials won't be found.

    **Fix:** Check where summon stores credentials:
    ```bash
    summon config show | grep data_dir
    ```
    Ensure the `WORKSPACE_MCP_CREDENTIALS_DIR` environment variable (set automatically by summon) points to the correct path. If credentials are in a different location, re-run `summon config google-auth`.

---

## Getting More Help

If your issue isn't covered here:

1. Check the session logs: `summon session logs <session-name>`
2. Enable verbose daemon logging: `summon daemon start -v`
3. Run config validation: `summon config check`
4. Open an issue at [github.com/summon-claude/summon-claude/issues](https://github.com/summon-claude/summon-claude/issues)
