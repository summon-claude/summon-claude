"""Tests for summon_claude.sessions.transcript — TranscriptReconciler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from summon_claude.sessions.transcript import (
    _MAX_LINE_BYTES,
    _MAX_RECONCILE_BYTES,
    TranscriptReconciler,
    encode_cwd,
)


class TestEncodeCwd:
    def test_absolute_path(self):
        assert encode_cwd("/Users/alice/myproject") == "-Users-alice-myproject"

    def test_nested_path_with_dots(self):
        assert (
            encode_cwd("/Users/alice/project/.claude/worktrees/feat-x")
            == "-Users-alice-project-.claude-worktrees-feat-x"
        )

    def test_root_path(self):
        assert encode_cwd("/") == "-"

    def test_relative_path(self):
        assert encode_cwd("relative/path") == "relative-path"


class TestTranscriptReconcilerSetup:
    def test_set_session_id_computes_path(self):
        r = TranscriptReconciler("/Users/alice/project")
        assert r.transcript_path is None

        r.set_session_id("abc-123")
        expected = Path.home() / ".claude/projects/-Users-alice-project/abc-123.jsonl"
        assert r.transcript_path == expected

    def test_set_session_id_idempotent(self):
        r = TranscriptReconciler("/Users/alice/project")
        r.set_session_id("first-id")
        first_path = r.transcript_path

        r.set_session_id("second-id")
        assert r.transcript_path == first_path

    async def test_reconcile_returns_empty_without_session_id(self):
        r = TranscriptReconciler("/x")
        results = await r.reconcile({"tu_1"})
        assert results == []

    async def test_reconcile_returns_empty_with_no_ids(self):
        r = TranscriptReconciler("/x")
        r.set_session_id("sid")
        results = await r.reconcile(set())
        assert results == []


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_tool_result_entry(tool_use_id: str, *, is_error: bool = False) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "result text",
                    "is_error": is_error,
                }
            ],
        },
    }


def _make_assistant_entry() -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "hello"}],
        },
    }


class TestTranscriptReconciler:
    async def test_recovers_matching_tool_result(self, tmp_path):
        cwd = str(tmp_path / "project")
        r = TranscriptReconciler(cwd)
        r.set_session_id("test-sess")

        transcript = r.transcript_path
        assert transcript is not None
        _write_jsonl(
            transcript,
            [
                _make_assistant_entry(),
                _make_tool_result_entry("tu_1"),
                _make_tool_result_entry("tu_2", is_error=True),
                _make_assistant_entry(),
            ],
        )

        results = await r.reconcile({"tu_1", "tu_2", "tu_missing"})

        assert len(results) == 2
        by_id = {r.tool_use_id: r for r in results}
        assert "tu_1" in by_id
        assert not by_id["tu_1"].is_error
        assert "tu_2" in by_id
        assert by_id["tu_2"].is_error

    async def test_incremental_offset_tracking(self, tmp_path):
        """Second reconcile call only reads new content."""
        cwd = str(tmp_path / "project")
        r = TranscriptReconciler(cwd)
        r.set_session_id("test-sess")

        transcript = r.transcript_path
        assert transcript is not None
        _write_jsonl(transcript, [_make_tool_result_entry("tu_1")])

        results = await r.reconcile({"tu_1"})
        assert len(results) == 1
        offset_after_first = r._last_read_offset
        assert offset_after_first > 0

        # tu_1 is already past the offset — won't be found again
        results = await r.reconcile({"tu_1"})
        assert len(results) == 0

        # Append new content — tu_2 is found
        with transcript.open("a") as f:
            f.write(json.dumps(_make_tool_result_entry("tu_2")) + "\n")

        results = await r.reconcile({"tu_2"})
        assert len(results) == 1
        assert results[0].tool_use_id == "tu_2"

    async def test_handles_missing_transcript(self, tmp_path):
        cwd = str(tmp_path / "project")
        r = TranscriptReconciler(cwd)
        r.set_session_id("nonexistent-sess")

        results = await r.reconcile({"tu_1"})
        assert results == []

    async def test_handles_corrupt_json_lines(self, tmp_path):
        cwd = str(tmp_path / "project")
        r = TranscriptReconciler(cwd)
        r.set_session_id("test-sess")

        transcript = r.transcript_path
        assert transcript is not None
        transcript.parent.mkdir(parents=True, exist_ok=True)
        with transcript.open("w") as f:
            f.write("not json\n")
            f.write('{"type": "user", "message": {"content": "not a list"}}\n')
            f.write(json.dumps(_make_tool_result_entry("tu_1")) + "\n")
            f.write("{truncated json\n")

        results = await r.reconcile({"tu_1"})
        assert len(results) == 1
        assert results[0].tool_use_id == "tu_1"

    async def test_respects_max_reconcile_bytes(self, tmp_path):
        """Stops reading after _MAX_RECONCILE_BYTES even if IDs aren't found."""
        cwd = str(tmp_path / "project")
        r = TranscriptReconciler(cwd)
        r.set_session_id("test-sess")

        transcript = r.transcript_path
        assert transcript is not None
        transcript.parent.mkdir(parents=True, exist_ok=True)

        # Write enough padding to exceed the cap, then the target after
        padding_line = json.dumps(_make_assistant_entry()) + "\n"
        padding_count = (_MAX_RECONCILE_BYTES // len(padding_line)) + 10
        with transcript.open("w") as f:
            for _ in range(padding_count):
                f.write(padding_line)
            f.write(json.dumps(_make_tool_result_entry("tu_after_cap")) + "\n")

        results = await r.reconcile({"tu_after_cap"})
        assert len(results) == 0  # capped before reaching it

    async def test_skips_oversized_lines(self, tmp_path):
        cwd = str(tmp_path / "project")
        r = TranscriptReconciler(cwd)
        r.set_session_id("test-sess")

        transcript = r.transcript_path
        assert transcript is not None
        transcript.parent.mkdir(parents=True, exist_ok=True)

        big_entry = _make_tool_result_entry("tu_big")
        big_entry["padding"] = "x" * (_MAX_LINE_BYTES + 1000)
        with transcript.open("w") as f:
            f.write(json.dumps(big_entry) + "\n")
            f.write(json.dumps(_make_tool_result_entry("tu_small")) + "\n")

        results = await r.reconcile({"tu_big", "tu_small"})
        by_id = {r.tool_use_id: r for r in results}
        assert "tu_big" not in by_id
        assert "tu_small" in by_id

    async def test_multiple_tool_results_in_one_message(self, tmp_path):
        cwd = str(tmp_path / "project")
        r = TranscriptReconciler(cwd)
        r.set_session_id("test-sess")

        transcript = r.transcript_path
        assert transcript is not None
        multi_entry = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_a", "content": "a"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_b",
                        "content": "b",
                        "is_error": True,
                    },
                ],
            },
        }
        _write_jsonl(transcript, [multi_entry])

        results = await r.reconcile({"tu_a", "tu_b"})
        assert len(results) == 2

    async def test_early_exit_when_all_ids_found(self, tmp_path):
        """Stops scanning once all requested IDs are recovered."""
        cwd = str(tmp_path / "project")
        r = TranscriptReconciler(cwd)
        r.set_session_id("test-sess")

        transcript = r.transcript_path
        assert transcript is not None
        entries = [_make_tool_result_entry("tu_target")]
        # Pad with many more lines
        for i in range(100):
            entries.append(_make_tool_result_entry(f"tu_other_{i}"))
        _write_jsonl(transcript, entries)

        results = await r.reconcile({"tu_target"})
        assert len(results) == 1
        # Offset should be well before end of file (early exit)
        file_size = transcript.stat().st_size
        assert r._last_read_offset < file_size
