"""Tests for write gate — safe-dir validation and worktree gating."""

from __future__ import annotations

from pathlib import Path

from summon_claude.sessions.permissions import _is_in_safe_dir


class TestIsSafeDir:
    """Unit tests for _is_in_safe_dir path validation."""

    def test_file_inside_safe_dir(self, tmp_path: Path):
        safe = tmp_path / "hack"
        safe.mkdir()
        target = safe / "notes.md"
        target.touch()
        assert _is_in_safe_dir(str(target), ["hack/"], tmp_path) is True

    def test_file_outside_safe_dir(self, tmp_path: Path):
        (tmp_path / "hack").mkdir()
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        assert _is_in_safe_dir(str(target), ["hack/"], tmp_path) is False

    def test_empty_safe_dirs_returns_false(self, tmp_path: Path):
        target = tmp_path / "anything.txt"
        target.touch()
        assert _is_in_safe_dir(str(target), [], tmp_path) is False

    def test_none_project_root_returns_false(self):
        assert _is_in_safe_dir("/some/file.py", ["hack/"], None) is False

    def test_relative_project_root_returns_false(self):
        assert _is_in_safe_dir("/some/file.py", ["hack/"], Path("relative")) is False

    def test_empty_project_root_returns_false(self):
        assert _is_in_safe_dir("/some/file.py", ["hack/"], Path()) is False

    def test_dotdot_traversal_blocked(self, tmp_path: Path):
        safe = tmp_path / "hack"
        safe.mkdir()
        # ../src/main.py should NOT be in hack/ even though it starts with ../
        assert _is_in_safe_dir(str(safe / ".." / "src" / "main.py"), ["hack/"], tmp_path) is False

    def test_symlink_resolved(self, tmp_path: Path):
        real_dir = tmp_path / "real_safe"
        real_dir.mkdir()
        target = real_dir / "notes.md"
        target.touch()
        link = tmp_path / "link_safe"
        link.symlink_to(real_dir)
        # File accessed via symlink should resolve to the real dir
        assert _is_in_safe_dir(str(link / "notes.md"), ["real_safe/"], tmp_path) is True

    def test_multiple_safe_dirs(self, tmp_path: Path):
        (tmp_path / "hack").mkdir()
        (tmp_path / ".dev").mkdir()
        target = tmp_path / ".dev" / "scratch.py"
        target.touch()
        assert _is_in_safe_dir(str(target), ["hack/", ".dev/"], tmp_path) is True

    def test_relative_file_path_resolved_against_project_root(self, tmp_path: Path):
        safe = tmp_path / "hack"
        safe.mkdir()
        target = safe / "notes.md"
        target.touch()
        # Relative path should be resolved against project_root
        assert _is_in_safe_dir("hack/notes.md", ["hack/"], tmp_path) is True

    def test_absolute_file_path_works(self, tmp_path: Path):
        safe = tmp_path / "hack"
        safe.mkdir()
        target = safe / "notes.md"
        target.touch()
        assert _is_in_safe_dir(str(target), ["hack/"], tmp_path) is True
