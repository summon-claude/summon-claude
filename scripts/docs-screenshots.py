"""Generate documentation screenshots using Playwright + Slack API.

The session-ux section is fully self-contained: it creates a temporary Slack
channel, posts messages that simulate a real summon session (turn threads,
emoji lifecycle, permission buttons), screenshots them via Playwright, then
cleans up the channel.

Usage:
    uv run python scripts/docs-screenshots.py [OPTIONS]

Environment variables:
    SUMMON_TEST_SLACK_BOT_TOKEN      Bot token for creating fixture channels/messages
    SUMMON_TEST_SLACK_WORKSPACE_URL  Allowlisted Slack workspace URL (browser capture)
    SUMMON_TEST_SLACK_COOKIE         Slack browser session cookie for Playwright auth
"""

from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path

import click

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = Path("docs/assets/screenshots")
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800

MANUAL_SCREENSHOTS = [
    {"name": "slack-setup-create-app.png", "description": "Create New App dialog at api.slack.com"},
    {"name": "slack-setup-app-workspace.png", "description": "Pick a workspace dialog"},
    {"name": "slack-setup-manifest.png", "description": "Paste manifest YAML screen"},
    {"name": "slack-setup-oauth-install.png", "description": "OAuth & Permissions install page"},
    {"name": "slack-setup-workspace-allow.png", "description": "Workspace permission consent"},
    {"name": "slack-setup-tokens.png", "description": "Bot User OAuth Token location"},
    {"name": "slack-setup-app-token.png", "description": "App-Level Tokens section"},
    {"name": "slack-setup-app-token-generate.png", "description": "Generate app-level token"},
    {"name": "slack-setup-app-token-properties.png", "description": "Generated token properties"},
    {"name": "slack-setup-socket-mode.png", "description": "Socket Mode toggle enabled"},
]

SESSION_UX_SCREENSHOTS = [
    # Quickstart flow
    {"name": "quickstart-slack-auth.png", "description": "Slash command auth response"},
    {"name": "quickstart-first-message.png", "description": "First message exchange"},
    {"name": "quickstart-permission-request.png", "description": "Permission request buttons"},
    {"name": "quickstart-help.png", "description": "!help command output"},
    # Guide pages
    {"name": "session-ux-channel-overview.png", "description": "Session channel overview"},
    {"name": "session-ux-turn-thread.png", "description": "Turn thread with tool activity"},
    {"name": "permissions-approval.png", "description": "Permission approval buttons"},
    {"name": "threading-turn-thread.png", "description": "Thread model illustration"},
]


# ---------------------------------------------------------------------------
# Slack fixture: create realistic session content via API
# ---------------------------------------------------------------------------


