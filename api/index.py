"""Vercel serverless entrypoint for the MRDS HTTP API (the FastAPI ASGI app).

Vercel runs this as a serverless function with a **read-only filesystem except** ``/tmp``.
Since the DB-only cutover, feature bundles (specs/prompts/datasets) live in the database,
not on disk — so the only writable state the API needs is the SQLite file. On cold start we
copy the committed, pre-seeded demo database (which already carries the built-in features'
bundle content) into ``/tmp`` and point the platform at it. Reads, feature activation, and a
warm instance's baseline promotion all work against that writable copy. Config
(``config/settings.yaml``) is read-only and served straight from the bundle.

Limitation (documented, not hidden): ``/tmp`` is **per-instance and ephemeral** — features
activated on one warm instance are lost on a cold start. Durable cloud onboarding requires a
persistent volume + external database; see ``docs/deploy-vercel.md``. On a normal long-lived
host none of this applies (the database is the configured ``data/eval.db``).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)  # so config/settings.yaml resolves against the bundle

# The serverless filesystem is read-only except /tmp: copy the pre-seeded demo database
# (which carries the built-in features' bundle content) to a writable location.
_TMP_DB = "/tmp/eval.db"
_SEED = _ROOT / "data" / "seed.db"
if _SEED.exists() and not os.path.exists(_TMP_DB):
    shutil.copy(_SEED, _TMP_DB)
os.environ.setdefault("MRDS_DATABASE_PATH", _TMP_DB)

from mrds.api.app import app  # noqa: E402  (import after sys.path + env setup)

__all__ = ["app"]
