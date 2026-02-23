"""Tests for new CLI commands: init, config show/set/path/edit."""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from summon_claude.cli import _build_parser, cmd_init
from summon_claude.cli_config import config_path, config_set, config_show


class TestParserHasInitCommand:
    def test_parser_accepts_init(self):
        parser = _build_parser()
        args = parser.parse_args(["init"])
        assert args.command == "init"


class TestParserHasConfigSubcommands:
    def test_config_show_parses(self):
        parser = _build_parser()
        args = parser.parse_args(["config", "show"])
        assert args.command == "config"
        assert args.config_command == "show"

    def test_config_path_parses(self):
        parser = _build_parser()
        args = parser.parse_args(["config", "path"])
        assert args.command == "config"
        assert args.config_command == "path"

    def test_config_edit_parses(self):
        parser = _build_parser()
        args = parser.parse_args(["config", "edit"])
        assert args.command == "config"
        assert args.config_command == "edit"

    def test_config_set_parses_key_value(self):
        parser = _build_parser()
        args = parser.parse_args(["config", "set", "SUMMON_SLACK_BOT_TOKEN", "xoxb-new"])
        assert args.command == "config"
        assert args.config_command == "set"
        assert args.key == "SUMMON_SLACK_BOT_TOKEN"
        assert args.value == "xoxb-new"


class TestCmdInit:
    def test_init_creates_config_file(self, tmp_path):
        """init should create config.env with provided values."""
        config_dir = tmp_path / "summon"
        config_file = config_dir / "config.env"

        inputs = iter(
            [
                "xoxb-valid-bot-token",  # bot token (valid)
                "xapp-valid-app-token",  # app token (valid)
                "mysecret",  # signing secret
                "U123,U456",  # allowed user IDs
            ]
        )

        with (
            patch("summon_claude.config.get_config_dir", return_value=config_dir),
            patch("summon_claude.config.get_config_file", return_value=config_file),
            patch("builtins.input", side_effect=lambda prompt: next(inputs)),
        ):
            import argparse

            args = argparse.Namespace()
            cmd_init(args)

        assert config_file.exists()
        content = config_file.read_text()
        assert "xoxb-valid-bot-token" in content
        assert "xapp-valid-app-token" in content
        assert "mysecret" in content
        assert "U123,U456" in content

    def test_init_validates_bot_token_prefix(self, tmp_path):
        """init should reject bot tokens that don't start with xoxb-."""
        config_dir = tmp_path / "summon"
        config_file = config_dir / "config.env"

        # First provide invalid, then valid
        inputs = iter(
            [
                "invalid-token",  # wrong prefix — should be rejected
                "xoxb-correct-token",  # correct
                "xapp-app-token",
                "mysecret",
                "U123",
            ]
        )

        output_lines = []
        with (
            patch("summon_claude.config.get_config_dir", return_value=config_dir),
            patch("summon_claude.config.get_config_file", return_value=config_file),
            patch("builtins.input", side_effect=lambda prompt: next(inputs)),
            patch(
                "builtins.print",
                side_effect=lambda *args, **kwargs: output_lines.append(str(args)),
            ),
        ):
            import argparse

            args = argparse.Namespace()
            cmd_init(args)

        # Error message for invalid token should have been printed
        error_msgs = [line for line in output_lines if "xoxb-" in line or "Error" in line]
        assert len(error_msgs) > 0

    def test_init_validates_app_token_prefix(self, tmp_path):
        """init should reject app tokens that don't start with xapp-."""
        config_dir = tmp_path / "summon"
        config_file = config_dir / "config.env"

        inputs = iter(
            [
                "xoxb-valid-bot",
                "invalid-app-token",  # wrong prefix
                "xapp-correct-app",  # correct
                "mysecret",
                "U123",
            ]
        )

        output_lines = []
        with (
            patch("summon_claude.config.get_config_dir", return_value=config_dir),
            patch("summon_claude.config.get_config_file", return_value=config_file),
            patch("builtins.input", side_effect=lambda prompt: next(inputs)),
            patch(
                "builtins.print",
                side_effect=lambda *args, **kwargs: output_lines.append(str(args)),
            ),
        ):
            import argparse

            args = argparse.Namespace()
            cmd_init(args)

        error_msgs = [line for line in output_lines if "xapp-" in line or "Error" in line]
        assert len(error_msgs) > 0


