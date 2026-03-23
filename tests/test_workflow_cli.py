"""Tests for summon project workflow show/set/clear CLI commands."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from summon_claude.cli import cli
from summon_claude.cli.project import (
    _strip_comment_lines,
    async_workflow_clear,
    async_workflow_set,
    async_workflow_show,
)

# ---------------------------------------------------------------------------
# _strip_comment_lines
# ---------------------------------------------------------------------------


class TestStripCommentLines:
    def test_strips_hash_space_lines(self):
        assert _strip_comment_lines("# comment\nkeep this") == "keep this"

    def test_strips_hash_only_lines(self):
        assert _strip_comment_lines("#\nkeep") == "keep"

    def test_preserves_markdown_headings(self):
        assert _strip_comment_lines("## Heading\n### Sub") == "## Heading\n### Sub"

    def test_preserves_hashtag_no_space(self):
        assert _strip_comment_lines("#hashtag\ntext") == "#hashtag\ntext"

    def test_strips_leading_trailing_whitespace(self):
        assert _strip_comment_lines("# comment\n\n  text  \n\n") == "text"

    def test_empty_input(self):
        assert _strip_comment_lines("") == ""

    def test_all_comments(self):
        assert _strip_comment_lines("# a\n# b\n#\n") == ""


# ---------------------------------------------------------------------------
# Workflow show
# ---------------------------------------------------------------------------


def _mock_registry(
    *,
    projects: list[dict] | None = None,
    global_wf: str = "",
    project_wf: str | None = None,
):
    """Build a mock SessionRegistry for workflow tests."""
    reg = AsyncMock()
    reg.list_projects = AsyncMock(return_value=projects or [])
    reg.get_workflow_defaults = AsyncMock(return_value=global_wf)
    reg.get_project_workflow = AsyncMock(return_value=project_wf)
    reg.set_workflow_defaults = AsyncMock()
    reg.set_project_workflow = AsyncMock()
    reg.clear_workflow_defaults = AsyncMock()
    reg.clear_project_workflow = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=reg)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, reg


_PROJECT = {
    "project_id": "proj-123",
    "name": "myapp",
    "directory": "/tmp/myapp",
}


class TestWorkflowShow:
    def test_show_global_defaults(self, capsys):
        mock_ctx, _reg = _mock_registry(global_wf="Global rules here.")
        with patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx):
            asyncio.run(async_workflow_show())
        out = capsys.readouterr().out
        assert "Global workflow defaults:" in out
        assert "Global rules here." in out

    def test_show_global_empty(self, capsys):
        mock_ctx, _reg = _mock_registry()
        with patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx):
            asyncio.run(async_workflow_show())
        out = capsys.readouterr().out
        assert "No workflow instructions configured." in out

    def test_show_project_override(self, capsys):
        mock_ctx, _reg = _mock_registry(
            projects=[_PROJECT],
            project_wf="Project-specific rules.",
            global_wf="Global.",
        )
        with patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx):
            asyncio.run(async_workflow_show("myapp"))
        out = capsys.readouterr().out
        assert "project-specific" in out
        assert "Project-specific rules." in out

    def test_show_project_fallback(self, capsys):
        mock_ctx, _reg = _mock_registry(
            projects=[_PROJECT],
            project_wf=None,  # NULL = fallback
            global_wf="Global defaults.",
        )
        with patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx):
            asyncio.run(async_workflow_show("myapp"))
        out = capsys.readouterr().out
        assert "using global defaults" in out
        assert "Global defaults." in out

    def test_show_project_explicitly_cleared(self, capsys):
        mock_ctx, _reg = _mock_registry(
            projects=[_PROJECT],
            project_wf="",  # empty string = explicitly cleared
            global_wf="Global.",
        )
        with patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx):
            asyncio.run(async_workflow_show("myapp"))
        out = capsys.readouterr().out
        assert "explicitly cleared" in out

    def test_show_raw_unexpanded(self, capsys):
        mock_ctx, _reg = _mock_registry(
            projects=[_PROJECT],
            project_wf="Before\n$INCLUDE_GLOBAL\nAfter",
            global_wf="GLOBAL CONTENT",
        )
        with patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx):
            asyncio.run(async_workflow_show("myapp", raw=True))
        out = capsys.readouterr().out
        assert "$INCLUDE_GLOBAL" in out
        assert "GLOBAL CONTENT" not in out

    def test_show_resolved_expanded(self, capsys):
        mock_ctx, _reg = _mock_registry(
            projects=[_PROJECT],
            project_wf="Before\n$INCLUDE_GLOBAL\nAfter",
            global_wf="GLOBAL CONTENT",
        )
        with patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx):
            asyncio.run(async_workflow_show("myapp", raw=False))
        out = capsys.readouterr().out
        assert "GLOBAL CONTENT" in out
        assert "includes global" in out

    def test_show_project_by_id_prefix(self, capsys):
        """_resolve_project matches on project_id prefix."""
        mock_ctx, _reg = _mock_registry(
            projects=[_PROJECT],
            project_wf="ID-matched rules.",
            global_wf="G",
        )
        with patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx):
            asyncio.run(async_workflow_show("proj-1"))
        out = capsys.readouterr().out
        assert "project-specific" in out
        assert "ID-matched rules." in out

    def test_show_project_not_found(self):
        mock_ctx, _reg = _mock_registry(projects=[])
        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx),
            pytest.raises(Exception, match="not found"),
        ):
            asyncio.run(async_workflow_show("nonexistent"))


# ---------------------------------------------------------------------------
# Workflow set
# ---------------------------------------------------------------------------


class TestWorkflowSet:
    def test_set_global_saves_content(self, capsys):
        mock_ctx, reg = _mock_registry(global_wf="")
        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx),
            patch("click.edit", return_value="# comment\nNew global rules."),
        ):
            asyncio.run(async_workflow_set())
        reg.set_workflow_defaults.assert_awaited_once_with("New global rules.")
        out = capsys.readouterr().out
        assert "Global workflow defaults updated." in out

    def test_set_project_saves_content(self, capsys):
        mock_ctx, reg = _mock_registry(projects=[_PROJECT], project_wf=None, global_wf="G")
        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx),
            patch("click.edit", return_value="# comment\nProject rules."),
        ):
            asyncio.run(async_workflow_set("myapp"))
        reg.set_project_workflow.assert_awaited_once_with("proj-123", "Project rules.")
        out = capsys.readouterr().out
        assert "Workflow updated for project 'myapp'." in out

    def test_set_editor_returns_none_aborts(self, capsys):
        mock_ctx, reg = _mock_registry()
        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx),
            patch("click.edit", return_value=None),
        ):
            asyncio.run(async_workflow_set())
        reg.set_workflow_defaults.assert_not_awaited()
        out = capsys.readouterr().out
        assert "No changes made." in out

    def test_set_all_comments_aborts(self, capsys):
        """Editor content that is all comments results in no changes."""
        mock_ctx, reg = _mock_registry()
        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx),
            patch("click.edit", return_value="# only comments\n# nothing else\n"),
        ):
            asyncio.run(async_workflow_set())
        reg.set_workflow_defaults.assert_not_awaited()
        out = capsys.readouterr().out
        assert "No content entered" in out

    def test_set_project_with_global_token(self, capsys):
        mock_ctx, reg = _mock_registry(projects=[_PROJECT], project_wf=None, global_wf="G")
        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx),
            patch("click.edit", return_value="Before\n$INCLUDE_GLOBAL\nAfter"),
        ):
            asyncio.run(async_workflow_set("myapp"))
        reg.set_project_workflow.assert_awaited_once_with(
            "proj-123", "Before\n$INCLUDE_GLOBAL\nAfter"
        )
        out = capsys.readouterr().out
        assert "includes global defaults" in out

    def test_set_project_not_found(self):
        mock_ctx, _reg = _mock_registry(projects=[])
        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx),
            pytest.raises(Exception, match="not found"),
        ):
            asyncio.run(async_workflow_set("nonexistent"))


# ---------------------------------------------------------------------------
# Workflow clear
# ---------------------------------------------------------------------------


class TestWorkflowClear:
    def test_clear_global(self, capsys):
        mock_ctx, reg = _mock_registry(global_wf="old")
        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx),
            patch("click.confirm", return_value=True),
        ):
            asyncio.run(async_workflow_clear())
        reg.clear_workflow_defaults.assert_awaited_once()
        out = capsys.readouterr().out
        assert "cleared" in out.lower()

    def test_clear_project(self, capsys):
        mock_ctx, reg = _mock_registry(projects=[_PROJECT])
        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx),
            patch("click.confirm", return_value=True),
        ):
            asyncio.run(async_workflow_clear("myapp"))
        reg.clear_project_workflow.assert_awaited_once_with("proj-123")
        out = capsys.readouterr().out
        assert "global defaults" in out.lower()

    def test_clear_cancelled(self, capsys):
        mock_ctx, reg = _mock_registry()
        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_ctx),
            patch("click.confirm", return_value=False),
        ):
            asyncio.run(async_workflow_clear())
        reg.clear_workflow_defaults.assert_not_awaited()
        out = capsys.readouterr().out
        assert "cancelled" in out.lower()


# ---------------------------------------------------------------------------
# Workflow CLI integration (Click runner)
# ---------------------------------------------------------------------------


class TestWorkflowClickCommands:
    def test_workflow_show_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["project", "workflow", "show", "--help"])
        assert result.exit_code == 0
        assert "Show workflow instructions" in result.output

    def test_workflow_set_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["project", "workflow", "set", "--help"])
        assert result.exit_code == 0

    def test_workflow_clear_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["project", "workflow", "clear", "--help"])
        assert result.exit_code == 0
