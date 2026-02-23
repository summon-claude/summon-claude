"""Tests for summon_claude.channel_manager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from helpers import make_mock_provider
from summon_claude.channel_manager import ChannelManager, _get_git_branch, _slugify
from summon_claude.providers.base import ChannelRef, MessageRef


class TestChannelManagerCreateChannel:
    async def test_create_returns_channel_id_and_name(self):
        provider = make_mock_provider()
        provider.create_channel = AsyncMock(
            return_value=ChannelRef(channel_id="C_TEST_123", name="summon-test-0101")
        )
        mgr = ChannelManager(provider, channel_prefix="summon")
        channel_id, channel_name = await mgr.create_session_channel("my-feature")
        assert channel_id == "C_TEST_123"
        assert channel_name == "summon-test-0101"
        provider.create_channel.assert_called_once()

    async def test_channel_name_includes_prefix(self):
        provider = make_mock_provider()
        mgr = ChannelManager(provider, channel_prefix="sc")
        await mgr.create_session_channel("auth-fix")
        call_args = provider.create_channel.call_args[0]
        name = call_args[0]
        assert name.startswith("sc-")

    async def test_channel_name_is_lowercase(self):
        provider = make_mock_provider()
        mgr = ChannelManager(provider)
        await mgr.create_session_channel("MyFeature")
        call_args = provider.create_channel.call_args[0]
        name = call_args[0]
        assert name == name.lower()

    async def test_channel_name_truncated_to_80_chars(self):
        provider = make_mock_provider()
        mgr = ChannelManager(provider)
        long_name = "x" * 200
        await mgr.create_session_channel(long_name)
        call_args = provider.create_channel.call_args[0]
        name = call_args[0]
        assert len(name) <= 80

    async def test_name_collision_retries_with_counter(self):
        provider = make_mock_provider()
        # First call raises (name taken), second succeeds
        provider.create_channel = AsyncMock(
            side_effect=[
                Exception("name_taken"),
                ChannelRef(channel_id="C_RETRY_456", name="summon-test-1"),
            ]
        )
        mgr = ChannelManager(provider)
        channel_id, channel_name = await mgr.create_session_channel("existing")
        assert channel_id == "C_RETRY_456"
        assert channel_name == "summon-test-1"
        assert provider.create_channel.call_count == 2

    async def test_second_attempt_has_numeric_suffix(self):
        provider = make_mock_provider()
        provider.create_channel = AsyncMock(
            side_effect=[
                Exception("name_taken"),
                ChannelRef(channel_id="C_OK", name="summon-test-1"),
            ]
        )
        mgr = ChannelManager(provider)
        await mgr.create_session_channel("test")
        second_call_name = provider.create_channel.call_args_list[1][0][0]
        assert second_call_name.endswith("-1")

    async def test_other_api_error_raises(self):
        provider = make_mock_provider()
        provider.create_channel = AsyncMock(side_effect=Exception("not_authed"))
        mgr = ChannelManager(provider)
        with pytest.raises(Exception, match="not_authed"):
            await mgr.create_session_channel("test")


class TestChannelManagerArchive:
    async def test_archive_posts_message_and_archives(self):
        provider = make_mock_provider()
        mgr = ChannelManager(provider)
        await mgr.archive_session_channel("C_ARCH_123")
        provider.post_message.assert_called_once()
        provider.archive_channel.assert_called_once_with("C_ARCH_123")

    async def test_archive_error_is_swallowed(self):
        provider = make_mock_provider()
        provider.archive_channel = AsyncMock(side_effect=Exception("network error"))
        mgr = ChannelManager(provider)
        # Should not raise
        await mgr.archive_session_channel("C_ARCH_ERR")


class TestChannelManagerPostHeader:
    async def test_post_header_returns_timestamp(self):
        provider = make_mock_provider()
        provider.post_message = AsyncMock(
            return_value=MessageRef(channel_id="C_HEADER", ts="9999.0001")
        )
        mgr = ChannelManager(provider)
        ts = await mgr.post_session_header(
            "C_HEADER",
            {"cwd": "/tmp", "model": "claude-opus-4-6", "session_id": "abc123"},
        )
        assert ts == "9999.0001"

    async def test_post_header_includes_cwd_in_blocks(self):
        provider = make_mock_provider()
        mgr = ChannelManager(provider)
        await mgr.post_session_header("C_H", {"cwd": "/my/project", "session_id": "x"})
        call_kwargs = provider.post_message.call_args[1]
        blocks = call_kwargs.get("blocks", [])
        blocks_str = str(blocks)
        assert "/my/project" in blocks_str

    async def test_post_header_includes_model(self):
        provider = make_mock_provider()
        mgr = ChannelManager(provider)
        await mgr.post_session_header(
            "C_H2", {"cwd": "/tmp", "model": "claude-sonnet-4-5", "session_id": "y"}
        )
        call_kwargs = provider.post_message.call_args[1]
        blocks = call_kwargs.get("blocks", [])
        blocks_str = str(blocks)
        assert "claude-sonnet-4-5" in blocks_str


class TestMakeChannelName:
    def test_name_format(self):
        mgr = ChannelManager(make_mock_provider(), channel_prefix="summon")
        name = mgr._make_channel_name("auth-refactor")
        # Should be summon-auth-refactor-MMDD
        assert name.startswith("summon-auth-refactor-")

    def test_empty_session_name_defaults_to_session(self):
        mgr = ChannelManager(make_mock_provider())
        name = mgr._make_channel_name("")
        assert "session" in name

    def test_max_length_enforced(self):
        mgr = ChannelManager(make_mock_provider())
        name = mgr._make_channel_name("x" * 200)
        assert len(name) <= 80


class TestSlugify:
    def test_spaces_become_hyphens(self):
        assert _slugify("my feature branch") == "my-feature-branch"

    def test_uppercase_lowercased(self):
        assert _slugify("MyFeature") == "myfeature"

    def test_special_chars_replaced(self):
        # Trailing special chars get stripped along with resulting trailing hyphens
        result = _slugify("fix/auth_bug!")
        assert "fix" in result
        assert "auth" in result
        assert "bug" in result
        assert result == result.lower()

    def test_consecutive_hyphens_collapsed(self):
        assert _slugify("foo--bar") == "foo-bar"

    def test_leading_trailing_hyphens_stripped(self):
        assert _slugify("--foo--") == "foo"

    def test_empty_string_returns_session(self):
        assert _slugify("") == "session"

    def test_all_special_chars_returns_session(self):
        assert _slugify("!!!") == "session"


class TestGetGitBranch:
    def test_returns_branch_name_in_git_repo(self):
        # The test itself runs inside a git repo
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True
        )
        if result.returncode == 0:
            expected = result.stdout.strip() or None
            branch = _get_git_branch(str(Path.cwd()))
            if expected and expected != "HEAD":
                assert branch == expected

    def test_returns_none_for_non_repo(self, tmp_path):
        branch = _get_git_branch(str(tmp_path))
        assert branch is None

    def test_returns_none_for_nonexistent_dir(self):
        branch = _get_git_branch("/nonexistent/path/xyz")
        assert branch is None
