"""Schema bootstrap and migration tracking.

The schema version is tracked portably in the ``schema_meta`` table (authoritative),
with ``PRAGMA user_version`` kept as a best-effort native marker and read fallback:
remote SQLite protocols (Turso/Hrana) reject pragma *writes*, and databases created
before ``schema_meta`` existed carry their version only in the pragma.

``schema.sql`` is the **full latest shape** of the database: a fresh database is
created directly from it, and because every statement uses ``IF NOT EXISTS`` it also
creates any brand-new *tables* on an existing database.

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


def _read_version(conn: sqlite3.Connection) -> int:
    """The database's current schema version.

    The portable ``schema_meta`` table is authoritative; ``PRAGMA user_version`` is the
    fallback so databases stamped only natively (created before the table existed)
    still report their true version and don't re-run upgrade steps as if fresh.
    """
    try:
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        if row is not None:
            return int(row[0])
    except Exception:  # noqa: BLE001 - table absent; engines differ on the error type raised
        pass
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _write_version(conn: sqlite3.Connection, version: int) -> None:
    """Record the schema version portably (table) plus best-effort natively (PRAGMA).

    Remote SQLite protocols (Turso/Hrana) reject ``PRAGMA user_version = N`` writes
    ("SQL not allowed statement"), so the pragma is advisory only — the ``schema_meta``
    row is what :func:`_read_version` trusts first.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(version),),
    )
    try:
        conn.execute(f"PRAGMA user_version = {version}")
    except Exception:  # noqa: BLE001 - pragma writes disallowed over Hrana; the table wins
        logger.debug("PRAGMA user_version write unsupported by this engine; using schema_meta")


def bootstrap(conn: sqlite3.Connection) -> int:
    """Create/upgrade the schema if needed; return the resulting schema version."""
    current = _read_version(conn)
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
    _write_version(conn, SCHEMA_VERSION)
    conn.commit()
    return SCHEMA_VERSION
