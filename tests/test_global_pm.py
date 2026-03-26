"""Tests for Global PM Core: config, cross-channel posting, system prompt, channel setup, auto-create.

Covers M5 Track A (global-pm.md Tasks 3, 5, 6, 7, 8).
"""  # noqa: E501

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from summon_claude.config import SummonConfig, get_reports_dir
from summon_claude.sessions.session import (
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
            client, allowed_channels=AsyncMock(return_value={"C001"}), is_global_pm=False
        )
        tool_names = [t.name for t in tools]
        assert "slack_post_to_channel" not in tool_names

    @pytest.mark.asyncio
    async def test_mcp_tool_not_registered_for_project_pm(self):
        """Guard: project PMs must NOT get slack_post_to_channel (GPM-only)."""
        from summon_claude.slack.mcp import create_summon_mcp_tools

        client = MagicMock()
        tools = create_summon_mcp_tools(
            client, allowed_channels=AsyncMock(return_value={"C001"}), is_global_pm=False
        )
        tool_names = [t.name for t in tools]
        assert "slack_post_to_channel" not in tool_names

    @pytest.mark.asyncio
    async def test_mcp_tool_registered_for_global_pm(self):
        from summon_claude.slack.mcp import create_summon_mcp_tools

        client = MagicMock()
        tools = create_summon_mcp_tools(
            client, allowed_channels=AsyncMock(return_value={"C001"}), is_global_pm=True
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

        tools = create_summon_mcp_tools(mock_client, allowed_channels=_allow_all, is_global_pm=True)
        post_tool = next(t for t in tools if t.name == "slack_post_to_channel")
        result = await post_tool.handler({"channel_id": "C999", "text": "Fix session X"})
        assert not result.get("is_error")
        call_text = mock_client.post_to_channel.call_args[0][1]
        from summon_claude.slack.mcp import _GPM_ATTRIBUTION

        assert call_text.startswith(f"{_GPM_ATTRIBUTION} ")
        assert "Fix session X" in call_text

    @pytest.mark.asyncio
    async def test_post_to_channel_rejects_unauthorized_channel(self):
        """Channel scope enforcement: disallowed channels must be rejected."""
        from summon_claude.slack.mcp import create_summon_mcp_tools

        mock_client = MagicMock()
        mock_client.post_to_channel = AsyncMock()
        mock_client.channel_id = "C001"

        async def _limited_scope() -> set[str]:
            return {"C001"}

        tools = create_summon_mcp_tools(
            mock_client, allowed_channels=_limited_scope, is_global_pm=True
        )
        post_tool = next(t for t in tools if t.name == "slack_post_to_channel")
        result = await post_tool.handler({"channel_id": "C_FORBIDDEN", "text": "Hello"})
        assert result.get("is_error") is True
        mock_client.post_to_channel.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_to_channel_missing_channel_id(self):
        from summon_claude.slack.mcp import create_summon_mcp_tools

        mock_client = MagicMock()
        mock_client.channel_id = "C001"
        tools = create_summon_mcp_tools(
            mock_client, allowed_channels=AsyncMock(return_value={"C001"}), is_global_pm=True
        )
        post_tool = next(t for t in tools if t.name == "slack_post_to_channel")
        result = await post_tool.handler({})
        assert result.get("is_error") is True

    @pytest.mark.asyncio
    async def test_post_to_channel_missing_text(self):
        from summon_claude.slack.mcp import create_summon_mcp_tools

        mock_client = MagicMock()
        mock_client.channel_id = "C001"

        async def _allow_all() -> set[str]:
            return {"C001", "C999"}

        tools = create_summon_mcp_tools(mock_client, allowed_channels=_allow_all, is_global_pm=True)
        post_tool = next(t for t in tools if t.name == "slack_post_to_channel")
        result = await post_tool.handler({"channel_id": "C999", "text": ""})
        assert result.get("is_error") is True


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
    async def test_start_global_pm_passes_channel_id(self):
        """When channel_id is provided, it's set on SessionOptions for channel reuse."""
        manager = make_manager()
        manager._start_global_pm("U001", channel_id="C_PREV")

        session = next(iter(manager._sessions.values()))
        assert session._channel_id_option == "C_PREV"

    @pytest.mark.asyncio
    async def test_start_global_pm_skips_if_already_running(self):
        manager = make_manager()
        manager._start_global_pm("U001")
        assert len(manager._sessions) == 1

        existing = next(iter(manager._sessions.values()))
        assert existing.is_global_pm

        # Try to start again — should skip (never reaches _start_global_pm or registry)
        with (
            patch.object(manager, "_start_global_pm") as mock_start,
            patch("summon_claude.sessions.manager.SessionRegistry") as mock_reg_cls,
        ):
            await manager._resume_or_start_global_pm("U001")
            mock_start.assert_not_called()
            mock_reg_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_suspended_gpm(self):
        """_resume_or_start_global_pm resumes a suspended GPM from the DB."""
        manager = make_manager()
        mock_registry = AsyncMock()
        suspended_row = {
            "session_id": "gpm-suspended-id",
            "session_name": "global-pm",
            "status": "suspended",
            "project_id": None,
            "slack_channel_id": "C_GPM",
            "claude_session_id": "claude-123",
            "cwd": "/tmp/gpm",
        }

        # Mock the DB cursor for the suspended query
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=suspended_row)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db.execute = MagicMock(return_value=mock_cursor)
        mock_registry.db = mock_db
        mock_registry.get_channel = AsyncMock(return_value={"claude_session_id": "claude-123"})
        mock_registry.update_status = AsyncMock()
        mock_registry.__aenter__ = AsyncMock(return_value=mock_registry)
        mock_registry.__aexit__ = AsyncMock(return_value=False)

        manager.create_resumed_session = AsyncMock(return_value="new-gpm-id")
        manager._check_channel_available = MagicMock()

        with patch("summon_claude.sessions.manager.SessionRegistry", return_value=mock_registry):
            await manager._resume_or_start_global_pm("U001")

        manager.create_resumed_session.assert_called_once()
        call_opts = manager.create_resumed_session.call_args[0][0]
        assert call_opts.global_pm_profile is True
        assert call_opts.channel_id == "C_GPM"
        assert call_opts.resume == "claude-123"
        mock_registry.update_status.assert_called_with("gpm-suspended-id", "completed")

    @pytest.mark.asyncio
    async def test_resume_failure_marks_errored_and_starts_fresh(self):
        """If resume fails, old session is marked errored and fresh GPM starts."""
        manager = make_manager()
        mock_registry = AsyncMock()

        # First cursor: suspended query returns a row
        suspended_row = {
            "session_id": "gpm-fail-id",
            "session_name": "global-pm",
            "status": "suspended",
            "project_id": None,
            "slack_channel_id": "C_GPM",
            "claude_session_id": None,
            "cwd": "/tmp/gpm",
        }
        mock_cursor_suspended = AsyncMock()
        mock_cursor_suspended.fetchone = AsyncMock(return_value=suspended_row)
        mock_cursor_suspended.__aenter__ = AsyncMock(return_value=mock_cursor_suspended)
        mock_cursor_suspended.__aexit__ = AsyncMock(return_value=False)

        # Second cursor: prev channel query
        mock_cursor_prev = AsyncMock()
        mock_cursor_prev.fetchone = AsyncMock(return_value={"slack_channel_id": "C_GPM"})
        mock_cursor_prev.__aenter__ = AsyncMock(return_value=mock_cursor_prev)
        mock_cursor_prev.__aexit__ = AsyncMock(return_value=False)

        call_count = 0

        def _execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_cursor_suspended
            return mock_cursor_prev

        mock_db = AsyncMock()
        mock_db.execute = MagicMock(side_effect=_execute_side_effect)
        mock_registry.db = mock_db
        mock_registry.get_channel = AsyncMock(return_value=None)
        mock_registry.update_status = AsyncMock()
        mock_registry.__aenter__ = AsyncMock(return_value=mock_registry)
        mock_registry.__aexit__ = AsyncMock(return_value=False)

        manager.create_resumed_session = AsyncMock(side_effect=RuntimeError("resume failed"))
        manager._check_channel_available = MagicMock()

        with patch("summon_claude.sessions.manager.SessionRegistry", return_value=mock_registry):
            await manager._resume_or_start_global_pm("U001")

        # Old session marked errored
        mock_registry.update_status.assert_any_call(
            "gpm-fail-id", "errored", error_message="Resume failed: resume failed"
        )
        # Fresh GPM started
        assert len(manager._sessions) == 1
        session = next(iter(manager._sessions.values()))
        assert session.is_global_pm

    def test_gpm_channel_name(self):
        """Global PM uses hardcoded channel name 0-summon-global-pm."""
        prompt = build_global_pm_system_prompt(reports_dir="/tmp/reports")
        assert "0-summon-global-pm" in prompt["append"]

    def test_resolve_gpm_cwd(self):
        """_resolve_gpm_cwd uses config, fallback, and creates directory."""
        manager = make_manager(global_pm_cwd="/custom/gpm")
        with patch("summon_claude.sessions.manager.pathlib.Path.mkdir"):
            cwd = manager._resolve_gpm_cwd()
        assert cwd == "/custom/gpm"

    def test_resolve_gpm_cwd_suspended_takes_priority(self):
        manager = make_manager(global_pm_cwd="/config/path")
        with patch("summon_claude.sessions.manager.pathlib.Path.mkdir"):
            cwd = manager._resolve_gpm_cwd("/suspended/path")
        assert cwd == "/suspended/path"


