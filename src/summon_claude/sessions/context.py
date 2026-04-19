"""Context window usage tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeSDKClient

logger = logging.getLogger(__name__)

_200K = 200_000

# Prefix -> default (non-1M) context window.  Order matters: more specific
# prefixes must come before shorter ones so startswith matching works.
CONTEXT_WINDOW_SIZES: dict[str, int] = {
    # Current generation
    "claude-opus-4-6": _200K,
    "claude-sonnet-4-6": _200K,
    "claude-haiku-4-5": _200K,
    # Previous generation
    "claude-sonnet-4-5": _200K,
    "claude-opus-4-5": _200K,
    "claude-opus-4-1": _200K,
    "claude-sonnet-4-0": _200K,
    "claude-opus-4-0": _200K,
    # Catch-all for claude-4 family (e.g. claude-sonnet-4, claude-opus-4)
    "claude-opus-4": _200K,
    "claude-sonnet-4": _200K,
    "claude-haiku-4": _200K,
    # Claude 3.x family
    "claude-3-7-sonnet": _200K,
    "claude-3-5-sonnet": _200K,
    "claude-3-5-haiku": _200K,
    "claude-3-opus": _200K,
    "claude-3-sonnet": _200K,
    "claude-3-haiku": _200K,
}

DEFAULT_CONTEXT_WINDOW = _200K

# Runtime overlay: populated by reconcile_context_window_sizes() for models
# not in CONTEXT_WINDOW_SIZES. Module-global so it accumulates across calls.
_runtime_context_sizes: dict[str, int] = {}

# CONTEXT_WINDOW_SIZES prefixes that should NOT trigger stale-entry warnings.
# Includes catch-all family prefixes and backward-compat 3.x entries kept
# intentionally. Suppression uses prefix matching (key.startswith(s)).
_SUPPRESS_STALE_PREFIXES: frozenset[str] = frozenset(
    {
        "claude-opus-4",
        "claude-sonnet-4",
        "claude-haiku-4",
        "claude-3-7-sonnet",
        "claude-3-5-sonnet",
        "claude-3-5-haiku",
        "claude-3-opus",
        "claude-3-sonnet",
        "claude-3-haiku",
    }
)


def reconcile_context_window_sizes(sdk_models: list[dict[str, str]]) -> None:
    """Compare SDK model list against CONTEXT_WINDOW_SIZES and update overlay.

    - Unknown models (no prefix match in CONTEXT_WINDOW_SIZES) get added to
      _runtime_context_sizes with DEFAULT_CONTEXT_WINDOW.
    - Stale CONTEXT_WINDOW_SIZES prefixes (no matching SDK model) are logged
      at INFO level unless suppressed by _SUPPRESS_STALE_PREFIXES.
    - Safe to call multiple times: additive/idempotent.
    """
    model_values: list[str] = []
    for m in sdk_models:
        val = m.get("value")
        if val:
            model_values.append(val)

    # Detect unknown models and add to runtime overlay.
    for model_value in model_values:
        matched = any(model_value.startswith(prefix) for prefix in CONTEXT_WINDOW_SIZES)
        if not matched:
            if len(model_value) > 200:
                logger.warning(
                    "Skipping oversized model_value in reconcile_context_window_sizes: %d chars",
                    len(model_value),
                )
                continue
            if len(_runtime_context_sizes) >= 500:
                logger.warning(
                    "_runtime_context_sizes cap reached (500 entries); skipping %r",
                    model_value,
                )
                continue
            _runtime_context_sizes[model_value] = DEFAULT_CONTEXT_WINDOW
            logger.info(
                "Model %s has no CONTEXT_WINDOW_SIZES mapping; using default %d",
                model_value,
                DEFAULT_CONTEXT_WINDOW,
            )

    # Detect stale CONTEXT_WINDOW_SIZES prefixes.
    for prefix in CONTEXT_WINDOW_SIZES:
        suppressed = any(prefix.startswith(s) for s in _SUPPRESS_STALE_PREFIXES)
        if suppressed:
            continue
        has_match = any(mv.startswith(prefix) for mv in model_values)
        if not has_match:
            logger.info(
                "CONTEXT_WINDOW_SIZES prefix %r has no matching SDK models — may be deprecated",
                prefix,
            )


@dataclass(frozen=True, slots=True)
class ContextUsage:
    """Snapshot of context window consumption for a single turn."""

    input_tokens: int
    context_window: int
    percentage: float  # 0-100


async def get_sdk_context_usage(client: ClaudeSDKClient) -> ContextUsage | None:
    """Get context usage from the SDK's get_context_usage() method.

    Returns None on any error (network, method not available, etc.).
    Must be called while the client is still connected (inside the
    ``async with ClaudeSDKClient()`` block).
    """
    try:
        usage = await client.get_context_usage()
        total_tokens = usage.get("totalTokens")
        max_tokens = usage.get("maxTokens")
        percentage = usage.get("percentage")
        if total_tokens is None or max_tokens is None or percentage is None:
            logger.debug("get_context_usage() returned incomplete data: %s", usage)
            return None
        return ContextUsage(
            input_tokens=total_tokens,
            context_window=max_tokens,
            percentage=percentage,
        )
    except Exception as e:
        logger.debug("get_context_usage() failed: %s", e)
        return None
