"""Content display: format code, diffs, and files for Slack (inline or file upload)."""

from __future__ import annotations

import difflib
import logging
from typing import Any

logger = logging.getLogger(__name__)

_SECTION_LIMIT = 3000


class ContentDisplay:
    """Formats and displays content in Slack — inline for short, file upload for long."""

    def __init__(self, max_inline_chars: int = 2500) -> None:
        self._max_inline = max_inline_chars

    def format_diff(
        self,
        old_string: str,
        new_string: str,
        filename: str = "file",
    ) -> list[dict[str, Any]]:
        """Format an edit as a unified diff in Slack Block Kit blocks."""
        diff_lines = list(
            difflib.unified_diff(
                old_string.splitlines(keepends=True),
                new_string.splitlines(keepends=True),
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}",
            )
        )
        if not diff_lines:
            return [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"_No changes in `{filename}`_"},
                }
            ]

        diff_text = "".join(diff_lines)
        # Prepend header to the full diff text, then split the combined string.
        header = f"*Edit:* `{filename}`\n"
        combined = f"{header}```{diff_text}```"
        chunks = _split_text(combined, _SECTION_LIMIT)
        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": chunk},
            }
            for chunk in chunks
        ]
        return blocks


_FENCE_OVERHEAD = len("\n```")  # bytes added when closing an unclosed code fence


def _split_text(text: str, limit: int) -> list[str]:
    """Split text into chunks that each fit within the block character limit.

    Code-block-aware: if a split would occur inside an open ``` fence,
    the fence is closed at the end of the chunk and re-opened at the start
    of the next chunk so Slack renders both halves correctly.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # If text contains fences, leave headroom for a potential closure suffix.
        # Only reduce the limit when fences exist to avoid penalizing plain text.
        effective_limit = limit
        has_fences = "```" in text
        if has_fences:
            effective_limit = max(limit - _FENCE_OVERHEAD, 1)

        # Try to break at a newline boundary
        split_at = text.rfind("\n", 0, effective_limit)
        if split_at == -1:
            split_at = effective_limit
        chunk = text[:split_at]
        rest = text[split_at:]

        # Check if we're splitting inside an open code fence.
        # Count triple-backtick fences in the chunk — odd count means unclosed.
        if has_fences:
            fence_count = chunk.count("```")
            if fence_count % 2 == 1:
                # Close the code block at end of this chunk, re-open in next
                chunk += "\n```"
                rest = "```\n" + rest

        chunks.append(chunk)
        text = rest
    return chunks
