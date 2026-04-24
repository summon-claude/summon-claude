"""Tests for summon_claude.sandbox.bug_hunter_memory."""

from __future__ import annotations

from pathlib import Path

from summon_claude.sandbox.bug_hunter_memory import (
    _MEMORY_FILES,
    initialize_bug_hunter_memory,
)


class TestInitializeBugHunterMemory:
    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "memory"
        assert not target.exists()
        initialize_bug_hunter_memory(target)
        assert target.is_dir()

    def test_creates_all_template_files(self, tmp_path: Path) -> None:
        target = tmp_path / "memory"
        initialize_bug_hunter_memory(target)
        for filename in _MEMORY_FILES:
            assert (target / filename).exists(), f"{filename} was not created"

    def test_template_files_are_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "memory"
        initialize_bug_hunter_memory(target)
        for filename in _MEMORY_FILES:
            assert (target / filename).read_text() == ""

    def test_does_not_overwrite_existing_files(self, tmp_path: Path) -> None:
        target = tmp_path / "memory"
        target.mkdir()
        existing = target / "FINDINGS.md"
        existing.write_text("existing content")
        initialize_bug_hunter_memory(target)
        assert existing.read_text() == "existing content"

    def test_idempotent_on_second_call(self, tmp_path: Path) -> None:
        target = tmp_path / "memory"
        initialize_bug_hunter_memory(target)
        (target / "FINDINGS.md").write_text("data from scan")
        initialize_bug_hunter_memory(target)
        assert (target / "FINDINGS.md").read_text() == "data from scan"
