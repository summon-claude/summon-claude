"""Tests for summon_claude.session — session orchestrator."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from summon_claude._formatting import format_file_references
from summon_claude.auth import SessionAuth
from summon_claude.config import SummonConfig
from summon_claude.rate_limiter import RateLimiter
from summon_claude.session import SessionOptions, SummonSession


def make_config(**overrides) -> SummonConfig:
    defaults = {
        "slack_bot_token": "xoxb-test-token",
        "slack_app_token": "xapp-test-token",
        "slack_signing_secret": "test-secret",
        "default_model": "claude-opus-4-6",
        "channel_prefix": "summon",
        "permission_debounce_ms": 10,
        "max_inline_chars": 2500,
    }
    defaults.update(overrides)
    return SummonConfig.model_validate(defaults)


def make_options(**overrides) -> SessionOptions:
    defaults = {
        "session_id": "test-session",
        "cwd": "/tmp/test",
        "name": "test",
    }
    defaults.update(overrides)
    return SessionOptions(**defaults)


def make_auth(**overrides) -> SessionAuth:
    defaults = {
        "short_code": "abcd1234",
        "session_id": "test-session",
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
    }
    defaults.update(overrides)
    return SessionAuth(**defaults)


class TestRateLimiter:
    def test_first_request_allowed(self):
        rl = RateLimiter(cooldown_seconds=2.0)
        assert rl.check("user1") is True

    def test_second_request_within_cooldown_denied(self):
        rl = RateLimiter(cooldown_seconds=2.0)
        rl.check("user1")
        assert rl.check("user1") is False

    def test_different_keys_are_independent(self):
        rl = RateLimiter(cooldown_seconds=2.0)
        rl.check("user1")
        assert rl.check("user2") is True

    async def test_rate_limiter_allows_after_cooldown(self):
        rl = RateLimiter(cooldown_seconds=0.1)
        rl.check("user1")
        assert rl.check("user1") is False
        await asyncio.sleep(0.2)
        assert rl.check("user1") is True

    def test_cleanup_removes_old_entries(self):
        rl = RateLimiter(cooldown_seconds=2.0)
        rl._last_attempt["old-user"] = time.monotonic() - 400  # older than max_age
        rl.check("user1")
        rl._cleanup(max_age=300.0)
        assert "old-user" not in rl._last_attempt
        assert "user1" in rl._last_attempt


class TestGenerateSessionToken:
    async def test_returns_session_auth(self, tmp_path):
        """generate_session_token should return a SessionAuth with correct fields."""
        from summon_claude.auth import generate_session_token
        from summon_claude.registry import SessionRegistry

        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            auth = await generate_session_token(registry, "sess-test")

        assert isinstance(auth, SessionAuth)
        assert len(auth.short_code) == 8
        assert auth.session_id == "sess-test"
        assert auth.expires_at > datetime.now(UTC)


class TestFormatFileReferences:
    def test_empty_list_returns_empty_string(self):
        result = format_file_references([])
        assert result == ""

    def test_single_file_with_name(self):
        files = [{"name": "photo.png", "filetype": "png", "size": 1024}]
        result = format_file_references(files)
        assert "photo.png" in result
        assert "(png)" in result
        assert "(1024 bytes)" in result
        # URL should NOT be included (Claude can't fetch Slack private URLs)
        assert "https://" not in result

    def test_single_file_without_url(self):
        files = [{"name": "doc.txt", "filetype": "txt"}]
        result = format_file_references(files)
        assert "doc.txt" in result
        assert "(txt)" in result

    def test_multiple_files_joined_by_newlines(self):
        files = [
            {"name": "a.py", "url_private_download": "https://example.com/a"},
            {"name": "b.py", "url_private_download": "https://example.com/b"},
        ]
        result = format_file_references(files)
        lines = result.splitlines()
        assert len(lines) == 2
        assert "a.py" in lines[0]
        assert "b.py" in lines[1]

    def test_missing_name_uses_unknown(self):
        files = [{"url_private": "https://example.com/f"}]
        result = format_file_references(files)
        assert "unknown" in result


class TestSessionSignalHandler:
    async def test_handle_signal_sets_shutdown_event(self):
        config = make_config()
        session = SummonSession(config, make_options(), auth=make_auth())
        assert not session._shutdown_event.is_set()
        session._handle_signal()
        assert session._shutdown_event.is_set()

    async def test_handle_signal_puts_sentinel_on_queue(self):
        config = make_config()
        session = SummonSession(config, make_options(), auth=make_auth())
        session._handle_signal()
        item = await asyncio.wait_for(session._message_queue.get(), timeout=1.0)
        assert item == ("", None)

    async def test_handle_signal_second_signal_force_exits(self):
        """Second signal call should trigger os._exit(1) when event already set."""
        config = make_config()
        session = SummonSession(config, make_options(), auth=make_auth())

        with patch("os._exit") as mock_exit:
            # First signal sets the event
            session._handle_signal()
            assert session._shutdown_event.is_set()
            mock_exit.assert_not_called()

            # Second signal should force exit
            session._handle_signal()
            mock_exit.assert_called_once_with(1)


class TestWaitForAuth:
    async def test_returns_immediately_when_event_set(self):
        config = make_config()
        session = SummonSession(config, make_options(), auth=make_auth())
        session._authenticated_event.set()

        # Should complete quickly since event is already set
        await asyncio.wait_for(session._wait_for_auth(), timeout=2.0)

    async def test_returns_when_shutdown_event_set(self):
        config = make_config()
        session = SummonSession(config, make_options(), auth=make_auth())
        session._shutdown_event.set()

        await asyncio.wait_for(session._wait_for_auth(), timeout=2.0)


class TestSlashCommandHandler:
    """Test the /summon slash command handler internals."""

    async def test_verify_short_code_returns_result(self, tmp_path):
        """verify_short_code should return a result for a valid code."""
        from summon_claude.auth import generate_session_token, verify_short_code
        from summon_claude.registry import SessionRegistry

        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-1", 1234, "/tmp")
            auth = await generate_session_token(registry, "sess-1")

            result = await verify_short_code(registry, auth.short_code)
            assert result is not None

    async def test_slash_command_invalid_code_no_event_set(self, tmp_path):
        """Invalid code should NOT set authenticated_event."""
        from summon_claude.auth import verify_short_code
        from summon_claude.registry import SessionRegistry

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-2", 1234, "/tmp")

            session = SummonSession(
                config,
                make_options(session_id="sess-2"),
                auth=make_auth(session_id="sess-2"),
            )

            result = await verify_short_code(registry, "badcod")
            assert result is None
            assert not session._authenticated_event.is_set()


class TestSessionShutdownSummary:
    async def test_shutdown_posts_summary_message(self, tmp_path):
        """_shutdown should post turns/cost summary to channel."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-sd", 1234, "/tmp")

            mock_client = AsyncMock()
            mock_provider = AsyncMock()
            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()
            mock_channel_manager = AsyncMock(spec=ChannelManager)

            session = SummonSession(
                config,
                make_options(session_id="sess-sd"),
                auth=make_auth(session_id="sess-sd"),
            )
            session._total_turns = 3
            session._total_cost = 0.0456

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=mock_provider,
                permission_handler=mock_permission_handler,
                channel_id="C_TEST_CHAN",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )
            mock_channel_manager.archive_session_channel = AsyncMock()

            await session._shutdown(rt)

            # Summary message should have been posted via provider
            mock_provider.post_message.assert_called_once()
            call_args = mock_provider.post_message.call_args
            assert call_args[0][0] == "C_TEST_CHAN"  # channel_id
            assert "3" in call_args[0][1]  # turns in message text
            assert "0.0456" in call_args[0][1] or "0.046" in call_args[0][1]

    async def test_shutdown_preserves_channel(self, tmp_path):
        """_shutdown should NOT archive the session channel — channels are preserved."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-arch", 1234, "/tmp")

            mock_client = AsyncMock()
            mock_client.chat_postMessage = AsyncMock(return_value={"ok": True})

            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()

            session = SummonSession(
                config,
                make_options(session_id="sess-arch"),
                auth=make_auth(session_id="sess-arch"),
            )

            mock_channel_manager = AsyncMock(spec=ChannelManager)
            mock_channel_manager.archive_session_channel = AsyncMock()
            mock_provider = AsyncMock()

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=mock_provider,
                permission_handler=mock_permission_handler,
                channel_id="C_ARCH_CHAN",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )

            await session._shutdown(rt)

            # Channel should NOT be archived — it is preserved
            mock_channel_manager.archive_session_channel.assert_not_called()
            # Disconnect message should be posted instead
            mock_provider.post_message.assert_called_once()
            call_args = mock_provider.post_message.call_args
            assert call_args[0][0] == "C_ARCH_CHAN"  # channel_id
            assert "session ended" in call_args[0][1].lower() or "wave" in call_args[0][1].lower()

    async def test_shutdown_updates_registry_to_completed(self, tmp_path):
        """_shutdown should update session status to completed."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-comp", 1234, "/tmp")

            mock_client = AsyncMock()
            mock_client.chat_postMessage = AsyncMock(return_value={"ok": True})

            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()

            session = SummonSession(
                config,
                make_options(session_id="sess-comp"),
                auth=make_auth(session_id="sess-comp"),
            )

            mock_channel_manager = AsyncMock(spec=ChannelManager)
            mock_channel_manager.archive_session_channel = AsyncMock()

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=AsyncMock(),
                permission_handler=mock_permission_handler,
                channel_id="C_COMP_CHAN",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )

            await session._shutdown(rt)

            sess = await registry.get_session("sess-comp")
            assert sess["status"] == "completed"


