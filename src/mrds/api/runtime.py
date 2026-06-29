"""Per-request database session for the HTTP API.

A single :class:`sqlite3.Connection` is **not** safe to share across FastAPI's
threadpool: concurrent requests would race on the same connection/cursor. Instead
each request opens (and closes) its own lightweight session. SQLite connections are
cheap to open, and WAL mode lets many readers (plus the occasional baseline-promotion
writer) proceed without contention.

``check_same_thread=False`` only disables the thread-identity assertion; it is safe
here because a session is used by exactly one request, never two at once.
"""

from __future__ import annotations

from mrds.dashboard.data import DashboardData
from mrds.db.backends import StorageBackend, get_backend
from mrds.db.store import EvaluationStore


class ApiSession:
    """A request-scoped store + read-only data seam over one DB connection."""

    def __init__(self, backend: StorageBackend | None = None) -> None:
        # Open through the configured storage backend so the API never depends on a
        # specific engine; tests inject an explicit backend (e.g. SqliteBackend).
        self._db = (backend or get_backend()).connect(check_same_thread=False)
        self.store = EvaluationStore(self._db)
        self.data = DashboardData(self.store)

    def close(self) -> None:
        self._db.close()
