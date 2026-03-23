"""Generate documentation screenshots using a real summon session + Playwright.

This script is a LOCAL developer tool — it cannot run in CI because it requires
a running Claude CLI, authenticated Anthropic account, and real Slack workspace.

The flow:
  1. Starts a real `summon start` session
  2. Authenticates via `/summon CODE` in the Slack web UI (Playwright)
  3. Sends a real message to Claude
  4. Waits for Claude to respond
  5. Screenshots the channel, thread, and permission UI
  6. Stops the session and archives the channel

Environment variables:
  SUMMON_TEST_SLACK_WORKSPACE_URL  Slack workspace URL (e.g. gtest.enterprise.slack.com)
  SUMMON_TEST_SLACK_COOKIE         Browser session cookie (`d` cookie, `xoxd-` prefix)
  SUMMON_TEST_SLACK_BOT_TOKEN      Bot token for channel discovery + cleanup

Usage:
  uv run python scripts/docs-screenshots.py [OPTIONS]
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import click

DEFAULT_OUTPUT_DIR = Path("docs/assets/screenshots")
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800
SESSION_NAME = "docs-screenshots"

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


# ---------------------------------------------------------------------------
# summon session lifecycle
# ---------------------------------------------------------------------------


def start_summon_session() -> tuple[subprocess.Popen, str]:
    """Start `summon start` and extract the auth code from stdout.

    Returns (process, short_code).
    """
    click.echo("  Starting summon session...")
    proc = subprocess.Popen(
        ["summon", "start", "--name", SESSION_NAME],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Read stdout lines until we find the auth code
    code_pattern = re.compile(r"SUMMON CODE:\s*(\w+)")
    short_code = None
    deadline = time.time() + 30

    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
            continue
        click.echo(f"    summon: {line.rstrip()}")
        m = code_pattern.search(line)
        if m:
            short_code = m.group(1)
            break

    if not short_code:
        proc.terminate()
        raise RuntimeError("Failed to extract auth code from summon start")

    click.echo(f"  Auth code: {short_code}")
    return proc, short_code


def stop_summon_session(proc: subprocess.Popen) -> None:
    """Stop the session and terminate the subprocess."""
    click.echo("  Stopping summon session...")
    try:
        subprocess.run(
            ["summon", "stop", SESSION_NAME],
            capture_output=True,
            timeout=15,
        )
    except Exception as exc:
        click.echo(f"  WARNING: summon stop failed: {exc}", err=True)
    proc.terminate()
    proc.wait(timeout=10)


def find_session_channel(bot_token: str) -> str | None:
    """Find the session channel by looking for recent channels matching the session name."""
    from slack_sdk import WebClient

    client = WebClient(token=bot_token)
    # List recent conversations created by the bot
    resp = client.conversations_list(types="public_channel,private_channel", limit=50)
    for ch in resp.get("channels", []):
        if SESSION_NAME in ch.get("name", ""):
            return ch["id"]
    return None


def get_team_id(bot_token: str) -> str:
    from slack_sdk import WebClient

    return WebClient(token=bot_token).auth_test()["team_id"]


def archive_channel(bot_token: str, channel_id: str) -> None:
    from slack_sdk import WebClient

    try:
        WebClient(token=bot_token).conversations_archive(channel=channel_id)
        click.echo(f"  Archived channel: {channel_id}")
    except Exception as exc:
        click.echo(f"  WARNING: archive failed: {exc}", err=True)


# ---------------------------------------------------------------------------
# Playwright capture
# ---------------------------------------------------------------------------


def create_browser_context(pw, cookie_value: str):
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
    return browser, context


def authenticate_via_slack(page, workspace_url: str, short_code: str) -> None:
    """Type `/summon CODE` in the Slack web UI to authenticate."""
    click.echo(f"  Authenticating in Slack: /summon {short_code}")
    page.goto(workspace_url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(8_000)

    # Find the message input and type the slash command
    composer = page.locator('[data-qa="message_input"] [contenteditable="true"]')
    composer.click()
    page.wait_for_timeout(500)
    composer.fill(f"/summon {short_code}")
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    click.echo("  Sent /summon command, waiting for auth...")
    page.wait_for_timeout(5_000)


def wait_for_session_channel(bot_token: str, timeout: int = 60) -> str:
    """Poll for the session channel to be created by the daemon."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        channel_id = find_session_channel(bot_token)
        if channel_id:
            click.echo(f"  Session channel found: {channel_id}")
            return channel_id
        time.sleep(2)
    raise RuntimeError(f"Session channel not found within {timeout}s")


