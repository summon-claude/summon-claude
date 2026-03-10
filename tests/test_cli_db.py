"""Tests for the 'summon db' CLI subgroup and config check DB validation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from click.testing import CliRunner

from summon_claude.cli import cli
from summon_claude.sessions.registry import SessionRegistry


class TestDbMigrate:
    def test_db_migrate_reports_version(self):
        """'db migrate' should report the current schema version."""
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "migrate"])
        assert result.exit_code == 0
        assert "Schema version: 1" in result.output


class TestDbReset:
    def test_db_reset_with_yes_recreates(self, tmp_path):
        """'db reset --yes' should recreate the database."""
        runner = CliRunner()
        # Create an initial DB so reset has something to delete
        db_path = tmp_path / "registry.db"

        async def _create_db():
            async with SessionRegistry(db_path=db_path):
                pass

        asyncio.run(_create_db())
        assert db_path.exists()

        with patch(
            "summon_claude.sessions.registry._default_db_path",
            return_value=db_path,
        ):
            result = runner.invoke(cli, ["db", "reset", "--yes"])
        assert result.exit_code == 0
        assert "Database recreated" in result.output
        assert "Schema version:" in result.output

    def test_db_reset_without_yes_aborts(self, tmp_path):
        """'db reset' without --yes should prompt and abort if not confirmed."""
        runner = CliRunner()
        db_path = tmp_path / "registry.db"
        with patch(
            "summon_claude.sessions.registry._default_db_path",
            return_value=db_path,
        ):
            result = runner.invoke(cli, ["db", "reset"], input="n\n")
        assert result.exit_code != 0
        assert "Aborted" in result.output


class TestDbVacuum:
    def test_db_vacuum_runs(self, tmp_path):
        """'db vacuum' should report integrity status and size."""
        runner = CliRunner()
        db_path = tmp_path / "registry.db"

        async def _create_db():
            async with SessionRegistry(db_path=db_path):
                pass

        asyncio.run(_create_db())

        with patch(
            "summon_claude.sessions.registry._default_db_path",
            return_value=db_path,
        ):
            result = runner.invoke(cli, ["db", "vacuum"])
        assert result.exit_code == 0
        assert "Integrity: ok" in result.output
        assert "Size:" in result.output


class TestDbPurge:
    def test_db_purge_deletes_old_rows(self, tmp_path):
        """'db purge --older-than 1' should delete sessions older than 1 day."""
        runner = CliRunner()
        db_path = tmp_path / "registry.db"
        old_ts = (datetime.now(UTC) - timedelta(days=5)).isoformat()

        async def _seed():
            async with SessionRegistry(db_path=db_path) as reg:
                await reg.register("old-sess-1", 111, "/tmp")
                await reg.update_status("old-sess-1", "completed")
                # Backdate the started_at to make it "old"
                await reg.db.execute(
                    "UPDATE sessions SET started_at = ? WHERE session_id = ?",
                    (old_ts, "old-sess-1"),
                )
                await reg.db.commit()

        asyncio.run(_seed())

        with patch(
            "summon_claude.sessions.registry._default_db_path",
            return_value=db_path,
        ):
            result = runner.invoke(cli, ["db", "purge", "--older-than", "1", "--yes"])
        assert result.exit_code == 0
        assert "Sessions:" in result.output
        # At least 1 session should have been purged
        assert "Sessions:    1" in result.output

    def test_db_purge_keeps_recent(self, tmp_path):
        """'db purge' should not delete recent sessions."""
        runner = CliRunner()
        db_path = tmp_path / "registry.db"

        async def _seed():
            async with SessionRegistry(db_path=db_path) as reg:
                await reg.register("recent-sess", 222, "/tmp")
                await reg.update_status("recent-sess", "completed")

        asyncio.run(_seed())

        with patch(
            "summon_claude.sessions.registry._default_db_path",
            return_value=db_path,
        ):
            result = runner.invoke(cli, ["db", "purge", "--older-than", "30", "--yes"])
        assert result.exit_code == 0
        assert "Sessions:    0" in result.output


class TestConfigCheckDbValidation:
    """Tests for schema version and integrity checks in 'config check'."""

    def test_config_check_reports_schema_version(self, tmp_path):
        """'config check' should report schema version as PASS."""
        runner = CliRunner()
        config_file = tmp_path / "config.env"
        config_file.write_text(
            "SUMMON_SLACK_BOT_TOKEN=xoxb-valid-token\n"
            "SUMMON_SLACK_APP_TOKEN=xapp-valid-token\n"
            "SUMMON_SLACK_SIGNING_SECRET=abcd1234\n"
        )

        with (
            patch("summon_claude.cli.config.get_config_file", return_value=config_file),
            patch("summon_claude.cli.config.get_data_dir", return_value=tmp_path),
        ):
            result = runner.invoke(cli, ["config", "check"])
        assert "[PASS] Schema version 1 (current)" in result.output

    def test_config_check_reports_integrity(self, tmp_path):
        """'config check' should report database integrity OK."""
        runner = CliRunner()
        config_file = tmp_path / "config.env"
        config_file.write_text(
            "SUMMON_SLACK_BOT_TOKEN=xoxb-valid-token\n"
            "SUMMON_SLACK_APP_TOKEN=xapp-valid-token\n"
            "SUMMON_SLACK_SIGNING_SECRET=abcd1234\n"
        )

        with (
            patch("summon_claude.cli.config.get_config_file", return_value=config_file),
            patch("summon_claude.cli.config.get_data_dir", return_value=tmp_path),
        ):
            result = runner.invoke(cli, ["config", "check"])
        assert "[PASS] Database integrity OK" in result.output
