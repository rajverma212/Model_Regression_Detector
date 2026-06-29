"""Production entrypoint for running the MRDS API on a persistent-disk host.

Unlike the Vercel serverless entrypoint (``api/index.py``), which rebuilds a
throwaway working root under ``/tmp`` on every cold start, this script targets a
host that gives the process a **durable mounted disk** (Render/Railway/Fly). It
seeds that disk *once* from the committed read-only assets and then keeps using
it, so features activated through the web UI — and every run, baseline, and
bundle they produce — survive restarts and redeploys.

Because a mounted disk attaches to a single instance, there is also exactly one
copy of the SQLite database and one platform root: no per-instance split-brain
(the failure that made online-activated features 404 on Vercel).

Configuration (all overridable via environment):

* ``MRDS_PLATFORM_ROOT`` — the durable disk mount; defaults to ``/data``. The
  committed ``config``/``prompts``/``datasets``/``specs`` dirs are copied here if
  absent, and new feature bundles are installed here.
* ``MRDS_DATABASE_PATH`` — defaults to ``<root>/eval.db``, seeded from the
  committed ``data/seed.db`` on first boot.
* ``PORT`` (host-provided) or ``MRDS_API_PORT`` — the port to bind; host is
  forced to ``0.0.0.0`` so the platform router can reach it.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# Committed assets that the platform reads (and, for new features, writes beside).
_ASSET_DIRS = ("config", "prompts", "datasets", "specs")


def _seed_disk(root: Path) -> Path:
    """Populate the durable ``root`` from committed assets on first boot only.

    Idempotent: each asset dir and the database are copied only when missing, so
    anything written on a previous boot (newly activated features, promotions,
    runs) is preserved. Returns the resolved database path.
    """
    root.mkdir(parents=True, exist_ok=True)
    for sub in _ASSET_DIRS:
        src = _REPO / sub
        dst = root / sub
        if src.is_dir() and not dst.exists():
            shutil.copytree(src, dst)

    db_path = Path(os.environ.get("MRDS_DATABASE_PATH", str(root / "eval.db")))
    seed = _REPO / "data" / "seed.db"
    if seed.exists() and not db_path.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(seed, db_path)
    return db_path


def main() -> int:
    import uvicorn

    root = Path(os.environ.get("MRDS_PLATFORM_ROOT", "/data"))
    db_path = _seed_disk(root)

    # Point the platform at the durable root for both reads and activation writes.
    os.environ.setdefault("MRDS_PLATFORM_ROOT", str(root))
    os.environ.setdefault("MRDS_DATABASE_PATH", str(db_path))
    # chdir so any CWD-relative access also resolves onto the disk (matches the
    # Vercel entrypoint's behaviour on the serverless side).
    os.chdir(root)

    port = int(os.environ.get("PORT") or os.environ.get("MRDS_API_PORT") or "8000")
    uvicorn.run("mrds.api.app:app", host="0.0.0.0", port=port, reload=False)  # noqa: S104
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
