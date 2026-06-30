"""FastAPI HTTP layer — a thin, feature-agnostic API over the platform.

This is a *presentation* layer in the same spirit as the dashboard: it adds no
evaluation logic. Every endpoint reuses the existing read-only :class:`DashboardData`
seam (or, for promotion, the existing :class:`EvaluationStore` /
:class:`BaselinePromoter`) and hands the result to a serializer. It contains **zero**
feature-specific branches, consistent with the platform's feature-agnostic core.

Each request gets its own :class:`ApiSession` (one SQLite connection) via the
``get_session`` dependency — see ``runtime.py`` for why sharing one connection across
FastAPI's threadpool is unsafe. Run it with ``python -m mrds.api``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from mrds.activation import ActivationError
from mrds.activation.lifecycle import activate_feature_from_store
from mrds.api.runtime import ApiSession
from mrds.api.serializers import (
    health_from_records,
    resolve_prompt_version,
    serialize_baseline,
    serialize_case,
    serialize_comparison,
    serialize_dataset,
    serialize_overview,
    serialize_recommendations,
    serialize_run_detail,
    serialize_run_summary,
    serialize_trend_point,
)
from mrds.config.settings import get_settings
from mrds.dashboard.data import (
    DashboardData,
    cases_for_metric,
    perfect_run_recommendations,
)
from mrds.db.records import BaselineRecord
from mrds.evaluation.models import AggregateMetrics
from mrds.llm.base import StructuredLLMClient
from mrds.llm.errors import LLMConfigurationError
from mrds.onboarding.errors import OnboardingError
from mrds.onboarding.inference import infer_feature_spec
from mrds.onboarding.scaffold import scaffold_prompt
from mrds.regression.models import Baseline, BaselineCandidate
from mrds.regression.promotion import BaselinePromoter


def get_session() -> Iterator[ApiSession]:
    """FastAPI dependency: a request-scoped DB session, always closed afterwards."""
    session = ApiSession()
    try:
        yield session
    finally:
        session.close()


def get_platform_root() -> Path:
    """FastAPI dependency: the writable root where activated bundles are installed."""
    return Path(get_settings().platform_root)


def get_llm_client() -> StructuredLLMClient | None:
    """FastAPI dependency: the evaluation LLM client.

    ``None`` defers to the real, settings-configured Anthropic client at run time; tests
    override this to inject a deterministic offline stub.
    """
    return None


def create_app() -> FastAPI:
    """Build the FastAPI application (factory; used by ``__main__`` and tests)."""
    app = FastAPI(
        title="MRDS Evaluation OS API",
        version="1.0.0",
        summary="HTTP surface for the AI evaluation platform.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _register_routes(app)
    return app


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now()


# ---------------------------------------------------------------------------
# Enrichment helpers (feature-agnostic; compose data-layer reads)
# ---------------------------------------------------------------------------


def _baseline_run_uuid(
    data: DashboardData, feature: str
) -> tuple[BaselineRecord | None, str | None]:
    record = data.active_baseline(feature)
    if record is None:
        return None, None
    return record, data.run_uuid_for(record.run_id)


def _run_pass_rate(data: DashboardData, run_db_id: int) -> float | None:
    run = data._store.runs.get_by_id(run_db_id)  # noqa: SLF001
    if run is None:
        return None
    return AggregateMetrics.model_validate_json(run.metrics_json).pass_rate


def _overview_payload(data: DashboardData, feature: str) -> dict[str, Any]:
    overview = data.feature_overview(feature)
    baseline_pr = data.baseline_pass_rate(feature)
    segment_field = data.segment_field_for(feature)
    labels = data.run_label_map(feature)
    latest = data.runs(feature, limit=1)
    latest_uuid = latest[0].run_uuid if latest else None
    sparkline = [
        {
            "sequence": labels[p.run_uuid].sequence if p.run_uuid in labels else i + 1,
            "label": labels[p.run_uuid].short_label if p.run_uuid in labels else p.run_uuid[:8],
            "pass_rate": p.pass_rate,
        }
        for i, p in enumerate(data.trend(feature))
    ]
    return serialize_overview(
        overview,
        baseline_pass_rate=baseline_pr,
        segment_field=segment_field,
        latest_run_uuid=latest_uuid,
        sparkline=sparkline,
    )


def _runs_payload(data: DashboardData, feature: str) -> list[dict[str, Any]]:
    records = data.runs(feature)
    labels = data.run_label_map(feature)
    _, baseline_uuid = _baseline_run_uuid(data, feature)
    payload: list[dict[str, Any]] = []
    for record in records:
        label = labels[record.run_uuid]
        health = health_from_records(data.regressions_for_run(record.run_uuid))
        payload.append(
            serialize_run_summary(
                record,
                label,
                health=health,
                is_baseline=record.run_uuid == baseline_uuid,
                prompt_version=resolve_prompt_version(data, record.prompt_version_id),
            )
        )
    return payload


def _run_detail_payload(session: ApiSession, run_uuid: str) -> dict[str, Any]:
    data = session.data
    result = data.run_detail(run_uuid)
    if result is None:
        raise HTTPException(status_code=404, detail=f"run '{run_uuid}' not found")

    feature = result.feature
    record = session.store.runs.get_by_uuid(run_uuid)
    labels = data.run_label_map(feature)
    label = labels.get(run_uuid)
    health = health_from_records(data.regressions_for_run(run_uuid))

    _, baseline_uuid = _baseline_run_uuid(data, feature)
    is_baseline = baseline_uuid == run_uuid
    baseline_pr = None if is_baseline else data.baseline_pass_rate(feature)
    baseline_label = (
        labels[baseline_uuid].label if (baseline_uuid and baseline_uuid in labels) else None
    )

    regression = None
    if baseline_uuid and not is_baseline:
        regression = data.compare_runs(baseline_uuid, run_uuid)

    segment_field = result.aggregate_metrics.segment_field
    recommendations = perfect_run_recommendations(
        result.per_case_results,
        segment_field=segment_field,
        baseline_pass_rate=baseline_pr,
    )
    return serialize_run_detail(
        result,
        label=label,
        prompt_version=resolve_prompt_version(data, record.prompt_version_id) if record else "",
        triggered_by=record.triggered_by if record else "",
        status=record.status if record else "completed",
        health=health,
        is_baseline=is_baseline,
        baseline_pass_rate=baseline_pr,
        baseline_label=baseline_label,
        baseline_run_uuid=None if is_baseline else baseline_uuid,
        regression=regression,
        recommendations=recommendations,
    )


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class PromoteRequest(BaseModel):
    run_uuid: str
    promoted_by: str = "dashboard"
    note: str = ""
    force: bool = Field(default=False, description="Promote even if the run has regressions.")


class InferRequest(BaseModel):
    feature_name: str
    feature_type: str = "classification"
    cases: list[dict[str, Any]]


class ActivateRequest(BaseModel):
    feature_name: str
    feature_type: str = "classification"
    cases: list[dict[str, Any]]
    system_prompt: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _register_routes(app: FastAPI) -> None:  # noqa: C901 - a flat list of thin handlers
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "mrds-evaluation-os"}

    @app.get("/api/features")
    def list_features(session: ApiSession = Depends(get_session)) -> list[dict[str, Any]]:
        data = session.data
        return [_overview_payload(data, feature) for feature in data.features()]

    @app.get("/api/features/{feature}")
    def feature_overview(
        feature: str, session: ApiSession = Depends(get_session)
    ) -> dict[str, Any]:
        data = session.data
        if feature not in data.features():
            raise HTTPException(status_code=404, detail=f"feature '{feature}' not found")
        return _overview_payload(data, feature)

    @app.get("/api/features/{feature}/runs")
    def feature_runs(
        feature: str, session: ApiSession = Depends(get_session)
    ) -> list[dict[str, Any]]:
        return _runs_payload(session.data, feature)

    @app.get("/api/features/{feature}/trend")
    def feature_trend(
        feature: str, session: ApiSession = Depends(get_session)
    ) -> list[dict[str, Any]]:
        data = session.data
        labels = data.run_label_map(feature)
        return [serialize_trend_point(p, labels.get(p.run_uuid)) for p in data.trend(feature)]

    @app.get("/api/features/{feature}/dataset")
    def feature_dataset(feature: str, session: ApiSession = Depends(get_session)) -> dict[str, Any]:
        data = session.data
        view = data.dataset_view(feature)
        if view is None:
            raise HTTPException(status_code=404, detail=f"no dataset for feature '{feature}'")
        return serialize_dataset(view, segment_field=data.segment_field_for(feature))

    @app.get("/api/features/{feature}/baseline")
    def feature_baseline(
        feature: str, session: ApiSession = Depends(get_session)
    ) -> dict[str, Any]:
        data = session.data
        labels = data.run_label_map(feature)

        def to_payload(record: BaselineRecord) -> dict[str, Any]:
            run_uuid = data.run_uuid_for(record.run_id)
            label = labels[run_uuid].label if (run_uuid and run_uuid in labels) else None
            return serialize_baseline(
                record,
                run_uuid=run_uuid,
                run_label=label,
                pass_rate=_run_pass_rate(data, record.run_id),
            )

        active = data.active_baseline(feature)
        return {
            "active": to_payload(active) if active else None,
            "history": [to_payload(r) for r in data.baseline_history(feature)],
        }

    @app.post("/api/features/{feature}/baseline/promote")
    def promote_baseline(
        feature: str, body: PromoteRequest, session: ApiSession = Depends(get_session)
    ) -> dict[str, Any]:
        data = session.data
        candidate = data.run_detail(body.run_uuid)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"run '{body.run_uuid}' not found")

        current_result = session.store.get_active_baseline_result(feature)
        active_record = data.active_baseline(feature)
        current = (
            Baseline(
                feature=feature,
                result=current_result,
                promoted_at=_parse_dt(active_record.promoted_at),
                promoted_by=active_record.promoted_by,
                note=active_record.note,
            )
            if current_result is not None and active_record is not None
            else None
        )

        promoter = BaselinePromoter()
        eligibility = promoter.check(BaselineCandidate(result=candidate), current)
        eligibility_payload = {
            "eligible": eligibility.eligible,
            "reasons": eligibility.reasons,
            "severity": eligibility.severity.value if eligibility.severity else None,
        }

        if not eligibility.eligible and not body.force:
            return {
                "promoted": False,
                "eligibility": eligibility_payload,
                "message": (
                    "Run has regressions vs the current baseline. Pass force=true to override."
                ),
            }

        session.store.promote_baseline(body.run_uuid, promoted_by=body.promoted_by, note=body.note)
        new_record = data.active_baseline(feature)
        labels = data.run_label_map(feature)
        run_uuid = data.run_uuid_for(new_record.run_id) if new_record else None
        return {
            "promoted": True,
            "forced": not eligibility.eligible,
            "eligibility": eligibility_payload,
            "baseline": serialize_baseline(
                new_record,
                run_uuid=run_uuid,
                run_label=labels[run_uuid].label if (run_uuid and run_uuid in labels) else None,
                pass_rate=_run_pass_rate(data, new_record.run_id) if new_record else None,
            )
            if new_record
            else None,
        }

    @app.get("/api/runs/{run_uuid}")
    def run_detail(run_uuid: str, session: ApiSession = Depends(get_session)) -> dict[str, Any]:
        return _run_detail_payload(session, run_uuid)

    @app.get("/api/runs/{run_uuid}/regressions")
    def run_regressions(
        run_uuid: str, session: ApiSession = Depends(get_session)
    ) -> dict[str, Any]:
        data = session.data
        result = data.run_detail(run_uuid)
        if result is None:
            raise HTTPException(status_code=404, detail=f"run '{run_uuid}' not found")
        feature = result.feature
        _, baseline_uuid = _baseline_run_uuid(data, feature)
        comparison = (
            data.compare_runs(baseline_uuid, run_uuid)
            if baseline_uuid and baseline_uuid != run_uuid
            else None
        )
        segment_field = result.aggregate_metrics.segment_field
        root_cause: dict[str, list[dict[str, Any]]] = {}
        if comparison is not None:
            for metric in comparison.regressions:
                cases = cases_for_metric(
                    metric.name, result.per_case_results, segment_field=segment_field
                )
                if cases:
                    root_cause[metric.name] = [serialize_case(c) for c in cases]
        persisted = [
            {
                "metric": r.metric,
                "baseline_value": r.baseline_value,
                "candidate_value": r.candidate_value,
                "delta": r.delta,
                "severity": r.severity,
            }
            for r in data.regressions_for_run(run_uuid)
        ]
        return {
            "run_uuid": run_uuid,
            "feature": feature,
            "has_baseline": baseline_uuid is not None,
            "comparison": serialize_comparison(comparison) if comparison else None,
            "root_cause": root_cause,
            "persisted": persisted,
        }

    @app.get("/api/runs/{run_uuid}/recommendations")
    def run_recommendations(
        run_uuid: str, session: ApiSession = Depends(get_session)
    ) -> dict[str, Any]:
        data = session.data
        result = data.run_detail(run_uuid)
        if result is None:
            raise HTTPException(status_code=404, detail=f"run '{run_uuid}' not found")
        rec = perfect_run_recommendations(
            result.per_case_results,
            segment_field=result.aggregate_metrics.segment_field,
            baseline_pass_rate=data.baseline_pass_rate(result.feature),
        )
        return serialize_recommendations(rec)

    @app.get("/api/compare")
    def compare(
        a: str = Query(..., description="Reference run uuid (baseline side)."),
        b: str = Query(..., description="Candidate run uuid (new side)."),
        session: ApiSession = Depends(get_session),
    ) -> dict[str, Any]:
        comparison = session.data.compare_runs(a, b)
        if comparison is None:
            raise HTTPException(status_code=404, detail="one or both runs not found")
        return serialize_comparison(comparison)

    @app.post("/api/onboarding/infer")
    def onboarding_infer(body: InferRequest) -> dict[str, Any]:
        try:
            spec = infer_feature_spec(
                {"cases": body.cases},
                feature_name=body.feature_name,
                feature_type=body.feature_type,
            )
            prompt = scaffold_prompt(spec, feature_type=body.feature_type)
        except OnboardingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"spec": spec.model_dump(mode="json"), "prompt": prompt}

    @app.post("/api/onboarding/activate")
    def onboarding_activate(
        body: ActivateRequest,
        session: ApiSession = Depends(get_session),
        client: StructuredLLMClient | None = Depends(get_llm_client),
    ) -> dict[str, Any]:
        """Activate an onboarded feature end-to-end: persist → register → evaluate.

        Stitches the existing onboarding/activation/evaluation pieces together (it adds no
        evaluation or persistence logic of its own): re-infers the spec from the labeled
        cases, persists the spec/prompt/dataset to the database, runs the first evaluation
        through the unchanged engine reading the bundle back from the database, persists the
        run, and promotes the result as the initial baseline. This is **filesystem-free** —
        the database is the system of record, so it works on a read-only platform root.
        After this returns, the feature has a persisted run and appears in Mission Control.
        """
        # Fail fast (before writing anything) if there's no way to run the evaluation, so we
        # never fabricate an all-errored 0% baseline. Only relevant when no client is injected.
        if client is None and not get_settings().anthropic_api_key:
            raise HTTPException(
                status_code=422,
                detail=(
                    "ANTHROPIC_API_KEY is not configured, so the first evaluation cannot run. "
                    "Set it on the server and retry activation."
                ),
            )
        try:
            spec = infer_feature_spec(
                {"cases": body.cases},
                feature_name=body.feature_name,
                feature_type=body.feature_type,
            )
            # DB-native activation: persist the bundle and evaluate it without touching the
            # filesystem. A duplicate name surfaces as an ActivationError -> 400.
            result = activate_feature_from_store(
                spec,
                cases=body.cases,
                system_prompt=body.system_prompt,
                store=session.store,
                client=client,
                triggered_by="onboarding",
            )
        except (OnboardingError, ActivationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # First run for the feature — nothing to regress against — so promote directly
        # through the store (no BaselinePromoter eligibility gate applies to a first baseline).
        baseline = session.store.promote_baseline(
            result.run_id, promoted_by="onboarding", note="Initial baseline"
        )
        metrics = result.aggregate_metrics
        return {
            "feature": result.feature,
            "run_id": result.run_id,
            "baseline_id": baseline.id,
            "summary": {
                "total_cases": metrics.total_cases,
                "passed": metrics.passed,
                "failed": metrics.failed,
                "errored": metrics.errored,
                "pass_rate": metrics.pass_rate,
            },
        }


app = create_app()