class TestSessionShutdown:
    """Test shutdown behavior including completion flag and error handling."""

    async def test_shutdown_sets_completed_flag(self, tmp_path):
        """After successful _shutdown(), _shutdown_completed should be True."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-flag", 1234, "/tmp")

            mock_client = AsyncMock()
            mock_client.chat_postMessage = AsyncMock(return_value={"ok": True})

            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()

            session = SummonSession(
                config,
                make_options(session_id="sess-flag"),
                auth=make_auth(session_id="sess-flag"),
            )
            assert session._shutdown_completed is False

            mock_channel_manager = AsyncMock(spec=ChannelManager)
            mock_channel_manager.archive_session_channel = AsyncMock()

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=AsyncMock(),
                permission_handler=mock_permission_handler,
                channel_id="C_FLAG_CHAN",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )

            await session._shutdown(rt)

            assert session._shutdown_completed is True

    async def test_shutdown_completed_flag_false_on_registry_failure(self, tmp_path):
        """If registry update raises, _shutdown_completed should remain False."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-fail", 1234, "/tmp")

            mock_client = AsyncMock()
            mock_client.chat_postMessage = AsyncMock(return_value={"ok": True})

            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()

            session = SummonSession(
                config,
                make_options(session_id="sess-fail"),
                auth=make_auth(session_id="sess-fail"),
            )
            assert session._shutdown_completed is False

            # Mock registry.update_status to raise an exception
            async def failing_update(*args, **kwargs):
                raise RuntimeError("Registry update failed")

            registry.update_status = failing_update

            mock_channel_manager = AsyncMock(spec=ChannelManager)
            mock_channel_manager.archive_session_channel = AsyncMock()

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=AsyncMock(),
                permission_handler=mock_permission_handler,
                channel_id="C_FAIL_CHAN",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )

            await session._shutdown(rt)

            # Flag should remain False because registry update failed
            assert session._shutdown_completed is False

    async def test_shutdown_disconnect_message_failure_continues(self, tmp_path):
        """If posting the disconnect message fails, shutdown should continue."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-arch-fail", 1234, "/tmp")

            mock_client = AsyncMock()
            mock_client.chat_postMessage = AsyncMock(return_value={"ok": True})

            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()

            session = SummonSession(
                config,
                make_options(session_id="sess-arch-fail"),
                auth=make_auth(session_id="sess-arch-fail"),
            )

            mock_channel_manager = AsyncMock(spec=ChannelManager)
            mock_provider = AsyncMock()
            mock_provider.post_message = AsyncMock(side_effect=RuntimeError("Post failed"))

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=mock_provider,
                permission_handler=mock_permission_handler,
                channel_id="C_ARCH_FAIL_CHAN",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )

            # Should not raise — should catch and continue
            await session._shutdown(rt)

            # Registry should still be updated despite message failure
            sess = await registry.get_session("sess-arch-fail")
            assert sess["status"] == "completed"
            assert session._shutdown_completed is True

    async def test_shutdown_timeout_on_slack_call(self, tmp_path):
        """If Slack call hangs, asyncio.wait_for should timeout and continue."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-timeout", 1234, "/tmp")

            mock_client = AsyncMock()

            # Make post_message hang forever (simulating timeout)
            async def hanging_post(*args, **kwargs):
                await asyncio.sleep(999)

            mock_client.chat_postMessage = AsyncMock(side_effect=hanging_post)

            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()

            session = SummonSession(
                config,
                make_options(session_id="sess-timeout"),
                auth=make_auth(session_id="sess-timeout"),
            )

            mock_channel_manager = AsyncMock(spec=ChannelManager)
            mock_channel_manager.archive_session_channel = AsyncMock()

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=AsyncMock(),
                permission_handler=mock_permission_handler,
                channel_id="C_TIMEOUT_CHAN",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )

            # Should timeout and continue (not hang forever)
            await session._shutdown(rt)

            # Registry should still be updated despite Slack timeout
            sess = await registry.get_session("sess-timeout")
            assert sess["status"] == "completed"
            assert session._shutdown_completed is True


