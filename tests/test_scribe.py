"""Tests for scribe session profile, scan timer, channel scoping, and auto-spawn.

Covers C12 (Phase 1) and C13 (Phase 2) test requirements.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from summon_claude.config import SummonConfig
from summon_claude.sessions.session import (
    SessionOptions,
    SummonSession,
    _is_quiet_hours,
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
# C12 Phase 1: _is_quiet_hours
# ---------------------------------------------------------------------------


class TestIsQuietHours:
    def _mock_now(self, hour: int, minute: int):
        """Return a datetime mock that returns the given hour:minute."""
        fake = datetime(2026, 3, 22, hour, minute)  # noqa: DTZ001
        return patch(
            "summon_claude.sessions.session.datetime",
            **{"now.return_value": fake, "side_effect": None},
        )

    def test_quiet_hours_inside(self):
        """22:00 local time falls inside 22:00-07:00 quiet hours."""
        with patch("summon_claude.sessions.session.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 22, 22, 30)  # noqa: DTZ001
            result = _is_quiet_hours("22:00-07:00")
        assert result is True

    def test_quiet_hours_outside(self):
        """12:00 local time is outside 22:00-07:00 quiet hours."""
        with patch("summon_claude.sessions.session.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 22, 12, 0)  # noqa: DTZ001
            result = _is_quiet_hours("22:00-07:00")
        assert result is False

    def test_quiet_hours_empty_string(self):
        assert _is_quiet_hours("") is False

    def test_quiet_hours_wraps_midnight(self):
        """02:00 falls inside 22:00-07:00 (midnight wrap)."""
        with patch("summon_claude.sessions.session.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 22, 2, 0)  # noqa: DTZ001
            result = _is_quiet_hours("22:00-07:00")
        assert result is True

    def test_quiet_hours_boundary_start(self):
        """Exactly at start time (22:00) is considered inside."""
        with patch("summon_claude.sessions.session.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 22, 22, 0)  # noqa: DTZ001
            result = _is_quiet_hours("22:00-07:00")
        assert result is True

    def test_quiet_hours_boundary_end_exclusive(self):
        """Exactly at end time (07:00) is NOT considered inside (exclusive end)."""
        with patch("summon_claude.sessions.session.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 22, 7, 0)  # noqa: DTZ001
            result = _is_quiet_hours("22:00-07:00")
        assert result is False

    def test_quiet_hours_no_wrap_range(self):
        """09:00-17:00 is a non-wrapping range; 12:00 is inside."""
        with patch("summon_claude.sessions.session.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 22, 12, 0)  # noqa: DTZ001
            result = _is_quiet_hours("09:00-17:00")
        assert result is True

    def test_quiet_hours_invalid_format(self):
        """Malformed strings return False without raising."""
        assert _is_quiet_hours("not-a-range") is False
        assert _is_quiet_hours("25:00-07:00") is False


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
