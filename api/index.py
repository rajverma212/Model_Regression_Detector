"""Vercel serverless entrypoint for the MRDS HTTP API (the FastAPI ASGI app).

Vercel runs this as a serverless function with a **read-only filesystem except** ``/tmp``.
The platform reads *and writes* relative directories (``config/``, ``prompts/``,
``datasets/``, ``specs/``) and a SQLite DB: reads for existing features, writes when a new
feature is activated from the web UI. To make the full Create→Activate→Mission-Control
lifecycle work in this environment, on cold start we assemble a single **writable working
root** under ``/tmp``:

* copy the committed, read-only assets (``config``/``prompts``/``datasets``/``specs``) into it,
* seed the demo database from the committed ``data/seed.db``,
* ``chdir`` into it and point ``MRDS_PLATFORM_ROOT`` / ``MRDS_DATABASE_PATH`` at it.

The platform then has one consistent, writable root for both reads and activation writes.

Limitation (documented, not hidden): ``/tmp`` is **per-instance and ephemeral** — features
activated on one warm instance are lost on a cold start. Durable cloud onboarding requires a
persistent volume + external database; see ``docs/deploy-vercel.md``. On a normal long-lived
host none of this applies (``platform_root`` defaults to the working directory).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

# A single writable working root (the serverless FS is read-only except /tmp).
_WORK = Path(os.environ.get("MRDS_WORK_DIR", "/tmp/mrds"))
_WORK.mkdir(parents=True, exist_ok=True)

# Seed committed, read-only assets into the writable root so the platform can both read
# existing features and write newly activated ones under one consistent root. ``specs`` may
# not exist in the repo (no installed specs committed); install_bundle creates it on demand.
for sub in ("config", "prompts", "datasets", "specs"):
    src = _ROOT / sub
    dst = _WORK / sub
    if src.is_dir() and not dst.exists():
        shutil.copytree(src, dst)

# Seed a writable copy of the pre-built demo database.
_db = _WORK / "eval.db"
_seed = _ROOT / "data" / "seed.db"
if _seed.exists() and not _db.exists():
    shutil.copy(_seed, _db)

os.chdir(_WORK)
os.environ.setdefault("MRDS_DATABASE_PATH", str(_db))
os.environ.setdefault("MRDS_PLATFORM_ROOT", str(_WORK))

from mrds.api.app import app  # noqa: E402  (import after sys.path + env setup)

__all__ = ["app"]
