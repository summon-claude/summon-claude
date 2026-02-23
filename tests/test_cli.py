"""Tests for summon_claude.cli."""

from __future__ import annotations

import argparse

from summon_claude.cli import (
    _build_parser,
    _format_ts,
    _print_session_detail,
    _print_session_table,
    _truncate,
)


class TestBuildParser:
    def test_parser_created_successfully(self):
        parser = _build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_has_start_command(self):
        parser = _build_parser()
        args = parser.parse_args(["start"])
        assert args.command == "start"

    def test_parser_has_status_command(self):
        parser = _build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_parser_has_stop_command(self):
        parser = _build_parser()
        args = parser.parse_args(["stop", "session-id"])
        assert args.command == "stop"
        assert args.session_id == "session-id"

    def test_parser_has_sessions_command(self):
        parser = _build_parser()
        args = parser.parse_args(["sessions"])
        assert args.command == "sessions"

    def test_parser_has_cleanup_command(self):
        parser = _build_parser()
        args = parser.parse_args(["cleanup"])
        assert args.command == "cleanup"

    def test_start_accepts_cwd_option(self):
        parser = _build_parser()
        args = parser.parse_args(["start", "--cwd", "/tmp"])
        assert args.cwd == "/tmp"

    def test_start_accepts_name_option(self):
        parser = _build_parser()
        args = parser.parse_args(["start", "--name", "my-session"])
        assert args.name == "my-session"

    def test_start_accepts_model_option(self):
        parser = _build_parser()
        args = parser.parse_args(["start", "--model", "claude-opus-4-6"])
        assert args.model == "claude-opus-4-6"

    def test_start_accepts_resume_option(self):
        parser = _build_parser()
        args = parser.parse_args(["start", "--resume", "sess-123"])
        assert args.resume == "sess-123"

    def test_verbose_flag_supported(self):
        parser = _build_parser()
        args = parser.parse_args(["-v", "status"])
        assert args.verbose is True

    def test_status_accepts_session_id(self):
        parser = _build_parser()
        args = parser.parse_args(["status", "sess-id"])
        assert args.session_id == "sess-id"

    def test_status_session_id_optional(self):
        parser = _build_parser()
        args = parser.parse_args(["status"])
        assert args.session_id is None


class TestPrintSessionTable:
    def test_empty_list(self, capsys):
        sessions = []
        _print_session_table(sessions)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_prints_session_data(self, capsys):
        sessions = [
            {
                "session_id": "sess-1",
                "status": "active",
                "session_name": "my-session",
                "slack_channel_name": "summon-my-session-0222",
                "cwd": "/tmp",
                "total_turns": 5,
                "total_cost_usd": 0.0123,
            }
        ]
        _print_session_table(sessions)
        captured = capsys.readouterr()
        assert "active" in captured.out
        assert "5" in captured.out

    def test_handles_none_values(self, capsys):
        sessions = [
            {
                "session_id": "sess-x",
                "status": "pending_auth",
                "session_name": None,
                "slack_channel_name": None,
                "cwd": "/home",
                "total_turns": 0,
                "total_cost_usd": 0.0,
            }
        ]
        _print_session_table(sessions)
        captured = capsys.readouterr()
        assert "pending_auth" in captured.out


class TestPrintSessionDetail:
    def test_prints_session_fields(self, capsys):
        session = {
            "session_id": "sess-123",
            "status": "active",
            "pid": 12345,
            "cwd": "/tmp",
            "model": "claude-opus-4-6",
            "slack_channel_id": "C123",
            "slack_channel_name": "summon-test",
            "started_at": "2025-02-22T10:00:00+00:00",
            "total_turns": 3,
            "total_cost_usd": 0.05,
        }
        _print_session_detail(session)
        captured = capsys.readouterr()
        assert "sess-123" in captured.out
        assert "active" in captured.out

    def test_includes_error_message_if_present(self, capsys):
        session = {
            "session_id": "sess-err",
            "status": "errored",
            "pid": 999,
            "cwd": "/tmp",
            "error_message": "Connection failed",
        }
        _print_session_detail(session)
        captured = capsys.readouterr()
        assert "Connection failed" in captured.out


class TestTruncate:
    def test_short_string_not_truncated(self):
        result = _truncate("hello", 10)
        assert result == "hello"

    def test_long_string_truncated(self):
        result = _truncate("hello world this is long", 10)
        assert len(result) <= 10
        assert "..." in result

    def test_exactly_at_limit(self):
        result = _truncate("hello", 5)
        assert result == "hello"

    def test_one_over_limit(self):
        result = _truncate("hello!", 5)
        assert len(result) <= 5
        assert "..." in result


class TestFormatTs:
    def test_valid_iso_timestamp(self):
        result = _format_ts("2025-02-22T10:30:45+00:00")
        assert isinstance(result, str)
        assert "2025" in result or "10:30" in result

    def test_none_returns_dash(self):
        result = _format_ts(None)
        assert result == "-"

    def test_empty_string_returns_dash(self):
        result = _format_ts("")
        assert result == "-"

    def test_invalid_format_returns_as_is(self):
        result = _format_ts("not-a-timestamp")
        assert result == "not-a-timestamp"
