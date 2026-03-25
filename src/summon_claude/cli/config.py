"""CLI config subcommands: show, path, edit, set."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import click

from summon_claude.config import (
    _BOOL_FALSE,
    _BOOL_TRUE,
    CONFIG_OPTIONS,
    find_workspace_mcp_bin,
    get_config_file,
    get_data_dir,
    get_google_credentials_dir,
    get_workspace_config_path,
    google_mcp_env,
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


def _ensure_google_client_secrets() -> dict[str, str]:
    """Ensure Google OAuth client credentials are available.

    Checks env vars first, then prompts interactively.  Returns env
    dict with ``GOOGLE_OAUTH_CLIENT_ID`` and ``GOOGLE_OAUTH_CLIENT_SECRET``.
    """
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")

    if client_id and client_secret:
        click.echo("Using Google OAuth credentials from environment.")
        return {"GOOGLE_OAUTH_CLIENT_ID": client_id, "GOOGLE_OAUTH_CLIENT_SECRET": client_secret}

    # Check if we saved them previously in summon's config
    secrets_file = get_google_credentials_dir() / "client_env"
    if secrets_file.exists():
        for line in secrets_file.read_text().splitlines():
            if line.startswith("GOOGLE_OAUTH_CLIENT_ID="):
                client_id = line.split("=", 1)[1].strip()
            elif line.startswith("GOOGLE_OAUTH_CLIENT_SECRET="):
                client_secret = line.split("=", 1)[1].strip()
        if client_id and client_secret:
            return {
                "GOOGLE_OAUTH_CLIENT_ID": client_id,
                "GOOGLE_OAUTH_CLIENT_SECRET": client_secret,
            }

    # Interactive prompt
    click.echo("Google OAuth client credentials are required.")
    click.echo("Get these from https://console.cloud.google.com/apis/credentials")
    click.echo("  1. Create or select a project")
    click.echo("  2. Enable Gmail, Calendar, and Drive APIs")
    click.echo("  3. Create an OAuth 2.0 Client ID (Desktop app type)")
    click.echo("  4. Download the JSON file or copy the Client ID + Secret")
    click.echo()
    response = click.prompt(
        "Path to client_secret.json (or paste Client ID)", default="", show_default=False
    )
    if not response:
        click.echo("Client credentials are required.", err=True)
        sys.exit(1)

    import json  # noqa: PLC0415

    json_path = Path(response.strip()).expanduser()
    if json_path.suffix == ".json" or json_path.exists():
        # User provided a JSON file path
        if not json_path.exists():
            click.echo(f"File not found: {json_path}", err=True)
            sys.exit(1)
        try:
            data = json.loads(json_path.read_text())
            # Google's format nests under "installed" or "web"
            inner = data.get("installed") or data.get("web") or data
            client_id = inner["client_id"]
            client_secret = inner["client_secret"]
        except (json.JSONDecodeError, KeyError) as e:
            click.echo(f"Invalid client_secret.json: {e}", err=True)
            sys.exit(1)
        # Copy the JSON to our credentials dir for workspace-mcp
        dest = secrets_file.parent / "client_secret.json"
        secrets_file.parent.mkdir(parents=True, exist_ok=True)
        import shutil  # noqa: PLC0415

        shutil.copy2(str(json_path), str(dest))
        with contextlib.suppress(OSError):
            dest.chmod(0o600)
        click.echo(f"Copied {json_path.name} to {dest}")
    else:
        # User pasted a Client ID directly
        client_id = response.strip()
        client_secret = click.prompt("Google OAuth Client Secret", default="", show_default=False)
        if not client_secret:
            click.echo("Client Secret is required.", err=True)
            sys.exit(1)

    # Persist env-style for future runs
    secrets_file.parent.mkdir(parents=True, exist_ok=True)
    secrets_file.write_text(
        f"GOOGLE_OAUTH_CLIENT_ID={client_id}\nGOOGLE_OAUTH_CLIENT_SECRET={client_secret}\n"
    )
    with contextlib.suppress(OSError):
        secrets_file.chmod(0o600)
    click.echo(f"Saved credentials to {secrets_file}")

    return {"GOOGLE_OAUTH_CLIENT_ID": client_id, "GOOGLE_OAUTH_CLIENT_SECRET": client_secret}


def google_auth() -> None:
    """Interactive Google Workspace authentication.

    Prompts for OAuth client credentials if not configured, then runs the
    workspace-mcp OAuth flow which opens a browser for authorization.
    Credentials are stored under summon's XDG data directory.
    """
    bin_path = find_workspace_mcp_bin()
    if not bin_path.exists():
        click.echo(
            "Google Workspace support requires the 'google' extra: "
            "uv pip install summon-claude[google]",
            err=True,
        )
        sys.exit(1)

    # Ensure client credentials and build env for subprocess.
    # Set LOG_LEVEL=WARNING to suppress workspace-mcp's INFO output.
    client_env = _ensure_google_client_secrets()
    env = {**os.environ, **client_env, **google_mcp_env(), "LOG_LEVEL": "WARNING"}

    click.echo("Starting Google OAuth flow — a browser window will open for authorization.")

    # workspace-mcp's ``start_google_auth`` tool initiates the OAuth flow.
    try:
        subprocess.run(  # noqa: S603
            [str(bin_path), "--single-user", "--cli", "start_google_auth"],
            check=True,
            stdout=subprocess.DEVNULL,
            env=env,
        )
        click.echo("Google Workspace authenticated successfully.")
        click.echo(f"Credentials stored in {get_google_credentials_dir()}")
    except subprocess.CalledProcessError:
        click.echo("Google auth flow did not complete.", err=True)
        click.echo("Run `summon config google-status` to check auth state.")
        sys.exit(1)


def _check_github_pat(pat: str, *, quiet: bool = False) -> bool:
    """Check GitHub PAT by calling the /user endpoint.

    Returns True if valid, False if the token is rejected.
    """
    import json  # noqa: PLC0415
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    # Strip CRLF to prevent header injection from hand-edited config or env vars.
    pat = pat.replace("\r", "").replace("\n", "")
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read(65536))
            login = re.sub(r"[^a-zA-Z0-9\-]", "", data.get("login", "unknown")) or "unknown"
            if not quiet:
                click.echo(f"  [PASS] GitHub PAT: valid (user: {login})")
            return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            click.echo(
                "  [FAIL] GitHub PAT: invalid or expired (summon config set SUMMON_GITHUB_PAT)"
            )
            return False
        click.echo(f"  [WARN] GitHub PAT: API returned {e.code}")
        return True  # non-auth HTTP error, don't fail the check
    except Exception as e:
        click.echo(f"  [WARN] GitHub PAT: check skipped ({e})")
        return True  # network issue, not a token problem


def _check_google_status(
    *, prefix: str = "", quiet: bool = False, google_services: str = ""
) -> bool | None:
    """Check Google Workspace authentication status.

    Returns True if valid, False if credentials exist but are broken,
    or None if Google isn't configured (not an error, just absent).
    """
    try:
        from auth.credential_store import LocalDirectoryCredentialStore  # noqa: PLC0415
        from auth.google_auth import has_required_scopes  # noqa: PLC0415
        from auth.scopes import get_scopes_for_tools  # noqa: PLC0415
    except ImportError:
        if not quiet:
            click.echo(f"{prefix}Google: not installed (install summon-claude[google])")
        return None

    creds_dir = get_google_credentials_dir()
    if not creds_dir.exists():
        if not quiet:
            click.echo(f"{prefix}Google: not configured (run `summon config google-auth`)")
        return None

    store = LocalDirectoryCredentialStore(str(creds_dir))
    users = store.list_users()
    if not users:
        if not quiet:
            click.echo(f"{prefix}Google: no credentials found")
        return None

    # Read configured services once, outside the per-user loop.
    if google_services:
        services = [s.strip() for s in google_services.split(",") if s.strip()]
    else:
        services = ["gmail", "calendar", "drive"]
    required = set(get_scopes_for_tools(services))

    all_ok = True
    for user in users:
        cred = store.get_credential(user)
        if not cred:
            click.echo(f"{prefix}Google: invalid credential file ({user})")
            all_ok = False
            continue

        if cred.valid:
            status = "valid"
        elif cred.expired and cred.refresh_token:
            status = "expired (will refresh on next use)"
        else:
            click.echo(f"{prefix}Google: invalid — re-run `summon config google-auth` ({user})")
            all_ok = False
            continue

        # Scope validation against configured services.
        granted = set(cred.scopes or [])
        if granted and not has_required_scopes(granted, required):
            missing = required - granted
            click.echo(f"{prefix}Google: {status} but missing scopes ({user})")
            if not quiet:
                click.echo(f"{prefix}  Missing: {', '.join(sorted(missing)[:3])}...")
                click.echo(f"{prefix}  Re-run `summon config google-auth` to grant scopes")
            all_ok = False
        elif not quiet:
            click.echo(f"{prefix}Google: {status} ({user})")

    return all_ok


def google_status() -> None:
    """Check Google Workspace authentication status (CLI entry point)."""
    values = parse_env_file(get_config_file())
    _check_google_status(google_services=values.get("SUMMON_SCRIBE_GOOGLE_SERVICES", ""))


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

    # GitHub PAT (optional, with connectivity check)
    github_pat = values.get("SUMMON_GITHUB_PAT", "")
    if github_pat:
        gh_status = _check_github_pat(github_pat, quiet=quiet)
        if gh_status is False:
            all_pass = False
    elif not quiet:
        click.echo(
            "  [INFO] GitHub PAT: not set — sessions won't have GitHub tools"
            " (summon config set SUMMON_GITHUB_PAT <token>)"
        )

    # Google Workspace (optional, only if credentials exist)
    google_result = _check_google_status(
        prefix="  ", quiet=quiet, google_services=values.get("SUMMON_SCRIBE_GOOGLE_SERVICES", "")
    )
    if google_result is not None:
        # Credentials exist — report pass/fail
        if google_result:
            if not quiet:
                click.echo("  [PASS] Google Workspace credentials valid")
        else:
            click.echo("  [FAIL] Google Workspace credentials have issues")
            all_pass = False
    elif not quiet:
        click.echo("  [INFO] Google Workspace: not configured (summon config google-auth)")

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
                "  [INFO] Scribe enabled but Google not configured (summon config google-auth)"
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


# ---------------------------------------------------------------------------
# External Slack workspace commands (C9)
# ---------------------------------------------------------------------------


def _pick_channels(channels: list[dict[str, str]] | None) -> str:
    """Interactive channel picker. Returns comma-separated channel IDs.

    Reusable by both ``slack-auth`` and ``slack-channels`` commands.
    Includes an empty-selection guard: if the user confirms with nothing
    selected (likely pressed Enter instead of Space), offers a retry.
    """
    if not channels:
        click.echo()
        click.echo("Could not detect channels from sidebar.")
        click.echo("To monitor specific channels, set their IDs in config:")
        click.echo("  summon config set SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS C01ABC,C02DEF")
        return ""

    click.echo()
    n = len(channels)
    click.echo(f"Found {n} sidebar channels (muted excluded).")
    click.echo("DMs and @mentions are always captured.")
    click.echo("Select channels for monitoring all messages (all messages, not just mentions).")

    if not sys.stdin.isatty():
        return _pick_channels_noninteractive(channels)

    import pick  # noqa: PLC0415

    # Build grouped display with non-selectable section headers
    display_options: list[str] = []
    channel_indices: list[int] = []
    current_section = ""
    for ch_idx, ch in enumerate(channels):
        section = ch.get("section", "Channels")
        if section != current_section:
            current_section = section
            display_options.append(f"── {section} ──")
            channel_indices.append(-1)
        display_options.append(f"  #{ch['name']}")
        channel_indices.append(ch_idx)

    pick_options = [pick.Option(opt, enabled=not opt.startswith("──")) for opt in display_options]
    title = (
        "Select channels to monitor\n"
        "  SPACE = toggle    ENTER = confirm\n"
        "DMs and @mentions are always captured "
        "— this is for monitoring all messages."
    )

    try:
        while True:
            selected_raw = pick.pick(
                pick_options,
                title,
                multiselect=True,
                min_selection_count=0,
                indicator=">",
            )
            selected_ch_indices = [
                channel_indices[int(s[1])]  # type: ignore[index]
                for s in selected_raw
                if channel_indices[int(s[1])] >= 0  # type: ignore[index]
            ]
            if selected_ch_indices:
                selected = [channels[i] for i in selected_ch_indices]
                result = ",".join(ch["id"] for ch in selected)
                names = ", ".join(f"#{ch['name']}" for ch in selected)
                click.echo(f"Selected: {names}")
                return result

            # Empty selection guard — user likely pressed Enter
            # instead of Space
            if not click.confirm(
                "No channels selected (use SPACE to toggle). Try again?",
                default=True,
            ):
                return ""
    except (KeyboardInterrupt, EOFError):
        click.echo("Skipped channel selection.")
        return ""


def _pick_channels_noninteractive(channels: list[dict[str, str]]) -> str:
    """Non-interactive fallback: numbered list with comma input."""
    for i, ch in enumerate(channels, 1):
        click.echo(f"  {i}) #{ch['name']}  ({ch['id']})")
    click.echo()
    selection = click.prompt(
        "Enter channel numbers (comma-separated, or Enter to skip)",
        default="",
    )
    if not selection.strip():
        return ""
    indices: list[int] = []
    for token in selection.split(","):
        stripped = token.strip()
        if stripped.isdigit():
            idx = int(stripped) - 1
            if 0 <= idx < len(channels):
                indices.append(idx)
    if not indices:
        return ""
    selected = [channels[i] for i in indices]
    result = ",".join(ch["id"] for ch in selected)
    names = ", ".join(f"#{ch['name']}" for ch in selected)
    click.echo(f"Selected: {names}")
    return result


def _save_monitored_channels(monitored_channels: str) -> None:
    """Save monitored channel IDs to the config file."""
    if not monitored_channels:
        return

    config_file = get_config_file()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    lines = config_file.read_text().splitlines() if config_file.exists() else []
    key = "SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS"
    new_line = f"{key}={monitored_channels}"
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = new_line
            updated = True
            break
    if not updated:
        lines.append(new_line)
    config_file.write_text("\n".join(lines) + "\n")
    click.echo(f"Monitored channels saved to {config_file}")


def _normalize_workspace(workspace: str) -> str:
    """Normalize a workspace name or URL to a full Slack URL.

    Accepts:
      - Full URL: ``https://myteam.slack.com`` → as-is
      - Bare name: ``myteam`` → ``https://myteam.slack.com``
      - Enterprise: ``acme.enterprise`` → ``https://acme.enterprise.slack.com``

    Raises ``SystemExit`` for explicit ``http://`` URLs (insecure).
    """
    # Reject explicit http:// — must use https
    if workspace.startswith("http://"):
        click.echo("Slack requires HTTPS. Use https:// or just the workspace name.", err=True)
        sys.exit(1)

    # Already a full URL
    if workspace.startswith("https://"):
        return workspace.rstrip("/")

    # Bare name or domain — strip trailing slashes
    workspace = workspace.rstrip("/")

    # Already has .slack.com
    if workspace.endswith(".slack.com"):
        return f"https://{workspace}"

    # Bare workspace name — append .slack.com
    return f"https://{workspace}.slack.com"


def _check_existing_slack_auth() -> dict[str, str] | None:
    """Check if valid Slack browser auth already exists.

    Reads the saved Playwright state file and checks the ``d`` cookie (Slack's
    primary auth cookie). Returns a dict with status info if credentials exist
    and appear valid, or ``None`` if missing/expired.
    """
    import datetime  # noqa: PLC0415
    import time  # noqa: PLC0415

    workspace_config_path = get_workspace_config_path()
    if not workspace_config_path.exists():
        return None

    workspace = json.loads(workspace_config_path.read_text())
    state_path = Path(workspace.get("auth_state_path", ""))
    if not state_path.is_file():
        return None

    # Check the primary auth cookie ("d") for expiry.
    # The d cookie is Slack's long-lived session cookie (~1 year).
    d_cookie = _find_slack_d_cookie(state_path)
    if not d_cookie:
        return None

    expires = d_cookie.get("expires", -1)
    if isinstance(expires, (int, float)) and 0 < expires < time.time():
        return None  # Primary auth cookie expired

    # Build status info
    mtime = state_path.stat().st_mtime
    saved_dt = datetime.datetime.fromtimestamp(mtime, tz=datetime.UTC)
    age = datetime.datetime.now(tz=datetime.UTC) - saved_dt
    if age.days > 0:
        age_str = f"{age.days}d ago"
    else:
        hours = age.seconds // 3600
        age_str = f"{hours}h ago" if hours > 0 else "just now"

    return {
        "saved": saved_dt.strftime("%Y-%m-%d %H:%M UTC"),
        "age": age_str,
        "user_id": workspace.get("user_id", ""),
        "url": workspace.get("url", ""),
    }


def _find_slack_d_cookie(state_path: Path) -> dict | None:
    """Find Slack's ``d`` auth cookie in a Playwright state file."""
    try:
        state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    cookies = state.get("cookies", [])
    return next((c for c in cookies if c.get("name") == "d"), None)


