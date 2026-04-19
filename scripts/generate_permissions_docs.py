#!/usr/bin/env python
"""Generate docs/reference/permissions.md sections from permission constants.

Replaces content between marker pairs:
  <!-- permissions:auto-approve -->   / <!-- /permissions:auto-approve -->
  <!-- permissions:write-gated -->    / <!-- /permissions:write-gated -->
  <!-- permissions:github-deny -->    / <!-- /permissions:github-deny -->
  <!-- permissions:github-allow -->   / <!-- /permissions:github-allow -->
  <!-- permissions:jira-deny -->      / <!-- /permissions:jira-deny -->
  <!-- permissions:jira-allow -->     / <!-- /permissions:jira-allow -->
  <!-- permissions:google-read -->    / <!-- /permissions:google-read -->

Usage::

    uv run python scripts/generate_permissions_docs.py          # regenerate
    uv run python scripts/generate_permissions_docs.py --check   # exit 1 if stale
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOC_PATH = _REPO_ROOT / "docs" / "reference" / "permissions.md"

# Generic marker regex — captures marker name for dispatch
_MARKER_RE = re.compile(
    r"(<!-- permissions:(\S+) -->\n).*?(<!-- /permissions:\2 -->)",
    re.DOTALL,
)


def _strip_prefix(name: str, prefix: str) -> str:
    return name[len(prefix) :] if name.startswith(prefix) else name


def _get_sections() -> dict[str, str]:
    """Return ``{marker_name: content}`` for each generated section."""
    from summon_claude.sessions.permissions import (
        _AUTO_APPROVE_TOOLS,
        _GITHUB_MCP_AUTO_APPROVE,
        _GITHUB_MCP_AUTO_APPROVE_PREFIXES,
        _GITHUB_MCP_REQUIRE_APPROVAL,
        _GOOGLE_READ_TOOL_PREFIXES,
        _JIRA_MCP_AUTO_APPROVE_EXACT,
        _JIRA_MCP_AUTO_APPROVE_PREFIXES,
        _JIRA_MCP_HARD_DENY,
        _WRITE_GATED_TOOLS,
    )

    sections: dict[str, str] = {}

    # --- auto-approve: table of tool names ---
    # Group tools that are aliases (Read/Cat share the same underlying operation)
    tool_groups: list[tuple[str, str]] = [
        ("`Read` / `Cat`", "Read file contents"),
        ("`Grep`", "Search file contents"),
        ("`Glob`", "List files by pattern"),
        ("`WebSearch`", "Search the web"),
        ("`WebFetch`", "Fetch a URL"),
        ("`LSP`", "Language server protocol queries"),
        ("`ListFiles`", "List directory contents"),
        ("`GetSymbolsOverview`", "Read code symbols overview"),
        ("`FindSymbol`", "Find a symbol definition"),
        ("`FindReferencingSymbols`", "Find symbol references"),
    ]
    # Verify all source tools are covered by groups
    grouped_names: set[str] = set()
    for cell, _ in tool_groups:
        for name in re.findall(r"`([^`]+)`", cell):
            grouped_names.add(name)
    if grouped_names != _AUTO_APPROVE_TOOLS:
        missing = _AUTO_APPROVE_TOOLS - grouped_names
        extra = grouped_names - _AUTO_APPROVE_TOOLS
        raise RuntimeError(
            f"tool_groups out of sync with _AUTO_APPROVE_TOOLS: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    rows = ["| Tool | Description |", "|------|-------------|"]
    for cell, desc in tool_groups:
        rows.append(f"| {cell} | {desc} |")
    sections["auto-approve"] = "\n".join(rows)

    # --- write-gated: inline list ---
    # Fixed order: primary tools first, then SDK alias in parenthetical
    primary = sorted(t for t in _WRITE_GATED_TOOLS if t != "str_replace_editor")
    sdk_alias = [t for t in _WRITE_GATED_TOOLS if t == "str_replace_editor"]
    tool_list = ", ".join(f"`{t}`" for t in primary)
    if sdk_alias:
        tool_list += f" (and the SDK alias `{sdk_alias[0]}`)"
    sections["write-gated"] = f"**Write-gated tools:** {tool_list}"

    # --- github-deny: table of stripped tool names ---
    # Maintain a reason mapping for documentation clarity
    github_deny_reasons: dict[str, str] = {
        "merge_pull_request": "Irreversible",
        "delete_branch": "Irreversible",
        "close_pull_request": "Visible to others",
        "close_issue": "Visible to others",
        "push_files": "Writes to remote",
        "create_or_update_file": "Writes to remote",
        "update_pull_request_branch": "Modifies shared branch",
        "pull_request_review_write": "Visible to others",
        "create_pull_request": "Visible to others",
        "create_issue": "Visible to others",
        "add_issue_comment": "Visible to others",
    }
    gh_short = sorted(_strip_prefix(t, "mcp__github__") for t in _GITHUB_MCP_REQUIRE_APPROVAL)
    # Verify all tools have reasons
    missing_reasons = set(gh_short) - set(github_deny_reasons)
    if missing_reasons:
        raise RuntimeError(f"github_deny_reasons missing entries for: {sorted(missing_reasons)}")
    gh_rows = ["| Tool | Reason |", "|------|--------|"]
    for name in gh_short:
        gh_rows.append(f"| `{name}` | {github_deny_reasons[name]} |")
    sections["github-deny"] = "\n".join(gh_rows)

    # --- github-allow: prose describing prefixes + exact matches ---
    gh_prefixes = sorted(
        _strip_prefix(p, "mcp__github__") for p in _GITHUB_MCP_AUTO_APPROVE_PREFIXES
    )
    gh_exact = sorted(_strip_prefix(t, "mcp__github__") for t in _GITHUB_MCP_AUTO_APPROVE)
    prefix_str = ", ".join(f"`{p}`" for p in gh_prefixes)
    exact_str = " and ".join(f"`{t}`" for t in gh_exact)
    sections["github-allow"] = (
        f"**Auto-approved (read-only):** Any tool with a {prefix_str} prefix, plus {exact_str}."
    )

    # --- jira-deny: table of stripped tool names ---
    jira_deny_reasons: dict[str, str] = {
        "addCommentToJiraIssue": "Write operation",
        "addWorklogToJiraIssue": "Write operation",
        "createConfluenceFooterComment": "Write operation",
        "createConfluenceInlineComment": "Write operation",
        "createConfluencePage": "Write operation",
        "createIssueLink": "Write operation",
        "createJiraIssue": "Write operation",
        "editJiraIssue": "Write operation",
        "fetchAtlassian": "Generic ARI accessor — bypasses per-tool gating",
        "transitionJiraIssue": "Write operation",
        "updateConfluencePage": "Write operation",
    }
    jira_short = sorted(_strip_prefix(t, "mcp__jira__") for t in _JIRA_MCP_HARD_DENY)
    missing_jira = set(jira_short) - set(jira_deny_reasons)
    if missing_jira:
        raise RuntimeError(f"jira_deny_reasons missing entries for: {sorted(missing_jira)}")
    jira_rows = ["| Tool | Reason |", "|------|--------|"]
    for name in jira_short:
        jira_rows.append(f"| `{name}` | {jira_deny_reasons[name]} |")
    sections["jira-deny"] = "\n".join(jira_rows)

    # --- jira-allow: prose describing prefixes + exact matches ---
    jira_prefixes = sorted(_strip_prefix(p, "mcp__jira__") for p in _JIRA_MCP_AUTO_APPROVE_PREFIXES)
    jira_exact = sorted(_strip_prefix(t, "mcp__jira__") for t in _JIRA_MCP_AUTO_APPROVE_EXACT)
    j_prefix_str = ", ".join(f"`{p}*`" for p in jira_prefixes)
    j_exact_str = ", ".join(f"`{t}`" for t in jira_exact)
    sections["jira-allow"] = (
        f"**Auto-approved (read-only):** Tools matching {j_prefix_str} prefixes, "
        f"plus the exact match {j_exact_str}."
    )

    # --- google-read: inline list of prefixes ---
    g_prefixes = ", ".join(f"`{p}`" for p in sorted(_GOOGLE_READ_TOOL_PREFIXES))
    sections["google-read"] = f"**Google read-only prefixes (step 6a):** {g_prefixes}"

    return sections


def generate(content: str, sections: dict[str, str]) -> str:
    """Replace permission marker sections in *content* with generated text."""

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        marker = m.group(2)
        if marker not in sections:
            msg = f"Unknown permissions marker {marker!r} — typo? Known: {sorted(sections)}"
            raise ValueError(msg)
        return f"{m.group(1)}{sections[marker]}\n{m.group(3)}"

    return _MARKER_RE.sub(_replace, content)


def main() -> int:
    check_only = "--check" in sys.argv

    sections = _get_sections()
    content = _DOC_PATH.read_text(encoding="utf-8")
    updated = generate(content, sections)

    if check_only:
        if content == updated:
            print("permissions.md is up to date")  # noqa: T201
            return 0
        print("permissions.md is stale — run: uv run python scripts/generate_permissions_docs.py")  # noqa: T201
        return 1

    _DOC_PATH.write_text(updated, encoding="utf-8")
    print(f"Updated {_DOC_PATH.relative_to(_REPO_ROOT)}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
