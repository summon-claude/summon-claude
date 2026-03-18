"""Project subcommand logic for CLI."""

from __future__ import annotations

import pathlib
from typing import Any

import click

from summon_claude.cli import daemon_client
from summon_claude.daemon import is_daemon_running
from summon_claude.sessions.registry import SessionRegistry


def _resolve_directory(directory: str) -> str:
    """Resolve and validate a directory path. Raises ClickException if invalid."""
    resolved = pathlib.Path(directory).resolve()
    if not resolved.is_dir():
        raise click.ClickException(f"Directory does not exist: {resolved}")
    return str(resolved)


async def async_project_add(name: str, directory: str) -> str:
    """Register a new project and return the project_id."""
    resolved = _resolve_directory(directory)
    project_id: str = ""
    async with SessionRegistry() as registry:
        try:
            project_id = await registry.add_project(name, resolved)
        except ValueError as e:
            raise click.ClickException(str(e)) from e
    return project_id


async def async_project_remove(name_or_id: str) -> None:
    """Remove a project by name or ID.

    If the project has active sessions, stops them via daemon IPC first.
    """
    active_ids: list[str] = []
    async with SessionRegistry() as registry:
        try:
            active_ids = await registry.remove_project(name_or_id)
        except ValueError as e:
            raise click.ClickException(str(e)) from e

    # Auto-stop any active sessions that were linked to this project
    if active_ids and is_daemon_running():
        for sid in active_ids:
            try:
                await daemon_client.stop_session(sid)
                click.echo(f"  Stopped session {sid[:8]}...")
            except Exception as e:
                click.echo(f"  Failed to stop session {sid[:8]}...: {e}", err=True)


async def async_project_list() -> list[dict[str, Any]]:
    """Return all projects from the registry."""
    result: list[dict[str, Any]] = []
    async with SessionRegistry() as registry:
        result = await registry.list_projects()
    return result  # noqa: RET504 — pyright requires pre-init before async with


async def launch_project_managers() -> list[str]:
    """Start PM sessions for all registered projects that don't have one running.

    Sends a single ``project_up`` IPC to the daemon, which handles all
    orchestration: auth, project discovery, and PM session creation.

    Returns a list of session_ids that were started.
    """
    response = await daemon_client.project_up(cwd=str(pathlib.Path.cwd()))

    # No projects need PM — daemon responded immediately
    if response.get("type") == "project_up_complete":
        return []

    if response.get("type") != "project_up_auth_required":
        raise click.ClickException(
            f"Unexpected daemon response: {response.get('message', response.get('type'))}"
        )

    short_code = response["short_code"]
    request_id = response["request_id"]
    project_count = response.get("project_count", 0)

    click.echo(f"Starting PM agents for {project_count} project(s)...")
    click.echo(f"\nAuthenticate in Slack: /summon {short_code}")

    # Long-poll the daemon until orchestration completes (after user authenticates).
    # DaemonError is raised by _request() if the daemon returns type=error.
    result = await daemon_client.project_up_await(request_id)

    started = result.get("started", [])
    errors = result.get("errors", [])

    for item in started:
        click.echo(f"  Started PM for {item['project']!r} (session {item['session_id'][:8]}...)")
    for item in errors:
        click.echo(f"  Error ({item['project']}): {item['error']}", err=True)

    return [item["session_id"] for item in started]


async def stop_project_managers() -> list[str]:
    """Stop all active PM sessions for registered projects.

    Returns a list of session_ids that were stopped.
    """
    if not is_daemon_running():
        click.echo("Daemon is not running. No PM sessions to stop.")
        return []

    stopped: list[str] = []
    async with SessionRegistry() as registry:
        projects = await registry.list_projects()
        if not projects:
            click.echo("No projects registered.")
            return []

        for project in projects:
            sessions = await registry.get_project_sessions(project["project_id"])
            active = [s for s in sessions if s.get("status") in ("pending_auth", "active")]
            for session in active:
                sid = session["session_id"]
                try:
                    found = await daemon_client.stop_session(sid)
                    if found:
                        stopped.append(sid)
                        click.echo(f"  Stopped PM for {project['name']!r} (session {sid[:8]}...)")
                except Exception as e:
                    click.echo(f"  Failed to stop session {sid[:8]}...: {e}", err=True)

    if not stopped:
        click.echo("No active PM sessions found.")
    return stopped
