"""Phase 2: a spec-only feature flows end-to-end through the unchanged platform.

Proves the chain:  FeatureSpec → GenericStructuredFeature → EvaluationEngine →
Metrics → EvaluationStore → RegressionDetector → DashboardData.

The PoC's prompt + dataset live in a **self-contained bundle** under
``features/sentiment_poc/`` (not the shared prompts/ + datasets/ roots), and the
feature is registered in a **local** registry — so no global wiring and no impact on
existing features. All runs use a deterministic offline client (no OpenAI).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from mrds.core.registry import FeatureRegistry
from mrds.dashboard.data import DashboardData
from mrds.datasets.registry import DatasetRegistry
from mrds.db import EvaluationStore, open_database
from mrds.evaluation import EvaluationConfig, EvaluationEngine
from mrds.evaluation.models import EvaluationResult
from mrds.features.spec import build_from_spec, load_feature_spec
from mrds.llm.base import LLMMessage, LLMResult
from mrds.prompts.registry import PromptRegistry
from mrds.regression import RegressionDetector

_BUNDLE = Path("features/sentiment_poc")
_SPEC = load_feature_spec(_BUNDLE / "feature.yaml")
_PROMPTS = PromptRegistry.from_directory(_BUNDLE / "prompts")

# Oracle built from the raw dataset JSON (no typed models needed for the stub).
_RAW = json.loads((_BUNDLE / "datasets" / "sentiment_poc" / "v1.json").read_text(encoding="utf-8"))
_ORACLE = {c["input"]["text"]: c["expected_output"]["sentiment"] for c in _RAW["cases"]}
_ORDERED_TEXTS = [c["input"]["text"] for c in _RAW["cases"]]
_LABELS = ["positive", "negative", "neutral"]


class _SentimentStub:
    """Deterministic offline client: routes from the oracle, misclassifies a wrong set."""

    def __init__(self, wrong: frozenset[str]) -> None:
        self._wrong = wrong

    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type
    ) -> LLMResult:
        text = messages[-1].content
        label = _ORACLE.get(text, "neutral")
        if text in self._wrong:
            label = _LABELS[(_LABELS.index(label) + 1) % len(_LABELS)]
        return LLMResult(
            parsed=schema.model_validate({"sentiment": label}),
            model=model,
            input_tokens=8,
            output_tokens=2,
            total_tokens=10,
        )


def _run(wrong: frozenset[str]) -> EvaluationResult:
    """Build the spec feature + isolated dataset registry and run one evaluation."""
    feature = build_from_spec(_SPEC, client=_SentimentStub(wrong), prompt_registry=_PROMPTS)
    # Isolated bundle dir holds only this dataset, so a scoped resolver is safe.
    datasets = DatasetRegistry.from_directory(
        _BUNDLE / "datasets",
        model_resolver=lambda _f: (feature.input_model, feature.output_model),
    )
    registry = FeatureRegistry()
    registry.register(feature)
    engine = EvaluationEngine(features=registry, prompts=_PROMPTS, datasets=datasets)
    return engine.run(EvaluationConfig(feature="sentiment_poc", segment_field="sentiment"))


# -- spec → generated feature → engine → metrics --------------------------------


def test_spec_only_feature_runs_through_engine() -> None:
    result = _run(frozenset())
    metrics = result.aggregate_metrics
    assert result.feature == "sentiment_poc"
    assert metrics.total_cases == 9
    assert metrics.pass_rate == pytest.approx(1.0)  # oracle-perfect baseline
    # The scorer declared in the spec is discovered and aggregated generically.
    assert set(metrics.scorers) == {"sentiment_match"}
    # Segmented by the spec's segment_field, with no engine awareness.
    assert metrics.segment_field == "sentiment"
    assert set(metrics.segments) == {"positive", "negative", "neutral"}


# -- … → store → regression → DashboardData -------------------------------------


def test_full_chain_store_regression_and_dashboard() -> None:
    store = EvaluationStore(open_database(":memory:"))

    good = _run(frozenset())
    store.save_evaluation(good, triggered_by="test")
    store.promote_baseline(good.run_id, promoted_by="test", note="poc baseline")

    # Degrade the last four cases -> a clear quality drop vs the baseline.
    wrong = frozenset(_ORDERED_TEXTS[-4:])
    bad = _run(wrong)
    store.save_evaluation(bad, triggered_by="test")

    regression = RegressionDetector().compare(good, bad)
    store.save_regression(regression)

    data = DashboardData(store)
    # DashboardData shows the spec-defined feature.
    assert "sentiment_poc" in data.features()
    # Runs appear.
    assert {r.run_uuid for r in data.runs("sentiment_poc")} == {good.run_id, bad.run_id}
    # Metrics reconstruct (5 of 9 correct after degrading 4).
    detail = data.run_detail(bad.run_id)
    assert detail is not None
    assert detail.aggregate_metrics.pass_rate == pytest.approx(5 / 9)
    # Regression detection works for the spec-defined feature.
    regs = data.regressions_for_run(bad.run_id)
    assert regs
    assert any("sentiment_match" in r.metric or r.metric == "pass_rate" for r in regs)
