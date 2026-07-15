"""Vercel serverless entrypoint for the MRDS HTTP API (the FastAPI ASGI app).

Vercel runs this as a serverless function with a **read-only filesystem except** ``/tmp``.
Since the DB-only cutover, feature bundles (specs/prompts/datasets) live in the database,
so the only state the API needs is its database. Two modes, chosen by deployment env:

* **Durable (Turso)** — set ``MRDS_STORAGE_BACKEND=libsql`` + ``TURSO_DATABASE_URL`` (+
  ``TURSO_AUTH_TOKEN``) on the Vercel project. Every request opens a Turso embedded
  replica (local read replica under ``/tmp``, writes to the remote primary), so activated
  features, runs, and baselines **survive cold starts and are shared across instances**.
  On cold start, an empty primary is seeded once with the built-in bundles + demo
  narrative (idempotent — skipped whenever any runs exist).
* **Demo fallback (no env)** — copy the committed, pre-seeded ``data/seed.db`` (which
  already carries the built-in features' bundle content) to ``/tmp`` and use SQLite.
  Fully functional within a warm instance, but ephemeral: writes reset on a cold start.

Config (``config/settings.yaml``) is read-only and served straight from the bundle.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)  # so config/settings.yaml (and seed-source prompts/datasets) resolve

_TURSO = bool(os.environ.get("TURSO_DATABASE_URL"))

if _TURSO:
    # Durable mode: libSQL embedded replica of the remote Turso primary. The replica
    # file must live under /tmp (the only writable path on Vercel).
    os.environ.setdefault("MRDS_STORAGE_BACKEND", "libsql")
    os.environ.setdefault("MRDS_DATABASE_PATH", "/tmp/mrds-replica.db")
else:
    # Demo fallback: a per-instance writable copy of the committed, pre-seeded SQLite DB.
    _TMP_DB = "/tmp/eval.db"
    _SEED = _ROOT / "data" / "seed.db"
    if _SEED.exists() and not os.path.exists(_TMP_DB):
        shutil.copy(_SEED, _TMP_DB)
    os.environ.setdefault("MRDS_DATABASE_PATH", _TMP_DB)

from mrds.api.app import app  # noqa: E402  (import after sys.path + env setup)

if _TURSO:
    # One-time seed of an empty primary (built-in bundles + demo narrative) so the site
    # has content on first deploy. seed_demo is idempotent: it no-ops when runs exist.
    # Best-effort — a seeding hiccup must never take the API down.
    try:
        from mrds.db import EvaluationStore, get_backend
        from mrds.demo import seed_demo

        _db = get_backend().connect(check_same_thread=False)
        try:
            seed_demo(EvaluationStore(_db))
        finally:
            _db.close()
    except Exception:  # noqa: BLE001 - cold-start seeding is best-effort by design
        import logging

        logging.getLogger(__name__).warning("Turso cold-start seeding failed", exc_info=True)

__all__ = ["app"]
