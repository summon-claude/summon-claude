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

Sections:
  slack-setup   — validates manually-captured Slack setup screenshots
  session-ux    — end-to-end Playwright screenshots of a real session
  terminal      — captures real CLI terminal output and injects into docs markdown

Environment variables:
  SUMMON_TEST_SLACK_BOT_TOKEN      Bot token for channel discovery, cleanup, and team ID
  SUMMON_TEST_SLACK_COOKIE         Browser session cookie (`d` cookie, `xoxd-` prefix)

Usage:
  uv run python scripts/docs-screenshots.py [OPTIONS]
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
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
    """Find the session channel by looking for channels matching the session name.

    Paginates through all channels since the bot may be in many channels.
    """
    from slack_sdk import WebClient

    client = WebClient(token=bot_token)
    cursor = None
    while True:
        kwargs = {"types": "public_channel,private_channel", "limit": 200, "exclude_archived": True}
        if cursor:
            kwargs["cursor"] = cursor
        resp = client.conversations_list(**kwargs)
        for ch in resp.get("channels", []):
            if SESSION_NAME in ch.get("name", ""):
                return ch["id"]
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
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


def create_browser_context(pw, cookie_value: str, *, headless: bool = True):
    browser = pw.chromium.launch(headless=headless)
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


def authenticate_via_slack(page, team_id: str, short_code: str, output_dir: Path) -> None:
    """Type `/summon CODE` in the Slack web UI to authenticate."""
    slack_url = f"https://app.slack.com/client/{team_id}"
    click.echo(f"  Authenticating in Slack: /summon {short_code}")
    click.echo(f"  Navigating to: {slack_url}")
    page.goto(slack_url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(12_000)

    # Debug screenshot to see page state
    debug_path = output_dir / "_debug_auth_page.png"
    page.screenshot(path=str(debug_path), full_page=False)
    click.echo(f"  Debug screenshot saved: {debug_path}")

    # Dismiss any "Explore AI" or promo overlays
    try:
        selectors = '[data-qa="explore_ai_dismiss"], button:has-text("Close"), [aria-label="Close"]'
        close_btn = page.locator(selectors)
        if close_btn.count() > 0:
            close_btn.first.click(timeout=3_000)
            click.echo("  Dismissed overlay")
            page.wait_for_timeout(1_000)
    except Exception:  # noqa: S110
        pass

    # Find the message input and type the slash command
    # Use press_sequentially (not fill) so Slack's JS recognizes the / prefix as a slash command
    composer = page.locator('[data-qa="texty_input"]')
    composer.click(timeout=15_000)
    page.wait_for_timeout(500)
    composer.press_sequentially(f"/summon {short_code}", delay=50)
    page.wait_for_timeout(1_000)
    page.keyboard.press("Enter")
    click.echo("  Sent /summon command, waiting for auth...")
    page.wait_for_timeout(8_000)


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
    composer = page.locator('[data-qa="texty_input"]')
    composer.click()
    page.wait_for_timeout(500)
    # Use fill for regular messages (not slash commands)
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


def wait_for_help_response(bot_token: str, channel_id: str, timeout: int = 30) -> str | None:
    """Poll for the !help thread reply using conversations_replies.

    The !help response is posted as a thread reply to the user's !help message,
    NOT as a top-level channel message. So conversations_history won't see the
    response — we must use conversations_replies.

    Returns the !help message ts if a reply was detected, None on timeout.
    """
    from slack_sdk import WebClient

    client = WebClient(token=bot_token)
    deadline = time.time() + timeout

    # Find the !help message in conversations_history (it IS a top-level message)
    help_ts = None
    while time.time() < deadline:
        resp = client.conversations_history(channel=channel_id, limit=10)
        for msg in resp.get("messages", []):
            if msg.get("text", "").strip() == "!help":
                help_ts = msg["ts"]
                break
        if help_ts:
            break
        time.sleep(2)

    if not help_ts:
        click.echo("  WARNING: Could not find !help message in channel", err=True)
        return None

    click.echo(f"  Found !help message: ts={help_ts}")

    # Poll conversations_replies for the daemon's thread reply
    while time.time() < deadline:
        resp = client.conversations_replies(channel=channel_id, ts=help_ts)
        messages = resp.get("messages", [])
        # First message is the parent (!help itself), replies follow
        if len(messages) > 1:
            click.echo("  !help response detected in thread")
            return help_ts
        time.sleep(2)

    click.echo("  WARNING: Timed out waiting for !help thread reply", err=True)
    return help_ts  # Return ts anyway so we can still try to screenshot


def capture_screenshots(
    page,
    output_dir: Path,
    team_id: str,
    channel_id: str,
    *,
    help_ts: str | None = None,
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

    # Navigate to channel
    click.echo("  Capturing channel screenshots...")
    nav(channel_url)

    # Scroll to top for auth/welcome message
    click.echo("  Scrolling to top for auth screenshot...")
    page.evaluate("document.querySelector('[data-qa=\"slack_kit_list\"]')?.scrollTo(0, 0)")
    page.wait_for_timeout(2_000)
    snap("quickstart-slack-auth.png")

    # Navigate to !help thread for help output screenshot
    if help_ts:
        help_thread_url = f"{channel_url}/thread/{channel_id}-{help_ts}"
        click.echo(f"  Capturing !help thread: {help_thread_url}")
        nav(help_thread_url, wait_ms=5_000)
    else:
        # Fallback: scroll to bottom of channel (won't show help response)
        click.echo("  No !help thread ts — falling back to channel bottom")
        page.evaluate("document.querySelector('[data-qa=\"slack_kit_list\"]')?.scrollTo(0, 999999)")
        page.wait_for_timeout(2_000)
    snap("quickstart-help.png")

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
        # Navigate to the first turn thread (oldest = last in reverse-chrono list)
        thread_ts = turn_threads[-1]
        thread_url = f"{channel_url}/thread/{channel_id}-{thread_ts}"
        click.echo(f"  Capturing turn thread: {thread_url}")
        nav(thread_url, wait_ms=5_000)
        # This shows Claude's response with tool calls — used for first-message & threading docs
        snap("quickstart-first-message.png")
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

    return captured


# ---------------------------------------------------------------------------
# Terminal output capture — registry-based CLI output capture system
# ---------------------------------------------------------------------------

TERMINAL_SESSION_NAME = "docs-terminal"


@dataclass
class CaptureSpec:
    """Specification for capturing terminal output from a CLI command.

    Each spec maps a CLI command to a marker in a markdown file.  The runner
    executes the command, optionally post-processes the output, and injects
    the result between ``<!-- terminal:MARKER -->`` / ``<!-- /terminal:MARKER -->``
    comment pairs in the target file.
    """

    marker: str  # marker name in <!-- terminal:MARKER -->
    md_file: str  # relative path from repo root
    command: list[str]  # CLI command args (prefixed with "uv run" automatically)
    fence: str = "text"  # code fence language / attributes
    timeout: int = 15  # capture timeout in seconds
    capture_fn: Callable[[], str] | None = None  # custom capture (overrides command)
    post_process: Callable[[str], str] | None = None  # transform captured output
    extra_md: str = ""  # markdown appended after code fence, before closing marker
    show_command: bool = False  # prepend "$ command" line to output


# -- Post-processors -------------------------------------------------------


def _sanitize_paths(text: str) -> str:
    """Replace the user's home directory with ``~`` for portability."""
    return text.replace(str(Path.home()), "~")


def _add_start_annotations(banner: str) -> str:
    """Add Material for MkDocs annotations to the ``summon start`` banner."""
    out = []
    for line in banner.split("\n"):
        if "SUMMON CODE:" in line:
            out.append(f"{line}  # (1)")
        elif "Expires in" in line:
            out.append(f"{line}  # (2)")
        else:
            out.append(line)
    return "\n".join(out)


# -- Custom capture functions -----------------------------------------------


def _capture_summon_start_banner() -> str:
    """Run ``summon start`` and capture just the auth banner.

    Starts a real session, reads stdout until the closing ``====`` border,
    then terminates and cleans up.
    """
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    click.echo("    Starting summon session for banner capture...")
    proc = subprocess.Popen(
        ["uv", "run", "summon", "start", "--name", TERMINAL_SESSION_NAME],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    lines: list[str] = []
    border_re = re.compile(r"^={10,}$")
    in_banner = False
    deadline = time.time() + 30

    try:
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
                continue

            stripped = line.rstrip()
            if not stripped:
                if in_banner:
                    lines.append(stripped)
                continue

            if border_re.match(stripped):
                lines.append(stripped)
                if in_banner:
                    break  # Closing border — done
                in_banner = True
            elif in_banner:
                lines.append(stripped)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            subprocess.run(
                ["uv", "run", "summon", "stop", TERMINAL_SESSION_NAME],
                capture_output=True,
                timeout=15,
                env=env,
            )
        except Exception:  # noqa: S110
            pass

    if len(lines) < 3:
        raise RuntimeError(f"Failed to capture auth banner (got {len(lines)} lines): {lines}")

    click.echo(f"    Captured {len(lines)} lines of banner output")
    return "\n".join(lines)


# -- Capture registry -------------------------------------------------------
#
# Add new entries here to auto-capture more CLI commands.  The runner iterates
# this list and skips any captures whose commands fail (missing config, etc.).

_START_EXTRA_MD = (
    "\n"
    "1. This is a one-time code. Type it exactly as shown in any Slack channel.\n"
    "2. Codes expire after 5 minutes. Run `summon start` again if it expires."
)

CAPTURES: list[CaptureSpec] = [
    # -- Getting started ----------------------------------------------------
    CaptureSpec(
        marker="summon-version-short",
        md_file="docs/getting-started/installation.md",
        command=["summon", "--version"],
    ),
    CaptureSpec(
        marker="summon-start",
        md_file="docs/getting-started/quickstart.md",
        command=[],
        fence="{ .text .annotate }",
        timeout=30,
        capture_fn=_capture_summon_start_banner,
        post_process=_add_start_annotations,
        extra_md=_START_EXTRA_MD,
    ),
    # -- Guide: sessions ----------------------------------------------------
    CaptureSpec(
        marker="summon-version",
        md_file="docs/guide/sessions.md",
        command=["summon", "version"],
        post_process=_sanitize_paths,
    ),
    CaptureSpec(
        marker="summon-start",
        md_file="docs/guide/sessions.md",
        command=[],
        fence="{ .text .annotate }",
        timeout=30,
        capture_fn=_capture_summon_start_banner,
        post_process=_add_start_annotations,
        extra_md=_START_EXTRA_MD,
    ),
    # -- Guide: configuration -----------------------------------------------
    CaptureSpec(
        marker="config-show",
        md_file="docs/guide/configuration.md",
        command=["summon", "config", "show"],
    ),
    CaptureSpec(
        marker="config-check",
        md_file="docs/guide/configuration.md",
        command=["summon", "config", "check"],
        timeout=30,
        post_process=_sanitize_paths,
    ),
]


# -- Runner -----------------------------------------------------------------


def _make_env() -> dict[str, str]:
    """Build a subprocess environment with CLAUDECODE unset."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


# Cache for custom capture functions — avoids running expensive captures
# (like summon start) multiple times when the same capture_fn is shared
# across registry entries.
_capture_cache: dict[Callable[[], str], str] = {}


def _run_capture(spec: CaptureSpec) -> str | None:
    """Execute a single capture spec and return its output, or None on failure."""
    if spec.capture_fn:
        if spec.capture_fn in _capture_cache:
            click.echo("    (cached)")
            return _capture_cache[spec.capture_fn]
        try:
            result = spec.capture_fn()
            _capture_cache[spec.capture_fn] = result
            return result
        except Exception as exc:
            click.echo(f"    WARNING: {spec.marker} custom capture failed: {exc}", err=True)
            return None

    try:
        result = subprocess.run(
            ["uv", "run", *spec.command],
            capture_output=True,
            text=True,
            timeout=spec.timeout,
            env=_make_env(),
        )
    except subprocess.TimeoutExpired:
        click.echo(f"    WARNING: {spec.marker} timed out after {spec.timeout}s", err=True)
        return None

    if result.returncode != 0:
        stderr_preview = result.stderr.strip()[:200]
        click.echo(
            f"    WARNING: {' '.join(spec.command)} exited {result.returncode}: {stderr_preview}",
            err=True,
        )
        return None

    return result.stdout.strip()


def _validate_content(content: str, marker: str) -> str | None:
    """Check captured content for patterns that would corrupt the markdown.

    Returns an error message if the content is unsafe, or None if OK.
    """
    if f"<!-- /terminal:{marker} -->" in content:
        return "content contains the closing marker comment"
    if "```" in content:
        return "content contains triple backticks (would break fences)"
    return None


def _inject_terminal_block(
    md_path: Path,
    marker: str,
    content: str,
    fence: str = "text",
    extra_md: str = "",
) -> bool:
    """Replace content between ``<!-- terminal:MARKER -->`` markers."""
    md_text = md_path.read_text()
    pattern = re.compile(
        rf"(<!-- terminal:{re.escape(marker)} -->)\n.*?\n(<!-- /terminal:{re.escape(marker)} -->)",
        re.DOTALL,
    )

    block = f"```{fence}\n{content}\n```"
    if extra_md:
        block += extra_md

    # Use a function replacement to avoid backreference interpretation in content
    def _replacer(m: re.Match[str]) -> str:
        return f"{m.group(1)}\n{block}\n{m.group(2)}"

    new_text, count = pattern.subn(_replacer, md_text)
    if count == 0:
        return False

    md_path.write_text(new_text)
    return True


def run_terminal_section(dry_run: bool = False) -> bool:
    """Run all registered captures and inject results into docs.

    Returns True if at least one capture succeeded, False if all failed.
    """
    click.echo("\n[terminal] Capturing CLI terminal output...")

    if dry_run:
        for spec in CAPTURES:
            cmd_str = " ".join(spec.command) if spec.command else "(custom)"
            click.echo(f"  (capture) {cmd_str} → {spec.md_file}#{spec.marker}")
        return True

    succeeded = 0
    failed = 0

    for spec in CAPTURES:
        cmd_str = " ".join(spec.command) if spec.command else "(custom)"
        click.echo(f"  Capturing: {cmd_str} → {spec.marker}...")

        output = _run_capture(spec)
        if output is None:
            failed += 1
            continue

        if spec.post_process:
            output = spec.post_process(output)
        if spec.show_command and spec.command:
            output = f"$ {' '.join(spec.command)}\n{output}"

        # Validate content won't corrupt the markdown
        error = _validate_content(output, spec.marker)
        if error:
            click.echo(f"    WARNING: skipping {spec.marker}: {error}", err=True)
            failed += 1
            continue

        md_path = Path(spec.md_file)
        if _inject_terminal_block(md_path, spec.marker, output, spec.fence, spec.extra_md):
            click.echo(f"    → injected into {spec.md_file}")
            succeeded += 1
        else:
            click.echo(
                f"    WARNING: no <!-- terminal:{spec.marker} --> marker in {spec.md_file}",
                err=True,
            )
            failed += 1

    click.echo(f"\n  Done: {succeeded} captured, {failed} skipped/failed.")
    return succeeded > 0


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
    type=click.Choice(["slack-setup", "session-ux", "terminal"]),
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

    Requires: SUMMON_TEST_SLACK_BOT_TOKEN, SUMMON_TEST_SLACK_COOKIE.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    sections = [section] if section else ["slack-setup", "session-ux", "terminal"]

    if dry_run:
        for sec in sections:
            if sec == "terminal":
                run_terminal_section(dry_run=True)
                continue
            items = (
                MANUAL_SCREENSHOTS
                if sec == "slack-setup"
                else [
                    {"name": "quickstart-slack-auth.png", "description": "Auth/welcome message"},
                    {
                        "name": "quickstart-first-message.png",
                        "description": "First exchange (turn thread)",
                    },
                    {"name": "quickstart-help.png", "description": "!help output"},
                    {
                        "name": "quickstart-permission-request.png",
                        "description": "Permission buttons",
                    },
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

    # Terminal capture (no Slack/Playwright prereqs needed)
    if "terminal" in sections and not run_terminal_section() and sections == ["terminal"]:
        raise SystemExit(1)

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
    cookie_value = os.environ.get("SUMMON_TEST_SLACK_COOKIE")

    missing_vars = []
    if not bot_token:
        missing_vars.append("SUMMON_TEST_SLACK_BOT_TOKEN")
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

            authenticate_via_slack(page, team_id, short_code, output_dir)

            # 3. Wait for session channel
            channel_id = wait_for_session_channel(bot_token, timeout=60)

            # 4. Navigate to session channel and send message
            channel_url = f"https://app.slack.com/client/{team_id}/{channel_id}"
            page.goto(channel_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(8_000)

            # Dismiss any overlays that may block the composer
            try:
                selectors = (
                    '[data-qa="explore_ai_dismiss"], button:has-text("Close"), [aria-label="Close"]'
                )
                close_btn = page.locator(selectors)
                if close_btn.count() > 0:
                    close_btn.first.click(timeout=3_000)
                    click.echo("  Dismissed overlay")
                    page.wait_for_timeout(1_000)
            except Exception:  # noqa: S110
                pass

            # Debug screenshot to verify channel loaded
            debug_path = output_dir / "_debug_channel_page.png"
            page.screenshot(path=str(debug_path), full_page=False)
            click.echo(f"  Debug screenshot saved: {debug_path}")

            send_message_via_slack(page, message)

            # 5. Wait for Claude to respond
            wait_for_claude_response(bot_token, channel_id, timeout=120)

            # 6. Send !help and wait for thread reply
            page.wait_for_timeout(3_000)
            send_message_via_slack(page, "!help")
            help_ts = wait_for_help_response(bot_token, channel_id, timeout=30)

            # 7. Capture all screenshots
            captured = capture_screenshots(page, output_dir, team_id, channel_id, help_ts=help_ts)
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
