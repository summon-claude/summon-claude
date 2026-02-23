"""CLI config subcommands: show, path, edit, set."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys

_TOKEN_MASK_THRESHOLD = 8

_SETTABLE_KEYS = frozenset(
    {
        "SUMMON_SLACK_BOT_TOKEN",
        "SUMMON_SLACK_APP_TOKEN",
        "SUMMON_SLACK_SIGNING_SECRET",
        "SUMMON_ALLOWED_USER_IDS",
        "SUMMON_DEFAULT_MODEL",
        "SUMMON_CHANNEL_PREFIX",
        "SUMMON_USE_VERTEX",
        "SUMMON_VERTEX_PROJECT_ID",
        "SUMMON_VERTEX_REGION",
        "SUMMON_PERMISSION_DEBOUNCE_MS",
        "SUMMON_MAX_INLINE_CHARS",
    }
)


def _require_config_file():
    """Return the config file Path if it exists, else print a hint and return None."""
    from .config import get_config_file

    config_file = get_config_file()
    if not config_file.exists():
        print(f"No config file found at {config_file}")
        print("Run `summon init` to create one.")
        return None
    return config_file


def config_path() -> None:
    from .config import get_config_file

    print(get_config_file())


def config_show() -> None:
    config_file = _require_config_file()
    if config_file is None:
        return

    token_keys = {
        "SUMMON_SLACK_BOT_TOKEN",
        "SUMMON_SLACK_APP_TOKEN",
        "SUMMON_SLACK_SIGNING_SECRET",
    }

    for raw_line in config_file.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            print(raw_line)
            continue
        if "=" in stripped:
            k, _, v = stripped.partition("=")
            k = k.strip()
            v = v.strip()
            if k in token_keys and len(v) > _TOKEN_MASK_THRESHOLD:
                v = v[:_TOKEN_MASK_THRESHOLD] + "..."
            print(f"{k}={v}")
        else:
            print(raw_line)


def config_edit() -> None:
    config_file = _require_config_file()
    if config_file is None:
        return

    editor = os.environ.get("EDITOR", "vi")
    try:
        subprocess.run([editor, str(config_file)], check=False)  # noqa: S603
    except FileNotFoundError:
        print(f"Editor '{editor}' not found. Set $EDITOR to your preferred editor.")
        sys.exit(1)


def config_set(key: str, value: str) -> None:
    from .config import get_config_dir, get_config_file

    key = key.strip().upper()
    if key not in _SETTABLE_KEYS:
        print(f"Unknown config key: {key!r}", file=sys.stderr)
        print(f"Valid keys: {', '.join(sorted(_SETTABLE_KEYS))}", file=sys.stderr)
        sys.exit(1)

    # Strip newlines to prevent injection into the .env format
    value = value.replace("\n", "").replace("\r", "")

    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = get_config_file()

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
    print(f"Set {key} in {config_file}")