# ---------------------------------------------------------------------------
# C5b: Channel security tests (sec-3)
# ---------------------------------------------------------------------------


class TestGPMChannelCreatorCheck:
    """[SEC-003] GPM channel discovery must verify bot created the channel."""

    @pytest.mark.asyncio
    async def test_skips_channel_created_by_other_user(self):
        session = make_gpm_session()
        mock_web = AsyncMock()
        # Channel exists but was created by a different user
        mock_web.conversations_list = AsyncMock(
            return_value={
                "channels": [
                    {"id": "C_HIJACK", "name": "0-summon-global-pm", "creator": "U_ATTACKER"}
                ],
                "response_metadata": {},
            }
        )
        # After skipping the hijacked channel, should create a new one
        mock_web.conversations_create = AsyncMock(
            return_value={"channel": {"id": "C_NEW", "name": "0-summon-global-pm"}}
        )

        channel_id, channel_name = await session._get_or_create_global_pm_channel(mock_web)
        assert channel_id == "C_NEW"
        # conversations_join should NOT have been called on the hijacked channel
        mock_web.conversations_join.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_channel_created_by_bot(self):
        session = make_gpm_session()
        mock_web = AsyncMock()
        # Channel was created by the bot
        mock_web.conversations_list = AsyncMock(
            return_value={
                "channels": [{"id": "C_OURS", "name": "0-summon-global-pm", "creator": "B001"}],
                "response_metadata": {},
            }
        )
        mock_web.conversations_join = AsyncMock()

        channel_id, channel_name = await session._get_or_create_global_pm_channel(mock_web)
        assert channel_id == "C_OURS"
        mock_web.conversations_join.assert_called_once_with(channel="C_OURS")


