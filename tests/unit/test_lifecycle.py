"""Tests for the unified Create → Activate → Evaluate → View Results lifecycle."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from mrds.activation.lifecycle import activate_bundle, run_first_evaluation
from mrds.core.registry import FeatureRegistry
from mrds.dashboard.data import DashboardData
from mrds.db import EvaluationStore, open_database
from mrds.llm.base import LLMMessage, LLMResult
from mrds.onboarding import infer_feature_spec, scaffold_prompt, write_feature_bundle

_RAW = {
    "cases": [
        {
            "id": "c1",
            "input": {"text": "please refund my charge"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c2",
            "input": {"text": "the app keeps crashing"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c3",
            "input": {"text": "i need to reset my password"},
            "expected_output": {"category": "account"},
        },
        {
            "id": "c4",
            "input": {"text": "send me this months invoice"},
            "expected_output": {"category": "billing"},
        },
    ]
}
_ORACLE = {c["input"]["text"]: c["expected_output"]["category"] for c in _RAW["cases"]}


class _Stub:
    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type
    ) -> LLMResult:
        label = _ORACLE.get(messages[-1].content, "billing")
        return LLMResult(
            parsed=schema.model_validate({"category": label}),
            model=model,
            input_tokens=5,
            output_tokens=2,
            total_tokens=7,
        )


def _onboard(tmp_path: Path, name: str = "support_cls") -> Path:
    spec = infer_feature_spec(_RAW, feature_name=name, feature_type="classification")
    prompt = scaffold_prompt(spec, feature_type="classification")
    return write_feature_bundle(
        spec, cases=_RAW["cases"], system_prompt=prompt, root=tmp_path / "work"
    ).bundle_dir


def test_activate_bundle_installs_and_registers(tmp_path: Path) -> None:
    bundle = _onboard(tmp_path)
    root = tmp_path / "platform"
    registry = FeatureRegistry()

    installed = activate_bundle(bundle, root=root, registry=registry)

    assert installed.feature_name == "support_cls"
    assert installed.spec.exists()
    assert "support_cls" in registry


def test_run_first_evaluation_persists_and_is_visible(tmp_path: Path) -> None:
    bundle = _onboard(tmp_path)
    root = tmp_path / "platform"
    installed = activate_bundle(bundle, root=root, registry=FeatureRegistry())

    store = EvaluationStore(open_database(":memory:"))
    result = run_first_evaluation(installed, root=root, store=store, client=_Stub())

    assert result.feature == "support_cls"
    assert result.aggregate_metrics.total_cases == 4
    assert result.aggregate_metrics.pass_rate == pytest.approx(1.0)

    data = DashboardData(store)
    assert "support_cls" in data.features()
    assert [r.run_uuid for r in data.runs("support_cls")] == [result.run_id]


def test_full_create_activate_evaluate_view(tmp_path: Path) -> None:
    # Create
    bundle = _onboard(tmp_path, name="cust_router")
    root = tmp_path / "platform"
    store = EvaluationStore(open_database(":memory:"))

    # Activate
    installed = activate_bundle(bundle, root=root, registry=FeatureRegistry())
    # Evaluate
    result = run_first_evaluation(installed, root=root, store=store, client=_Stub())
    # View Results (via DashboardData — what the dashboard renders)
    data = DashboardData(store)
    detail = data.run_detail(result.run_id)

    assert "cust_router" in data.features()
    assert detail is not None
    assert set(detail.aggregate_metrics.scorers) == {"category_match"}
    assert set(detail.aggregate_metrics.segments) == {"account", "billing", "technical"}
