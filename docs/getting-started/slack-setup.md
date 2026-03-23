# Slack Setup

Before starting your first session, you need to create a Slack app and configure summon-claude with its credentials.

## Prerequisites

- Slack workspace where you have **admin access** (or can request admin approval)
- The summon-claude app manifest from the repository

---

## Step 1: Create the Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**

    ![Create New App dialog](../assets/screenshots/slack-setup-create-app.png)

2. Choose **From a manifest**

3. Select the workspace where you want to install summon-claude

    ![Pick a workspace](../assets/screenshots/slack-setup-app-workspace.png)

4. Paste the contents of [`slack-app-manifest.yaml`](https://github.com/summon-claude/summon-claude/blob/main/slack-app-manifest.yaml) from the repository

    ![Paste manifest YAML](../assets/screenshots/slack-setup-manifest.png)

5. Click **Next**, review the summary, then click **Create**

!!! tip "Using the manifest"
    The manifest pre-configures all required scopes, event subscriptions, and Socket Mode settings. Do not create the app manually — the manifest ensures nothing is missed.

---

## Step 2: Install to your workspace

After creating the app, install it to your workspace:

1. Go to **OAuth & Permissions** and click **Install to Workspace**

    ![OAuth install page](../assets/screenshots/slack-setup-oauth-install.png)

2. Review the permissions and click **Allow**

    ![Permission consent dialog](../assets/screenshots/slack-setup-workspace-allow.png)

---

## Step 3: Enable Socket Mode

In your app settings, go to **Settings > Socket Mode** and toggle **Enable Socket Mode** on.

![Socket Mode toggle](../assets/screenshots/slack-setup-socket-mode.png)

!!! warning "Socket Mode is required"
    summon-claude uses Socket Mode (WebSocket) for real-time event delivery. Without it, the app will not receive messages from Slack.

---

## Step 4: Generate an App-Level Token

1. Go to **Settings > Basic Information > App-Level Tokens**

    ![App-Level Tokens section](../assets/screenshots/slack-setup-app-token.png)

2. Click **Generate Token and Scopes**, name it `summon-claude`, and add the `connections:write` scope

    ![Generate token dialog](../assets/screenshots/slack-setup-app-token-generate.png)

3. Click **Generate** and copy the token (starts with `xapp-`)

    ![Generated token properties](../assets/screenshots/slack-setup-app-token-properties.png)

---

## Step 5: Collect your credentials

You need three values from the Slack app settings:

| Credential | Where to find it | Format |
|------------|-----------------|--------|
| Bot Token | **OAuth & Permissions > Bot User OAuth Token** | `xoxb-...` |
| App Token | **Settings > Basic Information > App-Level Tokens** | `xapp-...` |
| Signing Secret | **Settings > Basic Information > App Credentials** | 32-character hex string |

![Bot token location on OAuth page](../assets/screenshots/slack-setup-tokens.png)

---

## Step 6: Run the setup wizard

summon-claude includes an interactive setup wizard:

```bash
summon init
```

The wizard prompts for your Bot Token, App Token, and Signing Secret, then writes them to the config file.

---

## Step 7: Validate the configuration

```bash
summon config check
```

This verifies that all credentials are present, checks token format, tests database writability, and validates Slack API connectivity.

---

## Common setup errors

**Wrong scopes**
: If you created the app manually instead of from the manifest, required scopes may be missing. Check **OAuth & Permissions > Bot Token Scopes** and compare against the manifest.

**Missing App-Level Token**
: The App Token (`xapp-`) is separate from the Bot Token (`xoxb-`). If you skipped Socket Mode setup or the App-Level Token generation, it will not exist.

**Socket Mode not enabled**
: `summon config check` will report a connection failure if Socket Mode is off. Toggle it on at **Settings > Socket Mode**.

**`connections:write` scope missing**
: The App-Level Token must have the `connections:write` scope. If you generated a token without this scope, delete it and generate a new one.

**Not installed to workspace**
: After creating the app from the manifest, you must click **Install to Workspace** to generate the Bot Token. Without installation, no token exists.

---

## Next steps

With Slack configured, you're ready to start your first session:

[Quick Start](quickstart.md){ .md-button .md-button--primary }
