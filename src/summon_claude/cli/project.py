"""Project subcommand logic for CLI."""

from __future__ import annotations

import pathlib

import click

from summon_claude.sessions.registry import SessionRegistry


def _resolve_directory(directory: str) -> str:
    """Resolve and validate a directory path. Raises ClickException if invalid."""
    resolved = str(pathlib.Path(directory).resolve())
    if not pathlib.Path(resolved).is_dir():
        raise click.ClickException(f"Directory does not exist: {resolved}")
    return resolved


async def async_project_add(name: str, directory: str) -> str:
    """Register a new project and return the project_id."""
    resolved = _resolve_directory(directory)
    async with SessionRegistry() as registry:
        try:
            project_id = await registry.add_project(name, resolved)
        except ValueError as e:
            raise click.ClickException(str(e)) from e
    return project_id


async def async_project_remove(name_or_id: str) -> None:
    """Remove a project by name or ID."""
    async with SessionRegistry() as registry:
        try:
            await registry.remove_project(name_or_id)
        except ValueError as e:
            raise click.ClickException(str(e)) from e


async def async_project_list() -> list[dict]:
    """Return all projects from the registry."""
    async with SessionRegistry() as registry:
        return await registry.list_projects()
