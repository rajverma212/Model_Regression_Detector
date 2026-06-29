"""CLI runtime — the dependency bundle the commands operate on.

Bundling the store, engine, detector, and reporter behind one object gives a
single dependency-injection seam: production builds it from real registries and
the configured database, while tests inject a runtime backed by fakes (no network,
in-memory database).
"""

from __future__ import annotations

from dataclasses import dataclass

from mrds.db import EvaluationStore, get_backend
from mrds.evaluation import EvaluationEngine
from mrds.observability.logging import get_logger
from mrds.regression import RegressionDetector
from mrds.reporting import ReportBuilder

logger = get_logger(__name__)


@dataclass
class CliRuntime:
    """The collaborators every CLI command needs."""

    store: EvaluationStore
    engine: EvaluationEngine
    detector: RegressionDetector
    reporter: ReportBuilder


def build_runtime() -> CliRuntime:
    """Construct the production runtime from real registries and the database."""
    # Importing the features package registers all built-in features so the
    # engine and dataset registry can resolve them by name.
    import mrds.features  # noqa: F401

    database = get_backend().connect()
    runtime = CliRuntime(
        store=EvaluationStore(database),
        engine=EvaluationEngine(),
        detector=RegressionDetector(),
        reporter=ReportBuilder(),
    )
    logger.debug("Built CLI runtime (db=%s)", database.path)
    return runtime
