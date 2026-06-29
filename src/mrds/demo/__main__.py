"""Seed the configured database with demo data: ``python -m mrds.demo``.

Useful for deploy pipelines / container builds that want to pre-seed the database
before launching the read-only dashboard.
"""

from __future__ import annotations

from mrds.config.settings import get_settings
from mrds.db import EvaluationStore, get_backend
from mrds.demo.seed import seed_demo
from mrds.observability.logging import configure_logging


def main() -> int:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)
    store = EvaluationStore(get_backend().connect())
    result = seed_demo(store)
    if result.seeded:
        print(f"Seeded {len(result.run_ids)} demo run(s); baseline={result.baseline_run_id}")
    else:
        print("Skipped: database already contains runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
