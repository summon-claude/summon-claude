"""Doctor command business logic for summon-claude CLI."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import click

from summon_claude.diagnostics import (
    DIAGNOSTIC_REGISTRY,
    CheckResult,
    redactor,
)

if TYPE_CHECKING:
    from summon_claude.config import SummonConfig


# Status → (label, color) for click.style
_STATUS_STYLE: dict[str, tuple[str, str | None]] = {
    "pass": ("PASS", "green"),
    "fail": ("FAIL", "red"),
    "warn": ("WARN", "yellow"),
    "info": ("INFO", "blue"),
    "skip": ("SKIP", None),  # dim handled separately
}


def _format_status(status: str, *, color: bool = True) -> str:
    label, fg = _STATUS_STYLE.get(status, (status.upper(), None))
    if not color:
        return f"[{label}]"
    if status == "skip":
        return click.style(f"[{label}]", dim=True)
    return click.style(f"[{label}]", fg=fg, bold=True)


def _redact_result(r: CheckResult) -> CheckResult:
    """Return a new CheckResult with all fields redacted."""
    redacted_logs = {
        redactor.redact(k): [redactor.redact(ln) for ln in v] for k, v in r.collected_logs.items()
    }
    return dataclasses.replace(
        r,
        message=redactor.redact(r.message),
        details=[redactor.redact(d) for d in r.details],
        suggestion=redactor.redact(r.suggestion) if r.suggestion else None,
        collected_logs=redacted_logs,
    )


async def async_doctor(
    ctx: click.Context,
    export_path: str | None,
    submit: bool,
) -> None:
    """Run all diagnostic checks and format/export results."""
    use_color = ctx.color is not False
    verbose = ctx.obj.get("verbose", False) if ctx.obj else False
    no_interactive = ctx.obj.get("no_interactive", False) if ctx.obj else False
    config_path_override = ctx.obj.get("config_path") if ctx.obj else None

    results: list[CheckResult] = []

    # Load config — failure produces a synthetic result
    config = _load_config(config_path_override, results)

    # Run all checks in parallel
    await _run_checks(results, config)

    # Print interactive output
    _print_results(results, use_color, verbose)

    # Export
    if export_path:
        _write_export(export_path, results)
        click.echo(f"Exported to {export_path}")

    # Submit
    if submit:
        await _handle_submit(results, no_interactive)


def _format_config_error(exc: Exception, redact_fn: Callable[[str], str]) -> str:
    """Format a config loading error, avoiding Pydantic's verbose input_value dump."""
    from pydantic import ValidationError  # noqa: PLC0415

    if isinstance(exc, ValidationError):
        missing = [err["loc"][0] for err in exc.errors() if err["type"] == "missing"]
        if missing:
            return f"{len(missing)} required field(s) missing: {', '.join(str(f) for f in missing)}"
        return f"{exc.error_count()} validation error(s)"
    return redact_fn(str(exc))


def _load_config(
    config_path: str | None,
    results: list[CheckResult],
) -> SummonConfig | None:
    """Try loading SummonConfig, append synthetic fail on error."""
    from summon_claude.config import SummonConfig as _Config  # noqa: PLC0415
    from summon_claude.slack.client import (  # noqa: PLC0415
        redact_secrets as _redact_err,
    )

    try:
        return _Config.from_file(config_path)
    except Exception as e:
        safe_err = _format_config_error(e, _redact_err)
        # Synthetic subsystem — not in KNOWN_SUBSYSTEMS/DIAGNOSTIC_REGISTRY
        # because it's produced inline, not by a registered check.
        results.append(
            CheckResult(
                status="fail",
                subsystem="config",
                message=(
                    f"Config failed to load: {safe_err}. Run `summon config check` for details."
                ),
            )
        )
        return None


async def _run_checks(
    results: list[CheckResult],
    config: SummonConfig | None,
) -> None:
    """Run all diagnostic checks in parallel."""
    bug_url = "https://github.com/summon-claude/summon-claude/issues"

    async def _safe_run(name: str, check: object) -> CheckResult:
        try:
            return await check.run(config)  # type: ignore[union-attr]
        except Exception as e:
            return CheckResult(
                status="fail",
                subsystem=name,
                message=f"Check crashed: {e}",
                suggestion=f"File a bug report at {bug_url}",
            )

    outcomes = await asyncio.gather(
        *(_safe_run(name, check) for name, check in DIAGNOSTIC_REGISTRY.items())
    )
    results.extend(outcomes)


