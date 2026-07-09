"""CLI runtime — the dependency bundle the commands operate on.

Bundling the store, engine, detector, and reporter behind one object gives a
single dependency-injection seam: production builds it from real registries and
the configured database, while tests inject a runtime backed by fakes (no network,
in-memory database).
"""

from __future__ import annotations

from dataclasses import dataclass

from mrds.activation.bootstrap import bootstrap_platform
from mrds.activation.discovery import load_datasets_from_store, load_prompts_from_store
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
    """Construct the production runtime from the database (the system of record).

    Registers every feature (built-in + DB-activated) and seeds built-in bundle content,
    then builds the engine from **store-backed** prompt/dataset registries — the filesystem
    is no longer a runtime resolution path.
    """
    database = get_backend().connect()
    store = EvaluationStore(database)
    bootstrap_platform(store)
    runtime = CliRuntime(
        store=store,
        engine=EvaluationEngine(
            prompts=load_prompts_from_store(store),
            datasets=load_datasets_from_store(store),
        ),
        detector=RegressionDetector(),
        reporter=ReportBuilder(),
    )
    logger.debug("Built CLI runtime (db=%s)", database.path)
    return runtime
