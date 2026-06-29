"""Unit tests for the storage backend abstraction (Phase 1).

Verify that the seam works without callers knowing the engine: the SQLite backend
opens a bootstrapped, usable database, and the factory selects backends purely from
configuration (raising clearly on an unknown backend).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mrds.config.settings import get_settings
from mrds.db import (
    Database,
    DbError,
    EvaluationStore,
    SqliteBackend,
    StorageBackend,
    create_backend,
    get_backend,
)


def test_sqlite_backend_connects_and_bootstraps() -> None:
    """connect() returns an owned, schema-bootstrapped Database."""
    backend = SqliteBackend(":memory:")
    assert backend.name == "sqlite"
    db = backend.connect()
    try:
        assert isinstance(db, Database)
        # Bootstrapped schema means the store can be used immediately.
        store = EvaluationStore(db)
        assert store.runs.features() == []
    finally:
        db.close()


def test_sqlite_backend_is_a_storage_backend() -> None:
    """The concrete backend satisfies the abstraction callers depend on."""
    assert isinstance(SqliteBackend(":memory:"), StorageBackend)


def test_connect_returns_independent_connections(tmp_path) -> None:
    """Each connect() call yields a separate connection the caller owns."""
    backend = SqliteBackend(tmp_path / "eval.db")
    a = backend.connect()
    b = backend.connect()
    try:
        assert a is not b
        assert a.connection is not b.connection
    finally:
        a.close()
        b.close()


def test_create_backend_selects_sqlite_from_settings() -> None:
    """The factory builds the backend named by settings, wired to its path."""
    settings = SimpleNamespace(storage_backend="sqlite", database_path=":memory:")
    backend = create_backend(settings)  # type: ignore[arg-type]  # duck-typed stub
    assert isinstance(backend, SqliteBackend)
    assert backend.database_path == ":memory:"


def test_create_backend_rejects_unknown_backend() -> None:
    """An unsupported backend name fails fast with a clear error."""
    settings = SimpleNamespace(storage_backend="bogus", database_path=":memory:")
    with pytest.raises(DbError, match="unknown storage backend"):
        create_backend(settings)  # type: ignore[arg-type]  # duck-typed stub


def test_get_backend_uses_process_settings() -> None:
    """The default accessor honours the process settings (sqlite by default)."""
    backend = get_backend()
    assert isinstance(backend, SqliteBackend)
    assert get_settings().storage_backend == "sqlite"
