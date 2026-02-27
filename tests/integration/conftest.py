"""Shared fixtures for Slack integration tests."""

from __future__ import annotations

import contextlib
import os
import time

import pytest
from slack_sdk.web.async_client import AsyncWebClient

from summon_claude.channel_manager import ChannelManager
from summon_claude.providers.slack import SlackChatProvider
from summon_claude.thread_router import ThreadRouter

pytestmark = [pytest.mark.slack]


class SlackTestHarness:
    """Manages Slack workspace state for integration tests."""

    def __init__(self) -> None:
        self._bot_token = os.environ["SUMMON_TEST_SLACK_BOT_TOKEN"]
        self._app_token = os.environ["SUMMON_TEST_SLACK_APP_TOKEN"]
        self._signing_secret = os.environ["SUMMON_TEST_SLACK_SIGNING_SECRET"]
        self._client: AsyncWebClient | None = None
        self._bot_user_id: str | None = None

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
            self._client = AsyncWebClient(token=self._bot_token)
        return self._client

    @property
    def keep_artifacts(self) -> bool:
        return os.environ.get("SUMMON_TEST_KEEP_ARTIFACTS", "") == "1"

    async def resolve_bot_user_id(self) -> str:
        if self._bot_user_id is None:
            resp = await self.client.auth_test()
            self._bot_user_id = resp["user_id"]
        return self._bot_user_id

    async def create_test_channel(self, prefix: str = "test") -> str:
        """Create a test channel with timestamp suffix. Returns channel_id."""
        name = f"{prefix}-integ-{int(time.time())}"[:80]
        resp = await self.client.conversations_create(name=name, is_private=True)
        channel = resp.get("channel") or {}
        return channel["id"]

    async def cleanup_channels(self, channel_ids: list[str]) -> None:
        """Archive test channels (best-effort)."""
        for cid in channel_ids:
            with contextlib.suppress(Exception):
                await self.client.conversations_archive(channel=cid)


@pytest.fixture
async def slack_harness():
    """Harness — skips if credentials not set."""
    if not os.environ.get("SUMMON_TEST_SLACK_BOT_TOKEN"):
        pytest.skip("SUMMON_TEST_SLACK_BOT_TOKEN not set")

    harness = SlackTestHarness()
    # Validate credentials
    await harness.resolve_bot_user_id()
    yield harness


@pytest.fixture
async def test_channel(slack_harness):
    """Function-scoped test channel with auto-cleanup."""
    channel_id = await slack_harness.create_test_channel()
    yield channel_id
    if not slack_harness.keep_artifacts:
        await slack_harness.cleanup_channels([channel_id])


@pytest.fixture
def slack_provider(slack_harness):
    """SlackChatProvider backed by real credentials."""
    return SlackChatProvider(slack_harness.client)


@pytest.fixture
def channel_manager(slack_provider):
    """ChannelManager backed by real SlackChatProvider."""
    return ChannelManager(slack_provider, channel_prefix="test")


@pytest.fixture
async def thread_router(slack_provider, test_channel):
    """ThreadRouter backed by real provider and test channel."""
    return ThreadRouter(slack_provider, test_channel)
