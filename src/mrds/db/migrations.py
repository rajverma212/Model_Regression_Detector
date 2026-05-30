"""Schema bootstrap and migration tracking.

Migrations are tracked with SQLite's ``PRAGMA user_version``. The current schema
lives in ``schema.sql`` and is written with ``IF NOT EXISTS``, so bootstrap is
idempotent. New schema revisions bump :data:`SCHEMA_VERSION` and extend the SQL.
"""

from __future__ import annotations

import sqlite3
from importlib.resources import files

from mrds.observability.logging import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 1


def _schema_sql() -> str:
    return files("mrds.db").joinpath("schema.sql").read_text(encoding="utf-8")


def bootstrap(conn: sqlite3.Connection) -> int:
    """Create/upgrade the schema if needed; return the resulting schema version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= SCHEMA_VERSION:
        return current

    logger.info("Bootstrapping database schema %d -> %d", current, SCHEMA_VERSION)
    conn.executescript(_schema_sql())
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return SCHEMA_VERSION
