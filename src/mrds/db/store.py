"""High-level persistence facade.

:class:`EvaluationStore` orchestrates the repositories to persist and reconstruct
domain objects. It integrates with the existing :class:`EvaluationResult` and
:class:`RegressionResult` models **without modifying their public contracts** —
runs are stored as rows + a metrics JSON snapshot, and per-case results round-trip
through their JSON payloads. This is the layer the CLI commands will call.
"""

from __future__ import annotations

import json
from datetime import datetime

from mrds.core.interfaces import ScoreResult
from mrds.datasets.models import Difficulty
from mrds.db.connection import Database
from mrds.db.errors import DbError
from mrds.db.records import BaselineRecord, RegressionRecord, RunRecord, TestResultRecord
from mrds.db.repositories import (
    BaselineRepository,
    DatasetVersionRepository,
    FeatureSpecRepository,
    PromptVersionRepository,
    RegressionRepository,
    RunRepository,
    TestResultRepository,
)
from mrds.evaluation.models import AggregateMetrics, CaseResult, EvaluationResult
from mrds.observability.logging import get_logger
from mrds.regression.models import RegressionResult

logger = get_logger(__name__)


class EvaluationStore:
    """The system-of-record API used by the rest of the platform."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self.feature_specs = FeatureSpecRepository(db)
        self.prompt_versions = PromptVersionRepository(db)
        self.dataset_versions = DatasetVersionRepository(db)
        self.runs = RunRepository(db)
        self.test_results = TestResultRepository(db)
        self.baselines = BaselineRepository(db)
        self.regressions = RegressionRepository(db)

    # -- writes -----------------------------------------------------------------

    def save_evaluation(
        self,
        result: EvaluationResult,
        *,
        status: str = "completed",
        triggered_by: str = "local",
        git_sha: str | None = None,
        judge_enabled: bool = False,
    ) -> RunRecord:
        """Persist a run, its versions, and its per-case results atomically."""
        agg = result.aggregate_metrics
        with self._db.transaction():
            prompt = self.prompt_versions.upsert(
                feature_name=result.feature,
                version=result.prompt_version,
                content_hash=result.prompt_hash,
            )
            dataset = self.dataset_versions.upsert(
                feature_name=result.feature,
                version=result.dataset_version,
                content_hash=result.dataset_hash,
                case_count=agg.total_cases,
            )
            run = self.runs.insert(
                run_uuid=result.run_id,
                feature_name=result.feature,
                prompt_version_id=prompt.id,
                dataset_version_id=dataset.id,
                model=result.model,
                judge_enabled=judge_enabled,
                status=status,
                git_sha=git_sha,
                triggered_by=triggered_by,
                started_at=result.start_time.isoformat(),
                finished_at=result.end_time.isoformat(),
                duration_seconds=result.duration_seconds,
                total_tokens=agg.tokens.total_tokens,
                total_cost_usd=0.0,
                metrics_json=agg.model_dump_json(),
            )
            self.test_results.bulk_insert(run.id, result.per_case_results)

        logger.info(
            "Persisted run %s (%d cases) for %s",
            result.run_id,
            len(result.per_case_results),
            result.feature,
        )
        return run

    def save_regression(self, regression: RegressionResult) -> list[RegressionRecord]:
        """Persist the regressed metrics of a comparison. Both runs must exist."""
        candidate = self.runs.get_by_uuid(regression.candidate_run_id)
        baseline = self.runs.get_by_uuid(regression.baseline_run_id)
        if candidate is None or baseline is None:
            raise DbError(
                "Both candidate and baseline runs must be persisted before saving regressions"
            )
        with self._db.transaction():
            return self.regressions.insert_many(
                run_id=candidate.id,
                baseline_run_id=baseline.id,
                comparisons=regression.regressions,
            )

    def promote_baseline(
        self, run_uuid: str, *, promoted_by: str = "manual", note: str = ""
    ) -> BaselineRecord:
        """Promote a persisted run to the active baseline for its feature."""
        run = self.runs.get_by_uuid(run_uuid)
        if run is None:
            raise DbError(f"Cannot promote unknown run '{run_uuid}'")
        with self._db.transaction():
            return self.baselines.set_active(
                feature_name=run.feature_name,
                run_id=run.id,
                promoted_by=promoted_by,
                note=note,
            )

    # -- reads / reconstruction -------------------------------------------------

    def latest_run_uuid(self, feature: str) -> str | None:
        """Return the most recently persisted run id for a feature."""
        return self.runs.latest_uuid(feature)

    def get_evaluation_result(self, run_uuid: str) -> EvaluationResult | None:
        """Reconstruct a full :class:`EvaluationResult` from persisted rows."""
        run = self.runs.get_by_uuid(run_uuid)
        return self._reconstruct(run) if run else None

    def get_active_baseline_result(self, feature: str) -> EvaluationResult | None:
        """Reconstruct the active baseline run for a feature, if any."""
        baseline = self.baselines.get_active(feature)
        if baseline is None:
            return None
        run = self.runs.get_by_id(baseline.run_id)
        return self._reconstruct(run) if run else None

    def _reconstruct(self, run: RunRecord) -> EvaluationResult:
        prompt = (
            self.prompt_versions.get_by_id(run.prompt_version_id)
            if run.prompt_version_id is not None
            else None
        )
        dataset = (
            self.dataset_versions.get_by_id(run.dataset_version_id)
            if run.dataset_version_id is not None
            else None
        )
        metrics = AggregateMetrics.model_validate_json(run.metrics_json)
        cases = [self._reconstruct_case(r) for r in self.test_results.list_for_run(run.id)]
        return EvaluationResult(
            run_id=run.run_uuid,
            feature=run.feature_name,
            prompt_version=prompt.version if prompt else "",
            prompt_hash=prompt.content_hash if prompt else "",
            dataset_version=dataset.version if dataset else "",
            dataset_hash=dataset.content_hash if dataset else "",
            model=run.model,
            start_time=datetime.fromisoformat(run.started_at),
            end_time=datetime.fromisoformat(run.finished_at),
            duration_seconds=run.duration_seconds,
            aggregate_metrics=metrics,
            per_case_results=cases,
        )

    @staticmethod
    def _reconstruct_case(record: TestResultRecord) -> CaseResult:
        return CaseResult(
            case_id=record.case_id,
            expected_difficulty=Difficulty(record.expected_difficulty),
            input=json.loads(record.input_json),
            expected_output=json.loads(record.expected_json),
            actual_output=(
                json.loads(record.actual_json) if record.actual_json is not None else None
            ),
            scores=[ScoreResult.model_validate(s) for s in json.loads(record.scores_json)],
            passed=bool(record.passed),
            latency_ms=record.latency_ms,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            total_tokens=record.total_tokens,
            error=record.error,
        )
