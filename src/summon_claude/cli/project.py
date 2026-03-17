"""Project subcommand logic for CLI."""

from __future__ import annotations

import asyncio
import pathlib
import secrets
from typing import Any

import click

from summon_claude.cli import daemon_client
from summon_claude.daemon import is_daemon_running
from summon_claude.sessions.auth import generate_spawn_token
from summon_claude.sessions.registry import SessionRegistry
from summon_claude.sessions.session import SessionOptions


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


_AUTH_POLL_INTERVAL_S = 2.0
_AUTH_POLL_TIMEOUT_S = 360.0  # 6 minutes


async def _poll_for_completion(session_id: str) -> bool:
    """Poll the registry until a session reaches completed/errored status.

    Returns True if completed, False if errored or timeout.
    """
    try:
        async with (
            asyncio.timeout(_AUTH_POLL_TIMEOUT_S),
            SessionRegistry() as registry,
        ):
            while True:
                await asyncio.sleep(_AUTH_POLL_INTERVAL_S)
                session = await registry.get_session(session_id)
                if session is None:
                    return False
                status = session.get("status")
                if status == "completed":
                    return True
                if status == "errored":
                    return False
    except TimeoutError:
        pass
    return False


async def launch_project_managers() -> list[str]:
    """Start PM sessions for all registered projects that don't have one running.

    Returns a list of session_ids that were started.
    Steps:
    1. Load all projects
    2. Check which already have an active PM session
    3. If any need spawning, create one auth-only session and wait for auth
    4. For each project needing a PM, generate spawn token + create session
    """
    projects: list[dict[str, Any]] = []
    async with SessionRegistry() as registry:
        projects = await registry.list_projects()

    if not projects:
        return []

    # pm_running is SQLite int (0/1) — falsy check works correctly
    needing_pm = [p for p in projects if not p.get("pm_running")]
    if not needing_pm:
        return []

    click.echo(f"Starting PM agents for {len(needing_pm)} project(s)...")

    # Phase 1: authenticate once via auth-only session
    auth_options = SessionOptions(
        cwd=str(pathlib.Path.cwd()),
        name=f"pm-auth-{secrets.token_hex(3)}",
        auth_only=True,
    )

    short_code, auth_session_id = await daemon_client.create_auth_session(auth_options)
    click.echo(f"\nAuthenticate in Slack: /summon {short_code}")

    authenticated = await _poll_for_completion(auth_session_id)
    if not authenticated:
        raise click.ClickException("Authentication timed out or failed.")

    # Retrieve the authenticated user_id from the completed auth session
    auth_session: dict[str, Any] | None = None
    async with SessionRegistry() as registry:
        auth_session = await registry.get_session(auth_session_id)
    if auth_session is None:
        raise click.ClickException("Auth session not found after completion.")
    user_id = auth_session.get("authenticated_user_id")
    if not user_id:
        raise click.ClickException("No authenticated user_id found in auth session.")

    # Phase 2: spawn a PM session for each project needing one
    started: list[str] = []
    for project in needing_pm:
        project_dir = project["directory"]
        if not pathlib.Path(project_dir).is_dir():  # noqa: ASYNC240
            click.echo(
                f"  Skipping {project['name']!r}: directory not found ({project_dir})",
                err=True,
            )
            continue

        token = ""
        async with SessionRegistry() as registry:
            spawn_auth = await generate_spawn_token(
                registry,
                target_user_id=user_id,
                cwd=project_dir,
                spawn_source="cli",
            )
            token = spawn_auth.token

        pm_options = SessionOptions(
            cwd=project_dir,
            name=f"{project['channel_prefix']}-pm-{secrets.token_hex(3)}",
            pm_profile=True,
            project_id=project["project_id"],
        )
        try:
            session_id = await daemon_client.create_session_with_spawn_token(pm_options, token)
            started.append(session_id)
            click.echo(f"  Started PM for {project['name']!r} (session {session_id[:8]}...)")
        except Exception as e:
            click.echo(f"  Failed to start PM for {project['name']!r}: {e}", err=True)

    return started


async def stop_project_managers() -> list[str]:
    """Stop all active PM sessions for registered projects.

    Returns a list of session_ids that were stopped.
    """
    if not is_daemon_running():
        click.echo("Daemon is not running. No PM sessions to stop.")
        return []

    projects: list[dict[str, Any]] = []
    async with SessionRegistry() as registry:
        projects = await registry.list_projects()

    if not projects:
        click.echo("No projects registered.")
        return []

    stopped: list[str] = []
    async with SessionRegistry() as registry:
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
