"""JSON serializers — the stable wire contract between the platform and the web UI.

These pure functions turn the platform's internal records/results (Pydantic models
and frozen dataclasses) into plain JSON-able dicts with a frontend-friendly shape.
Keeping serialization in one place means the HTTP layer (``app.py``) stays a thin
router and the contract is reviewable in a single file.

Nothing here does I/O *except* where a serializer is handed the read-only
:class:`DashboardData` to resolve an enrichment (e.g. a run's prompt version or a
feature's baseline) — those lookups are cheap and already cached by the data layer.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from mrds.dashboard.data import (
    CaseExplanation,
    DashboardData,
    DatasetView,
    FeatureOverview,
    RunLabel,
    RunRecommendations,
    TrendPoint,
    case_outcome,
    explain_case,
    humanize_metric_name,
)
from mrds.db.records import BaselineRecord, RegressionRecord, RunRecord
from mrds.evaluation.models import AggregateMetrics, CaseResult, EvaluationResult
from mrds.regression.models import RegressionResult

# ---------------------------------------------------------------------------
# Verdict helpers (feature-agnostic, pure)
# ---------------------------------------------------------------------------


def health_from_severities(severities: list[str]) -> str:
    """Reduce a set of regression severities to one health verdict."""
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "healthy"


def health_from_records(records: list[RegressionRecord]) -> str:
    """Health verdict for a run from its persisted regression records."""
    return health_from_severities([r.severity for r in records])


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def serialize_metrics(metrics: AggregateMetrics) -> dict[str, Any]:
    """Shape :class:`AggregateMetrics` for charts: scorers/segments as ordered lists."""
    return {
        "total_cases": metrics.total_cases,
        "passed": metrics.passed,
        "failed": metrics.failed,
        "errored": metrics.errored,
        "pass_rate": metrics.pass_rate,
        "segment_field": metrics.segment_field,
        "scorers": [
            {
                "name": name,
                "label": humanize_metric_name(f"scorer.{name}.mean_score"),
                "mean_score": stats.mean_score,
                "pass_rate": stats.pass_rate,
                "passed": stats.passed,
                "count": stats.count,
            }
            for name, stats in metrics.scorers.items()
        ],
        "segments": [
            {
                "segment": stats.segment,
                "count": stats.count,
                "passed": stats.passed,
                "pass_rate": stats.pass_rate,
                "scorer_means": dict(stats.scorer_means),
            }
            for stats in metrics.segments.values()
        ],
        "latency": metrics.latency.model_dump(),
        "tokens": metrics.tokens.model_dump(),
    }


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def serialize_case(case: CaseResult) -> dict[str, Any]:
    """A presentation-ready case: actual vs expected and every scorer's reason."""
    explained: CaseExplanation = explain_case(case)
    return {
        "case_id": explained.case_id,
        "difficulty": explained.difficulty,
        "outcome": case_outcome(case),
        "passed": explained.passed,
        "errored": explained.errored,
        "input": explained.input,
        "input_text": explained.input_text,
        "expected": explained.expected,
        "actual": explained.actual,
        "error": explained.error,
        "scorers": [
            {"name": s.name, "passed": s.passed, "score": s.score, "detail": s.detail}
            for s in explained.scorers
        ],
        "failed_scorers": list(explained.failed_scorers),
        "summary": explained.summary,
    }


# ---------------------------------------------------------------------------
# Feature overview (Mission Control fleet card)
# ---------------------------------------------------------------------------