def slack_auth(workspace: str) -> None:
    """Interactive Slack workspace authentication via Playwright.

    Opens a real browser window for the user to log in. Saves auth state
    to ``get_data_dir() / browser_auth/``.

    Accepts a workspace name (``myteam``), enterprise name (``acme.enterprise``),
    or full URL (``https://myteam.slack.com``).
    """
    workspace_url = _normalize_workspace(workspace)
    parsed = urlparse(workspace_url)
    if not (parsed.netloc.endswith(".slack.com") or parsed.netloc == "slack.com"):
        click.echo(
            f"Cannot resolve workspace {workspace!r} to a Slack URL. "
            "Expected a name like 'myteam' or URL like https://myteam.slack.com",
            err=True,
        )
        sys.exit(1)

    try:
        from summon_claude.slack_browser import interactive_slack_auth  # noqa: PLC0415
    except ImportError:
        click.echo(
            "External Slack support requires the 'slack-browser' extra: "
            "uv pip install summon-claude[slack-browser]",
            err=True,
        )
        sys.exit(1)

    # Check for existing valid credentials before launching browser
    existing = _check_existing_slack_auth()
    if existing:
        click.echo(f"Slack auth already configured for {existing['url']}")
        click.echo(f"  Saved: {existing['saved']} ({existing['age']})")
        if existing["user_id"]:
            click.echo(f"  User:  {existing['user_id']}")
        if not click.confirm("Re-authenticate?", default=False):
            return

    browser_type = os.environ.get("SUMMON_SCRIBE_SLACK_BROWSER", "chrome")

    click.echo(f"Opening {browser_type} browser for Slack login at {workspace_url}")
    click.echo("Complete the login in the browser window.")
    click.echo("The browser will close automatically after detecting your session.")
    click.echo("WARNING: Auth state contains session cookies — treat stored files as secrets.")

    result = asyncio.run(interactive_slack_auth(workspace_url, browser_type))

    click.echo(f"Slack auth saved to {result.state_file}")
    click.echo(f"  User ID:  {result.user_id or 'not detected'}")
    click.echo(f"  Team ID:  {result.team_id or 'not detected'}")
    click.echo(f"  Channels: {len(result.channels) if result.channels else 0} found")

    # User ID
    if result.user_id:
        click.echo(f"Auto-detected user ID: {result.user_id}")
        user_id = result.user_id
    else:
        click.echo()
        click.echo("Could not auto-detect user ID.")
        click.echo("To enable @mention detection, enter your Slack user ID for this workspace.")
        click.echo("Find it: click your profile picture → Profile → ⋮ → Copy member ID")
        user_id = click.prompt("External workspace user ID (or press Enter to skip)", default="")

    # Interactive channel selection
    monitored_channels = _pick_channels(result.channels)

    # Save workspace metadata
    workspace_config: dict[str, str] = {
        "url": workspace_url,
        "auth_state_path": str(result.state_file),
        "browser_type": browser_type,
    }
    if user_id:
        workspace_config["user_id"] = user_id
    if result.team_id:
        workspace_config["team_id"] = result.team_id
    if result.channels:
        workspace_config["channels"] = result.channels  # type: ignore[assignment]
    config_path = get_workspace_config_path()
    config_path.write_text(json.dumps(workspace_config, indent=2))
    config_path.chmod(0o600)

    _save_monitored_channels(monitored_channels)

    click.echo(f"Workspace config saved to {config_path}")
    if not user_id:
        click.echo("Note: @mention detection disabled (no user ID). Re-run slack-auth to add it.")


