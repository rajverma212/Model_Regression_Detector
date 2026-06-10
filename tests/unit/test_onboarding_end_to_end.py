"""Headline test: an onboarded bundle is a genuine, runnable spec-driven feature.

raw dataset + name + instructions  →  infer → scaffold → write bundle  →  load bundle
→ run through the unchanged engine (stub client) → metrics → store → regression →
DashboardData. No OpenAI, no global registration, no shared-dir writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from mrds.core.registry import FeatureRegistry
from mrds.dashboard.data import DashboardData
from mrds.datasets.registry import DatasetRegistry
from mrds.db import EvaluationStore, open_database
from mrds.evaluation import EvaluationConfig, EvaluationEngine
from mrds.features.spec import build_from_spec, load_feature_spec
from mrds.llm.base import LLMMessage, LLMResult
from mrds.onboarding import infer_feature_spec, scaffold_prompt, write_feature_bundle
from mrds.prompts.registry import PromptRegistry
from mrds.regression import RegressionDetector

_RAW = {
    "cases": [
        {
            "id": "c1",
            "input": {"text": "please refund my charge"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c2",
            "input": {"text": "send me an invoice"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c3",
            "input": {"text": "the app crashes on launch"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c4",
            "input": {"text": "error on the login page"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c5",
            "input": {"text": "reset my password"},
            "expected_output": {"category": "account"},
        },
        {
            "id": "c6",
            "input": {"text": "change my email address"},
            "expected_output": {"category": "account"},
        },
    ]
}
_ORACLE = {c["input"]["text"]: c["expected_output"]["category"] for c in _RAW["cases"]}
_ORDER = ["account", "billing", "technical"]


class _Stub:
    def __init__(self, wrong: frozenset[str]) -> None:
        self._wrong = wrong

    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type
    ) -> LLMResult:
        text = messages[-1].content
        label = _ORACLE.get(text, "billing")
        if text in self._wrong:
            label = _ORDER[(_ORDER.index(label) + 1) % len(_ORDER)]
        return LLMResult(
            parsed=schema.model_validate({"category": label}),
            model=model,
            input_tokens=6,
            output_tokens=2,
            total_tokens=8,
        )


def _onboard(tmp_path: Path) -> tuple[object, PromptRegistry, Path]:
    spec = infer_feature_spec(_RAW, feature_name="support_cls", feature_type="classification")
    prompt = scaffold_prompt(spec, feature_type="classification")
    paths = write_feature_bundle(spec, cases=_RAW["cases"], system_prompt=prompt, root=tmp_path)
    loaded = load_feature_spec(paths.feature_yaml)
    prompts = PromptRegistry.from_directory(paths.bundle_dir / "prompts")
    return loaded, prompts, paths.bundle_dir / "datasets"


def _run(tmp_path: Path, wrong: frozenset[str]):
    loaded, prompts, dataset_root = _onboard(tmp_path)
    feature = build_from_spec(loaded, client=_Stub(wrong), prompt_registry=prompts)
    datasets = DatasetRegistry.from_directory(
        dataset_root, model_resolver=lambda _f: (feature.input_model, feature.output_model)
    )
    registry = FeatureRegistry()
    registry.register(feature)
    engine = EvaluationEngine(features=registry, prompts=prompts, datasets=datasets)
    return engine.run(EvaluationConfig(feature="support_cls", segment_field="category"))


def test_onboarded_bundle_runs_end_to_end(tmp_path: Path) -> None:
    result = _run(tmp_path, frozenset())
    metrics = result.aggregate_metrics
    assert result.feature == "support_cls"
    assert metrics.total_cases == 6
    assert metrics.pass_rate == pytest.approx(1.0)
    assert set(metrics.scorers) == {"category_match"}
    assert set(metrics.segments) == {"account", "billing", "technical"}


def test_onboarded_bundle_supports_store_and_regression(tmp_path: Path) -> None:
    store = EvaluationStore(open_database(":memory:"))

    good = _run(tmp_path / "good", frozenset())
    store.save_evaluation(good, triggered_by="test")
    store.promote_baseline(good.run_id, promoted_by="test", note="baseline")

    wrong = frozenset(c["input"]["text"] for c in _RAW["cases"][-3:])
    bad = _run(tmp_path / "bad", wrong)
    store.save_evaluation(bad, triggered_by="test")
    store.save_regression(RegressionDetector().compare(good, bad))

    data = DashboardData(store)
    assert "support_cls" in data.features()
    assert {r.run_uuid for r in data.runs("support_cls")} == {good.run_id, bad.run_id}
    regs = data.regressions_for_run(bad.run_id)
    assert regs
    assert any("category_match" in r.metric or r.metric == "pass_rate" for r in regs)
