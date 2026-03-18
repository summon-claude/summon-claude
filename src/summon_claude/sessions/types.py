"""Shared types for the sessions package."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileChange:
    """Record of a file change during a session."""

    path: str
    change_type: str  # "created" | "modified"
    additions: int
    deletions: int
    timestamp: datetime
    turn_number: int