def slack_status() -> None:
    """Show external Slack workspace configuration and auth status."""
    config_path = get_workspace_config_path()
    if not config_path.exists():
        click.echo("No external Slack workspace configured.")
        click.echo("Run: summon config slack-auth <workspace-url>")
        return

    workspace = json.loads(config_path.read_text())
    click.echo(f"Workspace URL: {workspace.get('url', 'N/A')}")
    user_id = workspace.get("user_id", "")
    click.echo(f"User ID: {user_id or 'not set (re-run slack-auth to add)'}")

    state_path = Path(workspace.get("auth_state_path", ""))
    if state_path.exists():
        import datetime  # noqa: PLC0415

        mtime = datetime.datetime.fromtimestamp(state_path.stat().st_mtime, tz=datetime.UTC)
        click.echo(f"Auth state: {state_path} (saved {mtime.isoformat()})")
    else:
        click.echo("Auth state: MISSING (re-run slack-auth)")

    channels = os.environ.get("SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS", "")
    if channels:
        click.echo(f"Monitored channels: {channels}")
    else:
        click.echo("Monitored channels: none (DMs and @mentions always captured)")
    click.echo()
    click.echo("How to find IDs:")
    click.echo("  User ID: click profile picture > Profile > ... > Copy member ID")
    click.echo("  Channel ID: right-click channel > View channel details > ID at bottom")
    click.echo("  Set channels: summon config set SUMMON_SCRIBE_SLACK_MONITORED_CHANNELS C01,C02")


