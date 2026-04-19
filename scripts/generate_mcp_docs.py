#!/usr/bin/env python
"""Generate docs/reference/mcp-tools.md sections from MCP tool definitions.

Replaces content between marker pairs:
  <!-- mcp:summary -->  / <!-- /mcp:summary -->  — tool counts per server

Individual parameter tables are hand-maintained because the tool schemas
lack per-parameter descriptions and defaults.  Guard tests in
``test_mcp_tools.py`` validate that documented parameters match schemas.

Usage::

    uv run python scripts/generate_mcp_docs.py          # regenerate
    uv run python scripts/generate_mcp_docs.py --check   # exit 1 if stale
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOC_PATH = _REPO_ROOT / "docs" / "reference" / "mcp-tools.md"

# Matches  <!-- mcp:NAME -->\n...\n<!-- /mcp:NAME -->
_MCP_BLOCK_RE = re.compile(
    r"(<!-- mcp:(\S+) -->\n).*?(<!-- /mcp:\2 -->)",
    re.DOTALL,
)

# Server -> tool name prefix mapping.  Imported by tests/docs/test_mcp_tools.py.
# Order determines summary table row order — matches the doc section order.
_SERVER_PREFIXES: dict[str, str | None] = {
    "summon-slack": "slack_",
    "summon-cli": None,  # everything else
    "summon-canvas": "summon_canvas_",
}

_SERVER_DESC: dict[str, str] = {
    "summon-slack": "Slack actions and reading",
    "summon-cli": "Session lifecycle, scheduling, tasks",
    "summon-canvas": "canvas read/write",
}


def _collect_tool_names() -> tuple[set[str], set[str]]:
    """Collect all MCP tool names and identify PM-only tools.

    Returns (all_tool_names, pm_only_tool_names).
    PM-only tools are determined by comparing tools from is_pm=True vs is_pm=False.
    Mirrors tests/docs/conftest.py::_async_collect_mcp_tools().
    """
    from summon_claude.canvas_mcp import create_canvas_mcp_tools
    from summon_claude.sessions.registry import SessionRegistry
    from summon_claude.sessions.scheduler import SessionScheduler
    from summon_claude.slack.mcp import create_summon_mcp_tools
    from summon_claude.summon_cli_mcp import create_summon_cli_mcp_tools

    def _make_scheduler() -> SessionScheduler:
        return SessionScheduler(asyncio.Queue(maxsize=100), asyncio.Event())

    async def _collect() -> tuple[set[str], set[str]]:
        names: set[str] = set()

        fd, tmp_str = tempfile.mkstemp(suffix=".db", prefix="summon_doc_gen_")
        os.close(fd)
        tmp = Path(tmp_str)
        try:
            reg = SessionRegistry(db_path=tmp)
            async with reg:
                # Non-PM CLI tools (base set available to all sessions)
                base_cli_tools = create_summon_cli_mcp_tools(
                    registry=reg,
                    session_id="doc-gen-base",
                    authenticated_user_id="U_DOC",
                    channel_id="C_DOC",
                    cwd=tmp_str,
                    scheduler=_make_scheduler(),
                    is_pm=False,
                )
                base_cli_names = {t.name for t in base_cli_tools}

                # PM CLI tools (superset)
                cli_tools = create_summon_cli_mcp_tools(
                    registry=reg,
                    session_id="doc-gen",
                    authenticated_user_id="U_DOC",
                    channel_id="C_DOC",
                    cwd=tmp_str,
                    scheduler=_make_scheduler(),
                    is_pm=True,
                    pm_status_ts="1234567890.123456",
                    _web_client=AsyncMock(),
                )
                names.update(t.name for t in cli_tools)

                # GPM-only tools
                gpm_tools = create_summon_cli_mcp_tools(
                    registry=reg,
                    session_id="doc-gen-gpm",
                    authenticated_user_id="U_DOC",
                    channel_id="C_DOC",
                    cwd=tmp_str,
                    scheduler=_make_scheduler(),
                    is_pm=True,
                    is_global_pm=True,
                )
                names.update(t.name for t in gpm_tools)

                canvas_tools = create_canvas_mcp_tools(
                    canvas_store=AsyncMock(),
                    registry=reg,
                    authenticated_user_id="U_DOC",
                    channel_id="C_DOC",
                )
                names.update(t.name for t in canvas_tools)
        finally:
            tmp.unlink(missing_ok=True)  # noqa: ASYNC240

        slack_mock = AsyncMock()
        slack_mock.channel_id = "C_DOC"
        slack_tools = create_summon_mcp_tools(
            slack_mock,
            allowed_channels=AsyncMock(return_value={"C_DOC"}),
        )
        names.update(t.name for t in slack_tools)

        # PM-only = CLI tools present with is_pm=True but absent with is_pm=False
        pm_only = {t.name for t in cli_tools} - base_cli_names
        # GPM-only tools are also PM-only (GPM is a superset of PM)
        pm_only |= {t.name for t in gpm_tools} - {t.name for t in cli_tools}

        return names, pm_only

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_collect())
    finally:
        loop.close()


def _tools_for_server(server: str, all_names: set[str]) -> set[str]:
    prefix = _SERVER_PREFIXES[server]
    if prefix is None:
        other_prefixes = tuple(p for p in _SERVER_PREFIXES.values() if p is not None)
        return {n for n in all_names if not n.startswith(other_prefixes)}
    return {n for n in all_names if n.startswith(prefix)}


def _build_summary_table(tool_names: set[str], pm_only_tools: set[str]) -> str:
    """Build the summary table showing tool counts per server."""
    rows: list[str] = [
        "| Server | Available to | Tools |",
        "|--------|-------------|-------|",
    ]
    for server in _SERVER_PREFIXES:
        tools = _tools_for_server(server, tool_names)
        count = len(tools)
        desc = _SERVER_DESC.get(server, "")

        if server == "summon-cli":
            pm_count = len(tools & pm_only_tools)
            base_count = count - pm_count
            avail = f"All sessions ({base_count} tools) + PM sessions ({pm_count} additional)"
        elif server == "summon-canvas":
            avail = "Sessions with a canvas"
        else:
            avail = "All sessions"

        rows.append(f"| `{server}` | {avail} | {count} tools — {desc} |")

    return "\n".join(rows)


def get_generated_sections() -> dict[str, str]:
    """Return ``{marker_name: content}`` for all generated sections."""
    tool_names, pm_only_tools = _collect_tool_names()
    return {"summary": _build_summary_table(tool_names, pm_only_tools)}


def generate(content: str, sections: dict[str, str]) -> str:
    """Replace mcp blocks in *content* with generated text."""

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        marker = m.group(2)
        if marker not in sections:
            return m.group(0)  # leave unknown markers unchanged
        text = sections[marker]
        return f"{m.group(1)}{text}\n{m.group(3)}"

    return _MCP_BLOCK_RE.sub(_replace, content)


def main() -> int:
    check_only = "--check" in sys.argv

    sections = get_generated_sections()
    content = _DOC_PATH.read_text(encoding="utf-8")
    updated = generate(content, sections)

    if check_only:
        if content == updated:
            print("mcp-tools.md is up to date")  # noqa: T201
            return 0
        print("mcp-tools.md is stale — run: uv run python scripts/generate_mcp_docs.py")  # noqa: T201
        return 1

    _DOC_PATH.write_text(updated, encoding="utf-8")
    print(f"Updated {_DOC_PATH.relative_to(_REPO_ROOT)}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
