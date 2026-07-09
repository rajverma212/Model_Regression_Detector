"""Read-only data access for the dashboard.

This module has **no Streamlit dependency** — it is the testable seam between the
persisted data and the presentation pages. It reuses :class:`EvaluationStore` and
its repositories; the only derived computation is parsing each run's stored
metrics snapshot into chartable :class:`TrendPoint`s. Nothing here writes.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from mrds.db import EvaluationStore
from mrds.db.records import BaselineRecord, RegressionRecord, RunRecord
from mrds.evaluation.models import AggregateMetrics, CaseResult, EvaluationResult
from mrds.observability.logging import get_logger
from mrds.regression.detector import RegressionDetector
from mrds.regression.models import RegressionResult

logger = get_logger(__name__)


@dataclass(frozen=True)
class TrendPoint:
    """One point in a feature's metric time-series (derived from a run)."""

    run_uuid: str
    started_at: str
    pass_rate: float
    errored: int
    mean_latency_ms: float
    p95_latency_ms: float
    total_tokens: int
    scorer_means: dict[str, float]


@dataclass(frozen=True)
class RunLabel:
    """A human-readable identity for a run, paired with its internal ``run_uuid``.

    The label is **display-only**; ``run_uuid`` remains the value behind every widget
    so run selection is unaffected (see ``build_run_label``).
    """

    run_uuid: str
    sequence: int
    label: str  # full, e.g. "Email Classifier #12 · gpt-4o-mini · Dataset v1 · Jun 2, 2026"
    short_label: str  # compact, for chart axes, e.g. "#12 · Jun 2"


def _humanize_feature(feature: str) -> str:
    """Turn a feature slug into a title-cased display name (e.g. ``Email Classifier``)."""
    return feature.replace("_", " ").title()


def _parse_started_at(started_at: str) -> datetime | None:
    try:
        return datetime.fromisoformat(started_at)
    except ValueError:
        return None


def build_run_label(
    *,
    run_uuid: str,
    feature: str,
    sequence: int,
    model: str,
    dataset_version: str,
    started_at: str,
) -> RunLabel:
    """Build a :class:`RunLabel` from a run's display fields (pure; no I/O).

    Components that are missing (no model / dataset version / unparseable date) are
    simply omitted, so the label degrades gracefully. ``run_uuid`` is never altered.
    """
    feature_name = _humanize_feature(feature)
    dt = _parse_started_at(started_at)
    full_date = f"{dt:%b} {dt.day}, {dt.year}" if dt else ""
    short_date = f"{dt:%b} {dt.day}" if dt else ""

    parts = [f"{feature_name} #{sequence}"]
    if model:
        parts.append(model)
    if dataset_version:
        parts.append(f"Dataset {dataset_version}")
    if full_date:
        parts.append(full_date)

    short = f"#{sequence}" + (f" · {short_date}" if short_date else "")
    return RunLabel(
        run_uuid=run_uuid,
        sequence=sequence,
        label=" · ".join(parts),
        short_label=short,
    )


@dataclass(frozen=True)
class FeatureOverview:
    """Headline status for one feature, for the home page panel."""

    feature: str
    display_name: str
    run_count: int
    latest_run_label: str | None
    latest_pass_rate: float | None
    runs_with_regressions: int
    health: str  # "healthy" | "warning" | "critical" | "unknown"


def _health_from_severities(severities: list[str]) -> str:
    """Reduce a run's regression severities to a single health verdict."""
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "healthy"


def humanize_metric_name(name: str) -> str:
    """Turn a flattened metric name into a readable label (pure).

    e.g. ``scorer.category_match.mean_score`` -> ``category_match — mean score``,
    ``latency.p95_ms`` -> ``Latency (p95 ms)``, ``segment.billing.category_match``
    -> ``billing / category_match``. Reused anywhere a flattened name is shown.
    """
    if name == "pass_rate":
        return "Pass rate"
    if name == "errored":
        return "Errored cases"
    if name.startswith("latency."):
        stat = name.split(".", 1)[1].replace("_ms", "").replace("_", " ")
        return f"Latency ({stat} ms)"
    if name.startswith("tokens."):
        key = name.split(".", 1)[1]
        mapping = {"total_tokens": "Total tokens", "mean_tokens_per_case": "Tokens per case"}
        return mapping.get(key, key.replace("_", " ").capitalize())
    if name.startswith("scorer."):
        _, scorer, metric = name.split(".", 2)
        return f"{scorer} — {metric.replace('_', ' ')}"
    if name.startswith("segment."):
        _, segment, scorer = name.split(".", 2)
        return f"{segment} / {scorer}"
    return name