class TestAuditEventsLogged:
    async def test_registry_logs_session_created_event(self, tmp_path):
        """Registry.log_event is used in start() — test it works for session_created."""
        from summon_claude.registry import SessionRegistry

        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-audit", 1234, "/tmp")
            await registry.log_event(
                "session_created",
                session_id="sess-audit",
                details={"cwd": "/tmp", "name": "audit-test", "model": "claude-opus-4-6"},
            )

            db = registry._check_connected()
            async with db.execute(
                "SELECT * FROM audit_log WHERE session_id = ? ORDER BY id DESC LIMIT 100",
                ("sess-audit",),
            ) as cursor:
                rows = await cursor.fetchall()
            log = [dict(r) for r in rows]
            assert len(log) >= 1
            assert any(e["event_type"] == "session_created" for e in log)


class TestDisconnectMessageVariants:
    """Test the three variants of disconnect messages."""

    async def test_disconnect_message_ended(self, tmp_path):
        """Normal shutdown should post :wave: 'session ended' message."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-ended", 1234, "/tmp")

            mock_client = AsyncMock()
            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()
            mock_channel_manager = AsyncMock(spec=ChannelManager)
            mock_provider = AsyncMock()

            session = SummonSession(
                config,
                make_options(session_id="sess-ended"),
                auth=make_auth(session_id="sess-ended"),
            )
            session._total_turns = 5
            session._total_cost = 0.125
            session._disconnect_reason = "ended"

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=mock_provider,
                permission_handler=mock_permission_handler,
                channel_id="C_ENDED",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )

            await session._post_disconnect_message(rt, reason="ended")

            # Should post message with :wave: emoji and "session ended"
            mock_provider.post_message.assert_called_once()
            call_args = mock_provider.post_message.call_args
            text = call_args[0][1]
            assert ":wave:" in text
            assert "session ended" in text.lower()
            assert "5" in text  # turns
            assert "0.125" in text or "0.13" in text  # cost

    async def test_disconnect_message_reconnect_exhausted(self, tmp_path):
        """Reconnect exhaustion should post :x: 'disconnected' message."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-exhausted", 1234, "/tmp")

            mock_client = AsyncMock()
            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()
            mock_channel_manager = AsyncMock(spec=ChannelManager)
            mock_provider = AsyncMock()

            session = SummonSession(
                config,
                make_options(session_id="sess-exhausted"),
                auth=make_auth(session_id="sess-exhausted"),
            )
            session._total_turns = 3
            session._total_cost = 0.075
            session._claude_session_id = "claude-sess-123"
            session._disconnect_reason = "reconnect_exhausted"

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=mock_provider,
                permission_handler=mock_permission_handler,
                channel_id="C_EXHAUSTED",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )

            await session._post_disconnect_message(rt, reason="reconnect_exhausted")

            # Should post message with :x: and "disconnected"
            mock_provider.post_message.assert_called_once()
            call_args = mock_provider.post_message.call_args
            text = call_args[0][1]
            assert ":x:" in text
            assert "disconnected" in text.lower()
            assert "3" in text  # turns
            assert "claude-sess-123" in text  # session id

    async def test_disconnect_message_watchdog(self, tmp_path):
        """Watchdog termination should post :rotating_light: message."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-watchdog", 1234, "/tmp")

            mock_client = AsyncMock()
            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()
            mock_channel_manager = AsyncMock(spec=ChannelManager)
            mock_provider = AsyncMock()

            session = SummonSession(
                config,
                make_options(session_id="sess-watchdog"),
                auth=make_auth(session_id="sess-watchdog"),
            )
            session._total_turns = 7
            session._total_cost = 0.235
            session._disconnect_reason = "watchdog"

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=mock_provider,
                permission_handler=mock_permission_handler,
                channel_id="C_WATCHDOG",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )

            await session._post_disconnect_message(rt, reason="watchdog")

            # Should post message with :rotating_light: and "watchdog"
            mock_provider.post_message.assert_called_once()
            call_args = mock_provider.post_message.call_args
            text = call_args[0][1]
            assert ":rotating_light:" in text
            assert "watchdog" in text.lower() or "unresponsive" in text.lower()
            assert "7" in text  # turns


class TestWatchdogLoop:
    """Test the watchdog loop detection of stuck event loops."""

    async def test_watchdog_detects_stuck_loop(self, tmp_path):
        """When heartbeat is stale, watchdog should set disconnect_reason and shutdown event."""
        config = make_config()
        session = SummonSession(
            config,
            make_options(session_id="sess-wd-stuck"),
            auth=make_auth(session_id="sess-wd-stuck"),
        )

        # Set heartbeat time far in the past (beyond 90s threshold)
        loop = asyncio.get_running_loop()
        session._last_heartbeat_time = loop.time() - 120.0

        # Run the actual _watchdog_loop with a very short check interval so it
        # completes in one iteration without sleeping for 15 seconds
        with patch("summon_claude.session._WATCHDOG_CHECK_INTERVAL_S", 0.01):
            await asyncio.wait_for(session._watchdog_loop(), timeout=1.0)

        # Watchdog should have detected the stale heartbeat and triggered shutdown
        assert session._disconnect_reason == "watchdog"
        assert session._shutdown_event.is_set()

    async def test_heartbeat_updates_timestamp(self, tmp_path):
        """Calling heartbeat loop should update _last_heartbeat_time."""
        config = make_config()
        session = SummonSession(
            config,
            make_options(session_id="sess-hb-ts"),
            auth=make_auth(session_id="sess-hb-ts"),
        )

        loop = asyncio.get_running_loop()
        old_time = loop.time() - 50.0
        session._last_heartbeat_time = old_time

        # Build a minimal mock runtime with an async registry heartbeat
        from unittest.mock import MagicMock

        mock_rt = MagicMock()
        mock_rt.registry = AsyncMock()
        mock_rt.registry.heartbeat = AsyncMock()

        # Run one iteration of the heartbeat loop: patch the sleep interval to be very short,
        # then signal shutdown after the first iteration so the loop exits cleanly
        async def _set_shutdown_after_first_heartbeat(*_args, **_kwargs):
            # Allow the heartbeat to complete, then shut down
            session._shutdown_event.set()

        mock_rt.registry.heartbeat.side_effect = _set_shutdown_after_first_heartbeat

        with patch("summon_claude.session._HEARTBEAT_INTERVAL_S", 0.01):
            await asyncio.wait_for(session._heartbeat_loop(mock_rt), timeout=1.0)

        # Timestamp should be updated to approximately now
        elapsed = loop.time() - session._last_heartbeat_time
        assert elapsed < 1.0  # Was updated during the loop iteration


class TestReconnectSocket:
    """Test socket reconnection and handler switching."""

    async def test_reconnect_socket_creates_new_handler(self, tmp_path):
        """_reconnect_socket should create new app and socket handler."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-recon", 1234, "/tmp")

            mock_old_handler = AsyncMock()
            mock_old_handler.client = AsyncMock()
            mock_old_handler.close_async = AsyncMock()

            mock_client = AsyncMock()
            mock_provider = AsyncMock()
            mock_permission_handler = AsyncMock()
            mock_channel_manager = AsyncMock(spec=ChannelManager)

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=mock_provider,
                permission_handler=mock_permission_handler,
                channel_id="C_RECON",
                socket_handler=mock_old_handler,
                channel_manager=mock_channel_manager,
            )

            session = SummonSession(
                config,
                make_options(session_id="sess-recon"),
                auth=make_auth(session_id="sess-recon"),
            )

            # Mock the new socket handler creation
            with patch("summon_claude.session.AsyncSocketModeHandler") as mock_handler_class:
                mock_new_handler = AsyncMock()
                mock_new_handler.connect_async = AsyncMock()
                mock_handler_class.return_value = mock_new_handler

                new_rt = await session._reconnect_socket(rt)

                # New runtime should have a fresh socket handler
                assert new_rt.socket_handler is not rt.socket_handler
                # Old handler should have been closed
                mock_old_handler.close_async.assert_called_once()
                # New handler should be connected
                mock_new_handler.connect_async.assert_called_once()

    async def test_reconnect_preserves_channel_id(self, tmp_path):
        """_reconnect_socket should preserve channel_id in new runtime."""
        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-preserve", 1234, "/tmp")

            mock_old_handler = AsyncMock()
            mock_old_handler.close_async = AsyncMock()

            mock_client = AsyncMock()
            mock_provider = AsyncMock()
            mock_permission_handler = AsyncMock()
            mock_channel_manager = AsyncMock(spec=ChannelManager)

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=mock_provider,
                permission_handler=mock_permission_handler,
                channel_id="C_PRESERVE_ID",
                socket_handler=mock_old_handler,
                channel_manager=mock_channel_manager,
            )

            session = SummonSession(
                config,
                make_options(session_id="sess-preserve"),
                auth=make_auth(session_id="sess-preserve"),
            )

            # Mock AsyncSocketModeHandler with AsyncMock so connect_async is awaitable
            with patch("summon_claude.session.AsyncSocketModeHandler") as mock_handler_class:
                mock_new_handler = AsyncMock()
                mock_handler_class.return_value = mock_new_handler

                with patch("summon_claude.session.AsyncApp"):
                    new_rt = await session._reconnect_socket(rt)

                    # Channel ID should be preserved
                    assert new_rt.channel_id == "C_PRESERVE_ID"
                    assert new_rt.registry is rt.registry
                    assert new_rt.client is rt.client

    async def test_register_event_handlers_no_summon(self, tmp_path):
        """After reconnect, /summon handler should not be re-registered."""
        from slack_bolt.app.async_app import AsyncApp

        from summon_claude.channel_manager import ChannelManager
        from summon_claude.registry import SessionRegistry
        from summon_claude.session import _SessionRuntime

        config = make_config()
        async with SessionRegistry(db_path=tmp_path / "test.db") as registry:
            await registry.register("sess-no-summon", 1234, "/tmp")

            new_app = AsyncApp(
                token=config.slack_bot_token,
                signing_secret=config.slack_signing_secret,
            )

            mock_client = AsyncMock()
            mock_provider = AsyncMock()
            mock_permission_handler = AsyncMock()
            mock_socket_handler = AsyncMock()
            mock_channel_manager = AsyncMock(spec=ChannelManager)

            rt = _SessionRuntime(
                registry=registry,
                client=mock_client,
                provider=mock_provider,
                permission_handler=mock_permission_handler,
                channel_id="C_NO_SUMMON",
                socket_handler=mock_socket_handler,
                channel_manager=mock_channel_manager,
            )

            session = SummonSession(
                config,
                make_options(session_id="sess-no-summon"),
                auth=make_auth(session_id="sess-no-summon"),
            )

            # Smoke test: registers handlers without raising (does NOT register /summon)
            session._register_event_handlers(new_app, rt)
