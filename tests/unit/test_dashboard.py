"""Tests for the dashboard data-access layer and its repository integration."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mrds.core.interfaces import ScoreResult
from mrds.dashboard.data import (
    DashboardData,
    TrendPoint,
    build_run_label,
    case_outcome,
    cases_for_metric,
    explain_case,
    filter_cases,
    humanize_metric_name,
    parse_dataset,
    perfect_run_recommendations,
)
from mrds.datasets.models import Difficulty
from mrds.db import EvaluationStore, open_database
from mrds.evaluation.models import (
    AggregateMetrics,
    CaseResult,
    EvaluationResult,
    LatencyStats,
    ScorerStats,
    TokenStats,
)
from mrds.regression import RegressionDetector

NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)


def _result(
    run_id: str, *, feature: str = "email_classifier", cat_mean: float, pass_rate: float
) -> EvaluationResult:
    return EvaluationResult(
        run_id=run_id,
        feature=feature,
        prompt_version="v1",
        prompt_hash="ph1",
        dataset_version="v1",
        dataset_hash="dh1",
        model="gpt-4o-mini",
        start_time=NOW,
        end_time=NOW,
        duration_seconds=1.0,
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
                )
            },
            segments={},
            segment_field=None,
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
        per_case_results=[
            CaseResult(
                case_id="c-1",
                expected_difficulty=Difficulty.EASY,
                input={"email_text": "hi"},
                expected_output={"category": "billing", "summary": "x"},
                actual_output={"category": "billing", "summary": "x"},
                scores=[ScoreResult(name="category_match", score=cat_mean, passed=True)],
                passed=True,
                latency_ms=10.0,
                total_tokens=12,
            )
        ],
    )


@pytest.fixture
def data() -> DashboardData:
    store = EvaluationStore(open_database(":memory:"))
    # Two runs for email_classifier + one for a second feature.
    store.save_evaluation(_result("run-1", cat_mean=0.95, pass_rate=0.95))
    store.save_evaluation(_result("run-2", cat_mean=0.80, pass_rate=0.80))
    store.save_evaluation(_result("rag-1", feature="rag_qa", cat_mean=0.9, pass_rate=0.9))
    # A regression for run-2 against promoted run-1.
    store.promote_baseline("run-1", promoted_by="ci", note="first baseline")
    regression = RegressionDetector().compare(
        store.get_evaluation_result("run-1"), store.get_evaluation_result("run-2")
    )
    store.save_regression(regression)
    return DashboardData(store)


# -- features / runs ------------------------------------------------------------


def test_features_are_distinct_and_sorted(data: DashboardData) -> None:
    assert data.features() == ["email_classifier", "rag_qa"]


def test_runs_lists_most_recent_first(data: DashboardData) -> None:
    runs = data.runs("email_classifier")
    assert [r.run_uuid for r in runs] == ["run-2", "run-1"]


def test_run_detail_reconstructs(data: DashboardData) -> None:
    result = data.run_detail("run-1")
    assert result is not None
    assert result.feature == "email_classifier"
    assert result.aggregate_metrics.pass_rate == pytest.approx(0.95)
    assert result.per_case_results[0].case_id == "c-1"


def test_run_detail_unknown_returns_none(data: DashboardData) -> None:
    assert data.run_detail("missing") is None


# -- run labels -----------------------------------------------------------------


def test_build_run_label_full_and_short() -> None:
    label = build_run_label(
        run_uuid="abc123",
        feature="email_classifier",
        sequence=12,
        model="gpt-4o-mini",
        dataset_version="v1",
        started_at="2026-06-02T09:30:00+00:00",
    )
    assert label.run_uuid == "abc123"  # internal id is preserved untouched
    assert label.sequence == 12
    assert label.label == "Email Classifier #12 · gpt-4o-mini · Dataset v1 · Jun 2, 2026"
    assert label.short_label == "#12 · Jun 2"


def test_build_run_label_degrades_gracefully() -> None:
    label = build_run_label(
        run_uuid="x",
        feature="rag_qa",
        sequence=1,
        model="",
        dataset_version="",
        started_at="not-a-date",
    )
    # Missing model / dataset / unparseable date are omitted, not rendered as blanks.
    assert label.label == "Rag Qa #1"
    assert label.short_label == "#1"


def test_run_labels_number_oldest_first_and_preserve_uuid(data: DashboardData) -> None:
    labels = data.run_labels("email_classifier")
    # runs() is most-recent-first: run-2 then run-1; the oldest run is #1.
    assert [label.run_uuid for label in labels] == ["run-2", "run-1"]
    by_uuid = {label.run_uuid: label for label in labels}
    assert by_uuid["run-1"].sequence == 1
    assert by_uuid["run-2"].sequence == 2
    assert by_uuid["run-2"].label.startswith("Email Classifier #2 · gpt-4o-mini · Dataset v1 · ")


def test_run_label_map_keys_by_uuid(data: DashboardData) -> None:
    mapping = data.run_label_map("email_classifier")
    assert set(mapping) == {"run-1", "run-2"}
    assert mapping["run-1"].run_uuid == "run-1"


# -- case explanations ----------------------------------------------------------


def _case(*, passed: bool, scores: list[ScoreResult], actual, error=None) -> CaseResult:
    return CaseResult(
        case_id="ec-007",
        expected_difficulty=Difficulty.MEDIUM,
        input={"email_text": "My card was declined, how do I update payment?"},
        expected_output={"category": "billing", "summary": "payment update"},
        actual_output=actual,
        scores=scores,
        passed=passed,
        latency_ms=10.0,
        error=error,
    )


def test_explain_case_failure_surfaces_actual_vs_expected_and_reason() -> None:
    case = _case(
        passed=False,
        actual={"category": "technical", "summary": "payment update"},
        scores=[
            ScoreResult(
                name="category_match",
                score=0.0,
                passed=False,
                detail="expected 'billing', got 'technical'",
            ),
            ScoreResult(name="summary_quality", score=1.0, passed=True, detail="words=2"),
        ],
    )
    exp = explain_case(case)
    assert not exp.passed and not exp.errored
    assert exp.input_text == "My card was declined, how do I update payment?"
    assert exp.expected["category"] == "billing"
    assert exp.actual is not None and exp.actual["category"] == "technical"
    assert exp.failed_scorers == ("category_match",)
    assert "expected 'billing', got 'technical'" in exp.summary


def test_explain_case_pass() -> None:
    case = _case(
        passed=True,
        actual={"category": "billing", "summary": "payment update"},
        scores=[
            ScoreResult(name="category_match", score=1.0, passed=True, detail="category matched")
        ],
    )
    exp = explain_case(case)
    assert exp.passed and not exp.errored
    assert exp.failed_scorers == ()
    assert exp.summary == "All checks passed."


def test_explain_case_errored() -> None:
    case = _case(passed=False, actual=None, scores=[], error="invalid model output")
    exp = explain_case(case)
    assert exp.errored
    assert exp.actual is None
    assert exp.summary == "Errored — invalid model output"


# -- feature overview -----------------------------------------------------------


def test_feature_overview_reports_health_and_stats(data: DashboardData) -> None:
    overview = data.feature_overview("email_classifier")
    assert overview.display_name == "Email Classifier"
    assert overview.run_count == 2
    assert overview.latest_pass_rate == pytest.approx(0.80)  # latest run = run-2
    assert overview.runs_with_regressions == 1  # only run-2 regressed
    assert overview.health == "critical"  # run-2's drop vs run-1 is critical
    assert overview.latest_run_label and "Email Classifier #2" in overview.latest_run_label


def test_feature_overview_healthy_feature(data: DashboardData) -> None:
    overview = data.feature_overview("rag_qa")
    assert overview.run_count == 1
    assert overview.runs_with_regressions == 0
    assert overview.health == "healthy"


def test_feature_overview_unknown_feature(data: DashboardData) -> None:
    overview = data.feature_overview("nope")
    assert overview.run_count == 0
    assert overview.latest_pass_rate is None
    assert overview.latest_run_label is None
    assert overview.health == "unknown"


# -- trends ---------------------------------------------------------------------


def test_trend_is_chronological(data: DashboardData) -> None:
    points = data.trend("email_classifier")
    assert [p.run_uuid for p in points] == ["run-1", "run-2"]  # oldest -> newest
    assert isinstance(points[0], TrendPoint)
    assert points[0].pass_rate == pytest.approx(0.95)
    assert points[1].pass_rate == pytest.approx(0.80)
    assert points[0].scorer_means["category_match"] == pytest.approx(0.95)
    assert points[0].mean_latency_ms == 12.0
    assert points[0].total_tokens == 120


def test_trend_empty_for_unknown_feature(data: DashboardData) -> None:
    assert data.trend("nope") == []


# -- regressions ----------------------------------------------------------------


def test_regressions_for_run(data: DashboardData) -> None:
    regressions = data.regressions_for_run("run-2")
    assert regressions
    assert any(r.metric == "scorer.category_match.mean_score" for r in regressions)
    assert all(r.severity in {"warning", "critical"} for r in regressions)


def test_regressions_for_run_without_regressions(data: DashboardData) -> None:
    assert data.regressions_for_run("run-1") == []


def test_regressions_for_unknown_run(data: DashboardData) -> None:
    assert data.regressions_for_run("missing") == []


# -- test log explorer (filtering) ----------------------------------------------


def _explorer_case(
    case_id: str,
    *,
    passed: bool,
    error: str | None = None,
    category: str = "billing",
    difficulty: Difficulty = Difficulty.EASY,
    text: str = "hello there",
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        expected_difficulty=difficulty,
        input={"email_text": text},
        expected_output={"category": category, "summary": "s"},
        actual_output=None if error else {"category": category, "summary": "s"},
        scores=[],
        passed=passed,
        latency_ms=1.0,
        error=error,
    )


_EXPLORER_CASES = [
    _explorer_case("a", passed=True, category="billing", difficulty=Difficulty.EASY, text="refund"),
    _explorer_case(
        "b", passed=False, category="technical", difficulty=Difficulty.HARD, text="crash"
    ),
    _explorer_case(
        "c",
        passed=False,
        error="boom",
        category="account",
        difficulty=Difficulty.MEDIUM,
        text="login",
    ),
]


def test_case_outcome_classifies() -> None:
    assert [case_outcome(c) for c in _EXPLORER_CASES] == ["passed", "failed", "errored"]


def test_filter_cases_by_outcome() -> None:
    matching = filter_cases(_EXPLORER_CASES, outcomes=["failed", "errored"])
    assert [c.case_id for c in matching] == ["b", "c"]


def test_filter_cases_by_difficulty_and_category() -> None:
    by_diff = filter_cases(_EXPLORER_CASES, difficulties=["hard"])
    assert [c.case_id for c in by_diff] == ["b"]
    by_cat = filter_cases(_EXPLORER_CASES, categories=["account"], segment_field="category")
    assert [c.case_id for c in by_cat] == ["c"]


def test_filter_cases_by_search_matches_text_and_id() -> None:
    assert [c.case_id for c in filter_cases(_EXPLORER_CASES, search="refund")] == ["a"]
    assert [c.case_id for c in filter_cases(_EXPLORER_CASES, search="LOGIN")] == [
        "c"
    ]  # case-insensitive
    # "b" appears in no input text, so this matches the case id only.
    assert [c.case_id for c in filter_cases(_EXPLORER_CASES, search="b")] == ["b"]


def test_filter_cases_none_means_no_constraint() -> None:
    assert len(filter_cases(_EXPLORER_CASES)) == 3
    # Category filter is ignored when no segment_field is supplied.
    assert len(filter_cases(_EXPLORER_CASES, categories=["billing"], segment_field=None)) == 3


# -- root cause attribution -----------------------------------------------------


def _scored_case(
    case_id: str,
    *,
    passed: bool,
    category: str,
    scorer_passed: bool | None,
    error: str | None = None,
) -> CaseResult:
    scores = (
        []
        if scorer_passed is None
        else [
            ScoreResult(
                name="category_match",
                score=1.0 if scorer_passed else 0.0,
                passed=scorer_passed,
            )
        ]
    )
    return CaseResult(
        case_id=case_id,
        expected_difficulty=Difficulty.EASY,
        input={"email_text": "x"},
        expected_output={"category": category, "summary": "s"},
        actual_output=None if error else {"category": category, "summary": "s"},
        scores=scores,
        passed=passed,
        latency_ms=1.0,
        error=error,
    )


_RCA_CASES = [
    _scored_case("p", passed=True, category="billing", scorer_passed=True),
    _scored_case("f", passed=False, category="technical", scorer_passed=False),
    _scored_case("f2", passed=False, category="account", scorer_passed=False),
    _scored_case("e", passed=False, category="billing", scorer_passed=None, error="boom"),
]


def test_cases_for_metric_pass_rate_includes_errored() -> None:
    ids = [c.case_id for c in cases_for_metric("pass_rate", _RCA_CASES)]
    assert ids == ["f", "f2", "e"]


def test_cases_for_metric_errored() -> None:
    assert [c.case_id for c in cases_for_metric("errored", _RCA_CASES)] == ["e"]


def test_cases_for_metric_scorer_excludes_errored() -> None:
    # Errored case "e" has no category_match score, so it does not drag the scorer mean.
    ids = [c.case_id for c in cases_for_metric("scorer.category_match.mean_score", _RCA_CASES)]
    assert ids == ["f", "f2"]


def test_cases_for_metric_segment_scoped() -> None:
    ids = [
        c.case_id
        for c in cases_for_metric(
            "segment.account.category_match", _RCA_CASES, segment_field="category"
        )
    ]
    assert ids == ["f2"]


def test_cases_for_metric_aggregate_has_no_cases() -> None:
    assert cases_for_metric("latency.mean_ms", _RCA_CASES) == []
    assert cases_for_metric("tokens.total_tokens", _RCA_CASES) == []


# -- perfect run recommendations ------------------------------------------------


def test_perfect_run_recommendations_summarises_the_gap() -> None:
    # _RCA_CASES: 1 passing + 3 failing (technical, account, billing-errored) of 4.
    rec = perfect_run_recommendations(_RCA_CASES, segment_field="category", baseline_pass_rate=0.95)
    assert not rec.is_perfect
    assert rec.total_cases == 4
    assert rec.failing_cases == 3
    assert rec.current_pass_rate == pytest.approx(0.25)
    assert rec.points_to_recover == pytest.approx(0.75)
    assert rec.gap_to_baseline == pytest.approx(0.70)
    # One failing case in each of three categories, sorted by name on the count tie.
    assert [(g.category, g.failing) for g in rec.by_category] == [
        ("account", 1),
        ("billing", 1),
        ("technical", 1),
    ]
    assert rec.by_category[0].recoverable_points == pytest.approx(0.25)


def test_perfect_run_recommendations_all_passing() -> None:
    passing = [_scored_case("p1", passed=True, category="billing", scorer_passed=True)]
    rec = perfect_run_recommendations(passing, segment_field="category")
    assert rec.is_perfect
    assert rec.failing_cases == 0
    assert rec.points_to_recover == pytest.approx(0.0)
    assert rec.gap_to_baseline is None
    assert rec.by_category == ()


# -- dataset explorer -----------------------------------------------------------


_SAMPLE_DATASET = {
    "version": "v1",
    "description": "A tiny golden set.",
    "cases": [
        {
            "id": "ec-001",
            "input": {"email_text": "refund my duplicate charge"},
            "expected_output": {"category": "billing", "summary": "refund"},
            "expected_difficulty": "easy",
            "notes": "clear billing case",
        },
        {
            "id": "ec-002",
            "input": {"email_text": "app keeps crashing"},
            "expected_output": {"category": "technical", "summary": "crash"},
            "expected_difficulty": "hard",
            "notes": "",
        },
    ],
}


def test_parse_dataset_keeps_notes_and_input_text() -> None:
    view = parse_dataset(_SAMPLE_DATASET, feature="email_classifier")
    assert view.version == "v1"
    assert view.description == "A tiny golden set."
    assert view.case_count == 2
    first = view.cases[0]
    assert first.case_id == "ec-001"
    assert first.input_text == "refund my duplicate charge"
    assert first.expected["category"] == "billing"
    assert first.difficulty == "easy"
    assert first.notes == "clear billing case"


# -- metric name humanizing -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pass_rate", "Pass rate"),
        ("errored", "Errored cases"),
        ("latency.mean_ms", "Latency (mean ms)"),
        ("latency.p95_ms", "Latency (p95 ms)"),
        ("tokens.total_tokens", "Total tokens"),
        ("tokens.mean_tokens_per_case", "Tokens per case"),
        ("scorer.category_match.mean_score", "category_match — mean score"),
        ("scorer.summary_quality.pass_rate", "summary_quality — pass rate"),
        ("segment.billing.category_match", "billing / category_match"),
        ("something_unknown", "something_unknown"),
    ],
)
def test_humanize_metric_name(raw: str, expected: str) -> None:
    assert humanize_metric_name(raw) == expected


# -- run comparison -------------------------------------------------------------


def test_compare_runs_returns_b_minus_a_deltas(data: DashboardData) -> None:
    # A = run-1 (pass 0.95), B = run-2 (pass 0.80); delta = B - A.
    comparison = data.compare_runs("run-1", "run-2")
    assert comparison is not None
    by_name = {c.name: c for c in comparison.comparisons}
    pass_rate = by_name["pass_rate"]
    assert pass_rate.baseline_value == pytest.approx(0.95)
    assert pass_rate.candidate_value == pytest.approx(0.80)
    assert pass_rate.delta == pytest.approx(-0.15)


def test_compare_runs_direction_is_respected(data: DashboardData) -> None:
    # Swapping A and B flips the sign of the delta.
    forward = data.compare_runs("run-1", "run-2")
    backward = data.compare_runs("run-2", "run-1")
    assert forward is not None and backward is not None
    fwd = {c.name: c for c in forward.comparisons}["pass_rate"]
    bwd = {c.name: c for c in backward.comparisons}["pass_rate"]
    assert fwd.delta == pytest.approx(-bwd.delta)


def test_compare_runs_missing_returns_none(data: DashboardData) -> None:
    assert data.compare_runs("run-1", "missing") is None
    assert data.compare_runs("missing", "run-1") is None


# -- baselines ------------------------------------------------------------------


def test_active_baseline_and_history(data: DashboardData) -> None:
    active = data.active_baseline("email_classifier")
    assert active is not None
    assert data.run_uuid_for(active.run_id) == "run-1"
    assert len(data.baseline_history("email_classifier")) == 1


def test_no_baseline_for_other_feature(data: DashboardData) -> None:
    assert data.active_baseline("rag_qa") is None


def test_baseline_pass_rate(data: DashboardData) -> None:
    # run-1 (pass 0.95) is the promoted baseline for email_classifier.
    assert data.baseline_pass_rate("email_classifier") == pytest.approx(0.95)
    # rag_qa has no baseline.
    assert data.baseline_pass_rate("rag_qa") is None


# -- repository integration -----------------------------------------------------


def test_run_repository_features_distinct(data: DashboardData) -> None:
    store = EvaluationStore(open_database(":memory:"))
    assert store.runs.features() == []
    store.save_evaluation(_result("a", cat_mean=0.9, pass_rate=0.9))
    store.save_evaluation(_result("b", cat_mean=0.9, pass_rate=0.9))
    assert store.runs.features() == ["email_classifier"]  # distinct
