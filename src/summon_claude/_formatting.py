"""Shared formatting helpers used by streamer and permissions."""

from __future__ import annotations

from typing import Any

# Maps tool names to the keys where their primary argument lives (tried in order).
_TOOL_PATH_KEYS: dict[str, tuple[str, ...]] = {
    "Read": ("file_path", "path"),
    "Cat": ("file_path", "path"),
    "Edit": ("path", "file_path"),
    "str_replace_editor": ("path", "file_path"),
    "Write": ("file_path", "path"),
    "Glob": ("pattern",),
    "Grep": ("pattern",),
    "NotebookEdit": ("notebook_path",),
}

_BASH_PREVIEW_CHARS = 120


def get_tool_primary_arg(tool_name: str, input_data: dict[str, Any]) -> str:
    """Return the primary argument for *tool_name* from *input_data*.

    For file-oriented tools this is the path; for Bash the command preview;
    for WebSearch/WebFetch the query/url.  Returns ``""`` when nothing useful
    is found.
    """
    if tool_name == "Bash":
        cmd = input_data.get("command", "")
        return cmd[:_BASH_PREVIEW_CHARS] + ("..." if len(cmd) > _BASH_PREVIEW_CHARS else "")

    if tool_name == "WebSearch":
        return input_data.get("query", "")

    if tool_name == "WebFetch":
        url = input_data.get("url", "")
        return url[:60] if url else ""

    keys = _TOOL_PATH_KEYS.get(tool_name)
    if keys:
        for key in keys:
            val = input_data.get(key, "")
            if val:
                return val

    return ""


def sanitize_for_mrkdwn(text: str, max_len: int = 100) -> str:
    """Remove mrkdwn-significant characters and newlines to prevent injection."""
    return text.replace("\n", " ").replace("\r", " ").replace("`", "'").replace("*", "")[:max_len]


def format_file_references(files: list[dict]) -> str:
    """Format file attachment metadata as context for Claude.

    Only includes filename and file type -- NOT the private download URL,
    which requires Slack auth headers that Claude cannot provide.
    Filenames are sanitized to prevent prompt injection via crafted names.
    """
    parts: list[str] = []
    for f in files:
        name = f.get("name", "unknown").replace("\n", " ").replace("\r", " ")[:200]
        filetype = f.get("filetype", "")
        size = f.get("size", 0)
        size_str = f" ({size} bytes)" if size else ""
        parts.append(f"[Attached file: {name} ({filetype}){size_str}]")
    return "\n".join(parts)
