"""Vercel serverless entrypoint for the MRDS HTTP API (the FastAPI ASGI app).

Vercel runs this as a serverless function. Two adaptations vs. running locally:

1. The package lives at the repo-root ``src/``; since the function executes from the
   repo root, we add ``src`` to ``sys.path`` and ``chdir`` there so the platform's
   relative paths (``datasets/``, ``config/settings.yaml``) resolve against the bundle.
2. The serverless filesystem is read-only except ``/tmp``. On cold start we copy the
   committed, pre-seeded demo database to ``/tmp`` (writable) and point the platform at
   it via ``MRDS_DATABASE_PATH`` — so reads, and a warm instance's baseline promotion,
   work. (Writes are per-instance and reset on a cold start; fine for a demo.)
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)

_TMP_DB = "/tmp/eval.db"
_SEED = _ROOT / "data" / "seed.db"
if _SEED.exists() and not os.path.exists(_TMP_DB):
    shutil.copy(_SEED, _TMP_DB)
os.environ.setdefault("MRDS_DATABASE_PATH", _TMP_DB)

from mrds.api.app import app  # noqa: E402  (import after sys.path + env setup)

__all__ = ["app"]