class TestConfigShow:
    def test_config_show_masks_bot_token(self, tmp_path, capsys):
        """config show should mask SUMMON_SLACK_BOT_TOKEN after first 8 chars."""
        config_file = tmp_path / "config.env"
        config_file.write_text(
            "SUMMON_SLACK_BOT_TOKEN=xoxb-secret-should-not-appear\n"
            "SUMMON_SLACK_APP_TOKEN=xapp-another-secret\n"
            "SUMMON_SLACK_SIGNING_SECRET=mysecretvalue12345\n"
            "SUMMON_ALLOWED_USER_IDS=U123\n"
        )

        with patch("summon_claude.config.get_config_file", return_value=config_file):
            config_show()

        captured = capsys.readouterr()
        # Full token should NOT appear
        assert "xoxb-secret-should-not-appear" not in captured.out
        # First 8 chars + "..." should appear
        assert "xoxb-sec..." in captured.out

    def test_config_show_masks_app_token(self, tmp_path, capsys):
        config_file = tmp_path / "config.env"
        config_file.write_text(
            "SUMMON_SLACK_BOT_TOKEN=xoxb-testtest\n"
            "SUMMON_SLACK_APP_TOKEN=xapp-supersecrettoken\n"
            "SUMMON_SLACK_SIGNING_SECRET=signingkey\n"
        )

        with patch("summon_claude.config.get_config_file", return_value=config_file):
            config_show()

        captured = capsys.readouterr()
        assert "xapp-supersecrettoken" not in captured.out
        assert "xapp-sup..." in captured.out

    def test_config_show_masks_signing_secret(self, tmp_path, capsys):
        config_file = tmp_path / "config.env"
        config_file.write_text(
            "SUMMON_SLACK_BOT_TOKEN=xoxb-testtest\n"
            "SUMMON_SLACK_APP_TOKEN=xapp-testtest\n"
            "SUMMON_SLACK_SIGNING_SECRET=secretsigningkeyvalue\n"
        )

        with patch("summon_claude.config.get_config_file", return_value=config_file):
            config_show()

        captured = capsys.readouterr()
        assert "secretsigningkeyvalue" not in captured.out
        assert "secretsi..." in captured.out

    def test_config_show_non_token_values_not_masked(self, tmp_path, capsys):
        config_file = tmp_path / "config.env"
        config_file.write_text(
            "SUMMON_SLACK_BOT_TOKEN=xoxb-testtest\n"
            "SUMMON_ALLOWED_USER_IDS=U123,U456\n"
            "SUMMON_DEFAULT_MODEL=claude-opus-4-6\n"
        )

        with patch("summon_claude.config.get_config_file", return_value=config_file):
            config_show()

        captured = capsys.readouterr()
        assert "U123,U456" in captured.out
        assert "claude-opus-4-6" in captured.out

    def test_config_show_no_file_prints_message(self, tmp_path, capsys):
        missing_file = tmp_path / "nonexistent.env"

        with patch("summon_claude.config.get_config_file", return_value=missing_file):
            config_show()

        captured = capsys.readouterr()
        assert "No config file" in captured.out or "summon init" in captured.out


class TestConfigSet:
    def test_config_set_updates_existing_value(self, tmp_path):
        """config set should update an existing key in config.env."""
        config_file = tmp_path / "config.env"
        config_file.write_text("SUMMON_SLACK_BOT_TOKEN=xoxb-old\nSUMMON_ALLOWED_USER_IDS=U1\n")

        with (
            patch("summon_claude.config.get_config_dir", return_value=tmp_path),
            patch("summon_claude.config.get_config_file", return_value=config_file),
        ):
            config_set("SUMMON_SLACK_BOT_TOKEN", "xoxb-new-value")

        content = config_file.read_text()
        assert "xoxb-new-value" in content
        assert "xoxb-old" not in content

    def test_config_set_adds_new_key(self, tmp_path):
        """config set should add a new key if it doesn't exist."""
        config_file = tmp_path / "config.env"
        config_file.write_text("SUMMON_ALLOWED_USER_IDS=U1\n")

        with (
            patch("summon_claude.config.get_config_dir", return_value=tmp_path),
            patch("summon_claude.config.get_config_file", return_value=config_file),
        ):
            config_set("SUMMON_DEFAULT_MODEL", "claude-haiku-3")

        content = config_file.read_text()
        assert "SUMMON_DEFAULT_MODEL=claude-haiku-3" in content

    def test_config_set_creates_file_if_not_exists(self, tmp_path):
        """config set should create the config file if it doesn't exist yet."""
        config_dir = tmp_path / "newdir"
        config_dir.mkdir()
        config_file = config_dir / "config.env"

        with (
            patch("summon_claude.config.get_config_dir", return_value=config_dir),
            patch("summon_claude.config.get_config_file", return_value=config_file),
        ):
            config_set("SUMMON_CHANNEL_PREFIX", "myprefix")

        assert config_file.exists()
        content = config_file.read_text()
        assert "SUMMON_CHANNEL_PREFIX=myprefix" in content

    def test_config_set_preserves_other_lines(self, tmp_path):
        """config set should not modify other lines in the file."""
        config_file = tmp_path / "config.env"
        config_file.write_text("SUMMON_SLACK_BOT_TOKEN=xoxb-keep\nSUMMON_ALLOWED_USER_IDS=U1,U2\n")

        with (
            patch("summon_claude.config.get_config_dir", return_value=tmp_path),
            patch("summon_claude.config.get_config_file", return_value=config_file),
        ):
            config_set("SUMMON_ALLOWED_USER_IDS", "U3,U4")

        content = config_file.read_text()
        assert "xoxb-keep" in content
        assert "U3,U4" in content
        assert "U1,U2" not in content


class TestConfigPath:
    def test_config_path_prints_location(self, tmp_path, capsys):
        """config path should print the config file location."""
        expected_path = tmp_path / "summon" / "config.env"

        with patch("summon_claude.config.get_config_file", return_value=expected_path):
            config_path()

        captured = capsys.readouterr()
        assert str(expected_path) in captured.out
