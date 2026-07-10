"""Transcript reconciler — reads the CLI's JSONL transcript to recover dropped tool results.

The Claude Code CLI writes every message (including tool results) to an
on-disk JSONL transcript at ``~/.claude/projects/<encoded-cwd>/<session-id>.jsonl``.
The SDK client reads from the CLI's stdout stream, which sometimes drops
``type: "user"`` messages carrying ``ToolResultBlock``s (upstream SDK/CLI gap,
see SDK #425 backpressure, #1083 NDJSON buffer overflow).

This module provides a memory-safe, incremental reader that recovers specific
tool results from the authoritative transcript when the SDK stream drops them.

Memory safety guarantees:
- Offset-tracked incremental reads: only new content since last call is read.
- Line-by-line processing: never loads the entire file into memory.
- Per-call byte cap (``_MAX_RECONCILE_BYTES``): bounds worst-case memory.
- Per-line byte cap (``_MAX_LINE_BYTES``): skips pathologically large entries.
- File handle closed after each call: no persistent I/O resources.
- Runs in ``asyncio.to_thread``: file I/O never blocks the event loop.
- No caching: recovered results are returned and discarded.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_RECONCILE_BYTES = 512 * 1024  # 512 KB cap per reconciliation call
_MAX_LINE_BYTES = 256 * 1024  # skip JSONL lines larger than 256 KB


def encode_cwd(cwd: str) -> str:
    """Encode a CWD path into the CLI's project directory name.

    The Claude Code CLI replaces every ``/`` with ``-``, producing a
    leading ``-`` for absolute paths.  E.g.
    ``/Users/alice/myproject`` → ``-Users-alice-myproject``.
    """
    return cwd.replace("/", "-")


@dataclass(frozen=True, slots=True)
class RecoveredToolResult:
    """A tool result recovered from the CLI's JSONL transcript."""

    tool_use_id: str
    is_error: bool


def _extract_tool_results(data: dict, remaining: set[str]) -> list[RecoveredToolResult]:
    """Extract matching tool results from a parsed JSONL entry.

    Mutates *remaining* in place — found IDs are discarded.
    """
    if data.get("type") != "user":
        return []
    message = data.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []

    results: list[RecoveredToolResult] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_result":
            continue
        tid = block.get("tool_use_id")
        if tid in remaining:
            results.append(
                RecoveredToolResult(
                    tool_use_id=tid,
                    is_error=bool(block.get("is_error")),
                )
            )
            remaining.discard(tid)
            if not remaining:
                break
    return results


def _read_and_parse_transcript(
    path: Path, offset: int, unsettled_ids: set[str]
) -> tuple[list[RecoveredToolResult], int]:
    """Read the JSONL transcript incrementally and extract tool results.

    Returns ``(recovered_results, new_byte_offset)``.  Memory-safe: reads
    one line at a time, capped at ``_MAX_RECONCILE_BYTES``.

    Opens in binary mode (``'rb'``) with two pre-filters that skip lines
    without decoding or JSON-parsing:

    1. ``b'"tool_result"' not in raw`` — skips ~90% of lines (assistant
       messages, system messages, stream events).
    2. No target ``tool_use_id`` bytes in the raw line — skips tool results
       for unrelated tool calls.

    Only lines passing both filters are decoded and parsed.
    """
    results: list[RecoveredToolResult] = []
    remaining = set(unsettled_ids)
    id_needles = {tid.encode("utf-8") for tid in unsettled_ids}
    new_offset = offset

    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            bytes_read = 0

            # readline() instead of ``for line in fh`` — Python's file
            # iterator uses an internal read-ahead buffer that corrupts
            # fh.tell(), breaking offset tracking.
            while True:
                raw = fh.readline()
                if not raw:
                    break

                bytes_read += len(raw)

                if bytes_read > _MAX_RECONCILE_BYTES:
                    break

                if len(raw) > _MAX_LINE_BYTES:
                    continue

                # Pre-filter 1: skip lines that can't contain a tool_result
                if b'"tool_result"' not in raw:
                    continue

                # Pre-filter 2: skip tool results for unrelated tool calls
                if not any(needle in raw for needle in id_needles):
                    continue

                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                found = _extract_tool_results(data, remaining)
                results.extend(found)

                if not remaining:
                    break

            new_offset = fh.tell()
    except OSError:
        pass

    return results, new_offset


class TranscriptReconciler:
    """Reads the CLI's JSONL transcript to recover dropped tool results.

    Lifecycle:
    1. Created with the session's CWD (known at session start).
    2. ``set_session_id()`` called when the first ``ResultMessage.session_id``
       arrives (typically end of turn 1).
    3. ``reconcile()`` called at turn end for any unsettled ``tool_use_id``\\s.

    Thread safety: all file I/O runs in ``asyncio.to_thread``.  The offset
    is only mutated inside that thread call, so concurrent ``reconcile()``
    calls would read overlapping ranges — but summon's turn loop is
    single-threaded, so this can't happen in practice.
    """

    def __init__(self, session_cwd: str) -> None:
        self._session_cwd = session_cwd
        self._claude_session_id: str | None = None
        self._transcript_path: Path | None = None
        self._last_read_offset: int = 0

    def set_session_id(self, session_id: str) -> None:
        """Set the CLI session ID (from ``ResultMessage.session_id``).

        Computes the transcript path.  Idempotent — only the first call
        takes effect (the session ID doesn't change mid-session).
        """
        if self._claude_session_id is not None:
            return
        self._claude_session_id = session_id
        projects_dir = Path.home() / ".claude" / "projects"
        encoded = encode_cwd(self._session_cwd)
        self._transcript_path = projects_dir / encoded / f"{session_id}.jsonl"

    @property
    def transcript_path(self) -> Path | None:
        return self._transcript_path

    async def reconcile(self, unsettled_ids: set[str]) -> list[RecoveredToolResult]:
        """Recover tool results for *unsettled_ids* from the transcript.

        Returns only the results that were found.  Caller is responsible for
        acting on them (sending pill completion, invoking callbacks, etc.).

        Memory-safe: reads incrementally from ``_last_read_offset``, one line
        at a time, capped at ``_MAX_RECONCILE_BYTES``.  Runs in a thread.
        """
        if not unsettled_ids or self._transcript_path is None:
            return []

        path = self._transcript_path
        offset = self._last_read_offset

        loop = asyncio.get_running_loop()
        results, new_offset = await loop.run_in_executor(
            None, _read_and_parse_transcript, path, offset, unsettled_ids
        )
        self._last_read_offset = new_offset

        if results:
            logger.info(
                "Transcript reconciler recovered %d tool result(s): %s",
                len(results),
                {r.tool_use_id: ("error" if r.is_error else "ok") for r in results},
            )

        return results
