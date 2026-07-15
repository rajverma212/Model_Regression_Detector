"""Storage backends — pluggable database engines behind one interface.

Import :class:`StorageBackend` to depend on the abstraction, :func:`get_backend`
to obtain the configured backend, or :class:`SqliteBackend` to construct one
explicitly (tests, tooling).
"""

from mrds.db.backends.base import StorageBackend
from mrds.db.backends.factory import create_backend, get_backend
from mrds.db.backends.libsql import LibsqlBackend
from mrds.db.backends.sqlite import SqliteBackend

__all__ = [
    "LibsqlBackend",
    "SqliteBackend",
    "StorageBackend",
    "create_backend",
    "get_backend",
]
