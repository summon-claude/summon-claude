"""Playwright-based Slack WebSocket monitor for external workspace observation.

Captures DMs, @mentions, and monitored channel messages from external Slack
workspaces via browser automation. Auth state is stored at 0o600 permissions.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from summon_claude.config import get_data_dir

logger = logging.getLogger(__name__)

_QUEUE_MAX = 10_000
# Maximum wait for login confirmation during interactive auth (seconds)
_AUTH_TIMEOUT_S = 300


def _slugify(url: str) -> str:
    """Convert a workspace URL to a safe filesystem identifier.

    Examples::

        _slugify("https://myteam.slack.com") -> "myteam_slack_com"
        _slugify("https://acme-corp.slack.com/") -> "acme-corp_slack_com"
    """
    # Strip scheme and trailing slashes
    slug = re.sub(r"^https?://", "", url).rstrip("/")
    # Replace non-alphanumeric-or-hyphen chars with underscores
    slug = re.sub(r"[^\w\-]", "_", slug)
    # Collapse repeated underscores
    slug = re.sub(r"_+", "_", slug)
    # Remove leading/trailing underscores
    return slug.strip("_")


@dataclass
class SlackMessage:
    """A sanitised message captured from an external Slack workspace."""

    channel: str
    user: str
    text: str
    ts: str
    workspace: str
    is_dm: bool = False
    is_mention: bool = False


class SlackBrowserMonitor:
    """Monitor an external Slack workspace via Playwright WebSocket interception.

    Playwright's page.on('websocket') API intercepts all Slack RTM frames.
    Message filtering happens immediately on receipt so no raw frame data is
    stored or logged ([SEC-007]).

    The asyncio event loop is captured at ``start()`` time and used for
    thread-safe queue enqueue from Playwright's callback threads.
    """

    def __init__(
        self,
        workspace_id: str,
        workspace_url: str,
        state_file: Path,
        monitored_channel_ids: list[str],
        user_id: str,
    ) -> None:
        self._workspace_id = workspace_id
        self._workspace_url = workspace_url
        self._state_file = state_file
        self._monitored_channel_ids: set[str] = set(monitored_channel_ids)
        self._user_id = user_id

        self._queue: asyncio.Queue[SlackMessage] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._playwright = None  # type: ignore[assignment]
        self._browser = None  # type: ignore[assignment]
        self._context = None  # type: ignore[assignment]
        self._page = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self, browser_type: str = "chrome") -> None:
        """Launch Playwright, load Slack, and attach WebSocket listener."""
        from playwright.async_api import async_playwright  # noqa: PLC0415

        self._loop = asyncio.get_running_loop()

        self._playwright = await async_playwright().start()

        if browser_type == "chrome":
            browser_launcher = self._playwright.chromium
            channel = "chrome"
        elif browser_type == "firefox":
            browser_launcher = self._playwright.firefox
            channel = None
        else:
            browser_launcher = self._playwright.webkit
            channel = None

        launch_kwargs: dict = {}
        if channel:
            launch_kwargs["channel"] = channel

        self._browser = await browser_launcher.launch(headless=True, **launch_kwargs)

        context_kwargs: dict = {}
        if self._state_file.is_file():
            context_kwargs["storage_state"] = str(self._state_file)

        self._context = await self._browser.new_context(**context_kwargs)
        self._page = await self._context.new_page()
        self._page.on("websocket", self._on_websocket)

        await self._page.goto(self._workspace_url)
        logger.info("SlackBrowserMonitor started for workspace %s", self._workspace_id)

    def _on_websocket(self, ws) -> None:  # type: ignore[no-untyped-def]
        """Attach a frame handler to each new WebSocket connection."""
        ws.on("framereceived", self._on_frame)

    def _on_frame(self, payload: str | bytes) -> None:
        """Parse a WebSocket frame and enqueue matching messages.

        [SEC-007] Filters by type IMMEDIATELY after JSON parse. Never logs raw
        frames. Only enqueues sanitised SlackMessage fields.
        """
        try:
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="replace")
            frame = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            # Not JSON — ignore silently (many Slack WS frames are non-JSON pings)
            return

        # [SEC-007] Filter by type immediately — discard everything else
        if frame.get("type") != "message":
            return

        # Skip bot messages and message edits (subtype indicates non-user content)
        subtype = frame.get("subtype", "")
        if subtype in ("bot_message", "message_changed", "message_deleted"):
            return

        channel = str(frame.get("channel", ""))
        user = str(frame.get("user", ""))
        text = str(frame.get("text", ""))
        ts = str(frame.get("ts", ""))

        # Determine message classification
        is_dm = channel.startswith("D")
        is_mention = f"<@{self._user_id}>" in text

        # Apply routing filter: only accept DMs, mentions, or monitored channels
        if not (is_dm or is_mention or channel in self._monitored_channel_ids):
            return

        msg = SlackMessage(
            channel=channel,
            user=user,
            text=text,
            ts=ts,
            workspace=self._workspace_id,
            is_dm=is_dm,
            is_mention=is_mention,
        )

        # Thread-safe enqueue via the captured event loop
        if self._loop is not None and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, msg)
            except asyncio.QueueFull:
                logger.warning(
                    "SlackBrowserMonitor queue full for workspace %s — dropping message",
                    self._workspace_id,
                )
            except RuntimeError:
                # Loop was closed between the check and the call
                pass

    async def drain(self, limit: int = 0) -> list[SlackMessage]:
        """Drain queued messages and return them.

        Args:
            limit: Maximum number of messages to drain. 0 means drain all.
        """
        messages: list[SlackMessage] = []
        while limit == 0 or len(messages) < limit:
            try:
                messages.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return messages

    async def refresh_if_stuck(self) -> None:
        """Reload the Slack page as a fallback if the WebSocket appears stuck."""
        if self._page is not None:
            logger.info("SlackBrowserMonitor: refreshing page for workspace %s", self._workspace_id)
            try:
                await self._page.reload()
            except Exception as exc:
                logger.warning(
                    "SlackBrowserMonitor: page reload failed for workspace %s: %s",
                    self._workspace_id,
                    exc,
                )

    async def stop(self) -> None:
        """Save auth state and close the browser."""
        if self._context is not None:
            # [SEC-R-002] Verify state file is not a symlink before writing
            if self._state_file.is_symlink():
                logger.error(
                    "SlackBrowserMonitor: refusing to save auth state — %s is a symlink",
                    self._state_file,
                )
            else:
                try:
                    await self._context.storage_state(path=str(self._state_file))
                    # [SEC-005] Ensure saved state file has restricted permissions
                    self._state_file.chmod(0o600)
                    logger.info(
                        "SlackBrowserMonitor: saved auth state for workspace %s",
                        self._workspace_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "SlackBrowserMonitor: failed to save auth state for %s: %s",
                        self._workspace_id,
                        exc,
                    )

            with contextlib.suppress(Exception):
                await self._context.close()

        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()

        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()

        logger.info("SlackBrowserMonitor stopped for workspace %s", self._workspace_id)


async def interactive_slack_auth(
    workspace_url: str,
    browser_type: str = "chrome",
) -> Path:
    """Open a browser for interactive Slack login and persist auth state.

    Waits up to 5 minutes for the user to complete login. Auth state is
    saved to ``get_data_dir() / "browser_auth" / "slack_{workspace_id}.json"``
    with 0o600 permissions ([SEC-005]).

    Returns the path to the saved state file.
    """
    from playwright.async_api import async_playwright  # noqa: PLC0415

    workspace_id = _slugify(workspace_url)
    browser_auth_dir = get_data_dir() / "browser_auth"

    # [SEC-005] Validate that browser_auth/ is not a symlink before writing
    if browser_auth_dir.exists() and browser_auth_dir.is_symlink():
        raise RuntimeError(
            f"Security error: browser_auth directory {browser_auth_dir} is a symlink. "
            "Refusing to write auth state to a symlinked directory."
        )

    # Create directory with 0o700 permissions ([SEC-005])
    browser_auth_dir.mkdir(parents=True, exist_ok=True)
    browser_auth_dir.chmod(0o700)

    # Add .gitignore to prevent accidental commits ([SEC-005])
    gitignore_path = browser_auth_dir / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text("*\n")

    state_file = browser_auth_dir / f"slack_{workspace_id}.json"

    async with async_playwright() as p:
        if browser_type == "chrome":
            browser_launcher = p.chromium
            launch_kwargs: dict = {"channel": "chrome"}
        elif browser_type == "firefox":
            browser_launcher = p.firefox
            launch_kwargs = {}
        else:
            browser_launcher = p.webkit
            launch_kwargs = {}

        browser = await browser_launcher.launch(headless=False, **launch_kwargs)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(workspace_url)

        logger.info(
            "Waiting for Slack login at %s (timeout %ds) ...", workspace_url, _AUTH_TIMEOUT_S
        )

        # Wait for the channel sidebar — confirms successful login
        try:
            await page.wait_for_selector(
                '[data-qa="channel_sidebar"]',
                timeout=_AUTH_TIMEOUT_S * 1000,
            )
        except Exception as exc:
            await browser.close()
            raise TimeoutError(
                f"Slack login not completed within {_AUTH_TIMEOUT_S}s for {workspace_url}"
            ) from exc

        # Save auth state with restricted permissions ([SEC-005])
        await context.storage_state(path=str(state_file))
        state_file.chmod(0o600)

        await browser.close()

    logger.info("Slack auth state saved to %s", state_file)
    return state_file