def slack_remove() -> None:
    """Remove external Slack workspace auth state."""
    config_path = get_workspace_config_path()
    if not config_path.exists():
        click.echo("No external Slack workspace configured.")
        return

    if not click.confirm("Remove Slack auth state? This cannot be undone."):
        return

    workspace = json.loads(config_path.read_text())
    state_path = Path(workspace.get("auth_state_path", ""))

    # [SEC] Validate path is within expected directory before unlinking
    expected_dir = get_data_dir() / "browser_auth"
    if state_path.name and (not state_path.resolve().is_relative_to(expected_dir.resolve())):
        click.echo(
            f"Auth state path {state_path} is outside expected directory — skipping removal.",
            err=True,
        )
    else:
        with contextlib.suppress(FileNotFoundError):
            state_path.unlink()

    with contextlib.suppress(FileNotFoundError):
        config_path.unlink()

    click.echo("Slack auth state removed.")


def slack_channels(*, refresh: bool = False) -> None:
    """Update monitored channel selection.

    Uses cached channel list from workspace config by default.
    With ``--refresh``, re-fetches from Slack via Playwright.
    """
    config_path = get_workspace_config_path()
    if not config_path.exists():
        click.echo("No external Slack workspace configured.")
        click.echo("Run: summon config slack-auth <workspace>")
        return

    workspace = json.loads(config_path.read_text())
    workspace_url = workspace.get("url", "")
    cached_channels = workspace.get("channels")

    channels: list[dict[str, str]] | None = None

    if not refresh and cached_channels:
        click.echo(f"Using cached channel list ({len(cached_channels)} channels).")
        click.echo("Run with --refresh to re-fetch from Slack.")
        channels = cached_channels
    else:
        channels = _fetch_channels_via_playwright(workspace)
        if channels:
            # Update cache
            workspace["channels"] = channels
            config_path.write_text(json.dumps(workspace, indent=2))
            config_path.chmod(0o600)

    if not channels:
        click.echo("Could not load channels — auth state may be expired.")
        click.echo(f"Re-run: summon config slack-auth {workspace_url}")
        return

    monitored = _pick_channels(channels)
    _save_monitored_channels(monitored)


