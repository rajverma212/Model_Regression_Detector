"""SQLite connection management.

Wraps a single :class:`sqlite3.Connection` with the pragmas the system relies on
(foreign keys on, row access by name) and a transaction context manager.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mrds.db.migrations import bootstrap as _bootstrap
from mrds.observability.logging import get_logger

logger = get_logger(__name__)

_IN_MEMORY = ":memory:"


class Database:
    """A thin, owning wrapper around one SQLite connection."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self._path != _IN_MEMORY:
            self._conn.execute("PRAGMA journal_mode = WAL")

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def path(self) -> str:
        return self._path

    def bootstrap(self) -> int:
        """Ensure the schema exists; return the schema version."""
        return _bootstrap(self._conn)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on error."""
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        self._conn.close()


def open_database(path: str | Path | None = None) -> Database:
    """Open (and bootstrap) the database.

    Args:
        path: Database path; defaults to ``settings.database_path``. Use
            ``":memory:"`` for an ephemeral database (tests).
    """
    if path is None:
        from mrds.config.settings import get_settings

        path = get_settings().database_path

    path_str = str(path)
    if path_str != _IN_MEMORY:
        Path(path_str).parent.mkdir(parents=True, exist_ok=True)

    db = Database(path_str)
    db.bootstrap()
    logger.info("Opened database at %s", path_str)
    return db
