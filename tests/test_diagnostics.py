"""Unit tests for summon_claude.diagnostics module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from summon_claude.config import SummonConfig
from summon_claude.diagnostics import (
    DIAGNOSTIC_REGISTRY,
    KNOWN_SUBSYSTEMS,
    CheckResult,
    DaemonCheck,
    DatabaseCheck,
    DiagnosticCheck,
    EnvironmentCheck,
    GitHubMcpCheck,
    LogsCheck,
    Redactor,
    SlackCheck,
    WorkspaceMcpCheck,
    redactor,
)

# ---------------------------------------------------------------------------
# CheckResult tests
# ---------------------------------------------------------------------------


class TestCheckResult:
    def test_construction_defaults(self) -> None:
        r = CheckResult(status="pass", subsystem="test", message="ok")
        assert r.status == "pass"
        assert r.subsystem == "test"
        assert r.message == "ok"
        assert r.details == []
        assert r.suggestion is None
        assert r.collected_logs == {}

    def test_construction_full(self) -> None:
        r = CheckResult(
            status="fail",
            subsystem="db",
            message="bad",
            details=["detail1"],
            suggestion="fix it",
            collected_logs={"log.txt": ["line1"]},
        )
        assert r.status == "fail"
        assert r.details == ["detail1"]
        assert r.suggestion == "fix it"
        assert r.collected_logs == {"log.txt": ["line1"]}

    def test_frozen(self) -> None:
        r = CheckResult(status="pass", subsystem="test", message="ok")
        with pytest.raises(AttributeError):
            r.status = "fail"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Redactor tests
# ---------------------------------------------------------------------------


class TestRedactor:
    def test_redact_secrets(self) -> None:
        text = "token is xoxb-abc-123-def"
        result = redactor.redact(text)
        assert "xoxb-" not in result
        assert "[REDACTED]" in result

    def test_redact_home_dir(self) -> None:
        home = str(Path.home())
        text = f"path is {home}/projects/test"
        result = redactor.redact(text)
        assert home not in result
        assert "~/projects/test" in result

    def test_redact_slack_user_id(self) -> None:
        text = "user U0123456789 sent message"
        result = redactor.redact(text)
        assert "U0123456789" not in result
        assert "U***" in result

    def test_redact_slack_channel_id(self) -> None:
        text = "channel C0123456789 created"
        result = redactor.redact(text)
        assert "C0123456789" not in result
        assert "C***" in result

    def test_redact_slack_team_id(self) -> None:
        text = "team T0123456789 connected"
        result = redactor.redact(text)
        assert "T0123456789" not in result
        assert "T***" in result

    def test_redact_slack_bot_id(self) -> None:
        text = "bot B0123456789 active"
        result = redactor.redact(text)
        assert "B0123456789" not in result
        assert "B***" in result

    def test_redact_uuid(self) -> None:
        text = "session 12345678-abcd-1234-abcd-1234567890ab running"
        result = redactor.redact(text)
        assert "12345678-abcd-1234-abcd-1234567890ab" not in result
        assert "12345678..." in result

    def test_redact_no_sensitive_data(self) -> None:
        text = "all is well"
        assert redactor.redact(text) == "all is well"

    def test_redact_composition(self) -> None:
        home = str(Path.home())
        text = (
            f"xoxb-secret at {home}/proj "
            "for U0123456789 in C0123456789 "
            "session 12345678-abcd-1234-abcd-1234567890ab"
        )
        result = redactor.redact(text)
        assert "xoxb-" not in result
        assert home not in result
        assert "U0123456789" not in result
        assert "C0123456789" not in result
        assert "12345678-abcd-1234-abcd-1234567890ab" not in result

    def test_redact_github_tokens(self) -> None:
        for token in ("ghp_abc123", "github_pat_abc123", "gho_xyz"):
            result = redactor.redact(f"token: {token}")
            assert token not in result

    def test_redact_anthropic_key(self) -> None:
        text = "key is sk-ant-api01-abcdef"
        result = redactor.redact(text)
        assert "sk-ant-" not in result

    def test_redactor_is_instance(self) -> None:
        assert isinstance(redactor, Redactor)


# ---------------------------------------------------------------------------
# EnvironmentCheck tests
# ---------------------------------------------------------------------------


class TestEnvironmentCheck:
    @pytest.fixture()
    def check(self) -> EnvironmentCheck:
        return EnvironmentCheck()

    async def test_all_tools_present(self, check: EnvironmentCheck) -> None:
        with (
            patch("summon_claude.diagnostics.shutil.which", return_value="/usr/bin/tool"),
            patch(
                "summon_claude.diagnostics._get_version",
                return_value="1.0.0",
            ),
        ):
            result = await check.run(None)
        assert result.status == "pass"
        assert result.subsystem == "environment"

    async def test_claude_missing(self, check: EnvironmentCheck) -> None:
        def which_side_effect(name: str) -> str | None:
            return None if name == "claude" else "/usr/bin/" + name

        with (
            patch(
                "summon_claude.diagnostics.shutil.which",
                side_effect=which_side_effect,
            ),
            patch(
                "summon_claude.diagnostics._get_version",
                return_value="1.0.0",
            ),
        ):
            result = await check.run(None)
        assert result.status == "fail"

    async def test_python_version_check(self, check: EnvironmentCheck) -> None:
        """Python >= 3.12 should pass (running tests requires 3.12+)."""
        with (
            patch("summon_claude.diagnostics.shutil.which", return_value="/usr/bin/tool"),
            patch(
                "summon_claude.diagnostics._get_version",
                return_value="1.0.0",
            ),
        ):
            result = await check.run(None)
        assert result.status == "pass"
        assert any("Python" in d for d in result.details)


# ---------------------------------------------------------------------------
# DaemonCheck tests
# ---------------------------------------------------------------------------


class TestDaemonCheck:
    @pytest.fixture()
    def check(self) -> DaemonCheck:
        return DaemonCheck()

    async def test_daemon_running(self, check: DaemonCheck) -> None:
        mock_reg = MagicMock()
        mock_reg.__aenter__ = AsyncMock(return_value=mock_reg)
        mock_reg.__aexit__ = AsyncMock(return_value=False)
        mock_reg.db = MagicMock()
        mock_reg.db.execute_fetchall = AsyncMock(return_value=[(0,)])

        with (
            patch(
                "summon_claude.daemon.is_daemon_running",
                return_value=True,
            ),
            patch(
                "summon_claude.daemon._daemon_socket",
                return_value=Path("/tmp/test.sock"),
            ),
            patch(
                "summon_claude.daemon._daemon_pid",
                return_value=Path("/tmp/nonexistent.pid"),
            ),
            patch(
                "summon_claude.sessions.registry.SessionRegistry",
                return_value=mock_reg,
            ),
        ):
            result = await check.run(None)
        assert result.status == "pass"

    async def test_daemon_not_running_clean(self, check: DaemonCheck) -> None:
        """When daemon isn't running and no stale files, status is info."""
        result = await check.run(None)
        # This test just verifies the check runs without error.
        # Status depends on actual system state — daemon may or may not be running.
        assert result.status in ("pass", "info", "warn")
        assert result.subsystem == "daemon"


