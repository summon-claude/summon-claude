"""Tests for summon_claude.canvas_mcp — canvas MCP tools."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from summon_claude.canvas_mcp import (
    _CANVAS_MAX_CHARS,
    create_canvas_mcp_server,
    create_canvas_mcp_tools,
)
from summon_claude.sessions.registry import SessionRegistry


@pytest.fixture
async def populated_registry(registry: SessionRegistry) -> SessionRegistry:
    """Registry with sample sessions for canvas testing."""
    await registry.register(
        session_id="parent-1111",
        pid=os.getpid(),
        cwd="/home/user/proj",
        name="parent-session",
        authenticated_user_id="U_OWNER",
    )
    await registry.update_status(
        "parent-1111",
        "active",
        slack_channel_id="C100",
        slack_channel_name="summon-parent",
        authenticated_user_id="U_OWNER",
    )

    await registry.register(
        session_id="child-2222",
        pid=os.getpid(),
        cwd="/home/user/proj",
        name="child-session",
        parent_session_id="parent-1111",
        authenticated_user_id="U_OWNER",
    )
    await registry.update_status(
        "child-2222",
        "active",
        slack_channel_id="C200",
        slack_channel_name="summon-child",
        authenticated_user_id="U_OWNER",
    )
    return registry


@pytest.fixture
def canvas_tools(populated_registry):
    """Tools fixture with a mock CanvasStore."""
    mock_canvas = MagicMock()
    mock_canvas.read = MagicMock(return_value="# My Canvas\n\nContent here.")
    mock_canvas.write = AsyncMock()
    mock_canvas.update_section = AsyncMock()
    return {
        t.name: t
        for t in create_canvas_mcp_tools(
            canvas_store=mock_canvas,
            registry=populated_registry,
            authenticated_user_id="U_OWNER",
            channel_id="C100",
        )
    }, mock_canvas


class TestCanvasMCPServerCreation:
    def test_returns_valid_config(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        config = create_canvas_mcp_server(
            canvas_store=mock_canvas,
            registry=MagicMock(),
            authenticated_user_id="uid",
            channel_id="cid",
        )
        assert config["name"] == "summon-canvas"
        assert config["type"] == "sdk"

    def test_tool_count(self, canvas_tools):
        tools, _ = canvas_tools
        assert len(tools) == 3


class TestCanvasRead:
    async def test_reads_own_canvas(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        result = await tools["summon_canvas_read"].handler({})
        assert not result.get("is_error")
        assert "My Canvas" in result["content"][0]["text"]
        mock_canvas.read.assert_called_once()

    async def test_reads_own_canvas_explicit_channel(self, canvas_tools):
        """Passing own channel_id still uses canvas_store.read()."""
        tools, mock_canvas = canvas_tools
        result = await tools["summon_canvas_read"].handler({"channel": "C100"})
        assert not result.get("is_error")
        mock_canvas.read.assert_called_once()

    async def test_cross_channel_read(self, canvas_tools, populated_registry):
        """Reading another channel uses registry.get_canvas_by_channel."""
        await populated_registry.update_canvas("child-2222", "canvas-x", "# Cross Canvas")
        tools, _mock = canvas_tools
        result = await tools["summon_canvas_read"].handler({"channel": "C200"})
        assert not result.get("is_error")
        assert "Cross Canvas" in result["content"][0]["text"]

    async def test_cross_channel_not_found(self, canvas_tools):
        tools, _mock = canvas_tools
        result = await tools["summon_canvas_read"].handler({"channel": "C_NONEXISTENT"})
        assert result["is_error"] is True
        assert "No canvas found" in result["content"][0]["text"]

    async def test_cross_channel_read_blocked_for_different_owner(
        self, canvas_tools, populated_registry
    ):
        """Cross-channel canvas read is blocked when the canvas owner differs from caller."""
        await populated_registry.register(
            "other-cc", os.getpid(), "/tmp", name="other-cc", authenticated_user_id="U_OTHER"
        )
        await populated_registry.update_status(
            "other-cc", "active", slack_channel_id="C_OTHER", authenticated_user_id="U_OTHER"
        )
        await populated_registry.update_canvas("other-cc", "F_OTHER", "# Secret")
        tools, _mock = canvas_tools
        result = await tools["summon_canvas_read"].handler({"channel": "C_OTHER"})
        assert result["is_error"] is True
        assert "No canvas found" in result["content"][0]["text"]


class TestCanvasWrite:
    async def test_writes_content(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        result = await tools["summon_canvas_write"].handler({"markdown": "# New Content"})
        assert not result.get("is_error")
        mock_canvas.write.assert_called_once_with("# New Content")

    async def test_empty_content_rejected(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        result = await tools["summon_canvas_write"].handler({"markdown": ""})
        assert result["is_error"] is True
        assert "required" in result["content"][0]["text"].lower()
        mock_canvas.write.assert_not_called()

    async def test_whitespace_only_rejected(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        result = await tools["summon_canvas_write"].handler({"markdown": "   \n\n  "})
        assert result["is_error"] is True
        assert "required" in result["content"][0]["text"].lower()
        mock_canvas.write.assert_not_called()

    async def test_oversized_content_rejected(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        big_content = "x" * (_CANVAS_MAX_CHARS + 1)
        result = await tools["summon_canvas_write"].handler({"markdown": big_content})
        assert result["is_error"] is True
        assert "100K character limit" in result["content"][0]["text"]
        mock_canvas.write.assert_not_called()

    async def test_exactly_max_size_allowed(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        max_content = "x" * _CANVAS_MAX_CHARS
        result = await tools["summon_canvas_write"].handler({"markdown": max_content})
        assert not result.get("is_error")
        mock_canvas.write.assert_called_once()


class TestCanvasUpdateSection:
    async def test_updates_section(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        result = await tools["summon_canvas_update_section"].handler(
            {"heading": "Current Task", "markdown": "Working on feature X"}
        )
        assert not result.get("is_error")
        assert "Current Task" in result["content"][0]["text"]
        mock_canvas.update_section.assert_called_once_with("Current Task", "Working on feature X")

    async def test_empty_heading_rejected(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        result = await tools["summon_canvas_update_section"].handler(
            {"heading": "", "markdown": "some content"}
        )
        assert result["is_error"] is True
        mock_canvas.update_section.assert_not_called()

    async def test_hash_only_heading_raises_value_error(self, canvas_tools):
        """canvas_store.update_section raises ValueError for heading that strips to empty."""
        tools, mock_canvas = canvas_tools
        mock_canvas.update_section = AsyncMock(side_effect=ValueError("empty heading"))
        result = await tools["summon_canvas_update_section"].handler(
            {"heading": "###", "markdown": "content"}
        )
        assert result["is_error"] is True

    async def test_missing_heading_param(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        result = await tools["summon_canvas_update_section"].handler({"markdown": "content"})
        assert result["is_error"] is True
        mock_canvas.update_section.assert_not_called()

    async def test_oversized_section_content_rejected(self, canvas_tools):
        tools, mock_canvas = canvas_tools
        big_content = "x" * (_CANVAS_MAX_CHARS + 1)
        result = await tools["summon_canvas_update_section"].handler(
            {"heading": "Notes", "markdown": big_content}
        )
        assert result["is_error"] is True
        assert "100K character limit" in result["content"][0]["text"]
        mock_canvas.update_section.assert_not_called()