def send_message_via_slack(page, message: str) -> None:
    """Type a message in the Slack message composer and send it."""
    click.echo(f"  Sending message: {message[:50]}...")
    composer = page.locator('[data-qa="message_input"] [contenteditable="true"]')
    composer.click()
    page.wait_for_timeout(500)
    composer.fill(message)
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")


def wait_for_claude_response(bot_token: str, channel_id: str, timeout: int = 120) -> str | None:
    """Poll for Claude's response (a message from the bot after the user's message)."""
    from slack_sdk import WebClient

    client = WebClient(token=bot_token)
    deadline = time.time() + timeout
    baseline_count = 0

    # Get current message count
    resp = client.conversations_history(channel=channel_id, limit=50)
    baseline_count = len(resp.get("messages", []))
    click.echo(f"  Waiting for Claude response (baseline: {baseline_count} messages)...")

    while time.time() < deadline:
        time.sleep(5)
        resp = client.conversations_history(channel=channel_id, limit=50)
        messages = resp.get("messages", [])
        if len(messages) > baseline_count + 1:
            # Look for a message that looks like a turn completion (has the checkered_flag footer)
            for msg in messages:
                if ":checkered_flag:" in msg.get("text", ""):
                    click.echo("  Claude response detected (turn footer found)")
                    return msg.get("ts")
        elapsed = int(time.time() - (deadline - timeout))
        if elapsed % 15 == 0 and elapsed > 0:
            click.echo(f"  Still waiting... ({elapsed}s)")

    click.echo("  WARNING: Timed out waiting for Claude response", err=True)
    return None