# ---------------------------------------------------------------------------
# DatabaseCheck tests
# ---------------------------------------------------------------------------


class TestDatabaseCheck:
    @pytest.fixture()
    def check(self) -> DatabaseCheck:
        return DatabaseCheck()

    async def test_db_missing(self, check: DatabaseCheck, tmp_path: Path) -> None:
        with patch(
            "summon_claude.config.get_data_dir",
            return_value=tmp_path / "nonexistent",
        ):
            result = await check.run(None)
        assert result.status == "warn"
        assert "not found" in result.message.lower()


# ---------------------------------------------------------------------------
# SlackCheck tests
# ---------------------------------------------------------------------------


class TestSlackCheck:
    @pytest.fixture()
    def check(self) -> SlackCheck:
        return SlackCheck()

    async def test_skip_no_config(self, check: SlackCheck) -> None:
        result = await check.run(None)
        assert result.status == "skip"

    async def test_skip_no_token(self, check: SlackCheck) -> None:
        config = SummonConfig.for_test(slack_bot_token="")
        result = await check.run(config)
        assert result.status == "skip"

    async def test_auth_test_pass(self, check: SlackCheck) -> None:
        config = SummonConfig.for_test()
        mock_client = MagicMock()
        mock_client.auth_test.return_value = {
            "ok": True,
            "team": "test-team",
            "user": "test-bot",
        }
        with patch(
            "slack_sdk.WebClient",
            return_value=mock_client,
        ):
            result = await check.run(config)
        assert result.status == "pass"
        # SEC-003: workspace name should NOT be in message
        assert "test-team" not in result.message

    async def test_auth_test_fail(self, check: SlackCheck) -> None:
        config = SummonConfig.for_test()
        mock_client = MagicMock()
        mock_client.auth_test.return_value = {
            "ok": False,
            "error": "invalid_auth",
        }
        with patch(
            "slack_sdk.WebClient",
            return_value=mock_client,
        ):
            result = await check.run(config)
        assert result.status == "fail"


