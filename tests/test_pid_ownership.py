"""Tests for PID ownership check in summon_claude.cli."""

from __future__ import annotations

import os
import sys

import pytest

from summon_claude.cli import _pid_owned_by_current_user


class TestPidOwnership:
    def test_own_pid_returns_true(self):
        """The current process PID is owned by the current user.

        This test requires psutil (optional dependency) or Linux /proc.
        On macOS without psutil, the function conservatively returns False.
        """
        try:
            import psutil

            # psutil is available — result must be True for own PID
            assert _pid_owned_by_current_user(os.getpid()) is True
        except ImportError:
            if sys.platform.startswith("linux"):
                # On Linux, /proc fallback should work
                assert _pid_owned_by_current_user(os.getpid()) is True
            else:
                # On macOS without psutil, function returns False (safe default)
                # Just verify it returns a bool without crashing
                result = _pid_owned_by_current_user(os.getpid())
                assert isinstance(result, bool)

    def test_nonexistent_pid_returns_false(self):
        """A PID that cannot possibly exist should return False."""
        # PID 99999999 is well beyond any realistic process table
        assert _pid_owned_by_current_user(99999999) is False

    def test_pid_1_returns_false_unless_root(self):
        """PID 1 (init/launchd) is owned by root, not the current user (unless running as root)."""
        if os.getuid() == 0:
            # If actually running as root, PID 1 is owned by us
            assert _pid_owned_by_current_user(1) is True
        else:
            # Normal case: PID 1 is owned by root, not current user
            assert _pid_owned_by_current_user(1) is False

    def test_returns_bool_type(self):
        """_pid_owned_by_current_user should return a bool, not just truthy/falsy."""
        result = _pid_owned_by_current_user(os.getpid())
        assert isinstance(result, bool)

        result_nonexistent = _pid_owned_by_current_user(99999999)
        assert isinstance(result_nonexistent, bool)
