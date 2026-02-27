"""Integration tests for ChannelManager against real Slack API.

Basic channel lifecycle (create, topic, archive) is exercised
transitively by the shared test_channel fixture. Tests here focus
on ChannelManager-specific orchestration logic.
"""

from __future__ import annotations

import pytest

from summon_claude.channel_manager import ChannelManager

pytestmark = [pytest.mark.slack]


class TestChannelLifecycle:
    """Test ChannelManager orchestration logic."""

    async def test_create_channel_name_collision(self, slack_provider, slack_harness):
        """Two channels with same session name get different suffixes."""
        mgr = ChannelManager(slack_provider, channel_prefix="collision")
        id1, name1 = await mgr.create_session_channel("dup")
        id2, name2 = await mgr.create_session_channel("dup")
        assert id1 != id2
        assert name1 != name2
        await slack_harness.cleanup_channels([id1, id2])

    async def test_channel_name_slugify(self, channel_manager, slack_harness):
        """Special characters in name should be slugified."""
        channel_id, channel_name = await channel_manager.create_session_channel("My Feature! @v2")
        assert channel_id
        assert all(c.isalnum() or c == "-" for c in channel_name)
        await slack_harness.cleanup_channels([channel_id])

    async def test_post_session_header(self, channel_manager, test_channel, slack_harness):
        session_info = {
            "cwd": "/tmp/test-project",
            "model": "claude-sonnet-4-20250514",
            "session_id": "abc123def456",
        }
        ts = await channel_manager.post_session_header(test_channel, session_info)
        assert ts
        history = await slack_harness.client.conversations_history(channel=test_channel, limit=5)
        assert any(m["ts"] == ts for m in history["messages"])


class TestTopicManagement:
    """Test ChannelManager topic operations."""

    async def test_set_session_topic(self, channel_manager, test_channel, slack_harness):
        await channel_manager.set_session_topic(
            test_channel,
            model="claude-sonnet-4-20250514",
            cwd="/tmp/test",
            git_branch="main",
            context=None,
        )
        info = await slack_harness.client.conversations_info(channel=test_channel)
        topic = info["channel"]["topic"]["value"]
        assert "sonnet" in topic
        assert "main" in topic

    async def test_update_topic(self, channel_manager, test_channel, slack_harness):
        await channel_manager.update_topic(test_channel, "Updated topic")
        info = await slack_harness.client.conversations_info(channel=test_channel)
        assert info["channel"]["topic"]["value"] == "Updated topic"
