"""Formatting helpers for CLI output."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click


def echo(msg: str, ctx: click.Context, err: bool = False) -> None:
    if err or not ctx.obj.get("quiet"):
        click.echo(msg, err=err)


def format_json(data: list[dict] | dict) -> str:
    return json.dumps(data, indent=2, default=str)


def format_ts(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


_TAG_STYLE: dict[str, tuple[str, str | None]] = {
    "PASS": ("PASS", "green"),
    "FAIL": ("FAIL", "red"),
    "WARN": ("WARN", "yellow"),
    "INFO": ("INFO", "blue"),
}


def format_tag(tag: str) -> str:
    """Return a colored ``[PASS]``/``[FAIL]``/``[WARN]``/``[INFO]`` tag."""
    label, fg = _TAG_STYLE.get(tag, (tag, None))
    if fg is None:
        return f"[{label}]"
    return click.style(f"[{label}]", fg=fg, bold=True)


def format_uptime(seconds: float) -> str:
    """Format a duration in seconds as a human-readable uptime string."""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def print_session_table(sessions: list[dict], *, show_id: bool = False) -> None:
    """Print a compact table of sessions.

    When *show_id* is True (e.g. ``--all``), a full SESSION ID column is added.
    """
    if not sessions:
        return

    headers: list[str] = []
    if show_id:
        headers.append("SESSION ID")
    headers.extend(["ID", "STATUS", "NAME", "CHANNEL", "CWD"])

    rows: list[list[str]] = []
    for s in sessions:
        session_id = s.get("session_id", "")
        short_id = session_id[:8] if session_id else "-"
        row: list[str] = []
        if show_id:
            row.append(session_id or "-")
        row.extend(
            [
                short_id,
                s.get("status", "?"),
                s.get("session_name") or "-",
                s.get("slack_channel_name") or "-",
                s.get("cwd", ""),
            ]
        )
        rows.append(row)

    # Fixed-width for all columns except CWD (last), which wraps freely
    fixed = headers[:-1]
    col_widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(fixed)]
    prefix_fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    click.echo(f"{prefix_fmt.format(*fixed)}  {headers[-1]}")
    click.echo("  ".join("-" * w for w in col_widths) + "  " + "-" * len(headers[-1]))
    for row in rows:
        click.echo(f"{prefix_fmt.format(*row[:-1])}  {row[-1]}")


def print_session_detail(session: dict) -> None:
    """Print detailed info for a single session."""
    fields = [
        ("Session ID", session.get("session_id", "")),
        ("Status", session.get("status", "")),
        ("Name", session.get("session_name") or "-"),
        ("PID", str(session.get("pid", ""))),
        ("CWD", session.get("cwd", "")),
        ("Model", session.get("model") or "-"),
        ("Channel ID", session.get("slack_channel_id") or "-"),
        ("Channel", session.get("slack_channel_name") or "-"),
        ("Claude Session", session.get("claude_session_id") or "-"),
        ("Started", format_ts(session.get("started_at"))),
        ("Authenticated", format_ts(session.get("authenticated_at"))),
        ("Last Activity", format_ts(session.get("last_activity_at"))),
        ("Ended", format_ts(session.get("ended_at"))),
        ("Turns", str(session.get("total_turns", 0))),
        ("Total Cost", f"${session.get('total_cost_usd', 0.0) or 0.0:.4f}"),
    ]
    if session.get("error_message"):
        fields.append(("Error", session["error_message"]))

    max_key = max(len(k) for k, _ in fields)
    for key, val in fields:
        click.echo(f"  {key.ljust(max_key)} : {val}")


def _mask_secret(value: str, prefix_len: int = 5) -> str:
    """Return a masked preview of a secret value for user feedback.

    Shows a recognized format prefix (if any) plus character count.
    Does not reveal unique suffix characters to avoid terminal scrollback leaks.
    """
    if not value:
        return "(empty)"
    # Only show prefix when it reveals less than half the value
    if len(value) > 2 * prefix_len:
        return f"{value[:prefix_len]}*** [{len(value)} chars]"
    return f"[{len(value)} chars]"


# ---------------------------------------------------------------------------
# Auth output consistency — shared formatters for all providers
# ---------------------------------------------------------------------------

_AUTH_STATUS_TAGS: dict[str, str] = {
    "authenticated": "PASS",
    "not_configured": "INFO",
    "error": "FAIL",
    "warn": "WARN",
}

_VALID_AUTH_JSON_STATUSES = frozenset({"authenticated", "not_configured", "error"})


def auth_status_line(
    provider: str,
    *,
    status: str,
    message: str,
    prefix: str = "",
) -> str:
    """Build a tagged auth status line: ``{prefix}[TAG] Provider: message``.

    *status* selects the colored tag: authenticated->PASS, not_configured->INFO,
    error->FAIL, warn->WARN.
    """
    tag_name = _AUTH_STATUS_TAGS.get(status)
    if tag_name is None:
        raise ValueError(
            f"Unknown auth status {status!r}; expected one of {sorted(_AUTH_STATUS_TAGS)}"
        )
    return f"{prefix}{format_tag(tag_name)} {provider}: {message}"


def auth_not_configured_msg(setup_cmd: str) -> str:
    """Standard 'not configured' message with setup/login hint."""
    return f"not configured (run `{setup_cmd}`)"


def auth_authenticated_msg(*, identity: str = "", detail: str = "") -> str:
    """Standard 'authenticated' message with optional identity and detail."""
    parts = ["authenticated"]
    if identity:
        parts.append(f"as {identity}")
    if detail:
        parts.append(f"({detail})")
    return " ".join(parts)


def auth_login_success(
    provider: str,
    *,
    identity: str = "",
    detail: str = "",
    storage_path: str | Path,
    next_step: str = "",
) -> None:
    """Print standard post-login success output.

    Produces 2+ lines::

        {Provider} authenticated as {identity}.
        Credentials stored in {path}
        [blank line + next_step if provided]

    Use *identity* for user-identifying info (email, username).
    Use *detail* for non-identity info (site name, workspace).
    """
    if identity:
        click.echo(f"{provider} authenticated as {identity}.")
    elif detail:
        click.echo(f"{provider} authenticated ({detail}).")
    else:
        click.echo(f"{provider} authenticated.")
    click.echo(f"Credentials stored in {storage_path}")
    if next_step:
        click.echo()
        click.echo(next_step)


def auth_removed(provider: str, *, qualifier: str = "") -> str:
    """Standard credential-removed message."""
    suffix = f" ({qualifier})" if qualifier else ""
    return f"{provider} credentials removed{suffix}."


def auth_not_stored(provider: str, *, account: str = "") -> str:
    """Standard no-credentials message."""
    if account:
        return f"No {provider} credentials found for account '{account}'."
    return f"No {provider} credentials stored."


def auth_cancelled() -> str:
    """Standard authentication cancellation message (with leading newline)."""
    return "\nAuthentication cancelled."


def make_auth_status_data(provider: str, status: str, **extra: object) -> dict:
    """Build a provider status dict for ``--json`` output.

    Enforces ``{"provider": ..., "status": ...}`` base shape.
    Valid statuses: authenticated, not_configured, error.
    """
    if status not in _VALID_AUTH_JSON_STATUSES:
        raise ValueError(
            f"Invalid auth JSON status {status!r};"
            f" expected one of {sorted(_VALID_AUTH_JSON_STATUSES)}"
        )
    return {"provider": provider, "status": status, **extra}