def create_session_fixture(bot_token: str) -> dict:
    """Create a temporary Slack channel with simulated summon session content.

    Returns dict with channel_id, team_id, and message timestamps for navigation.
    """
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    client = WebClient(token=bot_token)

    # Resolve bot identity and team
    auth = client.auth_test()
    team_id = auth["team_id"]
    bot_user_id = auth["user_id"]

    # Create test channel
    suffix = secrets.token_hex(3)
    channel_name = f"docs-screenshots-{int(time.time())}-{suffix}"[:80]
    resp = client.conversations_create(name=channel_name, is_private=False)
    channel_id = resp["channel"]["id"]
    click.echo(f"  Created fixture channel: #{channel_name} ({channel_id})")

    # Invite non-bot users so the browser cookie user can see the channel
    try:
        members = client.users_list(limit=50)
        for member in members.get("members", []):
            uid = member.get("id", "")
            if (
                not member.get("is_bot")
                and not member.get("deleted")
                and uid not in {"USLACKBOT", bot_user_id}
            ):
                try:
                    client.conversations_invite(channel=channel_id, users=uid)
                except SlackApiError:
                    pass  # already in channel or can't be invited
    except SlackApiError:
        pass  # best-effort

    # --- Auth response (simulates /summon command result) ---
    client.chat_postMessage(
        channel=channel_id,
        text=(
            ":white_check_mark: *Authenticated!* Session `myproject-a1b2c3` is now active.\n"
            "This channel is your workspace — talk to Claude here."
        ),
    )

    # --- Session header ---
    client.chat_postMessage(
        channel=channel_id,
        text=(
            ":large_green_circle: *Session started* — `myproject-a1b2c3`\n"
            "Model: `claude-opus-4-6` | Effort: `high` | CWD: `/home/user/myproject`"
        ),
    )

    # --- User message with emoji lifecycle (completed state) ---
    user_msg = client.chat_postMessage(
        channel=channel_id,
        text="Fix the authentication bug in the login handler",
    )
    user_ts = user_msg["ts"]
    # Add final-state emoji (white_check_mark = completed turn)
    client.reactions_add(channel=channel_id, name="white_check_mark", timestamp=user_ts)

    # --- Turn thread starter ---
    turn_starter = client.chat_postMessage(
        channel=channel_id,
        text=(
            ":hammer_and_wrench: *Turn 1:* re: _Fix the authentication bug_... "
            "| 4 tool calls \u00b7 login.py, auth.py \u00b7 18k/200k (9%)"
        ),
    )
    turn_ts = turn_starter["ts"]

    # Tool calls in the turn thread
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=turn_ts,
        text=":hammer_and_wrench: `Read` \u2014 `src/auth/login.py`",
    )
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=turn_ts,
        text=":hammer_and_wrench: `Grep` \u2014 `validate_token` in `src/auth/`",
    )
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=turn_ts,
        text=":hammer_and_wrench: `Edit` \u2014 `src/auth/login.py`",
    )

    # Diff snippet in thread
    diff_content = (
        "--- a/src/auth/login.py\n"
        "+++ b/src/auth/login.py\n"
        "@@ -42,7 +42,7 @@\n"
        " def validate_token(token: str) -> bool:\n"
        "-    if token.expired:\n"
        "+    if token.expired or not token.is_valid:\n"
        '         raise AuthError("Token expired")\n'
        "     return True"
    )
    try:
        client.files_upload_v2(
            channel=channel_id,
            thread_ts=turn_ts,
            content=diff_content,
            filename="login.py.diff",
            title="Edit: src/auth/login.py",
            snippet_type="diff",
        )
    except SlackApiError:
        # files_upload_v2 can fail on some workspace tiers; post as text fallback
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=turn_ts,
            text=f"```diff\n{diff_content}\n```",
        )

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=turn_ts,
        text=":hammer_and_wrench: `Bash` \u2014 `uv run pytest tests/test_auth.py -v`",
    )

    # --- Claude's response in main channel ---
    client.chat_postMessage(
        channel=channel_id,
        text=(
            f"<@{bot_user_id}> Fixed the authentication bug. The issue was that "
            "`validate_token()` only checked for expiry but not validity. Added "
            "the `is_valid` check and all 12 auth tests pass."
        ),
    )

    # --- Turn footer ---
    client.chat_postMessage(
        channel=channel_id,
        text=":checkered_flag: $0.0342 \u00b7 9% context",
        blocks=[
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": ":checkered_flag: $0.0342 \u00b7 9% context"},
                ],
            }
        ],
    )

    # --- Second user message with permission request ---
    user_msg2 = client.chat_postMessage(
        channel=channel_id,
        text="Now deploy it to staging",
    )
    user_ts2 = user_msg2["ts"]
    client.reactions_add(channel=channel_id, name="gear", timestamp=user_ts2)

    # Turn 2 thread
    turn2 = client.chat_postMessage(
        channel=channel_id,
        text=":hammer_and_wrench: *Turn 2:* re: _Now deploy it to staging_...",
    )
    turn2_ts = turn2["ts"]

    # Permission request with buttons
    permission_msg = client.chat_postMessage(
        channel=channel_id,
        thread_ts=turn2_ts,
        text="<!channel> Permission requested",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        ":lock: *Permission requested* <!channel>\n\n"
                        "`Bash` \u2014 `./deploy.sh --env staging`"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "docs_screenshot_approve",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Deny"},
                        "style": "danger",
                        "action_id": "docs_screenshot_deny",
                    },
                ],
            },
        ],
    )

    # --- !help command response ---
    help_msg = client.chat_postMessage(
        channel=channel_id,
        text="!help",
    )
    help_ts = help_msg["ts"]
    client.reactions_add(channel=channel_id, name="white_check_mark", timestamp=help_ts)

    client.chat_postMessage(
        channel=channel_id,
        text=(
            "*Available commands:*\n\n"
            "| Command | Description |\n"
            "|---------|-------------|\n"
            "| `!help` | Show this help message |\n"
            "| `!status` | Show session status |\n"
            "| `!end` | End the current session |\n"
            "| `!stop` | Cancel the current turn |\n"
            "| `!clear` | Clear conversation history |\n"
            "| `!model [name]` | Show or switch model |\n"
            "| `!effort [level]` | Show or switch effort |\n"
            "| `!compact` | Compact conversation context |\n\n"
            "_Aliases:_ `!quit`/`!exit`/`!logout` \u2192 `!end` \u00b7 "
            "`!new`/`!reset` \u2192 `!clear`"
        ),
    )

    # --- Canvas (if possible) ---
    canvas_id = None
    try:
        canvas_resp = client.api_call(
            "canvases.create",
            json={
                "title": "myproject-a1b2c3",
                "channel_id": channel_id,
                "document_content": {
                    "type": "markdown",
                    "markdown": (
                        "# myproject-a1b2c3\n\n"
                        "**Model:** claude-opus-4-6 | **Effort:** high\n\n"
                        "## Active Work\n\n"
                        "| Task | Status | Priority |\n"
                        "|------|--------|----------|\n"
                        "| Fix auth bug | Completed | High |\n"
                        "| Deploy to staging | In Progress | Medium |\n\n"
                        "## Scheduled Jobs\n\n"
                        "No active cron jobs.\n"
                    ),
                },
            },
        )
        canvas_id = canvas_resp.get("canvas_id")
        if canvas_id:
            click.echo(f"  Created canvas: {canvas_id}")
        else:
            click.echo(f"  Canvas creation failed: {canvas_resp.get('error')}", err=True)
    except Exception as exc:
        click.echo(f"  Canvas creation skipped: {exc}", err=True)

    return {
        "channel_id": channel_id,
        "channel_name": channel_name,
        "team_id": team_id,
        "turn_ts": turn_ts,
        "turn2_ts": turn2_ts,
        "permission_ts": permission_msg["ts"],
        "canvas_id": canvas_id,
    }


