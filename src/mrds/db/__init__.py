"""SQLite system-of-record persistence layer.

Feature-agnostic, repository-pattern storage for runs, test results, regressions,
baselines, and prompt/dataset versions. :class:`EvaluationStore` is the high-level
API; it integrates with the existing evaluation/regression models without changing
their public contracts.
"""

from mrds.db.backends import SqliteBackend, StorageBackend, create_backend, get_backend
from mrds.db.connection import Database, open_database
from mrds.db.errors import DbError
from mrds.db.records import (
    BaselineRecord,
    DatasetVersionRecord,
    FeatureSpecRecord,
    PromptVersionRecord,
    RegressionRecord,
    RunRecord,
    TestResultRecord,
)
from mrds.db.store import EvaluationStore

__all__ = [
    "BaselineRecord",
    "Database",
    "DatasetVersionRecord",
    "DbError",
    "EvaluationStore",
    "FeatureSpecRecord",
    "PromptVersionRecord",
    "RegressionRecord",
    "RunRecord",
    "SqliteBackend",
    "StorageBackend",
    "TestResultRecord",
    "create_backend",
    "get_backend",
    "open_database",
]
