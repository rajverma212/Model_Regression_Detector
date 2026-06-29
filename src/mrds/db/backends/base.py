"""Storage backend abstraction — the seam that decouples EvalOS from one engine.

A :class:`StorageBackend` is a connection factory: given configuration it opens a
connected, schema-bootstrapped :class:`~mrds.db.connection.Database` for a single
storage engine. SQLite is the only backend today; libSQL/Turso, a persistent
SQLite host, or PostgreSQL can be added later as additional implementations.

Everything above the persistence layer — the store, repositories, evaluation
engine, regression detector, reporting, dashboard, CLI, and HTTP API — depends
only on this interface and the :class:`Database` it returns, never on the engine
itself. Selecting a backend is therefore a **configuration** change (which backend
the factory builds), not a code change anywhere else in EvalOS.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mrds.db.connection import Database


class StorageBackend(ABC):
    """A configuration-selected provider of database connections for EvalOS."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier for the backend (e.g. ``"sqlite"``); used in logs."""

    @abstractmethod
    def connect(self, *, check_same_thread: bool = True) -> Database:
        """Open a connected, schema-bootstrapped :class:`Database`.

        Each call returns an independent connection that the caller **owns and must
        close**. ``check_same_thread`` is forwarded for engines (SQLite) that
        enforce connection thread-affinity; backends to which it does not apply may
        ignore it. The returned :class:`Database` is the single contract all
        backends honour, so callers never branch on which engine is in use.
        """