@dataclass(frozen=True)
class ScorerExplanation:
    """One scorer's verdict on a case, with its human-readable reason."""

    name: str
    passed: bool
    score: float
    detail: str


@dataclass(frozen=True)
class CaseExplanation:
    """A presentation-ready view of one case: *why* it passed, failed, or errored.

    Pure and feature-agnostic — derived entirely from a stored :class:`CaseResult`
    (no I/O). This is the shared shape behind the per-case detail component, reused by
    the failures view, the test-log explorer, and root-cause drilldowns.
    """

    case_id: str
    difficulty: str
    passed: bool
    errored: bool
    input: dict[str, object]
    input_text: str  # best-effort primary text of the input (empty if not obvious)
    expected: dict[str, object]
    actual: dict[str, object] | None
    error: str | None
    scorers: tuple[ScorerExplanation, ...]
    failed_scorers: tuple[str, ...]
    summary: str  # one-line plain-English verdict


def _primary_input_text(input_data: dict[str, object]) -> str:
    """Return the single string field of an input dict, if there is exactly one."""
    str_values = [value for value in input_data.values() if isinstance(value, str)]
    return str_values[0] if len(str_values) == 1 else ""


def case_outcome(case: CaseResult) -> str:
    """Classify a case as ``"passed"``, ``"failed"``, or ``"errored"``."""
    if case.error is not None:
        return "errored"
    return "passed" if case.passed else "failed"


def case_category(case: CaseResult, segment_field: str | None) -> str | None:
    """The case's segment value (e.g. its category), or ``None`` if not applicable."""
    if not segment_field:
        return None
    value = case.expected_output.get(segment_field)
    return str(value) if value is not None else None


def filter_cases(
    cases: Sequence[CaseResult],
    *,
    outcomes: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    difficulties: Sequence[str] | None = None,
    search: str = "",
    segment_field: str | None = None,
) -> list[CaseResult]:
    """Filter cases by outcome, category, difficulty, and a text search (pure).

    A ``None`` filter means "no constraint" on that axis. Search matches the case id
    or any string value in the case's input, case-insensitively. The category filter
    only applies when ``segment_field`` is given.
    """
    needle = search.strip().lower()
    selected: list[CaseResult] = []
    for case in cases:
        if outcomes is not None and case_outcome(case) not in outcomes:
            continue
        if difficulties is not None and case.expected_difficulty.value not in difficulties:
            continue
        if (
            categories is not None
            and segment_field
            and case_category(case, segment_field) not in categories
        ):
            continue
        if needle:
            haystack = (case.case_id + " " + " ".join(str(v) for v in case.input.values())).lower()
            if needle not in haystack:
                continue
        selected.append(case)
    return selected


def _scorer_did_not_pass(case: CaseResult, scorer_name: str) -> bool:
    """True if the case has a score for ``scorer_name`` that did not pass.

    Errored cases (no scores) return False: the aggregator excludes them from a
    scorer's mean/pass-rate, so they don't drag a scorer metric (they drag pass_rate).
    """
    return any(s.name == scorer_name and not s.passed for s in case.scores)


def cases_for_metric(
    metric_name: str,
    cases: Sequence[CaseResult],
    *,
    segment_field: str | None = None,
) -> list[CaseResult]:
    """The cases responsible for a regressed metric (pure; root-cause attribution).

    Mirrors how the aggregator builds each metric, so the returned cases are exactly
    those that dragged it down:

    - ``pass_rate`` -> every case that did not pass (includes errored).
    - ``errored`` -> every errored case.
    - ``scorer.<name>.*`` -> cases where that scorer did not pass.
    - ``segment.<seg>.<scorer>`` -> cases in that segment where the scorer did not pass.
    - ``latency.*`` / ``tokens.*`` -> none (aggregate, not attributable to failures).
    """
    if metric_name == "pass_rate":
        return [c for c in cases if not c.passed]
    if metric_name == "errored":
        return [c for c in cases if c.error is not None]
    if metric_name.startswith("scorer."):
        _, scorer, _stat = metric_name.split(".", 2)
        return [c for c in cases if _scorer_did_not_pass(c, scorer)]
    if metric_name.startswith("segment."):
        _, segment, scorer = metric_name.split(".", 2)
        return [
            c
            for c in cases
            if case_category(c, segment_field) == segment and _scorer_did_not_pass(c, scorer)
        ]
    return []


