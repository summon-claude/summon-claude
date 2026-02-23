"""CLI entry point for summon-claude."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
from datetime import datetime

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )
    # Silence noisy libraries unless verbose
    if not verbose:
        logging.getLogger("slack_bolt").setLevel(logging.ERROR)
        logging.getLogger("slack_sdk").setLevel(logging.ERROR)
        logging.getLogger("asyncio").setLevel(logging.ERROR)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="summon",
        description="Bridge Claude Code sessions to Slack channels",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # start
    start_parser = subparsers.add_parser("start", help="Start a new summon session")
    start_parser.add_argument(
        "--cwd",
        default=None,
        help="Working directory for Claude (default: current directory)",
    )
    start_parser.add_argument(
        "--resume",
        metavar="SESSION_ID",
        default=None,
        help="Resume an existing Claude Code session by ID",
    )
    start_parser.add_argument(
        "--name",
        default=None,
        help="Session name (used for Slack channel naming)",
    )
    start_parser.add_argument(
        "--model",
        default=None,
        help="Model override (default: from config)",
    )

    # status
    status_parser = subparsers.add_parser("status", help="Show session status")
    status_parser.add_argument(
        "session_id",
        nargs="?",
        default=None,
        help="Session ID for detailed view (omit for all active sessions)",
    )

    # stop
    stop_parser = subparsers.add_parser("stop", help="Stop a running session")
    stop_parser.add_argument("session_id", help="Session ID to stop")

    # sessions
    subparsers.add_parser("sessions", help="List recent sessions (all statuses)")

    # cleanup
    subparsers.add_parser("cleanup", help="Mark sessions with dead processes as errored")

    # init
    subparsers.add_parser("init", help="Interactive setup wizard for summon-claude configuration")

    # config
    config_parser = subparsers.add_parser("config", help="Manage summon-claude configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)

    config_subparsers.add_parser("show", help="Show current configuration (tokens masked)")
    config_subparsers.add_parser("path", help="Print the config file path")
    config_subparsers.add_parser("edit", help="Open config file in $EDITOR")

    config_set_parser = config_subparsers.add_parser("set", help="Set a configuration value")
    config_set_parser.add_argument("key", help="Configuration key (e.g. SUMMON_SLACK_BOT_TOKEN)")
    config_set_parser.add_argument("value", help="Value to set")

    return parser


def cmd_start(args: argparse.Namespace) -> None:
    """Launch a new summon session."""
    from .config import SummonConfig
    from .session import SessionOptions, SummonSession

    try:
        config = SummonConfig()
        config.validate()
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    cwd = os.path.abspath(args.cwd) if args.cwd else os.getcwd()

    session = SummonSession(
        config=config,
        options=SessionOptions(
            cwd=cwd,
            name=args.name,
            model=args.model,
            resume=args.resume,
        ),
    )

    try:
        asyncio.run(session.start())
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as e:
        logger.exception("Session error: %s", e)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    """Show session status."""
    asyncio.run(_async_status(args.session_id))


async def _async_status(session_id: str | None) -> None:
    from .registry import SessionRegistry

    async with SessionRegistry() as registry:
        if session_id:
            session = await registry.get_session(session_id)
            if not session:
                print(f"Session not found: {session_id}")
                return
            _print_session_detail(session)
        else:
            sessions = await registry.list_active()
            if not sessions:
                print("No active sessions.")
                return
            _print_session_table(sessions)


def cmd_stop(args: argparse.Namespace) -> None:
    """Send SIGTERM to a running session process."""
    asyncio.run(_async_stop(args.session_id))


async def _async_stop(session_id: str) -> None:
    from .registry import SessionRegistry

    async with SessionRegistry() as registry:
        session = await registry.get_session(session_id)
        if not session:
            print(f"Session not found: {session_id}")
            return
        if session["status"] not in ("pending_auth", "active"):
            print(f"Session {session_id} is not active (status: {session['status']})")
            return

        pid = session["pid"]

        # Verify the PID belongs to the current user before signaling
        if not _pid_owned_by_current_user(pid):
            print(f"Process {pid} is not owned by the current user — refusing to signal")
            return

        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to session {session_id} (pid {pid})")
            await registry.log_event(
                "session_stopped",
                session_id=session_id,
                details={"pid": pid, "stopped_by": "cli"},
            )
        except ProcessLookupError:
            print(f"Process {pid} not found — session may have already ended")
            await registry.update_status(
                session_id, "errored", error_message="Process not found at stop time"
            )
        except PermissionError:
            print(f"Permission denied to send signal to pid {pid}")


def cmd_sessions(args: argparse.Namespace) -> None:
    """List recent sessions."""
    asyncio.run(_async_sessions())


async def _async_sessions() -> None:
    from .registry import SessionRegistry

    async with SessionRegistry() as registry:
        sessions = await registry.list_all(limit=50)
        if not sessions:
            print("No sessions found.")
            return
        _print_session_table(sessions)


def cmd_cleanup(args: argparse.Namespace) -> None:
    """Mark sessions with dead processes as errored."""
    asyncio.run(_async_cleanup())


async def _async_cleanup() -> None:
    from .registry import SessionRegistry

    async with SessionRegistry() as registry:
        cleaned = await registry.cleanup_stale()
        print(f"Cleaned up {cleaned} stale session(s).")


def cmd_init(args: argparse.Namespace) -> None:
    """Interactive setup wizard for summon-claude configuration."""
    from .config import get_config_dir, get_config_file

    print("Setting up summon-claude configuration...")
    print()

    def prompt(label: str, required: bool = True) -> str:
        while True:
            value = input(f"  {label}: ").strip()
            if value or not required:
                return value
            print("  This field is required.")

    bot_token = prompt("Slack Bot Token (xoxb-...)")
    while not bot_token.startswith("xoxb-"):
        print("  Error: Bot token must start with 'xoxb-'")
        bot_token = prompt("Slack Bot Token (xoxb-...)")

    app_token = prompt("Slack App Token (xapp-...)")
    while not app_token.startswith("xapp-"):
        print("  Error: App token must start with 'xapp-'")
        app_token = prompt("Slack App Token (xapp-...)")

    signing_secret = prompt("Slack Signing Secret")
    allowed_users = prompt("Allowed User IDs (comma-separated)")

    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = get_config_file()

    lines = [
        f"SUMMON_SLACK_BOT_TOKEN={bot_token}",
        f"SUMMON_SLACK_APP_TOKEN={app_token}",
        f"SUMMON_SLACK_SIGNING_SECRET={signing_secret}",
        f"SUMMON_ALLOWED_USER_IDS={allowed_users}",
    ]
    config_file.write_text("\n".join(lines) + "\n")
    # Restrict config file to owner-only access (0600)
    with contextlib.suppress(OSError):
        config_file.chmod(0o600)

    print()
    print(f"Configuration saved to {config_file}")


def cmd_config(args: argparse.Namespace) -> None:
    """Manage summon-claude configuration."""
    from .cli_config import config_edit, config_path, config_set, config_show

    config_command = args.config_command
    if config_command == "show":
        config_show()
    elif config_command == "path":
        config_path()
    elif config_command == "edit":
        config_edit()
    elif config_command == "set":
        config_set(args.key, args.value)


def _print_session_table(sessions: list[dict]) -> None:
    """Print a compact table of sessions."""
    if not sessions:
        return

    headers = ["STATUS", "NAME", "CHANNEL", "CWD", "TURNS", "COST"]
    rows: list[list[str]] = []
    for s in sessions:
        rows.append(
            [
                s.get("status", "?"),
                s.get("session_name") or "-",
                s.get("slack_channel_name") or "-",
                _truncate(s.get("cwd", ""), 30),
                str(s.get("total_turns", 0)),
                f"${s.get('total_cost_usd', 0.0) or 0.0:.4f}",
            ]
        )

    col_widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in col_widths))
    for row in rows:
        print(fmt.format(*row))


def _print_session_detail(session: dict) -> None:
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
        ("Started", _format_ts(session.get("started_at"))),
        ("Authenticated", _format_ts(session.get("authenticated_at"))),
        ("Last Activity", _format_ts(session.get("last_activity_at"))),
        ("Ended", _format_ts(session.get("ended_at"))),
        ("Turns", str(session.get("total_turns", 0))),
        ("Total Cost", f"${session.get('total_cost_usd', 0.0) or 0.0:.4f}"),
    ]
    if session.get("error_message"):
        fields.append(("Error", session["error_message"]))

    max_key = max(len(k) for k, _ in fields)
    for key, val in fields:
        print(f"  {key.ljust(max_key)} : {val}")


def _format_ts(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else "..." + s[-(n - 3) :]


def _pid_uid_from_proc(pid: int) -> int | None:
    """Read the real UID of *pid* from /proc (Linux only)."""
    import pathlib

    stat_file = pathlib.Path(f"/proc/{pid}/status")
    if not stat_file.exists():
        return None
    for line in stat_file.read_text().splitlines():
        if line.startswith("Uid:"):
            return int(line.split()[1])
    return None


def _pid_owned_by_current_user(pid: int) -> bool:
    """Return True if the process with the given PID is owned by the current user."""
    try:
        import psutil  # type: ignore[import]  # optional dependency

        proc = psutil.Process(pid)
        return proc.uids().real == os.getuid()
    except Exception:
        pass

    # psutil not available or process gone; fall back to /proc on Linux
    try:
        uid = _pid_uid_from_proc(pid)
        if uid is not None:
            return uid == os.getuid()
    except Exception:
        pass
    # Cannot determine owner; deny for safety
    return False


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _setup_logging(args.verbose)

    command_map = {
        "start": cmd_start,
        "status": cmd_status,
        "stop": cmd_stop,
        "sessions": cmd_sessions,
        "cleanup": cmd_cleanup,
        "init": cmd_init,
        "config": cmd_config,
    }
    command_map[args.command](args)