def cleanup_fixture(bot_token: str, channel_id: str) -> None:
    """Archive the fixture channel (best-effort)."""
    from slack_sdk import WebClient

    try:
        client = WebClient(token=bot_token)
        client.conversations_archive(channel=channel_id)
        click.echo(f"  Archived fixture channel: {channel_id}")
    except Exception as exc:
        click.echo(f"  WARNING: cleanup failed: {exc}", err=True)


# ---------------------------------------------------------------------------
# Playwright capture
# ---------------------------------------------------------------------------


def capture_session_ux(
    output_dir: Path,
    workspace_url: str,
    cookie_value: str,
    fixture: dict,
) -> list[str]:
    """Navigate to the fixture channel in Playwright and capture screenshots.

    Returns list of captured screenshot filenames.
    """
    from playwright.sync_api import sync_playwright

    captured = []
    channel_id = fixture["channel_id"]
    team_id = fixture["team_id"]
    turn_ts = fixture["turn_ts"]

    # Slack web client URL format
    channel_url = f"https://app.slack.com/client/{team_id}/{channel_id}"
    thread_url = f"{channel_url}/thread/{channel_id}-{turn_ts}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        )
        context.add_cookies(
            [
                {
                    "name": "d",
                    "value": cookie_value,
                    "domain": ".slack.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                },
            ]
        )
        page = context.new_page()

        def snap(name: str) -> None:
            dest = output_dir / name
            page.screenshot(path=str(dest), full_page=False)
            click.echo(f"  captured: {dest}")
            captured.append(dest.name)

        def nav(url: str, wait_ms: int = 8_000) -> None:
            click.echo(f"  Navigating: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(wait_ms)

        # 1. Channel overview — shows auth, header, first exchange, turn summary
        nav(channel_url)
        snap("quickstart-slack-auth.png")  # Auth response visible at top
        snap("quickstart-first-message.png")  # First message exchange visible
        snap("session-ux-channel-overview.png")  # Full channel view

        # 2. Turn 1 thread — tool calls, diffs, results
        nav(thread_url, wait_ms=5_000)
        snap("session-ux-turn-thread.png")
        snap("threading-turn-thread.png")  # Same content, referenced by threading.md

        # 3. Turn 2 thread — permission buttons
        turn2_ts = fixture["turn2_ts"]
        turn2_thread = f"{channel_url}/thread/{channel_id}-{turn2_ts}"
        nav(turn2_thread, wait_ms=5_000)
        snap("quickstart-permission-request.png")
        snap("permissions-approval.png")  # Same content, referenced by permissions.md

        # 4. Back to channel — scroll to !help output at bottom
        nav(channel_url, wait_ms=5_000)
        # Scroll to bottom to see !help
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2_000)
        snap("quickstart-help.png")

        context.close()
        browser.close()

    return captured


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--output",
    "output_dir",
    default=str(DEFAULT_OUTPUT_DIR),
    show_default=True,
    help="Output directory for screenshots.",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "--section",
    default=None,
    type=click.Choice(["slack-setup", "session-ux"]),
    help="Capture only a specific section.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List planned screenshots without capturing.",
)
@click.option(
    "--keep-channel",
    is_flag=True,
    default=False,
    help="Do not archive the fixture channel after capture (for debugging).",
)
def main(output_dir: Path, section: str | None, dry_run: bool, keep_channel: bool) -> None:
    """Generate documentation screenshots using Playwright + Slack API.

    Session-ux screenshots are fully automated: the script creates a temporary
    Slack channel, posts simulated session content (turn threads, emoji, permission
    buttons, canvas), screenshots via Playwright, then archives the channel.

    Requires: SUMMON_TEST_SLACK_BOT_TOKEN, SUMMON_TEST_SLACK_WORKSPACE_URL,
    SUMMON_TEST_SLACK_COOKIE.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    sections = [section] if section else ["slack-setup", "session-ux"]

    # --- Dry run ---
    if dry_run:
        for sec in sections:
            items = MANUAL_SCREENSHOTS if sec == "slack-setup" else SESSION_UX_SCREENSHOTS
            tag = "manual-only" if sec == "slack-setup" else "automated"
            click.echo(f"\n[{sec}]")
            for shot in items:
                click.echo(f"  ({tag}) {output_dir / shot['name']}")
                click.echo(f"         {shot['description']}")
        return

    # --- Slack-setup: validate manual screenshots ---
    if "slack-setup" in sections:
        click.echo("\n[slack-setup] Validating manual screenshots...")
        missing = [s["name"] for s in MANUAL_SCREENSHOTS if not (output_dir / s["name"]).exists()]
        if missing:
            click.echo(f"  WARNING: {len(missing)} manual screenshots missing:", err=True)
            for name in missing:
                click.echo(f"    {name}", err=True)
        else:
            click.echo(f"  All {len(MANUAL_SCREENSHOTS)} manual screenshots present.")

    # --- Session-ux: automated capture ---
    if "session-ux" not in sections:
        return

    click.echo("\n[session-ux] Automated screenshot capture...")

    # Check prerequisites
    bot_token = os.environ.get("SUMMON_TEST_SLACK_BOT_TOKEN")
    workspace_url = os.environ.get("SUMMON_TEST_SLACK_WORKSPACE_URL", "")
    cookie_value = os.environ.get("SUMMON_TEST_SLACK_COOKIE")

    if not workspace_url.startswith("http"):
        workspace_url = f"https://{workspace_url}" if workspace_url else ""

    missing_vars = []
    if not bot_token:
        missing_vars.append("SUMMON_TEST_SLACK_BOT_TOKEN")
    if not workspace_url:
        missing_vars.append("SUMMON_TEST_SLACK_WORKSPACE_URL")
    if not cookie_value:
        missing_vars.append("SUMMON_TEST_SLACK_COOKIE")

    if missing_vars:
        click.echo(
            f"  Skipping: missing env vars: {', '.join(missing_vars)}",
            err=True,
        )
        return

    try:
        import playwright
    except ImportError:
        click.echo("  Skipping: playwright not installed.", err=True)
        return

    # Create fixture
    click.echo("  Setting up Slack fixture...")
    fixture = create_session_fixture(bot_token)
    channel_id = fixture["channel_id"]

    try:
        # Capture screenshots
        click.echo("  Capturing screenshots via Playwright...")
        captured = capture_session_ux(output_dir, workspace_url, cookie_value, fixture)
        click.echo(f"\n  Done: {len(captured)} screenshots captured.")
    finally:
        if not keep_channel:
            cleanup_fixture(bot_token, channel_id)
        else:
            click.echo(f"  Keeping fixture channel: {channel_id} (--keep-channel)")


if __name__ == "__main__":
    main()
