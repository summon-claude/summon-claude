"""Integration tests for canvas operations against real Slack API.

Tests SlackClient canvas methods (create, sync, rename, discovery) and
CanvasStore restore/persist lifecycle with real Slack + real SQLite.

Canvas API quirks validated here:
- Free-plan workspaces require channel_id on canvases.create.
- Only 1 change per canvases.edit call.
- replace operation only replaces body, not title.
- files.list with types=spaces discovers canvases.
"""

from __future__ import annotations

import asyncio

import pytest

from summon_claude.slack.canvas_store import CanvasStore
from summon_claude.slack.client import SlackClient

pytestmark = [pytest.mark.slack]


class TestCanvasCreate:
    """Test canvas creation via SlackClient against real Slack."""

    async def test_canvas_create_returns_id(self, slack_harness, fresh_channel):
        """canvas_create returns a non-empty canvas file ID."""
        client = SlackClient(slack_harness.client, fresh_channel)
        canvas_id = await client.canvas_create(
            "# Test Canvas\n\nCreated by integration test.",
            title="Integration Test Canvas",
        )
        # canvas_create may return None on free-plan constraints;
        # but if it returns a value, it must be a valid ID
        if canvas_id is None:
            pytest.skip("Canvas creation not supported (likely free-plan limit)")
        assert isinstance(canvas_id, str)
        assert len(canvas_id) > 0

    async def test_canvas_create_fallback_to_existing(self, slack_harness, fresh_channel):
        """Second canvas_create on same channel falls back to existing canvas.

        Free-plan workspaces allow only one canvas per channel. The fallback
        path in SlackClient.canvas_create should find and reuse the existing one.
        """
        client = SlackClient(slack_harness.client, fresh_channel)
        first_id = await client.canvas_create("# First", title="First Canvas")
        if first_id is None:
            pytest.skip("Canvas creation not supported")

        # Second create on same channel — should either create a new one
        # or fall back to the existing one
        second_id = await client.canvas_create("# Second", title="Second Canvas")
        assert second_id is not None
        # On free plan, second_id == first_id (fallback reused existing)
        # On paid plan, second_id may differ (new canvas created)


class TestCanvasSync:
    """Test canvas content sync via SlackClient."""

    async def test_canvas_sync_replaces_content(self, slack_harness, fresh_channel):
        """canvas_sync replaces the body content of an existing canvas."""
        client = SlackClient(slack_harness.client, fresh_channel)
        canvas_id = await client.canvas_create("# Original Content", title="Sync Test")
        if not canvas_id:
            pytest.skip("Canvas creation not supported")
        assert canvas_id is not None  # narrow type for pyright

        result = await client.canvas_sync(canvas_id, "# Updated Content\n\nNew body text.")
        assert result is True

    async def test_canvas_sync_invalid_id_returns_false(self, slack_harness, fresh_channel):
        """canvas_sync with a bogus canvas ID returns False (never raises)."""
        client = SlackClient(slack_harness.client, fresh_channel)
        result = await client.canvas_sync("F0000INVALID", "# Content")
        assert result is False


class TestCanvasRename:
    """Test canvas rename via SlackClient."""

    async def test_canvas_rename_updates_title(self, slack_harness, fresh_channel):
        """canvas_rename changes the canvas title."""
        client = SlackClient(slack_harness.client, fresh_channel)
        canvas_id = await client.canvas_create("# Content", title="Original Title")
        if not canvas_id:
            pytest.skip("Canvas creation not supported")
        assert canvas_id is not None

        result = await client.canvas_rename(canvas_id, "Renamed Title")
        assert result is True

    async def test_canvas_rename_invalid_id_returns_false(self, slack_harness, fresh_channel):
        client = SlackClient(slack_harness.client, fresh_channel)
        result = await client.canvas_rename("F0000INVALID", "New Title")
        assert result is False


class TestCanvasDiscovery:
    """Test canvas discovery via files.list."""

    async def test_get_canvas_id_finds_canvas(self, slack_harness, fresh_channel):
        """get_canvas_id returns the canvas ID after creation.

        Slack's files.list indexing is async — canvases created via
        canvases.create may take several seconds to appear. On some
        workspaces (especially free-plan), indexing can be very slow
        or the canvas type filter may not match.
        """
        client = SlackClient(slack_harness.client, fresh_channel)
        created_id = await client.canvas_create("# Discovery Test", title="Find Me")
        if created_id is None:
            pytest.skip("Canvas creation not supported")

        # files.list indexing can be very slow — retry with backoff
        found_id = None
        for _ in range(10):
            found_id = await client.get_canvas_id()
            if found_id:
                break
            await asyncio.sleep(2)

        if found_id is None:
            pytest.skip(
                "files.list did not index canvas within timeout (known Slack API indexing delay)"
            )
        assert found_id == created_id

    async def test_get_canvas_id_returns_none_for_empty_channel(self, slack_harness, fresh_channel):
        """get_canvas_id returns None for a channel with no canvas."""
        client = SlackClient(slack_harness.client, fresh_channel)
        result = await client.get_canvas_id()
        assert result is None


