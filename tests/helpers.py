"""Shared test helpers for summon-claude tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from summon_claude.slack.client import ChannelRef, MessageRef, SlackClient


def make_mock_slack_client():
    """Create a mocked SlackClient with standard return values."""
    client = AsyncMock(spec=SlackClient)
    client.post = AsyncMock(return_value=MessageRef(channel_id="C123", ts="1234567890.123456"))
    client.update = AsyncMock()
    client.react = AsyncMock()
    client.upload = AsyncMock()
    client.set_topic = AsyncMock()
    client.post_ephemeral = AsyncMock()
    client.channel_id = "C123"
    return client


# Backward-compat alias — code that still references make_mock_provider gets a SlackClient mock
def make_mock_provider():
    """Backward-compatible alias for make_mock_slack_client."""
    return make_mock_provider_compat()


def make_mock_provider_compat():
    """Create a mocked object compatible with old ChatProvider interface.

    Used by test files that haven't been fully migrated to SlackClient yet.
    Returns a mock that supports both the old provider API (post_message, etc.)
    and the new SlackClient API (post, etc.).
    """
    from unittest.mock import MagicMock

    provider = MagicMock()
    provider.post_message = AsyncMock(
        return_value=MessageRef(channel_id="C123", ts="1234567890.123456")
    )
    provider.update_message = AsyncMock()
    provider.add_reaction = AsyncMock()
    provider.upload_file = AsyncMock()
    provider.create_channel = AsyncMock(
        return_value=ChannelRef(channel_id="C_NEW", name="test-channel")
    )
    provider.invite_user = AsyncMock()
    provider.archive_channel = AsyncMock()
    provider.set_topic = AsyncMock()
    provider.post_ephemeral = AsyncMock()
    # SlackClient-compatible methods
    provider.post = AsyncMock(return_value=MessageRef(channel_id="C123", ts="1234567890.123456"))
    provider.update = AsyncMock()
    provider.react = AsyncMock()
    provider.upload = AsyncMock()
    provider.channel_id = "C123"
    return provider
