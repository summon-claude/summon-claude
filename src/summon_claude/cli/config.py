"""CLI config subcommands: show, path, edit, set."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

from summon_claude.config import (
    _BOOL_FALSE,
    _BOOL_TRUE,
    CONFIG_OPTIONS,
    find_workspace_mcp_bin,
    get_config_file,
    get_data_dir,
    get_google_credentials_dir,
)
from summon_claude.sessions.migrations import CURRENT_SCHEMA_VERSION, get_schema_version
from summon_claude.sessions.registry import SessionRegistry

logger = logging.getLogger(__name__)

# Required Slack bot scopes — must match slack-app-manifest.yaml.
# Guard test test_required_scopes_match_manifest pins this set.
_REQUIRED_SLACK_SCOPES: frozenset[str] = frozenset(
    {
        "canvases:read",
        "canvases:write",
        "channels:history",
        "channels:join",
        "channels:manage",
        "channels:read",
        "chat:write",
        "commands",
        "files:read",
        "files:write",
        "groups:history",
        "groups:read",
        "groups:write",
        "reactions:read",
        "reactions:write",
        "users:read",
    }
)


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env-style config file into a dict. Returns {} if the file does not exist."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            k, _, v = stripped.partition("=")
            values[k.strip()] = v.strip()
    return values


def _require_config_file(override: str | None = None):
    """Return the config file Path if it exists, else print a hint and return None."""
    config_file = get_config_file(override)
    if not config_file.exists():
        click.echo(f"No config file found at {config_file}")
        click.echo("Run `summon init` to create one.")
        return None
    return config_file


def config_path(override: str | None = None) -> None:
    click.echo(str(get_config_file(override)))


def config_show(override: str | None = None, *, color: bool = True) -> None:
    """Show all config options with grouped display and source indicators."""
    from summon_claude.config import get_config_default  # noqa: PLC0415

    config_file = get_config_file(override)
    values = parse_env_file(config_file)
    if not config_file.exists():
        click.echo(f"No config file found at {config_file}")
        click.echo("Run `summon init` to create one.\n")

    current_group = ""
    for opt in CONFIG_OPTIONS:
        # Evaluate visibility predicate
        if opt.visible is not None and not opt.visible(values):
            # Show dim hint for hidden groups (only once per group).
            # Uses current_group so groups with at least one visible item
            # don't also print a "disabled" hint for their hidden items.
            if opt.group != current_group:
                current_group = opt.group
                hint = (
                    click.style(f"\n  {opt.group}: disabled", dim=True)
                    if color
                    else f"\n  {opt.group}: disabled"
                )
                click.echo(hint)
            continue

        # Print group header on group change
        if opt.group != current_group:
            current_group = opt.group
            if color:
                click.echo(click.style(f"\n  {opt.group}", bold=True))
            else:
                click.echo(f"\n  {opt.group}")

        # Determine value and source
        file_value = values.get(opt.env_key)
        default = get_config_default(opt)

        if opt.input_type == "secret":
            if file_value:
                display_value = "configured"
                source = "set"
            elif opt.required:
                display_value = ""
                source = "not set"
            else:
                display_value = ""
                source = "optional"
        elif file_value is not None:
            display_value = file_value
            if isinstance(default, bool):
                default_str = str(default).lower()
            else:
                default_str = str(default) if default is not None else ""
            source = "default" if file_value == default_str else "set"
        elif opt.required:
            display_value = ""
            source = "not set"
        else:
            if isinstance(default, bool):
                display_value = str(default).lower()
            else:
                display_value = str(default) if default is not None else ""
            source = "default"

        # Truncate long values to keep columns aligned
        val_col = 30
        if display_value and len(display_value) > val_col:
            display_value = display_value[: val_col - 1] + "\u2026"

        # Format output with color
        if color:
            if source == "set":
                source_label = click.style("(set)", fg="green")
            elif source == "not set":
                source_label = click.style("(not set)", fg="yellow")
            elif source == "optional":
                source_label = click.style("(optional)", dim=True)
            else:
                source_label = click.style("(default)", dim=True)
            # Pad before styling to avoid ANSI escape codes breaking alignment
            if display_value:
                val_display = f"{display_value:<{val_col}}"
            else:
                val_display = click.style(f"{'—':<{val_col}}", dim=True)
        else:
            source_label = f"({source})"
            val_display = f"{(display_value if display_value else '—'):<{val_col}}"

        click.echo(f"    {opt.env_key:<40} {val_display} {source_label}")


def config_edit(override: str | None = None) -> None:
    config_file = _require_config_file(override)
    if config_file is None:
        return

    editor = os.environ.get("EDITOR", "vi")
    try:
        subprocess.run([*shlex.split(editor), str(config_file)], check=False)  # noqa: S603
    except FileNotFoundError:
        click.echo(f"Editor '{editor}' not found. Set $EDITOR to your preferred editor.", err=True)
        sys.exit(1)


def config_set(key: str, value: str, override: str | None = None) -> None:
    key = key.strip().upper()
    valid_keys = {opt.env_key for opt in CONFIG_OPTIONS}
    if key not in valid_keys:
        click.echo(f"Unknown config key: {key!r}", err=True)
        click.echo(f"Valid keys: {', '.join(sorted(valid_keys))}", err=True)
        sys.exit(1)

    # Bool normalization for flag-type options
    option = next((opt for opt in CONFIG_OPTIONS if opt.env_key == key), None)
    if option and option.input_type == "flag":
        lower = value.lower()
        if lower in _BOOL_TRUE:
            value = "true"
        elif lower in _BOOL_FALSE:
            value = "false"
        else:
            click.echo(f"Invalid boolean value: {value!r}. Use true/false/yes/no/1/0.", err=True)
            sys.exit(1)

    # Validate choices for choice-type options (choices_fn takes precedence over static choices)
    if option and value:
        choices: list[str] = []
        if option.choices_fn:
            try:
                choices = option.choices_fn()
            except Exception as e:
                click.echo(f"Error resolving choices for {key}: {e}", err=True)
                sys.exit(1)
        elif option.choices:
            choices = list(option.choices)
        if choices and value not in choices:
            click.echo(
                f"Invalid value for {key}: {value!r}. Must be one of: {', '.join(choices)}",
                err=True,
            )
            sys.exit(1)

    # Run option validator if present
    if option and option.validate_fn and value:
        err = option.validate_fn(value)
        if err:
            click.echo(f"Invalid value for {key}: {err}", err=True)
            sys.exit(1)

    # Strip newlines to prevent injection into the .env format
    value = value.replace("\n", "").replace("\r", "")

    config_file = get_config_file(override)
    config_file.parent.mkdir(parents=True, exist_ok=True)

    # Read existing lines
    lines = config_file.read_text().splitlines() if config_file.exists() else []

    updated = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped == key:
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"{key}={value}")

    config_file.write_text("\n".join(new_lines) + "\n")
    with contextlib.suppress(OSError):
        config_file.chmod(0o600)
    click.echo(f"Set {key} in {config_file}")


_CHOICE_CURRENT = "use-current"
_CHOICE_EXISTING = "enter-existing"
_CHOICE_NEW = "create-new"
_CHOICE_SKIP = "skip"

_SETUP_STEPS = [
    "Google Cloud Project",
    "Enable APIs",
    "OAuth Consent Screen",
    "Create OAuth Client",
]


def _setup_roadmap(step: int, completed: dict[int, str]) -> str:
    """Return the step roadmap as a plain-text string (for pick titles)."""
    lines = [
        f"Google OAuth Setup                            Step {step} of {len(_SETUP_STEPS)}",
        "-" * 60,
    ]
    for i, title in enumerate(_SETUP_STEPS, 1):
        if i in completed:
            detail = f" [{completed[i]}]" if completed[i] else ""
            lines.append(f"  ✓ {i}. {title}{detail}")
        elif i == step:
            lines.append(f"  ◉ {i}. {title}")
        else:
            lines.append(f"    {i}. {title}")
    lines.append("")
    lines.append("-" * 60)
    lines.append("")
    return "\n".join(lines)


def _setup_header(step: int, completed: dict[int, str], *, skip_clear: bool = False) -> None:
    """Render a step header with progress roadmap to the terminal."""
    if not skip_clear:
        click.clear()
    click.secho(
        f"Google OAuth Setup                            Step {step} of {len(_SETUP_STEPS)}",
        bold=True,
    )
    click.echo(click.style("-" * 60, dim=True))
    for i, title in enumerate(_SETUP_STEPS, 1):
        if i in completed:
            detail = f" [{completed[i]}]" if completed[i] else ""
            click.secho(f"  ✓ {i}. {title}{detail}", fg="green")
        elif i == step:
            click.secho(f"  ◉ {i}. {title}", bold=True)
        else:
            click.secho(f"    {i}. {title}", dim=True)
    click.echo()


def _run_gcloud(
    gcloud_bin: str,
    args: list[str],
    *,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run a gcloud command and return the result."""
    return subprocess.run(  # noqa: S603
        [gcloud_bin, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _make_console_url_builder(
    gcloud_email: str | None,
):
    """Return a function that builds Google Console URLs.

    With *gcloud_email*: appends ``authuser=<email>`` to the URL.
    Without: wraps through the Google account chooser.
    """
    from urllib.parse import quote, urlencode, urlparse, urlunparse  # noqa: PLC0415

    def _build(base_url: str, **extra_params: str) -> str:
        parsed = urlparse(base_url)
        params: dict[str, str] = {}
        # Preserve existing query params (e.g. ?apiid=...)
        if parsed.query:
            for part in parsed.query.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v
        params.update(extra_params)
        if gcloud_email:
            params["authuser"] = gcloud_email
        qs = urlencode(params)
        target = urlunparse(parsed._replace(query=qs))
        if gcloud_email:
            return target
        return f"https://accounts.google.com/AccountChooser?continue={quote(target, safe='')}"

    return _build


def _open_or_print(url: str) -> None:
    """Print a URL and offer to open it in the browser."""
    click.secho(f"  {url}", fg="cyan")
    if click.confirm("  Open in browser?", default=True):
        click.launch(url)


def _show_and_open(urls: list[tuple[str, str]]) -> None:
    """Print labelled URLs, then offer to open all at once.

    *urls* is a list of ``(label, url)`` pairs.
    """
    for label, url in urls:
        click.secho(f"  {label}:", bold=True)
        click.secho(f"    {url}", fg="cyan")
    click.echo()
    if click.confirm("  Open all in browser?", default=True):
        for _, url in urls:
            click.launch(url)


def google_setup() -> None:
    """Interactive guided setup for Google OAuth credentials."""
    # Check for existing credentials
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    secrets_file = get_google_credentials_dir() / "client_env"

    if not (client_id and client_secret) and secrets_file.exists():
        for line in secrets_file.read_text().splitlines():
            if line.startswith("GOOGLE_OAUTH_CLIENT_ID="):
                client_id = line.split("=", 1)[1].strip()
            elif line.startswith("GOOGLE_OAUTH_CLIENT_SECRET="):
                client_secret = line.split("=", 1)[1].strip()

    if (
        client_id
        and client_secret
        and not click.confirm(
            "Google OAuth credentials already configured. Re-run setup?", default=False
        )
    ):
        return

    project_id: str | None = None
    _gcloud_bin = shutil.which("gcloud")
    has_gcloud = _gcloud_bin is not None
    completed: dict[int, str] = {}

    # Detect gcloud account email for URL authuser parameter
    _gcloud_email: str | None = None
    if has_gcloud:
        try:
            result = _run_gcloud(_gcloud_bin, ["config", "get-value", "account"], timeout=10)
            _val = result.stdout.strip()
            if result.returncode == 0 and _val and _val != "(unset)" and "@" in _val:
                _gcloud_email = _val
        except (subprocess.TimeoutExpired, OSError):
            pass

    _url = _make_console_url_builder(_gcloud_email)

    # ── Step 1: GCP Project ─────────────────────────────────────────────

    # Detect current gcloud project (before rendering, to build choices)
    _current_project: str | None = None
    if has_gcloud:
        try:
            result = _run_gcloud(_gcloud_bin, ["config", "get-value", "project"], timeout=10)
            _val = result.stdout.strip()
            if result.returncode == 0 and _val and _val != "(unset)":
                _current_project = _val
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Build choices
    _choices: list[str] = []
    _choice_keys: list[str] = []
    if _current_project:
        _choices.append(f"Use current gcloud project: {_current_project}")
        _choice_keys.append(_CHOICE_CURRENT)
    _choices.append("Enter an existing project ID")
    _choice_keys.append(_CHOICE_EXISTING)
    _choices.append("Create a new project")
    _choice_keys.append(_CHOICE_NEW)
    _choices.append("Skip this step")
    _choice_keys.append(_CHOICE_SKIP)

    _project_id_re = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")

    while True:  # Loop allows "go back" after resolution
        project_id = None

        if sys.stdin.isatty():
            import pick  # noqa: PLC0415

            _pick_title = _setup_roadmap(1, completed) + "Select or create a Google Cloud project:"
            try:
                _, idx = pick.pick(_choices, _pick_title, indicator=">")
            except KeyboardInterrupt:
                return
            choice = _choice_keys[int(idx)]  # type: ignore[arg-type]
        else:
            _setup_header(1, completed)
            click.echo("Select or create a Google Cloud project.\n")
            for i, label in enumerate(_choices, 1):
                click.echo(f"  {i}) {label}")
            try:
                raw_idx = click.prompt("Select", type=click.IntRange(1, len(_choices)))
            except (KeyboardInterrupt, click.Abort):
                return
            choice = _choice_keys[raw_idx - 1]

        # Re-render after pick exits curses
        _setup_header(1, completed)

        if choice == _CHOICE_CURRENT:
            project_id = _current_project
        elif choice == _CHOICE_EXISTING:
            _browse_url = _url("https://console.cloud.google.com/projectselector2/home")
            click.echo("Browse your GCP projects:\n")
            _open_or_print(_browse_url)
            click.echo()
            project_id = click.prompt(
                "Enter project ID, name, or number", default="", show_default=False
            ).strip()
        elif choice == _CHOICE_NEW:
            import secrets as secrets_mod  # noqa: PLC0415

            suggested = f"summon-claude-{secrets_mod.token_hex(3)[:5]}"
            project_id = click.prompt("Project ID", default=suggested).strip()
        else:
            break  # skip

        # Resolve names/numbers to project ID (for existing project input)
        if project_id and choice != _CHOICE_NEW and not _project_id_re.match(project_id):
            if has_gcloud:
                try:
                    result = _run_gcloud(
                        _gcloud_bin,
                        ["projects", "describe", project_id, "--format=value(projectId)"],
                        timeout=15,
                    )
                    resolved = result.stdout.strip()
                    if result.returncode == 0 and resolved:
                        project_id = resolved
                    else:
                        click.secho(f"  Could not resolve '{project_id}'.", fg="yellow")
                        project_id = None
                except (subprocess.TimeoutExpired, OSError):
                    click.secho("  Could not reach gcloud to resolve project.", fg="yellow")
            else:
                click.secho(
                    f"  '{project_id}' doesn't look like a project ID"
                    " (install gcloud to resolve names/numbers).",
                    fg="yellow",
                )
                project_id = None

        # Validate format for new projects
        if project_id and choice == _CHOICE_NEW and not _project_id_re.match(project_id):
            click.secho(
                "  Invalid project ID: 6-30 chars, lowercase letters/digits/hyphens,",
                fg="yellow",
            )
            click.secho("  starts with a letter, cannot end with a hyphen.", fg="yellow")
            project_id = None

        if not project_id:
            click.pause("  Press Enter to try again...")
            continue

        # Create the project if needed
        if choice == _CHOICE_NEW:
            _create_browser = _url("https://console.cloud.google.com/projectcreate")
            if has_gcloud:
                click.echo(f'\n  gcloud projects create {project_id} --name="summon-claude"\n')
                if click.confirm("  Run this now?", default=True):
                    try:
                        result = _run_gcloud(
                            _gcloud_bin,
                            ["projects", "create", project_id, "--name=summon-claude"],
                            timeout=60,
                        )
                        if result.returncode == 0:
                            click.secho("  ✓ Project created.", fg="green")
                        else:
                            stderr = result.stderr.strip()
                            if "already exists" in stderr.lower():
                                click.echo("  Project already exists — continuing.")
                            else:
                                click.secho(f"  gcloud error: {stderr}", fg="red")
                                click.echo(f"  Create manually: {_create_browser}")
                    except (subprocess.TimeoutExpired, OSError) as e:
                        click.echo(f"  Could not run gcloud: {e}")
                        click.echo(f"  Create manually: {_create_browser}")
                else:
                    _open_or_print(_create_browser)
            else:
                click.echo("\nCreate your project:\n")
                _open_or_print(_create_browser)

        # Verify project exists (all paths — consistent gate before confirm)
        if has_gcloud:
            try:
                result = _run_gcloud(
                    _gcloud_bin,
                    ["projects", "describe", project_id, "--format=value(projectId)"],
                    timeout=15,
                )
                resolved = result.stdout.strip()
                if result.returncode == 0 and resolved:
                    project_id = resolved  # Canonicalize
                else:
                    click.secho(f"\n  Project '{project_id}' not found.", fg="yellow")
                    click.pause("  Press Enter to try again...")
                    continue
            except (subprocess.TimeoutExpired, OSError):
                pass  # Can't verify — proceed with confirm

        # Show result in the step tracker and confirm
        completed[1] = project_id
        _setup_header(1, completed)
        if click.confirm(f"  Confirm project '{project_id}'?", default=True):
            break
        # User said no — clear and loop back
        del completed[1]

    if 1 not in completed:
        completed[1] = project_id or "skipped"

    # ── Step 2: Enable APIs ─────────────────────────────────────────────
    _setup_header(2, completed)
    click.echo("Enable required Google APIs for your project.\n")

    apis = [
        ("Gmail API", "gmail.googleapis.com"),
        ("Calendar API", "calendar-json.googleapis.com"),
        ("Drive API", "drive.googleapis.com"),
    ]
    _required_api_ids = {api_id for _, api_id in apis}

    def _check_apis_enabled() -> set[str]:
        """Return the set of required APIs that are currently enabled."""
        if not has_gcloud or not project_id:
            return set()
        try:
            result = _run_gcloud(
                _gcloud_bin,  # type: ignore[arg-type]
                [
                    "services",
                    "list",
                    "--enabled",
                    f"--project={project_id}",
                    "--format=value(config.name)",
                ],
                timeout=15,
            )
            if result.returncode == 0:
                enabled = {line.strip() for line in result.stdout.splitlines() if line.strip()}
                return _required_api_ids & enabled
        except (subprocess.TimeoutExpired, OSError):
            pass
        return set()

    # Pre-check: skip if all APIs already enabled
    _already_enabled = _check_apis_enabled()
    if _already_enabled == _required_api_ids:
        click.secho("  ✓ All required APIs already enabled.", fg="green")
        completed[2] = ", ".join(label for label, _ in apis)
    else:
        if _already_enabled:
            for label, api_id in apis:
                if api_id in _already_enabled:
                    click.secho(f"  ✓ {label}", fg="green")
                else:
                    click.secho(f"    {label}", dim=True)
            click.echo()

        _api_url_params = {"project": project_id} if project_id else {}
        _api_urls = [
            (
                label,
                _url(
                    f"https://console.cloud.google.com/flows/enableapi?apiid={api_id}",
                    **_api_url_params,
                ),
            )
            for label, api_id in apis
            if api_id not in _already_enabled
        ]
        _apis_ok = False

        if has_gcloud:
            missing_ids = [a for _, a in apis if a not in _already_enabled]
            project_flag = f" --project={project_id}" if project_id else ""
            _gcloud_cmd = f"gcloud services enable {' '.join(missing_ids)}{project_flag}"
            click.echo(f"  {_gcloud_cmd}\n")
            if click.confirm("  Run this now?", default=True):
                try:
                    result = _run_gcloud(
                        _gcloud_bin,
                        [
                            "services",
                            "enable",
                            *missing_ids,
                            *([f"--project={project_id}"] if project_id else []),
                        ],
                        timeout=60,
                    )
                    if result.returncode == 0:
                        click.secho("  ✓ APIs enabled.", fg="green")
                        _apis_ok = True
                    else:
                        click.secho(f"  gcloud error: {result.stderr.strip()}", fg="red")
                        click.echo("  Enable manually via the links below.\n")
                except (subprocess.TimeoutExpired, OSError) as e:
                    click.echo(f"  Could not run gcloud: {e}")
                    click.echo("  Enable manually via the links below.\n")

        if not _apis_ok:
            _show_and_open(_api_urls)
            click.pause("\n  Press Enter when APIs are enabled...")

            # Post-verify
            if has_gcloud and project_id:
                _now_enabled = _check_apis_enabled()
                _still_missing = _required_api_ids - _now_enabled
                if _still_missing:
                    missing_labels = [lbl for lbl, aid in apis if aid in _still_missing]
                    click.secho(
                        f"  Warning: still not enabled: {', '.join(missing_labels)}",
                        fg="yellow",
                    )

        completed[2] = ", ".join(label for label, _ in apis)

    # ── Step 3: OAuth Consent Screen ────────────────────────────────────
    _setup_header(3, completed)
    _proj_params = {"project": project_id} if project_id else {}
    branding_url = _url("https://console.developers.google.com/auth/branding", **_proj_params)
    audience_url = _url("https://console.developers.google.com/auth/audience", **_proj_params)

    if click.confirm("  Already configured the consent screen?", default=False):
        completed[3] = "already configured"
    else:
        _is_gmail = _gcloud_email and _gcloud_email.endswith("@gmail.com")
        _is_workspace = _gcloud_email and not _is_gmail
        click.echo("\nConfigure the OAuth consent screen:\n")
        click.echo("  1. Under Branding: fill in App name (e.g. 'summon-claude'),")
        click.echo("     User support email (your email)")
        if _is_gmail:
            click.echo("  2. Under Audience: select 'External' user type")
            click.secho("     (required for @gmail.com accounts)", dim=True)
            click.echo("  3. Under Publishing status: click 'Publish App' to switch to Production")
            click.secho("     (avoids 7-day token expiry for External apps)", dim=True)
        elif _is_workspace:
            click.echo("  2. Under Audience: select 'Internal' user type")
            click.secho("     (no unverified-app warning, no user cap, no token expiry)", dim=True)
        else:
            click.echo("  2. Under Audience: select 'Internal' if available, otherwise 'External'")
            click.secho(
                "     (Internal = Workspace only, no warnings; External = any account)",
                dim=True,
            )
            click.echo("  3. If you chose External: click 'Publish App' to switch to Production")
            click.secho("     (avoids 7-day token expiry for External apps)", dim=True)
        click.echo()
        _show_and_open([("Branding", branding_url), ("Audience", audience_url)])
        click.echo()
        if _is_gmail:
            click.secho(
                "  Note: You'll see an 'unverified app' warning during login —"
                " normal for personal use.",
                dim=True,
            )
        click.pause("\n  Press Enter when consent screen is configured...")
        completed[3] = "done"

    # ── Step 4: Create OAuth Client ─────────────────────────────────────
    _setup_header(4, completed)
    client_url = _url("https://console.developers.google.com/auth/clients/create", **_proj_params)

    click.echo("Create an OAuth client:\n")
    click.echo("  1. Application type: 'Desktop app'")
    click.echo("  2. Name: 'summon-claude' (or anything)")
    click.echo("  3. Click 'Create'")
    click.echo("  4. Click 'Download JSON' to save client_secret.json\n")
    _open_or_print(client_url)

    # Credential input loop
    import glob as glob_mod  # noqa: PLC0415
    import json as json_mod  # noqa: PLC0415
    import readline  # noqa: PLC0415

    _downloads = Path.home() / "Downloads"

    def _scan_downloads() -> list[Path]:
        if not _downloads.is_dir():
            return []
        return sorted(
            _downloads.glob("client_secret*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def _offer_detected(detected: list[Path]) -> str | None:
        """Offer detected files to the user. Returns selected path or None."""
        if len(detected) == 1:
            click.secho(f"\n  Found: {detected[0].name}", fg="green")
            if click.confirm(f"  Use {detected[0]}?", default=True):
                return str(detected[0])
            return None
        # Multiple files
        click.echo()
        if sys.stdin.isatty():
            import pick  # noqa: PLC0415

            _file_choices = [f"{p.name}  ({p.parent})" for p in detected]
            _file_choices.append("Enter path manually")
            try:
                _, idx = pick.pick(
                    _file_choices,
                    "Found client_secret files in Downloads:",
                    indicator=">",
                )
                if int(idx) < len(detected):  # type: ignore[arg-type]
                    return str(detected[int(idx)])  # type: ignore[arg-type]
            except KeyboardInterrupt:
                pass
        else:
            click.echo("  Found client_secret files in Downloads:\n")
            for i, p in enumerate(detected, 1):
                click.echo(f"    {i}) {p.name}")
            click.echo(f"    {len(detected) + 1}) Enter path manually")
            try:
                raw = click.prompt("  Select", type=click.IntRange(1, len(detected) + 1))
                if raw <= len(detected):
                    return str(detected[raw - 1])
            except (KeyboardInterrupt, click.Abort):
                pass
        return None

    # Set up readline tab-completion for manual path entry
    def _path_completer(text: str, state: int) -> str | None:
        expanded = str(Path(text).expanduser())
        # glob.glob required here — readline expects plain strings, not Path objects
        matches = glob_mod.glob(expanded + "*")  # noqa: PTH207
        matches = [m + "/" if Path(m).is_dir() else m for m in matches]
        return matches[state] if state < len(matches) else None

    _prev_completer = readline.get_completer()
    _prev_delims = readline.get_completer_delims()
    readline.set_completer(_path_completer)
    readline.set_completer_delims(" \t\n")
    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")

    try:
        while True:
            # Scan Downloads on every iteration (catches newly downloaded files)
            _detected = _scan_downloads()
            if _detected:
                _selected = _offer_detected(_detected)
                if _selected:
                    response = _selected
                else:
                    # User declined detected files — fall through to manual input
                    try:
                        response = input("Path to client_secret.json (or paste Client ID): ")
                    except EOFError:
                        response = ""
            else:
                try:
                    response = input("Path or Client ID (Enter to re-scan ~/Downloads): ")
                except EOFError:
                    response = ""

            if not response:
                # Empty input = re-scan Downloads on next iteration
                click.secho("  Scanning ~/Downloads...", dim=True)
                continue

            response = response.strip()
            json_path = Path(response).expanduser()

            if json_path.suffix == ".json" or json_path.exists():
                # JSON file path
                if not json_path.exists():
                    click.echo(f"File not found: {json_path}")
                    continue
                try:
                    raw_text = json_path.read_text()
                    data = json_mod.loads(raw_text)
                    inner = data.get("installed") or data.get("web") or data
                    client_id = inner["client_id"].replace("\n", "").replace("\r", "")
                    client_secret = inner["client_secret"].replace("\n", "").replace("\r", "")
                except (json_mod.JSONDecodeError, KeyError, TypeError, OSError) as e:
                    click.echo(f"Invalid client_secret.json: {e}")
                    continue
                # Copy JSON to credentials dir for workspace-mcp (0o600 from creation)
                dest = get_google_credentials_dir() / "client_secret.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(raw_text)
                click.secho(f"  ✓ Copied {json_path.name} to {dest}", fg="green")
            else:
                # User pasted a Client ID directly — strip newlines to prevent
                # format injection into client_env file (matches config_set pattern)
                client_id = response.replace("\n", "").replace("\r", "")
                client_secret = (
                    click.prompt("Google OAuth Client Secret", default="", show_default=False)
                    .replace("\n", "")
                    .replace("\r", "")
                )
                if not client_secret:
                    click.echo("Client Secret is required.")
                    continue

            break
    finally:
        # Restore readline state even on KeyboardInterrupt
        readline.set_completer(_prev_completer)
        readline.set_completer_delims(_prev_delims)

    # Save credentials (atomic write with 0o600 from creation — no world-readable window)
    creds_dir = get_google_credentials_dir()
    creds_dir.mkdir(parents=True, exist_ok=True)
    secrets_file = creds_dir / "client_env"
    fd = os.open(secrets_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"GOOGLE_OAUTH_CLIENT_ID={client_id}\nGOOGLE_OAUTH_CLIENT_SECRET={client_secret}\n")
    completed[4] = "saved"

    # Final success screen
    _setup_header(4, completed, skip_clear=False)
    click.secho("  ✓ Credentials saved.", fg="green")
    click.secho(f"    {secrets_file}", dim=True)
    click.echo()
    click.echo("Run `summon auth google login` to authenticate.")


# Read-only by default.  Append `:rw` to a service name to opt into write
# scopes (e.g. "calendar:rw").  This keeps the consent screen minimal while
# still being compatible with workspace-mcp's has_required_scopes() hierarchy.
_GOOGLE_SCOPE_PREFIX = "https://www.googleapis.com/auth/"
_GOOGLE_SERVICE_SCOPES: dict[str, dict[str, list[str]]] = {
    "gmail": {
        "ro": ["gmail.readonly"],
        "rw": ["gmail.modify", "gmail.settings.basic"],
    },
    "drive": {
        "ro": ["drive.readonly"],
        "rw": ["drive"],
    },
    "calendar": {
        "ro": ["calendar.readonly"],
        "rw": ["calendar"],
    },
}
_GOOGLE_BASE_SCOPES = [
    "openid",
    f"{_GOOGLE_SCOPE_PREFIX}userinfo.email",
    f"{_GOOGLE_SCOPE_PREFIX}userinfo.profile",
]


def _google_scopes_for_services(services: list[str]) -> list[str]:
    """Build a minimal OAuth scope list from service specs.

    Each entry is ``"service"`` (read-only) or ``"service:rw"`` (read-write).
    Unknown services are silently skipped so the caller can validate separately.
    """
    scopes: list[str] = list(_GOOGLE_BASE_SCOPES)
    for spec in services:
        name, _, mode = spec.partition(":")
        tier = "rw" if mode == "rw" else "ro"
        entry = _GOOGLE_SERVICE_SCOPES.get(name)
        if entry:
            for s in entry[tier]:
                full = s if s.startswith("https://") else f"{_GOOGLE_SCOPE_PREFIX}{s}"
                if full not in scopes:
                    scopes.append(full)
    return scopes


def _describe_granted_scopes(granted: set[str]) -> str:
    """Return a short human summary of granted Google scopes."""
    parts: list[str] = []
    for svc, tiers in _GOOGLE_SERVICE_SCOPES.items():
        rw_scopes = {
            s if s.startswith("https://") else f"{_GOOGLE_SCOPE_PREFIX}{s}" for s in tiers["rw"]
        }
        ro_scopes = {
            s if s.startswith("https://") else f"{_GOOGLE_SCOPE_PREFIX}{s}" for s in tiers["ro"]
        }
        if rw_scopes & granted:
            parts.append(f"{svc} (read-write)")
        elif ro_scopes & granted:
            parts.append(f"{svc} (read-only)")
    return ", ".join(parts)


_GOOGLE_WRITE_PROMPTS: dict[str, str] = {
    "gmail": "Send and compose emails via Gmail",
    "calendar": "Create and edit Google Calendar events",
    "drive": "Create, edit, and delete Google Drive files",
}


def _load_google_client_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret) or sys.exit."""
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")

    if not (client_id and client_secret):
        secrets_file = get_google_credentials_dir() / "client_env"
        if secrets_file.exists():
            for line in secrets_file.read_text().splitlines():
                if line.startswith("GOOGLE_OAUTH_CLIENT_ID="):
                    client_id = line.split("=", 1)[1].strip()
                elif line.startswith("GOOGLE_OAUTH_CLIENT_SECRET="):
                    client_secret = line.split("=", 1)[1].strip()

    if not (client_id and client_secret):
        click.echo("No Google OAuth credentials configured.", err=True)
        click.echo("Run `summon auth google setup` to create and configure credentials.", err=True)
        sys.exit(1)

    return client_id, client_secret


def _secure_credential_files(creds_dir: Path) -> None:
    """Ensure all credential JSON files are owner-readable only (0600)."""
    for p in creds_dir.glob("*.json"):
        p.chmod(0o600)


def _run_google_oauth(
    client_id: str,
    client_secret: str,
    scopes: list[str],
) -> Any:
    """Open a browser, complete the OAuth flow, and return credentials."""
    from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    import warnings  # noqa: PLC0415

    click.echo("Opening browser for Google authorization...\n")
    try:
        flow = InstalledAppFlow.from_client_config(client_config, scopes=scopes)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="datetime.datetime.utcfromtimestamp",
                category=DeprecationWarning,
            )
            return flow.run_local_server(
                port=0,
                open_browser=True,
                prompt="consent",
                access_type="offline",
            )
    except Exception as e:
        click.echo(f"Google auth flow failed: {e}", err=True)
        sys.exit(1)


def _resolve_google_email(cred: Any) -> str:
    """Discover the authenticated user's email, falling back to 'default'."""
    try:
        from googleapiclient.discovery import build  # noqa: PLC0415

        svc = build("oauth2", "v2", credentials=cred)
        return svc.userinfo().get().execute().get("email", "default")
    except Exception:
        return "default"


def google_auth() -> None:
    """Interactive Google Workspace authentication."""
    try:
        from auth.credential_store import LocalDirectoryCredentialStore  # noqa: PLC0415
        from auth.google_auth import has_required_scopes  # noqa: PLC0415
    except ImportError:
        click.echo(
            "Google Workspace support requires the 'google' extra: "
            "uv pip install summon-claude[google]",
            err=True,
        )
        sys.exit(1)

    client_id, client_secret = _load_google_client_credentials()
    creds_dir = get_google_credentials_dir()
    store = LocalDirectoryCredentialStore(str(creds_dir))

    # Load existing credential to derive prompt defaults.
    existing_cred = None
    users = store.list_users()
    if users:
        existing_cred = store.get_credential(users[0])

    # Detect which services already have write access.
    granted = set(existing_cred.scopes or []) if existing_cred else set()
    existing_rw: set[str] = set()
    for svc, tiers in _GOOGLE_SERVICE_SCOPES.items():
        rw_scopes = {
            s if s.startswith("https://") else f"{_GOOGLE_SCOPE_PREFIX}{s}" for s in tiers["rw"]
        }
        if rw_scopes & granted:
            existing_rw.add(svc)

    # Ask which services need write access.
    click.echo("All services get read-only access by default.")
    click.echo("Grant write access to any of these?\n")
    services: list[str] = []
    for svc, desc in _GOOGLE_WRITE_PROMPTS.items():
        default = svc in existing_rw
        if click.confirm(f"  {desc}", default=default):
            services.append(f"{svc}:rw")
        else:
            services.append(svc)
    click.echo()

    scopes = _google_scopes_for_services(services)

    # If valid credentials exist, check whether they exactly match the
    # requested scopes.  Re-auth if scopes were added OR removed.
    need_reauth = True
    if existing_cred:
        from google.auth.transport.requests import Request  # noqa: PLC0415

        # Refresh if expired.
        if existing_cred.expired and existing_cred.refresh_token:
            try:
                existing_cred.refresh(Request())
                store.store_credential(users[0], existing_cred)
                _secure_credential_files(creds_dir)
            except Exception:
                existing_cred = None  # force re-auth below

        if existing_cred and existing_cred.valid:
            requested_set = set(scopes)
            if has_required_scopes(granted, scopes) and requested_set == (granted & requested_set):
                # Granted scopes cover everything requested AND the user
                # didn't narrow any service (e.g. drop calendar write).
                need_reauth = False
            elif has_required_scopes(granted, scopes):
                # Granted scopes are broader than requested — user is
                # dropping write access.  Re-auth with the smaller set.
                click.echo("Re-authenticating to narrow scope access.\n")
            else:
                click.echo("Current credentials are missing some requested scopes.\n")

    if not need_reauth:
        click.echo(f"Google credentials for {users[0]} already cover the requested scopes.")
    else:
        cred = _run_google_oauth(client_id, client_secret, scopes)
        user_email = _resolve_google_email(cred)
        store.store_credential(user_email, cred)
        _secure_credential_files(creds_dir)
        click.echo()
        click.echo(f"Google Workspace authenticated as {user_email}.")
        click.echo(f"Credentials stored in {creds_dir}")

    # Context-aware next-step guidance.
    from summon_claude.daemon import is_daemon_running  # noqa: PLC0415

    click.echo()
    values = parse_env_file(get_config_file())
    scribe_on = values.get("SUMMON_SCRIBE_ENABLED", "").lower() in ("true", "1", "yes")
    daemon_up = is_daemon_running()
    if scribe_on and daemon_up:
        click.echo("Scribe will pick up Google tools on next project restart:")
        click.echo("  summon project down && summon project up")
    elif scribe_on:
        click.echo("Scribe will use Google tools on next start:")
        click.echo("  summon project up")
    else:
        click.echo("To use Google tools, enable the scribe agent:")
        click.echo("  summon config set SUMMON_SCRIBE_ENABLED true")
        click.echo("  summon project up")


async def github_auth_cmd() -> None:
    """Interactive GitHub OAuth device flow authentication.

    Runs the device flow, prompting the user to visit GitHub and enter a code.
    Stores the resulting token for use by all sessions.
    """
    import aiohttp  # noqa: PLC0415

    from summon_claude.github_auth import GitHubAuthError, run_device_flow  # noqa: PLC0415

    def _print_device_code(user_code: str, verification_uri: str) -> None:
        safe_uri = re.sub(r"[^\x20-\x7e]", "", verification_uri)
        safe_code = re.sub(r"[^\x20-\x7e]", "", user_code)
        click.echo(f"Visit {safe_uri} and enter code: {safe_code}")
        click.echo("Verify the authorization page shows 'summon-claude' as the app name.")
        click.echo("Waiting for GitHub authorization...")

    try:
        result = await run_device_flow(on_code=_print_device_code)
        login = re.sub(r"[^a-zA-Z0-9-]", "", result.login) or "unknown"
        click.echo(f"Authenticated as {login}. Token saved to {result.token_path}.")
    except aiohttp.ClientError as e:
        click.echo(f"Network error during GitHub auth: {e}", err=True)
        sys.exit(1)
    except GitHubAuthError as e:
        click.echo(f"GitHub authentication failed: {e}", err=True)
        sys.exit(1)


def github_logout() -> None:
    """Remove the stored GitHub OAuth token."""
    from summon_claude.github_auth import remove_token  # noqa: PLC0415

    removed = remove_token()
    if removed:
        click.echo("GitHub token removed.")
    else:
        click.echo("No GitHub token stored.")


def _check_github_status(*, prefix: str = "", quiet: bool = False) -> bool | None:
    """Check GitHub OAuth token status.

    Returns True if valid, False if broken, None if not configured.
    """
    import aiohttp  # noqa: PLC0415

    from summon_claude.github_auth import (  # noqa: PLC0415
        GitHubAuthError,
        load_token,
        validate_token,
    )

    token = load_token()
    if not token:
        if not quiet:
            click.echo(f"{prefix}[INFO] GitHub: not configured (run `summon auth github login`)")
        return None

    try:
        result = asyncio.run(validate_token(token))
    except (OSError, aiohttp.ClientError, GitHubAuthError):
        if not quiet:
            click.echo(f"{prefix}[WARN] GitHub: token found (validation skipped — network error)")
        return True

    if result is None:
        if not quiet:
            click.echo(f"{prefix}[FAIL] GitHub: token invalid — run `summon auth github login`")
        return False

    if not quiet:
        login = re.sub(r"[^a-zA-Z0-9-]", "", result["login"]) or "unknown"
        scopes = re.sub(r"[^\x20-\x7e]", "", result["scopes"])
        click.echo(f"{prefix}[PASS] GitHub: authenticated as {login} (scopes: {scopes})")
    return True


def _check_google_status(
    *,
    prefix: str = "",
    quiet: bool = False,
) -> bool | None:
    """Check Google Workspace authentication status.

    Returns True if valid, False if credentials exist but are broken,
    or None if Google isn't configured (not an error, just absent).
    """
    try:
        from auth.credential_store import LocalDirectoryCredentialStore  # noqa: PLC0415
    except ImportError:
        if not quiet:
            click.echo(f"{prefix}[INFO] Google: not installed (install summon-claude[google])")
        return None

    creds_dir = get_google_credentials_dir()
    if not creds_dir.exists():
        if not quiet:
            click.echo(f"{prefix}[INFO] Google: not configured (run `summon auth google setup`)")
        return None

    store = LocalDirectoryCredentialStore(str(creds_dir))
    users = store.list_users()
    if not users:
        if not quiet:
            click.echo(f"{prefix}[INFO] Google: no credentials found")
        return None

    all_ok = True
    for user in users:
        cred = store.get_credential(user)
        if not cred:
            if not quiet:
                click.echo(f"{prefix}[FAIL] Google: invalid credential file ({user})")
            all_ok = False
            continue

        if cred.valid:
            status = "valid"
        elif cred.expired and cred.refresh_token:
            status = "expired (will refresh on next use)"
        else:
            if not quiet:
                click.echo(
                    f"{prefix}[FAIL] Google: invalid — re-run `summon auth google login` ({user})"
                )
            all_ok = False
            continue

        if not quiet:
            # Summarise granted access level per service.
            granted = set(cred.scopes or [])
            access = _describe_granted_scopes(granted)
            click.echo(f"{prefix}[PASS] Google: {status} ({user})")
            if access:
                click.echo(f"{prefix}  Access: {access}")

    return all_ok


def google_status() -> None:
    """Check Google Workspace authentication status (CLI entry point)."""
    _check_google_status()


async def _check_db(db_path: Path) -> tuple[int, str, int, int]:
    """Query DB for schema version, integrity, and row counts."""
    version = 0
    integrity = "unknown"
    sessions = 0
    audit = 0
    reg = SessionRegistry(db_path=db_path)
    async with reg:
        db = reg.db
        version = await get_schema_version(db)
        async with db.execute("PRAGMA integrity_check") as cursor:
            row = await cursor.fetchone()
            integrity = row[0] if row else "unknown"
        async with db.execute("SELECT COUNT(*) FROM sessions") as cur:
            row = await cur.fetchone()
            sessions = row[0] if row else 0
        async with db.execute("SELECT COUNT(*) FROM audit_log") as cur:
            row = await cur.fetchone()
            audit = row[0] if row else 0
    return version, integrity, sessions, audit


async def _check_features(db_path: Path) -> tuple[bool, bool, int]:
    """Query DB for workflow, hooks, and project count."""
    has_workflow = False
    has_hooks = False
    project_count = 0
    reg = SessionRegistry(db_path=db_path)
    async with reg:
        has_workflow = bool(await reg.get_workflow_defaults())
        raw_hooks = await reg.get_raw_hooks_json(project_id=None)
        has_hooks = raw_hooks is not None
        db = reg.db
        async with db.execute("SELECT COUNT(*) FROM projects") as cur:
            row = await cur.fetchone()
            project_count = row[0] if row else 0
    return has_workflow, has_hooks, project_count


def config_check(quiet: bool = False, config_path: str | None = None) -> bool:
    """Check config validity. Returns True if all checks pass."""
    from summon_claude.cli.preflight import check_claude_cli  # noqa: PLC0415

    config_file = get_config_file(config_path)
    all_pass = True

    # Claude CLI preflight
    cli_status = check_claude_cli()
    if cli_status.found:
        if not quiet:
            version_str = f" ({cli_status.version})" if cli_status.version else ""
            click.echo(f"  [PASS] Claude CLI found{version_str}")
    else:
        click.echo("  [FAIL] Claude CLI not found — install from https://claude.ai/code")
        all_pass = False

    # Parse the config file into a dict
    values = parse_env_file(config_file)

    # Required keys
    required_keys = [opt.env_key for opt in CONFIG_OPTIONS if opt.required]
    for key in required_keys:
        present = bool(values.get(key))
        if present:
            if not quiet:
                click.echo(f"  [PASS] {key} is set")
        else:
            click.echo(f"  [FAIL] {key} is missing")
            all_pass = False

    # Token format
    bot_token = values.get("SUMMON_SLACK_BOT_TOKEN", "")
    app_token = values.get("SUMMON_SLACK_APP_TOKEN", "")
    signing_secret = values.get("SUMMON_SLACK_SIGNING_SECRET", "")

    if bot_token:
        if bot_token.startswith("xoxb-"):
            if not quiet:
                click.echo("  [PASS] Bot token format is valid (xoxb-)")
        else:
            click.echo("  [FAIL] Bot token must start with 'xoxb-'")
            all_pass = False

    if app_token:
        if app_token.startswith("xapp-"):
            if not quiet:
                click.echo("  [PASS] App token format is valid (xapp-)")
        else:
            click.echo("  [FAIL] App token must start with 'xapp-'")
            all_pass = False

    if signing_secret:
        if re.match(r"^[0-9a-f]+$", signing_secret):
            if not quiet:
                click.echo("  [PASS] Signing secret format looks valid (hex)")
        else:
            click.echo("  [FAIL] Signing secret should be a hex string")
            all_pass = False

    # Pydantic validation — catches @field_validator rules (effort, quiet_hours,
    # google_services, channel_prefix, etc.) that individual key checks above miss.
    # Skip when required keys are missing — those failures are already reported above
    # and model_validate would just produce a duplicate cryptic error.
    required_missing = [key for key in required_keys if not bool(values.get(key))]
    if values and not required_missing:
        from summon_claude.config import SummonConfig  # noqa: PLC0415

        try:
            SummonConfig.model_validate(
                {
                    opt.field_name: values[opt.env_key]
                    for opt in CONFIG_OPTIONS
                    if opt.env_key in values
                }
            )
            if not quiet:
                click.echo("  [PASS] Config values pass validation")
        except Exception as e:
            click.echo(f"  [FAIL] Config validation: {e}")
            all_pass = False

    # DB writable
    db_path = get_data_dir() / "registry.db"
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.touch()
        if os.access(db_path, os.W_OK):
            if not quiet:
                click.echo(f"  [PASS] DB path is writable: {db_path}")
        else:
            click.echo(f"  [FAIL] DB path is not writable: {db_path}")
            all_pass = False
    except OSError as e:
        click.echo(f"  [FAIL] DB path error: {e}")
        all_pass = False

    # Schema version, integrity, and row counts
    try:
        version, integrity, sessions_count, audit_count = asyncio.run(_check_db(db_path))

        # Schema version
        if version == CURRENT_SCHEMA_VERSION:
            if not quiet:
                click.echo(f"  [PASS] Schema version {version} (current)")
        elif version > CURRENT_SCHEMA_VERSION:
            click.echo(
                f"  [WARN] Schema version {version} is ahead of this release"
                f" (expects {CURRENT_SCHEMA_VERSION}) — upgrade summon-claude"
            )
        else:
            # Should not happen — _connect() auto-migrates
            click.echo(f"  [FAIL] Schema version {version} (expected {CURRENT_SCHEMA_VERSION})")
            all_pass = False

        # Integrity
        if integrity == "ok":
            if not quiet:
                click.echo("  [PASS] Database integrity OK")
        else:
            click.echo(f"  [FAIL] Database integrity error: {integrity}")
            all_pass = False

        # Row counts (informational only)
        if not quiet:
            click.echo(f"  [INFO] Sessions: {sessions_count}, Audit log: {audit_count}")

    except Exception:
        logger.debug("Database validation error", exc_info=True)
        click.echo("  [FAIL] Database validation error")
        all_pass = False

    # Slack API reachable + scope verification (optional, best-effort)
    if bot_token.startswith("xoxb-"):
        try:
            from slack_sdk import WebClient  # noqa: PLC0415

            client = WebClient(token=bot_token)
            resp = client.auth_test()
            if resp["ok"]:
                if not quiet:
                    click.echo(f"  [PASS] Slack API reachable (team: {resp.get('team')})")
                # Check bot scopes via x-oauth-scopes response header.
                # Header name casing varies by HTTP library, so do a
                # case-insensitive lookup.
                headers_lower = {k.lower(): v for k, v in resp.headers.items()}
                granted_str = headers_lower.get("x-oauth-scopes", "")
                if granted_str:
                    granted = {s.strip() for s in granted_str.split(",") if s.strip()}
                    missing = _REQUIRED_SLACK_SCOPES - granted
                    if missing:
                        click.echo(
                            f"  [FAIL] Slack bot missing scopes: {', '.join(sorted(missing))}"
                        )
                        click.echo(
                            "  Update at: api.slack.com/apps → your app"
                            " → OAuth & Permissions → Scopes"
                        )
                        all_pass = False
                    elif not quiet:
                        click.echo(
                            f"  [PASS] Slack bot scopes:"
                            f" all {len(_REQUIRED_SLACK_SCOPES)} required scopes granted"
                        )
            else:
                click.echo(f"  [FAIL] Slack API auth.test failed: {resp.get('error')}")
                all_pass = False
        except Exception as e:
            click.echo(f"  [WARN] Slack API check skipped: {e}")

    # GitHub OAuth (optional, with connectivity check)
    github_result = _check_github_status(prefix="  ", quiet=quiet)
    if github_result is False:
        all_pass = False

    # Google Workspace (optional, only if credentials exist)
    google_result = _check_google_status(prefix="  ", quiet=quiet)
    if google_result is False:
        all_pass = False

    # Optional extras availability (informational)
    if not quiet:
        from summon_claude.config import is_extra_installed  # noqa: PLC0415

        extras = [
            ("workspace-mcp (Google)", find_workspace_mcp_bin().exists()),
            ("playwright (Slack browser)", is_extra_installed("playwright")),
        ]
        for label, installed in extras:
            status = "installed" if installed else "not installed"
            click.echo(f"  [INFO] {label}: {status}")

    # Event health check — only when daemon is running
    from summon_claude.daemon import is_daemon_running  # noqa: PLC0415

    if is_daemon_running():
        if not quiet:
            click.echo("  Event health: checking...", nl=False)
        try:
            from summon_claude.cli import daemon_client  # noqa: PLC0415

            result = asyncio.run(daemon_client.health_check())
            healthy = result.get("healthy")
            details = result.get("details", "")
            remediation_url = result.get("remediation_url")

            if healthy is True:
                if not quiet:
                    click.echo("\r  [PASS] Event health: OK")
            elif healthy is None:
                if not quiet:
                    click.echo(f"\r  [INFO] Event health: {details}")
            else:
                click.echo(f"\r  [FAIL] Event health: {details}")
                if remediation_url and not quiet:
                    click.echo(f"         Fix at: {remediation_url}")
                all_pass = False
        except Exception as e:
            click.echo(f"\r  [WARN] Event health check failed: {e}")
    elif not quiet:
        click.echo("  [INFO] Event health: skipped (daemon not running)")

    # Feature inventory — surface external flows so users know they exist
    if not quiet:
        click.echo()
        click.echo(click.style("Features:", bold=True))
        _print_feature_inventory(db_path, values)

    return all_pass


def _print_feature_inventory(db_path: Path, config_values: dict[str, str]) -> None:
    """Print discoverable status of external setup flows."""
    project_count: int | None = None

    try:
        has_workflow, has_hooks, project_count = asyncio.run(_check_features(db_path))

        # Projects — the primary workflow
        if project_count:
            click.echo(f"  [PASS] Projects: {project_count} registered")
        else:
            click.echo("  [INFO] Projects: none registered (summon project add)")

        if has_workflow:
            click.echo("  [PASS] Workflow instructions: configured")
        else:
            click.echo("  [INFO] Workflow instructions: not set (summon project workflow set)")

        if has_hooks:
            click.echo("  [PASS] Lifecycle hooks: configured")
        else:
            click.echo("  [INFO] Lifecycle hooks: not set (summon hooks set)")

    except Exception:
        logging.getLogger(__name__).debug("Feature inventory DB error", exc_info=True)

    # Hook bridge — check settings.json for summon-owned entries
    has_bridge = False
    try:
        from summon_claude.cli.hooks import read_settings  # noqa: PLC0415

        settings = read_settings()
        hooks_list = settings.get("hooks", [])
        has_bridge = any(
            "summon-pre-worktree" in str(h) or "summon-post-worktree" in str(h) for h in hooks_list
        )
        if has_bridge:
            click.echo("  [PASS] Hook bridge: installed")
        else:
            click.echo("  [INFO] Hook bridge: not installed (summon hooks install)")
    except Exception:
        logging.getLogger(__name__).debug("Hook bridge check error", exc_info=True)

    # Scribe → Google auth nudge
    scribe_on = config_values.get("SUMMON_SCRIBE_ENABLED", "").lower() in _BOOL_TRUE
    if scribe_on:
        try:
            google_dir = get_google_credentials_dir()
            has_creds = google_dir.exists() and any(google_dir.iterdir())
        except OSError:
            has_creds = False
        if not has_creds:
            click.echo(
                "  [INFO] Scribe enabled but Google not configured (summon auth google setup)"
            )

    # Getting started nudge (only when count is confirmed 0, not on DB failure)
    if project_count == 0:
        click.echo()
        click.echo(click.style("Getting started:", bold=True))
        click.echo("  summon project add <path>           Register a project directory")
        click.echo("  summon project workflow set          Set workflow instructions")
        if not has_bridge:
            click.echo("  summon hooks install                Install Claude Code hook bridge")
        click.echo("  summon project up                   Start PM agents for all projects")