@dataclass(frozen=True)
class DatasetCaseView:
    """One golden-dataset case, for the dataset explorer (feature-agnostic)."""

    case_id: str
    input: dict[str, object]
    input_text: str
    expected: dict[str, object]
    difficulty: str
    notes: str


@dataclass(frozen=True)
class DatasetView:
    """A versioned golden dataset's description plus its labeled cases."""

    feature: str
    version: str
    description: str
    case_count: int
    cases: tuple[DatasetCaseView, ...]


def parse_dataset(raw: dict[str, object], *, feature: str) -> DatasetView:
    """Parse a raw dataset JSON dict into a :class:`DatasetView` (pure; no I/O).

    Feature-agnostic: ``input``/``expected_output`` are kept as plain dicts, so the
    dashboard never imports a feature's models. Includes the human ``notes``.
    """
    raw_cases = raw.get("cases", [])
    cases = tuple(
        DatasetCaseView(
            case_id=str(case.get("id", "")),
            input=dict(case.get("input", {})),
            input_text=_primary_input_text(dict(case.get("input", {}))),
            expected=dict(case.get("expected_output", {})),
            difficulty=str(case.get("expected_difficulty", "")),
            notes=str(case.get("notes", "")),
        )
        for case in raw_cases
        if isinstance(case, dict)
    )
    return DatasetView(
        feature=feature,
        version=str(raw.get("version", "")),
        description=str(raw.get("description", "")),
        case_count=len(cases),
        cases=cases,
    )


def _dataset_version_number(version: str) -> int:
    """Numeric component of a ``vN`` version label, or -1 if it doesn't match."""
    return int(version[1:]) if version.startswith("v") and version[1:].isdigit() else -1


@dataclass(frozen=True)
class CategoryGap:
    """How many cases in one category are failing, and the pass-rate points at stake."""

    category: str
    failing: int
    recoverable_points: float  # failing / total — pass-rate points if these all passed


@dataclass(frozen=True)
class RunRecommendations:
    """A structured 'what would make this run perfect' summary (pure; numbers only).

    Prose framing lives in the page; this carries only computed facts so it is
    trivially testable and never over-claims.
    """

    is_perfect: bool
    total_cases: int
    failing_cases: int
    current_pass_rate: float
    points_to_recover: float  # 1.0 - current_pass_rate
    gap_to_baseline: float | None  # baseline - current, only if currently below baseline
    by_category: tuple[CategoryGap, ...]


def perfect_run_recommendations(
    cases: Sequence[CaseResult],
    *,
    segment_field: str | None = None,
    baseline_pass_rate: float | None = None,
) -> RunRecommendations:
    """Summarise the gap between a run and a perfect (all-passing) run.

    A case counts as failing if it did not pass (includes errored). ``recoverable_points``
    is the exact pass-rate gain if a category's failing cases all passed; the page words
    this as an upper bound ("up to") to avoid implying other checks can't still fail.
    """
    total = len(cases)
    failing = [c for c in cases if not c.passed]
    current = (total - len(failing)) / total if total else 0.0

    by_category: tuple[CategoryGap, ...] = ()
    if segment_field and failing:
        counts: dict[str, int] = {}
        for case in failing:
            category = case_category(case, segment_field) or "unknown"
            counts[category] = counts.get(category, 0) + 1
        by_category = tuple(
            CategoryGap(
                category=category,
                failing=count,
                recoverable_points=count / total if total else 0.0,
            )
            # Most failures first; ties broken by name for determinism.
            for category, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )

    gap_to_baseline = (
        baseline_pass_rate - current
        if baseline_pass_rate is not None and current < baseline_pass_rate
        else None
    )

    return RunRecommendations(
        is_perfect=not failing,
        total_cases=total,
        failing_cases=len(failing),
        current_pass_rate=current,
        points_to_recover=max(0.0, 1.0 - current),
        gap_to_baseline=gap_to_baseline,
        by_category=by_category,
    )


