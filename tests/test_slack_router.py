"""Tests for summon_claude.slack.router — ThreadRouter (thread management only)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from summon_claude.slack.client import MessageRef, SlackClient
from summon_claude.slack.router import ThreadRouter


def make_mock_client(ts: str = "1234567890.123456") -> tuple[SlackClient, MagicMock]:
    """Create a mocked SlackClient bound to C123."""
    web = MagicMock()
    web.chat_postMessage = AsyncMock(return_value={"channel": "C123", "ts": ts})
    web.chat_postEphemeral = AsyncMock(return_value={})
    web.chat_update = AsyncMock(return_value={})
    web.reactions_add = AsyncMock(return_value={})
    web.files_upload_v2 = AsyncMock(return_value={})
    web.conversations_setTopic = AsyncMock(return_value={})
    client = SlackClient(web, "C123")
    return client, web


class TestThreadRouterInit:
    def test_init_with_slack_client(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        assert router.channel_id == "C123"

    def test_init_no_active_thread(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        assert router.active_thread_ts is None
        assert router.active_thread_ref is None

    def test_init_no_subagent_threads(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        assert router.subagent_threads == {}

    def test_client_is_private(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        assert not hasattr(router, "client")
        assert hasattr(router, "_client")


class TestThreadRouterActiveThread:
    def test_set_active_thread(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        ref = MessageRef(channel_id="C123", ts="9999.0")
        router.set_active_thread("9999.0", ref)
        assert router.active_thread_ts == "9999.0"
        assert router.active_thread_ref == ref

    def test_clear_active_thread(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        ref = MessageRef(channel_id="C123", ts="9999.0")
        router.set_active_thread("9999.0", ref)
        router.clear_active_thread()
        assert router.active_thread_ts is None
        assert router.active_thread_ref is None


class TestThreadRouterStartTurn:
    async def test_start_turn_posts_message(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        ts = await router.start_turn(1)
        assert ts == "1234567890.123456"
        web.chat_postMessage.assert_called_once()
        text = web.chat_postMessage.call_args.kwargs["text"]
        assert "Turn 1" in text

    async def test_start_turn_sets_active_thread(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        ts = await router.start_turn(1)
        assert router.active_thread_ts == ts

    async def test_start_turn_resets_tool_count(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        router.record_tool_call("Read", {"file_path": "/src/main.py"})
        await router.start_turn(2)
        assert router._tool_call_count == 0

    async def test_start_turn_resets_files_touched(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        router.record_tool_call("Read", {"file_path": "/src/main.py"})
        await router.start_turn(2)
        assert router._files_touched == []

    async def test_start_turn_sets_turn_number(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        await router.start_turn(5)
        assert router._current_turn_number == 5


class TestThreadRouterUpdateTurnSummary:
    async def test_update_turn_summary_updates_message(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.start_turn(1)
        await router.update_turn_summary("2 tool calls · config.py")
        web.chat_update.assert_called_once()
        call_kwargs = web.chat_update.call_args.kwargs
        assert "Turn 1" in call_kwargs["text"]
        assert "2 tool calls · config.py" in call_kwargs["text"]

    async def test_update_turn_summary_no_op_when_no_turn(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        # Should not raise
        await router.update_turn_summary("summary")
        web.chat_update.assert_not_called()


class TestThreadRouterPostToMain:
    async def test_post_to_main_no_thread_ts(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.post_to_main("Hello world")
        call_kwargs = web.chat_postMessage.call_args.kwargs
        assert call_kwargs.get("thread_ts") is None

    async def test_post_to_main_returns_message_ref(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        ref = await router.post_to_main("text")
        assert isinstance(ref, MessageRef)
        assert ref.ts == "1234567890.123456"

    async def test_post_to_main_with_blocks(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        blocks = [{"type": "divider"}]
        await router.post_to_main("text", blocks=blocks, raw=True)
        call_kwargs = web.chat_postMessage.call_args.kwargs
        assert call_kwargs["blocks"] == blocks


class TestThreadRouterPostToActiveThread:
    async def test_post_to_active_thread_with_active_turn(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.start_turn(1)
        await router.post_to_active_thread("Reply in thread")
        call_kwargs = web.chat_postMessage.call_args.kwargs
        assert call_kwargs["thread_ts"] == "1234567890.123456"

    async def test_post_to_active_thread_falls_back_to_main(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.post_to_active_thread("Text")
        call_kwargs = web.chat_postMessage.call_args.kwargs
        assert call_kwargs.get("thread_ts") is None

    async def test_post_to_active_thread_returns_message_ref(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        await router.start_turn(1)
        ref = await router.post_to_active_thread("Text")
        assert isinstance(ref, MessageRef)

    async def test_post_to_turn_thread_alias(self):
        """post_to_turn_thread should be an alias for post_to_active_thread."""
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.start_turn(1)
        await router.post_to_turn_thread("alias text")
        call_kwargs = web.chat_postMessage.call_args.kwargs
        assert call_kwargs["thread_ts"] == "1234567890.123456"


class TestThreadRouterPostToSubagentThread:
    async def test_post_to_subagent_thread_with_matching_id(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.start_subagent_thread("task_123", "Running analysis")
        await router.post_to_subagent_thread("task_123", "Subagent response")
        call_kwargs = web.chat_postMessage.call_args.kwargs
        assert call_kwargs["thread_ts"] == "1234567890.123456"

    async def test_post_to_subagent_thread_falls_back_to_active(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.start_turn(1)
        await router.post_to_subagent_thread("unknown_id", "Text")
        call_kwargs = web.chat_postMessage.call_args.kwargs
        assert call_kwargs["thread_ts"] == "1234567890.123456"


class TestThreadRouterStartSubagentThread:
    async def test_start_subagent_thread_creates_message(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        ts = await router.start_subagent_thread("task_123", "Running analysis")
        assert ts == "1234567890.123456"
        text = web.chat_postMessage.call_args.kwargs["text"]
        assert "Subagent" in text
        assert "Running analysis" in text

    async def test_start_subagent_thread_tracks_by_tool_id(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        ts = await router.start_subagent_thread("task_123", "Description")
        assert router.subagent_threads["task_123"] == ts

    async def test_start_subagent_thread_evicts_when_over_limit(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        # Fill to the limit
        for i in range(100):
            router.subagent_threads[f"task_{i}"] = f"ts_{i}"
        # Adding one more should trigger eviction
        await router.start_subagent_thread("task_new", "New")
        assert len(router.subagent_threads) <= 51  # 50 remaining + 1 new


class TestThreadRouterUpdateMessage:
    async def test_update_message_channel_bound(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.update_message("9999.0", "Updated text")
        web.chat_update.assert_called_once()
        call_kwargs = web.chat_update.call_args.kwargs
        assert call_kwargs["ts"] == "9999.0"
        assert call_kwargs["text"] == "Updated text"
        assert call_kwargs["channel"] == "C123"


class TestThreadRouterReact:
    async def test_react_channel_bound(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.react("9999.0", "white_check_mark")
        web.reactions_add.assert_called_once()
        call_kwargs = web.reactions_add.call_args.kwargs
        assert call_kwargs["timestamp"] == "9999.0"
        assert call_kwargs["name"] == "white_check_mark"
        assert call_kwargs["channel"] == "C123"

    async def test_react_strips_colons(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.react("9999.0", ":thumbsup:")
        call_kwargs = web.reactions_add.call_args.kwargs
        assert call_kwargs["name"] == "thumbsup"


class TestThreadRouterUploadToActiveThread:
    async def test_upload_to_active_thread(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.start_turn(1)
        await router.upload_to_active_thread("content", "file.txt")
        web.files_upload_v2.assert_called_once()
        call_kwargs = web.files_upload_v2.call_args.kwargs
        assert call_kwargs["content"] == "content"
        assert call_kwargs["filename"] == "file.txt"
        assert call_kwargs["thread_ts"] == "1234567890.123456"

    async def test_upload_to_turn_thread_alias(self):
        """upload_to_turn_thread should be an alias for upload_to_active_thread."""
        client, web = make_mock_client()
        router = ThreadRouter(client)
        await router.start_turn(1)
        await router.upload_to_turn_thread("content", "file.txt")
        web.files_upload_v2.assert_called_once()


class TestThreadRouterPermissionEphemeral:
    async def test_post_permission_ephemeral_calls_client(self):
        client, web = make_mock_client()
        router = ThreadRouter(client)
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Approve?"}}]
        await router.post_permission_ephemeral("U456", "Permission needed", blocks)
        web.chat_postEphemeral.assert_called_once()
        call_kwargs = web.chat_postEphemeral.call_args.kwargs
        assert call_kwargs["user"] == "U456"
        assert call_kwargs["channel"] == "C123"
        assert call_kwargs["text"] == "Permission needed"
        assert call_kwargs["blocks"] == blocks


class TestThreadRouterRecordToolCall:
    def test_increments_count(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        router.record_tool_call("Read", {"file_path": "/src/main.py"})
        assert router._tool_call_count == 1

    def test_extracts_file_paths(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        router.record_tool_call("Read", {"file_path": "/src/main.py"})
        assert "/src/main.py" in router._files_touched

    def test_deduplicates_files(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        router.record_tool_call("Read", {"file_path": "/src/main.py"})
        router.record_tool_call("Read", {"file_path": "/src/main.py"})
        assert router._files_touched.count("/src/main.py") == 1

    def test_ignores_non_path_keys(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        router.record_tool_call("Bash", {"command": "git status"})
        assert len(router._files_touched) == 0


class TestThreadRouterGenerateTurnSummary:
    def test_includes_tool_count(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        router.record_tool_call("Read", {"file_path": "/src/main.py"})
        router.record_tool_call("Edit", {"path": "/src/config.py"})
        summary = router.generate_turn_summary()
        assert "2 tool calls" in summary

    def test_singular_tool(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        router.record_tool_call("Read", {"file_path": "/src/main.py"})
        summary = router.generate_turn_summary()
        assert "1 tool call" in summary

    def test_includes_file_names(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        router.record_tool_call("Read", {"file_path": "/src/main.py"})
        summary = router.generate_turn_summary()
        assert "main.py" in summary

    def test_limits_files_to_3(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        for i in range(5):
            router.record_tool_call("Read", {"file_path": f"/src/file{i}.py"})
        summary = router.generate_turn_summary()
        assert "+2 more" in summary

    def test_no_tools_returns_processing(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        summary = router.generate_turn_summary()
        assert summary == "Processing..."

    def test_uses_separator(self):
        client, _ = make_mock_client()
        router = ThreadRouter(client)
        router.record_tool_call("Read", {"file_path": "/src/main.py"})
        router.record_tool_call("Edit", {"path": "/src/config.py"})
        summary = router.generate_turn_summary()
        assert " · " in summary
