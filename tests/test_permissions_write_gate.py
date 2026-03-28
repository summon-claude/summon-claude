"""Tests for write gate — safe-dir validation and worktree gating."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from helpers import make_mock_slack_client
from summon_claude.config import SummonConfig
from summon_claude.sessions.permissions import (
    _AUTO_APPROVE_TOOLS,
    _WRITE_GATED_TOOLS,
    PermissionHandler,
    _is_in_safe_dir,
)
from summon_claude.slack.router import ThreadRouter


def _make_config(safe_write_dirs: str = "", debounce_ms: int = 10):
    return SummonConfig.model_validate(
        {
            "slack_bot_token": "xoxb-t",
            "slack_app_token": "xapp-t",
            "slack_signing_secret": "abcdef",
            "permission_debounce_ms": debounce_ms,
            "safe_write_dirs": safe_write_dirs,
        }
    )


def _make_handler(
    safe_write_dirs: str = "",
    project_root: str = "/project",
):
    client = make_mock_slack_client()
    router = ThreadRouter(client)
    config = _make_config(safe_write_dirs=safe_write_dirs)
    handler = PermissionHandler(
        router,
        config,
        authenticated_user_id="U_TEST",
        project_root=project_root,
    )
    return handler, client


class TestIsSafeDir:
    """Unit tests for _is_in_safe_dir path validation."""

    def test_file_inside_safe_dir(self, tmp_path: Path):
        safe = tmp_path / "hack"
        safe.mkdir()
        target = safe / "notes.md"
        target.touch()
        assert _is_in_safe_dir(str(target), ["hack/"], tmp_path) is True

    def test_file_outside_safe_dir(self, tmp_path: Path):
        (tmp_path / "hack").mkdir()
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.touch()
        assert _is_in_safe_dir(str(target), ["hack/"], tmp_path) is False

    def test_empty_safe_dirs_returns_false(self, tmp_path: Path):
        target = tmp_path / "anything.txt"
        target.touch()
        assert _is_in_safe_dir(str(target), [], tmp_path) is False

    def test_none_project_root_returns_false(self):
        assert _is_in_safe_dir("/some/file.py", ["hack/"], None) is False

    def test_relative_project_root_returns_false(self):
        assert _is_in_safe_dir("/some/file.py", ["hack/"], Path("relative")) is False

    def test_empty_project_root_returns_false(self):
        assert _is_in_safe_dir("/some/file.py", ["hack/"], Path()) is False

    def test_dotdot_traversal_blocked(self, tmp_path: Path):
        safe = tmp_path / "hack"
        safe.mkdir()
        # ../src/main.py should NOT be in hack/ even though it starts with ../
        assert _is_in_safe_dir(str(safe / ".." / "src" / "main.py"), ["hack/"], tmp_path) is False

    def test_symlink_resolved(self, tmp_path: Path):
        real_dir = tmp_path / "real_safe"
        real_dir.mkdir()
        target = real_dir / "notes.md"
        target.touch()
        link = tmp_path / "link_safe"
        link.symlink_to(real_dir)
        # File accessed via symlink should resolve to the real dir
        assert _is_in_safe_dir(str(link / "notes.md"), ["real_safe/"], tmp_path) is True

    def test_multiple_safe_dirs(self, tmp_path: Path):
        (tmp_path / "hack").mkdir()
        (tmp_path / ".dev").mkdir()
        target = tmp_path / ".dev" / "scratch.py"
        target.touch()
        assert _is_in_safe_dir(str(target), ["hack/", ".dev/"], tmp_path) is True

    def test_relative_file_path_resolved_against_project_root(self, tmp_path: Path):
        safe = tmp_path / "hack"
        safe.mkdir()
        target = safe / "notes.md"
        target.touch()
        # Relative path should be resolved against project_root
        assert _is_in_safe_dir("hack/notes.md", ["hack/"], tmp_path) is True

    def test_absolute_file_path_works(self, tmp_path: Path):
        safe = tmp_path / "hack"
        safe.mkdir()
        target = safe / "notes.md"
        target.touch()
        assert _is_in_safe_dir(str(target), ["hack/"], tmp_path) is True


class TestWriteGateGuards:
    """Pin constants for the write gate."""

    def test_write_gated_tools_pinned(self):
        assert (
            frozenset(
                {
                    "Write",
                    "Edit",
                    "MultiEdit",
                    "NotebookEdit",
                    "Bash",
                }
            )
            == _WRITE_GATED_TOOLS
        )

    def test_write_gated_and_auto_approve_disjoint(self):
        """SEC-008: no tool should be both write-gated and auto-approved."""
        overlap = _WRITE_GATED_TOOLS & _AUTO_APPROVE_TOOLS
        assert not overlap, f"Overlap: {overlap}"


class TestWriteGateBehavior:
    """Tests for the write gate in PermissionHandler.handle()."""

    async def test_write_denied_not_in_worktree(self):
        handler, _ = _make_handler()
        result = await handler.handle("Write", {"file_path": "/f"}, None)
        assert isinstance(result, PermissionResultDeny)
        assert "worktree" in result.message.lower()

    async def test_bash_denied_not_in_worktree(self):
        handler, _ = _make_handler()
        result = await handler.handle("Bash", {"command": "ls"}, None)
        assert isinstance(result, PermissionResultDeny)
        assert "worktree" in result.message.lower()

    async def test_read_not_gated(self):
        handler, _ = _make_handler()
        result = await handler.handle("Read", {"file_path": "/f"}, None)
        assert isinstance(result, PermissionResultAllow)

    async def test_notify_worktree_sets_flag(self):
        handler, _ = _make_handler()
        assert not handler._in_worktree
        handler.notify_entered_worktree()
        assert handler._in_worktree

    async def test_write_after_worktree_prompts_once(self):
        handler, client = _make_handler()
        handler.notify_entered_worktree()
        # Mock post_interactive to auto-approve
        from tests.test_sessions_permissions import _interactive_auto_approve

        client.post_interactive = AsyncMock(side_effect=_interactive_auto_approve(handler))
        result = await handler.handle("Write", {"file_path": "/f"}, None)
        assert isinstance(result, PermissionResultAllow)
        assert handler._write_access_granted

    async def test_subsequent_write_auto_approved(self):
        handler, _ = _make_handler()
        handler._write_access_granted = True
        result = await handler.handle("Write", {"file_path": "/f"}, None)
        assert isinstance(result, PermissionResultAllow)

    async def test_bash_not_session_cached_after_gate(self):
        handler, _ = _make_handler()
        handler._write_access_granted = True
        # Bash should NOT be in session cache
        assert "Bash" not in handler._session_approved_tools

    async def test_write_tools_session_cached_after_gate(self):
        handler, _ = _make_handler()
        handler.notify_entered_worktree()
        from tests.test_sessions_permissions import _interactive_auto_approve

        client = handler._router.client
        client.post_interactive = AsyncMock(side_effect=_interactive_auto_approve(handler))
        await handler.handle("Write", {"file_path": "/f"}, None)
        # Write/Edit/MultiEdit/NotebookEdit should be cached, Bash should not
        assert "Write" in handler._session_approved_tools
        assert "Bash" not in handler._session_approved_tools

    async def test_safe_dir_write_auto_approved_e2e(self, tmp_path: Path):
        """QA-003: end-to-end test for safe-dir write through handle()."""
        safe = tmp_path / "hack"
        safe.mkdir()
        target = safe / "notes.md"
        target.touch()
        handler, client = _make_handler(
            safe_write_dirs="hack/",
            project_root=str(tmp_path),
        )
        result = await handler.handle("Write", {"file_path": str(target)}, None)
        assert isinstance(result, PermissionResultAllow)
        # Should NOT reach HITL
        client.post_interactive.assert_not_called()

    async def test_safe_dir_write_outside_dir_denied(self, tmp_path: Path):
        """Write outside safe-dir should be denied when not in worktree."""
        (tmp_path / "hack").mkdir()
        handler, _ = _make_handler(
            safe_write_dirs="hack/",
            project_root=str(tmp_path),
        )
        result = await handler.handle(
            "Write", {"file_path": str(tmp_path / "src" / "main.py")}, None
        )
        assert isinstance(result, PermissionResultDeny)
