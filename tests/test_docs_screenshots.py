"""Tests for scripts/docs-screenshots.py pure-Python functions.

Tests the independently testable logic: string processors, content
validation, terminal block injection, and capture caching.  Does NOT
test Playwright/Slack/subprocess integration (those require real
credentials and a running workspace).
"""

from __future__ import annotations

import importlib
import os
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
_make_env = docs_screenshots._make_env
_capture_summon_start_banner = docs_screenshots._capture_summon_start_banner
run_terminal_section = docs_screenshots.run_terminal_section
CaptureSpec = docs_screenshots.CaptureSpec
CAPTURES = docs_screenshots.CAPTURES
REPO_ROOT = Path(__file__).resolve().parent.parent


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

    def test_subprocess_passes_env_without_claudecode(self, monkeypatch) -> None:
        import subprocess as sp

        monkeypatch.setenv("CLAUDECODE", "1")
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="ok\n"))
        monkeypatch.setattr(sp, "run", mock_run)
        spec = CaptureSpec(marker="t", md_file="f.md", command=["summon", "--version"])
        _run_capture(spec)
        call_kwargs = mock_run.call_args[1]
        assert "env" in call_kwargs, "_run_capture must pass env= to subprocess.run"
        assert "CLAUDECODE" not in call_kwargs["env"]


# ---------------------------------------------------------------------------
# _make_env
# ---------------------------------------------------------------------------


class TestMakeEnv:
    def test_strips_claudecode(self, monkeypatch) -> None:
        monkeypatch.setenv("CLAUDECODE", "1")
        env = _make_env()
        assert "CLAUDECODE" not in env

    def test_preserves_other_vars(self) -> None:
        env = _make_env()
        assert "PATH" in env

    def test_returns_copy_not_original(self) -> None:
        env = _make_env()
        env["SENTINEL"] = "1"
        assert "SENTINEL" not in os.environ


# ---------------------------------------------------------------------------
# _capture_summon_start_banner
# ---------------------------------------------------------------------------


def _make_fake_popen(lines: list[str], *, exit_code: int = 0):
    """Build a MagicMock that behaves like subprocess.Popen with controlled stdout."""
    line_iter = iter(lines)
    proc = MagicMock()
    proc.poll.return_value = None

    def smart_readline():
        val = next(line_iter, None)
        if val is None:
            proc.poll.return_value = exit_code
            return ""
        return val

    proc.stdout.readline.side_effect = smart_readline
    proc.terminate.return_value = None
    proc.wait.return_value = exit_code
    proc.kill.return_value = None
    return proc


class TestCaptureSummonStartBanner:
    def test_captures_full_banner(self, monkeypatch) -> None:
        lines = [
            "==================================================\n",
            "  SUMMON CODE: a7f3b219\n",
            "  Type in Slack: /summon a7f3b219\n",
            "  Expires in 5 minutes\n",
            "==================================================\n",
        ]
        proc = _make_fake_popen(lines)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: proc)
        monkeypatch.setattr("subprocess.run", MagicMock())

        result = _capture_summon_start_banner()
        assert "SUMMON CODE: a7f3b219" in result
        assert "Expires in 5 minutes" in result
        # Should have opening border, 3 content lines, closing border
        result_lines = result.split("\n")
        assert len(result_lines) == 5

    def test_captures_banner_with_empty_lines(self, monkeypatch) -> None:
        lines = [
            "==================================================\n",
            "  SUMMON CODE: abc123\n",
            "\n",
            "  Expires in 5 minutes\n",
            "==================================================\n",
        ]
        proc = _make_fake_popen(lines)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: proc)
        monkeypatch.setattr("subprocess.run", MagicMock())

        result = _capture_summon_start_banner()
        # Empty line inside banner should be preserved
        assert "\n\n" in result or result.count("\n") >= 4

    def test_ignores_lines_before_banner(self, monkeypatch) -> None:
        lines = [
            "some startup noise\n",
            "more noise\n",
            "==================================================\n",
            "  SUMMON CODE: xyz789\n",
            "  Type in Slack: /summon xyz789\n",
            "  Expires in 5 minutes\n",
            "==================================================\n",
        ]
        proc = _make_fake_popen(lines)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: proc)
        monkeypatch.setattr("subprocess.run", MagicMock())

        result = _capture_summon_start_banner()
        assert "startup noise" not in result
        assert "SUMMON CODE: xyz789" in result

    def test_raises_on_too_few_lines(self, monkeypatch) -> None:
        lines = [
            "==================================================\n",
            "==================================================\n",
        ]
        proc = _make_fake_popen(lines)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: proc)
        monkeypatch.setattr("subprocess.run", MagicMock())

        with pytest.raises(RuntimeError, match="Failed to capture auth banner"):
            _capture_summon_start_banner()

    def test_raises_on_empty_output(self, monkeypatch) -> None:
        proc = _make_fake_popen([])
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: proc)
        monkeypatch.setattr("subprocess.run", MagicMock())

        with pytest.raises(RuntimeError, match="Failed to capture auth banner"):
            _capture_summon_start_banner()

    def test_terminates_process_on_success(self, monkeypatch) -> None:
        lines = [
            "==================================================\n",
            "  SUMMON CODE: abc\n",
            "  Type in Slack: /summon abc\n",
            "  Expires in 5 minutes\n",
            "==================================================\n",
        ]
        proc = _make_fake_popen(lines)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: proc)
        monkeypatch.setattr("subprocess.run", MagicMock())

        _capture_summon_start_banner()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()

    def test_terminates_process_on_failure(self, monkeypatch) -> None:
        proc = _make_fake_popen([])
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: proc)
        monkeypatch.setattr("subprocess.run", MagicMock())

        with pytest.raises(RuntimeError):
            _capture_summon_start_banner()
        proc.terminate.assert_called_once()


