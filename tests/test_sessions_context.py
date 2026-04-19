"""Tests for summon_claude.context — context window usage tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import summon_claude.sessions.context as ctx_mod
from summon_claude.sessions.context import (
    _SUPPRESS_STALE_PREFIXES,
    CONTEXT_WINDOW_SIZES,
    DEFAULT_CONTEXT_WINDOW,
    ContextUsage,
    _runtime_context_sizes,
    get_sdk_context_usage,
    reconcile_context_window_sizes,
)


@pytest.fixture(autouse=True)
def clear_runtime_context_sizes():
    """Clear module-global _runtime_context_sizes between tests.

    Must be module-level (not inside a class) to protect ALL tests in this
    file from pollution via the shared module-global dict.
    """
    ctx_mod._runtime_context_sizes.clear()
    yield
    ctx_mod._runtime_context_sizes.clear()


class TestContextUsageDataclass:
    def test_context_usage_dataclass_is_frozen(self):
        """ContextUsage should be immutable."""
        ctx = ContextUsage(input_tokens=50000, context_window=200000, percentage=25.0)
        with pytest.raises(AttributeError):
            ctx.input_tokens = 60000

    def test_context_usage_has_correct_attributes(self):
        """ContextUsage should have input_tokens, context_window, percentage."""
        ctx = ContextUsage(input_tokens=50000, context_window=200000, percentage=25.0)
        assert ctx.input_tokens == 50000
        assert ctx.context_window == 200000
        assert ctx.percentage == pytest.approx(25.0)


class TestGetSdkContextUsage:
    async def test_maps_sdk_response_to_context_usage(self):
        """get_sdk_context_usage maps SDK response fields to ContextUsage."""
        client = MagicMock()
        client.get_context_usage = AsyncMock(
            return_value={
                "totalTokens": 50000,
                "maxTokens": 200000,
                "percentage": 25.0,
            }
        )
        result = await get_sdk_context_usage(client)
        assert result is not None
        assert isinstance(result, ContextUsage)
        assert result.input_tokens == 50000
        assert result.context_window == 200000
        assert result.percentage == pytest.approx(25.0)

    async def test_returns_none_on_exception(self):
        """get_sdk_context_usage returns None when SDK raises an error."""
        client = MagicMock()
        client.get_context_usage = AsyncMock(side_effect=RuntimeError("connection lost"))
        result = await get_sdk_context_usage(client)
        assert result is None

    async def test_returns_none_on_missing_keys(self):
        """get_sdk_context_usage returns None when response lacks required keys."""
        client = MagicMock()
        client.get_context_usage = AsyncMock(
            return_value={"totalTokens": 50000}  # missing maxTokens and percentage
        )
        result = await get_sdk_context_usage(client)
        assert result is None

    async def test_handles_1m_context_window(self):
        """get_sdk_context_usage correctly maps 1M context window values."""
        client = MagicMock()
        client.get_context_usage = AsyncMock(
            return_value={
                "totalTokens": 500000,
                "maxTokens": 1000000,
                "percentage": 50.0,
            }
        )
        result = await get_sdk_context_usage(client)
        assert result is not None
        assert result.context_window == 1000000
        assert result.percentage == pytest.approx(50.0)

    async def test_handles_zero_tokens(self):
        """get_sdk_context_usage handles zero token count."""
        client = MagicMock()
        client.get_context_usage = AsyncMock(
            return_value={
                "totalTokens": 0,
                "maxTokens": 200000,
                "percentage": 0.0,
            }
        )
        result = await get_sdk_context_usage(client)
        assert result is not None
        assert result.input_tokens == 0
        assert result.percentage == pytest.approx(0.0)


class TestReconcileContextWindowSizes:
    def test_reconcile_unknown_model_gets_runtime_entry(self):
        """Unknown model → added to _runtime_context_sizes with DEFAULT."""
        reconcile_context_window_sizes([{"value": "claude-future-5-0"}])
        assert ctx_mod._runtime_context_sizes["claude-future-5-0"] == DEFAULT_CONTEXT_WINDOW

    def test_reconcile_known_model_no_runtime_entry(self):
        """Known model (matches CONTEXT_WINDOW_SIZES prefix) → no overlay entry."""
        reconcile_context_window_sizes([{"value": "claude-opus-4-6"}])
        assert ctx_mod._runtime_context_sizes == {}

    def test_reconcile_stale_entry_logs_info(self, caplog):
        """Non-suppressed CONTEXT_WINDOW_SIZES key with no SDK match → info log."""
        import logging

        synthetic_key = "test-unsuppressed-prefix"
        ctx_mod.CONTEXT_WINDOW_SIZES[synthetic_key] = DEFAULT_CONTEXT_WINDOW
        try:
            with caplog.at_level(logging.INFO, logger="summon_claude.sessions.context"):
                reconcile_context_window_sizes([])
            assert any(synthetic_key in r.message for r in caplog.records)
        finally:
            del ctx_mod.CONTEXT_WINDOW_SIZES[synthetic_key]

    def test_reconcile_skips_entries_without_value(self):
        """Models lacking 'value' key → no crash, no overlay entry."""
        reconcile_context_window_sizes([{"displayName": "No Value"}])
        assert ctx_mod._runtime_context_sizes == {}

    def test_reconcile_idempotent(self):
        """Calling reconcile twice with same model → no duplicates, same values."""
        models = [{"value": "claude-future-5-0"}]
        reconcile_context_window_sizes(models)
        reconcile_context_window_sizes(models)
        assert len(ctx_mod._runtime_context_sizes) == 1
        assert ctx_mod._runtime_context_sizes["claude-future-5-0"] == DEFAULT_CONTEXT_WINDOW

    def test_suppress_stale_prefixes_subset_of_context_window_sizes(self):
        """Every _SUPPRESS_STALE_PREFIXES entry must be a key in CONTEXT_WINDOW_SIZES.

        Guard test: catches drift when CONTEXT_WINDOW_SIZES is updated but
        _SUPPRESS_STALE_PREFIXES is not.
        """
        for prefix in _SUPPRESS_STALE_PREFIXES:
            assert prefix in CONTEXT_WINDOW_SIZES, (
                f"_SUPPRESS_STALE_PREFIXES entry {prefix!r} not found in CONTEXT_WINDOW_SIZES"
            )

    def test_reconcile_bounds_cap(self, caplog):
        """Cap at 500 entries: new models are skipped when cap is reached."""
        import logging

        for i in range(500):
            ctx_mod._runtime_context_sizes[f"fake-model-{i}"] = DEFAULT_CONTEXT_WINDOW
        with caplog.at_level(logging.WARNING, logger="summon_claude.sessions.context"):
            reconcile_context_window_sizes([{"value": "new-model"}])
        assert "new-model" not in ctx_mod._runtime_context_sizes
        assert any("cap reached" in r.message for r in caplog.records)

    def test_reconcile_oversized_model_value_skipped(self, caplog):
        """model_value longer than 200 chars → skipped with a WARNING, not added to overlay."""
        import logging

        oversized = "x" * 201
        with caplog.at_level(logging.WARNING, logger="summon_claude.sessions.context"):
            reconcile_context_window_sizes([{"value": oversized}])
        assert oversized not in ctx_mod._runtime_context_sizes
        assert any("oversized" in r.message for r in caplog.records)
