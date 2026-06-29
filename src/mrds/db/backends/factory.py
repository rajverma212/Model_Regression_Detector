"""Backend selection — build the configured :class:`StorageBackend` from settings.

This is the single place that maps configuration (``MRDS_STORAGE_BACKEND``) to a
concrete backend. Adding a backend in a later phase (e.g. libSQL/Turso) means
registering one branch here; no caller elsewhere in EvalOS changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mrds.db.backends.base import StorageBackend
from mrds.db.backends.sqlite import SqliteBackend
from mrds.db.errors import DbError

if TYPE_CHECKING:
    from mrds.config.settings import Settings


def create_backend(settings: Settings | None = None) -> StorageBackend:
    """Construct the backend named by ``settings.storage_backend``.

    Args:
        settings: Settings to read; defaults to the process settings. Injectable so
            tests can select a backend without touching the environment.

    Raises:
        DbError: if the configured backend name is not supported.
    """
    if settings is None:
        from mrds.config.settings import get_settings

        settings = get_settings()

    name = settings.storage_backend
    if name == "sqlite":
        return SqliteBackend(settings.database_path)
    raise DbError(f"unknown storage backend {name!r} (supported: 'sqlite')")


def get_backend() -> StorageBackend:
    """The :class:`StorageBackend` configured for the current process settings."""
    return create_backend()