# ---------------------------------------------------------------------------
# C6: CLI command tests
# ---------------------------------------------------------------------------


class TestGlobalPMCLI:
    @pytest.mark.asyncio
    async def test_global_status_running(self):
        from summon_claude.cli.project import async_global_status

        mock_registry = AsyncMock()
        mock_registry.list_active = AsyncMock(
            return_value=[
                {"session_id": "gpm-1234", "session_name": "global-pm", "project_id": None}
            ]
        )
        mock_registry.__aenter__ = AsyncMock(return_value=mock_registry)
        mock_registry.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_registry),
            patch("summon_claude.cli.project.click") as mock_click,
            patch("summon_claude.cli.formatting.print_session_detail"),
        ):
            await async_global_status()
            mock_click.echo.assert_any_call("Global PM: running")

    @pytest.mark.asyncio
    async def test_global_status_not_running(self):
        from summon_claude.cli.project import async_global_status

        mock_registry = AsyncMock()
        mock_registry.list_active = AsyncMock(return_value=[])
        mock_registry.__aenter__ = AsyncMock(return_value=mock_registry)
        mock_registry.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_registry),
            patch("summon_claude.cli.project.click") as mock_click,
        ):
            await async_global_status()
            mock_click.echo.assert_called_with("Global PM: not running")

    @pytest.mark.asyncio
    async def test_global_down_suspends(self):
        """global down must mark GPM as suspended for resume."""
        from summon_claude.cli.project import async_global_down

        mock_registry = AsyncMock()
        mock_registry.list_active = AsyncMock(
            return_value=[
                {"session_id": "gpm-abcd1234", "session_name": "global-pm", "project_id": None}
            ]
        )
        mock_registry.update_status = AsyncMock()
        mock_registry.__aenter__ = AsyncMock(return_value=mock_registry)
        mock_registry.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_registry),
            patch("summon_claude.cli.project.daemon_client") as mock_dc,
            patch("summon_claude.cli.project.click"),
        ):
            mock_dc.stop_session = AsyncMock(return_value=True)
            await async_global_down()
            mock_dc.stop_session.assert_called_once_with("gpm-abcd1234")
            mock_registry.update_status.assert_called_once_with("gpm-abcd1234", "suspended")

    @pytest.mark.asyncio
    async def test_global_down_not_running(self):
        from summon_claude.cli.project import async_global_down

        mock_registry = AsyncMock()
        mock_registry.list_active = AsyncMock(return_value=[])
        mock_registry.__aenter__ = AsyncMock(return_value=mock_registry)
        mock_registry.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_registry),
            patch("summon_claude.cli.project.click") as mock_click,
        ):
            await async_global_down()
            mock_click.echo.assert_called_with("Global PM is not running.")