# ---------------------------------------------------------------------------
# _inject_terminal_block — special characters
# ---------------------------------------------------------------------------


class TestInjectTerminalBlockSpecialChars:
    def test_backslash_content_preserved(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("<!-- terminal:t -->\n<!-- /terminal:t -->\n")
        _inject_terminal_block(md, "t", "path\\to\\file")
        text = md.read_text()
        assert "path\\to\\file" in text

    def test_dollar_sign_content_preserved(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("<!-- terminal:t -->\n<!-- /terminal:t -->\n")
        _inject_terminal_block(md, "t", "cost: $1.23")
        text = md.read_text()
        assert "cost: $1.23" in text

    def test_backreference_pattern_preserved(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("<!-- terminal:t -->\n<!-- /terminal:t -->\n")
        _inject_terminal_block(md, "t", "group \\1 match")
        text = md.read_text()
        assert "group \\1 match" in text

    def test_hyphenated_marker_name(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text(
            "<!-- terminal:summon-version-short -->\n"
            "```text\nold\n```\n"
            "<!-- /terminal:summon-version-short -->\n"
        )
        result = _inject_terminal_block(md, "summon-version-short", "v1.2.3")
        assert result is True
        text = md.read_text()
        assert "v1.2.3" in text
        assert "old" not in text


# ---------------------------------------------------------------------------
# CAPTURES registry validation
# ---------------------------------------------------------------------------


class TestCapturesRegistry:
    @pytest.mark.parametrize(
        "spec",
        CAPTURES,
        ids=[f"{s.md_file}#{s.marker}" for s in CAPTURES],
    )
    def test_md_file_exists(self, spec: CaptureSpec) -> None:
        md_path = REPO_ROOT / spec.md_file
        assert md_path.exists(), f"{spec.md_file} does not exist"

    @pytest.mark.parametrize(
        "spec",
        CAPTURES,
        ids=[f"{s.md_file}#{s.marker}" for s in CAPTURES],
    )
    def test_marker_pair_exists_in_file(self, spec: CaptureSpec) -> None:
        md_path = REPO_ROOT / spec.md_file
        content = md_path.read_text()
        opening = f"<!-- terminal:{spec.marker} -->"
        closing = f"<!-- /terminal:{spec.marker} -->"
        assert opening in content, f"Missing {opening} in {spec.md_file}"
        assert closing in content, f"Missing {closing} in {spec.md_file}"


# ---------------------------------------------------------------------------
# run_terminal_section
# ---------------------------------------------------------------------------


class TestRunTerminalSection:
    def test_dry_run_returns_true(self) -> None:
        assert run_terminal_section(dry_run=True) is True

    def test_returns_true_on_success(self, tmp_path: Path, monkeypatch) -> None:
        md = tmp_path / "test.md"
        md.write_text("<!-- terminal:t -->\n```text\nold\n```\n<!-- /terminal:t -->\n")

        specs = [CaptureSpec(marker="t", md_file=str(md), command=[])]
        monkeypatch.setattr(docs_screenshots, "CAPTURES", specs)

        fn = MagicMock(return_value="new output")
        specs[0] = CaptureSpec(marker="t", md_file=str(md), command=[], capture_fn=fn)
        monkeypatch.setattr(docs_screenshots, "CAPTURES", specs)
        _capture_cache.clear()

        result = run_terminal_section(dry_run=False)
        assert result is True
        assert "new output" in md.read_text()

    def test_returns_false_when_all_fail(self, monkeypatch) -> None:
        fn = MagicMock(return_value=None)
        specs = [CaptureSpec(marker="t", md_file="fake.md", command=[], capture_fn=fn)]
        monkeypatch.setattr(docs_screenshots, "CAPTURES", specs)
        _capture_cache.clear()

        result = run_terminal_section(dry_run=False)
        assert result is False

    def test_post_process_applied(self, tmp_path: Path, monkeypatch) -> None:
        md = tmp_path / "test.md"
        md.write_text("<!-- terminal:t -->\n<!-- /terminal:t -->\n")

        processor = MagicMock(side_effect=lambda s: s.upper())
        fn = MagicMock(return_value="hello")
        specs = [
            CaptureSpec(
                marker="t", md_file=str(md), command=[], capture_fn=fn, post_process=processor
            )
        ]
        monkeypatch.setattr(docs_screenshots, "CAPTURES", specs)
        _capture_cache.clear()

        run_terminal_section(dry_run=False)
        assert "HELLO" in md.read_text()
        processor.assert_called_once_with("hello")

    def test_validation_failure_skips_inject(self, tmp_path: Path, monkeypatch) -> None:
        md = tmp_path / "test.md"
        md.write_text("<!-- terminal:t -->\n```text\nold\n```\n<!-- /terminal:t -->\n")

        # Return content with triple backticks — should fail validation
        fn = MagicMock(return_value="has ```backticks``` inside")
        specs = [CaptureSpec(marker="t", md_file=str(md), command=[], capture_fn=fn)]
        monkeypatch.setattr(docs_screenshots, "CAPTURES", specs)
        _capture_cache.clear()

        result = run_terminal_section(dry_run=False)
        assert result is False
        assert "old" in md.read_text()  # original content preserved

    def teardown_method(self) -> None:
        _capture_cache.clear()