def capture_screenshots(
    page,
    output_dir: Path,
    team_id: str,
    channel_id: str,
) -> list[str]:
    """Navigate to the session channel and capture all screenshots."""
    captured = []
    channel_url = f"https://app.slack.com/client/{team_id}/{channel_id}"

    def snap(name: str) -> None:
        dest = output_dir / name
        page.screenshot(path=str(dest), full_page=False)
        click.echo(f"  captured: {dest}")
        captured.append(name)

    def nav(url: str, wait_ms: int = 8_000) -> None:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(wait_ms)

    # Channel overview (shows auth, header, messages, emoji lifecycle)
    click.echo("  Capturing channel overview...")
    nav(channel_url)
    snap("quickstart-slack-auth.png")
    snap("quickstart-first-message.png")
    snap("session-ux-channel-overview.png")

    # Find threads by looking for turn starters in the channel
    from slack_sdk import WebClient

    bot_token = os.environ["SUMMON_TEST_SLACK_BOT_TOKEN"]
    client = WebClient(token=bot_token)
    resp = client.conversations_history(channel=channel_id, limit=50)
    messages = resp.get("messages", [])

    # Find turn thread starters (contain "Turn" and tool-related emoji)
    turn_threads = [
        m["ts"] for m in messages if "Turn" in m.get("text", "") and m.get("reply_count", 0) > 0
    ]

    if turn_threads:
        # Navigate to the first turn thread
        thread_ts = turn_threads[-1]  # Oldest thread (last in reverse-chrono list)
        thread_url = f"{channel_url}/thread/{channel_id}-{thread_ts}"
        click.echo(f"  Capturing turn thread: {thread_url}")
        nav(thread_url, wait_ms=5_000)
        snap("session-ux-turn-thread.png")
        snap("threading-turn-thread.png")

    # Find permission thread (contains "Permission" or approval buttons)
    permission_threads = [
        m["ts"]
        for m in messages
        if "permission" in m.get("text", "").lower() or "Permission" in m.get("text", "")
    ]
    if permission_threads:
        perm_ts = permission_threads[-1]
        perm_url = f"{channel_url}/thread/{channel_id}-{perm_ts}"
        click.echo(f"  Capturing permission thread: {perm_url}")
        nav(perm_url, wait_ms=5_000)
        snap("quickstart-permission-request.png")
        snap("permissions-approval.png")

    # Help output — scroll to bottom of channel
    click.echo("  Capturing help output...")
    nav(channel_url, wait_ms=5_000)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(2_000)
    snap("quickstart-help.png")

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
    help="Do not archive the session channel after capture.",
)
@click.option(
    "--message",
    default="Read the README.md and give me a one-paragraph summary.",
    help="Message to send to Claude for generating screenshot content.",
)
def main(
    output_dir: Path,
    section: str | None,
    dry_run: bool,
    keep_channel: bool,
    message: str,
) -> None:
    """Generate documentation screenshots using a real summon session.

    Starts a real summon session, authenticates via the Slack web UI,
    sends a message to Claude, waits for the response, then captures
    screenshots of the channel, turn threads, and permission UI.

    This is a LOCAL developer tool — requires Claude CLI, summon config,
    and Slack browser credentials. Cannot run in CI.

    Requires: SUMMON_TEST_SLACK_BOT_TOKEN, SUMMON_TEST_SLACK_WORKSPACE_URL,
    SUMMON_TEST_SLACK_COOKIE.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    sections = [section] if section else ["slack-setup", "session-ux"]

    if dry_run:
        for sec in sections:
            items = (
                MANUAL_SCREENSHOTS
                if sec == "slack-setup"
                else [
                    {"name": "quickstart-slack-auth.png", "description": "Auth response"},
                    {"name": "quickstart-first-message.png", "description": "First exchange"},
                    {
                        "name": "quickstart-permission-request.png",
                        "description": "Permission buttons",
                    },
                    {"name": "quickstart-help.png", "description": "!help output"},
                    {"name": "session-ux-channel-overview.png", "description": "Channel overview"},
                    {"name": "session-ux-turn-thread.png", "description": "Turn thread"},
                    {"name": "permissions-approval.png", "description": "Permission approval"},
                    {"name": "threading-turn-thread.png", "description": "Thread model"},
                ]
            )
            tag = "manual" if sec == "slack-setup" else "e2e (real session)"
            click.echo(f"\n[{sec}]")
            for shot in items:
                click.echo(f"  ({tag}) {output_dir / shot['name']}")
                click.echo(f"         {shot['description']}")
        return

    # Validate manual screenshots
    if "slack-setup" in sections:
        click.echo("\n[slack-setup] Validating manual screenshots...")
        missing = [s["name"] for s in MANUAL_SCREENSHOTS if not (output_dir / s["name"]).exists()]
        if missing:
            click.echo(f"  WARNING: {len(missing)} manual screenshots missing:", err=True)
            for name in missing:
                click.echo(f"    {name}", err=True)
        else:
            click.echo(f"  All {len(MANUAL_SCREENSHOTS)} manual screenshots present.")

    if "session-ux" not in sections:
        return

    # Check prerequisites
    click.echo("\n[session-ux] End-to-end screenshot capture (real summon session)...")
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
        click.echo(f"  Skipping: missing env vars: {', '.join(missing_vars)}", err=True)
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        click.echo("  Skipping: playwright not installed.", err=True)
        return

    # Verify summon is installed
    try:
        subprocess.run(["summon", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        click.echo("  Skipping: `summon` CLI not found on PATH.", err=True)
        return

    team_id = get_team_id(bot_token)
    proc = None
    channel_id = None

    try:
        # 1. Start summon session
        proc, short_code = start_summon_session()

        # 2. Authenticate via Playwright
        with sync_playwright() as pw:
            browser, context = create_browser_context(pw, cookie_value)
            page = context.new_page()

            authenticate_via_slack(page, workspace_url, short_code)

            # 3. Wait for session channel
            channel_id = wait_for_session_channel(bot_token, timeout=30)

            # 4. Navigate to session channel and send message
            channel_url = f"https://app.slack.com/client/{team_id}/{channel_id}"
            page.goto(channel_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5_000)

            send_message_via_slack(page, message)

            # 5. Wait for Claude to respond
            wait_for_claude_response(bot_token, channel_id, timeout=120)

            # 6. Send !help for the help screenshot
            page.wait_for_timeout(3_000)
            send_message_via_slack(page, "!help")
            page.wait_for_timeout(5_000)

            # 7. Capture all screenshots
            captured = capture_screenshots(page, output_dir, team_id, channel_id)
            click.echo(f"\n  Done: {len(captured)} screenshots captured.")

            context.close()
            browser.close()

    finally:
        if proc:
            stop_summon_session(proc)
        if channel_id and not keep_channel:
            archive_channel(bot_token, channel_id)
        elif channel_id:
            click.echo(f"  Keeping channel: {channel_id} (--keep-channel)")


if __name__ == "__main__":
    main()