def explain_case(case: CaseResult) -> CaseExplanation:
    """Derive a plain-English explanation of a single case's outcome (pure).

    Surfaces what was already stored but never shown: the model's ``actual`` output
    against the ``expected`` output, and each scorer's ``detail`` reason.
    """
    errored = case.error is not None
    scorers = tuple(
        ScorerExplanation(name=s.name, passed=s.passed, score=s.score, detail=s.detail)
        for s in case.scores
    )
    failed_scorers = tuple(s.name for s in scorers if not s.passed)

    if errored:
        summary = f"Errored — {case.error}"
    elif case.passed:
        summary = "All checks passed."
    else:
        failing = [s for s in scorers if not s.passed]
        summary = (
            "; ".join(f"{s.name}: {s.detail}" for s in failing if s.detail)
            or "; ".join(s.name for s in failing)
            or "Marked failed."
        )

    return CaseExplanation(
        case_id=case.case_id,
        difficulty=case.expected_difficulty.value,
        passed=case.passed,
        errored=errored,
        input=case.input,
        input_text=_primary_input_text(case.input),
        expected=case.expected_output,
        actual=case.actual_output,
        error=case.error,
        scorers=scorers,
        failed_scorers=failed_scorers,
        summary=summary,
    )


class DashboardData:
    """Read-only queries backing the dashboard pages."""

    def __init__(self, store: EvaluationStore) -> None:
        self._store = store

    def features(self) -> list[str]:
        """Feature names that have at least one recorded run."""
        return self._store.runs.features()

    def runs(self, feature: str, *, limit: int = 100) -> list[RunRecord]:
        """Most-recent-first runs for a feature."""
        return self._store.runs.list_for_feature(feature, limit=limit)

    def run_labels(self, feature: str, *, limit: int = 100) -> list[RunLabel]:
        """Human-readable labels for a feature's runs, most-recent-first.

        Built from the lightweight run rows plus a per-distinct-id dataset-version
        lookup (cached) — never a full per-run reconstruction. The per-feature
        sequence number is assigned within the returned window (oldest = #1).
        """
        runs = self.runs(feature, limit=limit)
        total = len(runs)
        version_cache: dict[int, str] = {}
        labels: list[RunLabel] = []
        for index, record in enumerate(runs):
            labels.append(
                build_run_label(
                    run_uuid=record.run_uuid,
                    feature=record.feature_name,
                    sequence=total - index,  # most-recent-first list -> newest gets the highest #
                    model=record.model,
                    dataset_version=self._dataset_version(record.dataset_version_id, version_cache),
                    started_at=record.started_at,
                )
            )
        return labels

    def run_label_map(self, feature: str, *, limit: int = 100) -> dict[str, RunLabel]:
        """``run_uuid -> RunLabel`` for a feature's runs (for lookup by uuid)."""
        return {label.run_uuid: label for label in self.run_labels(feature, limit=limit)}

    def dataset_view(self, feature: str) -> DatasetView | None:
        """The latest golden dataset for a feature, read from the database (or ``None``).

        The database is the system of record: this reads the highest-version
        ``dataset_versions`` row's persisted content, so both built-in and onboarded
        features resolve the same way, in any process.
        """
        rows = [r for r in self._store.dataset_versions.all() if r.feature_name == feature]
        rows = [r for r in rows if r.content]
        if not rows:
            return None
        latest = max(rows, key=lambda r: _dataset_version_number(r.version))
        return parse_dataset(json.loads(latest.content), feature=feature)

    def segment_field_for(self, feature: str) -> str | None:
        """The segment field (e.g. ``category``) used by the feature's latest run."""
        runs = self.runs(feature, limit=1)
        if not runs:
            return None
        return AggregateMetrics.model_validate_json(runs[0].metrics_json).segment_field

    def baseline_pass_rate(self, feature: str) -> float | None:
        """The active baseline's pass rate, for a 'vs baseline' verdict, or ``None``.

        Reads the baseline run's stored metrics snapshot (no full reconstruction).
        """
        baseline = self.active_baseline(feature)
        if baseline is None:
            return None
        run = self._store.runs.get_by_id(baseline.run_id)
        if run is None:
            return None
        return AggregateMetrics.model_validate_json(run.metrics_json).pass_rate

    def feature_overview(self, feature: str, *, limit: int = 100) -> FeatureOverview:
        """Headline status for a feature: run count, latest pass rate, and health.

        Health is the worst regression severity recorded against the **latest** run.
        Stats come from the lightweight run rows (latest pass rate is read from the
        stored ``metrics_json`` snapshot — no per-case reconstruction).
        """
        runs = self.runs(feature, limit=limit)
        if not runs:
            return FeatureOverview(
                feature=feature,
                display_name=_humanize_feature(feature),
                run_count=0,
                latest_run_label=None,
                latest_pass_rate=None,
                runs_with_regressions=0,
                health="unknown",
            )

        latest = runs[0]
        latest_pass_rate = AggregateMetrics.model_validate_json(latest.metrics_json).pass_rate
        labels = self.run_label_map(feature, limit=limit)
        latest_label = labels[latest.run_uuid].label if latest.run_uuid in labels else None
        runs_with_regressions = sum(1 for run in runs if self.regressions_for_run(run.run_uuid))
        latest_health = _health_from_severities(
            [r.severity for r in self.regressions_for_run(latest.run_uuid)]
        )
        return FeatureOverview(
            feature=feature,
            display_name=_humanize_feature(feature),
            run_count=len(runs),
            latest_run_label=latest_label,
            latest_pass_rate=latest_pass_rate,
            runs_with_regressions=runs_with_regressions,
            health=latest_health,
        )

    def _dataset_version(self, dataset_version_id: int | None, cache: dict[int, str]) -> str:
        """Resolve a dataset version string by id, caching distinct lookups."""
        if dataset_version_id is None:
            return ""
        if dataset_version_id not in cache:
            record = self._store.dataset_versions.get_by_id(dataset_version_id)
            cache[dataset_version_id] = record.version if record else ""
        return cache[dataset_version_id]

    def run_detail(self, run_uuid: str) -> EvaluationResult | None:
        """Full reconstructed run (metadata, metrics, per-case results)."""
        return self._store.get_evaluation_result(run_uuid)

    def compare_runs(self, run_a_uuid: str, run_b_uuid: str) -> RegressionResult | None:
        """Compare two runs directly (A = reference, B = new); deltas are ``B - A``.

        Reuses the feature-agnostic :class:`RegressionDetector` — no new comparison
        math. Reconstructs both runs (two reconstructions is cheap). Returns ``None``
        if either run is missing. Both runs must belong to the same feature (the page
        only offers same-feature runs); the detector enforces this otherwise.
        """
        run_a = self.run_detail(run_a_uuid)
        run_b = self.run_detail(run_b_uuid)
        if run_a is None or run_b is None:
            return None
        return RegressionDetector().compare(run_a, run_b)

    def regressions_for_run(self, run_uuid: str) -> list[RegressionRecord]:
        """Persisted regressions where ``run_uuid`` is the candidate."""
        run = self._store.runs.get_by_uuid(run_uuid)
        if run is None:
            return []
        return self._store.regressions.list_for_run(run.id)

    def active_baseline(self, feature: str) -> BaselineRecord | None:
        """The currently active baseline for a feature, if any."""
        return self._store.baselines.get_active(feature)

    def baseline_history(self, feature: str) -> list[BaselineRecord]:
        """All baseline promotions for a feature, most recent first."""
        return self._store.baselines.history(feature)

    def run_uuid_for(self, run_db_id: int) -> str | None:
        """Resolve a run's UUID from its database id (for baseline display)."""
        run = self._store.runs.get_by_id(run_db_id)
        return run.run_uuid if run else None

    def trend(self, feature: str, *, limit: int = 100) -> list[TrendPoint]:
        """Chronological metric series for a feature, parsed from run snapshots."""
        points: list[TrendPoint] = []
        for record in reversed(self.runs(feature, limit=limit)):  # oldest -> newest
            metrics = AggregateMetrics.model_validate_json(record.metrics_json)
            points.append(
                TrendPoint(
                    run_uuid=record.run_uuid,
                    started_at=record.started_at,
                    pass_rate=metrics.pass_rate,
                    errored=metrics.errored,
                    mean_latency_ms=metrics.latency.mean_ms,
                    p95_latency_ms=metrics.latency.p95_ms,
                    total_tokens=metrics.tokens.total_tokens,
                    scorer_means={name: s.mean_score for name, s in metrics.scorers.items()},
                )
            )
        return points
