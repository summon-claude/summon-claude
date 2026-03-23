"""Tests for scripts/docs-screenshots.py pure-Python functions.

Tests the independently testable logic: string processors, content
validation, terminal block injection, and capture caching.  Does NOT
test Playwright/Slack/subprocess integration (those require real
credentials and a running workspace).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# The script lives in scripts/, not in a package.  Add it to sys.path
# so we can import its module-level functions.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

docs_screenshots = importlib.import_module("docs-screenshots")

_sanitize_paths = docs_screenshots._sanitize_paths
_add_start_annotations = docs_screenshots._add_start_annotations
_validate_content = docs_screenshots._validate_content
_inject_terminal_block = docs_screenshots._inject_terminal_block
_run_capture = docs_screenshots._run_capture
_capture_cache = docs_screenshots._capture_cache
CaptureSpec = docs_screenshots.CaptureSpec


# ---------------------------------------------------------------------------
# _sanitize_paths
# ---------------------------------------------------------------------------


class TestSanitizePaths:
    def test_replaces_home_dir(self) -> None:
        home = str(Path.home())
        assert _sanitize_paths(f"{home}/projects/foo") == "~/projects/foo"

    def test_replaces_multiple_occurrences(self) -> None:
        home = str(Path.home())
        text = f"config: {home}/.config\ndata: {home}/.local"
        result = _sanitize_paths(text)
        assert home not in result
        assert result.count("~") == 2

    def test_no_home_dir_unchanged(self) -> None:
        assert _sanitize_paths("no paths here") == "no paths here"

    def test_empty_string(self) -> None:
        assert _sanitize_paths("") == ""


# ---------------------------------------------------------------------------
# _add_start_annotations
# ---------------------------------------------------------------------------


class TestAddStartAnnotations:
    def test_annotates_summon_code_line(self) -> None:
        banner = "==============\n  SUMMON CODE: abc123\n=============="
        result = _add_start_annotations(banner)
        assert "SUMMON CODE: abc123  # (1)" in result

    def test_annotates_expires_line(self) -> None:
        banner = "==============\n  Expires in 5 minutes\n=============="
        result = _add_start_annotations(banner)
        assert "Expires in 5 minutes  # (2)" in result

    def test_leaves_other_lines_unchanged(self) -> None:
        banner = "==============\n  Type in Slack: /summon abc\n=============="
        result = _add_start_annotations(banner)
        assert "  Type in Slack: /summon abc" in result
        assert "# (" not in result.split("\n")[1]

    def test_full_banner(self) -> None:
        banner = (
            "==================================================\n"
            "  SUMMON CODE: a7f3b219\n"
            "  Type in Slack: /summon a7f3b219\n"
            "  Expires in 5 minutes\n"
            "=================================================="
        )
        result = _add_start_annotations(banner)
        lines = result.split("\n")
        assert lines[1].endswith("  # (1)")
        assert lines[3].endswith("  # (2)")
        assert "# (" not in lines[0]
        assert "# (" not in lines[2]
        assert "# (" not in lines[4]


# ---------------------------------------------------------------------------
# _validate_content
# ---------------------------------------------------------------------------


class TestValidateContent:
    def test_safe_content_returns_none(self) -> None:
        assert _validate_content("normal output text", "foo") is None

    def test_rejects_opening_marker(self) -> None:
        result = _validate_content("<!-- terminal:foo -->", "foo")
        assert result is not None
        assert "opening" in result

    def test_rejects_closing_marker(self) -> None:
        result = _validate_content("<!-- /terminal:foo -->", "foo")
        assert result is not None
        assert "closing" in result

    def test_rejects_triple_backticks(self) -> None:
        result = _validate_content("some ```code``` here", "foo")
        assert result is not None
        assert "backtick" in result.lower()

    def test_marker_name_is_specific(self) -> None:
        # A different marker name should not trigger rejection
        assert _validate_content("<!-- terminal:bar -->", "foo") is None
        assert _validate_content("<!-- /terminal:bar -->", "foo") is None

    def test_empty_content(self) -> None:
        assert _validate_content("", "foo") is None


# ---------------------------------------------------------------------------
# _inject_terminal_block
# ---------------------------------------------------------------------------


class TestInjectTerminalBlock:
    def test_replaces_content_between_markers(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text(
            "# Title\n"
            "<!-- terminal:ver -->\n"
            "```text\nold content\n```\n"
            "<!-- /terminal:ver -->\n"
            "## Footer\n"
        )
        result = _inject_terminal_block(md, "ver", "new content")
        assert result is True
        text = md.read_text()
        assert "new content" in text
        assert "old content" not in text
        assert "## Footer" in text

    def test_handles_empty_marker_pair(self, tmp_path: Path) -> None:
        """Regression: empty markers (no content between them) must match."""
        md = tmp_path / "test.md"
        md.write_text("before\n<!-- terminal:x -->\n<!-- /terminal:x -->\nafter\n")
        result = _inject_terminal_block(md, "x", "injected")
        assert result is True
        text = md.read_text()
        assert "injected" in text
        assert "after" in text

    def test_returns_false_when_marker_absent(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("# No markers here\n")
        result = _inject_terminal_block(md, "missing", "content")
        assert result is False
        assert md.read_text() == "# No markers here\n"

    def test_preserves_surrounding_content(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text(
            "line1\n<!-- terminal:m -->\n```text\nold\n```\n<!-- /terminal:m -->\nline2\n"
        )
        _inject_terminal_block(md, "m", "new")
        text = md.read_text()
        assert text.startswith("line1\n")
        assert text.endswith("line2\n")

    def test_custom_fence_language(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("<!-- terminal:t -->\n<!-- /terminal:t -->\n")
        _inject_terminal_block(md, "t", "code", fence="python")
        text = md.read_text()
        assert "```python\n" in text

    def test_extra_md_appended(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("<!-- terminal:t -->\n<!-- /terminal:t -->\n")
        _inject_terminal_block(md, "t", "code", extra_md="\n1. Note one")
        text = md.read_text()
        assert "\n1. Note one" in text

    def test_multiple_markers_same_name(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text(
            "<!-- terminal:x -->\n```text\nA\n```\n<!-- /terminal:x -->\n"
            "gap\n"
            "<!-- terminal:x -->\n```text\nB\n```\n<!-- /terminal:x -->\n"
        )
        _inject_terminal_block(md, "x", "replaced")
        text = md.read_text()
        assert text.count("replaced") == 2
        assert "gap" in text


# ---------------------------------------------------------------------------
# _run_capture (cache behavior)
# ---------------------------------------------------------------------------


class TestRunCaptureCache:
    def setup_method(self) -> None:
        _capture_cache.clear()

    def teardown_method(self) -> None:
        _capture_cache.clear()

    def test_custom_capture_is_cached(self) -> None:
        fn = MagicMock(return_value="captured output")
        spec = CaptureSpec(marker="test", md_file="fake.md", command=[], capture_fn=fn)

        result1 = _run_capture(spec)
        result2 = _run_capture(spec)

        assert result1 == "captured output"
        assert result2 == "captured output"
        fn.assert_called_once()

    def test_custom_capture_failure_returns_none(self) -> None:
        fn = MagicMock(side_effect=RuntimeError("boom"))
        spec = CaptureSpec(marker="test", md_file="fake.md", command=[], capture_fn=fn)

        result = _run_capture(spec)
        assert result is None

    def test_cache_shared_across_specs_with_same_fn(self) -> None:
        fn = MagicMock(return_value="shared")
        spec1 = CaptureSpec(marker="a", md_file="a.md", command=[], capture_fn=fn)
        spec2 = CaptureSpec(marker="b", md_file="b.md", command=[], capture_fn=fn)

        r1 = _run_capture(spec1)
        r2 = _run_capture(spec2)

        assert r1 == r2 == "shared"
        fn.assert_called_once()

    def test_subprocess_success_returns_stripped_stdout(self, monkeypatch) -> None:
        import subprocess as sp

        mock_result = MagicMock(returncode=0, stdout="  output\n")
        monkeypatch.setattr(sp, "run", MagicMock(return_value=mock_result))
        spec = CaptureSpec(marker="t", md_file="f.md", command=["summon", "--version"])
        assert _run_capture(spec) == "output"

    def test_subprocess_nonzero_returns_none(self, monkeypatch) -> None:
        import subprocess as sp

        mock_result = MagicMock(returncode=1, stderr="error msg")
        monkeypatch.setattr(sp, "run", MagicMock(return_value=mock_result))
        spec = CaptureSpec(marker="t", md_file="f.md", command=["summon", "--version"])
        assert _run_capture(spec) is None

    def test_subprocess_timeout_returns_none(self, monkeypatch) -> None:
        import subprocess as sp

        monkeypatch.setattr(sp, "run", MagicMock(side_effect=sp.TimeoutExpired(cmd=[], timeout=1)))
        spec = CaptureSpec(marker="t", md_file="f.md", command=["summon", "--version"])
        assert _run_capture(spec) is None