def _fetch_channels_via_playwright(
    workspace: dict,
) -> list[dict[str, str]] | None:
    """Load channels from Slack via headless Playwright."""
    workspace_url = workspace.get("url", "")
    state_path = Path(workspace.get("auth_state_path", ""))
    browser_type = workspace.get("browser_type", "chrome")

    if not state_path.is_file():
        click.echo("Auth state expired or missing.")
        click.echo(f"Re-run: summon config slack-auth {workspace_url}")
        return None

    try:
        from summon_claude.slack_browser import (  # noqa: PLC0415
            _extract_channels,
            _launch_browser,
        )
    except ImportError:
        click.echo(
            "External Slack support requires the 'slack-browser' extra: "
            "uv pip install summon-claude[slack-browser]",
            err=True,
        )
        return None

    click.echo(f"Loading channels from {workspace_url}...")

    async def _load() -> list[dict[str, str]]:
        from playwright.async_api import async_playwright  # noqa: PLC0415

        async with async_playwright() as p:
            browser = await _launch_browser(p, browser_type, headless=True)
            context = await browser.new_context(
                storage_state=str(state_path),
            )
            page = await context.new_page()
            await page.goto(workspace_url, wait_until="domcontentloaded")

            try:
                await page.wait_for_url(
                    "**/client/**",
                    timeout=30000,
                    wait_until="commit",
                )
            except Exception:
                await browser.close()
                return []

            with contextlib.suppress(Exception):
                await page.wait_for_selector(
                    '[data-qa^="channel_sidebar_name_"]',
                    timeout=5000,
                )

            result = await _extract_channels(page, workspace_url)
            await browser.close()
            return result

    result = asyncio.run(_load())
    return result or None
