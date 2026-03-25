"""Tests for Global PM Core: config, cross-channel posting, system prompt, channel setup, auto-create.

Covers M5 Track A (global-pm.md Tasks 3, 5, 6, 7, 8).
"""  # noqa: E501

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from summon_claude.config import SummonConfig, get_reports_dir
from summon_claude.sessions.session import (
    _GLOBAL_PM_SYSTEM_PROMPT_APPEND,
    SessionOptions,
    SummonSession,
    build_global_pm_system_prompt,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(**overrides) -> SummonConfig:
    defaults = {
        "slack_bot_token": "xoxb-test-token",
        "slack_app_token": "xapp-test-token",
        "slack_signing_secret": "abc123def456",
    }
    defaults.update(overrides)
    return SummonConfig.model_validate(defaults)


def make_gpm_session(**option_overrides) -> SummonSession:
    defaults = dict(
        cwd="/tmp/gpm",
        name="global-pm",
        pm_profile=True,
        global_pm_profile=True,
    )
    defaults.update(option_overrides)
    options = SessionOptions(**defaults)
    config = make_config()
    session = SummonSession(
        config=config,
        options=options,
        auth=None,
        session_id="gpm-test-id",
        web_client=AsyncMock(),
        dispatcher=MagicMock(),
        bot_user_id="B001",
    )
    return session


def make_manager(**config_overrides):
    """Create a SessionManager stub for testing _resume_or_start_global_pm."""
    from summon_claude.sessions.manager import SessionManager

    config = make_config(**config_overrides)
    manager = SessionManager.__new__(SessionManager)
    manager._config = config
    manager._sessions = {}
    manager._tasks = {}
    manager._web_client = AsyncMock()
    manager._dispatcher = MagicMock()
    manager._bot_user_id = "B001"
    manager._ipc_resume = AsyncMock()
    manager.create_session_with_spawn_token = AsyncMock()
    manager._grace_timer = None
    manager._resuming_channels = set()
    return manager


# ---------------------------------------------------------------------------
# C1: Config tests
# ---------------------------------------------------------------------------


class TestGlobalPMConfig:
    def test_default_values(self):
        config = make_config()
        assert config.global_pm_scan_interval_minutes == 15
        assert config.global_pm_cwd is None
        assert config.global_pm_model is None

    def test_env_var_parsing(self):
        config = make_config(
            global_pm_scan_interval_minutes=30,
            global_pm_cwd="/custom/path",
            global_pm_model="haiku",
        )
        assert config.global_pm_scan_interval_minutes == 30
        assert config.global_pm_cwd == "/custom/path"
        assert config.global_pm_model == "haiku"

    def test_scan_interval_minimum(self):
        with pytest.raises(ValueError, match="at least 1"):
            make_config(global_pm_scan_interval_minutes=0)

    def test_cwd_must_be_absolute(self):
        with pytest.raises(ValueError, match="absolute path"):
            make_config(global_pm_cwd="relative/path")

    def test_cwd_absolute_accepted(self):
        config = make_config(global_pm_cwd="/absolute/path")
        assert config.global_pm_cwd == "/absolute/path"

    def test_cwd_none_accepted(self):
        config = make_config(global_pm_cwd=None)
        assert config.global_pm_cwd is None

    def test_reports_dir_under_data_dir(self):
        from summon_claude.config import get_data_dir

        reports = get_reports_dir()
        data = get_data_dir()
        assert reports.parent == data
        assert reports.name == "reports"


# ---------------------------------------------------------------------------
# C2: Cross-channel posting tests
# ---------------------------------------------------------------------------


class TestCrossChannelPosting:
    @pytest.mark.asyncio
    async def test_slack_client_post_to_channel(self):
        from summon_claude.slack.client import SlackClient

        mock_web = AsyncMock()
        mock_web.chat_postMessage = AsyncMock(return_value={"channel": "C999", "ts": "1234.5678"})
        client = SlackClient(mock_web, "C001")

        ref = await client.post_to_channel("C999", "Hello cross-channel")
        assert ref.channel_id == "C999"
        assert ref.ts == "1234.5678"
        mock_web.chat_postMessage.assert_called_once_with(
            channel="C999", text="Hello cross-channel"
        )

    @pytest.mark.asyncio
    async def test_post_to_channel_redacts_secrets(self):
        from summon_claude.slack.client import SlackClient

        mock_web = AsyncMock()
        mock_web.chat_postMessage = AsyncMock(return_value={"channel": "C999", "ts": "1234.5678"})
        client = SlackClient(mock_web, "C001")

        await client.post_to_channel("C999", "token: xoxb-secret-123")
        call_text = mock_web.chat_postMessage.call_args[1]["text"]
        assert "[REDACTED]" in call_text
        assert "xoxb-secret" not in call_text

    @pytest.mark.asyncio
    async def test_mcp_tool_not_registered_for_regular_sessions(self):
        from summon_claude.slack.mcp import create_summon_mcp_tools

        client = MagicMock()
        tools = create_summon_mcp_tools(
            client, allowed_channels=AsyncMock(return_value={"C001"}), is_pm=False
        )
        tool_names = [t.name for t in tools]
        assert "slack_post_to_channel" not in tool_names

    @pytest.mark.asyncio
    async def test_mcp_tool_registered_for_pm_sessions(self):
        from summon_claude.slack.mcp import create_summon_mcp_tools

        client = MagicMock()
        tools = create_summon_mcp_tools(
            client, allowed_channels=AsyncMock(return_value={"C001"}), is_pm=True
        )
        tool_names = [t.name for t in tools]
        assert "slack_post_to_channel" in tool_names

    @pytest.mark.asyncio
    async def test_post_to_channel_adds_attribution_prefix(self):
        """[SEC-004] Cross-channel posts must be prefixed with [Global PM]."""
        from summon_claude.slack.mcp import create_summon_mcp_tools

        mock_client = MagicMock()
        mock_client.post_to_channel = AsyncMock(
            return_value=MagicMock(channel_id="C999", ts="1234.5678")
        )
        mock_client.channel_id = "C001"

        async def _allow_all() -> set[str]:
            return {"C001", "C999"}

        tools = create_summon_mcp_tools(mock_client, allowed_channels=_allow_all, is_pm=True)
        post_tool = next(t for t in tools if t.name == "slack_post_to_channel")
        result = await post_tool.handler({"channel_id": "C999", "text": "Fix session X"})
        assert not result.get("is_error")
        # Verify the text passed to post_to_channel has the [Global PM] prefix
        call_text = mock_client.post_to_channel.call_args[0][1]
        assert call_text.startswith("[Global PM] ")
        assert "Fix session X" in call_text


# ---------------------------------------------------------------------------
# C3: System prompt tests
# ---------------------------------------------------------------------------


class TestGlobalPMSystemPrompt:
    def test_prompt_contains_oversight_instructions(self):
        prompt = build_global_pm_system_prompt(reports_dir="/tmp/reports")
        assert prompt["type"] == "preset"
        assert prompt["preset"] == "claude_code"
        assert "Global Project Manager" in prompt["append"]
        assert "Periodic scanning" in prompt["append"]
        assert "Misbehavior detection" in prompt["append"]
        assert "Corrective messaging" in prompt["append"]
        assert "Daily summaries" in prompt["append"]

    def test_prompt_interpolates_reports_dir(self):
        prompt = build_global_pm_system_prompt(reports_dir="/custom/reports")
        assert "/custom/reports" in prompt["append"]
        assert "{reports_dir}" not in prompt["append"]

    def test_prompt_security_section(self):
        prompt = build_global_pm_system_prompt(reports_dir="/tmp/reports")
        text = prompt["append"]
        assert "SECURITY" in text
        assert "DATA to be analyzed" in text
        assert "UNTRUSTED_EXTERNAL_DATA" in text
        assert "session_stop" in text
        assert "genuinely stuck" in text

    def test_prompt_scribe_awareness(self):
        prompt = build_global_pm_system_prompt(reports_dir="/tmp/reports")
        assert "Scribe agent" in prompt["append"]
        assert "0-summon-scribe" in prompt["append"]

    def test_prompt_zzz_channel_awareness(self):
        prompt = build_global_pm_system_prompt(reports_dir="/tmp/reports")
        assert "zzz-" in prompt["append"]

    def test_prompt_tool_inventory(self):
        prompt = build_global_pm_system_prompt(reports_dir="/tmp/reports")
        text = prompt["append"]
        assert "session_list" in text
        assert "session_info" in text
        assert "session_stop" in text
        assert "slack_post_to_channel" in text
        assert "summon_canvas_read" in text
        assert "TaskList" in text
        assert "CronList" in text


# ---------------------------------------------------------------------------
# C3: Profile wiring tests
# ---------------------------------------------------------------------------


class TestGlobalPMProfile:
    def test_is_global_pm_property(self):
        session = make_gpm_session()
        assert session.is_global_pm is True
        assert session.is_pm is True

    def test_regular_session_not_global_pm(self):
        options = SessionOptions(cwd="/tmp", name="test")
        config = make_config()
        session = SummonSession(
            config=config,
            options=options,
            auth=None,
            session_id="regular-test",
            web_client=AsyncMock(),
            dispatcher=MagicMock(),
            bot_user_id="B001",
        )
        assert session.is_global_pm is False
        assert session.is_pm is False

    def test_session_start_excluded_from_gpm_tools(self):
        """Guard test: session_start MUST NOT be in GPM's CLI MCP tool list."""
        import asyncio

        from summon_claude.sessions.scheduler import SessionScheduler
        from summon_claude.summon_cli_mcp import create_summon_cli_mcp_tools

        scheduler = SessionScheduler(asyncio.Queue(), asyncio.Event())
        tools = create_summon_cli_mcp_tools(
            registry=MagicMock(),
            session_id="gpm-test",
            authenticated_user_id="U001",
            channel_id="C001",
            cwd="/tmp",
            is_pm=True,
            is_global_pm=True,
            scheduler=scheduler,
        )
        tool_names = [t.name for t in tools]
        assert "session_start" not in tool_names
        assert "session_message" not in tool_names
        assert "session_stop" in tool_names
        assert "session_resume" in tool_names

    def test_session_start_included_for_regular_pm(self):
        """Guard test: session_start IS in regular PM's CLI MCP tool list."""
        import asyncio

        from summon_claude.sessions.scheduler import SessionScheduler
        from summon_claude.summon_cli_mcp import create_summon_cli_mcp_tools

        scheduler = SessionScheduler(asyncio.Queue(), asyncio.Event())
        tools = create_summon_cli_mcp_tools(
            registry=MagicMock(),
            session_id="pm-test",
            authenticated_user_id="U001",
            channel_id="C001",
            cwd="/tmp",
            is_pm=True,
            is_global_pm=False,
            scheduler=scheduler,
        )
        tool_names = [t.name for t in tools]
        assert "session_start" in tool_names
        assert "session_message" in tool_names


# ---------------------------------------------------------------------------
# C5: Auto-create / SessionManager tests
# ---------------------------------------------------------------------------


class TestGlobalPMAutoCreate:
    @pytest.mark.asyncio
    async def test_start_global_pm_creates_session(self):
        manager = make_manager()
        manager._start_global_pm("U001")

        assert len(manager._sessions) == 1
        session = next(iter(manager._sessions.values()))
        assert session.is_global_pm is True
        assert session.is_pm is True
        assert session.name == "global-pm"

    @pytest.mark.asyncio
    async def test_start_global_pm_skips_if_already_running(self):
        manager = make_manager()
        manager._start_global_pm("U001")
        assert len(manager._sessions) == 1

        existing = next(iter(manager._sessions.values()))
        assert existing.is_global_pm

        # Try to start again — should skip
        with patch.object(manager, "_start_global_pm") as mock_start:
            await manager._resume_or_start_global_pm("U001")
            mock_start.assert_not_called()

    def test_gpm_channel_name(self):
        """Global PM uses hardcoded channel name 0-summon-global-pm."""
        prompt_text = _GLOBAL_PM_SYSTEM_PROMPT_APPEND
        assert "0-summon-global-pm" in prompt_text


# ---------------------------------------------------------------------------
# C8: Daily summary (verification only)
# ---------------------------------------------------------------------------


class TestDailySummary:
    def test_prompt_includes_summary_guidance(self):
        prompt = build_global_pm_system_prompt(reports_dir="/tmp/reports")
        text = prompt["append"]
        assert "Daily summary" in text or "daily summary" in text
        assert "Reports directory" in text
