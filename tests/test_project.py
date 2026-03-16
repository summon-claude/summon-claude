"""Tests for PM track: project registry CRUD, CLI commands, launcher, PM session behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from summon_claude.cli import cli
from summon_claude.sessions.registry import SessionRegistry
from summon_claude.sessions.session import SessionOptions, build_pm_system_prompt
from summon_claude.slack.canvas_templates import PM_CANVAS_TEMPLATE, get_canvas_template

# ---------------------------------------------------------------------------
# Registry: project CRUD
# ---------------------------------------------------------------------------


class TestProjectAdd:
    async def test_add_project_returns_uuid(self, registry, tmp_path):
        project_id = await registry.add_project("my-proj", str(tmp_path))
        assert len(project_id) == 36  # UUID format

    async def test_add_project_creates_record(self, registry, tmp_path):
        project_id = await registry.add_project("my-proj", str(tmp_path))
        project = await registry.get_project(project_id)
        assert project is not None
        assert project["name"] == "my-proj"
        assert project["directory"] == str(tmp_path)

    async def test_add_project_derives_channel_prefix(self, registry, tmp_path):
        project_id = await registry.add_project("My Cool Project", str(tmp_path))
        project = await registry.get_project(project_id)
        assert project["channel_prefix"] == "my-cool-project"

    async def test_add_project_truncates_prefix(self, registry, tmp_path):
        long_name = "a" * 30
        project_id = await registry.add_project(long_name, str(tmp_path))
        project = await registry.get_project(project_id)
        assert len(project["channel_prefix"]) <= 20

    async def test_add_duplicate_name_raises(self, registry, tmp_path):
        await registry.add_project("dup-proj", str(tmp_path))
        with pytest.raises(ValueError, match="already exists"):
            await registry.add_project("dup-proj", str(tmp_path))

    async def test_add_project_default_empty_workflow(self, registry, tmp_path):
        project_id = await registry.add_project("wf-proj", str(tmp_path))
        project = await registry.get_project(project_id)
        assert project["workflow_instructions"] == ""

    async def test_add_project_no_pm_channel_initially(self, registry, tmp_path):
        project_id = await registry.add_project("ch-proj", str(tmp_path))
        project = await registry.get_project(project_id)
        assert project["pm_channel_id"] is None


class TestProjectGet:
    async def test_get_by_id(self, registry, tmp_path):
        project_id = await registry.add_project("get-proj", str(tmp_path))
        project = await registry.get_project(project_id)
        assert project["project_id"] == project_id

    async def test_get_by_name(self, registry, tmp_path):
        await registry.add_project("named-proj", str(tmp_path))
        project = await registry.get_project("named-proj")
        assert project is not None
        assert project["name"] == "named-proj"

    async def test_get_nonexistent_returns_none(self, registry):
        result = await registry.get_project("no-such-project")
        assert result is None


class TestProjectRemove:
    async def test_remove_project(self, registry, tmp_path):
        project_id = await registry.add_project("rm-proj", str(tmp_path))
        await registry.remove_project(project_id)
        assert await registry.get_project(project_id) is None

    async def test_remove_by_name(self, registry, tmp_path):
        await registry.add_project("rm-name", str(tmp_path))
        await registry.remove_project("rm-name")
        assert await registry.get_project("rm-name") is None

    async def test_remove_nonexistent_raises(self, registry):
        with pytest.raises(ValueError, match="No project found"):
            await registry.remove_project("no-such")

    async def test_remove_with_active_session_raises(self, registry, tmp_path):
        project_id = await registry.add_project("active-proj", str(tmp_path))
        await registry.register("sess-1", 1234, str(tmp_path), project_id=project_id)
        # pending_auth is active — remove should fail
        with pytest.raises(ValueError, match="active session"):
            await registry.remove_project(project_id)

    async def test_remove_with_completed_session_succeeds(self, registry, tmp_path):
        project_id = await registry.add_project("done-proj", str(tmp_path))
        await registry.register("sess-2", 1234, str(tmp_path), project_id=project_id)
        await registry.update_status("sess-2", "completed")
        await registry.remove_project(project_id)
        assert await registry.get_project(project_id) is None


class TestProjectList:
    async def test_list_empty(self, registry):
        projects = await registry.list_projects()
        assert projects == []

    async def test_list_returns_all_projects(self, registry, tmp_path):
        await registry.add_project("proj-a", str(tmp_path))
        await registry.add_project("proj-b", str(tmp_path))
        projects = await registry.list_projects()
        names = [p["name"] for p in projects]
        assert "proj-a" in names
        assert "proj-b" in names

    async def test_list_includes_pm_running_false(self, registry, tmp_path):
        await registry.add_project("idle-proj", str(tmp_path))
        projects = await registry.list_projects()
        proj = next(p for p in projects if p["name"] == "idle-proj")
        assert proj["pm_running"] == 0  # SQLite stores bool as int

    async def test_list_includes_pm_running_true(self, registry, tmp_path):
        project_id = await registry.add_project("running-proj", str(tmp_path))
        await registry.register("sess-pm", 1234, str(tmp_path), project_id=project_id)
        await registry.update_status("sess-pm", "active")
        projects = await registry.list_projects()
        proj = next(p for p in projects if p["name"] == "running-proj")
        assert proj["pm_running"] == 1  # has an active session

    async def test_list_ordered_by_name(self, registry, tmp_path):
        await registry.add_project("z-proj", str(tmp_path))
        await registry.add_project("a-proj", str(tmp_path))
        projects = await registry.list_projects()
        names = [p["name"] for p in projects]
        assert names.index("a-proj") < names.index("z-proj")


class TestProjectSessions:
    async def test_get_project_sessions_empty(self, registry, tmp_path):
        project_id = await registry.add_project("emp-proj", str(tmp_path))
        sessions = await registry.get_project_sessions(project_id)
        assert sessions == []

    async def test_get_project_sessions_returns_linked(self, registry, tmp_path):
        project_id = await registry.add_project("link-proj", str(tmp_path))
        await registry.register("sess-linked", 1234, str(tmp_path), project_id=project_id)
        sessions = await registry.get_project_sessions(project_id)
        ids = [s["session_id"] for s in sessions]
        assert "sess-linked" in ids

    async def test_get_project_sessions_excludes_others(self, registry, tmp_path):
        project_id = await registry.add_project("excl-proj", str(tmp_path))
        await registry.register("sess-other", 1234, str(tmp_path))  # no project_id
        sessions = await registry.get_project_sessions(project_id)
        assert all(s["session_id"] != "sess-other" for s in sessions)


class TestProjectUpdate:
    async def test_update_pm_channel_id(self, registry, tmp_path):
        project_id = await registry.add_project("upd-proj", str(tmp_path))
        await registry.update_project(project_id, pm_channel_id="C_NEW_CHANNEL")
        project = await registry.get_project(project_id)
        assert project["pm_channel_id"] == "C_NEW_CHANNEL"

    async def test_update_workflow_instructions(self, registry, tmp_path):
        project_id = await registry.add_project("wi-proj", str(tmp_path))
        await registry.update_project(project_id, workflow_instructions="Use TDD.")
        project = await registry.get_project(project_id)
        assert project["workflow_instructions"] == "Use TDD."

    async def test_update_ignores_unknown_fields(self, registry, tmp_path):
        project_id = await registry.add_project("unk-proj", str(tmp_path))
        # Should not raise
        await registry.update_project(project_id, nonexistent_field="value")
        project = await registry.get_project(project_id)
        assert project is not None


class TestRegisterWithProjectId:
    async def test_register_with_project_id(self, registry, tmp_path):
        project_id = await registry.add_project("reg-proj", str(tmp_path))
        await registry.register("sess-proj", 1234, str(tmp_path), project_id=project_id)
        session = await registry.get_session("sess-proj")
        assert session["project_id"] == project_id

    async def test_register_without_project_id(self, registry, tmp_path):
        await registry.register("sess-noproj", 1234, str(tmp_path))
        session = await registry.get_session("sess-noproj")
        assert session["project_id"] is None


class TestProjectIdInUpdatableFields:
    def test_project_id_in_updatable_fields(self):
        assert "project_id" in SessionRegistry._UPDATABLE_FIELDS


# ---------------------------------------------------------------------------
# SessionOptions: new fields
# ---------------------------------------------------------------------------


class TestSessionOptionsNewFields:
    def test_auth_only_default_false(self):
        opts = SessionOptions(cwd="/tmp", name="test")
        assert opts.auth_only is False

    def test_project_id_default_none(self):
        opts = SessionOptions(cwd="/tmp", name="test")
        assert opts.project_id is None

    def test_scan_interval_s_default(self):
        opts = SessionOptions(cwd="/tmp", name="test")
        assert opts.scan_interval_s == 900

    def test_auth_only_can_be_set(self):
        opts = SessionOptions(cwd="/tmp", name="test", auth_only=True)
        assert opts.auth_only is True

    def test_project_id_can_be_set(self):
        opts = SessionOptions(cwd="/tmp", name="test", project_id="proj-123")
        assert opts.project_id == "proj-123"

    def test_scan_interval_s_can_be_set(self):
        opts = SessionOptions(cwd="/tmp", name="test", scan_interval_s=300)
        assert opts.scan_interval_s == 300


# ---------------------------------------------------------------------------
# PM system prompt
# ---------------------------------------------------------------------------


class TestBuildPmSystemPrompt:
    def test_returns_dict(self):
        result = build_pm_system_prompt(cwd="/tmp/project", scan_interval_s=900)
        assert isinstance(result, dict)

    def test_uses_preset_claude_code(self):
        result = build_pm_system_prompt(cwd="/tmp/project", scan_interval_s=900)
        assert result.get("preset") == "claude_code"

    def test_includes_cwd(self):
        result = build_pm_system_prompt(cwd="/my/project/dir", scan_interval_s=900)
        assert "/my/project/dir" in result["append"]

    def test_includes_scan_interval_minutes(self):
        result = build_pm_system_prompt(cwd="/tmp", scan_interval_s=600)
        assert "10" in result["append"]  # 600s = 10 minutes

    def test_15min_interval(self):
        result = build_pm_system_prompt(cwd="/tmp", scan_interval_s=900)
        assert "15" in result["append"]

    def test_append_is_string(self):
        result = build_pm_system_prompt(cwd="/tmp", scan_interval_s=900)
        assert isinstance(result["append"], str)
        assert len(result["append"]) > 50


# ---------------------------------------------------------------------------
# Canvas template
# ---------------------------------------------------------------------------


class TestPMCanvasTemplate:
    def test_get_pm_profile_returns_pm_template(self):
        template = get_canvas_template("pm")
        assert template == PM_CANVAS_TEMPLATE

    def test_pm_template_has_pm_header(self):
        assert "PM Agent" in PM_CANVAS_TEMPLATE

    def test_pm_template_formattable(self):
        filled = PM_CANVAS_TEMPLATE.format(model="claude-opus", cwd="/tmp")
        assert "claude-opus" in filled
        assert "/tmp" in filled


# ---------------------------------------------------------------------------
# CLI: project commands
# ---------------------------------------------------------------------------


class TestProjectCLICommands:
    def test_project_group_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["project", "--help"])
        assert result.exit_code == 0
        assert "Manage summon projects" in result.output

    def test_project_alias_p_works(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["p", "--help"])
        assert result.exit_code == 0
        assert "Manage summon projects" in result.output

    def test_project_add_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["project", "add", "--help"])
        assert result.exit_code == 0
        assert "NAME" in result.output

    def test_project_remove_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["project", "remove", "--help"])
        assert result.exit_code == 0

    def test_project_list_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["project", "list", "--help"])
        assert result.exit_code == 0

    def test_project_up_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["project", "up", "--help"])
        assert result.exit_code == 0

    def test_project_down_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["project", "down", "--help"])
        assert result.exit_code == 0


class TestProjectAddCLI:
    def test_add_project_invalid_directory(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["project", "add", "bad-proj", str(tmp_path / "nonexistent")])
        assert result.exit_code != 0

    def test_add_project_success(self, tmp_path):
        with patch("summon_claude.cli.project.SessionRegistry") as mock_reg:
            reg = AsyncMock()
            reg.add_project = AsyncMock(return_value="proj-123-id")
            mock_reg.return_value.__aenter__ = AsyncMock(return_value=reg)
            mock_reg.return_value.__aexit__ = AsyncMock(return_value=False)
            runner = CliRunner()
            result = runner.invoke(cli, ["project", "add", "cli-success-proj", str(tmp_path)])
        assert result.exit_code == 0
        assert "registered" in result.output

    def test_add_project_quiet_mode(self, tmp_path):
        with patch("summon_claude.cli.project.SessionRegistry") as mock_reg:
            reg = AsyncMock()
            reg.add_project = AsyncMock(return_value="proj-quiet-id")
            mock_reg.return_value.__aenter__ = AsyncMock(return_value=reg)
            mock_reg.return_value.__aexit__ = AsyncMock(return_value=False)
            runner = CliRunner()
            result = runner.invoke(cli, ["-q", "project", "add", "cli-quiet-proj", str(tmp_path)])
        assert result.exit_code == 0
        assert "registered" not in result.output


class TestProjectListCLI:
    def test_list_empty(self):
        with patch("summon_claude.cli.project.SessionRegistry") as mock_reg:
            reg = AsyncMock()
            reg.list_projects = AsyncMock(return_value=[])
            mock_reg.return_value.__aenter__ = AsyncMock(return_value=reg)
            mock_reg.return_value.__aexit__ = AsyncMock(return_value=False)
            runner = CliRunner()
            result = runner.invoke(cli, ["project", "list"])
        assert result.exit_code == 0
        assert "No projects" in result.output

    def test_list_with_projects(self, tmp_path):
        import json

        projects = [
            {
                "name": "my-proj",
                "directory": str(tmp_path),
                "pm_running": 0,
                "project_id": "abc123-def456",
                "channel_prefix": "my-proj",
            }
        ]
        with patch("summon_claude.cli.project.SessionRegistry") as mock_reg:
            reg = AsyncMock()
            reg.list_projects = AsyncMock(return_value=projects)
            mock_reg.return_value.__aenter__ = AsyncMock(return_value=reg)
            mock_reg.return_value.__aexit__ = AsyncMock(return_value=False)
            runner = CliRunner()
            result = runner.invoke(cli, ["project", "list"])
        assert result.exit_code == 0
        assert "my-proj" in result.output

    def test_list_json_output(self, tmp_path):
        import json

        projects = [
            {
                "name": "j-proj",
                "directory": str(tmp_path),
                "pm_running": False,
                "project_id": "uuid-123",
            }
        ]
        with patch("summon_claude.cli.project.SessionRegistry") as mock_reg:
            reg = AsyncMock()
            reg.list_projects = AsyncMock(return_value=projects)
            mock_reg.return_value.__aenter__ = AsyncMock(return_value=reg)
            mock_reg.return_value.__aexit__ = AsyncMock(return_value=False)
            runner = CliRunner()
            result = runner.invoke(cli, ["project", "list", "--output", "json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)


class TestProjectRemoveCLI:
    def test_remove_project_success(self):
        with patch("summon_claude.cli.project.SessionRegistry") as mock_reg:
            reg = AsyncMock()
            reg.get_project = AsyncMock(return_value={"project_id": "p1", "name": "my-proj"})
            reg.get_project_sessions = AsyncMock(return_value=[])
            reg.remove_project = AsyncMock()
            mock_reg.return_value.__aenter__ = AsyncMock(return_value=reg)
            mock_reg.return_value.__aexit__ = AsyncMock(return_value=False)
            runner = CliRunner()
            result = runner.invoke(cli, ["project", "remove", "my-proj"])
        assert result.exit_code == 0
        assert "removed" in result.output


# ---------------------------------------------------------------------------
# Launcher logic
# ---------------------------------------------------------------------------


class TestLaunchProjectManagers:
    async def test_launch_no_projects(self):
        from summon_claude.cli.project import launch_project_managers

        with patch("summon_claude.cli.project.SessionRegistry") as mock_reg:
            reg = AsyncMock()
            reg.list_projects = AsyncMock(return_value=[])
            mock_reg.return_value.__aenter__ = AsyncMock(return_value=reg)
            mock_reg.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await launch_project_managers()
        assert result == []

    async def test_launch_all_pm_running(self):
        from summon_claude.cli.project import launch_project_managers

        projects = [{"project_id": "p1", "name": "proj1", "pm_running": 1, "directory": "/tmp"}]
        with patch("summon_claude.cli.project.SessionRegistry") as mock_reg:
            reg = AsyncMock()
            reg.list_projects = AsyncMock(return_value=projects)
            mock_reg.return_value.__aenter__ = AsyncMock(return_value=reg)
            mock_reg.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await launch_project_managers()
        assert result == []

    async def test_stop_project_managers_no_projects(self):
        from summon_claude.cli.project import stop_project_managers

        with patch("summon_claude.cli.project.SessionRegistry") as mock_reg:
            reg = AsyncMock()
            reg.list_projects = AsyncMock(return_value=[])
            mock_reg.return_value.__aenter__ = AsyncMock(return_value=reg)
            mock_reg.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await stop_project_managers()
        assert result == []


# ---------------------------------------------------------------------------
# PM profile: MCP tool session_status_update
# ---------------------------------------------------------------------------


class TestSessionStatusUpdateTool:
    async def test_status_update_valid(self, registry):
        from summon_claude.summon_cli_mcp import create_summon_cli_mcp_tools

        # Register a session for the tool to look up
        await registry.register("test-sid", 1234, "/tmp")
        tools = create_summon_cli_mcp_tools(registry, "test-sid", "uid", "cid", "/tmp")
        status_tool = next(t for t in tools if t.name == "session_status_update")

        result = await status_tool.handler({"status": "active", "summary": "All good"})
        assert "is_error" not in result or not result.get("is_error")

    async def test_status_update_invalid_status(self, registry):
        from summon_claude.summon_cli_mcp import create_summon_cli_mcp_tools

        tools = create_summon_cli_mcp_tools(registry, "sid", "uid", "cid", "/tmp")
        status_tool = next(t for t in tools if t.name == "session_status_update")

        result = await status_tool.handler({"status": "bogus", "summary": "test"})
        assert result.get("is_error") is True

    async def test_status_update_missing_summary(self, registry):
        from summon_claude.summon_cli_mcp import create_summon_cli_mcp_tools

        tools = create_summon_cli_mcp_tools(registry, "sid", "uid", "cid", "/tmp")
        status_tool = next(t for t in tools if t.name == "session_status_update")

        result = await status_tool.handler({"status": "active", "summary": ""})
        assert result.get("is_error") is True

    async def test_status_update_all_valid_statuses(self, registry):
        from summon_claude.summon_cli_mcp import create_summon_cli_mcp_tools

        await registry.register("sid-allstatus", 1234, "/tmp")
        tools = create_summon_cli_mcp_tools(registry, "sid-allstatus", "uid", "cid", "/tmp")
        status_tool = next(t for t in tools if t.name == "session_status_update")

        for status in ("active", "idle", "blocked", "error"):
            result = await status_tool.handler({"status": status, "summary": f"{status} test"})
            assert "is_error" not in result or not result.get("is_error"), (
                f"Expected success for status={status!r}"
            )


# ---------------------------------------------------------------------------
# Scan timer loop behavior (unit tests with mock)
# ---------------------------------------------------------------------------


class TestScanTimerLoop:
    async def test_scan_timer_exits_on_shutdown(self):
        """_scan_timer_loop should exit immediately when shutdown is set."""

        from summon_claude.config import SummonConfig
        from summon_claude.sessions.session import SessionOptions, SummonSession

        config = MagicMock(spec=SummonConfig)
        options = SessionOptions(cwd="/tmp", name="pm-test", pm_profile=True, scan_interval_s=3600)
        session = SummonSession(config=config, options=options, session_id="test-scan")
        # Set shutdown immediately
        session._shutdown_event.set()
        # Should exit without delay
        await asyncio.wait_for(session._scan_timer_loop(), timeout=1.0)

    async def test_scan_timer_injects_event(self):
        """_scan_timer_loop injects a scan trigger after interval."""

        from summon_claude.config import SummonConfig
        from summon_claude.sessions.session import SessionOptions, SummonSession

        config = MagicMock(spec=SummonConfig)
        options = SessionOptions(cwd="/tmp", name="pm-scan", pm_profile=True, scan_interval_s=1)
        session = SummonSession(config=config, options=options, session_id="test-scan-inject")

        # Run timer for just past 1 second, then set shutdown
        async def _stop_after():
            await asyncio.sleep(1.5)
            session._shutdown_event.set()

        await asyncio.gather(session._scan_timer_loop(), _stop_after())
        # Should have received the synthetic scan event
        assert not session._raw_event_queue.empty()
        event = session._raw_event_queue.get_nowait()
        assert event is not None
        assert "SCAN TRIGGER" in event.get("text", "")
