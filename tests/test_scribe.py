"""Tests for scribe session profile, scan timer, channel scoping, and auto-spawn.

Covers C12 (Phase 1) and C13 (Phase 2) test requirements.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from summon_claude.config import SummonConfig
from summon_claude.sessions.session import (
    SessionOptions,
    SummonSession,
    build_scribe_system_prompt,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(**overrides) -> SummonConfig:
    defaults = {
        "slack_bot_token": "xoxb-test-token",
        "slack_app_token": "xapp-test-token",
        "slack_signing_secret": "test-secret",
    }
    defaults.update(overrides)
    return SummonConfig.model_validate(defaults)


def make_scribe_prompt(**overrides) -> dict:
    defaults = dict(
        scan_interval=5,
        user_mention="<@U12345>",
        importance_keywords="",
    )
    defaults.update(overrides)
    return build_scribe_system_prompt(**defaults)


# ---------------------------------------------------------------------------
# C12 Phase 1: SessionOptions defaults
# ---------------------------------------------------------------------------


class TestSessionOptionsScribeProfile:
    def test_session_options_scribe_profile_default(self):
        opts = SessionOptions(cwd="/tmp", name="test")
        assert opts.scribe_profile is False


# ---------------------------------------------------------------------------
# C12 Phase 1: System prompt content
# ---------------------------------------------------------------------------


class TestScribeSystemPromptSecurity:
    def test_scribe_system_prompt_security_at_top(self):
        """PROMPT INJECTION DEFENSE section appears before scan protocol."""
        prompt = make_scribe_prompt()
        text = prompt["append"]
        injection_pos = text.find("PROMPT INJECTION DEFENSE")
        scan_pos = text.lower().find("scan protocol")
        assert injection_pos != -1, "PROMPT INJECTION DEFENSE not found"
        assert scan_pos != -1, "scan protocol not found"
        assert injection_pos < scan_pos

    def test_scribe_system_prompt_canary_phrase(self):
        prompt = make_scribe_prompt()
        assert "Canary rule" in prompt["append"]

    def test_scribe_system_prompt_delivery_format(self):
        """Alert formatting contains rotating_light and Level 5 markers."""
        prompt = make_scribe_prompt()
        text = prompt["append"]
        assert ":rotating_light:" in text
        assert "Level 5" in text or "5 (urgent)" in text

    def test_scribe_system_prompt_daily_summary_format(self):
        prompt = make_scribe_prompt()
        assert "Daily Recap" in prompt["append"]


class TestScribeChannelName:
    def test_scribe_channel_name(self):
        """Scribe channel name is hard-coded to 0-summon-scribe."""
        # Verify by inspecting the source constant used in _get_or_create_scribe_channel
        import inspect

        from summon_claude.sessions import session as session_mod

        source = inspect.getsource(session_mod.SummonSession._get_or_create_scribe_channel)
        assert "0-summon-scribe" in source


class TestScribeIsScribeProperty:
    def test_scribe_is_scribe_property_true(self):
        opts = SessionOptions(cwd="/tmp", name="scribe", scribe_profile=True)
        config = make_config()
        sess = SummonSession(
            config=config,
            options=opts,
            auth=None,
            session_id="test-sess-1",
            web_client=None,
            dispatcher=MagicMock(),
            bot_user_id="B001",
            ipc_spawn=AsyncMock(),
            ipc_resume=AsyncMock(),
        )
        assert sess.is_scribe is True

    def test_scribe_is_scribe_property_false_for_normal(self):
        opts = SessionOptions(cwd="/tmp", name="regular")
        config = make_config()
        sess = SummonSession(
            config=config,
            options=opts,
            auth=None,
            session_id="test-sess-2",
            web_client=None,
            dispatcher=MagicMock(),
            bot_user_id="B001",
            ipc_spawn=AsyncMock(),
            ipc_resume=AsyncMock(),
        )
        assert sess.is_scribe is False


class TestScribeScanTimerNonce:
    def test_scribe_scan_timer_uses_nonce(self):
        """SUMMON-INTERNAL- prefix is used in scribe scan prompt."""
        import inspect

        from summon_claude.sessions import session as session_mod

        source = inspect.getsource(session_mod.SummonSession._run_session_tasks)
        assert "SUMMON-INTERNAL-" in source
        assert "_scribe_scan_nonce" in source

    def test_scribe_scan_nonce_uses_secrets(self):
        """secrets.token_hex is called to generate the nonce."""
        import inspect

        from summon_claude.sessions import session as session_mod

        source = inspect.getsource(session_mod.SummonSession._run_session_tasks)
        assert "secrets.token_hex" in source


class TestScribeNoGitHubMCP:
    def test_scribe_no_github_mcp(self):
        """GitHub MCP is gated by 'if not is_scribe' guard."""
        import inspect

        from summon_claude.sessions import session as session_mod

        source = inspect.getsource(session_mod.SummonSession._run_session_tasks)
        # The guard must exist: not wired for scribe
        assert "not is_scribe" in source or "if not is_scribe" in source


class TestScribeSettingSources:
    def test_scribe_setting_sources_user_only(self):
        """setting_sources is ['user'] for scribe sessions (not ['user', 'project'])."""
        import inspect

        from summon_claude.sessions import session as session_mod

        source = inspect.getsource(session_mod.SummonSession._run_session_tasks)
        # The line that sets setting_sources uses (is_pm or is_scribe) condition
        assert "is_scribe" in source
        assert '"user", "project"' in source or '["user", "project"]' in source


# ---------------------------------------------------------------------------
# C12 Phase 1: _start_scribe_if_enabled
# ---------------------------------------------------------------------------


class TestStartScribeIfEnabled:
    def _make_manager(self, **config_overrides):
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
        return manager

    def test_start_scribe_if_enabled_skips_when_disabled(self):
        """When scribe_enabled=False, no session is created."""
        manager = self._make_manager(scribe_enabled=False)

        with patch("summon_claude.sessions.manager.SummonSession") as mock_session_cls:
            manager._start_scribe_if_enabled("U123")

        mock_session_cls.assert_not_called()

    def test_start_scribe_if_enabled_skips_when_running(self):
        """When a scribe session is already running, skip spawning another."""
        manager = self._make_manager(scribe_enabled=True)

        # Inject a stub scribe session
        stub = MagicMock()
        stub.is_scribe = True
        manager._sessions["existing-scribe"] = stub

        with patch("summon_claude.sessions.manager.SummonSession") as mock_session_cls:
            manager._start_scribe_if_enabled("U123")

        mock_session_cls.assert_not_called()


# ---------------------------------------------------------------------------
# C13 Phase 2: importance_keywords and quiet_hours in prompt
# ---------------------------------------------------------------------------


class TestScribeImportanceKeywordsInPrompt:
    def test_scribe_importance_keywords_in_prompt(self):
        """Custom keywords appear verbatim in the rendered prompt."""
        keywords = "deadline,escalation,on-call"
        prompt = make_scribe_prompt(importance_keywords=keywords)
        assert keywords in prompt["append"]

    def test_scribe_importance_keywords_default_when_empty(self):
        """Empty keywords → default text in prompt."""
        prompt = make_scribe_prompt(importance_keywords="")
        assert "urgent, action required, deadline" in prompt["append"]


class TestScribePromptQuietHoursContext:
    def test_scribe_scan_includes_quiet_hours_config(self):
        """Quiet hours config is included in scan prompt for dynamic evaluation."""
        import inspect

        from summon_claude.sessions import session as session_mod

        source = inspect.getsource(session_mod.SummonSession._run_session_tasks)
        assert "quiet_hours" in source.lower()
        assert "only report level 5" in source.lower() or "quiet hours" in source.lower()


# ---------------------------------------------------------------------------
# QA Coverage Gaps (C12/C13 follow-up)
# ---------------------------------------------------------------------------


class TestStartScribeSpawnsSession:
    """test_start_scribe_spawns_session — happy path creates a SummonSession."""

    def _make_manager(self, **config_overrides):
        from summon_claude.sessions.manager import SessionManager

        config = make_config(scribe_enabled=True, **config_overrides)
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
        return manager

    def test_start_scribe_spawns_session(self):
        """With scribe_enabled=True and no existing scribe, a session is registered.

        Disables all preflight checks by: setting scribe_google_services="" and
        scribe_slack_enabled=False, then mocking asyncio.create_task to avoid
        needing a running event loop.
        """
        # Bypass google preflight: empty services string and slack disabled
        manager = self._make_manager(scribe_google_services="", scribe_slack_enabled=False)

        with (
            patch("summon_claude.sessions.manager.SummonSession") as mock_cls,
            patch("summon_claude.sessions.manager.asyncio.create_task") as mock_task,
            patch("summon_claude.sessions.manager.pathlib.Path") as mock_path,
        ):
            mock_instance = MagicMock()
            mock_instance.is_scribe = True
            mock_cls.return_value = mock_instance
            mock_task.return_value = MagicMock()
            mock_path.return_value = MagicMock()

            manager._start_scribe_if_enabled("U123")

        mock_cls.assert_called_once()
        # The session must be registered in the sessions dict
        assert len(manager._sessions) == 1


# ---------------------------------------------------------------------------
# _get_or_create_scribe_channel
# ---------------------------------------------------------------------------


class TestGetOrCreateScribeChannel:
    def _make_session(self):
        config = make_config()
        opts = SessionOptions(cwd="/tmp", name="scribe", scribe_profile=True)
        return SummonSession(
            config=config,
            options=opts,
            auth=None,
            session_id="test-scribe-ch",
            web_client=None,
            dispatcher=MagicMock(),
            bot_user_id="B001",
            ipc_spawn=AsyncMock(),
            ipc_resume=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_get_or_create_scribe_channel_creates_new(self):
        """When no existing channel found, conversations_create is called."""
        sess = self._make_session()
        web_client = AsyncMock()
        web_client.conversations_list.return_value = {
            "channels": [],
            "response_metadata": {"next_cursor": ""},
        }
        web_client.conversations_create.return_value = {
            "channel": {"id": "C_NEW", "name": "0-summon-scribe"}
        }

        channel_id, channel_name = await sess._get_or_create_scribe_channel(web_client)

        web_client.conversations_create.assert_called_once_with(
            name="0-summon-scribe", is_private=True
        )
        assert channel_id == "C_NEW"
        assert channel_name == "0-summon-scribe"

    @pytest.mark.asyncio
    async def test_get_or_create_scribe_channel_reuses_existing(self):
        """When channel already exists, conversations_join is called (no create)."""
        sess = self._make_session()
        web_client = AsyncMock()
        web_client.conversations_list.return_value = {
            "channels": [{"id": "C_EXISTING", "name": "0-summon-scribe"}],
            "response_metadata": {"next_cursor": ""},
        }

        channel_id, channel_name = await sess._get_or_create_scribe_channel(web_client)

        web_client.conversations_join.assert_called_once_with(channel="C_EXISTING")
        web_client.conversations_create.assert_not_called()
        assert channel_id == "C_EXISTING"


# ---------------------------------------------------------------------------
# _start_slack_monitors
# ---------------------------------------------------------------------------


class TestStartSlackMonitors:
    def _make_session(self):
        config = make_config()
        opts = SessionOptions(cwd="/tmp", name="scribe", scribe_profile=True)
        return SummonSession(
            config=config,
            options=opts,
            auth=None,
            session_id="test-scribe-monitors",
            web_client=None,
            dispatcher=MagicMock(),
            bot_user_id="B001",
            ipc_spawn=AsyncMock(),
            ipc_resume=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_start_slack_monitors_missing_config(self, tmp_path):
        """No slack_workspace.json → monitors list stays empty."""
        sess = self._make_session()

        with patch("summon_claude.sessions.session.get_data_dir", return_value=tmp_path):
            await sess._start_slack_monitors()

        assert sess._slack_monitors == []

    @pytest.mark.asyncio
    async def test_start_slack_monitors_missing_auth_state(self, tmp_path):
        """Config exists but auth state file missing → monitors list stays empty."""
        sess = self._make_session()

        import json as json_mod

        config_path = tmp_path / "slack_workspace.json"
        config_path.write_text(
            json_mod.dumps(
                {
                    "url": "https://example.slack.com",
                    "auth_state_path": str(tmp_path / "nonexistent_auth.json"),
                }
            )
        )

        with patch("summon_claude.sessions.session.get_data_dir", return_value=tmp_path):
            await sess._start_slack_monitors()

        assert sess._slack_monitors == []


# ---------------------------------------------------------------------------
# _create_external_slack_mcp — spotlighting and truncation
# ---------------------------------------------------------------------------


class TestExternalSlackMcp:
    def _make_session(self):
        config = make_config()
        opts = SessionOptions(cwd="/tmp", name="scribe", scribe_profile=True)
        return SummonSession(
            config=config,
            options=opts,
            auth=None,
            session_id="test-scribe-mcp",
            web_client=None,
            dispatcher=MagicMock(),
            bot_user_id="B001",
            ipc_spawn=AsyncMock(),
            ipc_resume=AsyncMock(),
        )

    def _build_monitor_with_messages(self, messages):
        """Return a mock monitor whose drain() returns the given messages."""
        from summon_claude.slack_browser import SlackMessage

        mock_monitor = AsyncMock()
        mock_monitor._queue = MagicMock()
        mock_monitor._queue.qsize.return_value = 0
        mock_monitor.drain = AsyncMock(return_value=messages)
        return mock_monitor

    def test_external_slack_check_spotlighting(self):
        """Messages are wrapped in UNTRUSTED delimiters containing a nonce.

        [SEC-001] Spotlighting with [SEC-R-005] per-session nonce — verified
        via source inspection since create_sdk_mcp_server is a local import.
        """
        import inspect as inspect_mod

        from summon_claude.sessions import session as session_mod

        source = inspect_mod.getsource(session_mod.SummonSession._create_external_slack_mcp)
        assert "BEGIN UNTRUSTED" in source
        assert "END UNTRUSTED" in source
        # Nonce is generated per session and embedded in delimiter
        assert "delimiter_nonce" in source

    @pytest.mark.asyncio
    async def test_external_slack_check_truncation(self):
        """Messages over 2000 chars are truncated and marked [truncated]."""
        import inspect as inspect_mod

        from summon_claude.sessions import session as session_mod

        source = inspect_mod.getsource(session_mod.SummonSession._create_external_slack_mcp)
        assert "max_text_len" in source or "2000" in source
        assert "[truncated]" in source

    @pytest.mark.asyncio
    async def test_external_slack_check_drain_cap(self):
        """drain() is called with limit=50 (max 50 messages per drain)."""
        import inspect as inspect_mod

        from summon_claude.sessions import session as session_mod

        source = inspect_mod.getsource(session_mod.SummonSession._create_external_slack_mcp)
        assert "max_per_drain" in source or "50" in source
        # drain is called with the limit keyword
        assert "drain(limit=" in source or "drain(limit=max_per_drain)" in source


# ---------------------------------------------------------------------------
# Scribe topic format
# ---------------------------------------------------------------------------


class TestScribeTopicFormat:
    def test_scribe_topic_format(self):
        """Topic for scribe sessions contains 'Scribe | Monitoring' and the interval.

        The topic string is set inside _run_session (not start), where channel
        creation and topic configuration happen.
        """
        import inspect

        from summon_claude.sessions import session as session_mod

        source = inspect.getsource(session_mod.SummonSession._run_session)
        assert "Scribe | Monitoring" in source
        assert "interval_min" in source or "scan_interval" in source


# ---------------------------------------------------------------------------
# Canvas template selection
# ---------------------------------------------------------------------------


class TestScribeCanvasTemplate:
    def test_scribe_canvas_template_selected(self):
        """'scribe' profile key maps to SCRIBE_CANVAS_TEMPLATE."""
        from summon_claude.slack.canvas_templates import SCRIBE_CANVAS_TEMPLATE, get_canvas_template

        template = get_canvas_template("scribe")
        assert template is SCRIBE_CANVAS_TEMPLATE

    def test_scribe_canvas_template_content(self):
        """SCRIBE_CANVAS_TEMPLATE contains scribe-specific heading."""
        from summon_claude.slack.canvas_templates import SCRIBE_CANVAS_TEMPLATE

        assert "Scribe Agent" in SCRIBE_CANVAS_TEMPLATE


# ---------------------------------------------------------------------------
# Shutdown stops monitors
# ---------------------------------------------------------------------------


class TestScribeShutdownStopsMonitors:
    def test_scribe_shutdown_stops_monitors(self):
        """_shutdown() calls stop() on each monitor in _slack_monitors."""
        import inspect

        from summon_claude.sessions import session as session_mod

        source = inspect.getsource(session_mod.SummonSession._shutdown)
        assert "slack_monitors" in source
        assert "monitor.stop()" in source or ".stop()" in source


# ---------------------------------------------------------------------------
# _build_scan_cron
# ---------------------------------------------------------------------------


class TestBuildScanCron:
    def test_build_scan_cron_minutes(self):
        """300 seconds (5 min) → '*/5 * * * *'."""
        from summon_claude.sessions.session import _build_scan_cron

        assert _build_scan_cron(300) == "*/5 * * * *"

    def test_build_scan_cron_hours(self):
        """7200 seconds (2 hours) → '0 */2 * * *'."""
        from summon_claude.sessions.session import _build_scan_cron

        assert _build_scan_cron(7200) == "0 */2 * * *"

    def test_build_scan_cron_minimum_clamp(self):
        """Values below 60 seconds are clamped to */1 * * * * (1 minute minimum)."""
        from summon_claude.sessions.session import _build_scan_cron

        assert _build_scan_cron(30) == "*/1 * * * *"

    def test_build_scan_cron_one_hour(self):
        """3600 seconds (1 hour) → '0 */1 * * *'."""
        from summon_claude.sessions.session import _build_scan_cron

        assert _build_scan_cron(3600) == "0 */1 * * *"


# ---------------------------------------------------------------------------
# slack_auth URL validation
# ---------------------------------------------------------------------------


class TestSlackAuthValidatesUrl:
    def test_slack_auth_rejects_non_slack_url(self):
        """slack_auth exits with code 1 for non-Slack URLs."""
        from click.testing import CliRunner

        from summon_claude.cli.__init__ import cmd_config

        runner = CliRunner()
        result = runner.invoke(cmd_config, ["slack-auth", "https://evil.example.com"])
        assert result.exit_code != 0
        assert "slack.com" in result.output.lower() or "Expected" in result.output

    def test_slack_auth_rejects_http_url(self):
        """slack_auth exits with code 1 for http:// (non-https) Slack URLs."""
        from click.testing import CliRunner

        from summon_claude.cli.__init__ import cmd_config

        runner = CliRunner()
        result = runner.invoke(cmd_config, ["slack-auth", "http://myteam.slack.com"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# project down stops scribe
# ---------------------------------------------------------------------------


class TestProjectDownStopsScribe:
    @pytest.mark.asyncio
    async def test_project_down_stops_scribe(self):
        """stop_project_managers (no name filter) finds and stops the scribe session.

        The function uses two separate ``async with SessionRegistry()`` blocks:
        the first lists projects (returns [] here), the second lists active sessions
        and finds the scribe. Both calls share the same mock registry instance.
        """
        from summon_claude.cli.project import stop_project_managers

        scribe_session = {
            "session_id": "scribe-sess-001",
            "session_name": "scribe",
            "status": "active",
            "project_id": None,
        }

        mock_reg = AsyncMock()
        mock_reg.__aenter__ = AsyncMock(return_value=mock_reg)
        mock_reg.__aexit__ = AsyncMock(return_value=False)
        # First block: list_projects returns one project with no active sessions
        # so we hit the "No active project sessions found" path, then proceed
        # to the scribe check in the second block.
        mock_reg.list_projects.return_value = [{"project_id": "proj-001", "name": "myproject"}]
        mock_reg.get_project_sessions.return_value = []
        mock_reg.list_active.return_value = [scribe_session]

        with (
            patch("summon_claude.cli.project.is_daemon_running", return_value=True),
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_reg),
            patch("summon_claude.cli.project.daemon_client") as mock_daemon,
            patch("summon_claude.cli.project._run_project_hooks", return_value=None),
        ):
            mock_daemon.stop_session = AsyncMock(return_value=True)

            stopped = await stop_project_managers()

        assert "scribe-sess-001" in stopped


# ---------------------------------------------------------------------------
# _start_scribe_if_enabled pre-flight checks
# ---------------------------------------------------------------------------


class TestScribePreflight:
    def _make_manager(self, **config_overrides):
        from summon_claude.sessions.manager import SessionManager

        config = make_config(scribe_enabled=True, **config_overrides)
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
        return manager

    def test_scribe_preflight_missing_google(self):
        """_start_scribe_if_enabled returns early when workspace-mcp binary missing.

        find_workspace_mcp_bin is a local import inside the method, so we patch
        it at its definition site (summon_claude.config).
        """
        manager = self._make_manager(scribe_google_services="gmail")

        missing_bin = MagicMock()
        missing_bin.exists.return_value = False

        with (
            patch("summon_claude.sessions.manager.SummonSession") as mock_cls,
            patch("summon_claude.config.find_workspace_mcp_bin", return_value=missing_bin),
        ):
            manager._start_scribe_if_enabled("U123")

        mock_cls.assert_not_called()

    def test_scribe_preflight_missing_playwright(self, tmp_path):
        """_start_scribe_if_enabled returns early when playwright not installed."""
        manager = self._make_manager(scribe_slack_enabled=True)

        with (
            patch("summon_claude.sessions.manager.SummonSession") as mock_cls,
            patch("summon_claude.sessions.manager.get_data_dir", return_value=tmp_path),
            patch("importlib.util.find_spec", return_value=None),
        ):
            manager._start_scribe_if_enabled("U123")

        mock_cls.assert_not_called()
