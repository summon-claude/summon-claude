"""Reset command logic for CLI."""

from __future__ import annotations

import shutil

import click

from summon_claude.cli.interactive import is_interactive
from summon_claude.config import get_config_dir, get_data_dir
from summon_claude.daemon import is_daemon_running


class _IpcError(Exception):
    """Raised when IPC communication with the daemon fails."""


async def _check_running_sessions() -> tuple[bool, bool]:
    """Return (has_adhoc, has_project) based on live daemon sessions.

    Raises:
        _IpcError: if the daemon is running but IPC communication fails.
    """
    if not is_daemon_running():
        return (False, False)

    from summon_claude.cli import daemon_client  # noqa: PLC0415

    try:
        sessions = await daemon_client.list_sessions()
    except Exception as exc:
        raise _IpcError(str(exc)) from exc

    has_adhoc = any("-pm-" not in session.get("session_name", "") for session in sessions)
    has_project = any("-pm-" in session.get("session_name", "") for session in sessions)
    return (has_adhoc, has_project)


async def _refuse_if_running() -> bool:
    """Check for running daemon/sessions and print guidance if found.

    Returns True if the caller should abort (daemon running, sessions detected,
    or IPC failed), False if it is safe to proceed.
    """
    try:
        has_adhoc, has_project = await _check_running_sessions()
    except _IpcError:
        click.echo(
            "Could not determine session status. Ensure the daemon is stopped before resetting."
        )
        return True

    if has_adhoc:
        click.echo("Active sessions detected. Run 'summon stop --all' first.")
    if has_project:
        click.echo("Project sessions detected. Run 'summon project down' first.")
    if has_adhoc or has_project:
        return True

    # Daemon running with zero sessions — still unsafe to delete data dir
    if is_daemon_running():
        click.echo(
            "The summon daemon is still running. Wait a moment for it to shut down, then retry."
        )
        return True

    return False


async def async_reset_data(ctx: click.Context) -> None:
    """Delete all runtime data (database, logs, etc.) after confirmation."""
    if not is_interactive(ctx):
        click.echo("Reset requires interactive mode.")
        raise SystemExit(1)

    if await _refuse_if_running():
        raise SystemExit(1)

    data_dir = get_data_dir()
    if not data_dir.exists():
        click.echo("Nothing to reset — data directory does not exist.")
        return

    click.echo(
        f"This will delete all runtime data at {data_dir} including the session "
        "database, project registrations, logs, and daemon state."
    )
    click.confirm("Continue?", default=False, abort=True)

    if data_dir.is_symlink():
        click.echo("Error: data directory is a symlink. Refusing to delete.")
        raise SystemExit(1)
    try:
        shutil.rmtree(data_dir)
    except OSError as exc:
        click.echo(f"Failed to delete data directory: {exc}")
        raise SystemExit(1) from exc
    click.echo("Data cleared. Run 'summon start' to begin a new session.")


async def async_reset_config(ctx: click.Context) -> None:
    """Delete all configuration (Slack tokens, Google OAuth credentials) after confirmation."""
    if not is_interactive(ctx):
        click.echo("Reset requires interactive mode.")
        raise SystemExit(1)

    if await _refuse_if_running():
        raise SystemExit(1)

    config_dir = get_config_dir()
    if not config_dir.exists():
        click.echo("Nothing to reset — config directory does not exist.")
        return

    click.echo(
        f"This will delete all configuration at {config_dir} including "
        "Slack tokens and Google OAuth credentials."
    )
    click.confirm("Continue?", default=False, abort=True)

    if config_dir.is_symlink():
        click.echo("Error: config directory is a symlink. Refusing to delete.")
        raise SystemExit(1)
    try:
        shutil.rmtree(config_dir)
    except OSError as exc:
        click.echo(f"Failed to delete config directory: {exc}")
        raise SystemExit(1) from exc
    click.echo(
        "Configuration cleared. Run 'summon hooks uninstall' to remove the Claude Code"
        " hook bridge, then 'summon init' to reconfigure."
    )