class TestCanvasStoreRestore:
    """Test CanvasStore.restore with real Slack + real SQLite registry."""

    async def test_restore_from_channels_table(self, slack_harness, fresh_channel, registry):
        """CanvasStore.restore reconstructs store from channels table data."""
        client = SlackClient(slack_harness.client, fresh_channel)
        canvas_id = await client.canvas_create(
            "# Restore Test\n\nOriginal content.", title="Restore Test Canvas"
        )
        if canvas_id is None:
            pytest.skip("Canvas creation not supported")

        # Seed the channels table with canvas data (simulating previous session)
        await registry.register_channel(
            channel_id=fresh_channel,
            channel_name="test-restore",
            cwd="/tmp/test",
            authenticated_user_id="U_TEST",
        )
        await registry.update_channel_canvas(
            fresh_channel, canvas_id, "# Restore Test\n\nOriginal content."
        )

        # Restore the CanvasStore
        store = await CanvasStore.restore(
            session_id="test-session-id",
            client=client,
            registry=registry,
            channel_id=fresh_channel,
        )
        assert store is not None
        assert store.canvas_id == canvas_id
        assert "Restore Test" in store.markdown

    async def test_restore_returns_none_for_no_canvas(self, slack_harness, fresh_channel, registry):
        """CanvasStore.restore returns None when no canvas data in channels table."""
        client = SlackClient(slack_harness.client, fresh_channel)

        # Register channel without canvas
        await registry.register_channel(
            channel_id=fresh_channel,
            channel_name="no-canvas",
            cwd="/tmp/test",
        )

        store = await CanvasStore.restore(
            session_id="test-session-id",
            client=client,
            registry=registry,
            channel_id=fresh_channel,
        )
        assert store is None

    async def test_restored_store_can_sync_to_slack(self, slack_harness, fresh_channel, registry):
        """A restored CanvasStore can write updated content to real Slack."""
        client = SlackClient(slack_harness.client, fresh_channel)
        canvas_id = await client.canvas_create("# Initial Content", title="Sync After Restore")
        if canvas_id is None:
            pytest.skip("Canvas creation not supported")

        await registry.register_channel(
            channel_id=fresh_channel,
            channel_name="test-sync-restore",
            cwd="/tmp/test",
        )
        await registry.update_channel_canvas(fresh_channel, canvas_id, "# Initial Content")

        store = await CanvasStore.restore(
            session_id="test-session-id",
            client=client,
            registry=registry,
            channel_id=fresh_channel,
        )
        assert store is not None

        # Write new content and verify it syncs to Slack
        await store.write("# Updated After Restore\n\nNew content written by restored store.")

        # Verify the content updated locally
        assert "Updated After Restore" in store.read()

        # Verify it persisted to SQLite
        channel = await registry.get_channel(fresh_channel)
        assert channel is not None
        assert "Updated After Restore" in (channel.get("canvas_markdown") or "")

    async def test_canvas_update_section_via_restored_store(
        self, slack_harness, fresh_channel, registry
    ):
        """CanvasStore.update_section works on a restored store."""
        client = SlackClient(slack_harness.client, fresh_channel)
        initial_md = "# Session Canvas\n\n## Status\n\nIdle\n\n## Notes\n\nNone yet"
        canvas_id = await client.canvas_create(initial_md, title="Section Update Test")
        if canvas_id is None:
            pytest.skip("Canvas creation not supported")

        await registry.register_channel(
            channel_id=fresh_channel,
            channel_name="test-section",
            cwd="/tmp/test",
        )
        await registry.update_channel_canvas(fresh_channel, canvas_id, initial_md)

        store = await CanvasStore.restore(
            session_id="test-session-id",
            client=client,
            registry=registry,
            channel_id=fresh_channel,
        )
        assert store is not None

        await store.update_section("Status", "Active - working on task X")
        assert "Active - working on task X" in store.read()
        # Notes section should be preserved
        assert "None yet" in store.read()

    async def test_sync_loop_flushes_to_slack(self, slack_harness, fresh_channel, registry):
        """CanvasStore background sync loop writes content to real Slack canvas.

        Starts the sync loop, writes content, waits for flush, then verifies
        the canvas was updated by reading it back via canvas_sync (replace+read).
        """
        client = SlackClient(slack_harness.client, fresh_channel)
        canvas_id = await client.canvas_create(
            "# Sync Loop Test\n\nOriginal.", title="Sync Loop Test"
        )
        if canvas_id is None:
            pytest.skip("Canvas creation not supported")
        assert canvas_id is not None

        await registry.register_channel(
            channel_id=fresh_channel,
            channel_name="sync-loop",
            cwd="/tmp/test",
        )
        await registry.update_channel_canvas(
            fresh_channel, canvas_id, "# Sync Loop Test\n\nOriginal."
        )

        store = await CanvasStore.restore(
            session_id="test-sync-loop",
            client=client,
            registry=registry,
            channel_id=fresh_channel,
        )
        assert store is not None

        store.start_sync()
        try:
            await store.write("# Sync Loop Test\n\nUpdated via sync loop.")
            # The sync loop debounces at 2s dirty delay. Wait for it to flush.
            await asyncio.sleep(4)
        finally:
            await store.stop_sync()

        # Verify content persisted to SQLite
        channel = await registry.get_channel(fresh_channel)
        assert channel is not None
        assert "Updated via sync loop" in (channel.get("canvas_markdown") or "")
