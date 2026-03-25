"""Tests for the 'summon reset' CLI subgroup."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from summon_claude.cli import cli


class TestResetBare:
    def test_reset_bare_shows_help(self):
        """'summon reset' with no subcommand shows usage."""
        runner = CliRunner()
        result = runner.invoke(cli, ["reset"])
        assert "data" in result.output or "Usage" in result.output


class TestResetData:
    def test_reset_data_deletes_data_dir(self, tmp_path):
        """'reset data' should delete the data directory after confirmation."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "registry.db").touch()

        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=False),
            patch("summon_claude.cli.reset.get_data_dir", return_value=data_dir),
        ):
            result = runner.invoke(cli, ["reset", "data"], input="y\n")
        assert result.exit_code == 0
        assert not data_dir.exists()
        assert "summon start" in result.output

    def test_reset_data_aborts_on_no(self, tmp_path):
        """'reset data' should abort when user declines."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=False),
            patch("summon_claude.cli.reset.get_data_dir", return_value=data_dir),
        ):
            result = runner.invoke(cli, ["reset", "data"], input="n\n")
        assert result.exit_code != 0
        assert data_dir.exists()

    def test_reset_data_refuses_if_sessions_running(self):
        """'reset data' should refuse when daemon has active sessions."""
        runner = CliRunner()
        mock_sessions = [{"session_id": "abc", "session_name": "test-sess"}]
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=True),
            patch(
                "summon_claude.cli.daemon_client.list_sessions",
                new_callable=AsyncMock,
                return_value=mock_sessions,
            ),
        ):
            result = runner.invoke(cli, ["reset", "data"])
        assert result.exit_code != 0
        assert "summon stop --all" in result.output

    def test_reset_data_refuses_mixed_sessions(self):
        """'reset data' should show both messages when ad-hoc and project sessions exist."""
        runner = CliRunner()
        mock_sessions = [
            {"session_id": "abc", "session_name": "test-sess"},
            {"session_id": "def", "session_name": "proj-pm-agent"},
        ]
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=True),
            patch(
                "summon_claude.cli.daemon_client.list_sessions",
                new_callable=AsyncMock,
                return_value=mock_sessions,
            ),
        ):
            result = runner.invoke(cli, ["reset", "data"])
        assert result.exit_code != 0
        assert "summon stop --all" in result.output
        assert "summon project down" in result.output

    def test_reset_data_refuses_idle_daemon(self):
        """'reset data' should refuse when daemon is running with no sessions."""
        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=True),
            patch(
                "summon_claude.cli.daemon_client.list_sessions",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = runner.invoke(cli, ["reset", "data"])
        assert result.exit_code != 0
        assert "daemon is still running" in result.output

    def test_reset_data_rmtree_failure(self, tmp_path):
        """'reset data' should show friendly error if rmtree fails."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=False),
            patch("summon_claude.cli.reset.get_data_dir", return_value=data_dir),
            patch(
                "summon_claude.cli.reset.shutil.rmtree",
                side_effect=OSError("Permission denied"),
            ),
        ):
            result = runner.invoke(cli, ["reset", "data"], input="y\n")
        assert result.exit_code != 0
        assert "Failed to delete" in result.output

    def test_reset_data_refuses_on_ipc_failure(self):
        """'reset data' should refuse when daemon IPC fails."""
        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=True),
            patch(
                "summon_claude.cli.daemon_client.list_sessions",
                new_callable=AsyncMock,
                side_effect=ConnectionRefusedError,
            ),
        ):
            result = runner.invoke(cli, ["reset", "data"])
        assert result.exit_code != 0
        assert "Could not determine session status" in result.output

    def test_reset_data_noop_if_dir_missing(self, tmp_path):
        """'reset data' should no-op when data directory does not exist."""
        missing_dir = tmp_path / "nonexistent"

        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=False),
            patch("summon_claude.cli.reset.get_data_dir", return_value=missing_dir),
        ):
            result = runner.invoke(cli, ["reset", "data"])
        assert result.exit_code == 0
        assert "Nothing to reset" in result.output

    def test_reset_data_refuses_symlink(self, tmp_path):
        """'reset data' should refuse when data directory is a symlink."""
        target = tmp_path / "real"
        target.mkdir()
        symlink = tmp_path / "data"
        symlink.symlink_to(target)

        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=False),
            patch("summon_claude.cli.reset.get_data_dir", return_value=symlink),
        ):
            result = runner.invoke(cli, ["reset", "data"], input="y\n")
        assert result.exit_code != 0
        assert "symlink" in result.output
        assert target.exists()

    def test_reset_data_refuses_non_interactive(self, tmp_path):
        """'reset data' should refuse in non-interactive mode."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.get_data_dir", return_value=data_dir),
        ):
            result = runner.invoke(cli, ["--no-interactive", "reset", "data"])
        assert result.exit_code != 0
        assert "interactive mode" in result.output
        assert data_dir.exists()


class TestResetConfig:
    def test_reset_config_deletes_config_dir(self, tmp_path):
        """'reset config' should delete the config directory after confirmation."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.env").touch()

        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=False),
            patch("summon_claude.cli.reset.get_config_dir", return_value=config_dir),
        ):
            result = runner.invoke(cli, ["reset", "config"], input="y\n")
        assert result.exit_code == 0
        assert not config_dir.exists()
        assert "summon hooks uninstall" in result.output
        assert "summon init" in result.output

    def test_reset_config_aborts_on_no(self, tmp_path):
        """'reset config' should abort when user declines."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=False),
            patch("summon_claude.cli.reset.get_config_dir", return_value=config_dir),
        ):
            result = runner.invoke(cli, ["reset", "config"], input="n\n")
        assert result.exit_code != 0
        assert config_dir.exists()

    def test_reset_config_refuses_adhoc_sessions(self):
        """'reset config' should refuse when daemon has ad-hoc sessions."""
        runner = CliRunner()
        mock_sessions = [{"session_id": "abc", "session_name": "test-sess"}]
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=True),
            patch(
                "summon_claude.cli.daemon_client.list_sessions",
                new_callable=AsyncMock,
                return_value=mock_sessions,
            ),
        ):
            result = runner.invoke(cli, ["reset", "config"])
        assert result.exit_code != 0
        assert "summon stop --all" in result.output

    def test_reset_config_refuses_if_sessions_running(self):
        """'reset config' should refuse when daemon has project sessions."""
        runner = CliRunner()
        mock_sessions = [{"session_id": "abc", "session_name": "my-pm-agent"}]
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=True),
            patch(
                "summon_claude.cli.daemon_client.list_sessions",
                new_callable=AsyncMock,
                return_value=mock_sessions,
            ),
        ):
            result = runner.invoke(cli, ["reset", "config"])
        assert result.exit_code != 0
        assert "summon project down" in result.output

    def test_reset_config_refuses_on_ipc_failure(self):
        """'reset config' should refuse when daemon IPC fails."""
        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=True),
            patch(
                "summon_claude.cli.daemon_client.list_sessions",
                new_callable=AsyncMock,
                side_effect=OSError("Connection refused"),
            ),
        ):
            result = runner.invoke(cli, ["reset", "config"])
        assert result.exit_code != 0
        assert "Could not determine session status" in result.output

    def test_reset_config_noop_if_dir_missing(self, tmp_path):
        """'reset config' should no-op when config directory does not exist."""
        missing_dir = tmp_path / "nonexistent"

        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.is_interactive", return_value=True),
            patch("summon_claude.cli.reset.is_daemon_running", return_value=False),
            patch("summon_claude.cli.reset.get_config_dir", return_value=missing_dir),
        ):
            result = runner.invoke(cli, ["reset", "config"])
        assert result.exit_code == 0
        assert "Nothing to reset" in result.output

    def test_reset_config_refuses_non_interactive(self, tmp_path):
        """'reset config' should refuse in non-interactive mode."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        runner = CliRunner()
        with (
            patch("summon_claude.cli.reset.get_config_dir", return_value=config_dir),
        ):
            result = runner.invoke(cli, ["--no-interactive", "reset", "config"])
        assert result.exit_code != 0
        assert "interactive mode" in result.output
        assert config_dir.exists()
