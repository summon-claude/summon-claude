"""Generate documentation screenshots using Playwright.

Usage:
    uv run python scripts/docs-screenshots.py [OPTIONS]

Options:
    --output DIR       Override output directory (default: docs/assets/screenshots/)
    --section SECTION  Capture only a specific section (slack-setup, session-ux)
    --dry-run          List planned screenshots without capturing

Environment variables:
    SUMMON_TEST_SLACK_WORKSPACE_URL  Allowlisted Slack workspace URL (required for browser capture)
    SUMMON_TEST_SLACK_COOKIE         Slack cookie for browser authentication
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = Path("docs/assets/screenshots")
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800

# Sections and their planned screenshots
SECTIONS: dict[str, list[dict]] = {
    "slack-setup": [
        {
            "name": "slack-setup-app-creation.png",
            "description": "Slack app creation page at api.slack.com",
            "manual_only": True,
        },
        {
            "name": "slack-setup-oauth-scopes.png",
            "description": "OAuth & Permissions scopes configuration",
            "manual_only": True,
        },
        {
            "name": "slack-setup-socket-mode.png",
            "description": "Socket Mode enabled configuration",
            "manual_only": True,
        },
        {
            "name": "slack-setup-event-subscriptions.png",
            "description": "Event Subscriptions configuration",
            "manual_only": True,
        },
        {
            "name": "slack-setup-install-app.png",
            "description": "Install App to workspace",
            "manual_only": True,
        },
    ],
    "session-ux": [
        {
            "name": "session-ux-channel-overview.png",
            "description": "Summon session channel with messages",
            "manual_only": False,
            "url_path": "/messages",
        },
        {
            "name": "session-ux-turn-thread.png",
            "description": "Turn thread showing tool use and response",
            "manual_only": False,
            "url_path": "/messages",
        },
        {
            "name": "session-ux-permissions-prompt.png",
            "description": "Permission approval prompt in Slack",
            "manual_only": False,
            "url_path": "/messages",
        },
        {
            "name": "session-ux-canvas-view.png",
            "description": "Session canvas with context summary",
            "manual_only": False,
            "url_path": "/canvas",
        },
    ],
}


# ---------------------------------------------------------------------------
# Workspace URL validation
# ---------------------------------------------------------------------------


def _get_allowlisted_workspace_url() -> str | None:
    """Return the allowlisted Slack workspace URL from env, or None if not set."""
    return os.environ.get("SUMMON_TEST_SLACK_WORKSPACE_URL")


def validate_workspace(page: object, allowlisted_url: str) -> bool:
    """Abort capture if the page is not connected to the test workspace.

    Args:
        page: Playwright Page object.
        allowlisted_url: The URL prefix that must match the current page URL.

    Returns:
        True if the workspace URL matches, False otherwise.
    """
    current_url: str = page.url  # type: ignore[attr-defined]
    # Normalize: strip trailing slashes for comparison
    allowlist_base = allowlisted_url.rstrip("/")
    if not current_url.startswith(allowlist_base):
        click.echo(
            f"SECURITY ABORT: current URL '{current_url}' does not match "
            f"allowlisted workspace '{allowlist_base}'. Refusing to capture.",
            err=True,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Screenshot capture class
# ---------------------------------------------------------------------------


class ScreenshotCapture:
    def __init__(self, output_dir: Path, dry_run: bool = False) -> None:
        self.output_dir = output_dir
        self.dry_run = dry_run
        self._captured: list[str] = []
        self._skipped: list[str] = []
        self._warnings: list[str] = []

    def _ensure_output_dir(self) -> None:
        if not self.dry_run:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def _capture(self, page: object, name: str, _description: str) -> None:
        """Take a screenshot and save it."""
        dest = self.output_dir / name
        if self.dry_run:
            click.echo(f"  [dry-run] would capture: {dest}")
            self._captured.append(name)
            return
        page.screenshot(path=str(dest), full_page=False)  # type: ignore[attr-defined]
        click.echo(f"  captured: {dest}")
        self._captured.append(name)

    def capture_session_ux(self, page: object, allowlisted_url: str) -> None:
        """Capture session interaction screenshots.

        Navigates to the test workspace Slack channel and captures UX screenshots.
        Validates workspace URL before each capture.
        """
        screenshots = SECTIONS["session-ux"]
        click.echo(f"Capturing {len(screenshots)} session-ux screenshots...")

        for shot in screenshots:
            name = shot["name"]
            description = shot["description"]

            if self.dry_run:
                click.echo(f"  [dry-run] would capture: {self.output_dir / name} ({description})")
                self._captured.append(name)
                continue

            # Validate workspace URL before every capture
            if not validate_workspace(page, allowlisted_url):
                click.echo(f"  SKIPPED (workspace mismatch): {name}", err=True)
                self._skipped.append(name)
                continue

            try:
                self._capture(page, name, description)
            except Exception as exc:
                msg = f"Failed to capture {name}: {exc}"
                click.echo(f"  WARNING: {msg}", err=True)
                self._warnings.append(msg)
                self._skipped.append(name)

    def validate_manual_screenshots(self) -> None:
        """Check that all manual-only screenshots exist and warn if missing."""
        missing = []
        for shot in SECTIONS["slack-setup"]:
            dest = self.output_dir / shot["name"]
            if not dest.exists():
                missing.append(shot["name"])

        if missing:
            click.echo("\nWARNING: The following manual screenshots are missing:", err=True)
            for name in missing:
                click.echo(f"  missing: {self.output_dir / name}", err=True)
            click.echo(
                "\nThese screenshots must be captured manually from api.slack.com.\n"
                "See docs/setup/slack-app.md for instructions.",
                err=True,
            )
            self._warnings.extend(f"Missing manual screenshot: {n}" for n in missing)

    def summary(self) -> None:
        """Print a summary of captured/skipped screenshots."""
        click.echo(f"\nSummary: {len(self._captured)} captured, {len(self._skipped)} skipped")
        if self._warnings:
            click.echo(f"  {len(self._warnings)} warning(s):")
            for w in self._warnings:
                click.echo(f"    - {w}", err=True)


# ---------------------------------------------------------------------------
# Dry-run listing (no browser needed)
# ---------------------------------------------------------------------------


def list_planned_screenshots(output_dir: Path, section: str | None) -> None:
    """List all planned screenshots without launching a browser."""
    sections = [section] if section else list(SECTIONS.keys())
    click.echo(f"Planned screenshots (output: {output_dir}):\n")
    for sec in sections:
        if sec not in SECTIONS:
            click.echo(f"Unknown section: {sec}", err=True)
            continue
        click.echo(f"[{sec}]")
        for shot in SECTIONS[sec]:
            tag = "(manual-only)" if shot.get("manual_only") else "(automated)"
            click.echo(f"  {tag} {output_dir / shot['name']}")
            click.echo(f"         {shot['description']}")
        click.echo()


# ---------------------------------------------------------------------------
# Browser-based capture
# ---------------------------------------------------------------------------


def run_browser_capture(
    capture: ScreenshotCapture,
    section: str | None,
    allowlisted_url: str,
    cookie_value: str,
) -> None:
    """Launch Playwright, authenticate, and capture automated screenshots."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        click.echo(
            "WARNING: playwright is not importable. "
            "Run `uv sync --group docs` and `playwright install chromium` to enable captures.",
            err=True,
        )
        return

    sections_to_capture = [section] if section else list(SECTIONS.keys())

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        )

        # Inject authentication cookie
        context.add_cookies(
            [
                {
                    "name": "d",
                    "value": cookie_value,
                    "domain": ".slack.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                }
            ]
        )

        page = context.new_page()

        for sec in sections_to_capture:
            if sec not in SECTIONS:
                click.echo(f"Unknown section: {sec}", err=True)
                continue

            if sec == "slack-setup":
                # slack-setup is manual-only; just validate existing files
                click.echo("[slack-setup] Manual-only section — skipping automated capture.")
                capture.validate_manual_screenshots()
                continue

            if sec == "session-ux":
                # Navigate to the allowlisted workspace
                click.echo(f"[session-ux] Navigating to {allowlisted_url} ...")
                try:
                    page.goto(allowlisted_url, wait_until="networkidle", timeout=30_000)
                except Exception as exc:
                    click.echo(f"WARNING: navigation failed: {exc}", err=True)
                    capture._skipped.extend(s["name"] for s in SECTIONS["session-ux"])  # noqa: SLF001
                    capture._warnings.append(f"Navigation to workspace failed: {exc}")  # noqa: SLF001
                    continue

                # Final workspace validation before any capture
                if not validate_workspace(page, allowlisted_url):
                    sys.exit(1)

                capture.capture_session_ux(page, allowlisted_url)

        context.close()
        browser.close()


# ---------------------------------------------------------------------------
# CLI entry point
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
    type=click.Choice(list(SECTIONS.keys())),
    help="Capture only a specific section.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List planned screenshots without capturing.",
)
def main(output_dir: Path, section: str | None, dry_run: bool) -> None:
    """Generate documentation screenshots using Playwright.

    Requires SUMMON_TEST_SLACK_WORKSPACE_URL to be set for automated browser captures.
    Requires SUMMON_TEST_SLACK_COOKIE for Slack authentication.

    Manual-only screenshots (slack-setup section) must be captured by hand from
    api.slack.com and placed in the output directory.
    """
    capture = ScreenshotCapture(output_dir=output_dir, dry_run=dry_run)
    capture._ensure_output_dir()  # noqa: SLF001

    # --dry-run: just list what would be captured
    if dry_run:
        list_planned_screenshots(output_dir, section)
        capture.validate_manual_screenshots()
        return

    # Verify Playwright is installed before proceeding
    try:
        import playwright
    except ImportError:
        click.echo(
            "WARNING: playwright package not found. "
            "Install with `uv sync --group docs` and run `playwright install chromium`.",
            err=True,
        )
        sys.exit(0)

    # Resolve workspace URL allowlist
    allowlisted_url = _get_allowlisted_workspace_url()
    cookie_value = os.environ.get("SUMMON_TEST_SLACK_COOKIE")

    # Sections that only need manual validation (no browser needed)
    manual_only_sections = {"slack-setup"}
    requested_sections = {section} if section else set(SECTIONS.keys())
    automated_sections = requested_sections - manual_only_sections

    # Always validate manual screenshots
    if not section or section == "slack-setup":
        click.echo("[slack-setup] Validating manual screenshots...")
        capture.validate_manual_screenshots()

    if automated_sections:
        if not allowlisted_url:
            click.echo(
                "INFO: SUMMON_TEST_SLACK_WORKSPACE_URL not set — skipping automated captures.",
                err=True,
            )
            capture._skipped.extend(  # noqa: SLF001
                s["name"]
                for sec in automated_sections
                for s in SECTIONS.get(sec, [])
                if not s.get("manual_only")
            )
        elif not cookie_value:
            click.echo(
                "INFO: SUMMON_TEST_SLACK_COOKIE not set — skipping browser-based captures.",
                err=True,
            )
            capture._skipped.extend(  # noqa: SLF001
                s["name"]
                for sec in automated_sections
                for s in SECTIONS.get(sec, [])
                if not s.get("manual_only")
            )
        else:
            run_browser_capture(capture, section, allowlisted_url, cookie_value)

    capture.summary()


if __name__ == "__main__":
    main()