# ---------------------------------------------------------------------------
# C7: project down GPM suspension
# ---------------------------------------------------------------------------


class TestProjectDownGPM:
    @pytest.mark.asyncio
    async def test_stop_project_managers_suspends_gpm(self):
        """project down suspends GPM alongside scribe."""
        from summon_claude.cli.project import stop_project_managers

        mock_registry = AsyncMock()
        mock_registry.list_projects = AsyncMock(
            return_value=[{"project_id": "p1", "name": "myproj"}]
        )
        mock_registry.get_project_sessions = AsyncMock(return_value=[])
        mock_registry.list_active = AsyncMock(
            return_value=[
                {
                    "session_id": "gpm-sid",
                    "session_name": "global-pm",
                    "project_id": None,
                    "status": "active",
                }
            ]
        )
        mock_registry.update_status = AsyncMock()
        mock_registry.__aenter__ = AsyncMock(return_value=mock_registry)
        mock_registry.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("summon_claude.cli.project.is_daemon_running", return_value=True),
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_registry),
            patch("summon_claude.cli.project.daemon_client") as mock_dc,
            patch("summon_claude.cli.project.click"),
            patch("summon_claude.cli.project._run_project_hooks", new_callable=AsyncMock),
        ):
            mock_dc.stop_session = AsyncMock(return_value=True)
            result = await stop_project_managers()
            assert "gpm-sid" in result
            mock_registry.update_status.assert_any_call("gpm-sid", "suspended")


# ---------------------------------------------------------------------------
# C8: Daily summary (verification only)
# ---------------------------------------------------------------------------


class TestDailySummary:
    def test_prompt_includes_summary_guidance(self):
        prompt = build_global_pm_system_prompt(reports_dir="/tmp/reports")
        text = prompt["append"]
        assert "Daily summary" in text or "daily summary" in text
        assert "Reports directory" in text