def _print_results(
    results: list[CheckResult],
    use_color: bool,
    verbose: bool,
) -> None:
    """Print interactive check results."""
    for result in results:
        # Always redact the summary line; full redaction (incl. collected_logs) only when verbose
        status_str = _format_status(result.status, color=use_color)
        subsystem = result.subsystem.replace("_", " ").title()
        click.echo(f"{status_str} {subsystem}: {redactor.redact(result.message)}")

        if verbose:
            redacted = _redact_result(result)
            for detail in redacted.details:
                click.echo(f"    {detail}")
            if redacted.suggestion:
                click.echo(f"    Suggestion: {redacted.suggestion}")
            for log_name, log_lines in redacted.collected_logs.items():
                shown = log_lines[-20:]
                click.echo(f"    --- {log_name} (last {len(shown)} lines) ---")
                for log_line in shown:
                    click.echo(f"    {log_line}")

    # Summary
    counts = {s: sum(1 for r in results if r.status == s) for s in _STATUS_STYLE}
    parts = []
    for key, label in [
        ("pass", "passed"),
        ("fail", "failed"),
        ("warn", "warnings"),
        ("info", "info"),
        ("skip", "skipped"),
    ]:
        n = counts.get(key, 0)
        if n:
            parts.append(f"{n} {label}")
    click.echo()
    click.echo(f"{len(results)} checks: {', '.join(parts)}")


async def _handle_submit(
    results: list[CheckResult],
    no_interactive: bool,
) -> None:
    """Handle --submit flag logic."""
    if no_interactive:
        click.echo(
            "Error: --no-interactive is set; cannot confirm "
            "submission. Remove --no-interactive to submit.",
            err=True,
        )
        return

    gh = shutil.which("gh")
    if not gh:
        click.echo(
            "Error: gh CLI not found. Install from https://cli.github.com/",
            err=True,
        )
        return

    body = _build_submit_body(results)
    click.echo()
    click.echo("=== Redacted report to be submitted ===")
    click.echo(body)
    click.echo("=" * 40)

    if not click.confirm("Submit the above to GitHub?"):
        click.echo("Submission cancelled.")
        return

    await _submit_to_github(gh, body)


def _write_export(path: str, results: list[CheckResult]) -> None:
    """Write redacted results as JSON to path."""
    import importlib.metadata  # noqa: PLC0415

    try:
        summon_version = importlib.metadata.version("summon-claude")
    except importlib.metadata.PackageNotFoundError:
        summon_version = "unknown"

    redacted = [_redact_result(r) for r in results]
    payload = {
        "version": "1.0",
        "timestamp": datetime.now(UTC).isoformat(),
        "summon_version": summon_version,
        "checks": [
            {
                "status": r.status,
                "subsystem": r.subsystem,
                "message": r.message,
                "details": r.details,
                "suggestion": r.suggestion,
                "collected_logs": r.collected_logs,
            }
            for r in redacted
        ],
    }
    with Path(path).open("w") as f:
        json.dump(payload, f, indent=2)


def _build_submit_body(results: list[CheckResult]) -> str:
    """Build a redacted markdown issue body from results."""
    import importlib.metadata  # noqa: PLC0415
    import platform  # noqa: PLC0415
    import sys  # noqa: PLC0415

    try:
        ver = importlib.metadata.version("summon-claude")
    except importlib.metadata.PackageNotFoundError:
        ver = "unknown"

    vi = sys.version_info
    lines = [
        "## summon doctor report",
        "",
        f"**summon-claude:** {ver}",
        f"**Python:** {vi.major}.{vi.minor}.{vi.micro}",
        f"**Platform:** {platform.system()} {platform.release()}",
        f"**Timestamp:** {datetime.now(UTC).isoformat()}",
        "",
        "## Check Results",
        "",
    ]

    for r in results:
        redacted = _redact_result(r)
        status = redacted.status.upper()
        lines.append(f"### [{status}] {redacted.subsystem}")
        lines.append(f"{redacted.message}")
        if redacted.details:
            lines.append("")
            lines.append("<details><summary>Details</summary>")
            lines.append("")
            for d in redacted.details:
                lines.append(f"- {d}")
            lines.append("")
            lines.append("</details>")
        if redacted.suggestion:
            lines.append(f"**Suggestion:** {redacted.suggestion}")
        if redacted.collected_logs:
            for log_name, log_lines in redacted.collected_logs.items():
                n = len(log_lines)
                lines.append(f"<details><summary>{log_name} (last {n} lines)</summary>")
                lines.append("")
                lines.append("```")
                lines.extend(log_lines)
                lines.append("```")
                lines.append("")
                lines.append("</details>")
        lines.append("")

    # Escape @ to prevent GitHub @mentions (SEC-008)
    body = "\n".join(lines)
    return body.replace("@", "\\@")


async def _submit_to_github(gh: str, body: str) -> None:
    """Submit the body as a GitHub issue via gh CLI."""
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            gh,
            "issue",
            "create",
            "--repo",
            "summon-claude/summon-claude",
            "--title",
            "summon doctor report",
            "--body-file",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=body.encode()),
            timeout=30,
        )
        if proc.returncode == 0:
            url = stdout.decode().strip()
            click.echo(f"Issue created: {url}")
        else:
            err = stderr.decode().strip()
            click.echo(f"Error: gh failed: {err}", err=True)
    except TimeoutError:
        if proc is not None:
            proc.kill()
            await proc.wait()  # reap zombie
        click.echo(
            "Error: gh issue create timed out after 30s",
            err=True,
        )
    except Exception as e:
        click.echo(f"Error: could not submit issue: {e}", err=True)
