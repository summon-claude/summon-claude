"""Tests for the 'summon project' CLI subcommand logic."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import click
import pytest

from summon_claude.cli.project import async_project_remove
from summon_claude.config import socket_path_for_project


class TestAsyncProjectRemove:
    """Tests for async_project_remove socket cleanup."""

    def test_project_remove_unlinks_socket(self, tmp_path):
        """async_project_remove deletes the daemon socket for the removed project's directory."""
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        sock_path = socket_path_for_project(project_dir)
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        sock_path.touch()

        project_record = {
            "project_id": "proj-abc",
            "name": "myproject",
            "directory": str(project_dir),
        }

        mock_reg = AsyncMock()
        mock_reg.__aenter__ = AsyncMock(return_value=mock_reg)
        mock_reg.__aexit__ = AsyncMock(return_value=False)
        mock_reg.get_project = AsyncMock(return_value=project_record)
        mock_reg.remove_project = AsyncMock(return_value=[])

        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_reg),
            patch("summon_claude.cli.project.is_daemon_running", return_value=False),
        ):
            asyncio.run(async_project_remove("myproject"))

        assert not sock_path.exists(), "socket file should have been unlinked after project removal"

    def test_project_remove_empty_parent_dirs_removed(self, tmp_path):
        """async_project_remove in local mode removes empty socket parent dirs after unlink."""
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        sock_path = socket_path_for_project(project_dir)
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        sock_path.touch()
        sock_parent = sock_path.parent

        project_record = {
            "project_id": "proj-abc",
            "name": "myproject",
            "directory": str(project_dir),
        }

        mock_reg = AsyncMock()
        mock_reg.__aenter__ = AsyncMock(return_value=mock_reg)
        mock_reg.__aexit__ = AsyncMock(return_value=False)
        mock_reg.get_project = AsyncMock(return_value=project_record)
        mock_reg.remove_project = AsyncMock(return_value=[])

        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_reg),
            patch("summon_claude.cli.project.is_daemon_running", return_value=False),
            patch("summon_claude.cli.project.is_local_install", return_value=True),
        ):
            asyncio.run(async_project_remove("myproject"))

        assert not sock_parent.exists(), "empty socket parent dir should be removed"

    def test_project_remove_global_mode_skips_rmdir(self, tmp_path):
        """async_project_remove in global mode unlinks socket but does not rmdir parents."""
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        sock_path = socket_path_for_project(project_dir)
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        sock_path.touch()
        sock_parent = sock_path.parent

        project_record = {
            "project_id": "proj-abc",
            "name": "myproject",
            "directory": str(project_dir),
        }

        mock_reg = AsyncMock()
        mock_reg.__aenter__ = AsyncMock(return_value=mock_reg)
        mock_reg.__aexit__ = AsyncMock(return_value=False)
        mock_reg.get_project = AsyncMock(return_value=project_record)
        mock_reg.remove_project = AsyncMock(return_value=[])

        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_reg),
            patch("summon_claude.cli.project.is_daemon_running", return_value=False),
            patch("summon_claude.cli.project.is_local_install", return_value=False),
        ):
            asyncio.run(async_project_remove("myproject"))

        assert not sock_path.exists(), "socket file should be unlinked in any mode"
        assert sock_parent.exists(), "global mode must not rmdir socket parent dirs"

    def test_project_remove_socket_missing_is_noop(self, tmp_path):
        """async_project_remove does not fail if the socket file does not exist."""
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        project_record = {
            "project_id": "proj-abc",
            "name": "myproject",
            "directory": str(project_dir),
        }

        mock_reg = AsyncMock()
        mock_reg.__aenter__ = AsyncMock(return_value=mock_reg)
        mock_reg.__aexit__ = AsyncMock(return_value=False)
        mock_reg.get_project = AsyncMock(return_value=project_record)
        mock_reg.remove_project = AsyncMock(return_value=[])

        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_reg),
            patch("summon_claude.cli.project.is_daemon_running", return_value=False),
        ):
            asyncio.run(async_project_remove("myproject"))

    def test_project_remove_no_directory_skips_socket_cleanup(self):
        """async_project_remove skips socket cleanup when project has no directory."""
        project_record = {
            "project_id": "proj-abc",
            "name": "myproject",
            "directory": "",
        }

        mock_reg = AsyncMock()
        mock_reg.__aenter__ = AsyncMock(return_value=mock_reg)
        mock_reg.__aexit__ = AsyncMock(return_value=False)
        mock_reg.get_project = AsyncMock(return_value=project_record)
        mock_reg.remove_project = AsyncMock(return_value=[])

        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_reg),
            patch("summon_claude.cli.project.is_daemon_running", return_value=False),
        ):
            asyncio.run(async_project_remove("myproject"))

    def test_project_remove_unknown_project_raises(self):
        """async_project_remove raises ClickException when project is not found."""
        mock_reg = AsyncMock()
        mock_reg.__aenter__ = AsyncMock(return_value=mock_reg)
        mock_reg.__aexit__ = AsyncMock(return_value=False)
        mock_reg.get_project = AsyncMock(
            return_value={"project_id": "proj-abc", "name": "x", "directory": ""}
        )
        mock_reg.remove_project = AsyncMock(side_effect=ValueError("No project found: 'missing'"))

        with (
            patch("summon_claude.cli.project.SessionRegistry", return_value=mock_reg),
            patch("summon_claude.cli.project.is_daemon_running", return_value=False),
            pytest.raises(click.ClickException),
        ):
            asyncio.run(async_project_remove("missing"))
