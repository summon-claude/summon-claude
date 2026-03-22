"""Claude CLI preflight checks and model discovery."""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import NamedTuple

logger = logging.getLogger(__name__)

# Known model IDs — update when new models ship.
# Used as suggestions in `summon init`, not for validation.
FALLBACK_MODELS: list[str] = [
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-haiku-4-5-20251001",
]


class CliStatus(NamedTuple):
    """Result of a Claude CLI preflight check."""

    found: bool
    version: str | None
    path: str | None


def check_claude_cli() -> CliStatus:
    """Check if the Claude CLI is available and get its version.

    Returns CliStatus(found=False, ...) if the binary is not on PATH
    or cannot be executed. All errors are caught — never raises.
    """
    path = shutil.which("claude")
    if not path:
        return CliStatus(found=False, version=None, path=None)

    try:
        result = subprocess.run(  # noqa: S603
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        version = result.stdout.strip() if result.returncode == 0 else None
        return CliStatus(found=True, version=version, path=path)
    except (subprocess.TimeoutExpired, OSError):
        return CliStatus(found=True, version=None, path=path)


def get_available_models() -> list[str]:
    """Return known Claude model IDs for use in summon init prompts.

    Returns a static list of model IDs. These are suggestions, not
    a validation constraint — users can enter any model string.

    Sync-only, suitable for use as ConfigOption.choices_fn.
    """
    return list(FALLBACK_MODELS)
