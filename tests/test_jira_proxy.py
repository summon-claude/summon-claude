"""Tests for summon_claude.jira_proxy — JiraAuthProxy reverse proxy."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from summon_claude.jira_proxy import JiraAuthProxy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token_data(
    *,
    token: str = "test-access-token",  # noqa: S107
    expires_at: float | None = None,
) -> dict[str, Any]:
    if expires_at is None:
        expires_at = time.time() + 7200  # fresh
    return {"access_token": token, "expires_at": expires_at}


def _make_stat(mtime: float = 1000.0) -> MagicMock:
    stat = MagicMock()
    stat.st_mtime = mtime
    return stat


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def proxy(tmp_path: Path):
    """Return a JiraAuthProxy with token_path pointing to tmp_path."""
    p = JiraAuthProxy()
    p._token_path = tmp_path / "token.json"
    return p


@pytest.fixture
async def started_proxy(proxy: JiraAuthProxy):
    """Start and yield a proxy, stop it after the test."""
    await proxy.start()
    yield proxy
    await proxy.stop()


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestProxyLifecycle:
    def test_port_raises_before_start(self, proxy: JiraAuthProxy):
        with pytest.raises(RuntimeError, match="not started"):
            _ = proxy.port

    async def test_start_returns_ephemeral_port(self, proxy: JiraAuthProxy):
        port = await proxy.start()
        try:
            assert port > 0
            assert proxy.port == port
        finally:
            await proxy.stop()

    async def test_stop_resets_port(self, proxy: JiraAuthProxy):
        await proxy.start()
        await proxy.stop()
        with pytest.raises(RuntimeError, match="not started"):
            _ = proxy.port

    async def test_double_stop_no_error(self, proxy: JiraAuthProxy):
        await proxy.start()
        await proxy.stop()
        await proxy.stop()  # Must not raise


# ---------------------------------------------------------------------------
# Token caching tests
# ---------------------------------------------------------------------------


class TestTokenCache:
    async def test_token_cache_hit(self, proxy: JiraAuthProxy):
        """Fresh cached token is returned without calling refresh or load."""
        proxy._cached_token = "cached-token"
        proxy._token_expires_at = time.time() + 7200
        proxy._token_file_mtime = 1000.0

        with (
            patch("pathlib.Path.stat", return_value=_make_stat(1000.0)),
            patch(
                "summon_claude.jira_proxy.refresh_jira_token_if_needed",
                new_callable=AsyncMock,
            ) as mock_refresh,
            patch("summon_claude.jira_proxy.load_jira_token") as mock_load,
        ):
            result = await proxy._get_fresh_token()

        assert result == "cached-token"
        mock_refresh.assert_not_called()
        mock_load.assert_not_called()

    async def test_token_refresh_on_expiry(self, proxy: JiraAuthProxy):
        """Expired token triggers refresh, then loads from disk."""
        proxy._cached_token = "old-token"
        proxy._token_expires_at = time.time() - 10  # expired
        proxy._token_file_mtime = 1000.0

        token_data = _make_token_data(token="new-token")

        with (
            patch("pathlib.Path.stat", return_value=_make_stat(1000.0)),
            patch(
                "summon_claude.jira_proxy.refresh_jira_token_if_needed",
                new_callable=AsyncMock,
            ) as mock_refresh,
            patch("summon_claude.jira_proxy.load_jira_token", return_value=token_data),
        ):
            result = await proxy._get_fresh_token()

        assert result == "new-token"
        mock_refresh.assert_called_once()

    async def test_token_refresh_failure_returns_none(self, proxy: JiraAuthProxy):
        """When load_jira_token returns None after refresh attempt, result is None."""
        proxy._token_expires_at = 0  # expired

        with (
            patch("pathlib.Path.stat", return_value=_make_stat(1000.0)),
            patch(
                "summon_claude.jira_proxy.refresh_jira_token_if_needed",
                new_callable=AsyncMock,
            ),
            patch("summon_claude.jira_proxy.load_jira_token", return_value=None),
        ):
            result = await proxy._get_fresh_token()

        assert result is None

    async def test_mtime_cache_invalidation(self, proxy: JiraAuthProxy):
        """Changed file mtime forces a re-read even if expiry appears fresh."""
        proxy._cached_token = "stale-token"
        # Set expiry far in future so it looks fresh
        proxy._token_expires_at = time.time() + 7200
        proxy._token_file_mtime = 1000.0  # old mtime

        token_data = _make_token_data(token="fresh-token")

        with (
            # New mtime — different from cached
            patch("pathlib.Path.stat", return_value=_make_stat(2000.0)),
            patch(
                "summon_claude.jira_proxy.refresh_jira_token_if_needed",
                new_callable=AsyncMock,
            ),
            patch("summon_claude.jira_proxy.load_jira_token", return_value=token_data),
        ):
            result = await proxy._get_fresh_token()

        assert result == "fresh-token"

    async def test_token_file_not_found_returns_none(self, proxy: JiraAuthProxy):
        """Missing token file returns None immediately."""
        with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
            result = await proxy._get_fresh_token()

        assert result is None

    async def test_concurrent_refresh_serialization(self, proxy: JiraAuthProxy):
        """Multiple concurrent callers trigger only one refresh call."""
        proxy._token_expires_at = 0  # expired
        proxy._token_file_mtime = 1000.0
        refresh_call_count = 0

        async def _fake_refresh() -> None:
            nonlocal refresh_call_count
            refresh_call_count += 1
            await asyncio.sleep(0.01)  # simulate network delay

        token_data = _make_token_data(token="refreshed-token")

        with (
            patch("pathlib.Path.stat", return_value=_make_stat(1000.0)),
            patch(
                "summon_claude.jira_proxy.refresh_jira_token_if_needed",
                side_effect=_fake_refresh,
            ),
            patch("summon_claude.jira_proxy.load_jira_token", return_value=token_data),
        ):
            results = await asyncio.gather(
                proxy._get_fresh_token(),
                proxy._get_fresh_token(),
                proxy._get_fresh_token(),
            )

        assert all(r == "refreshed-token" for r in results)
        assert refresh_call_count == 1


# ---------------------------------------------------------------------------
# Proxy authentication tests
# ---------------------------------------------------------------------------


class TestProxyAuthentication:
    async def test_proxy_token_missing_returns_403(self, started_proxy: JiraAuthProxy):
        async with (
            aiohttp.ClientSession() as session,
            session.get(f"http://127.0.0.1:{started_proxy.port}/test") as resp,
        ):
            assert resp.status == 403

    async def test_proxy_token_wrong_returns_403(self, started_proxy: JiraAuthProxy):
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                f"http://127.0.0.1:{started_proxy.port}/test",
                headers={"X-Summon-Proxy-Token": "wrong-token"},
            ) as resp,
        ):
            assert resp.status == 403

    async def test_proxy_token_correct_proceeds(self, started_proxy: JiraAuthProxy):
        """Correct proxy token passes auth gate (proceeds to token check, not 403)."""
        with (
            patch("pathlib.Path.stat", side_effect=FileNotFoundError),
        ):
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://127.0.0.1:{started_proxy.port}/test",
                    headers={"X-Summon-Proxy-Token": started_proxy.access_token},
                ) as resp:
                    # Should not be 403 — auth passed, but no token → 502
                    assert resp.status != 403


# ---------------------------------------------------------------------------
# Request forwarding tests
# ---------------------------------------------------------------------------


class TestRequestForwarding:
    async def test_request_forwarding(self, proxy: JiraAuthProxy):
        """Method, path, query string, and body are all forwarded upstream."""
        received: dict[str, Any] = {}

        async def _upstream_handler(request: web.Request) -> web.Response:
            received["method"] = request.method
            received["path"] = request.path
            received["query"] = request.query_string
            received["body"] = await request.read()
            received["auth"] = request.headers.get("Authorization")
            return web.Response(status=200, text="ok")

        upstream_app = web.Application()
        upstream_app.router.add_route("*", "/{path_info:.*}", _upstream_handler)

        async with TestServer(upstream_app) as upstream_server:
            with patch(
                "summon_claude.jira_proxy._TARGET_URL",
                f"http://127.0.0.1:{upstream_server.port}",
            ):
                port = await proxy.start()
                try:
                    token_data = _make_token_data(token="my-access-token")
                    with (
                        patch(
                            "pathlib.Path.stat",
                            return_value=_make_stat(1000.0),
                        ),
                        patch(
                            "summon_claude.jira_proxy.refresh_jira_token_if_needed",
                            new_callable=AsyncMock,
                        ),
                        patch(
                            "summon_claude.jira_proxy.load_jira_token",
                            return_value=token_data,
                        ),
                    ):
                        async with aiohttp.ClientSession() as session:
                            async with session.post(
                                f"http://127.0.0.1:{port}/api/v1/resource?key=val",
                                headers={"X-Summon-Proxy-Token": proxy.access_token},
                                data=b"request-body",
                            ) as resp:
                                assert resp.status == 200
                finally:
                    await proxy.stop()

        assert received["method"] == "POST"
        assert received["path"] == "/api/v1/resource"
        assert received["query"] == "key=val"
        assert received["body"] == b"request-body"
        assert received["auth"] == "Bearer my-access-token"

    async def test_proxy_token_not_forwarded_upstream(self, proxy: JiraAuthProxy):
        """X-Summon-Proxy-Token header must not be forwarded to the upstream server."""
        received_headers: dict[str, str] = {}

        async def _upstream_handler(request: web.Request) -> web.Response:
            received_headers.update(dict(request.headers))
            return web.Response(status=200, text="ok")

        upstream_app = web.Application()
        upstream_app.router.add_route("*", "/{path_info:.*}", _upstream_handler)

        async with TestServer(upstream_app) as upstream_server:
            with patch(
                "summon_claude.jira_proxy._TARGET_URL",
                f"http://127.0.0.1:{upstream_server.port}",
            ):
                port = await proxy.start()
                try:
                    token_data = _make_token_data()
                    with (
                        patch(
                            "pathlib.Path.stat",
                            return_value=_make_stat(1000.0),
                        ),
                        patch(
                            "summon_claude.jira_proxy.refresh_jira_token_if_needed",
                            new_callable=AsyncMock,
                        ),
                        patch(
                            "summon_claude.jira_proxy.load_jira_token",
                            return_value=token_data,
                        ),
                    ):
                        async with aiohttp.ClientSession() as session:
                            async with session.get(
                                f"http://127.0.0.1:{port}/test",
                                headers={"X-Summon-Proxy-Token": proxy.access_token},
                            ) as resp:
                                assert resp.status == 200
                finally:
                    await proxy.stop()

        assert "X-Summon-Proxy-Token" not in received_headers
        assert "x-summon-proxy-token" not in {k.lower() for k in received_headers}

    async def test_response_streaming(self, proxy: JiraAuthProxy):
        """Response status and body are preserved from upstream."""

        async def _upstream_handler(request: web.Request) -> web.Response:
            return web.Response(status=201, text="created-body")

        upstream_app = web.Application()
        upstream_app.router.add_route("*", "/{path_info:.*}", _upstream_handler)

        async with TestServer(upstream_app) as upstream_server:
            with patch(
                "summon_claude.jira_proxy._TARGET_URL",
                f"http://127.0.0.1:{upstream_server.port}",
            ):
                port = await proxy.start()
                try:
                    token_data = _make_token_data()
                    with (
                        patch(
                            "pathlib.Path.stat",
                            return_value=_make_stat(1000.0),
                        ),
                        patch(
                            "summon_claude.jira_proxy.refresh_jira_token_if_needed",
                            new_callable=AsyncMock,
                        ),
                        patch(
                            "summon_claude.jira_proxy.load_jira_token",
                            return_value=token_data,
                        ),
                    ):
                        async with aiohttp.ClientSession() as session:
                            async with session.get(
                                f"http://127.0.0.1:{port}/test",
                                headers={"X-Summon-Proxy-Token": proxy.access_token},
                            ) as resp:
                                assert resp.status == 201
                                body = await resp.text()
                                assert body == "created-body"
                finally:
                    await proxy.stop()


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    async def test_upstream_network_error_returns_502(self, proxy: JiraAuthProxy):
        """ClientError from upstream → 502."""
        port = await proxy.start()
        try:
            token_data = _make_token_data()
            with (
                patch(
                    "pathlib.Path.stat",
                    return_value=_make_stat(1000.0),
                ),
                patch(
                    "summon_claude.jira_proxy.refresh_jira_token_if_needed",
                    new_callable=AsyncMock,
                ),
                patch(
                    "summon_claude.jira_proxy.load_jira_token",
                    return_value=token_data,
                ),
                # Make the upstream request raise a ClientError
                patch.object(
                    proxy,
                    "_http_session",
                    create=True,
                ),
            ):
                # Replace _http_session with a mock that raises ClientError
                mock_session = MagicMock()
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(
                    side_effect=aiohttp.ClientConnectionError("refused")
                )
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_session.request = MagicMock(return_value=mock_ctx)
                mock_session.close = AsyncMock()
                real_session = proxy._http_session
                proxy._http_session = mock_session

                async with (
                    aiohttp.ClientSession() as session,
                    session.get(
                        f"http://127.0.0.1:{port}/test",
                        headers={"X-Summon-Proxy-Token": proxy.access_token},
                    ) as resp,
                ):
                    assert resp.status == 502
                proxy._http_session = real_session
        finally:
            await proxy.stop()

    async def test_upstream_timeout_returns_504(self, proxy: JiraAuthProxy):
        """TimeoutError from upstream → 504."""
        port = await proxy.start()
        try:
            token_data = _make_token_data()
            with (
                patch(
                    "pathlib.Path.stat",
                    return_value=_make_stat(1000.0),
                ),
                patch(
                    "summon_claude.jira_proxy.refresh_jira_token_if_needed",
                    new_callable=AsyncMock,
                ),
                patch(
                    "summon_claude.jira_proxy.load_jira_token",
                    return_value=token_data,
                ),
            ):
                mock_session = MagicMock()
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(side_effect=TimeoutError())
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_session.request = MagicMock(return_value=mock_ctx)
                mock_session.close = AsyncMock()
                real_session = proxy._http_session
                proxy._http_session = mock_session

                async with (
                    aiohttp.ClientSession() as session,
                    session.get(
                        f"http://127.0.0.1:{port}/test",
                        headers={"X-Summon-Proxy-Token": proxy.access_token},
                    ) as resp,
                ):
                    assert resp.status == 504
                proxy._http_session = real_session
        finally:
            await proxy.stop()

    async def test_jira_token_unavailable_returns_502(self, started_proxy: JiraAuthProxy):
        """No Jira token → 502 before forwarding."""
        with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://127.0.0.1:{started_proxy.port}/test",
                    headers={"X-Summon-Proxy-Token": started_proxy.access_token},
                ) as resp:
                    assert resp.status == 502
                    text = await resp.text()
                    assert "unavailable" in text
