"""Tests for deterministic, offline demo-data seeding."""

from __future__ import annotations

import pytest

from mrds.db import EvaluationStore, open_database
from mrds.demo import DemoConfig, DeterministicEmailClient, seed_demo
from mrds.demo.generator import DEFAULT_RUNS
from mrds.features.email_classifier import EmailCategory, EmailClassificationOutput
from mrds.llm.base import LLMMessage

# Offline + fast: no simulated latency sleeps in tests.
TEST_CONFIG = DemoConfig(simulate_latency=False)


@pytest.fixture
def store() -> EvaluationStore:
    return EvaluationStore(open_database(":memory:"))


# -- deterministic client -------------------------------------------------------


def _ask(client: DeterministicEmailClient, text: str) -> EmailClassificationOutput:
    messages = [LLMMessage(role="user", content=text)]
    result = client.parse_structured(model="m", messages=messages, schema=EmailClassificationOutput)
    return result.parsed


def test_client_classifies_via_oracle_and_misclassifies_wrong_set() -> None:
    oracle = {"a": "billing", "b": "technical"}
    client = DeterministicEmailClient(
        oracle=oracle, wrong_texts=frozenset({"b"}), summary="A demo summary line here."
    )
    assert _ask(client, "a").category is EmailCategory.BILLING  # correct
    assert _ask(client, "b").category is not EmailCategory.TECHNICAL  # deliberately wrong
    # Deterministic across calls.
    assert _ask(client, "b").category == _ask(client, "b").category


def test_client_token_scale_is_deterministic() -> None:
    oracle = {"hello world": "general"}
    base = DeterministicEmailClient(oracle=oracle, wrong_texts=frozenset(), summary="x y z w")
    scaled = DeterministicEmailClient(
        oracle=oracle, wrong_texts=frozenset(), summary="x y z w", token_scale=2.0
    )
    r1 = base.parse_structured(
        model="m", messages=[LLMMessage(role="user", content="hello world")], schema=object
    )
    r2 = scaled.parse_structured(
        model="m", messages=[LLMMessage(role="user", content="hello world")], schema=object
    )
    assert r2.total_tokens == 2 * r1.total_tokens
    assert r1.total_tokens > 0


# -- seeding --------------------------------------------------------------------


def test_seed_creates_full_narrative(store: EvaluationStore) -> None:
    result = seed_demo(store, config=TEST_CONFIG)
    assert result.seeded is True
    assert len(result.run_ids) == len(DEFAULT_RUNS)
    # The demo now seeds a second feature (ticket_router) additively; features() is sorted.
    assert store.runs.features() == ["email_classifier", "ticket_router"]
    # A promoted baseline exists.
    assert result.baseline_run_id is not None
    assert store.baselines.get_active("email_classifier") is not None
    # Multiple historical runs.
    assert len(store.runs.list_for_feature("email_classifier")) == len(DEFAULT_RUNS)


def test_seed_produces_warning_and_critical_regressions(store: EvaluationStore) -> None:
    result = seed_demo(store, config=TEST_CONFIG)

    assert result.warning_run_ids and result.critical_run_ids

    warning_run = store.runs.get_by_uuid(result.warning_run_ids[0])
    warning_regs = store.regressions.list_for_run(warning_run.id)
    assert warning_regs
    assert any(r.severity == "warning" for r in warning_regs)
    # The warning run regressed on tokens (not accuracy).
    assert any(r.metric.startswith("tokens.") for r in warning_regs)

    critical_run = store.runs.get_by_uuid(result.critical_run_ids[0])
    critical_regs = store.regressions.list_for_run(critical_run.id)
    assert any(r.severity == "critical" for r in critical_regs)
    # The critical run regressed on classification quality.
    assert any("category_match" in r.metric or r.metric == "pass_rate" for r in critical_regs)


def test_seed_is_idempotent(store: EvaluationStore) -> None:
    first = seed_demo(store, config=TEST_CONFIG)
    count_after_first = len(store.runs.list_for_feature("email_classifier"))
    second = seed_demo(store, config=TEST_CONFIG)
    assert first.seeded is True
    assert second.seeded is False
    assert len(store.runs.list_for_feature("email_classifier")) == count_after_first


def test_seed_metrics_are_deterministic() -> None:
    """Two independent seedings produce identical content metrics (ids differ)."""
    store_a = EvaluationStore(open_database(":memory:"))
    store_b = EvaluationStore(open_database(":memory:"))
    res_a = seed_demo(store_a, config=TEST_CONFIG)
    res_b = seed_demo(store_b, config=TEST_CONFIG)

    crit_a = store_a.get_evaluation_result(res_a.critical_run_ids[0])
    crit_b = store_b.get_evaluation_result(res_b.critical_run_ids[0])
    assert crit_a is not None and crit_b is not None

    metrics_a = crit_a.aggregate_metrics
    metrics_b = crit_b.aggregate_metrics
    assert metrics_a.pass_rate == metrics_b.pass_rate
    assert (
        metrics_a.scorers["category_match"].mean_score
        == metrics_b.scorers["category_match"].mean_score
    )
    assert metrics_a.tokens.total_tokens == metrics_b.tokens.total_tokens
    assert set(metrics_a.segments) == set(metrics_b.segments)


def test_seed_covers_all_categories(store: EvaluationStore) -> None:
    # Full dataset => all four categories appear as segments.
    result = seed_demo(store, config=TEST_CONFIG)
    baseline = store.get_evaluation_result(result.baseline_run_id)
    assert set(baseline.aggregate_metrics.segments) == {c.value for c in EmailCategory}
