"""Tests for the SQLite system-of-record layer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mrds.core.interfaces import ScoreResult
from mrds.datasets.models import Difficulty
from mrds.db import DbError, EvaluationStore, open_database
from mrds.db.migrations import SCHEMA_VERSION
from mrds.evaluation.models import (
    AggregateMetrics,
    CaseResult,
    EvaluationResult,
    LatencyStats,
    ScorerStats,
    SegmentStats,
    TokenStats,
)
from mrds.regression import RegressionDetector

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)

EXPECTED_TABLES = {
    "feature_specs",
    "prompt_versions",
    "dataset_versions",
    "runs",
    "test_results",
    "baselines",
    "regressions",
}


def _cases() -> list[CaseResult]:
    return [
        CaseResult(
            case_id="ec-001",
            expected_difficulty=Difficulty.EASY,
            input={"email_text": "I was charged twice."},
            expected_output={"category": "billing", "summary": "Double charge."},
            actual_output={"category": "billing", "summary": "Double charge."},
            scores=[
                ScoreResult(name="category_match", score=1.0, passed=True),
                ScoreResult(name="summary_quality", score=1.0, passed=True, detail="ok"),
            ],
            passed=True,
            latency_ms=11.5,
            input_tokens=8,
            output_tokens=4,
            total_tokens=12,
        ),
        CaseResult(
            case_id="ec-002",
            expected_difficulty=Difficulty.HARD,
            input={"email_text": "It's broken."},
            expected_output={"category": "technical", "summary": "Broke."},
            actual_output=None,
            scores=[],
            passed=False,
            latency_ms=9.0,
            error="LLM failed",
        ),
    ]


def _result(
    run_id: str,
    *,
    feature: str = "email_classifier",
    prompt: str = "v1",
    prompt_hash: str = "ph1",
    dataset: str = "v1",
    dataset_hash: str = "dh1",
    cat_mean: float = 0.9,
    pass_rate: float = 0.9,
) -> EvaluationResult:
    return EvaluationResult(
        run_id=run_id,
        feature=feature,
        prompt_version=prompt,
        prompt_hash=prompt_hash,
        dataset_version=dataset,
        dataset_hash=dataset_hash,
        model="gpt-4o-mini",
        start_time=NOW,
        end_time=NOW,
        duration_seconds=1.25,
        aggregate_metrics=AggregateMetrics(
            total_cases=10,
            passed=int(pass_rate * 10),
            failed=10 - int(pass_rate * 10),
            errored=0,
            pass_rate=pass_rate,
            scorers={
                "category_match": ScorerStats(
                    name="category_match",
                    mean_score=cat_mean,
                    pass_rate=cat_mean,
                    passed=9,
                    count=10,
                ),
                "summary_quality": ScorerStats(
                    name="summary_quality", mean_score=1.0, pass_rate=1.0, passed=10, count=10
                ),
            },
            segments={
                "billing": SegmentStats(
                    segment="billing",
                    count=5,
                    passed=4,
                    pass_rate=0.8,
                    scorer_means={"category_match": 0.8},
                )
            },
            segment_field="category",
            latency=LatencyStats(
                count=10, total_ms=120, mean_ms=12, min_ms=9, p50_ms=11, p95_ms=20, max_ms=25
            ),
            tokens=TokenStats(
                total_tokens=120,
                total_input_tokens=80,
                total_output_tokens=40,
                mean_tokens_per_case=12.0,
            ),
        ),
        per_case_results=_cases(),
    )


@pytest.fixture
def store() -> EvaluationStore:
    return EvaluationStore(open_database(":memory:"))


# -- bootstrap / connection -----------------------------------------------------


def test_bootstrap_creates_all_tables() -> None:
    db = open_database(":memory:")
    rows = db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    assert names >= EXPECTED_TABLES
    assert db.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_bootstrap_is_idempotent() -> None:
    db = open_database(":memory:")
    assert db.bootstrap() == SCHEMA_VERSION  # second call is a no-op and returns the version


def test_open_database_creates_file(tmp_path) -> None:
    path = tmp_path / "nested" / "eval.db"
    db = open_database(path)
    assert path.exists()
    db.close()


# -- version repositories -------------------------------------------------------


def test_prompt_version_upsert_is_idempotent(store: EvaluationStore) -> None:
    db = store._db
    with db.transaction():
        a = store.prompt_versions.upsert(feature_name="f", version="v1", content_hash="h1")
        b = store.prompt_versions.upsert(feature_name="f", version="v1", content_hash="h1")
    assert a.id == b.id
    count = db.connection.execute("SELECT COUNT(*) FROM prompt_versions").fetchone()[0]
    assert count == 1


def test_dataset_version_upsert_tracks_case_count(store: EvaluationStore) -> None:
    with store._db.transaction():
        rec = store.dataset_versions.upsert(
            feature_name="f", version="v1", content_hash="d1", case_count=54
        )
    assert rec.case_count == 54


# -- save / reconstruct ---------------------------------------------------------


def test_save_and_reconstruct_round_trips(store: EvaluationStore) -> None:
    original = _result("run-1")
    run = store.save_evaluation(original, triggered_by="ci", git_sha="abc123")
    assert run.run_uuid == "run-1"
    assert run.triggered_by == "ci"
    assert run.git_sha == "abc123"

    restored = store.get_evaluation_result("run-1")
    assert restored == original  # full round-trip equality


def test_save_persists_versions_and_cases(store: EvaluationStore) -> None:
    store.save_evaluation(_result("run-1"))
    conn = store._db.connection
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM test_results").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM prompt_versions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dataset_versions").fetchone()[0] == 1


def test_latest_run_uuid(store: EvaluationStore) -> None:
    store.save_evaluation(_result("run-1"))
    store.save_evaluation(_result("run-2"))
    assert store.latest_run_uuid("email_classifier") == "run-2"
    assert store.latest_run_uuid("nonexistent") is None


def test_get_unknown_run_returns_none(store: EvaluationStore) -> None:
    assert store.get_evaluation_result("missing") is None


def test_feature_agnostic_round_trip(store: EvaluationStore) -> None:
    result = EvaluationResult(
        run_id="rag-1",
        feature="rag_qa",
        prompt_version="v1",
        prompt_hash="p",
        dataset_version="v1",
        dataset_hash="d",
        model="gpt-4o-mini",
        start_time=NOW,
        end_time=NOW,
        duration_seconds=0.5,
        aggregate_metrics=AggregateMetrics(
            total_cases=1,
            passed=1,
            failed=0,
            errored=0,
            pass_rate=1.0,
            scorers={
                "answer_relevance": ScorerStats(
                    name="answer_relevance", mean_score=0.9, pass_rate=1.0, passed=1, count=1
                )
            },
            segments={},
            segment_field=None,
            latency=LatencyStats(
                count=1, total_ms=5, mean_ms=5, min_ms=5, p50_ms=5, p95_ms=5, max_ms=5
            ),
            tokens=TokenStats(
                total_tokens=10,
                total_input_tokens=6,
                total_output_tokens=4,
                mean_tokens_per_case=10.0,
            ),
        ),
        per_case_results=[
            CaseResult(
                case_id="q-1",
                expected_difficulty=Difficulty.EASY,
                input={"question": "What is MRDS?"},
                expected_output={"answer": "A platform."},
                actual_output={"answer": "A platform."},
                scores=[ScoreResult(name="answer_relevance", score=0.9, passed=True)],
                passed=True,
                latency_ms=5.0,
                total_tokens=10,
            )
        ],
    )
    store.save_evaluation(result)
    assert store.get_evaluation_result("rag-1") == result


# -- baselines ------------------------------------------------------------------


def test_promote_baseline_keeps_single_active(store: EvaluationStore) -> None:
    store.save_evaluation(_result("run-1", cat_mean=0.9))
    store.save_evaluation(_result("run-2", cat_mean=0.95))

    store.promote_baseline("run-1", promoted_by="ci", note="first")
    second = store.promote_baseline("run-2", promoted_by="ci", note="better")

    active = store.baselines.get_active("email_classifier")
    assert active is not None
    assert active.id == second.id
    assert active.run_id == store.runs.get_by_uuid("run-2").id
    # Exactly one active baseline; full history preserved.
    actives = store._db.connection.execute(
        "SELECT COUNT(*) FROM baselines WHERE feature_name='email_classifier' AND is_active=1"
    ).fetchone()[0]
    assert actives == 1
    assert len(store.baselines.history("email_classifier")) == 2


def test_promote_unknown_run_raises(store: EvaluationStore) -> None:
    with pytest.raises(DbError):
        store.promote_baseline("nope")


def test_get_active_baseline_result_reconstructs(store: EvaluationStore) -> None:
    original = _result("run-1")
    store.save_evaluation(original)
    store.promote_baseline("run-1", promoted_by="ci")
    assert store.get_active_baseline_result("email_classifier") == original
    assert store.get_active_baseline_result("other_feature") is None


# -- regressions ----------------------------------------------------------------


def test_save_regression_persists_regressed_metrics(store: EvaluationStore) -> None:
    baseline = _result("base-1", cat_mean=0.92, pass_rate=0.92)
    candidate = _result("cand-1", cat_mean=0.78, pass_rate=0.78)
    store.save_evaluation(baseline)
    store.save_evaluation(candidate)

    regression = RegressionDetector().compare(
        store.get_evaluation_result("base-1"), store.get_evaluation_result("cand-1")
    )
    assert regression.regressions  # there are regressed metrics

    records = store.save_regression(regression)
    assert len(records) == len(regression.regressions)
    cand_id = store.runs.get_by_uuid("cand-1").id
    assert len(store.regressions.list_for_run(cand_id)) == len(records)
    assert all(r.severity in {"warning", "critical"} for r in records)


def test_save_regression_requires_persisted_runs(store: EvaluationStore) -> None:
    baseline = _result("base-x")
    candidate = _result("cand-x", cat_mean=0.5)
    regression = RegressionDetector().compare(baseline, candidate)  # not persisted
    with pytest.raises(DbError):
        store.save_regression(regression)


# -- foreign keys ---------------------------------------------------------------


def test_delete_run_cascades_to_test_results(store: EvaluationStore) -> None:
    store.save_evaluation(_result("run-1"))
    conn = store._db.connection
    run_id = store.runs.get_by_uuid("run-1").id
    with store._db.transaction():
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    assert conn.execute("SELECT COUNT(*) FROM test_results").fetchone()[0] == 0
