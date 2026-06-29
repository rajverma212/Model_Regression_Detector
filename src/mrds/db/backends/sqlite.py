"""Filesystem-backed SQLite storage backend — the default (and, in Phase 1, only)
implementation of :class:`StorageBackend`.

This is the engine EvalOS has always used. The backend adds no behaviour; it simply
places the existing :func:`~mrds.db.connection.open_database` primitive behind the
:class:`StorageBackend` interface so other engines can be introduced later without
touching any caller.
"""

from __future__ import annotations

from pathlib import Path

from mrds.db.backends.base import StorageBackend
from mrds.db.connection import Database, open_database


class SqliteBackend(StorageBackend):
    """Opens a local SQLite database file (or an in-memory database for tests)."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        # ``None`` defers to ``settings.database_path`` at connect time (preserving
        # ``open_database``'s existing behaviour), so a configured default and
        # explicit/ephemeral overrides (e.g. ``":memory:"``) both keep working.
        self._database_path = database_path

    @property
    def name(self) -> str:
        return "sqlite"

    @property
    def database_path(self) -> str | Path | None:
        """The configured path, or ``None`` when deferring to settings."""
        return self._database_path

    def connect(self, *, check_same_thread: bool = True) -> Database:
        return open_database(self._database_path, check_same_thread=check_same_thread)
