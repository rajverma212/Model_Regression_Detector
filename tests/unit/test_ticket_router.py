"""End-to-end onboarding test for the support-ticket-router feature.

Validates that a *second* feature evaluates through the unchanged core pipeline —
engine, metrics, store, regression detector — and surfaces via the dashboard's
data seam, all offline (no OpenAI), using the feature's existing client-injection
extension point.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from mrds.core.registry import FeatureRegistry
from mrds.dashboard.data import DashboardData
from mrds.datasets.loader import DEFAULT_DATASETS_DIR
from mrds.datasets.registry import DatasetRegistry
from mrds.db import EvaluationStore, open_database
from mrds.evaluation import EvaluationConfig, EvaluationEngine
from mrds.features.ticket_router import (
    TicketCategory,
    TicketPriority,
    TicketRouterFeature,
    TicketRoutingOutput,
)
from mrds.features.ticket_router.scorers import CategoryMatchScorer, PriorityMatchScorer
from mrds.llm.base import LLMMessage, LLMResult
from mrds.prompts.loader import DEFAULT_PROMPTS_DIR
from mrds.prompts.registry import PromptRegistry


class _StubClient:
    """Deterministic offline client: routes from an oracle, misclassifies a wrong set."""

    def __init__(self, oracle: dict[str, tuple[str, str]], wrong: frozenset[str]) -> None:
        self._oracle = oracle
        self._wrong = wrong

    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type
    ) -> LLMResult[TicketRoutingOutput]:
        text = messages[-1].content
        category, priority = self._oracle.get(
            text, (TicketCategory.FEATURE_REQUEST.value, TicketPriority.LOW.value)
        )
        if text in self._wrong:  # flip to a deterministic other category
            order = [c.value for c in TicketCategory]
            category = order[(order.index(category) + 1) % len(order)]
        return LLMResult(
            parsed=TicketRoutingOutput(
                category=TicketCategory(category), priority=TicketPriority(priority)
            ),
            model=model,
            input_tokens=10,
            output_tokens=4,
            total_tokens=14,
        )


def _datasets() -> DatasetRegistry:
    # Default (registry-based) resolver — the datasets dir is multi-feature.
    return DatasetRegistry.from_directory(DEFAULT_DATASETS_DIR)


def _run(wrong: frozenset[str]) -> object:
    prompts = PromptRegistry.from_directory(DEFAULT_PROMPTS_DIR)
    datasets = _datasets()
    cases = list(datasets.get_latest("ticket_router").definition.cases)
    oracle = {
        c.input.ticket_text: (c.expected_output.category.value, c.expected_output.priority.value)
        for c in cases
    }
    feature = TicketRouterFeature(client=_StubClient(oracle, wrong), prompt_registry=prompts)
    registry = FeatureRegistry()
    registry.register(feature)
    engine = EvaluationEngine(features=registry, prompts=prompts, datasets=datasets)
    return engine.run(EvaluationConfig(feature="ticket_router", segment_field="category"))


# -- scorers --------------------------------------------------------------------


def _out(category: str, priority: str) -> TicketRoutingOutput:
    return TicketRoutingOutput(category=TicketCategory(category), priority=TicketPriority(priority))


def test_category_scorer_exact_match() -> None:
    scorer = CategoryMatchScorer()
    assert scorer.score(_out("billing", "high"), _out("billing", "high")).passed
    miss = scorer.score(_out("billing", "high"), _out("technical_support", "high"))
    assert not miss.passed
    assert "expected 'technical_support', got 'billing'" in miss.detail


def test_priority_scorer_exact_match() -> None:
    scorer = PriorityMatchScorer()
    assert scorer.score(_out("billing", "low"), _out("billing", "low")).passed
    assert not scorer.score(_out("billing", "low"), _out("billing", "high")).passed


# -- end-to-end through the core pipeline ---------------------------------------


def test_perfect_run_scores_100_percent() -> None:
    result = _run(frozenset())
    metrics = result.aggregate_metrics
    assert metrics.total_cases == 20
    assert metrics.pass_rate == pytest.approx(1.0)
    # Both scorers are discovered and aggregated generically.
    assert set(metrics.scorers) == {"category_match", "priority_match"}
    # Segmented by the configured field, with no hardcoding in the engine.
    assert metrics.segment_field == "category"
    assert set(metrics.segments) == {c.value for c in TicketCategory}


def test_dashboard_sees_feature_runs_metrics_and_regression() -> None:
    store = EvaluationStore(open_database(":memory:"))

    good = _run(frozenset())
    store.save_evaluation(good, triggered_by="test")
    store.promote_baseline(good.run_id, promoted_by="test", note="baseline")

    # Degrade the last 7 cases -> a real quality drop vs the baseline.
    cases = list(_datasets().get_latest("ticket_router").definition.cases)
    wrong = frozenset(c.input.ticket_text for c in cases[-7:])
    bad = _run(wrong)
    store.save_evaluation(bad, triggered_by="test")

    from mrds.regression import RegressionDetector

    regression = RegressionDetector().compare(good, bad)
    store.save_regression(regression)

    data = DashboardData(store)
    # Dashboard shows the new feature alongside any others.
    assert "ticket_router" in data.features()
    # Runs appear, newest first.
    assert {r.run_uuid for r in data.runs("ticket_router")} == {good.run_id, bad.run_id}
    # Metrics reconstruct.
    detail = data.run_detail(bad.run_id)
    assert detail is not None
    assert detail.aggregate_metrics.pass_rate == pytest.approx(13 / 20)
    # Regression detection works for the new feature.
    regs = data.regressions_for_run(bad.run_id)
    assert regs
    assert any("category_match" in r.metric or r.metric == "pass_rate" for r in regs)
