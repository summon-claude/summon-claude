"""Guard tests: commands.md <-> COMMAND_ACTIONS bidirectional + content match."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_COMMANDS_DOC = "reference/commands.md"


def _read_commands_doc(docs_dir: Path) -> str:
    doc_path = docs_dir / _COMMANDS_DOC
    assert doc_path.exists(), f"commands.md not found: {doc_path}"
    return doc_path.read_text(encoding="utf-8")


def _parse_session_commands_table(content: str) -> list[str]:
    """Extract command names from the session commands table.

    Parses the table under "## Session commands", stops at the next ## heading.
    Returns bare names (no ! prefix, first word only).
    Excludes the header row.
    """
    # Find the session commands section
    section_start = re.search(r"^## Session commands", content, re.MULTILINE)
    if not section_start:
        return []

    # Find the next ## heading after this section
    next_heading = re.search(r"^## ", content[section_start.end() :], re.MULTILINE)
    if next_heading:
        section = content[section_start.start() : section_start.end() + next_heading.start()]
    else:
        section = content[section_start.start() :]

    # Match table rows: | `!cmd ...` | ... |
    # Extract command name: strip !, take first word only
    cmd_names: list[str] = []
    table_row_re = re.compile(r"^\|\s*`!(\S+)", re.MULTILINE)
    for m in table_row_re.finditer(section):
        raw = m.group(1)
        # Strip trailing backtick or other punctuation, take first word
        name = raw.rstrip("`").split()[0].lower()
        # Skip table separator rows
        if name.startswith("-"):
            continue
        cmd_names.append(name)

    return cmd_names


def test_documented_session_commands_exist(docs_dir: Path) -> None:
    """Every command in the session commands table must exist in COMMAND_ACTIONS or aliases."""
    from summon_claude.sessions.commands import _ALIAS_LOOKUP, COMMAND_ACTIONS

    content = _read_commands_doc(docs_dir)
    cmd_names = _parse_session_commands_table(content)
    assert cmd_names, "No session commands found in the table — parser may be broken"

    missing: list[str] = []
    for name in cmd_names:
        if name not in COMMAND_ACTIONS and name not in _ALIAS_LOOKUP:
            missing.append(name)

    if missing:
        pytest.fail(
            f"Commands in session commands table not found in COMMAND_ACTIONS or _ALIAS_LOOKUP: "
            f"{sorted(missing)}"
        )


def test_all_commands_are_documented(docs_dir: Path) -> None:
    """Every key in COMMAND_ACTIONS must appear somewhere in commands.md."""
    from summon_claude.sessions.commands import COMMAND_ACTIONS

    content = _read_commands_doc(docs_dir)

    undocumented: list[str] = []
    for name in COMMAND_ACTIONS:
        # Skip plugin-registered entries (contain colon)
        if ":" in name:
            continue
        # Search for `!name` anywhere in the doc — the name may be followed by
        # arguments (e.g. `!help [COMMAND]`) or appear as a heading (### !help),
        # so we match on the bare token `!name` with a word boundary after.
        pattern = r"`!" + re.escape(name) + r"(?:`|\s|\\|\[)"
        if not re.search(pattern, content) and f"### !{name}" not in content:
            undocumented.append(name)

    if undocumented:
        pytest.fail(
            f"COMMAND_ACTIONS keys not found in commands.md (search: `!name`): "
            f"{sorted(undocumented)}"
        )


def test_generated_sections_match() -> None:
    """commands.md generated sections must be up to date with COMMAND_ACTIONS."""
    result = subprocess.run(
        ["uv", "run", "python", "scripts/generate_commands_docs.py", "--check"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"commands.md is stale — run `make docs-commands` to regenerate\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
