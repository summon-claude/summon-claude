"""Tests for summon_claude.auth."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from summon_claude.auth import (
    SessionAuth,
    _generate_short_code,
    generate_session_token,
    verify_short_code,
)


class TestGenerateShortCode:
    def test_length_is_six(self):
        code = _generate_short_code()
        assert len(code) == 6

    def test_only_uppercase_alphanumeric(self):
        for _ in range(20):
            code = _generate_short_code()
            assert code.isalnum()
            assert code == code.upper()

    def test_codes_are_random(self):
        codes = {_generate_short_code() for _ in range(100)}
        # With a 36^6 = 2.1B search space, duplicates in 100 tries are astronomically unlikely
        assert len(codes) > 90


class TestGenerateSessionToken:
    async def test_returns_session_auth(self, registry):
        auth = await generate_session_token(registry, "sess-1", "/tmp")
        assert isinstance(auth, SessionAuth)

    async def test_token_is_urlsafe_string(self, registry):
        auth = await generate_session_token(registry, "sess-2", "/tmp")
        assert isinstance(auth.token, str)
        assert len(auth.token) > 20

    async def test_short_code_is_six_chars(self, registry):
        auth = await generate_session_token(registry, "sess-3", "/tmp")
        assert len(auth.short_code) == 6

    async def test_session_id_preserved(self, registry):
        auth = await generate_session_token(registry, "my-session-id", "/tmp")
        assert auth.session_id == "my-session-id"

    async def test_expires_in_five_minutes(self, registry):
        before = datetime.now(UTC)
        auth = await generate_session_token(registry, "sess-exp", "/tmp")
        after = datetime.now(UTC)
        # expires_at should be ~5 minutes from now
        min_expiry = before + timedelta(minutes=4, seconds=59)
        max_expiry = after + timedelta(minutes=5, seconds=1)
        assert min_expiry <= auth.expires_at <= max_expiry

    async def test_token_stored_in_registry(self, registry):
        auth = await generate_session_token(registry, "sess-stored", "/tmp")
        entry = await registry._get_pending_token(auth.short_code)
        assert entry is not None
        assert entry["session_id"] == "sess-stored"
        assert entry["token"] == auth.token


class TestVerifyShortCode:
    async def test_valid_code_returns_session_auth(self, registry):
        auth = await generate_session_token(registry, "sess-v", "/tmp")
        result = await verify_short_code(registry, auth.short_code)
        assert result is not None
        assert result.session_id == "sess-v"

    async def test_invalid_code_returns_none(self, registry):
        result = await verify_short_code(registry, "XXXXXX")
        assert result is None

    async def test_code_is_one_time_use(self, registry):
        auth = await generate_session_token(registry, "sess-otu", "/tmp")
        first = await verify_short_code(registry, auth.short_code)
        second = await verify_short_code(registry, auth.short_code)
        assert first is not None
        assert second is None

    async def test_expired_code_returns_none(self, registry):
        auth = await generate_session_token(registry, "sess-exp", "/tmp")
        # Manually overwrite expiry to the past
        past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        await registry.store_pending_token(
            short_code=auth.short_code,
            token=auth.token,
            session_id="sess-exp",
            cwd="/tmp",
            expires_at=past,
        )
        result = await verify_short_code(registry, auth.short_code)
        assert result is None

    async def test_expired_code_is_deleted(self, registry):
        auth = await generate_session_token(registry, "sess-del", "/tmp")
        past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        await registry.store_pending_token(
            short_code=auth.short_code,
            token=auth.token,
            session_id="sess-del",
            cwd="/tmp",
            expires_at=past,
        )
        await verify_short_code(registry, auth.short_code)
        # Should be gone from the registry
        entry = await registry._get_pending_token(auth.short_code)
        assert entry is None

    async def test_code_verification_is_case_insensitive(self, registry):
        auth = await generate_session_token(registry, "sess-case", "/tmp")
        lowercase = auth.short_code.lower()
        result = await verify_short_code(registry, lowercase)
        assert result is not None
        assert result.session_id == "sess-case"

    async def test_code_verification_trims_whitespace(self, registry):
        auth = await generate_session_token(registry, "sess-ws", "/tmp")
        padded = f"  {auth.short_code}  "
        result = await verify_short_code(registry, padded)
        assert result is not None
