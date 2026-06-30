"""Schema bootstrap and migration tracking.

Migrations are tracked with SQLite's ``PRAGMA user_version``. ``schema.sql`` is the
**full latest shape** of the database: a fresh database is created directly from it,
and because every statement uses ``IF NOT EXISTS`` it also creates any brand-new
*tables* on an existing database.

What ``schema.sql`` cannot do on an existing database is alter an *existing* table
(e.g. add a column). Those changes are expressed as ordered, incremental steps in
:data:`_MIGRATIONS`, each keyed by the schema version it reaches. On upgrade, every
step newer than the database's current version is applied. A fresh database (version
0) already has the latest shape from ``schema.sql``, so no steps run.

History:
* v2 — ``feature_specs`` table (new table; handled by ``schema.sql``, no step).
* v3 — ``prompt_versions.content`` column (prompt bodies move into the DB).
* v4 — ``dataset_versions.content`` column (dataset cases move into the DB).
"""

from __future__ import annotations

import sqlite3
from importlib.resources import files

from mrds.observability.logging import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 4

#: Incremental upgrade steps for *existing* databases, keyed by the version reached.
#: Only changes to existing tables need a step; new tables come from ``schema.sql``.
_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (3, "ALTER TABLE prompt_versions ADD COLUMN content TEXT NOT NULL DEFAULT '';"),
    (4, "ALTER TABLE dataset_versions ADD COLUMN content TEXT NOT NULL DEFAULT '';"),
)


def _schema_sql() -> str:
    return files("mrds.db").joinpath("schema.sql").read_text(encoding="utf-8")


def bootstrap(conn: sqlite3.Connection) -> int:
    """Create/upgrade the schema if needed; return the resulting schema version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= SCHEMA_VERSION:
        return current

    logger.info("Bootstrapping database schema %d -> %d", current, SCHEMA_VERSION)
    # Always ensure all tables exist (also creates brand-new tables on existing DBs).
    conn.executescript(_schema_sql())
    # Apply incremental table changes for upgrades from a populated, older schema.
    # A fresh database (version 0) already has the latest shape from schema.sql.
    if current > 0:
        for version, statement in _MIGRATIONS:
            if current < version:
                conn.executescript(statement)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return SCHEMA_VERSION
