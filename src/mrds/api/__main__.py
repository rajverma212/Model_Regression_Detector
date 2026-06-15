"""Run the API server: ``python -m mrds.api`` (or the ``mrds-api`` script).

Binds to ``127.0.0.1:8000`` by default; override host/port with ``MRDS_API_HOST`` /
``MRDS_API_PORT``. The frontend dev server proxies to this origin.
"""

from __future__ import annotations

import os


def main() -> int:
    import uvicorn

    host = os.environ.get("MRDS_API_HOST", "127.0.0.1")
    port = int(os.environ.get("MRDS_API_PORT", "8000"))
    uvicorn.run("mrds.api.app:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