def serialize_overview(
    overview: FeatureOverview,
    *,
    baseline_pass_rate: float | None,
    segment_field: str | None,
    latest_run_uuid: str | None,
    sparkline: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fleet-card payload: health + headline metrics + a pass-rate sparkline."""
    delta = (
        overview.latest_pass_rate - baseline_pass_rate
        if overview.latest_pass_rate is not None and baseline_pass_rate is not None
        else None
    )
    return {
        "feature": overview.feature,
        "display_name": overview.display_name,
        "health": overview.health,
        "run_count": overview.run_count,
        "latest_run_label": overview.latest_run_label,
        "latest_run_uuid": latest_run_uuid,
        "latest_pass_rate": overview.latest_pass_rate,
        "baseline_pass_rate": baseline_pass_rate,
        "has_baseline": baseline_pass_rate is not None,
        "baseline_delta": delta,
        "runs_with_regressions": overview.runs_with_regressions,
        "segment_field": segment_field,
        "sparkline": sparkline,
    }


# ---------------------------------------------------------------------------
# Run summary (timeline row) + run detail (the hero payload)
# ---------------------------------------------------------------------------


def serialize_run_summary(
    record: RunRecord,
    label: RunLabel,
    *,
    health: str,
    is_baseline: bool,
    prompt_version: str,
) -> dict[str, Any]:
    """One row in a feature's run timeline (cheap: parses the metrics snapshot)."""
    metrics = AggregateMetrics.model_validate_json(record.metrics_json)
    return {
        "run_uuid": record.run_uuid,
        "sequence": label.sequence,
        "label": label.label,
        "short_label": label.short_label,
        "status": record.status,
        "model": record.model,
        "prompt_version": prompt_version,
        "dataset_version": _dataset_version_from_label(label),
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "duration_seconds": record.duration_seconds,
        "total_tokens": record.total_tokens,
        "triggered_by": record.triggered_by,
        "pass_rate": metrics.pass_rate,
        "total_cases": metrics.total_cases,
        "passed": metrics.passed,
        "failed": metrics.failed,
        "errored": metrics.errored,
        "health": health,
        "is_baseline": is_baseline,
    }


def _dataset_version_from_label(label: RunLabel) -> str:
    """Pull the ``Dataset vN`` token out of a run label, if present."""
    for part in label.label.split(" · "):
        if part.startswith("Dataset "):
            return part.removeprefix("Dataset ")
    return ""


def make_verdict(
    pass_rate: float,
    *,
    total_cases: int,
    failed: int,
    errored: int,
    baseline_pass_rate: float | None,
    health: str,
) -> dict[str, Any]:
    """A one-line, plain-English verdict for the run-detail hero.

    Mirrors the dashboard's 'conclusion first' framing: state the standing vs
    baseline (if any) and the count of failing cases, in words.
    """
    failing = failed + errored
    if baseline_pass_rate is not None:
        delta = pass_rate - baseline_pass_rate
        points = abs(round(delta * 100))
        if delta < 0:
            standing = f"{points} pts below baseline"
        elif delta > 0:
            standing = f"{points} pts above baseline"
        else:
            standing = "level with baseline"
    else:
        standing = f"{round(pass_rate * 100)}% pass rate"

    if failing:
        evidence = f"{failing} of {total_cases} cases failing"
    else:
        evidence = f"all {total_cases} cases passing"

    return {
        "health": health,
        "headline": f"{standing} · {evidence}",
        "standing": standing,
        "evidence": evidence,
        "baseline_delta": (pass_rate - baseline_pass_rate)
        if baseline_pass_rate is not None
        else None,
    }


def serialize_run_detail(
    result: EvaluationResult,
    *,
    label: RunLabel | None,
    prompt_version: str,
    triggered_by: str,
    status: str,
    health: str,
    is_baseline: bool,
    baseline_pass_rate: float | None,
    baseline_label: str | None,
    baseline_run_uuid: str | None,
    regression: RegressionResult | None,
    recommendations: RunRecommendations,
) -> dict[str, Any]:
    """The full run-detail payload: verdict → metrics → cases, in one response."""
    metrics = result.aggregate_metrics
    return {
        "run_uuid": result.run_id,
        "feature": result.feature,
        "display_name": result.feature.replace("_", " ").title(),
        "label": label.label if label else result.run_id,
        "short_label": label.short_label if label else result.run_id,
        "sequence": label.sequence if label else None,
        "model": result.model,
        "prompt_version": prompt_version or result.prompt_version,
        "dataset_version": result.dataset_version,
        "status": status,
        "triggered_by": triggered_by,
        "start_time": result.start_time.isoformat(),
        "end_time": result.end_time.isoformat(),
        "duration_seconds": result.duration_seconds,
        "is_baseline": is_baseline,
        "segment_field": metrics.segment_field,
        "verdict": make_verdict(
            metrics.pass_rate,
            total_cases=metrics.total_cases,
            failed=metrics.failed,
            errored=metrics.errored,
            baseline_pass_rate=baseline_pass_rate,
            health=health,
        ),
        "metrics": serialize_metrics(metrics),
        "baseline": (
            {
                "run_uuid": baseline_run_uuid,
                "label": baseline_label,
                "pass_rate": baseline_pass_rate,
            }
            if baseline_pass_rate is not None
            else None
        ),
        "regression": serialize_comparison(regression) if regression else None,
        "recommendations": serialize_recommendations(recommendations),
        "cases": [serialize_case(c) for c in result.per_case_results],
    }


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------


def serialize_trend_point(point: TrendPoint, label: RunLabel | None) -> dict[str, Any]:
    """One point in a feature's time series, tagged with its readable label."""
    return {
        "run_uuid": point.run_uuid,
        "sequence": label.sequence if label else None,
        "label": label.short_label if label else point.run_uuid[:8],
        "started_at": point.started_at,
        "pass_rate": point.pass_rate,
        "errored": point.errored,
        "mean_latency_ms": point.mean_latency_ms,
        "p95_latency_ms": point.p95_latency_ms,
        "total_tokens": point.total_tokens,
        "scorer_means": dict(point.scorer_means),
    }


# ---------------------------------------------------------------------------
# Comparison / regressions
# ---------------------------------------------------------------------------


def _serialize_metric_comparison(comparison: Any) -> dict[str, Any]:
    return {
        "name": comparison.name,
        "label": humanize_metric_name(comparison.name),
        "kind": comparison.kind.value,
        "baseline_value": comparison.baseline_value,
        "candidate_value": comparison.candidate_value,
        "delta": comparison.delta,
        "relative_delta": comparison.relative_delta,
        "severity": comparison.severity.value,
        "regressed": comparison.regressed,
        "reason": comparison.reason,
    }


def serialize_comparison(result: RegressionResult) -> dict[str, Any]:
    """Shape a run-vs-run comparison, with humanized metric labels."""
    return {
        "feature": result.feature,
        "baseline_run_id": result.baseline_run_id,
        "candidate_run_id": result.candidate_run_id,
        "baseline_prompt_version": result.baseline_prompt_version,
        "candidate_prompt_version": result.candidate_prompt_version,
        "baseline_dataset_version": result.baseline_dataset_version,
        "candidate_dataset_version": result.candidate_dataset_version,
        "prompt_changed": result.prompt_changed,
        "dataset_changed": result.dataset_changed,
        "severity": result.severity.value,
        "warning_count": result.warning_count,
        "critical_count": result.critical_count,
        "is_blocking": result.is_blocking,
        "has_regression": result.has_regression,
        "comparisons": [_serialize_metric_comparison(c) for c in result.comparisons],
        "regressions": [_serialize_metric_comparison(c) for c in result.regressions],
    }


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


def serialize_baseline(
    record: BaselineRecord,
    *,
    run_uuid: str | None,
    run_label: str | None,
    pass_rate: float | None,
) -> dict[str, Any]:
    """A baseline promotion record, joined to its run's readable label + pass rate."""
    return {
        "id": record.id,
        "run_id": record.run_id,
        "run_uuid": run_uuid,
        "run_label": run_label,
        "is_active": bool(record.is_active),
        "promoted_by": record.promoted_by,
        "promoted_at": record.promoted_at,
        "note": record.note,
        "pass_rate": pass_rate,
    }


# ---------------------------------------------------------------------------
# Recommendations ("what would make this run perfect")
# ---------------------------------------------------------------------------


def serialize_recommendations(rec: RunRecommendations) -> dict[str, Any]:
    return {
        "is_perfect": rec.is_perfect,
        "total_cases": rec.total_cases,
        "failing_cases": rec.failing_cases,
        "current_pass_rate": rec.current_pass_rate,
        "points_to_recover": rec.points_to_recover,
        "gap_to_baseline": rec.gap_to_baseline,
        "by_category": [
            {
                "category": gap.category,
                "failing": gap.failing,
                "recoverable_points": gap.recoverable_points,
            }
            for gap in rec.by_category
        ],
    }


# ---------------------------------------------------------------------------
# Dataset (golden examples + coverage)
# ---------------------------------------------------------------------------


def serialize_dataset(view: DatasetView, *, segment_field: str | None) -> dict[str, Any]:
    """The golden dataset with coverage distributions for the Dataset explorer."""
    by_difficulty = Counter(c.difficulty for c in view.cases)
    by_category: Counter[str] = Counter()
    if segment_field:
        for c in view.cases:
            value = c.expected.get(segment_field)
            if value is not None:
                by_category[str(value)] += 1
    return {
        "feature": view.feature,
        "version": view.version,
        "description": view.description,
        "case_count": view.case_count,
        "segment_field": segment_field,
        "coverage": {
            "by_difficulty": [{"key": k, "count": v} for k, v in sorted(by_difficulty.items())],
            "by_category": [
                {"key": k, "count": v}
                for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])
            ],
        },
        "cases": [
            {
                "case_id": c.case_id,
                "input": c.input,
                "input_text": c.input_text,
                "expected": c.expected,
                "difficulty": c.difficulty,
                "notes": c.notes,
                "category": (str(c.expected.get(segment_field)) if segment_field else None),
            }
            for c in view.cases
        ],
    }


def resolve_prompt_version(data: DashboardData, prompt_version_id: int | None) -> str:
    """Best-effort prompt version string for a run row (empty if unresolved)."""
    if prompt_version_id is None:
        return ""
    record = data._store.prompt_versions.get_by_id(prompt_version_id)  # noqa: SLF001
    return record.version if record else ""
