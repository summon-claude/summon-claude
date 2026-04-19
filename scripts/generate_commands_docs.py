#!/usr/bin/env python
"""Generate docs/reference/commands.md sections from COMMAND_ACTIONS.

Replaces content between marker pairs:
  <!-- commands:session -->       / <!-- /commands:session -->
  <!-- commands:passthrough -->   / <!-- /commands:passthrough -->
  <!-- commands:blocked-specific --> / <!-- /commands:blocked-specific -->
  <!-- commands:cli-only -->      / <!-- /commands:cli-only -->

Usage::

    uv run python scripts/generate_commands_docs.py          # regenerate
    uv run python scripts/generate_commands_docs.py --check   # exit 1 if stale
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOC_PATH = _REPO_ROOT / "docs" / "reference" / "commands.md"

_SESSION_RE = re.compile(
    r"(<!-- commands:session -->\n).*?(<!-- /commands:session -->)",
    re.DOTALL,
)
_PASSTHROUGH_RE = re.compile(
    r"(<!-- commands:passthrough -->\n).*?(<!-- /commands:passthrough -->)",
    re.DOTALL,
)
_BLOCKED_SPECIFIC_RE = re.compile(
    r"(<!-- commands:blocked-specific -->\n).*?(<!-- /commands:blocked-specific -->)",
    re.DOTALL,
)
_CLI_ONLY_RE = re.compile(
    r"(<!-- commands:cli-only -->\n).*?(<!-- /commands:cli-only -->)",
    re.DOTALL,
)


def _get_session_commands() -> list[tuple[str, str, list[str], str]]:
    """Return sorted list of (name, argument_hint, aliases, description) for handler commands."""
    from summon_claude.sessions.commands import COMMAND_ACTIONS

    entries: list[tuple[str, str, list[str], str]] = []
    for name, defn in COMMAND_ACTIONS.items():
        if ":" in name:
            continue
        if defn.handler is None:
            continue
        entries.append((name, defn.argument_hint, list(defn.aliases), defn.description))

    entries.sort(key=lambda x: x[0])
    return entries


def _build_session_table(entries: list[tuple[str, str, list[str], str]]) -> str:
    lines = ["| Command | Aliases | Description |", "|---------|---------|-------------|"]
    for name, hint, aliases, description in entries:
        cmd = f"`!{name}"
        if hint:
            escaped_hint = hint.replace("|", "\\|")
            cmd += f" {escaped_hint}"
        cmd += "`"
        alias_str = ", ".join(f"`!{a}`" for a in aliases) if aliases else ""
        lines.append(f"| {cmd} | {alias_str} | {description} |")
    return "\n".join(lines) + "\n"


_ClassifyResult = tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, list[str]]]]


def _classify_commands() -> _ClassifyResult:
    """Return (passthrough, blocked_specific, cli_only) sorted lists.

    passthrough: list of (name, description)
    blocked_specific: list of (name, block_reason)
    cli_only: list of (name, aliases)
    """
    from summon_claude.sessions.commands import _CLI_ONLY, COMMAND_ACTIONS

    passthrough: list[tuple[str, str]] = []
    blocked_specific: list[tuple[str, str]] = []
    cli_only: list[tuple[str, list[str]]] = []

    for name, defn in COMMAND_ACTIONS.items():
        # Skip plugin-registered entries (contain colon)
        if ":" in name:
            continue

        # handler present → local (skip)
        if defn.handler is not None:
            continue

        if defn.block_reason is not None:
            if defn.block_reason == _CLI_ONLY:
                cli_only.append((name, list(defn.aliases)))
            else:
                blocked_specific.append((name, defn.block_reason))
        else:
            # neither handler nor block_reason → passthrough
            passthrough.append((name, defn.description))

    passthrough.sort(key=lambda x: x[0])
    blocked_specific.sort(key=lambda x: x[0])
    cli_only.sort(key=lambda x: x[0])

    return passthrough, blocked_specific, cli_only


def _build_passthrough_table(entries: list[tuple[str, str]]) -> str:
    lines = ["| Command | Description |", "|---------|-------------|"]
    for name, description in entries:
        lines.append(f"| `!{name}` | {description} |")
    return "\n".join(lines) + "\n"


def _build_blocked_specific_table(entries: list[tuple[str, str]]) -> str:
    lines = ["| Command | Reason |", "|---------|--------|"]
    for name, reason in entries:
        lines.append(f"| `!{name}` | {reason} |")
    return "\n".join(lines) + "\n"


def _build_cli_only_list(entries: list[tuple[str, list[str]]]) -> str:
    parts: list[str] = []
    for name, aliases in entries:
        if aliases:
            alias_str = ", ".join(f"`!{a}`" for a in aliases)
            parts.append(f"`!{name}` ({alias_str})")
        else:
            parts.append(f"`!{name}`")
    if not parts:
        return ""
    return ", ".join(parts) + "\n"


def generate(content: str) -> str:
    """Replace marker sections in *content* with generated text."""
    session_entries = _get_session_commands()
    passthrough, blocked_specific, cli_only = _classify_commands()

    session_table = _build_session_table(session_entries)
    passthrough_table = _build_passthrough_table(passthrough)
    blocked_table = _build_blocked_specific_table(blocked_specific)
    cli_only_list = _build_cli_only_list(cli_only)

    def _replace_session(m: re.Match) -> str:  # type: ignore[type-arg]
        return f"{m.group(1)}{session_table}{m.group(2)}"

    def _replace_passthrough(m: re.Match) -> str:  # type: ignore[type-arg]
        return f"{m.group(1)}{passthrough_table}{m.group(2)}"

    def _replace_blocked(m: re.Match) -> str:  # type: ignore[type-arg]
        return f"{m.group(1)}{blocked_table}{m.group(2)}"

    def _replace_cli_only(m: re.Match) -> str:  # type: ignore[type-arg]
        return f"{m.group(1)}{cli_only_list}{m.group(2)}"

    result = _SESSION_RE.sub(_replace_session, content)
    result = _PASSTHROUGH_RE.sub(_replace_passthrough, result)
    result = _BLOCKED_SPECIFIC_RE.sub(_replace_blocked, result)
    return _CLI_ONLY_RE.sub(_replace_cli_only, result)


def main() -> int:
    check_only = "--check" in sys.argv

    content = _DOC_PATH.read_text(encoding="utf-8")
    updated = generate(content)

    if check_only:
        if content == updated:
            print("commands.md is up to date")  # noqa: T201
            return 0
        print("commands.md is stale — run: uv run python scripts/generate_commands_docs.py")  # noqa: T201
        return 1

    _DOC_PATH.write_text(updated, encoding="utf-8")
    print(f"Updated {_DOC_PATH.relative_to(_REPO_ROOT)}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
