"""Shared fixtures for Slack integration tests.

All tests share a single channel to stay within Slack's rate limits
(conversations.create is Tier 2 — ~20/min). The shared channel fixture
exercises lifecycle operations (create, invite, set_topic) on first use,
providing transitive signal for those code paths. Archive is exercised
in teardown.

``EventConsumer`` maintains a Socket Mode WebSocket connection during
tests, acknowledging all events. This serves dual purpose: enabling
round-trip event delivery tests (HTTP API → Socket Mode → assertion)
and preventing Slack from auto-disabling event subscriptions on the
test app (events with no consumer trigger auto-disable).
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path

import pytest
import pytest_asyncio
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.http_retry.async_handler import AsyncRetryHandler
from slack_sdk.http_retry.builtin_async_handlers import (
    AsyncRateLimitErrorRetryHandler,
    AsyncServerErrorRetryHandler,
)
from slack_sdk.web.async_client import AsyncWebClient

from summon_claude.sessions.registry import SessionRegistry
from summon_claude.slack.client import SlackClient
from summon_claude.slack.router import ThreadRouter


def _retry_handlers() -> list[AsyncRetryHandler]:
    """SDK retry handlers matching production config (bolt.py) with higher rate-limit budget."""
    return [
        AsyncRateLimitErrorRetryHandler(max_retry_count=3),
        AsyncServerErrorRetryHandler(max_retry_count=1),
    ]


# Load .env file so credentials are available for local runs
_env_file = Path(__file__).resolve().parents[2] / ".env"
if _env_file.exists():
    for raw_line in _env_file.read_text().splitlines():
        entry = raw_line.strip()
        if entry and not entry.startswith("#") and "=" in entry:
            key, _, value = entry.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Channel cleanup tracking — channels are archived at session end
_channels_to_cleanup: list[str] = []


class SlackTestHarness:
    """Manages Slack workspace state for integration tests."""

    def __init__(self) -> None:
        self._bot_token = os.environ["SUMMON_TEST_SLACK_BOT_TOKEN"]
        self._app_token = os.environ["SUMMON_TEST_SLACK_APP_TOKEN"]
        self._signing_secret = os.environ["SUMMON_TEST_SLACK_SIGNING_SECRET"]
        self._client: AsyncWebClient | None = None
        self._bot_user_id: str | None = None
        self._non_bot_user_id: str | None = None
        self._non_bot_user_resolved = False

    @property
    def bot_token(self) -> str:
        return self._bot_token

    @property
    def app_token(self) -> str:
        return self._app_token

    @property
    def signing_secret(self) -> str:
        return self._signing_secret

    @property
    def client(self) -> AsyncWebClient:
        if self._client is None:
            self._client = AsyncWebClient(
                token=self._bot_token,
                retry_handlers=_retry_handlers(),
            )
        return self._client

    @property
    def keep_artifacts(self) -> bool:
        return os.environ.get("SUMMON_TEST_KEEP_ARTIFACTS", "") == "1"

    async def resolve_bot_user_id(self) -> str:
        if self._bot_user_id is None:
            resp = await self.client.auth_test()
            self._bot_user_id = resp["user_id"]
        return self._bot_user_id

    async def find_non_bot_user(self) -> str | None:
        """Find a non-bot workspace member. Returns user_id or None. Cached."""
        if not self._non_bot_user_resolved:
            resp = await self.client.users_list(limit=50)
            bot_id = await self.resolve_bot_user_id()
            for member in resp.get("members", []):
                if (
                    not member.get("is_bot")
                    and not member.get("deleted")
                    and member.get("id") != "USLACKBOT"
                    and member.get("id") != bot_id
                ):
                    self._non_bot_user_id = member["id"]
                    break
            self._non_bot_user_resolved = True
        return self._non_bot_user_id

    async def create_test_channel(self, prefix: str = "test") -> str:
        """Create a test channel with timestamp + random suffix. Returns channel_id."""
        name = f"{prefix}-integ-{int(time.time())}-{secrets.token_hex(3)}"[:80]
        resp = await self.client.conversations_create(name=name, is_private=True)
        channel = resp.get("channel") or {}
        channel_id = channel["id"]
        _channels_to_cleanup.append(channel_id)
        return channel_id

    async def cleanup_channels(self, channel_ids: list[str]) -> None:
        """Archive test channels (best-effort)."""
        for cid in channel_ids:
            with contextlib.suppress(Exception):
                await self.client.conversations_archive(channel=cid)


class EventConsumer:
    """Socket Mode event consumer for integration tests.

    Maintains a real WebSocket connection to Slack, acknowledging all
    received events and collecting them in a queue for test assertions.

    Serves dual purpose:
      1. Enables round-trip event delivery tests (HTTP API → Socket Mode)
      2. Prevents Slack from auto-disabling event subscriptions on the
         test app (events with no consumer trigger auto-disable)

    Uses ``ignoring_self_events_enabled=False`` so the bot's own actions
    (messages, reactions) generate capturable events — essential since
    tests can only act as the bot.

    **Pause/resume**: Tests that need their own isolated Socket Mode
    connection must first pause this consumer to avoid event theft
    (Slack distributes events round-robin across all connected consumers
    for the same app token). Use the ``paused_consumer`` fixture.
    """

    def __init__(self, bot_token: str, app_token: str, signing_secret: str) -> None:
        self._bot_token = bot_token
        self._app_token = app_token
        self._signing_secret = signing_secret
        self._events: asyncio.Queue[dict] = asyncio.Queue()
        self._handler: AsyncSocketModeHandler | None = None

    async def start(self) -> None:
        app = AsyncApp(
            token=self._bot_token,
            signing_secret=self._signing_secret,
            ignoring_self_events_enabled=False,
        )
        # Register handlers for all subscribed event types to ensure
        # acknowledgment — unacknowledged events trigger retries and
        # can lead to Slack disabling subscriptions.
        for event_type in ("message", "reaction_added", "file_shared", "app_home_opened"):
            app.event(event_type)(self._capture_event)

        handler = AsyncSocketModeHandler(app, self._app_token)
        await handler.connect_async()
        self._handler = handler

    async def _capture_event(self, event: dict, **kwargs: object) -> None:
        await self._events.put(event)

    async def stop(self) -> None:
        if self._handler:
            try:
                await asyncio.wait_for(self._handler.close_async(), timeout=5.0)
            except Exception:
                logging.getLogger(__name__).debug(
                    "EventConsumer: close error (expected)", exc_info=True
                )

    async def pause(self) -> None:
        """Disconnect the Socket Mode consumer without destroying it.

        Used by ``paused_consumer`` to temporarily yield the connection
        so isolated tests can create their own consumer without event theft.
        """
        await self.stop()

    async def resume(
        self,
        client: AsyncWebClient,
        test_channel: str,
    ) -> None:
        """Reconnect and validate event delivery with a canary message.

        Restarts the Socket Mode connection and runs a canary check to
        ensure events are flowing before returning control to subsequent
        tests that depend on this consumer.
        """
        await self.start()
        # Slack's event routing table takes 1-3s to register a new consumer
        await asyncio.sleep(2.0)
        self.drain()

        # Canary: confirm events are actually flowing after reconnect
        canary = f"resume-canary-{secrets.token_hex(4)}"
        await client.chat_postMessage(channel=test_channel, text=canary)
        await self.wait_for_event(
            lambda e: e.get("type") == "message" and canary in e.get("text", ""),
            timeout=15.0,
        )
        self.drain()

    async def wait_for_event(
        self,
        predicate: Callable[[dict], bool],
        timeout: float = 10.0,
    ) -> dict:
        """Wait for an event matching *predicate*. Returns the event dict.

        Non-matching events are discarded (each test uses a unique nonce
        so cross-test interference is impossible). On timeout, raises
        ``TimeoutError`` with a summary of events seen for debugging.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        seen: list[dict] = []
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"No matching event within {timeout}s. "
                    f"Received {len(seen)} non-matching: "
                    f"{[e.get('type') for e in seen]}"
                )
            try:
                event = await asyncio.wait_for(self._events.get(), timeout=remaining)
            except TimeoutError:
                raise TimeoutError(
                    f"No matching event within {timeout}s. "
                    f"Received {len(seen)} non-matching: "
                    f"{[e.get('type') for e in seen]}"
                ) from None
            if predicate(event):
                return event
            seen.append(event)

    def drain(self) -> list[dict]:
        """Drain all events from the queue. Non-blocking."""
        events: list[dict] = []
        while not self._events.empty():
            try:
                events.append(self._events.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events


# Lock file shared across all worktrees and the main repo. Lives in ~/.cache
# (not repo-local .cache/) so concurrent runs from different worktrees or
# overlapping git push hooks all serialize through the same file.
_SOCKET_MODE_LOCK = Path.home() / ".cache" / "summon-claude" / "slack-test.lock"


@pytest.fixture(scope="session")
def _slack_socket_lock():
    """Exclusive file lock for Socket Mode tests.

    Slack distributes Socket Mode events across all connected consumers
    for the same app token.  Concurrent test runs (e.g. overlapping
    ``git push`` hooks) would steal each other's events, causing
    non-deterministic timeouts.  This lock serialises access so only
    one process holds a Socket Mode connection at a time.
    """
    _SOCKET_MODE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fd = _SOCKET_MODE_LOCK.open("w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def slack_harness():
    """Session-scoped harness — skips if credentials not set."""
    if not os.environ.get("SUMMON_TEST_SLACK_BOT_TOKEN"):
        pytest.skip("SUMMON_TEST_SLACK_BOT_TOKEN not set")

    harness = SlackTestHarness()
    await harness.resolve_bot_user_id()
    yield harness


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_channel(slack_harness):
    """Session-scoped test channel — created once, shared across all tests.

    Exercises create_channel + invite_user + set_topic, providing
    transitive lifecycle signal for those code paths.
    """
    channel_id = await slack_harness.create_test_channel()
    user_id = await slack_harness.find_non_bot_user()
    if user_id:
        with contextlib.suppress(Exception):
            await slack_harness.client.conversations_invite(channel=channel_id, users=user_id)
    await slack_harness.client.conversations_setTopic(
        channel=channel_id, topic="Integration test channel"
    )
    yield channel_id


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def event_consumer(_slack_socket_lock, slack_harness, test_channel):
    """Session-scoped Socket Mode consumer — one connection for all modules.

    Maintains a real WebSocket connection to Slack, shared across all
    Socket Mode tests. Runs a one-time canary (post -> wait -> drain)
    to validate event delivery before any tests execute.

    Failure modes:
      - No credentials -> handled by slack_harness (pytest.skip)
      - Connection timeout -> pytest.skip (infrastructure issue)
      - Canary timeout -> pytest.fail (event pipeline broken)
    """
    consumer = EventConsumer(
        bot_token=slack_harness.bot_token,
        app_token=slack_harness.app_token,
        signing_secret=slack_harness.signing_secret,
    )
    try:
        await asyncio.wait_for(consumer.start(), timeout=15.0)
    except TimeoutError:
        pytest.skip("Socket Mode connection timed out (15s)")
    except Exception as exc:
        await consumer.stop()
        pytest.skip(f"Socket Mode connection failed: {exc}")

    # Brief pause after connect: Slack's event routing table takes 1-3s to
    # fully register a new consumer after rapid consumer cycling (e.g. the
    # isolated tests disconnect/reconnect their own consumers just before us).
    await asyncio.sleep(2.0)

    canary = f"canary-{secrets.token_hex(4)}"
    await slack_harness.client.chat_postMessage(channel=test_channel, text=canary)
    try:
        await consumer.wait_for_event(
            lambda e: e.get("type") == "message" and canary in e.get("text", ""),
            timeout=15.0,
        )
    except TimeoutError:
        await consumer.stop()
        pytest.fail(
            "Socket Mode canary failed -- events not flowing. "
            "Credentials are valid but the event delivery pipeline is broken."
        )
    consumer.drain()

    yield consumer
    await consumer.stop()


@pytest_asyncio.fixture(loop_scope="session")
async def paused_consumer(event_consumer, slack_harness, test_channel):
    """Temporarily disconnect the session-scoped EventConsumer.

    Slack distributes Socket Mode events round-robin across all connected
    consumers for the same app token. Tests that create their own consumer
    must use this fixture to pause the session-scoped one first, preventing
    event theft.

    On teardown, the session consumer is reconnected and validated with a
    canary message before subsequent tests can use it.
    """
    await event_consumer.pause()
    yield event_consumer
    await event_consumer.resume(slack_harness.client, test_channel)


@pytest.fixture
def slack_client(slack_harness, test_channel):
    """SlackClient bound to test channel."""
    return SlackClient(slack_harness.client, test_channel)


@pytest.fixture
async def thread_router(slack_client):
    """ThreadRouter backed by real SlackClient and test channel."""
    return ThreadRouter(slack_client)


@pytest.fixture
async def fresh_channel(slack_harness):
    """Create a fresh isolated channel for tests that modify channel state.

    Unlike test_channel, this is NOT shared — each test gets its own channel.
    The channel is archived in teardown.
    """
    channel_id = await slack_harness.create_test_channel(prefix="lifecycle")
    yield channel_id
    with contextlib.suppress(Exception):
        await slack_harness.client.conversations_archive(channel=channel_id)


@pytest.fixture
async def registry(tmp_path):
    """SessionRegistry backed by a temp SQLite DB."""
    db_path = tmp_path / "test.db"
    async with SessionRegistry(db_path=db_path) as reg:
        yield reg


def pytest_sessionfinish(session, exitstatus):
    """Archive all test channels at end of session."""
    if not _channels_to_cleanup:
        return
    if os.environ.get("SUMMON_TEST_KEEP_ARTIFACTS", "") == "1":
        return
    token = os.environ.get("SUMMON_TEST_SLACK_BOT_TOKEN")
    if not token:
        return
    client = AsyncWebClient(token=token, retry_handlers=_retry_handlers())

    async def _cleanup():
        for cid in _channels_to_cleanup:
            with contextlib.suppress(Exception):
                await client.conversations_archive(channel=cid)

    with contextlib.suppress(Exception):
        asyncio.run(_cleanup())
