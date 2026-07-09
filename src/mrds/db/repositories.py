"""Repository-pattern data access for each table.

Each repository wraps the shared connection and exposes typed CRUD for one table.
Repositories do not commit; the caller (typically :class:`EvaluationStore`) wraps
related writes in a single transaction.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

from mrds.db.connection import Database
from mrds.db.records import (
    BaselineRecord,
    DatasetVersionRecord,
    FeatureSpecRecord,
    PromptVersionRecord,
    RegressionRecord,
    RunRecord,
    TestResultRecord,
)
from mrds.evaluation.models import CaseResult
from mrds.regression.models import MetricComparison


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class FeatureSpecRepository:
    """Stores installed feature specifications, one row per feature.

    The spec is held opaquely as ``spec_json`` so this layer stays feature-agnostic
    (it never imports the spec model). Upsert-by-name: re-activating a feature updates
    its spec in place while preserving ``created_at``.
    """

    def __init__(self, db: Database) -> None:
        self._conn: sqlite3.Connection = db.connection

    def upsert(
        self,
        *,
        feature_name: str,
        content_hash: str,
        spec_json: str,
        segment_field: str | None = None,
        created_at: str | None = None,
    ) -> FeatureSpecRecord:
        now = created_at or _utcnow_iso()
        self._conn.execute(
            "INSERT INTO feature_specs(feature_name, content_hash, spec_json, segment_field, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(feature_name) DO UPDATE SET "
            "content_hash=excluded.content_hash, spec_json=excluded.spec_json, "
            "segment_field=excluded.segment_field, updated_at=excluded.updated_at",
            (feature_name, content_hash, spec_json, segment_field, now, now),
        )
        record = self.get(feature_name)
        assert record is not None  # just inserted or updated
        return record

    def get(self, feature_name: str) -> FeatureSpecRecord | None:
        row = self._conn.execute(
            "SELECT * FROM feature_specs WHERE feature_name = ?", (feature_name,)
        ).fetchone()
        return FeatureSpecRecord.model_validate(dict(row)) if row else None

    def list_all(self) -> list[FeatureSpecRecord]:
        rows = self._conn.execute("SELECT * FROM feature_specs ORDER BY feature_name").fetchall()
        return [FeatureSpecRecord.model_validate(dict(r)) for r in rows]


class PromptVersionRepository:
    """Append-only registry of prompt versions, keyed by content hash."""

    def __init__(self, db: Database) -> None:
        self._conn: sqlite3.Connection = db.connection

    def upsert(
        self,
        *,
        feature_name: str,
        version: str,
        content_hash: str,
        path: str = "",
        content: str = "",
        created_at: str | None = None,
    ) -> PromptVersionRecord:
        self._conn.execute(
            "INSERT INTO prompt_versions(feature_name, version, content_hash, path, content, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?) "
            # Identity (content_hash) is immutable, but backfill the content/path blob when a
            # later caller supplies it for a row first recorded (by save_evaluation) with none.
            "ON CONFLICT(content_hash) DO UPDATE SET content=excluded.content, path=excluded.path "
            "WHERE excluded.content <> '' "
            "AND (prompt_versions.content = '' OR prompt_versions.content IS NULL)",
            (feature_name, version, content_hash, path, content, created_at or _utcnow_iso()),
        )
        record = self.get_by_hash(content_hash)
        assert record is not None  # just inserted or already present
        return record

    def get_by_hash(self, content_hash: str) -> PromptVersionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM prompt_versions WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return PromptVersionRecord.model_validate(dict(row)) if row else None

    def get_by_id(self, version_id: int) -> PromptVersionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM prompt_versions WHERE id = ?", (version_id,)
        ).fetchone()
        return PromptVersionRecord.model_validate(dict(row)) if row else None

    def all(self) -> list[PromptVersionRecord]:
        """Every prompt version row, ordered by feature then version."""
        rows = self._conn.execute(
            "SELECT * FROM prompt_versions ORDER BY feature_name, version"
        ).fetchall()
        return [PromptVersionRecord.model_validate(dict(r)) for r in rows]


class DatasetVersionRepository:
    """Append-only registry of dataset versions, keyed by content hash."""

    def __init__(self, db: Database) -> None:
        self._conn: sqlite3.Connection = db.connection

    def upsert(
        self,
        *,
        feature_name: str,
        version: str,
        content_hash: str,
        case_count: int = 0,
        path: str = "",
        content: str = "",
        created_at: str | None = None,
    ) -> DatasetVersionRecord:
        self._conn.execute(
            "INSERT INTO dataset_versions(feature_name, version, content_hash, path, "
            "case_count, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            # Identity (content_hash) is immutable, but backfill the content/path blob when a
            # later caller supplies it for a row first recorded (by save_evaluation) with none.
            "ON CONFLICT(content_hash) DO UPDATE SET content=excluded.content, path=excluded.path "
            "WHERE excluded.content <> '' "
            "AND (dataset_versions.content = '' OR dataset_versions.content IS NULL)",
            (
                feature_name,
                version,
                content_hash,
                path,
                case_count,
                content,
                created_at or _utcnow_iso(),
            ),
        )
        record = self.get_by_hash(content_hash)
        assert record is not None
        return record

    def get_by_hash(self, content_hash: str) -> DatasetVersionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM dataset_versions WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return DatasetVersionRecord.model_validate(dict(row)) if row else None

    def get_by_id(self, version_id: int) -> DatasetVersionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM dataset_versions WHERE id = ?", (version_id,)
        ).fetchone()
        return DatasetVersionRecord.model_validate(dict(row)) if row else None

    def all(self) -> list[DatasetVersionRecord]:
        """Every dataset version row, ordered by feature then version."""
        rows = self._conn.execute(
            "SELECT * FROM dataset_versions ORDER BY feature_name, version"
        ).fetchall()
        return [DatasetVersionRecord.model_validate(dict(r)) for r in rows]


class RunRepository:
    """Access to the ``runs`` table."""

    def __init__(self, db: Database) -> None:
        self._conn: sqlite3.Connection = db.connection

    def insert(
        self,
        *,
        run_uuid: str,
        feature_name: str,
        prompt_version_id: int | None,
        dataset_version_id: int | None,
        model: str,
        judge_enabled: bool,
        status: str,
        git_sha: str | None,
        triggered_by: str,
        started_at: str,
        finished_at: str,
        duration_seconds: float,
        total_tokens: int,
        total_cost_usd: float,
        metrics_json: str,
    ) -> RunRecord:
        cursor = self._conn.execute(
            "INSERT INTO runs(run_uuid, feature_name, prompt_version_id, dataset_version_id, "
            "model, judge_enabled, status, git_sha, triggered_by, started_at, finished_at, "
            "duration_seconds, total_tokens, total_cost_usd, metrics_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_uuid,
                feature_name,
                prompt_version_id,
                dataset_version_id,
                model,
                int(judge_enabled),
                status,
                git_sha,
                triggered_by,
                started_at,
                finished_at,
                duration_seconds,
                total_tokens,
                total_cost_usd,
                metrics_json,
            ),
        )
        record = self.get_by_id(int(cursor.lastrowid))
        assert record is not None
        return record

    def get_by_id(self, run_id: int) -> RunRecord | None:
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return RunRecord.model_validate(dict(row)) if row else None

    def get_by_uuid(self, run_uuid: str) -> RunRecord | None:
        row = self._conn.execute("SELECT * FROM runs WHERE run_uuid = ?", (run_uuid,)).fetchone()
        return RunRecord.model_validate(dict(row)) if row else None

    def latest_uuid(self, feature_name: str) -> str | None:
        row = self._conn.execute(
            "SELECT run_uuid FROM runs WHERE feature_name = ? ORDER BY id DESC LIMIT 1",
            (feature_name,),
        ).fetchone()
        return row["run_uuid"] if row else None

    def list_for_feature(self, feature_name: str, *, limit: int = 50) -> list[RunRecord]:
        rows = self._conn.execute(
            "SELECT * FROM runs WHERE feature_name = ? ORDER BY id DESC LIMIT ?",
            (feature_name, limit),
        ).fetchall()
        return [RunRecord.model_validate(dict(r)) for r in rows]

    def features(self) -> list[str]:
        """Return the distinct feature names that have at least one run."""
        rows = self._conn.execute(
            "SELECT DISTINCT feature_name FROM runs ORDER BY feature_name"
        ).fetchall()
        return [r["feature_name"] for r in rows]


class TestResultRepository:
    """Access to the ``test_results`` table."""

    def __init__(self, db: Database) -> None:
        self._conn: sqlite3.Connection = db.connection

    def bulk_insert(self, run_id: int, cases: Sequence[CaseResult]) -> int:
        rows = [
            (
                run_id,
                case.case_id,
                case.expected_difficulty.value,
                json.dumps(case.input),
                json.dumps(case.expected_output),
                json.dumps(case.actual_output) if case.actual_output is not None else None,
                int(case.passed),
                json.dumps([s.model_dump() for s in case.scores]),
                case.latency_ms,
                case.input_tokens,
                case.output_tokens,
                case.total_tokens,
                case.error,
            )
            for case in cases
        ]
        self._conn.executemany(
            "INSERT INTO test_results(run_id, case_id, expected_difficulty, input_json, "
            "expected_json, actual_json, passed, scores_json, latency_ms, input_tokens, "
            "output_tokens, total_tokens, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        return len(rows)

    def list_for_run(self, run_id: int) -> list[TestResultRecord]:
        rows = self._conn.execute(
            "SELECT * FROM test_results WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return [TestResultRecord.model_validate(dict(r)) for r in rows]


class BaselineRepository:
    """Access to the ``baselines`` table (one active baseline per feature)."""

    def __init__(self, db: Database) -> None:
        self._conn: sqlite3.Connection = db.connection

    def set_active(
        self, *, feature_name: str, run_id: int, promoted_by: str, note: str = ""
    ) -> BaselineRecord:
        self._conn.execute(
            "UPDATE baselines SET is_active = 0 WHERE feature_name = ? AND is_active = 1",
            (feature_name,),
        )
        cursor = self._conn.execute(
            "INSERT INTO baselines(feature_name, run_id, is_active, promoted_by, promoted_at, "
            "note) VALUES (?, ?, 1, ?, ?, ?)",
            (feature_name, run_id, promoted_by, _utcnow_iso(), note),
        )
        record = self.get_by_id(int(cursor.lastrowid))
        assert record is not None
        return record

    def get_active(self, feature_name: str) -> BaselineRecord | None:
        row = self._conn.execute(
            "SELECT * FROM baselines WHERE feature_name = ? AND is_active = 1", (feature_name,)
        ).fetchone()
        return BaselineRecord.model_validate(dict(row)) if row else None

    def get_by_id(self, baseline_id: int) -> BaselineRecord | None:
        row = self._conn.execute("SELECT * FROM baselines WHERE id = ?", (baseline_id,)).fetchone()
        return BaselineRecord.model_validate(dict(row)) if row else None

    def history(self, feature_name: str) -> list[BaselineRecord]:
        rows = self._conn.execute(
            "SELECT * FROM baselines WHERE feature_name = ? ORDER BY id DESC", (feature_name,)
        ).fetchall()
        return [BaselineRecord.model_validate(dict(r)) for r in rows]


class RegressionRepository:
    """Access to the ``regressions`` table."""

    def __init__(self, db: Database) -> None:
        self._conn: sqlite3.Connection = db.connection

    def insert_many(
        self,
        *,
        run_id: int,
        baseline_run_id: int,
        comparisons: Sequence[MetricComparison],
    ) -> list[RegressionRecord]:
        detected_at = _utcnow_iso()
        ids: list[int] = []
        for comparison in comparisons:
            cursor = self._conn.execute(
                "INSERT INTO regressions(run_id, baseline_run_id, metric, baseline_value, "
                "candidate_value, delta, severity, detected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    baseline_run_id,
                    comparison.name,
                    comparison.baseline_value,
                    comparison.candidate_value,
                    comparison.delta,
                    comparison.severity.value,
                    detected_at,
                ),
            )
            ids.append(int(cursor.lastrowid))
        return [r for r in (self.get_by_id(i) for i in ids) if r is not None]

    def get_by_id(self, regression_id: int) -> RegressionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM regressions WHERE id = ?", (regression_id,)
        ).fetchone()
        return RegressionRecord.model_validate(dict(row)) if row else None

    def list_for_run(self, run_id: int) -> list[RegressionRecord]:
        rows = self._conn.execute(
            "SELECT * FROM regressions WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return [RegressionRecord.model_validate(dict(r)) for r in rows]