# ---------------------------------------------------------------------------
# LogsCheck tests
# ---------------------------------------------------------------------------


class TestLogsCheck:
    @pytest.fixture()
    def check(self) -> LogsCheck:
        return LogsCheck()

    async def test_no_log_directory(self, check: LogsCheck, tmp_path: Path) -> None:
        with patch(
            "summon_claude.config.get_data_dir",
            return_value=tmp_path / "nonexistent",
        ):
            result = await check.run(None)
        assert result.status == "info"
        assert "fresh install" in result.message.lower()

    async def test_logs_with_content(self, check: LogsCheck, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        daemon_log = log_dir / "daemon.log"
        daemon_log.write_text(
            "2025-01-01 ERROR something failed\n"
            "2025-01-01 WARNING something warned\n"
            "2025-01-01 INFO all good\n"
        )
        with patch(
            "summon_claude.config.get_data_dir",
            return_value=tmp_path,
        ):
            result = await check.run(None)
        assert result.status == "info"
        assert "daemon.log" in result.collected_logs
        assert any("1 errors" in d for d in result.details)

    async def test_redaction_applied(self, check: LogsCheck, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        daemon_log = log_dir / "daemon.log"
        home = str(Path.home())
        daemon_log.write_text(f"path is {home}/secret/project\ntoken is xoxb-abc-123-def\n")
        with patch(
            "summon_claude.config.get_data_dir",
            return_value=tmp_path,
        ):
            result = await check.run(None)
        logs = result.collected_logs.get("daemon.log", [])
        for line in logs:
            assert home not in line
            assert "xoxb-" not in line


# ---------------------------------------------------------------------------
# WorkspaceMcpCheck tests
# ---------------------------------------------------------------------------


class TestWorkspaceMcpCheck:
    @pytest.fixture()
    def check(self) -> WorkspaceMcpCheck:
        return WorkspaceMcpCheck()

    async def test_skip_no_config(self, check: WorkspaceMcpCheck) -> None:
        result = await check.run(None)
        assert result.status == "skip"

    async def test_skip_scribe_disabled(self, check: WorkspaceMcpCheck) -> None:
        config = SummonConfig.for_test(scribe_enabled=False)
        result = await check.run(config)
        assert result.status == "skip"


# ---------------------------------------------------------------------------
# GitHubMcpCheck tests
# ---------------------------------------------------------------------------


class TestGitHubMcpCheck:
    @pytest.fixture()
    def check(self) -> GitHubMcpCheck:
        return GitHubMcpCheck()

    async def test_skip_no_config_no_github_auth(self, check: GitHubMcpCheck) -> None:
        """Skip when github_auth doesn't exist and no config."""
        result = await check.run(None)
        assert result.status == "skip"

    async def test_skip_no_pat(self, check: GitHubMcpCheck) -> None:
        """Skip when no PAT configured and github_auth doesn't exist."""
        config = SummonConfig.for_test(github_pat=None)
        result = await check.run(config)
        assert result.status == "skip"


# ---------------------------------------------------------------------------
# CLI doctor tests
# ---------------------------------------------------------------------------


class TestDoctorCli:
    def test_format_status_pass(self) -> None:
        from summon_claude.cli.doctor import _format_status

        result = _format_status("pass", color=False)
        assert result == "[PASS]"

    def test_format_status_fail(self) -> None:
        from summon_claude.cli.doctor import _format_status

        result = _format_status("fail", color=False)
        assert result == "[FAIL]"

    def test_redact_result(self) -> None:
        from summon_claude.cli.doctor import _redact_result

        home = str(Path.home())
        r = CheckResult(
            status="pass",
            subsystem="test",
            message=f"path is {home}/secret",
            details=[f"detail with {home}"],
            collected_logs={"log": [f"line with {home}"]},
        )
        redacted = _redact_result(r)
        assert home not in redacted.message
        assert home not in redacted.details[0]
        assert home not in redacted.collected_logs["log"][0]

    def test_redact_result_keys(self) -> None:
        """Log filename keys with UUIDs should be redacted."""
        from summon_claude.cli.doctor import _redact_result

        uuid_name = "12345678-abcd-1234-abcd-1234567890ab.log"
        r = CheckResult(
            status="info",
            subsystem="logs",
            message="ok",
            collected_logs={uuid_name: ["line1"]},
        )
        redacted = _redact_result(r)
        # Full UUID should not survive in keys
        assert uuid_name not in redacted.collected_logs
        # Truncated UUID should be present
        assert any("12345678..." in k for k in redacted.collected_logs)

    def test_write_export(self, tmp_path: Path) -> None:
        """--export should write valid JSON with redacted results."""
        from summon_claude.cli.doctor import _write_export

        results = [
            CheckResult(
                status="pass",
                subsystem="test",
                message="all good",
            ),
            CheckResult(
                status="fail",
                subsystem="bad",
                message="broken",
                suggestion="fix it",
            ),
        ]
        export_path = str(tmp_path / "report.json")
        _write_export(export_path, results)

        import json

        data = json.loads(Path(export_path).read_text())
        assert data["version"] == "1.0"
        assert len(data["checks"]) == 2
        assert data["checks"][0]["status"] == "pass"
        assert data["checks"][1]["suggestion"] == "fix it"

    def test_build_submit_body(self) -> None:
        """--submit body should contain check results and escape @."""
        from summon_claude.cli.doctor import _build_submit_body

        results = [
            CheckResult(
                status="pass",
                subsystem="test",
                message="ok @user",
            ),
        ]
        body = _build_submit_body(results)
        assert "\\@user" in body
        assert "@user" not in body.replace("\\@", "")
        assert "## summon doctor report" in body

    def test_build_submit_body_logs_in_code_blocks(self) -> None:
        """Log content in submit body should be inside fenced code blocks."""
        from summon_claude.cli.doctor import _build_submit_body

        results = [
            CheckResult(
                status="info",
                subsystem="logs",
                message="logs found",
                collected_logs={"daemon.log": ["ERROR something"]},
            ),
        ]
        body = _build_submit_body(results)
        assert "```" in body


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_human_size_bytes(self) -> None:
        from summon_claude.diagnostics import _human_size

        assert _human_size(0) == "0.0 B"
        assert _human_size(512) == "512.0 B"

    def test_human_size_kb(self) -> None:
        from summon_claude.diagnostics import _human_size

        assert _human_size(1536) == "1.5 KB"

    def test_human_size_mb(self) -> None:
        from summon_claude.diagnostics import _human_size

        result = _human_size(2 * 1024 * 1024)
        assert result == "2.0 MB"

    def test_tail_file(self, tmp_path: Path) -> None:
        from summon_claude.diagnostics import _tail_file

        f = tmp_path / "test.log"
        f.write_text("\n".join(f"line{i}" for i in range(200)))
        lines = _tail_file(f, 50)
        assert len(lines) == 50
        assert lines[-1] == "line199"

    def test_tail_file_short(self, tmp_path: Path) -> None:
        from summon_claude.diagnostics import _tail_file

        f = tmp_path / "test.log"
        f.write_text("line1\nline2\nline3")
        lines = _tail_file(f, 100)
        assert len(lines) == 3

    def test_tail_file_missing(self) -> None:
        from summon_claude.diagnostics import _tail_file

        lines = _tail_file(Path("/nonexistent/file.log"), 10)
        assert lines == []
